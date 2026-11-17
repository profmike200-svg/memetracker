"""Recolector periódico: mercado, holders, seguridad, velas y eventos."""
import json
import logging
import threading
import time
import traceback

import analysis
from sources import Sources, norm_addr

log = logging.getLogger("collector")


class Collector:
    def __init__(self, db, cfg):
        self.db = db
        self.cfg = cfg
        self.src = Sources(cfg)
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.status = {"last_cycle": None, "last_error": None, "running": False}
        self.lock = threading.RLock()

    # ------------------------------------------------------------ alta de tokens
    def resolve(self, address, chain=None):
        """Busca el token en DexScreener y devuelve sus metadatos (detecta la cadena)."""
        address = address.strip()
        pairs = self.src.dex_pairs([address])
        best, allp = self.src.best_pair(pairs, address, chain)
        if not best:
            return None
        meta = self.src.meta_from_pair(best)
        base = best.get("baseToken") or {}
        meta["address"] = norm_addr(meta["chain"], base.get("address") or address)
        return meta

    def add(self, address, chain=None):
        meta = self.resolve(address, chain)
        if not meta:
            raise ValueError("No encuentro ese token en DexScreener. ¿Está bien la dirección? "
                             "Tiene que tener al menos un par con liquidez.")
        tid, created = self.db.add_token(meta)
        self.refresh(tid, full=True)
        return tid, created

    # ------------------------------------------------------------ bucle
    def run(self):
        self.status["running"] = True
        while not self.stop.is_set():
            try:
                self.cycle()
                self.status["last_error"] = None
            except Exception as e:  # nunca matar el hilo
                self.status["last_error"] = f"{type(e).__name__}: {e}"
                log.error("Error en ciclo: %s\n%s", e, traceback.format_exc())
            self.status["last_cycle"] = int(time.time())
            self.wake.wait(timeout=30)
            self.wake.clear()

    def cycle(self):
        with self.lock:
            self._cycle()

    def _cycle(self):
        now = int(time.time())
        toks = self.db.tokens()
        due_market = [t for t in toks if now - (t["last_market_ts"] or 0) >= self.cfg["market_interval_sec"]]
        if due_market:
            self._market(due_market)
        for t in self.db.tokens():
            if now - (t["last_ohlcv_ts"] or 0) >= self.cfg["ohlcv_interval_sec"]:
                self._safe(self._ohlcv, t)

    def refresh(self, tid, full=False):
        with self.lock:
            t = self.db.token(tid)
            if full:
                self.db.update_token(tid, last_info_ts=0)
                t = self.db.token(tid)
            self._market([t])
            self._safe(self._ohlcv, self.db.token(tid))

    def _safe(self, fn, *a):
        try:
            return fn(*a)
        except Exception as e:
            log.warning("%s falló: %s", fn.__name__, e)
            self.status["last_error"] = f"{fn.__name__}: {e}"

    # ------------------------------------------------------------ mercado + holders
    def _market(self, toks):
        now = int(time.time())
        pairs = self.src.dex_pairs([t["address"] for t in toks])
        for t in toks:
            best, allp = self.src.best_pair(pairs, t["address"], t["chain"])
            if not best:
                log.info("Sin datos de mercado para %s", t["symbol"])
                continue
            snap = self.src.market_from_pair(best, allp)
            m = self.src.meta_from_pair(best)
            upd = {"last_market_ts": now, "pair_address": m["pair_address"], "dex": m["dex"],
                   "pair_url": m["pair_url"], "meta_json": json.dumps(m["meta"])}
            if m.get("image_url"):
                upd["image_url"] = m["image_url"]
            self.db.update_token(t["id"], **upd)

            if now - (t["last_info_ts"] or 0) >= self.cfg["info_interval_sec"]:
                extra = self._safe(self._info, t)
                if extra:
                    snap.update(extra)
                self.db.update_token(t["id"], last_info_ts=now)

            prev_sec = self.db.last_value(t["id"], "security_score")
            self.db.add_snapshot(t["id"], now, snap)
            self._live_events(t, now, snap, prev_sec)

    def _info(self, t):
        chain, addr = t["chain"], t["address"]
        info = self._safe(self.src.gt_token_info, chain, addr) or {}
        sec = None
        if chain == "solana":
            sec = self._safe(self.src.rugcheck, addr)
        else:
            sec = self._safe(self.src.goplus, chain, addr)
        be = self._safe(self.src.birdeye_overview, chain, addr)
        holders = ((be or {}).get("holders") or info.get("holders") or (sec or {}).get("holders"))
        top10 = info.get("top10_pct") if info.get("top10_pct") is not None else (sec or {}).get("top10_pct")
        if sec is not None and (sec.get("top10_pct") is None or info.get("top10_pct") is not None):
            sec["top10_pct"] = top10  # GeckoTerminal excluye pools/burn; preferimos su cifra
        old = self.db.get_info(t["id"])
        self.db.set_info(t["id"], {"gt": info or old.get("gt") or {}, "security": sec or old.get("security"),
                                   "birdeye": be or old.get("birdeye")})
        return {"holders": int(holders) if holders else None, "top10_pct": top10,
                "security_score": (sec or {}).get("score_norm")}

    # ------------------------------------------------------------ velas
    def _ohlcv(self, t):
        if not t["pair_address"]:
            return
        first = not t["last_ohlcv_ts"]
        for tf, lim_first, lim in (("h1", 1000, 60), ("m15", 1000, 100), ("d1", 365, 10)):
            candles = self._safe(self.src.gt_ohlcv, t["chain"], t["pair_address"], tf, lim_first if first else lim)
            if candles:
                self.db.upsert_ohlcv(t["id"], tf, candles)
        self.db.update_token(t["id"], last_ohlcv_ts=int(time.time()))
        self.detect_moves(t["id"])

    def detect_moves(self, tid):
        """Registra como eventos los tramos de subida/bajada confirmados en velas de 1h."""
        candles = self.db.ohlcv(tid, "h1", limit=100000)
        th = self.cfg["move_threshold_pct"] / 100
        legs, _ = analysis.zigzag(candles, th)
        for leg in legs:
            up = leg["direction"] == "up"
            self.db.add_event(tid, {
                "ts": leg["end_ts"], "kind": "move", "direction": leg["direction"], "pct": leg["pct"],
                "price_from": leg["price_from"], "price_to": leg["price_to"], "start_ts": leg["start_ts"],
                "message": f"{'Subida' if up else 'Bajada'} de {leg['pct']:+.1f}% en {leg['hours']:g} h",
            })

    # ------------------------------------------------------------ alertas en vivo
    def _ev(self, t, now, kind, cooldown, **ev):
        if self.db.recent_event(t["id"], kind, now - cooldown):
            return
        ev.update(ts=now, kind=kind, start_ts=now)
        self.db.add_event(t["id"], ev)

    def _live_events(self, t, now, s, psc):
        c = self.cfg
        p = s.get("price_usd")
        ch1 = s.get("change_h1")
        if ch1 is not None and ch1 >= c["live_move_pct"]:
            self._ev(t, now, "pump", 3600, direction="up", pct=ch1, price_to=p,
                     message=f"Pump en curso: {ch1:+.1f}% en la última hora")
        if ch1 is not None and ch1 <= -c["live_move_pct"]:
            self._ev(t, now, "dump", 3600, direction="down", pct=ch1, price_to=p,
                     message=f"Caída fuerte en curso: {ch1:+.1f}% en la última hora")

        ref = self.db.snapshot_before(t["id"], now - 3000)
        if ref and ref.get("liquidity_usd") and s.get("liquidity_usd") is not None:
            d = analysis.pct(ref["liquidity_usd"], s["liquidity_usd"])
            if d is not None and d <= -c["liquidity_drop_pct"]:
                self._ev(t, now, "liquidity", 3 * 3600, direction="down", pct=d,
                         message=f"La liquidez cae {d:.1f}% (${ref['liquidity_usd']:,.0f} → "
                                 f"${s['liquidity_usd']:,.0f}). Posible retirada de liquidez")

        if s.get("holders"):
            old = self.db.one("SELECT holders FROM snapshots WHERE token_id=? AND holders IS NOT NULL "
                              "AND ts<=? ORDER BY ts DESC LIMIT 1", (t["id"], now - 20 * 3600))
            if old and old["holders"]:
                d = analysis.pct(old["holders"], s["holders"])
                if d is not None and abs(d) >= c["holders_change_pct"]:
                    self._ev(t, now, "holders", 12 * 3600, direction="up" if d > 0 else "down", pct=d,
                             message=f"Holders {d:+.1f}% en ~24 h ({old['holders']:,} → {s['holders']:,})")

        if p:
            hi = self.db.one("SELECT MAX(h) AS m FROM ohlcv WHERE token_id=? AND tf='h1' AND ts<?",
                             (t["id"], now - 3600))
            mx = max(filter(None, [(hi or {}).get("m"),
                                   (self.db.one("SELECT MAX(price_usd) AS m FROM snapshots WHERE token_id=? "
                                                "AND ts<?", (t["id"], now)) or {}).get("m")]), default=None)
            if mx and p > mx * 1.01:
                self._ev(t, now, "ath", 6 * 3600, direction="up", price_from=mx, price_to=p,
                         pct=analysis.pct(mx, p), message="Nuevo máximo histórico")

        sc = s.get("security_score")
        if sc is not None and psc and psc["v"] is not None and sc - psc["v"] >= 20:
            self._ev(t, now, "security", 6 * 3600, direction="down", pct=None,
                     message=f"El riesgo de seguridad sube de {psc['v']:.0f} a {sc:.0f}/100")

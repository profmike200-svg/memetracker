"""Memetracker: servidor web local. Arranca con:  python server.py"""
import csv
import io
import json
import logging
import os
import re
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import analysis
from collector import Collector
from db import DB

ROOT = os.path.dirname(os.path.abspath(__file__))
DEFAULTS = {
    "port": 8787,
    "db_path": "memetracker.db",
    "market_interval_sec": 300,
    "info_interval_sec": 1800,
    "ohlcv_interval_sec": 900,
    "move_threshold_pct": 20,
    "live_move_pct": 25,
    "liquidity_drop_pct": 25,
    "holders_change_pct": 10,
    "timezone": "Europe/Madrid",
    "birdeye_api_key": "",
    "open_browser": True,
    "base_urls": {},
}


def load_config():
    cfg = dict(DEFAULTS)
    path = os.environ.get("MEMETRACKER_CONFIG", os.path.join(ROOT, "config.json"))
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            cfg.update(json.load(f))
    if os.environ.get("BIRDEYE_API_KEY"):
        cfg["birdeye_api_key"] = os.environ["BIRDEYE_API_KEY"]
    if not os.path.isabs(cfg["db_path"]):
        cfg["db_path"] = os.path.join(ROOT, cfg["db_path"])
    return cfg


CFG = load_config()
DBI = DB(CFG["db_path"])
COL = Collector(DBI, CFG)


def token_view(t):
    t = dict(t)
    t["meta"] = json.loads(t.pop("meta_json") or "{}")
    return t


def summary(t):
    tid = t["id"]
    s = DBI.last_snapshot(tid) or {}
    first = DBI.one("SELECT price_usd, market_cap, ts FROM snapshots WHERE token_id=? AND price_usd IS NOT NULL "
                    "ORDER BY ts LIMIT 1", (tid,)) or {}
    hold = DBI.last_value(tid, "holders")
    candles = DBI.ohlcv(tid, "h1", 200)
    spark = [c["c"] for c in candles[-48:]]
    ta = analysis.technical(candles) if candles else {"ok": False}
    last_ev = DBI.one("SELECT * FROM events WHERE token_id=? ORDER BY ts DESC LIMIT 1", (tid,))
    _, cur = analysis.zigzag(candles, CFG["move_threshold_pct"] / 100) if candles else ([], None)
    return {
        **token_view(t),
        "snap": s,
        "holders": hold["v"] if hold else None,
        "since_added_pct": analysis.pct(first.get("price_usd"), s.get("price_usd")),
        "price_at_add": first.get("price_usd"),
        "spark": spark,
        "trend": ta.get("trend"),
        "rsi": ta.get("rsi"),
        "drawdown_from_ath": ta.get("drawdown_from_ath"),
        "last_event": last_ev,
        "current_leg": cur,
        "sentiment": analysis.sentiment(s),
    }


def detail(tid, tf):
    t = DBI.token(tid)
    if not t:
        return None
    tv = token_view(t)
    s = DBI.last_snapshot(tid)
    info = DBI.get_info(tid)
    sec = info.get("security")
    candles = DBI.ohlcv(tid, tf, 1500)
    ta = analysis.technical(candles)
    h1 = DBI.ohlcv(tid, "h1", 100000)
    legs, cur = analysis.zigzag(h1, CFG["move_threshold_pct"] / 100)
    nar = analysis.narrative(tv, info.get("gt") or {}, sec)
    h_old = DBI.one("SELECT holders FROM snapshots WHERE token_id=? AND holders IS NOT NULL AND ts<=? "
                    "ORDER BY ts DESC LIMIT 1", (tid, int(time.time()) - 20 * 3600))
    h_now = DBI.last_value(tid, "holders")
    htrend = analysis.pct(h_old["holders"], h_now["v"]) if h_old and h_now else None
    if sec is not None and sec.get("top10_pct") is None:
        sec["top10_pct"] = (info.get("gt") or {}).get("top10_pct")
    return {
        "token": tv,
        "snap": s,
        "info": info.get("gt") or {},
        "security": sec,
        "birdeye": info.get("birdeye"),
        "holders": h_now["v"] if h_now else None,
        "holders_trend_24h": htrend,
        "candles": candles,
        "ta": ta,
        "legs": legs[-50:],
        "current_leg": cur,
        "narrative": nar,
        "sentiment": analysis.sentiment(s),
        "health": analysis.health(s, sec or {"top10_pct": (info.get("gt") or {}).get("top10_pct")}, nar, htrend),
        "config": {"move_threshold_pct": CFG["move_threshold_pct"], "timezone": CFG["timezone"]},
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "memetracker"

    def log_message(self, fmt, *a):
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
        if not isinstance(body, (bytes, bytearray)):
            body = json.dumps(body, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json_body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def _static(self, path):
        if path == "/":
            path = "/index.html"
        fp = os.path.normpath(os.path.join(ROOT, "static", path.lstrip("/")))
        if not fp.startswith(os.path.join(ROOT, "static")) or not os.path.isfile(fp):
            return self._send(404, {"error": "no encontrado"})
        ctype = {".html": "text/html", ".js": "text/javascript", ".css": "text/css",
                 ".svg": "image/svg+xml"}.get(os.path.splitext(fp)[1], "application/octet-stream")
        with open(fp, "rb") as f:
            self._send(200, f.read(), ctype + "; charset=utf-8")

    def do_GET(self):
        u = urlparse(self.path)
        qs = parse_qs(u.query)
        p = u.path
        try:
            if p == "/api/tokens":
                return self._send(200, [summary(t) for t in DBI.tokens()])
            if p == "/api/status":
                return self._send(200, {**COL.status, "tokens": len(DBI.tokens()),
                                        "intervals": {k: CFG[k] for k in CFG if k.endswith("_sec")},
                                        "timezone": CFG["timezone"]})
            if p == "/api/events":
                return self._send(200, DBI.events(None, int(qs.get("limit", ["300"])[0])))
            m = re.fullmatch(r"/api/tokens/(\d+)(/[a-z.]+)?", p)
            if m:
                tid, sub = int(m.group(1)), m.group(2)
                if not DBI.token(tid):
                    return self._send(404, {"error": "token no encontrado"})
                if sub is None:
                    return self._send(200, detail(tid, qs.get("tf", ["h1"])[0]))
                if sub == "/snapshots":
                    since = int(qs.get("since", ["0"])[0])
                    return self._send(200, DBI.snapshots(tid, since))
                if sub == "/events":
                    return self._send(200, DBI.events(tid))
                if sub == "/export.csv":
                    rows = DBI.snapshots(tid)
                    buf = io.StringIO()
                    if rows:
                        w = csv.DictWriter(buf, fieldnames=list(rows[0].keys()))
                        w.writeheader()
                        w.writerows(rows)
                    t = DBI.token(tid)
                    return self._send(200, buf.getvalue().encode("utf-8-sig"), "text/csv; charset=utf-8",
                                      {"Content-Disposition": f'attachment; filename="{t["symbol"]}_historico.csv"'})
            if p.startswith("/api/"):
                return self._send(404, {"error": "ruta desconocida"})
            return self._static(p)
        except Exception as e:
            logging.exception("GET %s", p)
            return self._send(500, {"error": str(e)})

    def do_POST(self):
        p = urlparse(self.path).path
        try:
            if p == "/api/tokens":
                b = self._json_body()
                addr = (b.get("address") or "").strip()
                if not addr:
                    return self._send(400, {"error": "Falta la dirección del token"})
                tid, created = COL.add(addr, b.get("chain") or None)
                if b.get("note"):
                    DBI.update_token(tid, note=b["note"])
                return self._send(201 if created else 200, {"id": tid, "created": created})
            m = re.fullmatch(r"/api/tokens/(\d+)/(refresh|note)", p)
            if m:
                tid = int(m.group(1))
                if m.group(2) == "refresh":
                    COL.refresh(tid, full=True)
                else:
                    DBI.update_token(tid, note=self._json_body().get("note", ""))
                return self._send(200, {"ok": True})
            return self._send(404, {"error": "ruta desconocida"})
        except ValueError as e:
            return self._send(400, {"error": str(e)})
        except Exception as e:
            logging.exception("POST %s", p)
            return self._send(502, {"error": f"Error consultando las APIs: {e}"})

    def do_DELETE(self):
        m = re.fullmatch(r"/api/tokens/(\d+)", urlparse(self.path).path)
        if not m:
            return self._send(404, {"error": "ruta desconocida"})
        DBI.delete_token(int(m.group(1)))
        self._send(200, {"ok": True})


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    th = threading.Thread(target=COL.run, daemon=True)
    th.start()
    srv = ThreadingHTTPServer(("127.0.0.1", CFG["port"]), Handler)
    url = f"http://localhost:{CFG['port']}"
    print(f"\n  Memetracker funcionando en {url}\n  (deja esta ventana abierta; Ctrl+C para parar)\n")
    if CFG.get("open_browser") and "--no-browser" not in sys.argv:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        COL.stop.set()
        COL.wake.set()


if __name__ == "__main__":
    main()

"""Clientes de las APIs públicas (DexScreener, GeckoTerminal, RugCheck, GoPlus, Birdeye opcional)."""
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "memetracker/1.0 (+local)"

# DexScreener chainId -> red de GeckoTerminal
GT_NETWORK = {
    "ethereum": "eth", "bsc": "bsc", "base": "base", "arbitrum": "arbitrum", "polygon": "polygon_pos",
    "avalanche": "avax", "optimism": "optimism", "solana": "solana", "sui": "sui-network", "ton": "ton",
    "tron": "tron", "blast": "blast", "linea": "linea", "fantom": "ftm", "cronos": "cro",
    "zksync": "zksync", "abstract": "abstract", "sonic": "sonic", "unichain": "unichain",
    "hyperevm": "hyperevm", "mantle": "mantle", "scroll": "scroll",
}
# DexScreener chainId -> chain id de GoPlus (EVM)
GOPLUS_CHAIN = {
    "ethereum": "1", "bsc": "56", "base": "8453", "arbitrum": "42161", "polygon": "137",
    "avalanche": "43114", "optimism": "10", "fantom": "250", "cronos": "25", "linea": "59144",
    "blast": "81457", "zksync": "324", "scroll": "534352", "mantle": "5000", "unichain": "130",
}
EVM_CHAINS = set(GOPLUS_CHAIN) | {"abstract", "sonic", "hyperevm"}


def norm_addr(chain, address):
    address = address.strip()
    return address.lower() if chain in EVM_CHAINS else address


def fnum(x):
    try:
        if x is None or x == "":
            return None
        return float(x)
    except (TypeError, ValueError):
        return None


class Http:
    """GET JSON con limitación de ritmo por host y reintentos en 429/5xx."""

    def __init__(self, min_interval):
        self.min_interval = min_interval  # {host: seconds}
        self.last = {}
        self.lock = threading.Lock()

    def _wait(self, host):
        gap = self.min_interval.get(host, 0.5)
        with self.lock:
            now = time.time()
            wait = self.last.get(host, 0) + gap - now
            self.last[host] = max(now, self.last.get(host, 0) + gap)
        if wait > 0:
            time.sleep(wait)

    def get(self, url, headers=None, retries=3):
        host = urllib.parse.urlparse(url).hostname or ""
        h = {"User-Agent": UA, "Accept": "application/json"}
        h.update(headers or {})
        for attempt in range(retries):
            self._wait(host)
            try:
                req = urllib.request.Request(url, headers=h)
                with urllib.request.urlopen(req, timeout=20) as r:
                    return json.loads(r.read().decode("utf-8"))
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return None
                if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                    time.sleep(3 * (attempt + 1) ** 2)
                    continue
                raise
            except (urllib.error.URLError, TimeoutError):
                if attempt < retries - 1:
                    time.sleep(2 * (attempt + 1))
                    continue
                raise


class Sources:
    def __init__(self, cfg):
        self.cfg = cfg
        b = cfg.get("base_urls", {})
        self.ds = b.get("dexscreener", "https://api.dexscreener.com")
        self.gt = b.get("geckoterminal", "https://api.geckoterminal.com/api/v2")
        self.rc = b.get("rugcheck", "https://api.rugcheck.xyz/v1")
        self.gp = b.get("goplus", "https://api.gopluslabs.io/api/v1")
        self.be = b.get("birdeye", "https://public-api.birdeye.so")
        host = lambda u: urllib.parse.urlparse(u).hostname
        self.http = Http({host(self.ds): 0.3, host(self.gt): 2.2, host(self.rc): 1.0,
                          host(self.gp): 1.0, host(self.be): 1.1})

    # ---------------------------------------------------------------- DexScreener
    def dex_pairs(self, addresses):
        """Pares de varios tokens (hasta 30 por llamada). Devuelve lista de pares."""
        pairs = []
        for i in range(0, len(addresses), 30):
            chunk = addresses[i:i + 30]
            data = self.http.get(f"{self.ds}/latest/dex/tokens/{','.join(chunk)}")
            pairs.extend((data or {}).get("pairs") or [])
        return pairs

    @staticmethod
    def best_pair(pairs, address, chain=None):
        """Par con más liquidez donde el token es la base."""
        a = address.lower()
        cands = [p for p in pairs if (p.get("baseToken") or {}).get("address", "").lower() == a
                 and (chain is None or p.get("chainId") == chain)]
        if not cands:
            cands = [p for p in pairs if (p.get("quoteToken") or {}).get("address", "").lower() == a
                     and (chain is None or p.get("chainId") == chain)]
        if not cands:
            return None, []
        cands.sort(key=lambda p: fnum((p.get("liquidity") or {}).get("usd")) or 0, reverse=True)
        return cands[0], cands

    @staticmethod
    def market_from_pair(p, all_pairs):
        tx = p.get("txns") or {}
        vol = p.get("volume") or {}
        ch = p.get("priceChange") or {}
        liq_total = sum(fnum((x.get("liquidity") or {}).get("usd")) or 0 for x in all_pairs)
        vol24_total = sum(fnum((x.get("volume") or {}).get("h24")) or 0 for x in all_pairs)
        return {
            "price_usd": fnum(p.get("priceUsd")),
            "price_native": fnum(p.get("priceNative")),
            "market_cap": fnum(p.get("marketCap")) or fnum(p.get("fdv")),
            "fdv": fnum(p.get("fdv")),
            "liquidity_usd": liq_total or fnum((p.get("liquidity") or {}).get("usd")),
            "volume_m5": fnum(vol.get("m5")),
            "volume_h1": fnum(vol.get("h1")),
            "volume_h6": fnum(vol.get("h6")),
            "volume_h24": vol24_total or fnum(vol.get("h24")),
            "buys_h1": (tx.get("h1") or {}).get("buys"),
            "sells_h1": (tx.get("h1") or {}).get("sells"),
            "buys_h24": (tx.get("h24") or {}).get("buys"),
            "sells_h24": (tx.get("h24") or {}).get("sells"),
            "change_m5": fnum(ch.get("m5")),
            "change_h1": fnum(ch.get("h1")),
            "change_h6": fnum(ch.get("h6")),
            "change_h24": fnum(ch.get("h24")),
            "pair_count": len(all_pairs),
        }

    @staticmethod
    def meta_from_pair(p):
        info = p.get("info") or {}
        return {
            "chain": p.get("chainId"),
            "pair_address": p.get("pairAddress"),
            "dex": p.get("dexId"),
            "name": (p.get("baseToken") or {}).get("name"),
            "symbol": (p.get("baseToken") or {}).get("symbol"),
            "image_url": info.get("imageUrl"),
            "pair_url": p.get("url"),
            "pair_created_at": int((p.get("pairCreatedAt") or 0) / 1000) or None,
            "meta": {
                "websites": info.get("websites") or [],
                "socials": info.get("socials") or [],
                "boosts": (p.get("boosts") or {}).get("active", 0),
                "quote_symbol": (p.get("quoteToken") or {}).get("symbol"),
                "labels": p.get("labels") or [],
            },
        }

    # ---------------------------------------------------------------- GeckoTerminal
    def gt_ohlcv(self, chain, pool, tf, limit=1000):
        """tf: 'm15' | 'h1' | 'h4' | 'd1'. Devuelve velas ascendentes [ts,o,h,l,c,v]."""
        net = GT_NETWORK.get(chain, chain)
        period, agg = {"m5": ("minute", 5), "m15": ("minute", 15), "h1": ("hour", 1),
                       "h4": ("hour", 4), "d1": ("day", 1)}[tf]
        url = (f"{self.gt}/networks/{net}/pools/{pool}/ohlcv/{period}"
               f"?aggregate={agg}&limit={limit}&currency=usd&token=base")
        data = self.http.get(url)
        lst = (((data or {}).get("data") or {}).get("attributes") or {}).get("ohlcv_list") or []
        out = []
        for c in lst:
            vals = [fnum(v) for v in c[:6]]
            if None not in vals[:5]:
                out.append([int(vals[0])] + vals[1:5] + [vals[5] or 0.0])
        out.sort(key=lambda c: c[0])
        return out

    def gt_token_info(self, chain, address):
        net = GT_NETWORK.get(chain, chain)
        data = self.http.get(f"{self.gt}/networks/{net}/tokens/{address}/info")
        a = ((data or {}).get("data") or {}).get("attributes") or {}
        holders = a.get("holders") or {}
        dist = holders.get("distribution_percentage") or {}
        return {
            "description": a.get("description"),
            "websites": a.get("websites") or [],
            "twitter": a.get("twitter_handle"),
            "telegram": a.get("telegram_handle"),
            "discord": a.get("discord_url"),
            "gt_score": fnum(a.get("gt_score")),
            "categories": a.get("categories") or [],
            "holders": int(holders["count"]) if holders.get("count") not in (None, "") else None,
            "top10_pct": fnum(dist.get("top_10")),
            "distribution": dist,
            "image_url": a.get("image_url"),
        }

    # ---------------------------------------------------------------- Seguridad
    def rugcheck(self, mint):
        r = self.http.get(f"{self.rc}/tokens/{mint}/report")
        if not r:
            return None
        top = r.get("topHolders") or []
        top10 = sum(fnum(h.get("pct")) or 0 for h in top[:10]) if top else None
        risks = [{"name": x.get("name"), "level": x.get("level"), "description": x.get("description"),
                  "value": x.get("value")} for x in (r.get("risks") or [])]
        return {
            "source": "RugCheck",
            "score_norm": fnum(r.get("score_normalised")),  # 0 = sin riesgo, 100 = máximo riesgo
            "risks": risks,
            "holders": r.get("totalHolders"),
            "top10_pct": top10,
            "mint_authority": r.get("mintAuthority"),
            "freeze_authority": r.get("freezeAuthority"),
            "rugged": bool(r.get("rugged")),
            "lp_locked_pct": max([fnum((m.get("lp") or {}).get("lpLockedPct")) or 0
                                  for m in (r.get("markets") or [])] or [None]),
            "insiders_detected": r.get("graphInsidersDetected"),
            "creator_balance": r.get("creatorBalance"),
        }

    def goplus(self, chain, address):
        cid = GOPLUS_CHAIN.get(chain)
        if not cid:
            return None
        r = self.http.get(f"{self.gp}/token_security/{cid}?contract_addresses={address}")
        res = ((r or {}).get("result") or {})
        d = res.get(address.lower()) or (next(iter(res.values())) if res else None)
        if not d:
            return None
        flag = lambda k: str(d.get(k)) == "1"
        risks = []
        checks = [("is_honeypot", "Honeypot (no se puede vender)", "danger"),
                  ("cannot_sell_all", "No se puede vender todo", "danger"),
                  ("is_mintable", "Se pueden mintear más tokens", "warn"),
                  ("hidden_owner", "Owner oculto", "danger"),
                  ("can_take_back_ownership", "Puede recuperar ownership", "danger"),
                  ("owner_change_balance", "Owner puede cambiar balances", "danger"),
                  ("is_blacklisted", "Tiene blacklist", "warn"),
                  ("transfer_pausable", "Transferencias pausables", "warn"),
                  ("is_proxy", "Contrato proxy (actualizable)", "warn"),
                  ("slippage_modifiable", "Impuestos modificables", "warn"),
                  ("external_call", "Llamadas externas", "warn")]
        for k, label, level in checks:
            if flag(k):
                risks.append({"name": label, "level": level})
        if str(d.get("is_open_source")) == "0":
            risks.append({"name": "Contrato no verificado", "level": "danger"})
        bt, st = fnum(d.get("buy_tax")), fnum(d.get("sell_tax"))
        if (bt or 0) > 0.1 or (st or 0) > 0.1:
            risks.append({"name": f"Impuestos altos (compra {bt:.0%} / venta {st:.0%})", "level": "danger"})
        holders = d.get("holders") or []
        top10 = sum((fnum(h.get("percent")) or 0) for h in holders[:10]) * 100 if holders else None
        lp_locked = sum((fnum(h.get("percent")) or 0) for h in (d.get("lp_holders") or [])
                        if str(h.get("is_locked")) == "1") * 100
        score = min(100, sum(30 if r["level"] == "danger" else 10 for r in risks))
        return {
            "source": "GoPlus",
            "score_norm": score,
            "risks": risks,
            "holders": int(d["holder_count"]) if d.get("holder_count") else None,
            "top10_pct": top10,
            "buy_tax": bt, "sell_tax": st,
            "owner": d.get("owner_address"),
            "creator_pct": (fnum(d.get("creator_percent")) or 0) * 100,
            "lp_locked_pct": lp_locked,
        }

    def birdeye_overview(self, chain, address):
        key = self.cfg.get("birdeye_api_key")
        if not key:
            return None
        r = self.http.get(f"{self.be}/defi/token_overview?address={address}",
                          headers={"X-API-KEY": key, "x-chain": chain})
        d = (r or {}).get("data") or {}
        if not d:
            return None
        return {"holders": d.get("holder"), "unique_wallets_24h": d.get("uniqueWallet24h"),
                "unique_wallets_24h_change": d.get("uniqueWallet24hChangePercent")}

"""Servidor que imita DexScreener/GeckoTerminal/RugCheck/GoPlus para probar sin internet.
Uso: python tests/mock_apis.py  (puerto 9999) y config con base_urls apuntando a él."""
import json
import math
import random
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

SOL = "7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr"
EVM = "0x6982508145454ce325ddbe47a25d4ec3d2311933"
TOKENS = {
    SOL.lower(): dict(chain="solana", addr=SOL, sym="WOOF", name="Woof Inu", pair="PoolSoL111", p0=0.00042, dex="raydium"),
    EVM: dict(chain="ethereum", addr=EVM, sym="PEPE2", name="Pepe Two AI", pair="0xpool000000000000000000000000000000000001", p0=0.0000123, dex="uniswap"),
}
NOW = int(time.time()) // 3600 * 3600


def candles(tok, tf, limit):
    random.seed(tok["sym"] + tf)
    step = {"m15": 900, "h1": 3600, "d1": 86400}[tf]
    n = min(limit, 1000 if tf != "d1" else 60)
    p = tok["p0"]
    out = []
    for i in range(n):
        ts = NOW - (n - 1 - i) * step
        drift = 0.0
        phase = (i // 60) % 4
        drift = [0.012, -0.01, 0.004, -0.006][phase] * (step / 3600) ** 0.5
        o = p
        c = max(1e-12, o * math.exp(drift + random.gauss(0, 0.03)))
        h = max(o, c) * (1 + abs(random.gauss(0, 0.015)))
        l = min(o, c) * (1 - abs(random.gauss(0, 0.015)))
        out.append([ts, o, h, l, c, random.uniform(2e4, 2e5)])
        p = c
    tok["last"] = p
    return list(reversed(out))


def pair(tok):
    p = tok.get("last") or tok["p0"]
    p *= 1 + random.uniform(-0.02, 0.02)
    return {
        "chainId": tok["chain"], "dexId": tok["dex"], "url": f"https://dexscreener.com/{tok['chain']}/{tok['pair']}",
        "pairAddress": tok["pair"],
        "baseToken": {"address": tok["addr"], "name": tok["name"], "symbol": tok["sym"]},
        "quoteToken": {"address": "So11111111111111111111111111111111111111112", "symbol": "SOL"},
        "priceNative": str(p / 150), "priceUsd": str(p),
        "txns": {"m5": {"buys": 12, "sells": 9}, "h1": {"buys": random.randint(80, 200), "sells": random.randint(60, 180)},
                 "h6": {"buys": 900, "sells": 800}, "h24": {"buys": 3400, "sells": 2900}},
        "volume": {"h24": 1.9e6, "h6": 5e5, "h1": random.uniform(5e4, 2e5), "m5": 9000},
        "priceChange": {"m5": 0.4, "h1": random.uniform(-8, 8), "h6": 12.5, "h24": -4.2},
        "liquidity": {"usd": random.uniform(3.9e5, 4.1e5), "base": 1, "quote": 1},
        "fdv": p * 1e9, "marketCap": p * 9.5e8, "pairCreatedAt": (NOW - 60 * 86400) * 1000,
        "info": {"imageUrl": "", "websites": [{"label": "Website", "url": "https://example.com"}],
                 "socials": [{"type": "twitter", "url": "https://x.com/example"}, {"type": "telegram", "url": "https://t.me/example"}]},
        "boosts": {"active": 10},
    }


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, obj, code=200):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        p = self.path
        m = re.match(r"/ds/latest/dex/tokens/([^?]+)", p)
        if m:
            pairs = [pair(TOKENS[a.lower()]) for a in m.group(1).split(",") if a.lower() in TOKENS]
            return self.send({"schemaVersion": "1.0.0", "pairs": pairs or None})
        m = re.match(r"/gt/networks/([^/]+)/pools/([^/]+)/ohlcv/(\w+)\?aggregate=(\d+)&limit=(\d+)", p)
        if m:
            tok = next(t for t in TOKENS.values() if t["pair"] == m.group(2))
            tf = {"minute": "m15", "hour": "h1", "day": "d1"}[m.group(3)]
            return self.send({"data": {"attributes": {"ohlcv_list": candles(tok, tf, int(m.group(5)))}}})
        m = re.match(r"/gt/networks/([^/]+)/tokens/([^/]+)/info", p)
        if m:
            tok = TOKENS[m.group(2).lower()]
            return self.send({"data": {"attributes": {
                "description": f"{tok['name']} is the most based dog meme coin with an AI agent community.",
                "twitter_handle": "example", "telegram_handle": "example", "gt_score": 61.5,
                "categories": ["Meme"], "websites": ["https://example.com"],
                "holders": {"count": 12000 + int(time.time()) % 500,
                            "distribution_percentage": {"top_10": "18.4", "11_30": "9", "31_50": "5", "rest": "67.6"}}}}})
        m = re.match(r"/rc/tokens/([^/]+)/report", p)
        if m:
            return self.send({"score_normalised": 12, "rugged": False, "totalHolders": 11950,
                              "mintAuthority": None, "freezeAuthority": None,
                              "risks": [{"name": "Low amount of LP Providers", "level": "warn",
                                         "description": "Only a few users are providing liquidity"}],
                              "topHolders": [{"pct": 2.1}] * 10,
                              "markets": [{"lp": {"lpLockedPct": 100}}]})
        m = re.match(r"/gp/token_security/(\d+)\?contract_addresses=(.+)", p)
        if m:
            a = m.group(2).lower()
            return self.send({"code": 1, "result": {a: {
                "holder_count": "54321", "is_honeypot": "0", "is_open_source": "1", "is_mintable": "0",
                "buy_tax": "0", "sell_tax": "0.01", "is_proxy": "0", "creator_percent": "0.02",
                "holders": [{"percent": "0.05"}] * 10,
                "lp_holders": [{"percent": "0.95", "is_locked": "1"}]}}})
        self.send({"error": "not found"}, 404)


if __name__ == "__main__":
    print("mock en :9999")
    ThreadingHTTPServer(("127.0.0.1", 9999), H).serve_forever()

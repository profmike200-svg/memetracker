"""Análisis técnico, detección de subidas/bajadas, narrativa y puntuación."""
import math
import re


# ------------------------------------------------------------------ indicadores
def ema(vals, n):
    out, k, e = [], 2 / (n + 1), None
    for v in vals:
        e = v if e is None else v * k + e * (1 - k)
        out.append(e)
    return out


def sma(vals, n):
    out, s = [], 0.0
    for i, v in enumerate(vals):
        s += v
        if i >= n:
            s -= vals[i - n]
        out.append(s / n if i >= n - 1 else None)
    return out


def rsi(closes, n=14):
    out = [None] * len(closes)
    if len(closes) <= n:
        return out
    gains = [max(closes[i] - closes[i - 1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i - 1] - closes[i], 0) for i in range(1, len(closes))]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    out[n] = 100 if al == 0 else 100 - 100 / (1 + ag / al)
    for i in range(n + 1, len(closes)):
        ag = (ag * (n - 1) + gains[i - 1]) / n
        al = (al * (n - 1) + losses[i - 1]) / n
        out[i] = 100 if al == 0 else 100 - 100 / (1 + ag / al)
    return out


def macd(closes, f=12, s=26, sig=9):
    ef, es = ema(closes, f), ema(closes, s)
    line = [a - b for a, b in zip(ef, es)]
    signal = ema(line, sig)
    hist = [a - b for a, b in zip(line, signal)]
    return line, signal, hist


def bollinger(closes, n=20, k=2):
    mid = sma(closes, n)
    up, lo = [], []
    for i, m in enumerate(mid):
        if m is None:
            up.append(None); lo.append(None); continue
        w = closes[i - n + 1:i + 1]
        sd = math.sqrt(sum((x - m) ** 2 for x in w) / n)
        up.append(m + k * sd); lo.append(m - k * sd)
    return up, mid, lo


def atr(candles, n=14):
    trs = []
    for i, c in enumerate(candles):
        if i == 0:
            trs.append(c["h"] - c["l"])
        else:
            pc = candles[i - 1]["c"]
            trs.append(max(c["h"] - c["l"], abs(c["h"] - pc), abs(c["l"] - pc)))
    return ema(trs, n)


def pct(a, b):
    if a in (None, 0) or b is None:
        return None
    return (b / a - 1) * 100


# ------------------------------------------------------------------ subidas / bajadas (zigzag)
def zigzag(candles, threshold=0.2):
    """Detecta tramos de subida/bajada >= threshold (0.2 = 20%).
    Devuelve (tramos_confirmados, tramo_en_curso)."""
    if len(candles) < 2:
        return [], None
    legs = []
    piv_ts, piv_p = candles[0]["ts"], candles[0]["c"]
    d, ext_ts, ext_p = 0, piv_ts, piv_p
    for c in candles[1:]:
        hi, lo, ts = c["h"], c["l"], c["ts"]
        if d == 0:
            if hi >= piv_p * (1 + threshold):
                d, ext_ts, ext_p = 1, ts, hi
            elif lo <= piv_p * (1 - threshold):
                d, ext_ts, ext_p = -1, ts, lo
        elif d == 1:
            if hi > ext_p:
                ext_ts, ext_p = ts, hi
            elif lo <= ext_p * (1 - threshold):
                legs.append(_leg("up", piv_ts, piv_p, ext_ts, ext_p))
                piv_ts, piv_p, d, ext_ts, ext_p = ext_ts, ext_p, -1, ts, lo
        else:
            if lo < ext_p:
                ext_ts, ext_p = ts, lo
            elif hi >= ext_p * (1 + threshold):
                legs.append(_leg("down", piv_ts, piv_p, ext_ts, ext_p))
                piv_ts, piv_p, d, ext_ts, ext_p = ext_ts, ext_p, 1, ts, hi
    current = None
    if d != 0:
        last = candles[-1]
        current = _leg("up" if d == 1 else "down", piv_ts, piv_p, ext_ts, ext_p)
        current["last_price"] = last["c"]
        current["pullback_pct"] = pct(ext_p, last["c"])
    return legs, current


def _leg(direction, t0, p0, t1, p1):
    return {"direction": direction, "start_ts": int(t0), "end_ts": int(t1),
            "price_from": p0, "price_to": p1, "pct": pct(p0, p1),
            "hours": round((t1 - t0) / 3600, 1)}


# ------------------------------------------------------------------ análisis técnico
def technical(candles):
    """candles: lista de dicts {ts,o,h,l,c,v} ascendente."""
    if len(candles) < 5:
        return {"ok": False, "reason": "Pocas velas todavía para análisis técnico"}
    closes = [c["c"] for c in candles]
    vols = [c["v"] for c in candles]
    e9, e21, e50, e200 = ema(closes, 9), ema(closes, 21), ema(closes, 50), ema(closes, 200)
    r = rsi(closes)
    ml, ms, mh = macd(closes)
    bu, bm, bl = bollinger(closes)
    a = atr(candles)
    last = closes[-1]
    n = len(candles)
    look = candles[-min(n, 48):]
    support = min(c["l"] for c in look)
    resistance = max(c["h"] for c in look)
    ath = max(c["h"] for c in candles)
    ath_ts = next(c["ts"] for c in candles if c["h"] == ath)
    atl = min(c["l"] for c in candles)
    vol_recent = sum(vols[-6:]) / max(1, len(vols[-6:]))
    vol_base = sum(vols[-54:-6]) / max(1, len(vols[-54:-6])) if n > 10 else None

    score = 0
    signals = []

    def sig(text, w, kind):
        nonlocal score
        score += w
        signals.append({"text": text, "kind": kind})

    if n >= 50:
        if last > e21[-1] > e50[-1]:
            sig("Precio por encima de EMA21 y EMA50 (estructura alcista)", 2, "bull")
        elif last < e21[-1] < e50[-1]:
            sig("Precio por debajo de EMA21 y EMA50 (estructura bajista)", -2, "bear")
        if e9[-1] > e21[-1] and e9[-2] <= e21[-2]:
            sig("Cruce alcista EMA9/EMA21 en la última vela", 1, "bull")
        if e9[-1] < e21[-1] and e9[-2] >= e21[-2]:
            sig("Cruce bajista EMA9/EMA21 en la última vela", -1, "bear")
    elif last > e21[-1]:
        sig("Precio por encima de EMA21", 1, "bull")
    else:
        sig("Precio por debajo de EMA21", -1, "bear")

    if r[-1] is not None:
        if r[-1] >= 75:
            sig(f"RSI {r[-1]:.0f}: sobrecompra, riesgo de corrección", -1, "warn")
        elif r[-1] <= 25:
            sig(f"RSI {r[-1]:.0f}: sobreventa, posible rebote", 1, "warn")
        elif r[-1] > 55:
            sig(f"RSI {r[-1]:.0f}: momentum positivo", 1, "bull")
        elif r[-1] < 45:
            sig(f"RSI {r[-1]:.0f}: momentum débil", -1, "bear")

    if n > 35:
        if mh[-1] > 0 and mh[-2] <= 0:
            sig("MACD cruza al alza su señal", 1, "bull")
        elif mh[-1] < 0 and mh[-2] >= 0:
            sig("MACD cruza a la baja su señal", -1, "bear")
        elif mh[-1] > 0:
            sig("MACD por encima de su señal", 0.5, "bull")
        else:
            sig("MACD por debajo de su señal", -0.5, "bear")

    if vol_base:
        vr = vol_recent / vol_base if vol_base else None
        if vr and vr > 2:
            sig(f"Volumen reciente x{vr:.1f} sobre la media", 0.5 if closes[-1] > closes[-6] else -0.5,
                "bull" if closes[-1] > closes[-6] else "bear")
        elif vr is not None and vr < 0.4:
            sig("Volumen apagándose (interés cayendo)", -1, "bear")

    if bu[-1] is not None:
        if last > bu[-1]:
            sig("Precio por encima de la banda alta de Bollinger (extendido)", 0, "warn")
        elif last < bl[-1]:
            sig("Precio por debajo de la banda baja de Bollinger", 0, "warn")

    dd = pct(ath, last)
    if dd is not None and dd < -80:
        sig(f"A {dd:.0f}% del máximo registrado", -1, "bear")

    if score >= 3:
        trend = "Alcista fuerte"
    elif score >= 1:
        trend = "Alcista"
    elif score <= -3:
        trend = "Bajista fuerte"
    elif score <= -1:
        trend = "Bajista"
    else:
        trend = "Lateral"

    return {
        "ok": True,
        "trend": trend,
        "score": round(score, 1),
        "signals": signals,
        "last": last,
        "rsi": r[-1],
        "macd_hist": mh[-1],
        "ema9": e9[-1], "ema21": e21[-1], "ema50": e50[-1] if n >= 50 else None,
        "ema200": e200[-1] if n >= 200 else None,
        "atr_pct": (a[-1] / last * 100) if last else None,
        "support": support, "resistance": resistance,
        "ath": ath, "ath_ts": ath_ts, "atl": atl,
        "drawdown_from_ath": dd,
        "series": {
            "ema9": e9, "ema21": e21, "ema50": e50, "rsi": r,
            "macd": ml, "macd_signal": ms, "macd_hist": mh, "bb_up": bu, "bb_low": bl,
        },
    }


# ------------------------------------------------------------------ narrativa
NARRATIVES = {
    "Perros": r"\b(dog|doge|shib|inu|puppy|pup|wif|bonk|floki|corgi|shiba|perro)\b",
    "Gatos": r"\b(cat|kitty|meow|popcat|mew|nyan|gato|kitten)\b",
    "Ranas / Pepe": r"\b(pepe|frog|toad|ribbit|kek)\b",
    "IA / Agentes": r"\b(ai|agent|gpt|llm|neural|bot|agi|virtual|autonomous|intelligence)\b",
    "Política": r"\b(trump|maga|biden|elon|president|vote|election|kamala|politic|usa|america)\b",
    "Celebridades / Influencers": r"\b(celebrity|influencer|streamer|kanye|drake|tate|mrbeast|rapper)\b",
    "Gaming": r"\b(game|gaming|play|arcade|nft|metaverse|esports)\b",
    "Comida": r"\b(pizza|burger|banana|taco|food|cheese|bread|coffee)\b",
    "Animales (otros)": r"\b(monkey|ape|penguin|bear|bull|hamster|goat|duck|fish|whale|moo|deng|hippo)\b",
    "Cultura de internet": r"\b(meme|chad|wojak|based|gm|wagmi|ngmi|degen|moon|lol|troll)\b",
    "DeFi / Utilidad": r"\b(staking|yield|swap|dex|bridge|protocol|utility|dao|launchpad)\b",
    "Religión / Mitos": r"\b(god|jesus|zeus|myth|church|holy|satoshi)\b",
}


def narrative(token, info, sec):
    text = " ".join(filter(None, [token.get("name"), token.get("symbol"), info.get("description"),
                                  " ".join(info.get("categories") or [])])).lower()
    tags = [k for k, rx in NARRATIVES.items() if re.search(rx, text)]
    meta = token.get("meta") or {}
    socials = {s.get("type"): s.get("url") for s in meta.get("socials") or []}
    if info.get("twitter") and "twitter" not in socials:
        socials["twitter"] = f"https://x.com/{info['twitter']}"
    if info.get("telegram") and "telegram" not in socials:
        socials["telegram"] = f"https://t.me/{info['telegram']}"
    websites = [w.get("url") if isinstance(w, dict) else w for w in (meta.get("websites") or [])] \
        or list(info.get("websites") or [])
    presence = sum([bool(socials.get("twitter")), bool(socials.get("telegram")), bool(websites),
                    bool(info.get("description"))])
    return {
        "tags": tags or ["Sin clasificar"],
        "description": info.get("description"),
        "socials": socials,
        "websites": websites,
        "boosts": meta.get("boosts") or 0,
        "categories": info.get("categories") or [],
        "presence_score": presence,  # 0-4
    }


def sentiment(s, prev24=None):
    """Sentimiento de mercado a partir del flujo de órdenes y la aceleración del volumen."""
    if not s:
        return None
    b1, s1 = s.get("buys_h1") or 0, s.get("sells_h1") or 0
    b24, s24 = s.get("buys_h24") or 0, s.get("sells_h24") or 0
    r1 = b1 / (b1 + s1) if b1 + s1 else 0.5
    r24 = b24 / (b24 + s24) if b24 + s24 else 0.5
    accel = None
    if s.get("volume_h1") is not None and s.get("volume_h24"):
        accel = s["volume_h1"] * 24 / s["volume_h24"]
    pts = (r1 - 0.5) * 4 + (r24 - 0.5) * 2
    ch1, ch24 = s.get("change_h1") or 0, s.get("change_h24") or 0
    pts += max(-1.5, min(1.5, ch1 / 15)) + max(-1.5, min(1.5, ch24 / 40))
    if accel:
        pts += 0.5 if accel > 1.5 and ch1 >= 0 else (-0.5 if accel > 1.5 else 0)
    label = ("Euforia" if pts >= 2.5 else "Positivo" if pts >= 0.8 else "Pánico" if pts <= -2.5
             else "Negativo" if pts <= -0.8 else "Neutral")
    return {"label": label, "score": round(pts, 2), "buy_ratio_h1": r1, "buy_ratio_h24": r24,
            "volume_accel": accel}


def health(s, sec, nar, holders_trend):
    """Puntuación 0-100 heurística de 'salud' del token (NO es consejo de inversión)."""
    if not s:
        return None
    parts = []
    liq, mc = s.get("liquidity_usd") or 0, s.get("market_cap") or 0
    lr = liq / mc if mc else 0
    parts.append(("Liquidez / market cap", min(20, lr * 200), 20,
                  f"{lr * 100:.1f}% (sano > 10%)"))
    turnover = (s.get("volume_h24") or 0) / liq if liq else 0
    parts.append(("Actividad (volumen 24h / liquidez)", min(15, turnover * 7.5), 15, f"x{turnover:.2f}"))
    if liq >= 500_000:
        lp = 15
    elif liq >= 100_000:
        lp = 10
    elif liq >= 25_000:
        lp = 5
    else:
        lp = 0
    parts.append(("Profundidad de liquidez", lp, 15, f"${liq:,.0f}"))
    if sec and sec.get("score_norm") is not None:
        sp = max(0, 25 - sec["score_norm"] / 4)
        parts.append(("Seguridad del contrato", sp, 25, f"riesgo {sec['score_norm']:.0f}/100 ({sec['source']})"))
    top10 = (sec or {}).get("top10_pct")
    if top10 is not None:
        parts.append(("Distribución de holders", max(0, 15 - max(0, top10 - 15) * 0.3), 15,
                      f"top 10 = {top10:.1f}%"))
    if holders_trend is not None:
        parts.append(("Crecimiento de holders", max(0, min(10, 5 + holders_trend)), 10,
                      f"{holders_trend:+.1f}%"))
    if nar:
        parts.append(("Presencia social", nar["presence_score"] * 2.5, 10, f"{nar['presence_score']}/4"))
    got = sum(p[1] for p in parts)
    total = sum(p[2] for p in parts)
    return {"score": round(got / total * 100) if total else None,
            "parts": [{"name": p[0], "pts": round(p[1], 1), "max": p[2], "detail": p[3]} for p in parts]}

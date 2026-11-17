"""Almacenamiento SQLite del histórico."""
import json
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    chain TEXT NOT NULL,
    address TEXT NOT NULL,
    pair_address TEXT,
    dex TEXT,
    name TEXT,
    symbol TEXT,
    image_url TEXT,
    pair_url TEXT,
    pair_created_at INTEGER,
    added_at INTEGER NOT NULL,
    note TEXT,
    meta_json TEXT,
    last_market_ts INTEGER DEFAULT 0,
    last_info_ts INTEGER DEFAULT 0,
    last_ohlcv_ts INTEGER DEFAULT 0,
    UNIQUE(chain, address)
);
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id INTEGER NOT NULL,
    ts INTEGER NOT NULL,
    price_usd REAL, price_native REAL, market_cap REAL, fdv REAL, liquidity_usd REAL,
    volume_m5 REAL, volume_h1 REAL, volume_h6 REAL, volume_h24 REAL,
    buys_h1 INTEGER, sells_h1 INTEGER, buys_h24 INTEGER, sells_h24 INTEGER,
    change_m5 REAL, change_h1 REAL, change_h6 REAL, change_h24 REAL,
    holders INTEGER, top10_pct REAL, security_score REAL, pair_count INTEGER
);
CREATE INDEX IF NOT EXISTS ix_snap ON snapshots(token_id, ts);
CREATE TABLE IF NOT EXISTS ohlcv (
    token_id INTEGER NOT NULL, tf TEXT NOT NULL, ts INTEGER NOT NULL,
    o REAL, h REAL, l REAL, c REAL, v REAL,
    PRIMARY KEY (token_id, tf, ts)
);
CREATE TABLE IF NOT EXISTS info (
    token_id INTEGER PRIMARY KEY, ts INTEGER, data_json TEXT
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_id INTEGER NOT NULL,
    ts INTEGER NOT NULL,
    kind TEXT NOT NULL,
    direction TEXT,
    pct REAL,
    price_from REAL,
    price_to REAL,
    start_ts INTEGER,
    message TEXT,
    UNIQUE(token_id, kind, start_ts)
);
CREATE INDEX IF NOT EXISTS ix_ev ON events(token_id, ts);
"""


class DB:
    def __init__(self, path):
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.executescript(SCHEMA)
            self.conn.commit()

    # -- helpers -----------------------------------------------------------
    def q(self, sql, args=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        rows = self.q(sql, args)
        return rows[0] if rows else None

    def x(self, sql, args=()):
        with self.lock:
            cur = self.conn.execute(sql, args)
            self.conn.commit()
            return cur

    def xmany(self, sql, rows):
        with self.lock:
            self.conn.executemany(sql, rows)
            self.conn.commit()

    # -- tokens ------------------------------------------------------------
    def add_token(self, t):
        cur = self.x(
            """INSERT OR IGNORE INTO tokens(chain,address,pair_address,dex,name,symbol,image_url,
               pair_url,pair_created_at,added_at,meta_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (t["chain"], t["address"], t.get("pair_address"), t.get("dex"), t.get("name"),
             t.get("symbol"), t.get("image_url"), t.get("pair_url"), t.get("pair_created_at"),
             int(time.time()), json.dumps(t.get("meta") or {})),
        )
        row = self.one("SELECT id FROM tokens WHERE chain=? AND address=?", (t["chain"], t["address"]))
        return row["id"], cur.rowcount > 0

    def tokens(self):
        return self.q("SELECT * FROM tokens ORDER BY added_at")

    def token(self, tid):
        return self.one("SELECT * FROM tokens WHERE id=?", (tid,))

    def delete_token(self, tid):
        with self.lock:
            for tbl in ("snapshots", "ohlcv", "info", "events"):
                self.conn.execute(f"DELETE FROM {tbl} WHERE token_id=?", (tid,))
            self.conn.execute("DELETE FROM tokens WHERE id=?", (tid,))
            self.conn.commit()

    def update_token(self, tid, **fields):
        if not fields:
            return
        keys = ", ".join(f"{k}=?" for k in fields)
        self.x(f"UPDATE tokens SET {keys} WHERE id=?", (*fields.values(), tid))

    # -- snapshots ---------------------------------------------------------
    SNAP_COLS = ["price_usd", "price_native", "market_cap", "fdv", "liquidity_usd",
                 "volume_m5", "volume_h1", "volume_h6", "volume_h24",
                 "buys_h1", "sells_h1", "buys_h24", "sells_h24",
                 "change_m5", "change_h1", "change_h6", "change_h24",
                 "holders", "top10_pct", "security_score", "pair_count"]

    def add_snapshot(self, tid, ts, s):
        cols = ["token_id", "ts"] + self.SNAP_COLS
        vals = [tid, ts] + [s.get(c) for c in self.SNAP_COLS]
        self.x(f"INSERT INTO snapshots({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", vals)

    def last_snapshot(self, tid):
        return self.one("SELECT * FROM snapshots WHERE token_id=? ORDER BY ts DESC LIMIT 1", (tid,))

    def snapshot_before(self, tid, ts):
        return self.one("SELECT * FROM snapshots WHERE token_id=? AND ts<=? ORDER BY ts DESC LIMIT 1", (tid, ts))

    def last_value(self, tid, col):
        return self.one(f"SELECT ts, {col} AS v FROM snapshots WHERE token_id=? AND {col} IS NOT NULL "
                        f"ORDER BY ts DESC LIMIT 1", (tid,))

    def snapshots(self, tid, since=0):
        return self.q("SELECT * FROM snapshots WHERE token_id=? AND ts>=? ORDER BY ts", (tid, since))

    # -- ohlcv -------------------------------------------------------------
    def upsert_ohlcv(self, tid, tf, candles):
        self.xmany("INSERT OR REPLACE INTO ohlcv(token_id,tf,ts,o,h,l,c,v) VALUES (?,?,?,?,?,?,?,?)",
                   [(tid, tf, int(c[0]), c[1], c[2], c[3], c[4], c[5]) for c in candles])

    def ohlcv(self, tid, tf, limit=1000):
        rows = self.q("SELECT ts,o,h,l,c,v FROM ohlcv WHERE token_id=? AND tf=? ORDER BY ts DESC LIMIT ?",
                      (tid, tf, limit))
        rows.reverse()
        return rows

    # -- info --------------------------------------------------------------
    def set_info(self, tid, data):
        self.x("INSERT OR REPLACE INTO info(token_id,ts,data_json) VALUES (?,?,?)",
               (tid, int(time.time()), json.dumps(data)))

    def get_info(self, tid):
        r = self.one("SELECT * FROM info WHERE token_id=?", (tid,))
        return json.loads(r["data_json"]) if r else {}

    # -- events ------------------------------------------------------------
    def add_event(self, tid, ev):
        cur = self.x(
            """INSERT OR IGNORE INTO events(token_id,ts,kind,direction,pct,price_from,price_to,start_ts,message)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (tid, ev["ts"], ev["kind"], ev.get("direction"), ev.get("pct"), ev.get("price_from"),
             ev.get("price_to"), ev.get("start_ts", ev["ts"]), ev.get("message")),
        )
        return cur.rowcount > 0

    def recent_event(self, tid, kind, since):
        return self.one("SELECT * FROM events WHERE token_id=? AND kind=? AND ts>=? ORDER BY ts DESC LIMIT 1",
                        (tid, kind, since))

    def events(self, tid=None, limit=500):
        if tid is None:
            return self.q("""SELECT e.*, t.symbol, t.name FROM events e JOIN tokens t ON t.id=e.token_id
                             ORDER BY e.ts DESC LIMIT ?""", (limit,))
        return self.q("SELECT * FROM events WHERE token_id=? ORDER BY ts DESC LIMIT ?", (tid, limit))

"""data/db/manager.py — 本地 SQLite K线数据库管理"""
import os
import sqlite3
import pandas as pd

_DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stock_kline.db")


def db_path() -> str:
    return _DB_FILE


def init_db() -> None:
    conn = sqlite3.connect(_DB_FILE)
    cur = conn.cursor()
    cur.executescript("""
        CREATE TABLE IF NOT EXISTS daily_kline (
            code       TEXT NOT NULL,
            date       TEXT NOT NULL,
            open       REAL,
            high       REAL,
            low        REAL,
            close      REAL,
            volume     REAL,
            amount     REAL,
            pct_change REAL,
            PRIMARY KEY (code, date)
        );
        CREATE TABLE IF NOT EXISTS stock_meta (
            code      TEXT PRIMARY KEY,
            name      TEXT,
            last_date TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_dk_code ON daily_kline(code);
        CREATE INDEX IF NOT EXISTS idx_dk_date ON daily_kline(date);
    """)
    conn.commit()
    conn.close()


def upsert_daily(code: str, df: pd.DataFrame) -> None:
    """将 DataFrame 写入 daily_kline，重复(code,date)自动覆盖。"""
    if df.empty:
        return
    init_db()
    tmp = df.copy()
    tmp["date"] = pd.to_datetime(tmp["date"]).dt.strftime("%Y-%m-%d")
    for col in ["open", "high", "low", "close", "volume", "amount", "pct_change"]:
        if col not in tmp.columns:
            tmp[col] = None
    records = [
        (
            code,
            row["date"],
            _safe(row, "open"), _safe(row, "high"), _safe(row, "low"), _safe(row, "close"),
            _safe(row, "volume"), _safe(row, "amount"), _safe(row, "pct_change"),
        )
        for _, row in tmp.iterrows()
    ]
    conn = sqlite3.connect(_DB_FILE)
    conn.executemany(
        "INSERT OR REPLACE INTO daily_kline "
        "(code,date,open,high,low,close,volume,amount,pct_change) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        records,
    )
    conn.commit()
    conn.close()


def _safe(row, col):
    v = row.get(col)
    if v is None:
        return None
    try:
        import math
        if math.isnan(float(v)):
            return None
        return float(v)
    except Exception:
        return None


def get_daily(code: str, start: str = None, end: str = None) -> pd.DataFrame:
    """按代码和日期范围查询日K，升序返回。"""
    init_db()
    sql = ("SELECT date,open,high,low,close,volume,amount,pct_change "
           "FROM daily_kline WHERE code=?")
    params = [code]
    if start:
        sql += " AND date>=?"; params.append(start)
    if end:
        sql += " AND date<=?"; params.append(end)
    sql += " ORDER BY date ASC"
    conn = sqlite3.connect(_DB_FILE)
    df = pd.read_sql(sql, conn, params=params)
    conn.close()
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def upsert_meta(code: str, name: str, last_date: str) -> None:
    init_db()
    conn = sqlite3.connect(_DB_FILE)
    conn.execute(
        "INSERT OR REPLACE INTO stock_meta (code,name,last_date) VALUES (?,?,?)",
        (code, name, last_date),
    )
    conn.commit()
    conn.close()


def get_meta(code: str) -> dict:
    init_db()
    conn = sqlite3.connect(_DB_FILE)
    cur = conn.execute("SELECT code,name,last_date FROM stock_meta WHERE code=?", (code,))
    row = cur.fetchone()
    conn.close()
    if row:
        return {"code": row[0], "name": row[1], "last_date": row[2]}
    return None


def get_all_codes() -> list:
    """返回 [{"code": ..., "name": ...}, ...]"""
    init_db()
    conn = sqlite3.connect(_DB_FILE)
    cur = conn.execute("SELECT code,name FROM stock_meta ORDER BY code")
    rows = cur.fetchall()
    conn.close()
    return [{"code": r[0], "name": r[1]} for r in rows]

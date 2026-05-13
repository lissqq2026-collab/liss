"""data/db/manager.py — 本地 SQLite K线数据库管理"""
import datetime
import os
import sqlite3
from contextlib import contextmanager
import pandas as pd

_DB_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "stock_kline.db")


@contextmanager
def _conn():
    """线程安全的数据库连接上下文管理器，timeout=30秒防止并发锁等待超时。"""
    conn = sqlite3.connect(_DB_FILE, timeout=30)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def db_path() -> str:
    return _DB_FILE


def init_db() -> None:
    with _conn() as conn:
        conn.executescript("""
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=NORMAL;
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
            CREATE TABLE IF NOT EXISTS watchlist (
                code      TEXT NOT NULL,
                name      TEXT,
                added_at  TEXT NOT NULL,
                note      TEXT DEFAULT '',
                PRIMARY KEY (code)
            );
        """)


def upsert_daily(code: str, df: pd.DataFrame) -> None:
    """将 DataFrame 写入 daily_kline，重复(code,date)自动覆盖。"""
    if df.empty:
        return
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
    with _conn() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO daily_kline "
            "(code,date,open,high,low,close,volume,amount,pct_change) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            records,
        )


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
    sql = ("SELECT date,open,high,low,close,volume,amount,pct_change "
           "FROM daily_kline WHERE code=?")
    params = [code]
    if start:
        sql += " AND date>=?"; params.append(start)
    if end:
        sql += " AND date<=?"; params.append(end)
    sql += " ORDER BY date ASC"
    with _conn() as conn:
        df = pd.read_sql(sql, conn, params=params)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
    return df


def upsert_meta(code: str, name: str, last_date: str) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO stock_meta (code,name,last_date) VALUES (?,?,?)",
            (code, name, last_date),
        )


def get_meta(code: str) -> dict:
    with _conn() as conn:
        cur = conn.execute("SELECT code,name,last_date FROM stock_meta WHERE code=?", (code,))
        row = cur.fetchone()
    if row:
        return {"code": row[0], "name": row[1], "last_date": row[2]}
    return None


def get_all_codes() -> list:
    """返回 [{"code": ..., "name": ...}, ...]"""
    with _conn() as conn:
        cur = conn.execute("SELECT code,name FROM stock_meta ORDER BY code")
        rows = cur.fetchall()
    return [{"code": r[0], "name": r[1]} for r in rows]


# ---------------------------------------------------------------------------
# 自选股（watchlist）相关操作
# ---------------------------------------------------------------------------

def add_to_watchlist(code: str, name: str, note: str = "") -> bool:
    """将股票加入自选股。
    返回 True 表示新增成功；返回 False 表示该 code 已存在（未重复插入）。
    """
    added_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _conn() as conn:
        cur = conn.execute(
            "INSERT OR IGNORE INTO watchlist (code, name, added_at, note) VALUES (?, ?, ?, ?)",
            (code, name, added_at, note),
        )
        affected = cur.rowcount
    return affected > 0


def remove_from_watchlist(code: str) -> bool:
    """从自选股中删除指定股票。
    返回 True 表示删除成功；返回 False 表示该 code 不存在。
    """
    with _conn() as conn:
        cur = conn.execute("DELETE FROM watchlist WHERE code=?", (code,))
        affected = cur.rowcount
    return affected > 0


def get_watchlist() -> list:
    """返回全部自选股，按 added_at 倒序排列。
    格式：[{"code": ..., "name": ..., "added_at": ..., "note": ...}, ...]
    """
    with _conn() as conn:
        cur = conn.execute(
            "SELECT code, name, added_at, note FROM watchlist ORDER BY added_at DESC"
        )
        rows = cur.fetchall()
    return [
        {"code": r[0], "name": r[1], "added_at": r[2], "note": r[3]}
        for r in rows
    ]


def is_in_watchlist(code: str) -> bool:
    """判断指定股票是否已在自选股中。"""
    with _conn() as conn:
        cur = conn.execute("SELECT 1 FROM watchlist WHERE code=? LIMIT 1", (code,))
        found = cur.fetchone() is not None
    return found


def update_watchlist_note(code: str, note: str) -> bool:
    """更新自选股备注，返回 True 表示更新成功（code 存在）。"""
    with _conn() as conn:
        cur = conn.execute(
            "UPDATE watchlist SET note=? WHERE code=?",
            (note, code),
        )
        affected = cur.rowcount
    return affected > 0


def get_all_daily_bulk(codes: list, days_limit: int = 300) -> dict:
    """
    一次性批量读取多只股票最近 days_limit 天的K线，返回 {code: DataFrame}。
    比逐只 get_daily() 快10-50倍（单次连接，单次 SQL）。
    days_limit=300 足够覆盖所有形态检测所需的最大历史窗口（60根K线）。
    """
    if not codes:
        return {}
    cutoff = (datetime.date.today() - datetime.timedelta(days=days_limit)).isoformat()
    placeholders = ",".join("?" * len(codes))
    sql = (
        f"SELECT code,date,open,high,low,close,volume,amount,pct_change "
        f"FROM daily_kline WHERE code IN ({placeholders}) AND date>=? "
        f"ORDER BY code,date ASC"
    )
    with _conn() as conn:
        df = pd.read_sql(sql, conn, params=codes + [cutoff])
    if df.empty:
        return {}
    df["date"] = pd.to_datetime(df["date"])
    return {
        code: grp.drop(columns="code").reset_index(drop=True)
        for code, grp in df.groupby("code")
    }


def get_daily_count(code: str) -> int:
    """返回本地数据库中指定股票的K线记录总数。"""
    with _conn() as conn:
        cur = conn.execute(
            "SELECT COUNT(*) FROM daily_kline WHERE code=?",
            (code,),
        )
        row = cur.fetchone()
    return int(row[0]) if row else 0


# 模块加载时统一执行一次数据库初始化
init_db()

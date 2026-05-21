"""data/sources/sina_intraday.py — 新浪财经分时(1分钟)数据源

接口：
  https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData
  ?symbol=sh600519&scale=1&ma=no&datalen=242

返回：当前交易日 (上午 9:30–11:30 + 下午 13:00–15:00) 共 242 根 1 分钟 K 线。
内存缓存 TTL=60s，避免单分钟内重复打远端。
"""
from __future__ import annotations

import json
import threading
import time
from typing import Optional
from urllib import request, error

import pandas as pd

_CACHE: dict[str, tuple[float, pd.DataFrame]] = {}
_CACHE_LOCK = threading.Lock()
_TTL = 60.0
_TIMEOUT = 8.0
_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
       "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121 Safari/537.36")


def _to_sina_symbol(code: str) -> str:
    code = code.strip()
    if code.startswith(("sh", "sz", "bj")):
        return code
    if code.startswith("6"):
        return f"sh{code}"
    if code.startswith(("0", "3")):
        return f"sz{code}"
    if code.startswith(("4", "8")):
        return f"bj{code}"
    return f"sh{code}"


def get_intraday_1min(code: str, datalen: int = 242,
                       use_cache: bool = True) -> Optional[pd.DataFrame]:
    """获取当前交易日 1 分钟分时数据。

    返回 DataFrame 列：datetime, open, high, low, close, volume
    失败或无数据返回 None。
    """
    symbol = _to_sina_symbol(code)
    cache_key = f"{symbol}:{datalen}"

    if use_cache:
        with _CACHE_LOCK:
            hit = _CACHE.get(cache_key)
            if hit and (time.time() - hit[0] < _TTL):
                return hit[1].copy()

    url = ("https://quotes.sina.cn/cn/api/json_v2.php/"
           "CN_MarketDataService.getKLineData"
           f"?symbol={symbol}&scale=1&ma=no&datalen={datalen}")
    req = request.Request(url, headers={"User-Agent": _UA, "Referer": "https://finance.sina.com.cn/"})
    try:
        with request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
    except (error.URLError, TimeoutError, ConnectionError) as e:
        print(f"[sina_intraday] {symbol} 网络错误: {e}")
        return None

    raw = raw.strip()
    if not raw or raw in ("null", "[]"):
        return None
    try:
        rows = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not rows:
        return None

    df = pd.DataFrame(rows)
    if df.empty or "day" not in df.columns:
        return None

    df = df.rename(columns={"day": "datetime"})
    df["datetime"] = pd.to_datetime(df["datetime"])
    for col in ("open", "high", "low", "close", "volume", "amount"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["close"]).sort_values("datetime").reset_index(drop=True)

    if df.empty:
        return None

    # 新浪 datalen=242 返回跨日的最近 242 根 1 分钟 K 线，
    # 仅保留最新交易日，避免分时图跨日拼接 / VWAP 累计起点错位
    latest_date = df["datetime"].dt.normalize().max()
    df = df[df["datetime"].dt.normalize() == latest_date].reset_index(drop=True)
    if df.empty:
        return None

    with _CACHE_LOCK:
        _CACHE[cache_key] = (time.time(), df.copy())
    return df


def get_prev_close(code: str) -> Optional[float]:
    """从新浪 hq 接口取昨收价，用于分时图涨跌幅基准。失败返回 None。"""
    symbol = _to_sina_symbol(code)
    url = f"https://hq.sinajs.cn/list={symbol}"
    req = request.Request(url, headers={"User-Agent": _UA, "Referer": "https://finance.sina.com.cn/"})
    try:
        with request.urlopen(req, timeout=_TIMEOUT) as resp:
            text = resp.read().decode("gbk", errors="ignore")
    except (error.URLError, TimeoutError, ConnectionError):
        return None
    try:
        payload = text.split('"', 2)[1]
        fields = payload.split(",")
        return float(fields[2]) if len(fields) > 2 else None
    except (IndexError, ValueError):
        return None

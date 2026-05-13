"""
data/sources/baostock_source.py
基于 Baostock 的 A 股数据源实现。

Baostock 不提供实时行情和北向资金接口，
这两个函数直接从 akshare_source 引入作为 fallback。

核心优势：提供稳定的历史日线 K 线数据（前复权）。

使用前无需配置 token，Baostock 免费开放。
"""

import sys
import os

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pandas as pd

# Baostock 不支持实时行情和北向资金，直接复用 akshare_source
from data.sources.akshare_source import (
    get_all_a_stock_realtime,
    get_northbound_flow,
    get_northbound_holdings,
)

__all__ = [
    "get_all_a_stock_realtime",
    "get_stock_history",
    "get_stock_history_batch",
    "get_northbound_flow",
    "get_northbound_holdings",
]


def get_stock_history(code: str, days: int = 120, config: dict = None) -> pd.DataFrame:
    """
    使用 Baostock 获取指定股票的日线历史K线数据（前复权）。
    返回 DataFrame 列：date(datetime), open, high, low, close, volume, amount, pct_change
    """
    from data.sources._baostock_utils import bs_get_stock_history
    return bs_get_stock_history(code, days, caller="baostock_source")


def get_stock_history_batch(codes: list, days: int = 120, config: dict = None) -> dict:
    """批量获取历史K线，共享 baostock 会话。"""
    from data.sources._baostock_utils import bs_batch_get_stock_history
    return bs_batch_get_stock_history(codes, days, caller="baostock_source")

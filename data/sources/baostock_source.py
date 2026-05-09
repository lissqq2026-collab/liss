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
from datetime import datetime, timedelta

# Baostock 不支持实时行情和北向资金，直接复用 akshare_source
from data.sources.akshare_source import (
    get_all_a_stock_realtime,
    get_northbound_flow,
    get_northbound_holdings,
)

__all__ = [
    "get_all_a_stock_realtime",
    "get_stock_history",
    "get_northbound_flow",
    "get_northbound_holdings",
]


def get_stock_history(code: str, days: int = 120, config: dict = None) -> pd.DataFrame:
    """
    使用 Baostock 获取指定股票的日线历史K线数据（前复权）。

    参数：
        code   - 股票代码（6位纯数字字符串，如 "000001"）
        days   - 获取最近N个交易日数据，默认120天
        config - Baostock 无需配置，忽略

    返回 DataFrame 列：
        date(datetime), open, high, low, close, volume, amount, pct_change
    按日期升序排列。

    失败时返回空 DataFrame。
    """
    import baostock as bs

    try:
        bs.login()

        # 代码格式：sh.600519 或 sz.000001
        prefix = "sh" if code.startswith("6") else "sz"
        bs_code = f"{prefix}.{code}"

        end_date = datetime.today().strftime("%Y-%m-%d")
        start_date = (datetime.today() - timedelta(days=days * 2)).strftime("%Y-%m-%d")

        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,volume,amount,pctChg",
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="2",   # 2 = 前复权
        )

        if rs.error_code != "0":
            print(f"[baostock_source] query_history_k_data_plus 错误: "
                  f"code={rs.error_code}, msg={rs.error_msg}")
            return pd.DataFrame()

        data_list = []
        while rs.error_code == "0" and rs.next():
            data_list.append(rs.get_row_data())

        if not data_list:
            print(f"[baostock_source] get_stock_history({code}) 无数据")
            return pd.DataFrame()

        df = pd.DataFrame(data_list, columns=rs.fields)

        # 统一列名
        df = df.rename(columns={"pctChg": "pct_change"})

        # 类型转换
        df["date"] = pd.to_datetime(df["date"])
        numeric_cols = ["open", "high", "low", "close", "volume", "amount", "pct_change"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        keep_cols = [c for c in
                     ["date", "open", "high", "low", "close", "volume", "amount", "pct_change"]
                     if c in df.columns]
        df = df[keep_cols].copy()

        df = df.sort_values("date").reset_index(drop=True)
        df = df.tail(days).reset_index(drop=True)

        return df

    except Exception as e:
        print(f"[baostock_source] get_stock_history({code}) 失败: {e}")
        return pd.DataFrame()

    finally:
        try:
            bs.logout()
        except Exception:
            pass

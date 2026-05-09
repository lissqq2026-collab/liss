"""
data/sources/akshare_source.py
基于 AKShare 的 A 股数据源实现。
所有函数签名统一增加 config: dict = None 参数（暂不使用，保持接口一致性）。
"""

import sys
import os

# 确保项目根目录在 sys.path 中
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import akshare as ak
import pandas as pd
from datetime import datetime, timedelta


def get_all_a_stock_realtime(config: dict = None) -> pd.DataFrame:
    """
    获取全部A股实时行情，包含PE、PB、市值、涨跌幅等字段。

    返回 DataFrame 列：
        code          - 股票代码（6位，无前缀）
        name          - 股票名称
        price         - 最新价
        pct_change    - 涨跌幅(%)
        pe            - 市盈率(TTM)
        pb            - 市净率
        total_mv      - 总市值(亿元)
        volume        - 成交量(手)
        amount        - 成交额(元)

    网络失败时返回空 DataFrame 并打印错误。
    """
    try:
        df = ak.stock_zh_a_spot_em()
        rename_map = {
            "代码": "code",
            "名称": "name",
            "最新价": "price",
            "涨跌幅": "pct_change",
            "成交量": "volume",
            "成交额": "amount",
            "市盈率-动态": "pe",
            "市净率": "pb",
            "总市值": "total_mv",
            "流通市值": "float_mv",
            "换手率": "turnover_rate",
            "量比": "volume_ratio",
        }
        df = df.rename(columns=rename_map)

        keep_cols = [c for c in rename_map.values() if c in df.columns]
        df = df[keep_cols].copy()

        numeric_cols = ["price", "pct_change", "pe", "pb", "volume",
                        "amount", "turnover_rate", "volume_ratio"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        if "total_mv" in df.columns:
            df["total_mv"] = pd.to_numeric(df["total_mv"], errors="coerce") / 1e8
        if "float_mv" in df.columns:
            df["float_mv"] = pd.to_numeric(df["float_mv"], errors="coerce") / 1e8

        df = df[df["price"].notna() & (df["price"] > 0)].reset_index(drop=True)

        print(f"[akshare_source] 实时行情获取成功，共 {len(df)} 条记录")
        return df

    except Exception as e:
        print(f"[akshare_source] get_all_a_stock_realtime 失败: {e}")
        return pd.DataFrame()


def get_stock_history(code: str, days: int = 120, config: dict = None) -> pd.DataFrame:
    """
    获取指定股票的日线历史K线数据（前复权）。

    参数：
        code   - 股票代码（6位纯数字字符串，如 "000001"）
        days   - 获取最近N个交易日的数据，默认120天
        config - 数据源配置（AKShare 无需配置，忽略）

    返回 DataFrame 列：
        date(datetime), open, high, low, close, volume, amount, pct_change
    按日期升序排列。

    网络失败时返回空 DataFrame 并打印错误。
    """
    try:
        end_date = datetime.today().strftime("%Y%m%d")
        start_date = (datetime.today() - timedelta(days=days * 2)).strftime("%Y%m%d")

        df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="qfq",
        )

        rename_map = {
            "日期": "date",
            "开盘": "open",
            "最高": "high",
            "最低": "low",
            "收盘": "close",
            "成交量": "volume",
            "成交额": "amount",
            "涨跌幅": "pct_change",
        }
        df = df.rename(columns=rename_map)

        keep_cols = [c for c in rename_map.values() if c in df.columns]
        df = df[keep_cols].copy()

        df["date"] = pd.to_datetime(df["date"])
        numeric_cols = ["open", "high", "low", "close", "volume", "amount", "pct_change"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.sort_values("date").reset_index(drop=True)
        df = df.tail(days).reset_index(drop=True)

        return df

    except Exception as e:
        print(f"[akshare_source] get_stock_history({code}) 失败: {e}")
        return pd.DataFrame()


def get_northbound_flow(config: dict = None) -> pd.DataFrame:
    """
    获取北向资金（沪深港通北向）净流入数据。

    返回 DataFrame 列：
        date(datetime), sh_net_inflow, sz_net_inflow, total_net_inflow
    单位：亿元

    网络失败时返回空 DataFrame 并打印错误。
    """
    try:
        df = ak.stock_em_hsgt_north_net_flow_in(symbol="沪深港通")

        rename_map = {
            "日期": "date",
            "沪股通": "sh_net_inflow",
            "深股通": "sz_net_inflow",
            "北向资金": "total_net_inflow",
        }
        df = df.rename(columns=rename_map)

        keep_cols = [c for c in rename_map.values() if c in df.columns]
        df = df[keep_cols].copy()

        df["date"] = pd.to_datetime(df["date"])

        numeric_cols = ["sh_net_inflow", "sz_net_inflow", "total_net_inflow"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce") / 1e8

        df = df.sort_values("date").reset_index(drop=True)

        print(f"[akshare_source] 北向资金数据获取成功，共 {len(df)} 条记录")
        return df

    except Exception as e:
        print(f"[akshare_source] get_northbound_flow 失败: {e}")
        return pd.DataFrame()


def get_northbound_holdings(config: dict = None) -> pd.DataFrame:
    """
    获取北向资金（沪深港通）个股持股数据（最新一期）。

    返回 DataFrame 列：
        code, name, hold_shares, hold_ratio, hold_change, market

    网络失败时返回空 DataFrame 并打印错误。
    """
    try:
        frames = []
        for market in ["沪股通", "深股通"]:
            try:
                df_m = ak.stock_em_hsgt_hold_stock(market=market)
                df_m["market"] = market
                frames.append(df_m)
            except Exception as e:
                print(f"[akshare_source] 获取{market}持股数据失败: {e}")

        if not frames:
            return pd.DataFrame()

        df = pd.concat(frames, ignore_index=True)

        rename_map = {
            "股票代码": "code",
            "股票名称": "name",
            "持股数量": "hold_shares",
            "持股占比": "hold_ratio",
            "持股变动": "hold_change",
        }
        df = df.rename(columns=rename_map)

        keep_cols = [c for c in rename_map.values() if c in df.columns] + ["market"]
        keep_cols = [c for c in keep_cols if c in df.columns]
        df = df[keep_cols].copy()

        for col in ["hold_shares", "hold_ratio", "hold_change"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        print(f"[akshare_source] 北向持股数据获取成功，共 {len(df)} 条记录")
        return df

    except Exception as e:
        print(f"[akshare_source] get_northbound_holdings 失败: {e}")
        return pd.DataFrame()

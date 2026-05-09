"""
data/fetcher.py
A股实时行情、历史K线、北向资金数据获取模块
依赖：akshare, pandas
"""

import akshare as ak
import pandas as pd
from datetime import datetime, timedelta


def get_all_a_stock_realtime() -> pd.DataFrame:
    """
    获取全部A股实时行情，包含PE、PB、市值、涨跌幅等字段。

    返回 DataFrame 列（统一命名）：
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
        # 使用东方财富A股实时行情接口，字段最全
        df = ak.stock_zh_a_spot_em()
        # 原始列名参考：序号,代码,名称,最新价,涨跌幅,涨跌额,成交量,成交额,振幅,
        # 最高,最低,今开,昨收,量比,换手率,市盈率-动态,市净率,总市值,流通市值,...
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

        # 只保留需要的列（容错：列不存在则跳过）
        keep_cols = [c for c in rename_map.values() if c in df.columns]
        df = df[keep_cols].copy()

        # 类型转换
        numeric_cols = ["price", "pct_change", "pe", "pb", "volume",
                        "amount", "turnover_rate", "volume_ratio"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # 总市值转换为亿元（原始单位为元）
        if "total_mv" in df.columns:
            df["total_mv"] = pd.to_numeric(df["total_mv"], errors="coerce") / 1e8
        if "float_mv" in df.columns:
            df["float_mv"] = pd.to_numeric(df["float_mv"], errors="coerce") / 1e8

        # 剔除停牌（价格为0或NaN）
        df = df[df["price"].notna() & (df["price"] > 0)].reset_index(drop=True)

        print(f"[fetcher] 实时行情获取成功，共 {len(df)} 条记录")
        return df

    except Exception as e:
        print(f"[fetcher] get_all_a_stock_realtime 失败: {e}")
        return pd.DataFrame()


def get_stock_history(code: str, days: int = 120) -> pd.DataFrame:
    """
    获取指定股票的日线历史K线数据（用于技术指标计算）。

    参数：
        code  - 股票代码（6位纯数字字符串，如 "000001"）
        days  - 获取最近N个交易日的数据，默认120天（够算MA60+缓冲）

    返回 DataFrame 列：
        date     - 日期 (datetime)
        open     - 开盘价
        high     - 最高价
        low      - 最低价
        close    - 收盘价
        volume   - 成交量(手)
        amount   - 成交额(元)
        pct_change - 涨跌幅(%)

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
            adjust="qfq",   # 前复权，技术分析标准做法
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

        # 只保留最近 days 个交易日
        df = df.tail(days).reset_index(drop=True)

        return df

    except Exception as e:
        print(f"[fetcher] get_stock_history({code}) 失败: {e}")
        return pd.DataFrame()


def get_northbound_flow() -> pd.DataFrame:
    """
    获取北向资金（沪深港通北向）净流入数据。

    返回 DataFrame 列：
        date              - 日期 (datetime)
        sh_net_inflow     - 沪股通净流入(亿元)
        sz_net_inflow     - 深股通净流入(亿元)
        total_net_inflow  - 合计净流入(亿元)

    网络失败时返回空 DataFrame 并打印错误。
    """
    try:
        # 北向资金每日流向汇总
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
                df[col] = pd.to_numeric(df[col], errors="coerce") / 1e8  # 转亿元

        df = df.sort_values("date").reset_index(drop=True)

        print(f"[fetcher] 北向资金数据获取成功，共 {len(df)} 条记录")
        return df

    except Exception as e:
        print(f"[fetcher] get_northbound_flow 失败: {e}")
        return pd.DataFrame()


def get_northbound_holdings() -> pd.DataFrame:
    """
    获取北向资金（沪深港通）个股持股数据（最新一期）。

    返回 DataFrame 列：
        code           - 股票代码
        name           - 股票名称
        hold_shares    - 持股数量(股)
        hold_ratio     - 持股比例(%)
        hold_change    - 持股变动(股)
        market         - 市场(沪/深)

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
                print(f"[fetcher] 获取{market}持股数据失败: {e}")

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

        print(f"[fetcher] 北向持股数据获取成功，共 {len(df)} 条记录")
        return df

    except Exception as e:
        print(f"[fetcher] get_northbound_holdings 失败: {e}")
        return pd.DataFrame()


if __name__ == "__main__":
    print("=== 测试 data/fetcher.py ===")

    print("\n[1] 获取全部A股实时行情（前5条）")
    df_spot = get_all_a_stock_realtime()
    if not df_spot.empty:
        print(df_spot.head())

    print("\n[2] 获取 000001(平安银行) 历史K线（前5条）")
    df_hist = get_stock_history("000001", days=30)
    if not df_hist.empty:
        print(df_hist.head())

    print("\n[3] 获取北向资金净流入（前5条）")
    df_north = get_northbound_flow()
    if not df_north.empty:
        print(df_north.head())

    print("\n[4] 获取北向持股数据（前5条）")
    df_hold = get_northbound_holdings()
    if not df_hold.empty:
        print(df_hold.head())

"""
data/sources/tushare_source.py
基于 Tushare Pro 的 A 股数据源实现。

使用前需在 config 中传入 token：
    set_data_source("tushare", {"token": "your_tushare_pro_token"})

注意：
- get_northbound_holdings 需要高积分权限，当前返回空 DataFrame。
- total_mv 原始单位为万元，此处统一转换为亿元（÷10000）。
"""

import sys
import os

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pandas as pd
from datetime import datetime, timedelta


def _get_pro(config: dict):
    """初始化并返回 Tushare Pro API 对象。"""
    import tushare as ts
    token = (config or {}).get("token", "")
    ts.set_token(token)
    return ts.pro_api()


def _latest_trade_date(pro) -> str:
    """
    获取最新有效交易日（YYYYMMDD 格式）。
    从今天开始向前最多回退 5 个自然日，找到 daily 接口有数据的那天。
    """
    today = datetime.today()
    for offset in range(6):
        candidate = (today - timedelta(days=offset)).strftime("%Y%m%d")
        try:
            df = pro.daily(trade_date=candidate, fields="ts_code")
            if df is not None and not df.empty:
                return candidate
        except Exception:
            continue
    # 兜底：返回今天日期
    return today.strftime("%Y%m%d")


def get_all_a_stock_realtime(config: dict = None) -> pd.DataFrame:
    """
    获取全部A股实时（最新交易日）行情，包含PE、PB、市值、涨跌幅等字段。

    调用接口：
        pro.daily_basic  → pe, pb, total_mv
        pro.daily        → open/close/pct_chg/vol/amount
        pro.stock_basic  → 股票名称

    返回 DataFrame 列：
        code, name, price, pct_change, pe, pb, total_mv(亿元), volume, amount

    失败时返回空 DataFrame。
    """
    try:
        pro = _get_pro(config)
        trade_date = _latest_trade_date(pro)

        # 基础行情
        df_daily = pro.daily(
            trade_date=trade_date,
            fields="ts_code,close,pct_chg,vol,amount"
        )
        if df_daily is None or df_daily.empty:
            print(f"[tushare_source] daily 接口在 {trade_date} 无数据")
            return pd.DataFrame()

        # 估值数据
        df_basic = pro.daily_basic(
            trade_date=trade_date,
            fields="ts_code,pe_ttm,pb,total_mv"
        )

        # 股票名称
        df_names = pro.stock_basic(
            list_status="L",
            fields="ts_code,name"
        )

        # 合并
        df = df_daily.merge(df_basic, on="ts_code", how="left")
        df = df.merge(df_names, on="ts_code", how="left")

        # ts_code → code（去掉 .SH / .SZ 后缀）
        df["code"] = df["ts_code"].str.split(".").str[0]

        # 统一列名
        df = df.rename(columns={
            "close": "price",
            "pct_chg": "pct_change",
            "vol": "volume",
            "pe_ttm": "pe",
        })

        # total_mv: 万元 → 亿元
        if "total_mv" in df.columns:
            df["total_mv"] = pd.to_numeric(df["total_mv"], errors="coerce") / 10000

        numeric_cols = ["price", "pct_change", "pe", "pb", "volume", "amount"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        keep_cols = [c for c in
                     ["code", "name", "price", "pct_change", "pe", "pb",
                      "total_mv", "volume", "amount"]
                     if c in df.columns]
        df = df[keep_cols].copy()

        # 剔除停牌（价格为 0 或 NaN）
        df = df[df["price"].notna() & (df["price"] > 0)].reset_index(drop=True)

        print(f"[tushare_source] 实时行情获取成功（{trade_date}），共 {len(df)} 条记录")
        return df

    except Exception as e:
        print(f"[tushare_source] get_all_a_stock_realtime 失败: {e}")
        return pd.DataFrame()


def get_stock_history(code: str, days: int = 120, config: dict = None) -> pd.DataFrame:
    """
    获取指定股票的日线历史K线数据（前复权）。

    参数：
        code   - 股票代码（6位纯数字字符串，如 "000001"）
        days   - 获取最近N个交易日数据，默认120天
        config - 需包含 token 字段

    返回 DataFrame 列：
        date(datetime), open, high, low, close, volume, amount, pct_change
    按日期升序排列。

    失败时返回空 DataFrame。
    """
    try:
        pro = _get_pro(config)

        # 判断交易所后缀：6开头→SH，0/3开头→SZ
        if code.startswith("6"):
            ts_code = f"{code}.SH"
        else:
            ts_code = f"{code}.SZ"

        end_date = datetime.today().strftime("%Y%m%d")
        start_date = (datetime.today() - timedelta(days=days * 2)).strftime("%Y%m%d")

        df = pro.daily(
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
            fields="ts_code,trade_date,open,high,low,close,vol,amount,pct_chg",
            adj="qfq",
        )

        if df is None or df.empty:
            print(f"[tushare_source] get_stock_history({code}) 无数据")
            return pd.DataFrame()

        df = df.rename(columns={
            "trade_date": "date",
            "vol": "volume",
            "pct_chg": "pct_change",
        })

        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")

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
        print(f"[tushare_source] get_stock_history({code}) 失败: {e}")
        return pd.DataFrame()


def get_northbound_flow(config: dict = None) -> pd.DataFrame:
    """
    获取北向资金净流入数据。

    调用 pro.moneyflow_hsgt 接口。
    注意：Tushare 该接口仅提供合计北向资金（north_money），
    无法拆分沪/深股通，sh_net_inflow / sz_net_inflow 设为 NaN。

    返回 DataFrame 列：
        date(datetime), sh_net_inflow(NaN), sz_net_inflow(NaN),
        total_net_inflow(亿元)

    失败时返回空 DataFrame。
    """
    try:
        pro = _get_pro(config)

        end_date = datetime.today().strftime("%Y%m%d")
        start_date = (datetime.today() - timedelta(days=365)).strftime("%Y%m%d")

        df = pro.moneyflow_hsgt(
            start_date=start_date,
            end_date=end_date,
            fields="trade_date,north_money"
        )

        if df is None or df.empty:
            print("[tushare_source] get_northbound_flow 无数据")
            return pd.DataFrame()

        df = df.rename(columns={"trade_date": "date", "north_money": "total_net_inflow"})
        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
        df["total_net_inflow"] = pd.to_numeric(df["total_net_inflow"], errors="coerce")
        # Tushare north_money 单位已是亿元，无需转换
        df["sh_net_inflow"] = float("nan")
        df["sz_net_inflow"] = float("nan")

        keep_cols = ["date", "sh_net_inflow", "sz_net_inflow", "total_net_inflow"]
        df = df[keep_cols].copy()
        df = df.sort_values("date").reset_index(drop=True)

        print(f"[tushare_source] 北向资金数据获取成功，共 {len(df)} 条记录")
        return df

    except Exception as e:
        print(f"[tushare_source] get_northbound_flow 失败: {e}")
        return pd.DataFrame()


def get_northbound_holdings(config: dict = None) -> pd.DataFrame:
    """
    获取北向资金个股持股数据。

    注意：Tushare Pro 的持股明细接口（hsgt_top10 等）需要较高积分权限，
    当前版本直接返回空 DataFrame 并给出提示。

    返回：空 DataFrame（含标准列名）
    """
    print(
        "[tushare_source] get_northbound_holdings: "
        "Tushare Pro 持股明细接口需要高级积分权限，暂不支持。"
        "请改用 akshare 数据源或联系 Tushare 开通权限。"
    )
    return pd.DataFrame(columns=["code", "name", "hold_shares",
                                  "hold_ratio", "hold_change", "market"])

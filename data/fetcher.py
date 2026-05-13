"""
data/fetcher.py
A股实时行情、历史K线、北向资金数据获取模块
依赖：baostock, pandas；可选：tushare, akshare

支持多数据源切换，默认使用 AKShare（无需配置）。
切换示例：
    from data.fetcher import set_data_source
    set_data_source("tushare", {"token": "your_token"})
    set_data_source("baostock")
    set_data_source("akshare")   # 切回默认
"""

import sys
import os

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pandas as pd

# ---------------------------------------------------------------------------
# 数据源管理
# ---------------------------------------------------------------------------

_SOURCE: str = "akshare"
_SOURCE_CONFIG: dict = {}


def set_data_source(source: str, config: dict = None) -> None:
    """
    切换全局数据源。

    参数：
        source - 数据源名称，支持 "akshare"（默认）、"tushare"、"baostock"
        config - 数据源配置字典，例如 Tushare 需要 {"token": "xxx"}
    """
    global _SOURCE, _SOURCE_CONFIG
    _SOURCE = source
    _SOURCE_CONFIG = config or {}
    print(f"[fetcher] 数据源已切换为: {_SOURCE}")


def _get_source_module():
    """根据当前 _SOURCE 动态加载对应的数据源模块。"""
    if _SOURCE == "tushare":
        from data.sources import tushare_source
        return tushare_source
    elif _SOURCE == "baostock":
        from data.sources import baostock_source
        return baostock_source
    else:
        from data.sources import akshare_source
        return akshare_source


# ---------------------------------------------------------------------------
# 公共接口（委托至数据源模块）
# ---------------------------------------------------------------------------

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
    当前数据源由 set_data_source() 控制，默认为 akshare。
    """
    return _get_source_module().get_all_a_stock_realtime(_SOURCE_CONFIG)


def get_stock_history(code: str, days: int = 120) -> pd.DataFrame:
    """
    获取指定股票的日线历史K线数据（前复权，用于技术指标计算）。

    参数：
        code  - 股票代码（6位纯数字字符串，如 "000001"）
        days  - 获取最近N个交易日的数据，默认120天（够算MA60+缓冲）

    返回 DataFrame 列：
        date(datetime), open, high, low, close, volume, amount, pct_change
    按日期升序排列。

    网络失败时返回空 DataFrame 并打印错误。
    当前数据源由 set_data_source() 控制，默认为 akshare。
    """
    return _get_source_module().get_stock_history(code, days, _SOURCE_CONFIG)


def get_northbound_flow() -> pd.DataFrame:
    """
    获取北向资金（沪深港通北向）净流入数据。

    返回 DataFrame 列：
        date(datetime), sh_net_inflow, sz_net_inflow, total_net_inflow
    单位：亿元

    网络失败时返回空 DataFrame 并打印错误。
    当前数据源由 set_data_source() 控制，默认为 akshare。
    注意：tushare 数据源仅提供合计北向资金，sh/sz 拆分为 NaN。
    """
    return _get_source_module().get_northbound_flow(_SOURCE_CONFIG)


def get_northbound_holdings() -> pd.DataFrame:
    """
    获取北向资金（沪深港通）个股持股数据（最新一期）。

    返回 DataFrame 列：
        code, name, hold_shares, hold_ratio, hold_change, market

    网络失败时返回空 DataFrame 并打印错误。
    当前数据源由 set_data_source() 控制，默认为 akshare。
    注意：tushare 数据源需要高级积分权限，将返回空 DataFrame。
    """
    return _get_source_module().get_northbound_holdings(_SOURCE_CONFIG)


def get_stock_history_batch(codes: list, days: int = 120) -> dict:
    """
    批量获取多只股票历史K线（共享 baostock 会话，大幅减少网络握手次数）。

    参数：
        codes - 股票代码列表（6位字符串）
        days  - 最近N个交易日

    返回：{code: DataFrame} 字典，DataFrame 列与 get_stock_history 一致。
    网络失败的个股值为空 DataFrame。
    """
    src = _get_source_module()
    if hasattr(src, "get_stock_history_batch"):
        return src.get_stock_history_batch(codes, days, _SOURCE_CONFIG)
    # 不支持批量的数据源退化为逐条获取
    return {code: src.get_stock_history(code, days, _SOURCE_CONFIG) for code in codes}


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

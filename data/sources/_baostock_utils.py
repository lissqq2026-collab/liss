"""
data/sources/_baostock_utils.py
baostock 共用工具，供 akshare_source 和 baostock_source 调用，消除重复实现。
"""

import threading
import pandas as pd
from datetime import datetime, timedelta

_bs_lock = threading.RLock()


def bs_get_stock_history(code: str, days: int = 120, caller: str = "baostock_utils") -> pd.DataFrame:
    """
    使用 baostock 获取指定股票的日线历史K线数据（前复权）。

    参数：
        code   - 股票代码（6位纯数字，如 "000001"）
        days   - 最近N个交易日，默认120
        caller - 日志前缀，便于追踪调用来源

    返回 DataFrame 列：
        date(datetime), open, high, low, close, volume, amount, pct_change
    按日期升序排列，失败时返回空 DataFrame。
    """
    import baostock as bs

    prefix     = "sh" if code.startswith("6") else ("bj" if code.startswith(("83", "43")) else "sz")
    bs_code    = f"{prefix}.{code}"
    end_date   = datetime.today().strftime("%Y-%m-%d")
    start_date = (datetime.today() - timedelta(days=days * 2)).strftime("%Y-%m-%d")

    _row_data   = None
    _row_fields = None

    with _bs_lock:
        try:
            bs.login()
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,open,high,low,close,volume,amount,pctChg",
                start_date=start_date,
                end_date=end_date,
                frequency="d",
                adjustflag="2",
            )
            if rs.error_code != "0":
                print(f"[{caller}] baostock history 错误: {rs.error_code} {rs.error_msg}")
            else:
                _row_fields = rs.fields
                _row_data = []
                while rs.error_code == "0" and rs.next():
                    _row_data.append(rs.get_row_data())
                if not _row_data:
                    print(f"[{caller}] get_stock_history({code}) 无数据")
        except Exception as e:
            print(f"[{caller}] get_stock_history({code}) 失败: {e}")
        finally:
            try:
                bs.logout()
            except Exception:
                pass

    if not _row_data:
        return pd.DataFrame()

    df = pd.DataFrame(_row_data, columns=_row_fields)
    df = df.rename(columns={"pctChg": "pct_change"})
    df["date"] = pd.to_datetime(df["date"])
    for col in ["open", "high", "low", "close", "volume", "amount", "pct_change"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    keep = [c for c in ["date", "open", "high", "low", "close", "volume", "amount", "pct_change"]
            if c in df.columns]
    return df[keep].sort_values("date").tail(days).reset_index(drop=True)


def bs_batch_get_stock_history(codes: list, days: int = 120, caller: str = "baostock_utils") -> dict:
    """
    批量获取多只股票历史K线，per-stock 持锁（login→query→logout→释放锁→下一只）。
    锁持有时间约 1-3s/只，允许其他 baostock 调用在股票间隙插入。
    返回 {code: DataFrame}，失败的股票值为空 DataFrame。
    """
    import socket
    import baostock as bs

    _orig_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(30)

    results = {code: pd.DataFrame() for code in codes}
    end_date = datetime.today().strftime("%Y-%m-%d")

    try:
        for code in codes:
            start_date = (datetime.today() - timedelta(days=days * 2)).strftime("%Y-%m-%d")
            prefix = "sh" if code.startswith("6") else ("bj" if code.startswith(("83", "43")) else "sz")
            bs_code = f"{prefix}.{code}"

            _row_data   = None
            _row_fields = None

            with _bs_lock:
                try:
                    bs.login()
                    rs = bs.query_history_k_data_plus(
                        bs_code,
                        "date,open,high,low,close,volume,amount,pctChg",
                        start_date=start_date,
                        end_date=end_date,
                        frequency="d",
                        adjustflag="2",
                    )
                    if rs.error_code == "0":
                        _row_fields = rs.fields
                        _row_data = []
                        while rs.error_code == "0" and rs.next():
                            _row_data.append(rs.get_row_data())
                    else:
                        print(f"[{caller}] {code} query 错误: {rs.error_code} {rs.error_msg}")
                except Exception as e:
                    print(f"[{caller}] {code} 批量查询失败: {e}")
                finally:
                    try:
                        bs.logout()
                    except Exception:
                        pass

            if _row_data:
                df = pd.DataFrame(_row_data, columns=_row_fields)
                df = df.rename(columns={"pctChg": "pct_change"})
                df["date"] = pd.to_datetime(df["date"])
                for col in ["open", "high", "low", "close", "volume", "amount", "pct_change"]:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")
                keep = [c for c in ["date", "open", "high", "low", "close", "volume", "amount", "pct_change"]
                        if c in df.columns]
                results[code] = df[keep].sort_values("date").tail(days).reset_index(drop=True)

    finally:
        socket.setdefaulttimeout(_orig_timeout)

    return results

"""
data/sources/akshare_source.py
A 股数据源实现。
实时行情：baostock（股票列表） + 腾讯行情 API（qt.gtimg.cn，含PE/PB/市值）。
历史K线：baostock（前复权日线）。
东方财富/AKShare 的东财接口在当前网络环境下被屏蔽，已停用。
所有函数签名统一增加 config: dict = None 参数（暂不使用，保持接口一致性）。
"""

import sys
import os

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pandas as pd
from datetime import datetime, timedelta


# ---------------------------------------------------------------------------
# 内部辅助：腾讯行情批量查询
# ---------------------------------------------------------------------------

def _tencent_batch_query(codes_with_prefix: list) -> list:
    """
    批量查询腾讯 qt.gtimg.cn，每批100只，返回解析后的行情 dict 列表。
    codes_with_prefix: ["sh600000", "sz000001", ...]
    腾讯字段索引（~分隔，0起）：
      [1]=名称  [3]=现价  [32]=涨跌幅%  [36]=成交量(手)
      [37]=成交额(万元)  [43]=PB  [44]=总市值(亿元)  [65]=PE-TTM
    """
    import requests

    results = []
    batch_size = 100

    for i in range(0, len(codes_with_prefix), batch_size):
        batch = codes_with_prefix[i : i + batch_size]
        url = "http://qt.gtimg.cn/q=" + ",".join(batch)
        try:
            resp = requests.get(
                url, timeout=10,
                headers={"Referer": "http://finance.qq.com"},
            )
            resp.encoding = "gbk"
            for line in resp.text.splitlines():
                if "~" not in line or '"' not in line:
                    continue
                try:
                    data_part = line.split('"')[1]
                except IndexError:
                    continue
                fields = data_part.split("~")
                if len(fields) < 50:
                    continue
                try:
                    def _f(idx):
                        return fields[idx] if idx < len(fields) else ""

                    price_s = _f(3)
                    if not price_s:
                        continue
                    price = float(price_s)
                    if price <= 0:
                        continue

                    results.append({
                        "code":       _f(2),
                        "name":       _f(1),
                        "price":      price,
                        "pct_change": float(_f(32)) if _f(32) else None,
                        "volume":     float(_f(36)) if _f(36) else None,
                        "amount":     float(_f(37)) * 10000 if _f(37) else None,
                        "pb":         float(_f(43)) if _f(43) else None,
                        "total_mv":   float(_f(44)) if _f(44) else None,
                        "pe":         float(_f(65)) if _f(65) else None,
                    })
                except (ValueError, IndexError):
                    continue
        except Exception as e:
            print(f"[akshare_source] 腾讯行情批次 {i//batch_size+1} 失败: {e}")
            continue

    return results


# ---------------------------------------------------------------------------
# 内部辅助：通过 baostock 获取全部A股代码列表
# ---------------------------------------------------------------------------

def _baostock_get_all_codes() -> list:
    """
    返回 [{"prefix_code": "sh600000", "code": "600000", "name": "浦发银行"}, ...]
    自动往回最多10个工作日查找有数据的交易日。
    """
    import baostock as bs

    try:
        bs.login()
        day = datetime.today()
        for _ in range(14):
            day -= timedelta(days=1)
            if day.weekday() >= 5:
                continue
            day_str = day.strftime("%Y-%m-%d")
            rs = bs.query_all_stock(day=day_str)
            if rs.error_code != "0":
                continue
            rows = []
            while rs.next():
                rows.append(rs.get_row_data())
            if not rows:
                continue

            result = []
            for row in rows:
                bs_code = row[0]          # e.g. sh.600000
                name    = row[2] if len(row) > 2 else ""
                parts   = bs_code.split(".")
                if len(parts) != 2:
                    continue
                prefix, code = parts[0], parts[1]
                if (prefix == "sh" and code.startswith("6")) or \
                   (prefix == "sz" and (code.startswith("0") or code.startswith("3"))):
                    result.append({
                        "prefix_code": f"{prefix}{code}",
                        "code": code,
                        "name": name,
                    })
            if result:
                print(f"[akshare_source] baostock query_all_stock({day_str}) -> {len(result)} 只A股")
                return result
    except Exception as e:
        print(f"[akshare_source] baostock 获取股票列表失败: {e}")
    finally:
        try:
            bs.logout()
        except Exception:
            pass

    return []


# ---------------------------------------------------------------------------
# 公共接口
# ---------------------------------------------------------------------------

def get_all_a_stock_realtime(config: dict = None) -> pd.DataFrame:
    """
    获取全部A股实时行情，包含PE、PB、市值、涨跌幅等字段。
    数据源：baostock（股票列表） + 腾讯行情 API（实时价格/指标）。

    返回 DataFrame 列：
        code, name, price, pct_change, pe, pb, total_mv(亿元), volume(手), amount(元)
    网络失败时返回空 DataFrame 并打印错误。
    """
    stock_list = _baostock_get_all_codes()
    if not stock_list:
        print("[akshare_source] 未能获取股票列表，实时行情返回空")
        return pd.DataFrame()

    code_name_map = {s["code"]: s["name"] for s in stock_list}
    prefix_codes  = [s["prefix_code"] for s in stock_list]

    print(f"[akshare_source] 开始批量查询腾讯行情，共 {len(prefix_codes)} 只…")
    rows = _tencent_batch_query(prefix_codes)

    if not rows:
        print("[akshare_source] 腾讯行情批量查询无结果")
        return pd.DataFrame()

    df = pd.DataFrame(rows)

    # 用 baostock 名称补充（腾讯返回的名称有时较短）
    df["name"] = df["code"].map(code_name_map).fillna(df["name"])

    df = df[df["price"].notna() & (df["price"] > 0)].reset_index(drop=True)

    out_cols = ["code", "name", "price", "pct_change", "pe", "pb", "total_mv", "volume", "amount"]
    df = df[[c for c in out_cols if c in df.columns]]

    print(f"[akshare_source] 实时行情获取成功（baostock+腾讯），共 {len(df)} 条记录")
    return df


def get_stock_history(code: str, days: int = 120, config: dict = None) -> pd.DataFrame:
    """
    获取指定股票的日线历史K线数据（前复权）。
    使用 baostock（东方财富/AKShare 已被网络屏蔽）。

    参数：
        code  - 股票代码（6位纯数字字符串，如 "000001"）
        days  - 获取最近N个交易日的数据，默认120天
    返回 DataFrame 列：
        date(datetime), open, high, low, close, volume, amount, pct_change
    按日期升序排列。失败时返回空 DataFrame。
    """
    import baostock as bs

    try:
        bs.login()

        prefix = "sh" if code.startswith("6") else "sz"
        bs_code = f"{prefix}.{code}"

        end_date   = datetime.today().strftime("%Y-%m-%d")
        start_date = (datetime.today() - timedelta(days=days * 2)).strftime("%Y-%m-%d")

        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,volume,amount,pctChg",
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="2",
        )

        if rs.error_code != "0":
            print(f"[akshare_source] baostock history 错误: {rs.error_code} {rs.error_msg}")
            return pd.DataFrame()

        data_list = []
        while rs.error_code == "0" and rs.next():
            data_list.append(rs.get_row_data())

        if not data_list:
            print(f"[akshare_source] get_stock_history({code}) 无数据")
            return pd.DataFrame()

        df = pd.DataFrame(data_list, columns=rs.fields)
        df = df.rename(columns={"pctChg": "pct_change"})
        df["date"] = pd.to_datetime(df["date"])

        numeric_cols = ["open", "high", "low", "close", "volume", "amount", "pct_change"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        keep = [c for c in ["date", "open", "high", "low", "close", "volume", "amount", "pct_change"]
                if c in df.columns]
        df = df[keep].sort_values("date").tail(days).reset_index(drop=True)
        return df

    except Exception as e:
        print(f"[akshare_source] get_stock_history({code}) 失败: {e}")
        return pd.DataFrame()

    finally:
        try:
            bs.logout()
        except Exception:
            pass


def get_northbound_flow(config: dict = None) -> pd.DataFrame:
    """
    获取北向资金（沪深港通北向）净流入数据。

    返回 DataFrame 列：
        date(datetime), sh_net_inflow, sz_net_inflow, total_net_inflow
    单位：亿元

    网络失败时返回空 DataFrame 并打印错误。
    """
    try:
        import akshare as ak
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
        import akshare as ak
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

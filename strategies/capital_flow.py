"""
strategies/capital_flow.py
资金流向选股：北向资金近5日持续净流入的股票
依赖：pandas, akshare

通过分析北向个股持仓变动，筛选出连续N日净增持的标的。
"""

import pandas as pd
import akshare as ak
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.fetcher import get_northbound_holdings


# 默认参数
DEFAULT_PARAMS = {
    "min_consecutive_days": 5,     # 最少连续净流入天数
    "min_total_increase": 0,       # 近N日累计增持股数下限（0=只要是净增持即可）
    "markets": ["沪股通", "深股通"], # 要纳入的市场
}


def _get_hsgt_history_by_stock(code: str, market: str, days: int = 10) -> pd.DataFrame:
    """
    获取单只股票的北向持股历史记录（近 days 个交易日）。

    返回 DataFrame 列：date, hold_shares, hold_change
    数据来源：东财沪深港通个股持股历史
    """
    try:
        _start = (datetime.today() - timedelta(days=days * 2)).strftime("%Y%m%d")
        _end   = datetime.today().strftime("%Y%m%d")
        with ThreadPoolExecutor(max_workers=1) as _tex:
            _fut = _tex.submit(
                ak.stock_em_hsgt_individual_detail,
                symbol=code, start_date=_start, end_date=_end, market=market,
            )
            try:
                df = _fut.result(timeout=10)
            except FuturesTimeoutError:
                print(f"[capital_flow] 获取 {code}({market}) 超时（10s）")
                return pd.DataFrame()
        rename_map = {
            "日期": "date",
            "持股数量": "hold_shares",
            "持股变动": "hold_change",
        }
        df = df.rename(columns=rename_map)
        keep = [c for c in rename_map.values() if c in df.columns]
        df = df[keep].copy()
        df["date"] = pd.to_datetime(df["date"])
        for col in ["hold_shares", "hold_change"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df.sort_values("date").reset_index(drop=True)
        return df.tail(days).reset_index(drop=True)
    except Exception as e:
        print(f"[capital_flow] 获取 {code}({market}) 持股历史失败: {e}")
        return pd.DataFrame()


def _is_consecutive_inflow(df: pd.DataFrame, min_days: int) -> bool:
    """
    判断 DataFrame 中 hold_change 是否近 min_days 天连续大于0（净增持）。
    """
    if df.empty or "hold_change" not in df.columns:
        return False
    recent = df["hold_change"].dropna().tail(min_days)
    if len(recent) < min_days:
        return False
    return (recent > 0).all()


def screen(params: dict = None, progress_cb=None) -> tuple:
    """
    资金流向选股：筛选北向资金近N日持续净流入（持续增持）的A股。

    策略说明：
        1. 拉取最新北向持股快照（沪股通+深股通）
        2. 对每只股票拉取历史持仓变动
        3. 判断近 min_consecutive_days 日是否连续净增持
        4. 计算累计增持量，按此排序

    参数：
        params - 筛选参数，支持 DEFAULT_PARAMS 中的所有键

    返回 DataFrame 列：
        code                 - 股票代码
        name                 - 股票名称
        market               - 所属市场（沪股通/深股通）
        hold_shares          - 当前持股数量
        hold_ratio           - 当前持股比例(%)
        consecutive_days     - 实际连续净增持天数
        total_increase       - 近N日累计净增持股数
    """
    cfg = {**DEFAULT_PARAMS, **(params or {})}
    min_days    = cfg["min_consecutive_days"]
    min_increase = cfg["min_total_increase"]
    markets     = cfg["markets"]

    # ── 步骤1：获取当前北向持股快照 ─────────────────────────────────────────
    print("[capital_flow] 正在获取北向持股快照...")
    snapshot = get_northbound_holdings()
    if snapshot.empty:
        print("[capital_flow] 持股快照为空，退出")
        return pd.DataFrame()

    # 只保留指定市场
    if "market" in snapshot.columns:
        snapshot = snapshot[snapshot["market"].isin(markets)]

    if snapshot.empty:
        return pd.DataFrame()

    print(f"[capital_flow] 快照共 {len(snapshot)} 条，开始预筛选...")

    # ── 预筛选：今日 hold_change > 0 才可能满足连续增持条件 ────────────────
    if "hold_change" in snapshot.columns:
        candidates = snapshot[snapshot["hold_change"] > 0].copy()
        print(f"[capital_flow] 预筛选后候选 {len(candidates)} 只（跳过 {len(snapshot) - len(candidates)} 只今日未增持）")
    else:
        candidates = snapshot.copy()

    if candidates.empty:
        return pd.DataFrame()

    records = []
    total = len(candidates)

    # 用于区分 API 失败 vs 不满足条件
    _API_FAIL = "__api_fail__"

    def _check_one(row: pd.Series):
        code        = str(row.get("code", "")).zfill(6)
        name        = row.get("name", "")
        market      = row.get("market", "")
        hold_shares = row.get("hold_shares", 0)
        hold_ratio  = row.get("hold_ratio", 0)

        # ── 步骤2：拉取个股历史持仓变动 ──────────────────────────────────
        hist = _get_hsgt_history_by_stock(code, market, days=min_days + 5)
        if hist is None:
            return _API_FAIL
        if hist.empty:
            return _API_FAIL

        # ── 步骤3：判断连续净增持（验证日期连续性）────────────────────────────
        hist_sorted = hist.sort_values("date").dropna(subset=["hold_change"])
        recent_rows = hist_sorted.tail(min_days)
        if len(recent_rows) < min_days:
            return None

        # 验证相邻交易日差不超过5自然日（最长连休4天+1个交易日）
        dates = pd.to_datetime(recent_rows["date"]).tolist()
        for i in range(1, len(dates)):
            if (dates[i] - dates[i - 1]).days > 5:
                return None  # 日期断层，数据不连续

        recent = recent_rows["hold_change"]
        consecutive = 0
        for chg in reversed(recent.tolist()):
            if chg > 0:
                consecutive += 1
            else:
                break

        if consecutive < min_days:
            return None

        # ── 步骤4：计算累计增持量 ─────────────────────────────────────────
        total_increase = recent[recent > 0].sum()
        if total_increase < min_increase:
            return None

        hold_change_pct = round(total_increase / hold_shares * 100, 4) if hold_shares and hold_shares > 0 else 0.0
        return {
            "code":             code,
            "name":             name,
            "market":           market,
            "hold_shares":      hold_shares,
            "hold_ratio":       hold_ratio,
            "consecutive_days": consecutive,
            "total_increase":   total_increase,
            "hold_change_pct":  hold_change_pct,
        }

    print(f"[capital_flow] 并发分析 {total} 只候选股票（workers=5）...")
    api_fail_count = 0
    done_count = 0
    timeout_count = 0
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(_check_one, row): row for _, row in candidates.iterrows()}
        try:
            for future in as_completed(futures, timeout=180):
                done_count += 1
                item = future.result()
                if item == _API_FAIL:
                    api_fail_count += 1
                elif item is not None:
                    records.append(item)
                if progress_cb:
                    progress_cb(done_count / total)
                if done_count % 10 == 0 or done_count == total:
                    print(f"[capital_flow] 进度 {done_count}/{total}，命中 {len(records)} 只...", end="\r")
        except FuturesTimeoutError:
            timeout_count = total - done_count
            print(f"\n[capital_flow] 总超时（180s），{timeout_count} 只未完成，返回部分结果")
            if progress_cb:
                progress_cb(1.0)

    print()  # 换行

    meta: dict = {"api_fail_count": api_fail_count, "total_candidates": total, "timeout_count": timeout_count}
    if api_fail_count > 0:
        fail_ratio = api_fail_count / total
        if fail_ratio > 0.5:
            print(f"[capital_flow] 警告：{api_fail_count}/{total} 只股票API请求失败（可能被限流），结果可能不完整")
        else:
            print(f"[capital_flow] {api_fail_count} 只股票API请求失败（其余正常）")

    result = pd.DataFrame(records)
    if not result.empty:
        result = result.sort_values(
            ["consecutive_days", "total_increase"],
            ascending=[False, False]
        ).reset_index(drop=True)

    print(f"[capital_flow] 北向资金筛选完成，共选出 {len(result)} 只持续净流入股票")
    return result, meta


def screen_by_aggregate_flow(params: dict = None) -> pd.DataFrame:
    """
    备用策略：使用北向资金每日汇总净流入数据选股。
    当个股历史接口不可用时，改为分析整体北向净流入趋势，
    结合快照中持股变动字段（hold_change）筛选当日增持标的。

    适用场景：个股历史接口受限时的降级方案。

    返回 DataFrame 列：
        code         - 股票代码
        name         - 股票名称
        market       - 市场
        hold_change  - 当日持股变动（正=增持）
        hold_ratio   - 持股比例(%)
    """
    cfg = {**DEFAULT_PARAMS, **(params or {})}
    markets = cfg["markets"]

    print("[capital_flow] 使用聚合快照模式（降级方案）...")
    snapshot = get_northbound_holdings()
    if snapshot.empty:
        return pd.DataFrame()

    if "market" in snapshot.columns:
        snapshot = snapshot[snapshot["market"].isin(markets)]

    # 筛选当日净增持（hold_change > 0）
    if "hold_change" not in snapshot.columns:
        print("[capital_flow] 缺少 hold_change 列，无法筛选")
        return pd.DataFrame()

    result = snapshot[snapshot["hold_change"] > 0].copy()
    result = result.sort_values("hold_change", ascending=False).reset_index(drop=True)

    print(f"[capital_flow] 聚合模式：当日净增持股票 {len(result)} 只")
    return result


if __name__ == "__main__":
    print("=== 测试 strategies/capital_flow.py ===")

    print("\n[1] 主策略：近5日持续净流入")
    result = screen({"min_consecutive_days": 5})
    if not result.empty:
        print(result.to_string(index=False))
    else:
        print("无满足条件股票，尝试降级方案...")

        print("\n[2] 降级方案：当日净增持")
        result2 = screen_by_aggregate_flow()
        if not result2.empty:
            cols = [c for c in ["code", "name", "market", "hold_change", "hold_ratio"]
                    if c in result2.columns]
            print(result2[cols].head(10).to_string(index=False))
        else:
            print("降级方案也未获取到数据")

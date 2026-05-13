"""
strategies/fundamental.py
基本面选股策略
依赖：pandas

函数签名：screen(df: pd.DataFrame, params: dict) -> pd.DataFrame
"""

import pandas as pd


# 默认筛选参数（可被调用方 params 覆盖）
DEFAULT_PARAMS = {
    "pe_min": 0,           # PE下限（剔除负PE/亏损股）
    "pe_max": 80,          # PE上限
    "pb_max": 5.0,         # PB上限
    "total_mv_min": 20,    # 总市值下限（亿元）—— 小盘下边界
    "total_mv_max": 1000,  # 总市值上限（亿元）—— 中盘上边界
    "roe_min": 0.0,        # ROE下限(%)，0=不过滤；ROE近似值=PB/PE×100
    "pct_exclude_limit": 9.0,  # 涨跌幅绝对值超过此阈值视为涨停/跌停（科创板/创业板为20%）
}


def screen(df: pd.DataFrame, params: dict = None) -> pd.DataFrame:
    """
    基本面选股：对实时行情 DataFrame 做多条件过滤。

    参数：
        df     - get_all_a_stock_realtime() 返回的 DataFrame
                 必须包含列：pe, pb, total_mv, pct_change
        params - 筛选阈值字典，缺少的键用 DEFAULT_PARAMS 补全

    返回：
        符合条件的股票 DataFrame（保持原始列），按总市值升序排列
    """
    if df is None or df.empty:
        print("[fundamental] 输入 DataFrame 为空，跳过筛选")
        return pd.DataFrame()

    # 合并用户参数与默认参数
    cfg = {**DEFAULT_PARAMS, **(params or {})}

    result = df.copy()
    before = len(result)

    # ── 1. 必须有有效的 PE、PB、市值数据 ──────────────────────────────────────
    required_cols = ["pe", "pb", "total_mv", "pct_change"]
    missing = [c for c in required_cols if c not in result.columns]
    if missing:
        print(f"[fundamental] 缺少必要列: {missing}，无法筛选")
        return pd.DataFrame()

    result = result.dropna(subset=required_cols)

    # ── 1b. 派生 ROE 近似值（ROE ≈ PB/PE × 100，PE clip防止除以0）────────────
    result["roe_approx"] = (result["pb"] / result["pe"].clip(lower=1) * 100).round(2)

    # ── 2. PE 范围筛选（剔除亏损股及高估值） ──────────────────────────────────
    pe_min = cfg["pe_min"]
    pe_max = cfg["pe_max"]
    result = result[(result["pe"] > pe_min) & (result["pe"] < pe_max)]
    print(f"[fundamental] PE({pe_min}~{pe_max})筛选后: {len(result)} 只（原 {before} 只）")

    # ── 3. PB 范围筛选 ─────────────────────────────────────────────────────────
    pb_max = cfg["pb_max"]
    result = result[result["pb"] < pb_max]
    print(f"[fundamental] PB(<{pb_max})筛选后: {len(result)} 只")

    # ── 4. 总市值范围筛选（中小盘）────────────────────────────────────────────
    mv_min = cfg["total_mv_min"]
    mv_max = cfg["total_mv_max"]
    result = result[(result["total_mv"] >= mv_min) & (result["total_mv"] <= mv_max)]
    print(f"[fundamental] 市值({mv_min}~{mv_max}亿)筛选后: {len(result)} 只")

    # ── 5. ROE 下限筛选（用近似值 PB/PE×100） ────────────────────────────────
    roe_min = cfg["roe_min"]
    if roe_min > 0:
        result = result[result["roe_approx"] >= roe_min]
        print(f"[fundamental] ROE(≥{roe_min}%)筛选后: {len(result)} 只")

    # ── 6. 排除涨停/跌停（按板块动态阈值：主板10%，创业板/科创板20%，北交所30%）
    def _limit_pct(code: str) -> float:
        s = str(code)
        if s.startswith("688") or s.startswith("300") or s.startswith("301"):
            return 20.0
        if s.startswith("8") or s.startswith("4"):
            return 30.0
        return 10.0

    if "code" in result.columns:
        result = result[result.apply(
            lambda row: abs(row["pct_change"]) < _limit_pct(row["code"]), axis=1
        )]
    else:
        limit_pct = cfg["pct_exclude_limit"]
        result = result[result["pct_change"].abs() < limit_pct]
    print(f"[fundamental] 排除涨跌停（按板块阈值）筛选后: {len(result)} 只")

    # ── 7. 排除 ST / *ST / 退市整理股 ────────────────────────────────────────
    if "name" in result.columns:
        result = result[~result["name"].str.contains(r"ST|退", na=False, regex=True)]
        print(f"[fundamental] 排除ST/退市后: {len(result)} 只")

    # ── 8. 按总市值升序排列（优先小盘）──────────────────────────────────────
    result = result.sort_values("total_mv", ascending=True).reset_index(drop=True)

    print(f"[fundamental] 最终选出 {len(result)} 只股票")
    return result


if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from data.fetcher import get_all_a_stock_realtime

    print("=== 测试 strategies/fundamental.py ===")
    df_spot = get_all_a_stock_realtime()

    if not df_spot.empty:
        result = screen(df_spot)
        print(f"\n基本面筛选结果（前10条）：")
        cols = [c for c in ["code", "name", "price", "pct_change", "pe", "pb", "total_mv"]
                if c in result.columns]
        print(result[cols].head(10).to_string(index=False))
    else:
        print("实时行情获取失败，无法测试")

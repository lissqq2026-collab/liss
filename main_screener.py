"""
main_screener.py
A股选股工具主入口：依次执行基本面 → 技术面 → 资金流向筛选
用法：python main_screener.py
"""

import pandas as pd
from data.fetcher import get_all_a_stock_realtime
from strategies.fundamental import screen as fundamental_screen
from strategies.technical import screen as technical_screen
from strategies.capital_flow import screen as capital_flow_screen


def run_pipeline():
    print("=" * 60)
    print("  A股选股工具 - 三阶段筛选流水线")
    print("=" * 60)

    # ── 阶段1：基本面筛选 ──────────────────────────────────────────────────
    print("\n【阶段1】获取全市场实时行情...")
    df_all = get_all_a_stock_realtime()

    print("\n【阶段1】基本面筛选（PE/PB/市值/排除涨跌停）...")
    fundamental_params = {
        "pe_min": 0,
        "pe_max": 30,
        "pb_max": 3.0,
        "total_mv_min": 20,
        "total_mv_max": 500,
        "pct_exclude_limit": 9.0,
    }
    df_fundamental = fundamental_screen(df_all, fundamental_params)

    if df_fundamental.empty:
        print("基本面筛选结果为空，流程终止")
        return

    codes_fundamental = df_fundamental["code"].tolist()
    print(f"\n基本面入选：{len(codes_fundamental)} 只")

    # ── 阶段2：技术面筛选 ──────────────────────────────────────────────────
    print("\n【阶段2】技术面筛选（均线/MACD/KDJ/量价）...")
    technical_params = {
        "ma_periods": [5, 10, 20, 60],
        "macd_fast": 12,
        "macd_slow": 26,
        "macd_signal": 9,
        "kdj_k_oversold": 20,
        "volume_amplify_ratio": 1.5,
        "volume_ma_period": 20,
        "history_days": 120,
        "require_all": False,   # 满足≥1个技术条件即入选
    }
    df_technical = technical_screen(codes_fundamental, technical_params)

    if df_technical.empty:
        print("技术面筛选结果为空，流程终止")
        return

    codes_technical = df_technical["code"].tolist()

    # 合并基本面与技术面结果
    df_stage2 = df_fundamental[df_fundamental["code"].isin(codes_technical)].copy()
    df_stage2 = df_stage2.merge(df_technical, on="code", how="left")
    df_stage2 = df_stage2.sort_values("signal_count", ascending=False).reset_index(drop=True)

    print(f"\n技术面入选：{len(df_stage2)} 只")

    # ── 阶段3：资金流向筛选（可选叠加） ───────────────────────────────────
    print("\n【阶段3】北向资金筛选（近5日持续净流入）...")
    capital_params = {
        "min_consecutive_days": 5,
        "min_total_increase": 0,
        "markets": ["沪股通", "深股通"],
    }
    df_capital = capital_flow_screen(capital_params)

    # ── 汇总输出 ───────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  最终筛选结果")
    print("=" * 60)

    print(f"\n基本面候选：{len(codes_fundamental)} 只")
    print(f"技术面叠加后：{len(df_stage2)} 只")
    if not df_capital.empty:
        print(f"北向持续净流入：{len(df_capital)} 只")

        # 三重共振：同时满足基本面+技术面+北向净流入
        triple_codes = set(codes_technical) & set(df_capital["code"].tolist())
        df_triple = df_stage2[df_stage2["code"].isin(triple_codes)].reset_index(drop=True)
        print(f"\n三重共振（基本面+技术面+北向）：{len(df_triple)} 只")
        if not df_triple.empty:
            show_cols = [c for c in ["code", "name", "price", "pct_change",
                                     "pe", "pb", "total_mv", "signal_count"]
                         if c in df_triple.columns]
            print(df_triple[show_cols].to_string(index=False))
    else:
        print("北向资金数据不可用，跳过三重筛选")

    print("\n技术面+基本面 Top20：")
    show_cols = [c for c in ["code", "name", "price", "pct_change",
                              "pe", "pb", "total_mv", "signal_count",
                              "ma_bullish", "macd_golden_cross",
                              "kdj_oversold_rec", "vol_price_match"]
                 if c in df_stage2.columns]
    print(df_stage2[show_cols].head(20).to_string(index=False))

    return df_stage2


if __name__ == "__main__":
    run_pipeline()

"""
app.py
A股选股工具 Streamlit 前端
"""

import streamlit as st
import pandas as pd

st.set_page_config(layout="wide", page_title="A股选股工具")

# ── 缓存包装：避免频繁拉取，TTL=10分钟 ──────────────────────────────────────

@st.cache_data(ttl=600)
def cached_get_all_a_stock_realtime():
    from data.fetcher import get_all_a_stock_realtime
    return get_all_a_stock_realtime()


@st.cache_data(ttl=600)
def cached_technical_screen(codes_tuple, params_frozen):
    from strategies.technical import screen as technical_screen
    return technical_screen(list(codes_tuple), dict(params_frozen))


@st.cache_data(ttl=600)
def cached_capital_flow_screen(params_frozen):
    from strategies.capital_flow import screen as capital_flow_screen
    return capital_flow_screen(dict(params_frozen))


# ── 颜色高亮：A股习惯（涨红跌绿） ──────────────────────────────────────────

def highlight_pct_change(val):
    if pd.isna(val):
        return ""
    color = "red" if val > 0 else ("green" if val < 0 else "")
    return f"color: {color}" if color else ""


def style_df(df: pd.DataFrame) -> pd.io.formats.style.Styler:
    styler = df.style
    if "pct_change" in df.columns:
        styler = styler.map(highlight_pct_change, subset=["pct_change"])
    return styler


# ── 侧边栏 ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("A 股选股工具")

    with st.expander("基本面参数", expanded=True):
        pe_min = st.slider("PE 最小值", min_value=0, max_value=100, value=0, step=1)
        pe_max = st.slider("PE 最大值", min_value=1, max_value=200, value=30, step=1)
        pb_max = st.number_input("PB 上限", min_value=0.1, max_value=20.0, value=3.0, step=0.1)
        mv_min = st.number_input("市值下限（亿）", min_value=1.0, max_value=10000.0, value=20.0, step=1.0)
        mv_max = st.number_input("市值上限（亿）", min_value=1.0, max_value=100000.0, value=500.0, step=10.0)
        pct_exclude = st.number_input("排除涨跌停阈值（%）", min_value=0.0, max_value=20.0, value=9.0, step=0.5)

    with st.expander("技术面参数", expanded=False):
        require_all = st.checkbox(
            "要求满足所有技术条件（默认：满足任意1条即可）",
            value=False,
        )

    with st.expander("资金流向参数", expanded=False):
        min_consecutive_days = st.slider("连续净流入天数", min_value=1, max_value=20, value=5)
        markets = st.multiselect(
            "市场",
            options=["沪股通", "深股通"],
            default=["沪股通", "深股通"],
        )

    run_btn = st.button("开始筛选", type="primary", use_container_width=True)

# ── 主区域 ───────────────────────────────────────────────────────────────────

st.title("A 股选股工具")

if not run_btn:
    st.info("请在左侧设置参数后点击「开始筛选」。")
    st.stop()

# 执行筛选
with st.spinner("正在筛选，请稍候..."):
    try:
        # 阶段1：基本面筛选
        from strategies.fundamental import screen as fundamental_screen

        df_all = cached_get_all_a_stock_realtime()
        if df_all.empty:
            st.error("实时行情获取失败，请检查网络后重试。")
            st.stop()

        fundamental_params = {
            "pe_min": pe_min,
            "pe_max": pe_max,
            "pb_max": pb_max,
            "total_mv_min": mv_min,
            "total_mv_max": mv_max,
            "pct_exclude_limit": pct_exclude,
        }
        df_fundamental = fundamental_screen(df_all, fundamental_params)
        n_fundamental = len(df_fundamental)

        # 阶段2：技术面筛选
        if df_fundamental.empty:
            df_stage2 = pd.DataFrame()
            n_technical = 0
        else:
            codes_fundamental = df_fundamental["code"].tolist()
            technical_params = {
                "ma_periods": [5, 10, 20, 60],
                "macd_fast": 12,
                "macd_slow": 26,
                "macd_signal": 9,
                "kdj_k_oversold": 20,
                "volume_amplify_ratio": 1.5,
                "volume_ma_period": 20,
                "history_days": 120,
                "require_all": require_all,
            }
            df_technical = cached_technical_screen(
                tuple(codes_fundamental),
                tuple(sorted(technical_params.items())),
            )

            if df_technical.empty:
                df_stage2 = pd.DataFrame()
                n_technical = 0
            else:
                codes_technical = df_technical["code"].tolist()
                df_stage2 = df_fundamental[df_fundamental["code"].isin(codes_technical)].copy()
                df_stage2 = df_stage2.merge(df_technical, on="code", how="left")
                df_stage2 = df_stage2.sort_values("signal_count", ascending=False).reset_index(drop=True)
                n_technical = len(df_stage2)

        # 阶段3：北向资金筛选
        capital_params = {
            "min_consecutive_days": min_consecutive_days,
            "min_total_increase": 0,
            "markets": markets,
        }
        df_capital = cached_capital_flow_screen(tuple(sorted(
            (k, tuple(v) if isinstance(v, list) else v)
            for k, v in capital_params.items()
        )))

        # 三重共振
        if not df_stage2.empty and not df_capital.empty:
            triple_codes = set(df_stage2["code"].tolist()) & set(df_capital["code"].tolist())
            df_triple = df_stage2[df_stage2["code"].isin(triple_codes)].reset_index(drop=True)
        else:
            df_triple = pd.DataFrame()
        n_triple = len(df_triple)

    except Exception as e:
        st.error(f"筛选过程出错：{e}")
        st.stop()

# ── 漏斗指标 ─────────────────────────────────────────────────────────────────

col1, col2, col3 = st.columns(3)
col1.metric("基本面入选", f"{n_fundamental} 只")
col2.metric("技术面叠加后", f"{n_technical} 只")
col3.metric("三重共振", f"{n_triple} 只")

st.divider()

# ── 三个 Tab ─────────────────────────────────────────────────────────────────

tab1, tab2, tab3 = st.tabs(["技术+基本面 Top20", "三重共振", "北向资金"])

SHOW_COLS = ["code", "name", "price", "pct_change", "pe", "pb", "total_mv", "signal_count"]

with tab1:
    if df_stage2.empty:
        st.warning("技术面筛选无结果。")
    else:
        cols = [c for c in SHOW_COLS if c in df_stage2.columns]
        df_top20 = df_stage2[cols].head(20)
        st.caption(f"共 {n_technical} 只，展示前 20 只（按信号数量排序）")
        st.dataframe(style_df(df_top20), use_container_width=True)

with tab2:
    if df_triple.empty:
        st.warning("暂无同时满足三重条件的股票。")
    else:
        cols = [c for c in SHOW_COLS if c in df_triple.columns]
        st.caption(f"共 {n_triple} 只（基本面 + 技术面 + 北向持续净流入）")
        st.dataframe(style_df(df_triple[cols]), use_container_width=True)

with tab3:
    if df_capital.empty:
        st.warning("北向资金数据获取失败或无符合条件的股票。")
    else:
        st.caption(f"共 {len(df_capital)} 只（北向连续净流入 ≥ {min_consecutive_days} 天）")
        st.dataframe(df_capital, use_container_width=True)

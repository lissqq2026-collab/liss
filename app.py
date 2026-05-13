"""
app.py
A股选股工具 Streamlit 前端
"""

import sys
import os

# 确保项目根目录在 sys.path 中，避免子模块导入失败
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import datetime
import streamlit as st
import pandas as pd
from io import BytesIO

st.set_page_config(layout="wide", page_title="A股选股工具")

# ── 缓存包装：避免频繁拉取，TTL=10分钟 ──────────────────────────────────────

@st.cache_data(ttl=600)
def cached_get_all_a_stock_realtime(source_key: str):
    from data.fetcher import get_all_a_stock_realtime
    return get_all_a_stock_realtime()


def cached_technical_screen(codes_tuple, params_frozen, source_key: str, progress_cb=None):
    """Session-state backed cache for technical screening with optional progress callback."""
    _cache_key = ("tech_screen", codes_tuple, params_frozen, source_key)
    cached = st.session_state.get("_tech_cache")
    if cached and cached.get("key") == _cache_key:
        return cached["df"]
    from strategies.technical import screen as technical_screen
    df = technical_screen(list(codes_tuple), dict(params_frozen), progress_cb=progress_cb)
    st.session_state["_tech_cache"] = {"key": _cache_key, "df": df}
    return df


def cached_capital_flow_screen(params_frozen, source_key: str, progress_cb=None):
    """Session-state backed cache for northbound capital flow screening."""
    _cache_key = ("capital_flow", params_frozen, source_key)
    cached = st.session_state.get("_capital_cache")
    if cached and cached.get("key") == _cache_key:
        return cached["result"]
    from strategies.capital_flow import screen as capital_flow_screen
    result = capital_flow_screen(dict(params_frozen), progress_cb=progress_cb)
    st.session_state["_capital_cache"] = {"key": _cache_key, "result": result}
    return result


# ── 颜色高亮：A股习惯（涨红跌绿） ──────────────────────────────────────────

def highlight_pct_change(val):
    if pd.isna(val):
        return ""
    color = "red" if val > 0 else ("green" if val < 0 else "")
    return f"color: {color}" if color else ""


def style_df(df: pd.DataFrame):
    styler = df.style
    if "pct_change" in df.columns:
        styler = styler.map(highlight_pct_change, subset=["pct_change"])
    return styler


def _watchlist_action(code: str, name: str, btn_key: str) -> None:
    """渲染单只股票的自选股加入/移出按钮（紧凑版，嵌入列中使用）。"""
    _in_wl = db_wl.is_in_watchlist(code)
    _label = "✅ 已加入" if _in_wl else "⭐ 加入自选"
    if st.button(_label, key=btn_key, use_container_width=True):
        if _in_wl:
            db_wl.remove_from_watchlist(code)
            st.toast(f"已移出：{code}", icon="🗑️")
        else:
            db_wl.add_to_watchlist(code, name)
            st.toast(f"已加入：{code}", icon="⭐")
        st.rerun()


# ── 侧边栏 ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.title("A 股选股工具")

    with st.expander("数据源配置", expanded=True):
        data_source = st.radio(
            "选择数据源",
            options=["AKShare（免费，无需配置）", "Tushare Pro（需 Token）", "Baostock（免费，历史数据更准确）"],
            index=0,
        )

        tushare_token = ""
        if "Tushare" in data_source:
            tushare_token = st.text_input(
                "Tushare Token",
                type="password",
                placeholder="请输入 Tushare Pro Token",
                help="在 tushare.pro 注册后获取，免费账户有120积分",
            )
            if not tushare_token:
                st.warning("请输入 Token 后再运行筛选。")

        # 各数据源说明
        source_info = {
            "AKShare": "✅ 实时行情 ✅ 历史K线 ✅ 北向资金",
            "Tushare": "✅ 实时行情 ✅ 历史K线（2008年后高质量）✅ 北向资金流向 ❌ 个股持仓（需高积分）",
            "Baostock": "⚠️ 实时行情（降级AKShare）✅ 历史K线（交易所权威数据）⚠️ 北向资金（降级AKShare）",
        }
        for key, info in source_info.items():
            if key in data_source:
                st.caption(info)
                break

    with st.expander("基本面参数", expanded=True):
        pe_min = st.slider("PE 最小值", min_value=0, max_value=100, value=0, step=1)
        pe_max = st.slider("PE 最大值", min_value=1, max_value=200, value=100, step=1)
        pb_max = st.number_input("PB 上限", min_value=0.1, max_value=20.0, value=5.0, step=0.1)
        st.caption("市值快选")
        _mv_presets = {"小盘": (20.0, 200.0), "中盘": (200.0, 1000.0), "大盘": (1000.0, 10000.0), "全部": (1.0, 100000.0)}
        _mv_btn_cols = st.columns(len(_mv_presets))
        for _i, (_label, (_vmin, _vmax)) in enumerate(_mv_presets.items()):
            with _mv_btn_cols[_i]:
                if st.button(_label, key=f"mv_preset_{_label}", use_container_width=True):
                    st.session_state["_mv_min_val"] = _vmin
                    st.session_state["_mv_max_val"] = _vmax
                    st.rerun()
        mv_min = st.number_input("市值下限（亿）", min_value=1.0, max_value=10000.0,
                                  value=st.session_state.get("_mv_min_val", 20.0), step=1.0)
        mv_max = st.number_input("市值上限（亿）", min_value=1.0, max_value=100000.0,
                                  value=st.session_state.get("_mv_max_val", 1000.0), step=10.0)
        roe_min = st.slider("ROE 最低值（%，0=不过滤）", min_value=0, max_value=50, value=0, step=1,
                            help="ROE ≈ PB/PE×100，为近似估算值")
    with st.expander("技术面参数", expanded=True):
        st.markdown("**均线条件**")
        check_ma_bullish = st.checkbox("日线均线多头排列（MA5>MA10>MA20>MA60）", value=True)
        check_price_above_ma20 = st.checkbox("收盘价在 MA20 上方", value=False)
        check_weekly_ma_bullish = st.checkbox("周线均线多头排列（WMA5>WMA10>WMA20）", value=False)

        st.markdown("**MACD 条件**")
        check_macd_golden_cross = st.checkbox("MACD 金叉（DIF 上穿 DEA）", value=True)
        check_macd_above_zero = st.checkbox("DIF 和 DEA 均在零轴上方", value=False)
        check_macd_hist_expand = st.checkbox("MACD 红柱连续 3 日扩大", value=False)

        st.markdown("**KDJ 条件**")
        check_kdj_oversold_rec = st.checkbox("KDJ 超卖回升", value=True)
        kdj_k_oversold = st.slider("KDJ 超卖阈值（K <）", min_value=5, max_value=40, value=30)
        check_kdj_golden_cross = st.checkbox("KDJ 金叉（K 上穿 D）", value=False)

        st.markdown("**量价条件**")
        check_vol_price = st.checkbox("放量上涨（成交量 ≥ N 日均量 × 倍数）", value=True)
        volume_amplify_ratio = st.slider("放量倍数", min_value=1.0, max_value=5.0, value=2.0, step=0.1)

        st.markdown("**RSI 条件**")
        check_rsi_oversold_rec = st.checkbox("RSI 超卖回升", value=False)
        rsi_oversold = st.slider("RSI 超卖阈值（RSI <）", min_value=10, max_value=50, value=25)

        st.markdown("**动量条件**")
        check_momentum = st.checkbox("N 日涨幅为正", value=False)
        momentum_days = st.slider("动量周期（日）", min_value=1, max_value=60, value=5)

        st.divider()
        min_signals = st.number_input(
            "最少满足条件数量（已启用条件中至少满足 N 个）",
            min_value=1, max_value=11, value=2, step=1,
        )

    with st.expander("资金流向参数", expanded=False):
        min_consecutive_days = st.slider("连续净流入天数", min_value=1, max_value=20, value=5)
        markets = st.multiselect(
            "市场",
            options=["沪股通", "深股通"],
            default=["沪股通", "深股通"],
        )

    run_btn = st.button("开始筛选", type="primary", use_container_width=True)

from data.db import manager as db_wl


# ── 主区域 ───────────────────────────────────────────────────────────────────

st.title("A 股选股工具")

if run_btn:
    # 根据用户选择配置数据源
    if "Tushare" in data_source:
        if not tushare_token:
            st.error("请先在左侧输入 Tushare Token。")
            st.stop()
        from data.fetcher import set_data_source
        set_data_source("tushare", {"token": tushare_token})
        source_key = "tushare"
    elif "Baostock" in data_source:
        from data.fetcher import set_data_source
        set_data_source("baostock")
        source_key = "baostock"
    else:
        from data.fetcher import set_data_source
        set_data_source("akshare")
        source_key = "akshare"

    # 执行筛选（三阶段可视化进度）
    _prog = st.container(border=True)
    with _prog:
        st.markdown("#### 🔍 正在筛选…")
        _s1 = st.status("阶段 1／3　基本面筛选", expanded=True)
        _s2 = st.status("阶段 2／3　技术面筛选", expanded=False)
        _s3 = st.status("阶段 3／3　北向资金筛选", expanded=False)

    try:
        # 阶段1：基本面筛选
        with _s1:
            from strategies.fundamental import screen as fundamental_screen

            st.write("正在拉取全市场实时行情…")
            df_all = cached_get_all_a_stock_realtime(source_key)
            if df_all.empty:
                st.error("实时行情获取失败，请检查网络后重试。")
                st.stop()

            st.write("正在按基本面参数筛选…")
            fundamental_params = {
                "pe_min": pe_min,
                "pe_max": pe_max,
                "pb_max": pb_max,
                "total_mv_min": mv_min,
                "total_mv_max": mv_max,
                "roe_min": roe_min,
            }
            df_fundamental = fundamental_screen(df_all, fundamental_params)
            n_fundamental = len(df_fundamental)
        _s1.update(label=f"✅ 阶段 1／3　基本面筛选　→ {n_fundamental} 只", state="complete", expanded=False)

        # 阶段2：技术面筛选
        with _s2:
            _s2.update(state="running", expanded=True)
            if df_fundamental.empty:
                df_stage2 = pd.DataFrame()
                n_technical = 0
                st.write("基本面无结果，跳过技术面筛选。")
            else:
                codes_fundamental = df_fundamental["code"].tolist()
                technical_params = {
                    "ma_periods": [5, 10, 20, 60],
                    "macd_fast": 12,
                    "macd_slow": 26,
                    "macd_signal": 9,
                    "kdj_k_oversold": kdj_k_oversold,
                    "volume_amplify_ratio": volume_amplify_ratio,
                    "volume_ma_period": 20,
                    "rsi_period": 14,
                    "rsi_oversold": rsi_oversold,
                    "momentum_days": momentum_days,
                    "history_days": 150,
                    "min_signals": int(min_signals),
                    "check_ma_bullish": check_ma_bullish,
                    "check_price_above_ma20": check_price_above_ma20,
                    "check_weekly_ma_bullish": check_weekly_ma_bullish,
                    "check_macd_golden_cross": check_macd_golden_cross,
                    "check_macd_above_zero": check_macd_above_zero,
                    "check_macd_hist_expand": check_macd_hist_expand,
                    "check_kdj_oversold_rec": check_kdj_oversold_rec,
                    "check_kdj_golden_cross": check_kdj_golden_cross,
                    "check_vol_price": check_vol_price,
                    "check_rsi_oversold_rec": check_rsi_oversold_rec,
                    "check_momentum": check_momentum,
                }
                params_hashable = tuple(sorted(
                    (k, tuple(v) if isinstance(v, list) else v)
                    for k, v in technical_params.items()
                ))
                st.write(f"正在对 {n_fundamental} 只股票进行技术指标计算…")
                _tech_cache_key = ("tech_screen", tuple(codes_fundamental), params_hashable, source_key)
                _is_cached = (st.session_state.get("_tech_cache", {}).get("key") == _tech_cache_key)
                if _is_cached:
                    _prog_bar = None
                else:
                    _prog_bar = st.progress(0, text=f"技术指标计算中…  0 / {n_fundamental}")

                def _tech_progress(frac):
                    if _prog_bar:
                        done = int(frac * n_fundamental)
                        _prog_bar.progress(frac, text=f"技术指标计算中…  {done} / {n_fundamental}")

                df_technical = cached_technical_screen(
                    tuple(codes_fundamental),
                    params_hashable,
                    source_key,
                    progress_cb=_tech_progress,
                )
                if _prog_bar:
                    _prog_bar.empty()

                if df_technical.empty:
                    df_stage2 = pd.DataFrame()
                    n_technical = 0
                else:
                    codes_technical = df_technical["code"].tolist()
                    df_stage2 = df_fundamental[df_fundamental["code"].isin(codes_technical)].copy()
                    df_stage2 = df_stage2.merge(df_technical, on="code", how="left")
                    _sort_keys = ["signal_count"] + (["amount"] if "amount" in df_stage2.columns else [])
                    df_stage2 = df_stage2.sort_values(_sort_keys, ascending=False).reset_index(drop=True)
                    n_technical = len(df_stage2)
        _s2.update(label=f"✅ 阶段 2／3　技术面筛选　→ {n_technical} 只", state="complete", expanded=False)

        # 阶段3：北向资金筛选
        with _s3:
            _s3.update(state="running", expanded=True)
            capital_params = {
                "min_consecutive_days": min_consecutive_days,
                "min_total_increase": 0,
                "markets": markets,
            }
            _capital_params_key = tuple(sorted(
                (k, tuple(v) if isinstance(v, list) else v)
                for k, v in capital_params.items()
            ))
            _capital_cache_key = ("capital_flow", _capital_params_key, source_key)
            _cf_cached = st.session_state.get("_capital_cache", {}).get("key") == _capital_cache_key

            _cf_prog_bar = None
            if _cf_cached:
                st.write("北向资金数据已缓存，直接复用")
            else:
                st.write("正在分析北向资金持仓，候选较多时最长等待 3 分钟…")
                _cf_prog_bar = st.progress(0, text="北向资金分析中…")

            def _cf_progress(frac):
                if _cf_prog_bar:
                    _cf_prog_bar.progress(min(frac, 1.0), text=f"北向资金分析中…  {int(frac * 100)}%")

            df_capital, _cf_meta = cached_capital_flow_screen(
                _capital_params_key,
                source_key,
                progress_cb=None if _cf_cached else _cf_progress,
            )
            if _cf_prog_bar:
                _cf_prog_bar.empty()
        _s3.update(label=f"✅ 阶段 3／3　北向资金筛选　→ {len(df_capital)} 只", state="complete", expanded=False)

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

    # 将筛选结果写入 session state，行点击触发的 rerun 可直接复用
    st.session_state["screen_results"] = {
        "df_stage2":     df_stage2,
        "df_triple":     df_triple,
        "df_capital":    df_capital,
        "_cf_meta":      _cf_meta,
        "n_fundamental": n_fundamental,
        "n_technical":   n_technical,
        "n_triple":      n_triple,
    }

elif "screen_results" in st.session_state:
    # 行点击等非筛选 rerun：直接读取上次结果
    _r = st.session_state["screen_results"]
    df_stage2     = _r["df_stage2"]
    df_triple     = _r["df_triple"]
    df_capital    = _r["df_capital"]
    _cf_meta      = _r.get("_cf_meta", {})
    n_fundamental = _r["n_fundamental"]
    n_technical   = _r["n_technical"]
    n_triple      = _r["n_triple"]

else:
    st.markdown("### 欢迎使用 A股三阶段选股工具")
    c1, c2, c3 = st.columns(3)
    with c1:
        with st.container(border=True):
            st.markdown("**第一阶段：基本面**")
            st.caption("市值、PE/PB 范围过滤，快速缩小股票池")
    with c2:
        with st.container(border=True):
            st.markdown("**第二阶段：技术面**")
            st.caption("均线、MACD、KDJ、量价、RSI 多信号共振筛选")
    with c3:
        with st.container(border=True):
            st.markdown("**第三阶段：北向资金**")
            st.caption("沪深港通持股变动验证主力资金方向")
    st.info("在左侧设置筛选参数后点击「开始筛选」即可开始。", icon="👈")
    st.stop()

# ── 漏斗指标 ─────────────────────────────────────────────────────────────────

col1, col2, col3 = st.columns(3)
col1.metric("基本面入选", f"{n_fundamental} 只")
_tech_pct = f"{n_technical / n_fundamental * 100:.1f}%" if n_fundamental else "—"
col2.metric("技术面叠加后", f"{n_technical} 只", delta=f"通过率 {_tech_pct}", delta_color="off")
_triple_pct = f"{n_triple / n_technical * 100:.1f}%" if n_technical else "—"
col3.metric("三重共振", f"{n_triple} 只", delta=f"通过率 {_triple_pct}", delta_color="off")

st.divider()

# ── 三个 Tab ─────────────────────────────────────────────────────────────────

# ── 列配置：格式化数字显示（A股风格）──────────────────────────────────────────
_COL_CONFIG = {
    "code":              st.column_config.TextColumn("代码"),
    "name":              st.column_config.TextColumn("名称"),
    "price":             st.column_config.NumberColumn("价格", format="%.2f"),
    "pct_change":        st.column_config.NumberColumn("涨跌幅(%)", format="%+.2f"),
    "pe":                st.column_config.NumberColumn("PE(TTM)", format="%.1f"),
    "pb":                st.column_config.NumberColumn("PB", format="%.2f"),
    "total_mv":          st.column_config.NumberColumn("市值(亿)", format="%.1f"),
    "turnover_rate":     st.column_config.NumberColumn("换手率(%)", format="%.2f"),
    "roe_approx":        st.column_config.NumberColumn("ROE≈(%)", format="%.1f"),
    "signal_count":      st.column_config.NumberColumn("信号数", format="%d"),
    "volume":            st.column_config.NumberColumn("成交量(手)", format="%.0f"),
    "amount":            st.column_config.NumberColumn("成交额(万)", format="%.0f"),
    "vol_ratio":         st.column_config.NumberColumn("量比", format="%.2f"),
    # 技术信号列：显示为可视复选框
    "ma_bullish":        st.column_config.CheckboxColumn("均线多头"),
    "price_above_ma20":  st.column_config.CheckboxColumn("价在MA20上"),
    "weekly_ma_bullish": st.column_config.CheckboxColumn("周线多头"),
    "macd_golden_cross": st.column_config.CheckboxColumn("MACD金叉"),
    "macd_above_zero":   st.column_config.CheckboxColumn("MACD零轴上"),
    "macd_hist_expand":  st.column_config.CheckboxColumn("MACD柱放大"),
    "kdj_oversold_rec":  st.column_config.CheckboxColumn("KDJ超卖回升"),
    "kdj_golden_cross":  st.column_config.CheckboxColumn("KDJ金叉"),
    "vol_price_match":   st.column_config.CheckboxColumn("量价配合"),
    "rsi_oversold_rec":  st.column_config.CheckboxColumn("RSI超卖回升"),
    "momentum":          st.column_config.CheckboxColumn("动量正"),
}

tab1, tab2, tab3 = st.tabs(["技术+基本面", "三重共振", "北向资金"])

BASE_COLS = ["code", "name", "price", "pct_change", "pe", "pb", "roe_approx", "total_mv", "turnover_rate", "amount", "signal_count"]
SIGNAL_COLS = [
    "ma_bullish", "price_above_ma20", "weekly_ma_bullish",
    "macd_golden_cross", "macd_above_zero", "macd_hist_expand",
    "kdj_oversold_rec", "kdj_golden_cross",
    "vol_price_match", "rsi_oversold_rec", "momentum",
]

with tab1:
    if df_stage2.empty:
        st.warning("技术面筛选无结果。")
    else:
        cols = [c for c in BASE_COLS + SIGNAL_COLS if c in df_stage2.columns]
        _top_n = st.slider("展示数量", min_value=10, max_value=100, value=20, step=10, key="top_n_t1")
        df_top20 = df_stage2[cols].head(_top_n)
        st.caption(f"共 {n_technical} 只，展示前 {_top_n} 只（按信号数量排序）")
        _kl_opts_t1 = ["请选择股票"] + [
            f"{r['code']}  {r.get('name', r['code'])}" for r in df_top20.to_dict("records")
        ]
        _t1_ev = st.dataframe(
            style_df(df_top20),
            use_container_width=True,
            column_config=_COL_CONFIG,
            selection_mode="single-row",
            on_select="rerun",
            key="t1_table",
        )
        if _t1_ev.selection.rows:
            _t1_new_sel = _kl_opts_t1[_t1_ev.selection.rows[0] + 1]
            st.session_state.pop("kl_t1_sel", None)
            st.session_state["kl_t1_sel"] = _t1_new_sel
        # 导出按钮
        _buf1 = BytesIO()
        with pd.ExcelWriter(_buf1, engine="openpyxl") as _w1:
            df_stage2[cols].to_excel(_w1, index=False, sheet_name="技术基本面")
        st.download_button(
            label="📥 导出 Excel",
            data=_buf1.getvalue(),
            file_name="选股结果_技术基本面.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="dl_t1",
        )
        # 内嵌K线
        st.divider()
        st.markdown("### 📈 查看K线")
        _kl_sel_t1 = st.selectbox("选择股票", options=_kl_opts_t1, key="kl_t1_sel",
                                   label_visibility="collapsed")
        if _kl_sel_t1 and _kl_sel_t1 != "请选择股票":
            _t1_parts = _kl_sel_t1.split()
            _t1_code  = _t1_parts[0].strip()
            _t1_name  = _t1_parts[1] if len(_t1_parts) > 1 else _t1_code
            # 工具栏：MA均线选择 + 自选股操作，合并为一行
            _t1_tb = st.columns([1, 1, 1, 1, 2, 5])
            _t1_ma5  = _t1_tb[0].checkbox("MA5",  value=True,  key="kl_t1_ma5")
            _t1_ma10 = _t1_tb[1].checkbox("MA10", value=True,  key="kl_t1_ma10")
            _t1_ma20 = _t1_tb[2].checkbox("MA20", value=True,  key="kl_t1_ma20")
            _t1_ma60 = _t1_tb[3].checkbox("MA60", value=False, key="kl_t1_ma60")
            with _t1_tb[4]:
                _watchlist_action(_t1_code, _t1_name, f"t1_wl_{_t1_code}")
            _t1_ma_periods = [p for p, s in [(5, _t1_ma5), (10, _t1_ma10), (20, _t1_ma20), (60, _t1_ma60)] if s]
            _t1_df = db_wl.get_daily(_t1_code,
                          start=(datetime.date.today() - datetime.timedelta(days=365)).isoformat())
            if _t1_df is None or _t1_df.empty:
                with st.spinner(f"本地暂无 {_t1_code} 数据，正在实时获取…"):
                    from data.fetcher import get_stock_history as _fetch_hist
                    _t1_df = _fetch_hist(_t1_code, days=250)
            if _t1_df is None or _t1_df.empty:
                st.warning(f"无法获取 {_t1_code} 的K线数据，请稍后重试。")
            else:
                from strategies.chart import build_kline_chart as _build_kl
                _t1_fig = _build_kl(_t1_df, title=f"{_t1_code}  {_t1_name}  日K", show_macd=True, period="D",
                                    show_ma_periods=_t1_ma_periods)
                st.plotly_chart(_t1_fig, use_container_width=True, config={"scrollZoom": True})
                # 多头趋势状态
                if len(_t1_df) >= 20:
                    _t1_c = _t1_df["close"]
                    _t1_m5  = _t1_c.rolling(5).mean().iloc[-1]
                    _t1_m10 = _t1_c.rolling(10).mean().iloc[-1]
                    _t1_m20 = _t1_c.rolling(20).mean().iloc[-1]
                    _t1_bull = _t1_m5 > _t1_m10 > _t1_m20
                    _t1_trend = "✅ 多头排列" if _t1_bull else "⚠️ 非多头排列"
                    st.caption(f"均线趋势：{_t1_trend}　MA5={_t1_m5:.2f}　MA10={_t1_m10:.2f}　MA20={_t1_m20:.2f}")

with tab2:
    if df_triple.empty:
        st.warning("暂无同时满足三重条件的股票。")
    else:
        cols = [c for c in BASE_COLS + SIGNAL_COLS if c in df_triple.columns]
        df_triple_view = df_triple[cols].reset_index(drop=True)
        st.caption(f"共 {n_triple} 只（基本面 + 技术面 + 北向持续净流入）")
        _kl_opts_t2 = ["请选择股票"] + [
            f"{r['code']}  {r.get('name', r['code'])}" for r in df_triple_view.to_dict("records")
        ]
        _t2_ev = st.dataframe(
            style_df(df_triple_view),
            use_container_width=True,
            column_config=_COL_CONFIG,
            selection_mode="single-row",
            on_select="rerun",
            key="t2_table",
        )
        if _t2_ev.selection.rows:
            _t2_new_sel = _kl_opts_t2[_t2_ev.selection.rows[0] + 1]
            st.session_state.pop("kl_t2_sel", None)
            st.session_state["kl_t2_sel"] = _t2_new_sel
        # 导出按钮
        _buf2 = BytesIO()
        with pd.ExcelWriter(_buf2, engine="openpyxl") as _w2:
            df_triple_view.to_excel(_w2, index=False, sheet_name="三重共振")
        st.download_button(
            label="📥 导出 Excel",
            data=_buf2.getvalue(),
            file_name="选股结果_三重共振.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="dl_t2",
        )
        # 内嵌K线
        st.divider()
        st.markdown("### 📈 查看K线")
        _kl_sel_t2 = st.selectbox("选择股票", options=_kl_opts_t2, key="kl_t2_sel",
                                   label_visibility="collapsed")
        if _kl_sel_t2 and _kl_sel_t2 != "请选择股票":
            _t2_parts = _kl_sel_t2.split()
            _t2_code  = _t2_parts[0].strip()
            _t2_name  = _t2_parts[1] if len(_t2_parts) > 1 else _t2_code
            # 工具栏：MA均线选择 + 自选股操作，合并为一行
            _t2_tb = st.columns([1, 1, 1, 1, 2, 5])
            _t2_ma5  = _t2_tb[0].checkbox("MA5",  value=True,  key="kl_t2_ma5")
            _t2_ma10 = _t2_tb[1].checkbox("MA10", value=True,  key="kl_t2_ma10")
            _t2_ma20 = _t2_tb[2].checkbox("MA20", value=True,  key="kl_t2_ma20")
            _t2_ma60 = _t2_tb[3].checkbox("MA60", value=False, key="kl_t2_ma60")
            with _t2_tb[4]:
                _watchlist_action(_t2_code, _t2_name, f"t2_wl_{_t2_code}")
            _t2_ma_periods = [p for p, s in [(5, _t2_ma5), (10, _t2_ma10), (20, _t2_ma20), (60, _t2_ma60)] if s]
            _t2_df = db_wl.get_daily(_t2_code,
                          start=(datetime.date.today() - datetime.timedelta(days=365)).isoformat())
            if _t2_df is None or _t2_df.empty:
                with st.spinner(f"本地暂无 {_t2_code} 数据，正在实时获取…"):
                    from data.fetcher import get_stock_history as _fetch_hist
                    _t2_df = _fetch_hist(_t2_code, days=250)
            if _t2_df is None or _t2_df.empty:
                st.warning(f"无法获取 {_t2_code} 的K线数据，请稍后重试。")
            else:
                from strategies.chart import build_kline_chart as _build_kl
                _t2_fig = _build_kl(_t2_df, title=f"{_t2_code}  {_t2_name}  日K", show_macd=True, period="D",
                                    show_ma_periods=_t2_ma_periods)
                st.plotly_chart(_t2_fig, use_container_width=True, config={"scrollZoom": True})
                if len(_t2_df) >= 20:
                    _t2_c = _t2_df["close"]
                    _t2_m5  = _t2_c.rolling(5).mean().iloc[-1]
                    _t2_m10 = _t2_c.rolling(10).mean().iloc[-1]
                    _t2_m20 = _t2_c.rolling(20).mean().iloc[-1]
                    _t2_bull = _t2_m5 > _t2_m10 > _t2_m20
                    _t2_trend = "✅ 多头排列" if _t2_bull else "⚠️ 非多头排列"
                    st.caption(f"均线趋势：{_t2_trend}　MA5={_t2_m5:.2f}　MA10={_t2_m10:.2f}　MA20={_t2_m20:.2f}")

with tab3:
    if df_capital.empty:
        if _cf_meta.get("api_fail_count", 0) > 0:
            _fail = _cf_meta["api_fail_count"]
            _ttl  = _cf_meta.get("total_candidates", _fail)
            st.warning(
                f"北向个股接口受限：{_fail}/{_ttl} 只股票API请求失败，结果可能不完整。\n\n"
                "建议稍后重试，或切换至「降级方案」（仅看当日增持）。"
            )
        else:
            st.info("当前无满足条件的北向持续净流入股票（连续净增持天数不足）。")
    else:
        st.caption(f"共 {len(df_capital)} 只（北向连续净流入 ≥ {min_consecutive_days} 天）")
        _COL_CFG_CAPITAL = {
            "code":             st.column_config.TextColumn("代码"),
            "name":             st.column_config.TextColumn("名称"),
            "market":           st.column_config.TextColumn("市场"),
            "hold_shares":      st.column_config.NumberColumn("持股数(股)", format="%.0f"),
            "hold_ratio":       st.column_config.NumberColumn("持股比例(%)", format="%.2f"),
            "consecutive_days": st.column_config.NumberColumn("连续净流入(天)", format="%d"),
            "total_increase":   st.column_config.NumberColumn("累计增持(股)", format="%.0f"),
            "hold_change_pct":  st.column_config.NumberColumn("增持比例(%)", format="+%.4f"),
        }
        _t3_opts = ["请选择股票"] + [
            f"{r['code']}  {r.get('name', r['code'])}" for r in df_capital.to_dict("records")
        ]
        _t3_ev = st.dataframe(
            df_capital,
            use_container_width=True,
            column_config=_COL_CFG_CAPITAL,
            selection_mode="single-row",
            on_select="rerun",
            key="t3_table",
        )
        if _t3_ev.selection.rows:
            _t3_new_sel = _t3_opts[_t3_ev.selection.rows[0] + 1]
            st.session_state["t3_wl_sel"] = _t3_new_sel
        # 导出按钮
        _buf3 = BytesIO()
        with pd.ExcelWriter(_buf3, engine="openpyxl") as _w3:
            df_capital.to_excel(_w3, index=False, sheet_name="北向资金")
        st.download_button(
            label="📥 导出 Excel",
            data=_buf3.getvalue(),
            file_name="选股结果_北向资金.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="dl_t3",
        )
        # 内嵌K线
        st.divider()
        st.markdown("### 📈 查看K线")
        _t3_sel = st.selectbox("选择股票", options=_t3_opts, key="t3_wl_sel",
                               label_visibility="collapsed")
        if _t3_sel and _t3_sel != "请选择股票":
            _t3_parts = _t3_sel.split()
            _t3_code  = _t3_parts[0].strip()
            _t3_name  = _t3_parts[1] if len(_t3_parts) > 1 else _t3_code
            # 工具栏：MA均线选择 + 自选股操作，合并为一行
            _t3_tb = st.columns([1, 1, 1, 1, 2, 5])
            _t3_ma5  = _t3_tb[0].checkbox("MA5",  value=True,  key="kl_t3_ma5")
            _t3_ma10 = _t3_tb[1].checkbox("MA10", value=True,  key="kl_t3_ma10")
            _t3_ma20 = _t3_tb[2].checkbox("MA20", value=True,  key="kl_t3_ma20")
            _t3_ma60 = _t3_tb[3].checkbox("MA60", value=False, key="kl_t3_ma60")
            with _t3_tb[4]:
                _watchlist_action(_t3_code, _t3_name, f"t3_wl_{_t3_code}")
            _t3_ma_periods = [p for p, s in [(5, _t3_ma5), (10, _t3_ma10), (20, _t3_ma20), (60, _t3_ma60)] if s]
            _t3_df = db_wl.get_daily(_t3_code,
                          start=(datetime.date.today() - datetime.timedelta(days=365)).isoformat())
            if _t3_df is None or _t3_df.empty:
                with st.spinner(f"本地暂无 {_t3_code} 数据，正在实时获取…"):
                    from data.fetcher import get_stock_history as _fetch_hist
                    _t3_df = _fetch_hist(_t3_code, days=250)
            if _t3_df is None or _t3_df.empty:
                st.warning(f"无法获取 {_t3_code} 的K线数据，请稍后重试。")
            else:
                from strategies.chart import build_kline_chart as _build_kl
                _t3_fig = _build_kl(_t3_df, title=f"{_t3_code}  {_t3_name}  日K", show_macd=True, period="D",
                                    show_ma_periods=_t3_ma_periods)
                st.plotly_chart(_t3_fig, use_container_width=True, config={"scrollZoom": True})
                if len(_t3_df) >= 20:
                    _t3_c = _t3_df["close"]
                    _t3_m5  = _t3_c.rolling(5).mean().iloc[-1]
                    _t3_m10 = _t3_c.rolling(10).mean().iloc[-1]
                    _t3_m20 = _t3_c.rolling(20).mean().iloc[-1]
                    _t3_bull = _t3_m5 > _t3_m10 > _t3_m20
                    _t3_trend = "✅ 多头排列" if _t3_bull else "⚠️ 非多头排列"
                    st.caption(f"均线趋势：{_t3_trend}　MA5={_t3_m5:.2f}　MA10={_t3_m10:.2f}　MA20={_t3_m20:.2f}")


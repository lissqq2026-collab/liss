"""
app.py
A股选股工具 Streamlit 前端
"""

import sys
import os

# 确保项目根目录在 sys.path 中，避免子模块导入失败
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import pandas as pd

st.set_page_config(layout="wide", page_title="A股选股工具")

# ── 缓存包装：避免频繁拉取，TTL=10分钟 ──────────────────────────────────────

@st.cache_data(ttl=600)
def cached_get_all_a_stock_realtime(source_key: str):
    from data.fetcher import get_all_a_stock_realtime
    return get_all_a_stock_realtime()


@st.cache_data(ttl=600)
def cached_technical_screen(codes_tuple, params_frozen, source_key: str):
    from strategies.technical import screen as technical_screen
    return technical_screen(list(codes_tuple), dict(params_frozen))


@st.cache_data(ttl=600)
def cached_capital_flow_screen(params_frozen, source_key: str):
    from strategies.capital_flow import screen as capital_flow_screen
    return capital_flow_screen(dict(params_frozen))


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
        pe_max = st.slider("PE 最大值", min_value=1, max_value=200, value=30, step=1)
        pb_max = st.number_input("PB 上限", min_value=0.1, max_value=20.0, value=3.0, step=0.1)
        mv_min = st.number_input("市值下限（亿）", min_value=1.0, max_value=10000.0, value=20.0, step=1.0)
        mv_max = st.number_input("市值上限（亿）", min_value=1.0, max_value=100000.0, value=500.0, step=10.0)
        pct_exclude = st.number_input("排除涨跌停阈值（%）", min_value=0.0, max_value=20.0, value=9.0, step=0.5)

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
        kdj_k_oversold = st.slider("KDJ 超卖阈值（K <）", min_value=5, max_value=40, value=20)
        check_kdj_golden_cross = st.checkbox("KDJ 金叉（K 上穿 D）", value=False)

        st.markdown("**量价条件**")
        check_vol_price = st.checkbox("放量上涨（成交量 ≥ N 日均量 × 倍数）", value=True)
        volume_amplify_ratio = st.slider("放量倍数", min_value=1.0, max_value=5.0, value=1.5, step=0.1)

        st.markdown("**RSI 条件**")
        check_rsi_oversold_rec = st.checkbox("RSI 超卖回升", value=False)
        rsi_oversold = st.slider("RSI 超卖阈值（RSI <）", min_value=10, max_value=50, value=30)

        st.markdown("**动量条件**")
        check_momentum = st.checkbox("N 日涨幅为正", value=False)
        momentum_days = st.slider("动量周期（日）", min_value=1, max_value=20, value=5)

        st.divider()
        min_signals = st.number_input(
            "最少满足条件数量（已启用条件中至少满足 N 个）",
            min_value=1, max_value=11, value=1, step=1,
        )

    with st.expander("资金流向参数", expanded=False):
        min_consecutive_days = st.slider("连续净流入天数", min_value=1, max_value=20, value=5)
        markets = st.multiselect(
            "市场",
            options=["沪股通", "深股通"],
            default=["沪股通", "深股通"],
        )

    run_btn = st.button("开始筛选", type="primary", use_container_width=True)

    st.markdown("---")
    with st.expander("批量下载全市场数据"):
        st.caption("将全市场A股历史数据下载到本地数据库（约5000只，耗时较长）")
        st.warning("全市场下载约需30-60分钟，请保持网络连接")
        bulk_btn = st.button("开始批量下载", use_container_width=True, key="bulk_dl")
        if bulk_btn:
            import datetime as _dt_bulk
            from data.fetcher import get_all_a_stock_realtime, get_stock_history
            from data.db import manager as _db_bulk
            st.info("正在获取全市场股票列表…")
            df_bulk_all = get_all_a_stock_realtime()
            if df_bulk_all.empty:
                st.error("获取股票列表失败，请检查网络后重试。")
            else:
                _codes_all = df_bulk_all["code"].tolist()
                _names_map = dict(zip(df_bulk_all["code"], df_bulk_all.get("name", df_bulk_all["code"])))
                _total = len(_codes_all)
                st.info(f"共获取到 {_total} 只股票，开始逐个下载…")
                _pbulk = st.progress(0)
                _stxt = st.empty()
                _errs = 0
                for _i, _c in enumerate(_codes_all):
                    _stxt.text(f"[{_i+1}/{_total}] 正在下载：{_c} {_names_map.get(_c, '')}")
                    try:
                        _today = _dt_bulk.date.today().isoformat()
                        _meta = _db_bulk.get_meta(_c)
                        if _meta is None or _meta.get("last_date") != _today:
                            _days = 3700 if _meta is None else 90
                            _dfh = get_stock_history(_c, days=_days)
                            if not _dfh.empty:
                                _nc = str(_dfh["name"].iloc[-1]) if "name" in _dfh.columns else _names_map.get(_c, _c)
                                _ld = _dfh["date"].max()
                                _lds = _ld.strftime("%Y-%m-%d") if hasattr(_ld, "strftime") else str(_ld)[:10]
                                _db_bulk.upsert_daily(_c, _dfh)
                                _db_bulk.upsert_meta(_c, _nc, _lds)
                    except Exception:
                        _errs += 1
                    _pbulk.progress((_i + 1) / _total)
                _stxt.text(f"批量下载完成！成功 {_total - _errs} 只，失败 {_errs} 只。")
                st.success("批量下载完毕，可在图形选股中使用本地数据。")

# ── 主区域 ───────────────────────────────────────────────────────────────────

st.title("A 股选股工具")

if not run_btn:
    st.info("请在左侧设置参数后点击「开始筛选」。")
    st.stop()

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

# 执行筛选
with st.spinner("正在筛选，请稍候..."):
    try:
        # 阶段1：基本面筛选
        from strategies.fundamental import screen as fundamental_screen

        df_all = cached_get_all_a_stock_realtime(source_key)
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
            df_technical = cached_technical_screen(
                tuple(codes_fundamental),
                params_hashable,
                source_key,
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
        df_capital = cached_capital_flow_screen(
            tuple(sorted(
                (k, tuple(v) if isinstance(v, list) else v)
                for k, v in capital_params.items()
            )),
            source_key,
        )

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

BASE_COLS = ["code", "name", "price", "pct_change", "pe", "pb", "total_mv", "signal_count"]
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
        df_top20 = df_stage2[cols].head(20)
        st.caption(f"共 {n_technical} 只，展示前 20 只（按信号数量排序）")
        st.dataframe(style_df(df_top20), use_container_width=True)

with tab2:
    if df_triple.empty:
        st.warning("暂无同时满足三重条件的股票。")
    else:
        cols = [c for c in BASE_COLS + SIGNAL_COLS if c in df_triple.columns]
        st.caption(f"共 {n_triple} 只（基本面 + 技术面 + 北向持续净流入）")
        st.dataframe(style_df(df_triple[cols]), use_container_width=True)

with tab3:
    if df_capital.empty:
        st.warning("北向资金数据获取失败或无符合条件的股票。")
    else:
        st.caption(f"共 {len(df_capital)} 只（北向连续净流入 ≥ {min_consecutive_days} 天）")
        st.dataframe(df_capital, use_container_width=True)

# ── K线查看 ───────────────────────────────────────────────────────────────────

import datetime as _dt_kl
from data.db import manager as _db_kl
from data.fetcher import get_stock_history as _get_hist
from strategies.chart import build_kline_chart as _build_kl
from strategies.chart import resample_weekly as _resample_w
from strategies.chart import resample_monthly as _resample_m

st.divider()
st.markdown("### 📈 查看K线")

_kl_opts = ["手动输入代码"]
if not df_stage2.empty:
    _nc = "name" if "name" in df_stage2.columns else None
    for _, _r in df_stage2.iterrows():
        _kl_opts.append(f"{_r['code']}  {_r[_nc]}" if _nc else _r["code"])

_kc1, _kc2, _kc3 = st.columns([4, 1, 2])
with _kc1:
    _kl_sel = st.selectbox("选择股票", _kl_opts, key="kl_sel")
with _kc2:
    _kl_period = st.selectbox("周期", ["日K", "周K", "月K"], key="kl_period")
with _kc3:
    _kl_range = st.selectbox("时间范围", ["近3月", "近6月", "近1年", "近3年", "全部"], index=2, key="kl_range")

_kl_macd = st.checkbox("显示MACD", value=True, key="kl_macd")

if _kl_sel == "手动输入代码":
    _kl_code = st.text_input("输入6位股票代码", max_chars=6, key="kl_manual").strip()
else:
    _kl_code = _kl_sel.split()[0].strip()

_kl_ranges = {
    "近3月": (_dt_kl.date.today() - _dt_kl.timedelta(days=90)).isoformat(),
    "近6月": (_dt_kl.date.today() - _dt_kl.timedelta(days=180)).isoformat(),
    "近1年": (_dt_kl.date.today() - _dt_kl.timedelta(days=365)).isoformat(),
    "近3年": (_dt_kl.date.today() - _dt_kl.timedelta(days=1095)).isoformat(),
    "全部":  "2016-01-01",
}

if _kl_code and _kl_code.isdigit() and len(_kl_code) == 6:
    _kl_today = _dt_kl.date.today().isoformat()
    _kl_meta = _db_kl.get_meta(_kl_code)
    if _kl_meta is None:
        with st.spinner(f"首次下载 {_kl_code} 历史数据…"):
            _kl_new = _get_hist(_kl_code, days=3700)
    elif _kl_meta["last_date"] < _kl_today:
        with st.spinner(f"增量更新 {_kl_code}…"):
            _kl_new = _get_hist(_kl_code, days=90)
    else:
        _kl_new = None

    if _kl_new is not None and not _kl_new.empty:
        _kl_name = str(_kl_new["name"].iloc[-1]) if "name" in _kl_new.columns else (_kl_meta["name"] if _kl_meta else _kl_code)
        _kl_ld = _kl_new["date"].max()
        _kl_lds = _kl_ld.strftime("%Y-%m-%d") if hasattr(_kl_ld, "strftime") else str(_kl_ld)[:10]
        _db_kl.upsert_daily(_kl_code, _kl_new)
        _db_kl.upsert_meta(_kl_code, _kl_name, _kl_lds)
    elif _kl_meta:
        _kl_name = _kl_meta.get("name", _kl_code)
    else:
        _kl_name = _kl_code

    _df_kl = _db_kl.get_daily(_kl_code, start=_kl_ranges[_kl_range])

    if _df_kl is None or _df_kl.empty:
        st.warning(f"无法读取 {_kl_code} 的K线数据，请先批量下载或确认代码正确。")
    else:
        _period_map = {"日K": "D", "周K": "W", "月K": "M"}
        if _kl_period == "周K":
            _df_plot = _resample_w(_df_kl)
        elif _kl_period == "月K":
            _df_plot = _resample_m(_df_kl)
        else:
            _df_plot = _df_kl.copy()

        if _df_plot.empty:
            st.warning("该时间范围内暂无数据。")
        else:
            _kl_fig = _build_kl(
                _df_plot,
                title=f"{_kl_code}  {_kl_name}  {_kl_period}",
                show_macd=_kl_macd,
                period=_period_map[_kl_period],
            )
            st.plotly_chart(_kl_fig, use_container_width=True, config={
                "scrollZoom": True,
                "displayModeBar": True,
                "modeBarButtonsToAdd": ["drawline", "eraseshape"],
                "modeBarButtonsToRemove": ["select2d", "lasso2d"],
            })
elif _kl_sel == "手动输入代码" and _kl_code:
    st.error("请输入有效的6位股票代码。")

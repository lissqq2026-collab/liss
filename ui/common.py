"""ui/common.py — 共享工具：缓存包装、颜色高亮、列配置、自选股、K线区块、空态"""
import datetime
import streamlit as st
import pandas as pd

from data.db import manager as db_wl
from ui import tokens as T


# ── 全局紧凑样式（基于 ui/tokens.py 设计令牌）────────────────────────────────────

_COMPACT_CSS = f"""
<style>
  html {{ font-size: {T.FONT_SIZE_BASE}; }}
  .stApp {{ --st-font-size-sm: {T.FONT_SIZE_SM}; }}
  h1 {{ font-size: {T.FONT_SIZE_H1} !important; }}
  h2 {{ font-size: {T.FONT_SIZE_H2} !important; }}
  h3 {{ font-size: {T.FONT_SIZE_H3} !important; }}
  .stMarkdown p, .stCaption {{ font-size: {T.FONT_SIZE_SM} !important; }}
  section[data-testid="stSidebar"] .stMarkdown {{ font-size: {T.FONT_SIZE_SM} !important; }}
  .stDataFrame {{ font-size: {T.FONT_SIZE_XS}; }}
  .stExpander header {{ font-size: {T.FONT_SIZE_MD} !important; }}
  .stTabs button {{ font-size: {T.FONT_SIZE_SM} !important; padding: {T.SPACE_2} {T.SPACE_4} !important; }}
  div[data-testid="stMetricValue"] {{ font-size: {T.FONT_SIZE_XL} !important; }}
  .stSlider, .stCheckbox, .stSelectbox, .stNumberInput, .stRadio {{ font-size: {T.FONT_SIZE_SM} !important; }}
  .stButton button {{ font-size: {T.FONT_SIZE_SM} !important; }}
  section[data-testid="stSidebar"] .stExpander {{ margin-bottom: {T.SPACE_1} !important; }}
  section[data-testid="stSidebar"] .stExpander header {{ padding: {T.SPACE_2} {T.SPACE_3} !important; }}
  section[data-testid="stSidebar"] .stExpander > div {{ padding: {T.SPACE_2} {T.SPACE_3} !important; }}
  section[data-testid="stSidebar"] .stVerticalBlock {{ gap: {T.SPACE_1} !important; }}
</style>
"""


def inject_compact_css():
    """注入全局紧凑样式，供所有页面调用。"""
    st.markdown(_COMPACT_CSS, unsafe_allow_html=True)


# ── 缓存包装 ────────────────────────────────────────────────────────────────────

@st.cache_data(ttl=600)
def cached_get_all_a_stock_realtime(source_key: str):
    from data.fetcher import get_all_a_stock_realtime
    return get_all_a_stock_realtime()


@st.cache_data(ttl=300)
def cached_get_all_codes():
    """共享：本地数据库已下载股票列表（含 code/name），TTL=5分钟。"""
    return db_wl.get_all_codes()


# ── 空态占位 ────────────────────────────────────────────────────────────────────

def empty_state(
    icon: str,
    title: str,
    desc: str,
    *,
    hint: str = "",
) -> None:
    """统一空态卡片：图标 + 标题 + 一句话描述 + 可选提示。

    desc 必须是纯文本（不允许 HTML），长说明请用 st.expander 自行渲染。
    hint 显示为次要灰字（用于"前置依赖"类提示），同样必须是纯文本。
    """
    import html as _html
    _title = _html.escape(title)
    _desc  = _html.escape(desc)
    _hint  = (
        f'<p style="color: {T.COLOR_TEXT_DISABLED}; font-size: {T.FONT_SIZE_SM}; '
        f'margin-top: {T.SPACE_4};">{_html.escape(hint)}</p>'
        if hint else ""
    )
    with st.container(border=True):
        st.markdown(
            f"""
            <div style="text-align: center; padding: {T.SPACE_6} {T.SPACE_5};">
                <div style="font-size: 3rem; margin-bottom: {T.SPACE_3};">{icon}</div>
                <h4 style="margin-bottom: {T.SPACE_2}; color: {T.COLOR_TEXT_SECONDARY}; font-size: {T.FONT_SIZE_MD};">{_title}</h4>
                <p style="color: {T.COLOR_TEXT_MUTED}; font-size: {T.FONT_SIZE_SM}; line-height: 1.6;">{_desc}</p>
                {_hint}
            </div>
            """,
            unsafe_allow_html=True,
        )


def cached_technical_screen(codes_tuple, params_frozen, source_key: str, progress_cb=None):
    _cache_key = ("tech_screen", codes_tuple, params_frozen, source_key)
    cached = st.session_state.get("_tech_cache")
    if cached and cached.get("key") == _cache_key:
        return cached["df"]
    from strategies.technical import screen as technical_screen
    df = technical_screen(list(codes_tuple), dict(params_frozen), progress_cb=progress_cb)
    st.session_state["_tech_cache"] = {"key": _cache_key, "df": df}
    return df


def cached_capital_flow_screen(params_frozen, source_key: str, progress_cb=None):
    _cache_key = ("capital_flow", params_frozen, source_key)
    cached = st.session_state.get("_capital_cache")
    if cached and cached.get("key") == _cache_key:
        return cached["result"]
    from strategies.capital_flow import screen as capital_flow_screen
    result = capital_flow_screen(dict(params_frozen), progress_cb=progress_cb)
    st.session_state["_capital_cache"] = {"key": _cache_key, "result": result}
    return result


# ── 颜色高亮（A股：涨红跌绿）───────────────────────────────────────────────────

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


# ── 列配置 ──────────────────────────────────────────────────────────────────────

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

BASE_COLS = ["code", "name", "price", "pct_change", "pe", "pb", "roe_approx", "total_mv", "turnover_rate", "amount", "signal_count"]
SIGNAL_COLS = [
    "ma_bullish", "price_above_ma20", "weekly_ma_bullish",
    "macd_golden_cross", "macd_above_zero", "macd_hist_expand",
    "kdj_oversold_rec", "kdj_golden_cross",
    "vol_price_match", "rsi_oversold_rec", "momentum",
]


# ── 自选股操作 ──────────────────────────────────────────────────────────────────

def watchlist_action(code: str, name: str, btn_key: str) -> None:
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


# ── K线内嵌区块（消除3处重复）───────────────────────────────────────────────────

def make_kline_section(opts_list: list, selectbox_key: str, key_prefix: str) -> None:
    """渲染内嵌K线查看器：选择框 + MA工具栏 + 图表 + 趋势状态。

    Args:
        opts_list: 股票选项列表，首项为占位文本（如 "请选择股票"）
        selectbox_key: Streamlit selectbox 的 key（如 "kl_t1_sel"）
        key_prefix: 用于生成 MA checkbox 和自选股按钮的 key 前缀（如 "t1"）
    """
    _sel = st.selectbox("选择股票", options=opts_list, key=selectbox_key,
                        label_visibility="collapsed")
    if not _sel or _sel == "请选择股票":
        return

    _parts = _sel.split()
    _code = _parts[0].strip()
    _name = _parts[1] if len(_parts) > 1 else _code

    _tb = st.columns([1, 1, 1, 1, 2, 5])
    _ma5  = _tb[0].checkbox("MA5",  value=True,  key=f"kl_{key_prefix}_ma5")
    _ma10 = _tb[1].checkbox("MA10", value=True,  key=f"kl_{key_prefix}_ma10")
    _ma20 = _tb[2].checkbox("MA20", value=True,  key=f"kl_{key_prefix}_ma20")
    _ma60 = _tb[3].checkbox("MA60", value=False, key=f"kl_{key_prefix}_ma60")
    with _tb[4]:
        watchlist_action(_code, _name, f"{key_prefix}_wl_{_code}")
    _ma_periods = [p for p, s in [(5, _ma5), (10, _ma10), (20, _ma20), (60, _ma60)] if s]

    _df = db_wl.get_daily(_code, start=(datetime.date.today() - datetime.timedelta(days=365)).isoformat())
    if _df is None or _df.empty:
        with st.spinner(f"本地暂无 {_code} 数据，正在实时获取…"):
            from data.fetcher import get_stock_history as _fetch_hist
            _df = _fetch_hist(_code, days=250)
    if _df is None or _df.empty:
        st.warning(f"无法获取 {_code} 的K线数据，请稍后重试。")
        return

    from strategies.chart import build_kline_chart as _build_kl
    _fig = _build_kl(_df, title=f"{_code}  {_name}  日K", show_macd=True, period="D",
                     show_ma_periods=_ma_periods)
    st.plotly_chart(_fig, use_container_width=True, config={"scrollZoom": True})

    if len(_df) >= 20:
        _c = _df["close"]
        _m5  = _c.rolling(5).mean().iloc[-1]
        _m10 = _c.rolling(10).mean().iloc[-1]
        _m20 = _c.rolling(20).mean().iloc[-1]
        _bull = _m5 > _m10 > _m20
        _trend = "✅ 多头排列" if _bull else "⚠️ 非多头排列"
        st.caption(f"均线趋势：{_trend}　MA5={_m5:.2f}　MA10={_m10:.2f}　MA20={_m20:.2f}")

"""
pages/0_自选股.py
自选股管理页面
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
st.set_page_config(layout="wide", page_title="自选股")

from ui.common import inject_compact_css, empty_state
inject_compact_css()

import pandas as pd
from data.db import manager as db


@st.cache_data(ttl=120)
def _get_realtime_snapshot() -> pd.DataFrame:
    """拉取全市场实时行情快照，TTL=2分钟。"""
    try:
        from data.fetcher import get_all_a_stock_realtime
        return get_all_a_stock_realtime()
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=120)
def _get_last_prices(codes_tuple: tuple) -> dict:
    """
    优先用实时行情获取价格/涨跌幅，缺失的从本地数据库补充。
    返回 {code: {"close": float, "pct_chg": float, "realtime": bool}}。
    """
    rt_map: dict = {}
    try:
        df_rt = _get_realtime_snapshot()
        if not df_rt.empty and "code" in df_rt.columns:
            for _, row in df_rt[df_rt["code"].isin(codes_tuple)].iterrows():
                try:
                    rt_map[str(row["code"]).zfill(6)] = {
                        "close":    float(row.get("price") or float("nan")),
                        "pct_chg":  float(row.get("pct_change") or float("nan")),
                        "realtime": True,
                    }
                except Exception:
                    pass
    except Exception:
        pass

    prices = dict(rt_map)
    missing = [c for c in codes_tuple if c not in prices]
    for code in missing:
        try:
            df_p = db.get_daily(code)
            if df_p is not None and not df_p.empty:
                prices[code] = {
                    "close":    float(df_p["close"].iloc[-1]),
                    "pct_chg":  float(df_p["pct_change"].iloc[-1]) if "pct_change" in df_p.columns else float("nan"),
                    "realtime": False,
                }
        except Exception:
            pass
    return prices


# ── 侧边栏 ───────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### ⭐ 自选股")
    st.caption("管理你的关注股票")

watchlist = db.get_watchlist()

with st.sidebar:
    st.divider()
    st.metric("自选股数量", f"{len(watchlist)} 只")

# ── 主区域 ───────────────────────────────────────────────────────────────────

st.title("自选股")

if not watchlist:
    empty_state(
        "⭐", "暂无自选股",
        "在选股结果中点击「⭐ 股票代码」可快速加入自选股",
    )
    st.stop()

_codes_tuple = tuple(r["code"] for r in watchlist)
try:
    _prices = _get_last_prices(_codes_tuple)
except Exception:
    _prices = {}

# 拉取实时 PE/PB/总市值
_rt_metrics: dict = {}
try:
    _df_rt = _get_realtime_snapshot()
    if not _df_rt.empty and "code" in _df_rt.columns:
        for _, _rt_row in _df_rt[_df_rt["code"].isin(_codes_tuple)].iterrows():
            try:
                _rt_metrics[str(_rt_row["code"]).zfill(6)] = {
                    "pe":       _rt_row.get("pe"),
                    "pb":       _rt_row.get("pb"),
                    "total_mv": _rt_row.get("total_mv"),
                }
            except Exception:
                pass
except Exception:
    pass

# 构造表格
df_wl = pd.DataFrame(watchlist)
df_wl["price"]    = df_wl["code"].map(lambda c: _prices.get(c, {}).get("close"))
df_wl["pct_chg"]  = df_wl["code"].map(lambda c: _prices.get(c, {}).get("pct_chg"))
df_wl["_stale"]   = df_wl["code"].map(lambda c: not _prices.get(c, {}).get("realtime", True))
df_wl["pe"]       = df_wl["code"].map(lambda c: _rt_metrics.get(c, {}).get("pe"))
df_wl["pb"]       = df_wl["code"].map(lambda c: _rt_metrics.get(c, {}).get("pb"))
df_wl["total_mv"] = df_wl["code"].map(lambda c: _rt_metrics.get(c, {}).get("total_mv"))

_stale_count = sum(1 for v in _prices.values() if not v.get("realtime", True))
if _stale_count:
    st.caption(f"价格数据：实时行情（2分钟缓存），{_stale_count} 只使用本地历史数据（可能为前一日，标记 `*`）")

# 侧边栏涨跌统计
_n_up   = sum(1 for v in _prices.values() if v.get("pct_chg", 0) > 0)
_n_down = sum(1 for v in _prices.values() if v.get("pct_chg", 0) < 0)
with st.sidebar:
    _mc1, _mc2 = st.columns(2)
    _mc1.metric("上涨", f"{_n_up} 只")
    _mc2.metric("下跌", f"{_n_down} 只")

# 准备 editor 视图：备注可编辑、删除列可勾选
def _fmt_price(p, stale):
    if pd.isna(p):
        return "—"
    return f"{p:.2f}*" if stale else f"{p:.2f}"

df_edit = pd.DataFrame({
    "🗑️":         [False] * len(df_wl),
    "代码":        df_wl["code"],
    "名称":        df_wl["name"],
    "最新价":      [_fmt_price(p, s) for p, s in zip(df_wl["price"], df_wl["_stale"])],
    "涨跌幅(%)":   df_wl["pct_chg"],
    "PE(TTM)":     df_wl["pe"],
    "PB":          df_wl["pb"],
    "总市值(亿)":  df_wl["total_mv"],
    "备注":        df_wl["note"].fillna(""),
    "加入时间":    df_wl["added_at"],
})

_snapshot_key = "_wl_snapshot"
st.session_state[_snapshot_key] = df_edit.copy()

st.markdown("**操作提示**：直接修改「备注」列或勾选「🗑️」即可，点击下方按钮保存改动。")

edited = st.data_editor(
    df_edit,
    use_container_width=True,
    hide_index=True,
    num_rows="fixed",
    column_config={
        "🗑️":         st.column_config.CheckboxColumn("🗑️", help="勾选后点击保存，将该股票移出自选", default=False),
        "代码":        st.column_config.TextColumn("代码", disabled=True),
        "名称":        st.column_config.TextColumn("名称", disabled=True),
        "最新价":      st.column_config.TextColumn("最新价", disabled=True),
        "涨跌幅(%)":   st.column_config.NumberColumn("涨跌幅(%)", format="%+.2f", disabled=True),
        "PE(TTM)":     st.column_config.NumberColumn("PE(TTM)", format="%.1f", disabled=True),
        "PB":          st.column_config.NumberColumn("PB", format="%.2f", disabled=True),
        "总市值(亿)":  st.column_config.NumberColumn("总市值(亿)", format="%.1f", disabled=True),
        "备注":        st.column_config.TextColumn("备注", help="直接点击编辑", max_chars=200),
        "加入时间":    st.column_config.TextColumn("加入时间", disabled=True),
    },
    key="watchlist_editor",
)

_btn_col1, _btn_col2, _btn_col3 = st.columns([1, 1, 4])
with _btn_col1:
    _apply = st.button("💾 应用改动", type="primary", use_container_width=True)
with _btn_col2:
    _open_kline = st.selectbox(
        "查看K线",
        options=["—"] + [f"{c} {n}" for c, n in zip(df_wl["code"], df_wl["name"])],
        label_visibility="collapsed",
        key="kline_picker",
    )
    if _open_kline and _open_kline != "—":
        st.session_state["kline_jump_code"] = _open_kline.split()[0]
        st.switch_page("app.py")

if _apply:
    _orig = st.session_state.get(_snapshot_key)
    _changes_note = 0
    _changes_rm = 0
    for i in range(len(edited)):
        _code = str(edited.iloc[i]["代码"])
        # 移除
        if bool(edited.iloc[i]["🗑️"]):
            if db.remove_from_watchlist(_code):
                _changes_rm += 1
            continue
        # 备注变更
        _new_note = str(edited.iloc[i]["备注"] or "")
        _old_note = str(_orig.iloc[i]["备注"] or "") if _orig is not None else ""
        if _new_note != _old_note:
            if db.update_watchlist_note(_code, _new_note):
                _changes_note += 1
    if _changes_rm or _changes_note:
        st.toast(f"已保存：备注 {_changes_note} 条，移除 {_changes_rm} 只", icon="✅")
        st.rerun()
    else:
        st.toast("没有需要保存的改动", icon="ℹ️")

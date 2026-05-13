"""
pages/0_自选股.py
自选股管理页面
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import streamlit as st
st.set_page_config(layout="wide", page_title="自选股")

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
    优先用实时行情获取价格/涨跌幅，缺失的从本地数据库补充（可能为前一日数据）。
    返回 {code: {"close": float, "pct_chg": float, "realtime": bool}} 字典。
    任何异常均静默处理，确保始终返回 dict（可能为空）。
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
    st.title("⭐ 自选股")
    st.caption("管理你的关注股票")

# ── 读取自选股数据 ────────────────────────────────────────────────────────────

watchlist = db.get_watchlist()

# ── 侧边栏底部指标 ────────────────────────────────────────────────────────────

with st.sidebar:
    st.divider()
    st.metric("自选股数量", f"{len(watchlist)} 只")

# ── 主区域 ───────────────────────────────────────────────────────────────────

st.title("自选股")

if not watchlist:
    # 空态提示
    c = st.container(border=True)
    with c:
        st.markdown(
            "<div style='text-align:center; padding: 2rem; color: #888;'>"
            "暂无自选股，在选股结果中点击「⭐ 股票代码」可快速加入自选股"
            "</div>",
            unsafe_allow_html=True,
        )
else:
    _codes_tuple = tuple(r["code"] for r in watchlist)
    try:
        _prices = _get_last_prices(_codes_tuple)
    except Exception:
        _prices = {}
    df_wl = pd.DataFrame(watchlist)
    df_wl["price"]   = df_wl["code"].map(lambda c: _prices.get(c, {}).get("close"))
    df_wl["pct_chg"] = df_wl["code"].map(lambda c: _prices.get(c, {}).get("pct_chg"))

    # 从实时行情快照补充 PE / PB / 总市值
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
    df_wl["pe"]       = df_wl["code"].map(lambda c: _rt_metrics.get(c, {}).get("pe"))
    df_wl["pb"]       = df_wl["code"].map(lambda c: _rt_metrics.get(c, {}).get("pb"))
    df_wl["total_mv"] = df_wl["code"].map(lambda c: _rt_metrics.get(c, {}).get("total_mv"))

    _stale_count = sum(1 for v in _prices.values() if not v.get("realtime", True))
    if _stale_count:
        st.caption(f"价格数据：实时行情（2分钟缓存），{_stale_count} 只使用本地历史数据（可能为前一日）")

    # 侧边栏涨跌统计
    _n_up   = sum(1 for v in _prices.values() if v.get("pct_chg", 0) > 0)
    _n_down = sum(1 for v in _prices.values() if v.get("pct_chg", 0) < 0)
    with st.sidebar:
        _mc1, _mc2 = st.columns(2)
        _mc1.metric("上涨", f"{_n_up} 只", delta=None)
        _mc2.metric("下跌", f"{_n_down} 只", delta=None)

    # 列配置
    _COL_CFG = {
        "code":     st.column_config.TextColumn("代码"),
        "name":     st.column_config.TextColumn("名称"),
        "price":    st.column_config.NumberColumn("最新价", format="%.2f"),
        "pct_chg":  st.column_config.NumberColumn("涨跌幅(%)", format="%+.2f"),
        "pe":       st.column_config.NumberColumn("PE(TTM)", format="%.1f"),
        "pb":       st.column_config.NumberColumn("PB", format="%.2f"),
        "total_mv": st.column_config.NumberColumn("总市值(亿)", format="%.1f"),
        "added_at": st.column_config.TextColumn("加入时间"),
        "note":     st.column_config.TextColumn("备注"),
    }

    _display_cols = [c for c in ["code", "name", "price", "pct_chg", "pe", "pb", "total_mv", "added_at", "note"]
                     if c in df_wl.columns]

    def _color_pct(val):
        if pd.isna(val):
            return ""
        return "color: #FF3333" if val > 0 else ("color: #33AA33" if val < 0 else "")

    _df_display = df_wl[_display_cols]
    if "pct_chg" in _df_display.columns:
        _styled = _df_display.style.map(_color_pct, subset=["pct_chg"])
    else:
        _styled = _df_display.style

    st.dataframe(
        _styled,
        use_container_width=True,
        column_config=_COL_CFG,
        hide_index=True,
    )

    st.divider()
    st.markdown("**操作与备注**")

    # 每行展示：代码、名称、备注编辑、K线按钮、移出按钮
    _hdr = st.columns([2, 2, 3, 1, 1, 1])
    _hdr[0].markdown("**代码**")
    _hdr[1].markdown("**名称**")
    _hdr[2].markdown("**备注（编辑后点击💾保存）**")
    _hdr[3].markdown("**保存**")
    _hdr[4].markdown("**K线**")
    _hdr[5].markdown("**移出**")

    for _row in watchlist:
        _code  = _row["code"]
        _name  = _row["name"] or ""
        _note  = _row["note"] or ""
        _cols  = st.columns([2, 2, 3, 1, 1, 1])
        _cols[0].write(_code)
        _cols[1].write(_name)
        with _cols[2]:
            _new_note = st.text_input(
                "备注",
                value=_note,
                key=f"note_{_code}",
                label_visibility="collapsed",
                placeholder="添加备注…",
            )
        with _cols[3]:
            if st.button("💾", key=f"save_{_code}", use_container_width=True, help="保存备注"):
                db.update_watchlist_note(_code, _new_note)
                st.toast(f"{_code} 备注已保存", icon="💾")
                st.rerun()
        with _cols[4]:
            if st.button("📈", key=f"kl_{_code}", use_container_width=True, help="查看K线"):
                st.session_state["kl_view_sel"] = f"{_code}  {_name}"
                st.switch_page("pages/1_K线查看.py")
        with _cols[5]:
            if st.button("🗑️", key=f"rm_{_code}", use_container_width=True, help="移出自选股"):
                db.remove_from_watchlist(_code)
                st.toast(f"已从自选股移除", icon="🗑️")
                st.rerun()

"""ui/updater_panel.py — 数据更新状态面板组件 (用于主页 sidebar)。"""
from __future__ import annotations

import streamlit as st

from data import auto_updater
from data.db import manager as db


_ICON = {
    "idle":    "⏸️",
    "running": "🔄",
    "done":    "✅",
    "error":   "❌",
}


def trigger_auto_update_once() -> None:
    """页面首次加载时触发一次后台增量更新（同一会话内幂等）。"""
    if "_auto_update_triggered" not in st.session_state:
        st.session_state["_auto_update_triggered"] = True
        auto_updater.start_update()


def render_updater_panel() -> None:
    """渲染数据更新状态面板（图标/进度/计数/手动按钮）。"""
    state = auto_updater.get_state()
    status = state["status"]

    st.markdown(f"**{_ICON.get(status, '⏸️')} 数据更新状态**")

    if status == "running":
        total = state["total"] or 1
        progress = state["progress"]
        st.progress(min(progress / total, 1.0), text=state["message"])
        st.caption(
            f"已更新 **{state['updated']}**  |  "
            f"失败 **{state['failed']}**  |  "
            f"跳过 **{state['skipped']}**"
        )
        st.info("后台更新中，不影响正常使用，刷新页面可查看最新进度。")
    else:
        st.caption(state["message"])
        if state["last_run"]:
            st.caption(f"上次更新：{state['last_run']}")
        if status == "error" and state["error"]:
            st.error(f"错误详情：{state['error']}")

    st.markdown("---")

    codes = db.get_all_codes() or []
    st.metric("本地库存量", f"{len(codes)} 只股票")

    st.markdown("---")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("增量更新", use_container_width=True,
                     disabled=(status == "running"), key="upd_inc"):
            started = auto_updater.start_update(force=False)
            st.toast("增量更新已启动" if started else "数据已是最新",
                     icon="🔄" if started else "✅")
            st.rerun()
    with c2:
        if st.button("强制全量", use_container_width=True,
                     disabled=(status == "running"), key="upd_full"):
            started = auto_updater.start_update(force=True)
            if started:
                st.toast("强制全量更新已启动", icon="🔄")
            st.rerun()

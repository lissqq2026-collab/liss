"""ui/results.py — 筛选结果展示：漏斗指标 + 三个 Tab"""
from __future__ import annotations
import streamlit as st
import pandas as pd
from io import BytesIO

from ui.common import (
    _COL_CONFIG, BASE_COLS, SIGNAL_COLS, style_df, make_kline_section
)


def _build_opts(df: pd.DataFrame) -> list:
    """从 DataFrame 构建 selectbox 选项列表。"""
    return ["请选择股票"] + [
        f"{r['code']}  {r.get('name', r['code'])}" for r in df.to_dict("records")
    ]


def _handle_selection(ev, opts: list, session_key: str) -> None:
    """处理 dataframe 行选中 → 写入 session_state。"""
    if ev.selection.rows:
        st.session_state.pop(session_key, None)
        st.session_state[session_key] = opts[ev.selection.rows[0] + 1]


def _render_result_tab(
    df_display: pd.DataFrame,
    df_full: pd.DataFrame,
    cols: list,
    caption: str,
    key_prefix: str,
    *,
    col_config: dict | None = None,
    styled: bool = True,
    top_n: int = 0,
    export_sheet: str = "",
    export_file: str = "",
    empty_warning: str = "无结果。",
) -> None:
    """通用结果 Tab：表格 + 导出 + K 线查看。

    Args:
        top_n: >0 时显示 top_n slider 并只展示前 N 条。
    """
    if df_display.empty:
        st.warning(empty_warning)
        return

    if top_n > 0:
        _n = st.slider("展示数量", 10, 100, min(top_n, 15), 10, key=f"top_n_{key_prefix}")
        df_view = df_display[cols].head(_n)
        st.caption(f"{caption}，展示前 {_n} 只")
    else:
        df_view = df_display[cols].reset_index(drop=True)
        st.caption(caption)

    _kl_opts = _build_opts(df_view)
    _ev = st.dataframe(
        style_df(df_view) if styled else df_view,
        use_container_width=True,
        column_config=col_config or _COL_CONFIG,
        selection_mode="single-row",
        on_select="rerun",
        key=f"{key_prefix}_table",
    )
    _handle_selection(_ev, _kl_opts, f"kl_{key_prefix}_sel")

    # 导出按钮
    _buf = BytesIO()
    with pd.ExcelWriter(_buf, engine="openpyxl") as _w:
        df_full[cols].to_excel(_w, index=False, sheet_name=export_sheet or key_prefix)
    st.download_button(
        label="📥 导出 Excel",
        data=_buf.getvalue(),
        file_name=export_file or f"选股结果_{key_prefix}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"dl_{key_prefix}",
    )
    st.divider()
    st.markdown("**📈 查看K线**")
    make_kline_section(_kl_opts, f"kl_{key_prefix}_sel", key_prefix)


def render_results(results: dict, config: dict) -> None:
    """渲染漏斗指标 + 技术基本面 / 三重共振 / 北向资金三个 Tab。"""
    df_stage2     = results["df_stage2"]
    df_triple     = results["df_triple"]
    df_capital    = results["df_capital"]
    _cf_meta      = results.get("_cf_meta", {})
    n_fundamental = results["n_fundamental"]
    n_technical   = results["n_technical"]
    n_triple      = results["n_triple"]
    min_consecutive_days = config.get("min_consecutive_days", 5)

    # ── 漏斗指标 ──
    col1, col2, col3 = st.columns(3)
    col1.metric("基本面入选", f"{n_fundamental} 只")
    _tech_pct = f"{n_technical / n_fundamental * 100:.1f}%" if n_fundamental else "—"
    col2.metric("技术面叠加后", f"{n_technical} 只", delta=f"通过率 {_tech_pct}", delta_color="off")
    _triple_pct = f"{n_triple / n_technical * 100:.1f}%" if n_technical else "—"
    col3.metric("三重共振", f"{n_triple} 只", delta=f"通过率 {_triple_pct}", delta_color="off")

    st.divider()

    tab1, tab2, tab3 = st.tabs(["技术+基本面", "三重共振", "北向资金"])

    # ── Tab 1：技术+基本面 ──
    with tab1:
        _cols1 = [c for c in BASE_COLS + SIGNAL_COLS if c in df_stage2.columns]
        _render_result_tab(
            df_display=df_stage2, df_full=df_stage2, cols=_cols1,
            caption=f"共 {n_technical} 只（按信号数量排序）",
            key_prefix="t1", top_n=15,
            export_sheet="技术基本面", export_file="选股结果_技术基本面.xlsx",
            empty_warning="技术面筛选无结果。",
        )

    # ── Tab 2：三重共振 ──
    with tab2:
        _cols2 = [c for c in BASE_COLS + SIGNAL_COLS if c in df_triple.columns]
        _render_result_tab(
            df_display=df_triple, df_full=df_triple, cols=_cols2,
            caption=f"共 {n_triple} 只（基本面 + 技术面 + 北向持续净流入）",
            key_prefix="t2",
            export_sheet="三重共振", export_file="选股结果_三重共振.xlsx",
            empty_warning="暂无同时满足三重条件的股票。",
        )

    # ── Tab 3：北向资金 ──
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
            _cols3 = [c for c in _COL_CFG_CAPITAL if c in df_capital.columns]
            st.caption(f"共 {len(df_capital)} 只（北向连续净流入 ≥ {min_consecutive_days} 天）")

            _t3_opts = _build_opts(df_capital)
            _t3_ev = st.dataframe(
                df_capital,
                use_container_width=True,
                column_config=_COL_CFG_CAPITAL,
                selection_mode="single-row",
                on_select="rerun",
                key="t3_table",
            )
            _handle_selection(_t3_ev, _t3_opts, "t3_wl_sel")

            _buf3 = BytesIO()
            with pd.ExcelWriter(_buf3, engine="openpyxl") as _w3:
                df_capital[_cols3].to_excel(_w3, index=False, sheet_name="北向资金")
            st.download_button(
                label="📥 导出 Excel",
                data=_buf3.getvalue(),
                file_name="选股结果_北向资金.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="dl_t3",
            )
            st.divider()
            st.markdown("**📈 查看K线**")
            make_kline_section(_t3_opts, "t3_wl_sel", "t3")

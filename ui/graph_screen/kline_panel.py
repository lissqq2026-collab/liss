"""ui/graph_screen/kline_panel.py — 图形选股右侧 K 线面板（fragment 局部重绘 + 键盘导航）"""
import json
import datetime as _dt_kl_p

import streamlit as st
import streamlit.components.v1 as components
import pandas as pd

from data.db import manager as db
from data.sources import sina_intraday
from strategies.chart import build_kline_chart, resample_weekly, resample_monthly
from strategies.intraday_chart import build_intraday_chart
from ui.plotly_autoscale import inject_y_autoscale


def render(ctx: dict):
    """渲染右侧 K 线面板。需在 `with right_col:` 上下文内调用。"""
    df_result = ctx["df_result"]
    _N = ctx["_N"]

    @st.fragment
    def _render_kline_panel():
        # 行选中桥接：JS 点击行 → 写入此 input → 仅本 fragment 重跑，不再 rerun 整页
        if "row_sel_bridge" not in st.session_state:
            st.session_state["row_sel_bridge"] = str(st.session_state.get("sel_idx", 0))
        st.text_input(
            "row_sel_bridge",
            key="row_sel_bridge",
            label_visibility="collapsed",
            placeholder="row_sel_bridge",
        )
        # 解析当前选中行（优先来自 bridge，其次 session_state）
        try:
            _idx = int(st.session_state["row_sel_bridge"])
        except (ValueError, TypeError):
            _idx = int(st.session_state.get("sel_idx", 0))
        _idx = max(0, min(_idx, _N - 1))
        st.session_state["sel_idx"] = _idx  # 给左侧导航按钮保持一致
        _sel_row = df_result.iloc[_idx]
        sel_code = str(_sel_row["code"])
        sel_name = str(_sel_row["name"])
        _saved_shapes = st.session_state.setdefault("pattern_drawings", {}).get(sel_code, [])

        _c1, _c2, _c3, _c4, _c5 = st.columns([2, 1, 1, 1, 1])
        with _c1:
            _kl_range_sel = st.selectbox(
                "时间范围", ["近3月", "近6月", "近1年", "近3年", "全部"],
                index=2, key="kl_pattern_range",
            )
        with _c2:
            _show_macd = st.checkbox("MACD", value=True, key="kl_pattern_macd")
        with _c3:
            _show_arr = st.checkbox("多头排列", value=True, key="kl_pattern_arr")
        with _c4:
            _arc_default = st.session_state.get("_last_arc_selected", False)
            _show_arc_fit = st.checkbox(
                "圆弧底部", value=_arc_default, key="kl_pattern_arc_fit",
                help="在 MA10 实际曲线上标注最近60日的圆弧最低点（不做拟合，反映真实均线形态）",
            )
        with _c5:
            _show_buy_sell = st.checkbox(
                "买卖点", value=True, key="kl_pattern_buy_sell",
                help="MACD 金叉/死叉 + 顶/底背离信号；最近 120 个交易日",
            )

        _kl_ranges = {
            "近3月": (_dt_kl_p.date.today() - _dt_kl_p.timedelta(days=90)).isoformat(),
            "近6月": (_dt_kl_p.date.today() - _dt_kl_p.timedelta(days=180)).isoformat(),
            "近1年": (_dt_kl_p.date.today() - _dt_kl_p.timedelta(days=365)).isoformat(),
            "近3年": (_dt_kl_p.date.today() - _dt_kl_p.timedelta(days=1095)).isoformat(),
            "全部":  "2016-01-01",
        }

        # ── 分时 + K线 子 tab（分时默认） ──
        t_intra, t_day, t_week, t_month = st.tabs(["分时", "日K", "周K", "月K"])

        with t_intra:
            # 分时图
            st.caption("数据：新浪 1 分钟分时 · 仅交易时段实时刷新")
            with st.spinner(f"正在加载 {sel_code} 的分时数据…"):
                df_intra = sina_intraday.get_intraday_1min(sel_code)
                prev_close = sina_intraday.get_prev_close(sel_code)
            if df_intra is None or df_intra.empty:
                st.warning(f"暂无 {sel_code} 的分时数据（可能非交易时段、停牌、或新浪接口异常）。")
            else:
                fig_intra = build_intraday_chart(
                    df_intra, title=f"{sel_code}  {sel_name}  分时",
                    prev_close=prev_close,
                )
                st.plotly_chart(fig_intra, use_container_width=True,
                                 config={"displayModeBar": False},
                                 key=f"intra_chart_{sel_code}")

        with t_day:
            df_kline = db.get_daily(sel_code, start=_kl_ranges[_kl_range_sel])

            if df_kline is None or df_kline.empty:
                st.warning(f"无法读取 {sel_code} 的K线数据。")
            else:
                # 默认缩放：初始显示最近约45个交易日（数据不足时显示全部）
                # 右侧留 1 天空白，避免最新一根 K 线贴边
                _init_xrange = None
                if len(df_kline) >= 10:
                    _n_init = min(45, len(df_kline))
                    _last_date = pd.Timestamp(df_kline["date"].iloc[-1])
                    _right_pad = _last_date + pd.Timedelta(days=1)
                    _init_xrange = [df_kline["date"].iloc[-_n_init], _right_pad]

                # ── 画线桥接：不可见 textarea 供 JS 回传 shapes → Python ──────────
                _curr_shapes_json = json.dumps(_saved_shapes if isinstance(_saved_shapes, list) else [])
                st.text_area(
                    "画线桥接",
                    value=_curr_shapes_json,
                    key=f"_draw_bridge_{sel_code}",
                    label_visibility="collapsed",
                    height=68,
                )
                _bridge_val = st.session_state.get(f"_draw_bridge_{sel_code}", _curr_shapes_json)
                if _bridge_val != _curr_shapes_json:
                    try:
                        _new_shapes = json.loads(_bridge_val)
                        if isinstance(_new_shapes, list):
                            if _new_shapes:
                                st.session_state["pattern_drawings"][sel_code] = _new_shapes
                            else:
                                st.session_state["pattern_drawings"].pop(sel_code, None)
                            _saved_shapes = _new_shapes if _new_shapes else []
                    except Exception:
                        pass

                fig = build_kline_chart(
                    df_kline,
                    title=f"{sel_code}  {sel_name}  日K",
                    show_macd=_show_macd,
                    show_ma_arrangement=_show_arr,
                    show_ma_arc_fit=_show_arc_fit,
                    arc_fit_window=60,
                    show_buy_sell=_show_buy_sell,
                    buy_sell_lookback=120,
                    user_shapes=_saved_shapes if _saved_shapes else None,
                    initial_xrange=_init_xrange,
                )
                _kl_height_map = {"近3月": 340, "近6月": 360, "近1年": 380, "近3年": 400, "全部": 420}
                _kl_height = _kl_height_map.get(_kl_range_sel, 520)
                fig.update_layout(
                    autosize=True,
                    height=_kl_height,
                    margin=dict(l=80, r=60, t=50, b=30),
                )
                st.plotly_chart(fig, use_container_width=True, key=f"kl_chart_{sel_code}", config={
                    "scrollZoom": True,
                    "displayModeBar": "hover",
                    "displaylogo": False,
                    "responsive": True,
                    "toImageButtonOptions": {"format": "png", "scale": 2},
                    "modeBarButtonsToAdd": ["drawline", "eraseshape"],
                    "modeBarButtonsToRemove": ["select2d", "lasso2d", "autoScale2d", "toggleSpikelines"],
                    "modeBarButtonColor": "rgba(70,70,70,0.6)",
                    "modeBarBgColor": "rgba(248,248,248,0.4)",
                })

                # ── 画线保存工具栏（通过隐藏 textarea 桥接 JS→Python） ──
                components.html(f"""
                <div style="display:flex;gap:8px;margin:4px 0;align-items:center;">
                    <button id="save-draw-btn" style="padding:4px 14px;background:#FF6600;color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:13px;">💾 保存画线</button>
                    <button id="clear-draw-btn" style="padding:4px 14px;background:#888;color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:13px;">🗑️ 清除画线</button>
                <span id="draw-status" style="font-size:12px;color:#999;margin-left:4px;"></span>
            </div>
            <script>
            (function(){{
                // 隐藏桥接 textarea（含重试 + MutationObserver，防止 React 渲染时序问题）
                (function hideBridge() {{
                    function doHide() {{
                        var tas = window.parent.document.querySelectorAll('textarea');
                        for (var i = 0; i < tas.length; i++) {{
                            if (tas[i].id && tas[i].id.indexOf('_draw_bridge_') >= 0) {{
                                tas[i].style.display = 'none';
                                var el = tas[i].parentElement;
                                var depth = 0;
                                while (el && el !== window.parent.document.body && depth < 10) {{
                                    if (el.dataset && (el.dataset.testid === 'stVerticalBlockBorderWrapper' || el.dataset.testid === 'stVerticalBlock')) {{
                                        el.style.display = 'none';
                                        break;
                                    }}
                                    el = el.parentElement;
                                    depth++;
                                }}
                            }}
                        }}
                    }}
                    doHide();
                    setTimeout(doHide, 200);
                    setTimeout(doHide, 800);
                    try {{
                        var obs = new MutationObserver(function() {{ doHide(); }});
                        obs.observe(window.parent.document.body, {{ childList: true, subtree: true }});
                        setTimeout(function() {{ obs.disconnect(); }}, 3000);
                    }} catch(e) {{}}
                }})();

                function findBridgeTextarea() {{
                    var textareas = window.parent.document.querySelectorAll('textarea');
                    for (var i = 0; i < textareas.length; i++) {{
                        if (textareas[i].id && textareas[i].id.indexOf('_draw_bridge_') >= 0) {{
                            return textareas[i];
                        }}
                    }}
                    return null;
                }}

                function setTextareaValue(textarea, value) {{
                    var nativeSetter = Object.getOwnPropertyDescriptor(
                        window.HTMLTextAreaElement.prototype, 'value'
                    ).set;
                    nativeSetter.call(textarea, value);
                    textarea.dispatchEvent(new Event('input', {{ bubbles: true }}));
                }}

                function findPlotlyShapes() {{
                    var iframes = window.parent.document.querySelectorAll('iframe');
                    for (var i = 0; i < iframes.length; i++) {{
                        try {{
                            var doc = iframes[i].contentDocument || iframes[i].contentWindow.document;
                            if (!doc) continue;
                            var el = doc.querySelector('.js-plotly-plot');
                            if (el && el._fullLayout && el._fullLayout.shapes) {{
                                return el._fullLayout.shapes || [];
                            }}
                        }} catch(e) {{}}
                    }}
                    return [];
                }}

                function filterUserShapes(shapes) {{
                    return shapes.filter(function(s) {{
                        if (s.fillcolor) return false;
                        if (s.xref === 'paper' || s.yref === 'paper') return false;
                        if (s.name === 'user_drawn') return true;
                        if (!s.name) return true;
                        return false;
                    }});
                }}

                var saveBtn = document.getElementById('save-draw-btn');
                var clearBtn = document.getElementById('clear-draw-btn');
                var statusEl = document.getElementById('draw-status');

                saveBtn.addEventListener('click', function() {{
                    var allShapes = findPlotlyShapes();
                    var userShapes = filterUserShapes(allShapes);
                    if (userShapes.length === 0) {{
                        statusEl.textContent = '⚠️ 未检测到画线，请先用工具栏画线';
                        return;
                    }}
                    statusEl.textContent = '⏳ 保存中...';
                    var bridge = findBridgeTextarea();
                    if (bridge) {{
                        setTextareaValue(bridge, JSON.stringify(userShapes));
                        statusEl.textContent = '✅ 已保存 ' + userShapes.length + ' 条画线';
                    }} else {{
                        statusEl.textContent = '❌ 桥接失败，请刷新页面';
                    }}
                }});

                clearBtn.addEventListener('click', function() {{
                    var bridge = findBridgeTextarea();
                    if (bridge) {{
                        setTextareaValue(bridge, '[]');
                        statusEl.textContent = '已清除';
                    }} else {{
                        statusEl.textContent = '❌ 桥接失败';
                    }}
                }});
            }})();
            </script>
            """, height=50)

        with t_week:
            df_w = db.get_daily(sel_code, start=_kl_ranges[_kl_range_sel])
            if df_w is None or df_w.empty:
                st.warning(f"无法读取 {sel_code} 的K线数据。")
            else:
                df_w = resample_weekly(df_w)
                if df_w.empty:
                    st.warning("当前时间范围内无周K数据，请切换更大范围。")
                else:
                    fig_w = build_kline_chart(
                        df_w, title=f"{sel_code}  {sel_name}  周K",
                        show_macd=_show_macd, period="W",
                        show_ma_arrangement=_show_arr,
                    )
                    fig_w.update_layout(height=360, margin=dict(l=80, r=60, t=50, b=30))
                    st.plotly_chart(fig_w, use_container_width=True, key=f"kl_chart_w_{sel_code}", config={
                        "scrollZoom": True, "displayModeBar": "hover", "displaylogo": False,
                        "responsive": True,
                    })

        with t_month:
            df_m = db.get_daily(sel_code, start=_kl_ranges[_kl_range_sel])
            if df_m is None or df_m.empty:
                st.warning(f"无法读取 {sel_code} 的K线数据。")
            else:
                df_m = resample_monthly(df_m)
                if df_m.empty:
                    st.warning("当前时间范围内无月K数据，请切换更大范围。")
                else:
                    fig_m = build_kline_chart(
                        df_m, title=f"{sel_code}  {sel_name}  月K",
                        show_macd=_show_macd, period="M",
                        show_ma_arrangement=_show_arr,
                    )
                    fig_m.update_layout(height=360, margin=dict(l=80, r=60, t=50, b=30))
                    st.plotly_chart(fig_m, use_container_width=True, key=f"kl_chart_m_{sel_code}", config={
                        "scrollZoom": True, "displayModeBar": "hover", "displaylogo": False,
                        "responsive": True,
                    })

    _render_kline_panel()
    # 同花顺式 Y 轴自适应：缩放/平移时主图 Y 轴跟随可见窗口高低点
    inject_y_autoscale()


def render_keyboard_handler():
    """全局键盘上下键 → 调用 iframe 内 bumpSel（仅 fragment 重绘）。在页面末尾调用。"""
    components.html(
        """
        <script>
        (function(){
            const doc = window.parent.document;
            const win = window.parent;
            if (doc.__patternKbdInstalled_v2) return;
            doc.__patternKbdInstalled_v2 = true;
            doc.addEventListener('keydown', function(e){
                const tag = (e.target && e.target.tagName) || '';
                if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
                if (e.target && e.target.isContentEditable) return;
                let delta = 0;
                if (e.key === 'ArrowUp')        delta = -1;
                else if (e.key === 'ArrowDown') delta = 1;
                else return;
                if (typeof win.__patternBumpSel === 'function') {
                    e.preventDefault();
                    win.__patternBumpSel(delta);
                }
            }, true);
        })();
        </script>
        """,
        height=0,
    )

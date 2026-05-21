"""ui/graph_screen/results_table.py — 图形选股结果：排序/自选状态 + 自建HTML表渲染"""
import streamlit as st
import streamlit.components.v1 as components
import pandas as pd

from data.db import manager as db
from ui.common import empty_state


def _toggle_wl(code: str, name: str, in_wl: bool):
    if in_wl:
        db.remove_from_watchlist(code)
        st.toast(f"已移出自选股：{code}", icon="🗑️")
    else:
        db.add_to_watchlist(code, name)
        st.toast(f"已加入自选股：{code}", icon="⭐")


def prepare(results: list, config: dict) -> dict:
    """构建排序后的结果表 + 选中状态，渲染顶部信息条，返回上下文 ctx。

    可能调用 st.stop()（无命中）。
    """
    sort_by = config["sort_by"]

    if not results:
        empty_state(
            "📭", "未找到符合条件的股票",
            "请尝试更换形态条件、降低成交额门槛，或将匹配模式改为「满足任一所选条件」后重新扫描。",
        )
        st.stop()

    df_result = pd.DataFrame(results)

    # ── 排序 ─────────────────────────────────────────────────────────────────────
    _sort_map = {
        "流畅度降序": ("流畅度", False),
        "命中数降序": ("命中数", False),
    }
    _sort_col, _sort_asc = _sort_map.get(sort_by, ("流畅度", False))
    if _sort_col in df_result.columns:
        df_result = df_result.sort_values(_sort_col, ascending=_sort_asc, na_position="last")
    df_result = df_result.reset_index(drop=True)

    # ── 自选股状态 ───────────────────────────────────────────────────────────────
    _wl_codes = {r["code"] for r in db.get_watchlist()}
    df_result["自选"] = df_result["code"].apply(lambda c: "⭐" if c in _wl_codes else "")

    # ── 选中索引（支持上下键切换） ──────────────────────────────────────────────
    _N = len(df_result)
    if "sel_idx" not in st.session_state or st.session_state["sel_idx"] >= _N:
        st.session_state["sel_idx"] = 0
    sel_idx = int(st.session_state["sel_idx"])
    sel_row  = df_result.iloc[sel_idx]
    sel_code = str(sel_row["code"])
    sel_name = str(sel_row["name"])

    st.session_state.setdefault("pattern_drawings", {})

    # ── 顶部信息条 ───────────────────────────────────────────────────────────────
    _top_row = st.columns([6, 1])
    with _top_row[0]:
        st.success(
            f"共命中 {_N} 只股票（排序：{sort_by}）｜ "
            f"⬆/⬇ 键或按钮切换 → 右侧 K 线同步刷新"
        )
    with _top_row[1]:
        csv_bytes = df_result.to_csv(index=False).encode("utf-8-sig")
        st.download_button("⬇ 导出CSV", csv_bytes, "图形选股结果.csv", "text/csv", width="stretch")

    # ── 进度条最大值（HTML 表 .bar 渲染用） ──────────────────────────────────────
    _max_hits = int(df_result["命中数"].max()) if not df_result.empty else 1

    return {
        "df_result": df_result,
        "_N":        _N,
        "sel_idx":   sel_idx,
        "sel_code":  sel_code,
        "sel_name":  sel_name,
        "_wl_codes": _wl_codes,
        "_max_hits": _max_hits,
        "sort_by":   sort_by,
    }


def render_table(ctx: dict):
    """渲染左侧自建 HTML 结果表（含导航条 + JS 桥接）。"""
    df_result = ctx["df_result"]
    _N        = ctx["_N"]
    sel_idx   = ctx["sel_idx"]
    sel_code  = ctx["sel_code"]
    sel_name  = ctx["sel_name"]
    _wl_codes = ctx["_wl_codes"]
    _max_hits = ctx["_max_hits"]

    _nav = st.columns([2, 5])
    with _nav[0]:
        _in_wl = sel_code in _wl_codes
        st.button(
            "移出 ⭐" if _in_wl else "加入 ⭐",
            key="wl_toggle",
            on_click=_toggle_wl, args=(sel_code, sel_name, _in_wl),
            type=("secondary" if _in_wl else "primary"),
            width="stretch",
        )
    with _nav[1]:
        st.caption(f"**{sel_idx + 1}** / {_N}　{sel_code} {sel_name}")

    # 行选中桥接 input 已移入 right_col 的 K线 fragment，
    # 这样点击切换只触发 fragment 局部重绘，不再 rerun 整个页面
    _rows_html = []
    for _i, _row in df_result.iterrows():
        _is_sel = (_i == sel_idx)
        _row_cls = "sel" if _is_sel else ""
        _star = "⭐" if _row["code"] in _wl_codes else ""
        _pct = _row.get("pct_chg") or 0.0
        _pct_cls = "pos" if _pct >= 0 else "neg"
        _hits = int(_row.get("命中数") or 0)
        _hits_w = min(100, _hits / max(_max_hits, 1) * 100)
        _flow = float(_row.get("流畅度") or 0.0)
        _flow_w = min(100, _flow * 100)
        _name = str(_row.get("name") or "")
        _patterns = str(_row.get("命中形态") or "")
        _price = _row.get("price")
        _price_s = f"{_price:.2f}" if _price is not None and not pd.isna(_price) else "—"
        _rows_html.append(
            f'<tr class="{_row_cls}" data-idx="{_i}" onclick="pickRow({_i})">'
            f'<td>{_star}</td><td>{_row["code"]}</td>'
            f'<td title="{_name}">{_name}</td>'
            f'<td class="num">{_price_s}</td>'
            f'<td class="num {_pct_cls}">{_pct:+.2f}</td>'
            f'<td><div class="bar"><div class="fill" style="width:{_hits_w:.1f}%;background:#1976d2"></div><span class="lab">{_hits}</span></div></td>'
            f'<td><div class="bar"><div class="fill" style="width:{_flow_w:.1f}%;background:#388e3c"></div><span class="lab">{_flow:.3f}</span></div></td>'
            f'<td title="{_patterns}">{_patterns}</td>'
            f'</tr>'
        )
    _rows_joined = "".join(_rows_html)
    _table_html = """
<style>
* { box-sizing: border-box; }
body { margin: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", sans-serif; }
.nav-bar { display: flex; gap: 6px; margin-bottom: 6px; }
.nav-bar button { flex: 1; padding: 6px 10px; font-size: 13px; font-weight: 500; border: 1px solid #d0d0d0; background: #fff; border-radius: 5px; cursor: pointer; transition: all .12s; user-select: none; }
.nav-bar button:hover:not(:disabled) { background: #f0f7ff; border-color: #1976d2; color: #1976d2; }
.nav-bar button:active:not(:disabled) { background: #e3f2fd; }
.nav-bar button:disabled { color: #bbb; cursor: not-allowed; background: #fafafa; }
.scroll-wrap { height: 300px; overflow-y: auto; overflow-x: hidden; border: 1px solid #e0e0e0; border-radius: 6px; background: #fff; }
.resdf { width: 100%; table-layout: fixed; border-collapse: collapse; font-size: 12.5px; }
.resdf colgroup col:nth-child(1) { width: 32px; }
.resdf colgroup col:nth-child(2) { width: 72px; }
.resdf colgroup col:nth-child(3) { width: 92px; }
.resdf colgroup col:nth-child(4) { width: 60px; }
.resdf colgroup col:nth-child(5) { width: 64px; }
.resdf colgroup col:nth-child(6) { width: 70px; }
.resdf colgroup col:nth-child(7) { width: 90px; }
.resdf thead th { position: sticky; top: 0; z-index: 2; background: #f5f7fa; color: #555; font-weight: 600; padding: 7px 8px; border-bottom: 1px solid #e0e0e0; text-align: left; white-space: nowrap; }
.resdf td { padding: 6px 8px; border-bottom: 1px solid #f2f2f2; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.resdf tbody tr { cursor: pointer; }
.resdf tbody tr:hover { background: #f7faff; }
.resdf tbody tr.sel { background: #fff3e0 !important; }
.resdf tbody tr.sel td:first-child { box-shadow: inset 3px 0 0 #ff6600; }
.num { text-align: right; font-variant-numeric: tabular-nums; }
.pos { color: #d32f2f; } .neg { color: #388e3c; }
.bar { position: relative; width: 100%; height: 16px; background: #f0f0f0; border-radius: 3px; overflow: hidden; }
.bar .fill { height: 100%; border-radius: 3px; }
.bar .lab { position: absolute; left: 0; right: 0; top: 0; text-align: center; font-size: 11px; line-height: 16px; color: #222; font-weight: 500; }
</style>
<div class="nav-bar">
  <button id="prev-btn" onclick="bumpSel(-1)" title="上一只 (↑)">⬆ 上一只</button>
  <button id="next-btn" onclick="bumpSel(1)" title="下一只 (↓)">下一只 ⬇</button>
</div>
<div class="scroll-wrap">
<table class="resdf">
<colgroup><col><col><col><col><col><col><col><col></colgroup>
<thead><tr>
  <th>⭐</th><th>代码</th><th>名称</th>
  <th class="num">收盘</th><th class="num">涨跌%</th>
  <th>命中</th><th>流畅度</th><th>命中形态</th>
</tr></thead>
<tbody>__ROWS__</tbody>
</table>
</div>
<script>
function findBridgeInput() {
  const doc = window.parent.document;
  // 优先：wrapper class（Streamlit 注入的 st-key-{key}）
  let wrap = doc.querySelector('[class*="st-key-row_sel_bridge"]');
  if (wrap) {
    const inp = wrap.querySelector('input');
    if (inp) return inp;
  }
  // 兜底1：aria-label
  let inp = doc.querySelector('input[aria-label="row_sel_bridge"]');
  if (inp) return inp;
  // 兜底2：placeholder
  inp = doc.querySelector('input[placeholder="row_sel_bridge"]');
  if (inp) return inp;
  return null;
}
function pickRow(idx) {
  // 立刻在 iframe 内反馈视觉切换，避免等 Streamlit rerun
  document.querySelectorAll('tr.sel').forEach(function(r){ r.classList.remove('sel'); });
  const target = document.querySelector('tr[data-idx="' + idx + '"]');
  if (target) target.classList.add('sel');
  const input = findBridgeInput();
  if (!input) {
    console.warn('[pickRow] bridge input not found');
    return;
  }
  // Streamlit text_input 仅在 onBlur 时把值提交到 Python session_state，
  // 所以必须真实 focus → 修改 value → blur，才能触发 rerun
  const setter = Object.getOwnPropertyDescriptor(window.parent.HTMLInputElement.prototype, 'value').set;
  input.focus();
  setter.call(input, String(idx));
  input.dispatchEvent(new Event('input', { bubbles: true }));
  input.dispatchEvent(new Event('change', { bubbles: true }));
  // 同时模拟 Enter 提交（双保险）
  input.dispatchEvent(new KeyboardEvent('keydown', { bubbles: true, key: 'Enter', code: 'Enter', keyCode: 13, which: 13 }));
  input.dispatchEvent(new KeyboardEvent('keypress', { bubbles: true, key: 'Enter', code: 'Enter', keyCode: 13, which: 13 }));
  input.dispatchEvent(new KeyboardEvent('keyup', { bubbles: true, key: 'Enter', code: 'Enter', keyCode: 13, which: 13 }));
  // 延迟 blur，确保 Streamlit 监听到 value 变化
  setTimeout(function() { input.blur(); }, 30);
}
function updateNav() {
  const total = document.querySelectorAll('tr[data-idx]').length;
  const sel = document.querySelector('tr.sel');
  const cur = sel ? parseInt(sel.dataset.idx, 10) : 0;
  const prev = document.getElementById('prev-btn');
  const next = document.getElementById('next-btn');
  if (prev) prev.disabled = (cur <= 0);
  if (next) next.disabled = (cur >= total - 1);
}
let _bumpBusy = false;
function bumpSel(delta) {
  if (_bumpBusy) return;
  const total = document.querySelectorAll('tr[data-idx]').length;
  const sel = document.querySelector('tr.sel');
  const cur = sel ? parseInt(sel.dataset.idx, 10) : 0;
  const newIdx = Math.max(0, Math.min(total - 1, cur + delta));
  if (newIdx === cur) return;
  _bumpBusy = true;
  setTimeout(function() { _bumpBusy = false; }, 180);
  pickRow(newIdx);
  const row = document.querySelector('tr[data-idx="' + newIdx + '"]');
  if (row) row.scrollIntoView({ block: 'nearest' });
  updateNav();
}
// 暴露给父窗口（键盘上下键调用）
try { window.parent.__patternBumpSel = bumpSel; } catch(e) {}
// iframe 内部也监听键盘（光标在 iframe 时父监听不到）
document.addEventListener('keydown', function(e) {
  const tag = (e.target && e.target.tagName) || '';
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
  if (e.key === 'ArrowUp')        { e.preventDefault(); bumpSel(-1); }
  else if (e.key === 'ArrowDown') { e.preventDefault(); bumpSel(1); }
}, true);
(function() {
  const sel = document.querySelector('tr.sel');
  if (sel) sel.scrollIntoView({ block: 'nearest' });
  updateNav();
})();
</script>
""".replace("__ROWS__", _rows_joined)
    components.html(_table_html, height=420, scrolling=False)

"""ui/stock_search.py — 股票搜索组件（拼音/简拼/代码/名称模糊匹配）。

依赖：streamlit-searchbox + pypinyin（在 requirements.txt 中声明）。
若导入失败则降级为标准 selectbox。
"""
from __future__ import annotations

from typing import Optional

import streamlit as st

from data.db import manager as db


@st.cache_data(ttl=300, show_spinner=False)
def _build_search_index() -> list[dict]:
    """返回 [{code, name, py_full, py_short}]，按 code 排序。"""
    try:
        from pypinyin import lazy_pinyin, Style
    except ImportError:
        lazy_pinyin = None
        Style = None

    rows = db.get_all_codes() or []
    idx = []
    for r in rows:
        code = r["code"]
        name = r.get("name") or code
        if lazy_pinyin:
            py_full = "".join(lazy_pinyin(name)).lower()
            py_short = "".join(
                p[0] for p in lazy_pinyin(name, style=Style.FIRST_LETTER) if p
            ).lower()
        else:
            py_full = name.lower()
            py_short = name.lower()
        idx.append({
            "code": code, "name": name,
            "py_full": py_full, "py_short": py_short,
        })
    return idx


def _search(term: str, limit: int = 30) -> list[tuple[str, str]]:
    """按输入串模糊匹配，返回 [(label, code)]。

    匹配优先级：code 前缀 > 名称含 > 全拼含 > 简拼含。
    """
    term = (term or "").strip().lower()
    idx = _build_search_index()
    if not term:
        return [(f"{r['code']}  {r['name']}", r["code"]) for r in idx[:limit]]

    hits_code, hits_name, hits_full, hits_short = [], [], [], []
    for r in idx:
        code, name = r["code"], r["name"]
        if code.startswith(term):
            hits_code.append(r)
        elif term in name.lower():
            hits_name.append(r)
        elif term in r["py_full"]:
            hits_full.append(r)
        elif term in r["py_short"]:
            hits_short.append(r)

    merged = hits_code + hits_name + hits_full + hits_short
    seen = set()
    out = []
    for r in merged:
        if r["code"] in seen:
            continue
        seen.add(r["code"])
        out.append((f"{r['code']}  {r['name']}", r["code"]))
        if len(out) >= limit:
            break
    return out


def stock_search(
    key: str = "stock_search",
    label: str = "搜索股票",
    placeholder: str = "代码 / 名称 / 拼音（如 600519 / 茅台 / mt / maotai）…",
    default: Optional[str] = None,
) -> Optional[str]:
    """渲染搜索框，返回选中股票 code（无选中则返回 None）。"""
    try:
        from streamlit_searchbox import st_searchbox

        def _searchfn(term: str):
            return _search(term, limit=30)

        return st_searchbox(
            _searchfn,
            label=label,
            placeholder=placeholder,
            key=key,
            default=default,
            clear_on_submit=False,
        )
    except ImportError:
        # 降级：标准 selectbox + 手动文本输入
        idx = _build_search_index()
        term = st.text_input(label, placeholder=placeholder, key=f"{key}_text")
        results = _search(term, limit=50) if term else \
            [(f"{r['code']}  {r['name']}", r["code"]) for r in idx[:200]]
        if not results:
            st.caption("无匹配结果")
            return None
        labels = [r[0] for r in results]
        codes = [r[1] for r in results]
        choice = st.selectbox(" ", options=["请选择"] + labels,
                              key=f"{key}_sel", label_visibility="collapsed")
        if choice == "请选择":
            return None
        return codes[labels.index(choice)]

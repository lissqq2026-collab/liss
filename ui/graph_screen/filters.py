"""ui/graph_screen/filters.py — 板块 / 指数 / 形态分组过滤辅助"""


def is_index(code: str, name: str = "") -> bool:
    """识别指数类标的：399开头的深证指数，或名称包含“指数”。"""
    if code.startswith("399"):
        return True
    if name and "指数" in name:
        return True
    return False


def board_match(code: str, boards: list) -> bool:
    if not boards:
        return True
    if "科创板" in boards and code.startswith("688"):
        return True
    if "创业板" in boards and (code.startswith("300") or code.startswith("301")):
        return True
    if "北交所" in boards and (code.startswith("8") or code.startswith("430")):
        return True
    if "沪深主板" in boards:
        if not (code.startswith("688") or code.startswith("3")
                or code.startswith("8") or code.startswith("430")):
            return True
    return False


def group_catalog(catalog: list) -> dict[str, list]:
    trend_ids    = {"three_soldiers", "golden_cross_ma", "ma_convergence",
                    "ma60_breakout", "volume_breakout", "ma_bullish_arrangement",
                    "box_breakout", "ma_smooth_up", "arc_up", "arc_flow", "close_above_ma5"}
    reversal_ids = {"morning_star", "hammer", "macd_divergence",
                    "double_bottom", "oversold_bounce"}
    vol_ids      = {"low_vol_consolidation", "low_vol_pullback"}

    groups: dict[str, list] = {
        "趋势延续": [],
        "底部反转": [],
        "量价特征": [],
        "其他形态": [],
    }
    for item in catalog:
        pid = item["id"]
        if pid in trend_ids:
            groups["趋势延续"].append(item)
        elif pid in reversal_ids:
            groups["底部反转"].append(item)
        elif pid in vol_ids:
            groups["量价特征"].append(item)
        else:
            groups["其他形态"].append(item)

    return {k: v for k, v in groups.items() if v}

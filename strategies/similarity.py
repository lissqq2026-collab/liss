"""
strategies/similarity.py — A股"相似K线选股"核心算法模块

算法说明：
  1. 归一化：价格用累计收益率（第一根=0），量能用相对均量
  2. 相似度：Pearson相关系数，综合 = 价格×0.7 + 量能×0.3
  3. 匹配策略：对每只候选股取其最近 n 根K线（n = 模板区间长度）
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from data.db import manager as db


# ─────────────────────────── 归一化函数 ───────────────────────────────────────

def normalize_returns(close: pd.Series) -> np.ndarray:
    """
    收盘价序列 → 累计收益率序列，第一根为 0。

    ret[i] = close[i] / close[0] - 1

    Parameters
    ----------
    close : pd.Series
        收盘价序列（长度 >= 1，首元素不得为 0）

    Returns
    -------
    np.ndarray  shape=(n,)，dtype=float64
    """
    arr = close.to_numpy(dtype=float)
    base = arr[0]
    if base == 0 or np.isnan(base):
        # 无法归一化时返回全零序列
        return np.zeros(len(arr))
    return arr / base - 1.0


def normalize_volume(volume: pd.Series) -> np.ndarray:
    """
    成交量序列 → 相对均量序列。

    vol_rel[i] = vol[i] / vol.mean()

    均值为 0 时返回全零（调用方按此判断量能维度是否可用）。

    Parameters
    ----------
    volume : pd.Series

    Returns
    -------
    np.ndarray  shape=(n,)，dtype=float64；均值为0时全零
    """
    arr = volume.to_numpy(dtype=float)
    mean_vol = np.nanmean(arr)
    if mean_vol == 0 or np.isnan(mean_vol):
        return np.zeros(len(arr))
    return arr / mean_vol


# ─────────────────────────── 相似度计算 ───────────────────────────────────────

def pearson_sim(a: np.ndarray, b: np.ndarray) -> float:
    """
    计算两个等长数组的 Pearson 相关系数。

    - 使用 numpy 向量化，不做 Python 循环
    - 任一序列的标准差为 0（常量序列）或出现 NaN/inf 时返回 -1.0

    Parameters
    ----------
    a, b : np.ndarray  等长一维数组

    Returns
    -------
    float  范围 [-1.0, 1.0]；无效时返回 -1.0
    """
    if len(a) != len(b) or len(a) < 2:
        return -1.0

    a = a.astype(float)
    b = b.astype(float)

    # 快速检测 NaN / inf
    if not (np.isfinite(a).all() and np.isfinite(b).all()):
        return -1.0

    a_mean = a.mean()
    b_mean = b.mean()
    a_dev = a - a_mean
    b_dev = b - b_mean

    std_a = np.sqrt((a_dev ** 2).mean())
    std_b = np.sqrt((b_dev ** 2).mean())

    if std_a == 0.0 or std_b == 0.0:
        return -1.0

    corr = (a_dev * b_dev).mean() / (std_a * std_b)

    # 数值误差可能使结果略超 [-1, 1]，做夹紧处理
    corr = float(np.clip(corr, -1.0, 1.0))
    return corr if np.isfinite(corr) else -1.0


# ─────────────────────────── 主入口函数 ───────────────────────────────────────

def find_similar_stocks(
    template_code: str,
    date_start: str,
    date_end: str,
    top_n: int = 5,
    min_similarity: float = 0.7,
    price_weight: float = 0.7,
    exclude_self: bool = True,
) -> list:
    """
    相似K线选股主入口。

    Parameters
    ----------
    template_code  : str   模板股票代码，如 '000001'
    date_start     : str   模板区间开始日期 'YYYY-MM-DD'
    date_end       : str   模板区间结束日期 'YYYY-MM-DD'
    top_n          : int   最多返回的匹配数量
    min_similarity : float 最低综合相似度阈值，默认 0.7
    price_weight   : float 价格维度权重（量能权重 = 1 - price_weight），默认 0.7
    exclude_self   : bool  是否排除模板股票自身，默认 True

    Returns
    -------
    list[dict] 按 similarity 降序排列，最多 top_n 条；无匹配时返回 []

    每条记录字段：
        code           : str
        name           : str
        similarity     : float   综合相似度（0~1，仅保留正相关）
        price_sim      : float   价格 Pearson 相关系数
        vol_sim        : float   量能 Pearson 相关系数
        df_template    : pd.DataFrame  模板K线（8字段）
        df_candidate   : pd.DataFrame  候选K线（最近n根，8字段）
        template_norm  : list    模板归一化价格序列（供绘图）
        candidate_norm : list    候选归一化价格序列（供绘图）
    """
    vol_weight = 1.0 - price_weight

    # ── 1. 获取模板K线 ────────────────────────────────────────────────────────
    df_tmpl = db.get_daily(template_code, start=date_start, end=date_end)
    if df_tmpl.empty:
        return []

    n = len(df_tmpl)  # 模板长度
    if n < 2:
        # 少于2根K线无法计算相关系数
        return []

    # 归一化模板序列
    tmpl_price_norm = normalize_returns(df_tmpl["close"])
    tmpl_vol_norm = normalize_volume(df_tmpl["volume"])
    tmpl_vol_valid = tmpl_vol_norm.any()  # 量能归一化是否有效（均值非零）

    # ── 2. 获取全部候选股代码 ─────────────────────────────────────────────────
    all_codes_meta = db.get_all_codes()  # [{"code": str, "name": str}, ...]
    if not all_codes_meta:
        return []

    # 构建 code -> name 映射
    code_name_map = {item["code"]: item["name"] for item in all_codes_meta}
    all_codes = list(code_name_map.keys())

    # ── 3. 批量拉取候选股最近数据 ─────────────────────────────────────────────
    # days_limit 须覆盖至少 n 根K线；以 n*2+60 为安全冗余，最少 300
    days_limit = max(300, n * 2 + 60)
    bulk_data = db.get_all_daily_bulk(all_codes, days_limit=days_limit)

    # ── 4. 逐只计算相似度 ─────────────────────────────────────────────────────
    results = []

    for code, df_cand_full in bulk_data.items():
        # 排除自身
        if exclude_self and code == template_code:
            continue

        # 数据不足 n 根，跳过
        if len(df_cand_full) < n:
            continue

        # 取最近 n 根
        df_cand = df_cand_full.iloc[-n:].reset_index(drop=True)

        # 归一化候选序列
        cand_price_norm = normalize_returns(df_cand["close"])
        cand_vol_norm = normalize_volume(df_cand["volume"])

        # 价格相似度
        price_sim = pearson_sim(tmpl_price_norm, cand_price_norm)

        # 量能相似度：任一一方量能无效时只用价格维度
        cand_vol_valid = cand_vol_norm.any()
        if tmpl_vol_valid and cand_vol_valid:
            vol_sim = pearson_sim(tmpl_vol_norm, cand_vol_norm)
            # 仅正相关计入综合分；负相关量能当作 0 贡献
            vol_contribution = max(vol_sim, 0.0) * vol_weight
        else:
            vol_sim = -1.0
            # 量能退化：综合分 = price_sim * price_weight，与正常路径量纲一致
            price_sim_clamped = max(price_sim, 0.0)
            similarity = price_sim_clamped * price_weight
            if similarity < min_similarity:
                continue
            results.append({
                "code": code,
                "name": code_name_map.get(code, code),
                "similarity": round(similarity, 4),
                "price_sim": round(price_sim, 4),
                "vol_sim": vol_sim,
                "df_template": df_tmpl.copy(),
                "df_candidate": df_cand,
                "template_norm": tmpl_price_norm.tolist(),
                "candidate_norm": cand_price_norm.tolist(),
            })
            continue

        # 综合相似度（仅取正相关部分，负相关视为0贡献）
        price_contribution = max(price_sim, 0.0) * price_weight
        similarity = price_contribution + vol_contribution

        if similarity < min_similarity:
            continue

        results.append({
            "code": code,
            "name": code_name_map.get(code, code),
            "similarity": round(similarity, 4),
            "price_sim": round(price_sim, 4),
            "vol_sim": round(vol_sim, 4),
            "df_template": df_tmpl.copy(),
            "df_candidate": df_cand,
            "template_norm": tmpl_price_norm.tolist(),
            "candidate_norm": cand_price_norm.tolist(),
        })

    # ── 5. 排序并截取 top_n ───────────────────────────────────────────────────
    results.sort(key=lambda x: x["similarity"], reverse=True)
    return results[:top_n]

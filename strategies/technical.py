"""
strategies/technical.py
技术面选股策略：均线多头排列、MACD金叉、KDJ超卖回升、量价配合
依赖：pandas, numpy

函数签名：screen(codes: list, params: dict) -> pd.DataFrame
"""

import pandas as pd
import numpy as np
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.fetcher import get_stock_history


# 默认技术面参数
DEFAULT_PARAMS = {
    "ma_periods": [5, 10, 20, 60],   # 均线周期列表（必须有序）
    "macd_fast": 12,                  # MACD 快线EMA周期
    "macd_slow": 26,                  # MACD 慢线EMA周期
    "macd_signal": 9,                 # MACD 信号线DEA周期
    "kdj_k_oversold": 20,             # KDJ K值超卖阈值
    "volume_amplify_ratio": 1.5,      # 量价配合：当日成交量 / N日均量 的最低倍数
    "volume_ma_period": 20,           # 量价配合：成交量均线周期
    "history_days": 120,              # 拉取历史K线天数（需覆盖最长均线周期）
    "require_all": False,             # True=四个条件全满足；False=满足≥1个即入选（可调）
}


# ──────────────────────────────── 指标计算函数 ──────────────────────────────────

def _calc_ma(close: pd.Series, period: int) -> pd.Series:
    """简单移动平均线"""
    return close.rolling(window=period, min_periods=period).mean()


def _calc_ema(series: pd.Series, period: int) -> pd.Series:
    """指数移动平均，adjust=False 对应国内软件算法"""
    return series.ewm(span=period, adjust=False).mean()


def _calc_macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """
    计算 MACD 三线：DIF、DEA（Signal）、MACD柱
    返回：(dif, dea, hist) 三个 Series
    """
    ema_fast = _calc_ema(close, fast)
    ema_slow = _calc_ema(close, slow)
    dif = ema_fast - ema_slow
    dea = _calc_ema(dif, signal)
    hist = (dif - dea) * 2   # 国内软件惯例 ×2
    return dif, dea, hist


def _calc_kdj(high: pd.Series, low: pd.Series, close: pd.Series, n: int = 9,
              m1: int = 3, m2: int = 3):
    """
    计算 KDJ 指标
    n=9, m1=3, m2=3（国内主流参数）
    返回：(K, D, J) 三个 Series
    """
    low_n = low.rolling(window=n, min_periods=1).min()
    high_n = high.rolling(window=n, min_periods=1).max()

    # RSV（原始随机值）
    rsv = (close - low_n) / (high_n - low_n + 1e-9) * 100

    # K、D 用EWM模拟SMA(3)平滑（与国内主流算法接近）
    k = rsv.ewm(com=m1 - 1, adjust=False).mean()
    d = k.ewm(com=m2 - 1, adjust=False).mean()
    j = 3 * k - 2 * d
    return k, d, j


# ──────────────────────────── 单股票条件检测 ────────────────────────────────────

def _check_ma_bullish(df: pd.DataFrame, periods: list) -> bool:
    """
    均线多头排列：最后一根K线满足 MA5 > MA10 > MA20 > MA60
    """
    if len(df) < max(periods):
        return False
    close = df["close"]
    mas = [_calc_ma(close, p).iloc[-1] for p in periods]
    # 检查严格递减（MA5 > MA10 > MA20 > MA60）
    return all(mas[i] > mas[i + 1] for i in range(len(mas) - 1))


def _check_macd_golden_cross(df: pd.DataFrame, fast: int, slow: int, signal: int) -> bool:
    """
    MACD 金叉：最新DIF上穿DEA（前一日DIF<=DEA，当日DIF>DEA）
    """
    if len(df) < slow + signal + 5:
        return False
    dif, dea, _ = _calc_macd(df["close"], fast, slow, signal)
    if len(dif) < 2:
        return False
    # 当日DIF > DEA，且前一日DIF <= DEA
    cross = (dif.iloc[-1] > dea.iloc[-1]) and (dif.iloc[-2] <= dea.iloc[-2])
    return cross


def _check_kdj_oversold_recovery(df: pd.DataFrame, k_threshold: int) -> bool:
    """
    KDJ 超卖后回升：
    - 近期K值曾经低于 k_threshold（超卖）
    - 当前K值已回升（K[-1] > K[-2]）
    - 当前K值仍处于相对低位（< 50，避免追高）
    """
    if len(df) < 15:
        return False
    k, d, j = _calc_kdj(df["high"], df["low"], df["close"])
    if k.isna().all():
        return False

    k_recent = k.iloc[-10:]   # 近10日
    k_last = k.iloc[-1]
    k_prev = k.iloc[-2]

    # 条件：近10日曾低于超卖线 & 当日回升 & 还没涨过头
    was_oversold = (k_recent < k_threshold).any()
    is_rising = k_last > k_prev
    not_overbought = k_last < 50
    return was_oversold and is_rising and not_overbought


def _check_volume_price(df: pd.DataFrame, amplify_ratio: float, vol_ma_period: int) -> bool:
    """
    量价配合：当日成交量 >= N日均量 * amplify_ratio，且当日收盘涨（pct_change > 0）
    """
    if len(df) < vol_ma_period + 1:
        return False
    vol = df["volume"]
    vol_ma = vol.rolling(window=vol_ma_period).mean()

    last_vol = vol.iloc[-1]
    last_vol_ma = vol_ma.iloc[-2]  # 用前一日均量，避免当日数据影响均值
    last_pct = df["pct_change"].iloc[-1] if "pct_change" in df.columns else 0

    vol_amplified = last_vol >= last_vol_ma * amplify_ratio
    price_up = last_pct > 0
    return vol_amplified and price_up


# ──────────────────────────── 主筛选函数 ────────────────────────────────────────

def screen(codes: list, params: dict = None) -> pd.DataFrame:
    """
    技术面选股：对给定股票代码列表逐一拉取K线并检验技术条件。

    参数：
        codes  - 股票代码列表（6位字符串），通常来自基本面筛选结果
        params - 技术参数字典，缺少的键用 DEFAULT_PARAMS 补全

    返回：
        DataFrame，列：
            code              - 股票代码
            ma_bullish        - 均线多头排列
            macd_golden_cross - MACD金叉
            kdj_oversold_rec  - KDJ超卖回升
            vol_price_match   - 量价配合
            signal_count      - 满足条件数量（越多越优先）
    """
    if not codes:
        print("[technical] 代码列表为空，跳过")
        return pd.DataFrame()

    cfg = {**DEFAULT_PARAMS, **(params or {})}
    ma_periods      = cfg["ma_periods"]
    macd_fast       = cfg["macd_fast"]
    macd_slow       = cfg["macd_slow"]
    macd_signal     = cfg["macd_signal"]
    k_oversold      = cfg["kdj_k_oversold"]
    vol_ratio       = cfg["volume_amplify_ratio"]
    vol_ma_period   = cfg["volume_ma_period"]
    history_days    = cfg["history_days"]
    require_all     = cfg["require_all"]

    records = []
    total = len(codes)

    for idx, code in enumerate(codes, 1):
        print(f"[technical] 处理 {code} ({idx}/{total})...", end="\r")
        df = get_stock_history(code, days=history_days)
        if df.empty or len(df) < max(ma_periods) + 5:
            continue

        ma_ok   = _check_ma_bullish(df, ma_periods)
        macd_ok = _check_macd_golden_cross(df, macd_fast, macd_slow, macd_signal)
        kdj_ok  = _check_kdj_oversold_recovery(df, k_oversold)
        vp_ok   = _check_volume_price(df, vol_ratio, vol_ma_period)

        signal_count = sum([ma_ok, macd_ok, kdj_ok, vp_ok])

        # 过滤逻辑
        if require_all:
            if not (ma_ok and macd_ok and kdj_ok and vp_ok):
                continue
        else:
            if signal_count == 0:
                continue

        records.append({
            "code": code,
            "ma_bullish": ma_ok,
            "macd_golden_cross": macd_ok,
            "kdj_oversold_rec": kdj_ok,
            "vol_price_match": vp_ok,
            "signal_count": signal_count,
        })

    print()  # 换行
    result = pd.DataFrame(records)
    if not result.empty:
        result = result.sort_values("signal_count", ascending=False).reset_index(drop=True)

    print(f"[technical] 技术面筛选完成，从 {total} 只中选出 {len(result)} 只")
    return result


if __name__ == "__main__":
    print("=== 测试 strategies/technical.py ===")

    # 用少量已知代码测试，避免全量拉取耗时过长
    test_codes = ["000001", "600519", "300750", "000858", "601318"]
    result = screen(test_codes)
    if not result.empty:
        print("\n技术面筛选结果：")
        print(result.to_string(index=False))
    else:
        print("无满足条件的股票（测试样本较小属正常）")

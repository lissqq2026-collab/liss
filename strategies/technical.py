"""
strategies/technical.py
技术面选股策略：支持11个技术条件，按条件最少满足数量筛选
依赖：pandas, numpy

函数签名：screen(codes: list, params: dict) -> pd.DataFrame
"""

import pandas as pd
import numpy as np
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data.fetcher import get_stock_history, get_stock_history_batch


# 默认技术面参数
DEFAULT_PARAMS = {
    # 均线
    "ma_periods": [5, 10, 20, 60],
    "check_ma_bullish": True,           # 日线均线多头排列
    "check_price_above_ma20": False,    # 收盘价在MA20上方
    "check_weekly_ma_bullish": False,   # 周线均线多头排列
    # MACD
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9,
    "check_macd_golden_cross": True,    # MACD金叉
    "check_macd_above_zero": False,     # DIF和DEA均在零轴上方
    "check_macd_hist_expand": False,    # MACD柱连续3日放大
    # KDJ
    "kdj_k_oversold": 30,
    "check_kdj_oversold_rec": True,     # KDJ超卖回升
    "check_kdj_golden_cross": False,    # KDJ金叉（K上穿D）
    # 量价
    "volume_amplify_ratio": 2.0,
    "volume_ma_period": 20,
    "check_vol_price": True,            # 放量上涨
    # RSI
    "rsi_period": 14,
    "rsi_oversold": 25,
    "check_rsi_oversold_rec": False,    # RSI超卖回升
    # 动量
    "momentum_days": 5,
    "check_momentum": False,            # N日涨幅为正
    # 筛选逻辑
    "min_signals": 2,                   # 最少满足N个已启用条件
    "history_days": 150,
    "require_all": False,               # 兼容旧接口
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


def _calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """计算RSI指标"""
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(com=period - 1, adjust=False).mean()
    avg_loss = loss.ewm(com=period - 1, adjust=False).mean()
    rs = avg_gain / (avg_loss + 1e-9)
    return 100 - (100 / (1 + rs))


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


def _check_macd_golden_cross(
    df: pd.DataFrame, fast: int, slow: int, signal: int,
    require_above_zero: bool = False,
) -> bool:
    """
    MACD 金叉：近3个交易日内DIF上穿DEA（且当前DIF仍在DEA上方）。
    require_above_zero=True 时额外要求 DIF 和 DEA 均在零轴上方（A股实战推荐）。
    """
    if len(df) < slow + signal + 5:
        return False
    dif, dea, _ = _calc_macd(df["close"], fast, slow, signal)
    if len(dif) < 3:
        return False
    # 当前 DIF 必须仍在 DEA 上方（金叉有效）
    if dif.iloc[-1] <= dea.iloc[-1]:
        return False
    # 近3日内任意一天发生上穿（DIF从DEA下方穿到上方）
    n = min(3, len(dif) - 1)
    crossed = any(
        (dif.iloc[-k] > dea.iloc[-k]) and (dif.iloc[-k - 1] <= dea.iloc[-k - 1])
        for k in range(1, n + 1)
    )
    if not crossed:
        return False
    if require_above_zero:
        return float(dif.iloc[-1]) > 0 and float(dea.iloc[-1]) > 0
    return True


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

    k_recent = k.iloc[-10:]   # 近10日（A股底部震荡通常持续10-15个交易日）
    k_last = k.iloc[-1]
    k_prev = k.iloc[-2]

    # 条件：近10日曾低于超卖线 & 连续2日回升 & 还没涨过头
    was_oversold = (k_recent < k_threshold).any()
    is_rising = (k_last > k_prev) and (k_prev > float(k.iloc[-3]))
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


def _check_price_above_ma(df: pd.DataFrame, period: int = 20) -> bool:
    """收盘价在MA20上方"""
    if len(df) < period:
        return False
    return df["close"].iloc[-1] > _calc_ma(df["close"], period).iloc[-1]


def _check_weekly_ma_bullish(df: pd.DataFrame, periods: tuple = (5, 10, 20)) -> bool:
    """日线数据重采样为周线，检验周线均线多头排列"""
    if "date" not in df.columns or len(df) < max(periods) * 6:
        return False
    df_w = df.set_index("date").resample("W")["close"].last().dropna()
    if len(df_w) < max(periods):
        return False
    mas = [_calc_ma(df_w, p).iloc[-1] for p in periods]
    return all(mas[i] > mas[i + 1] for i in range(len(mas) - 1))


def _check_macd_above_zero(df: pd.DataFrame, fast: int, slow: int, signal: int) -> bool:
    """DIF和DEA均在零轴上方"""
    if len(df) < slow + signal + 5:
        return False
    dif, dea, _ = _calc_macd(df["close"], fast, slow, signal)
    return float(dif.iloc[-1]) > 0 and float(dea.iloc[-1]) > 0


def _check_macd_hist_expanding(df: pd.DataFrame, fast: int, slow: int, signal: int) -> bool:
    """MACD柱（红柱）连续3日为正且扩大"""
    if len(df) < slow + signal + 5:
        return False
    _, _, hist = _calc_macd(df["close"], fast, slow, signal)
    h = hist.dropna().iloc[-3:]
    if len(h) < 3:
        return False
    return (h > 0).all() and float(h.iloc[-1]) > float(h.iloc[-2]) > float(h.iloc[-3])


def _check_kdj_golden_cross(df: pd.DataFrame) -> bool:
    """KDJ金叉：K上穿D（前一日K<=D，当日K>D）"""
    if len(df) < 15:
        return False
    k, d, _ = _calc_kdj(df["high"], df["low"], df["close"])
    if len(k) < 2:
        return False
    return (float(k.iloc[-1]) > float(d.iloc[-1])) and (float(k.iloc[-2]) <= float(d.iloc[-2]))


def _check_rsi_oversold_recovery(df: pd.DataFrame, period: int = 14, threshold: int = 30) -> bool:
    """RSI超卖回升：近5日内曾低于阈值，且连续2日回升且未超买"""
    if len(df) < period + 5:
        return False
    rsi = _calc_rsi(df["close"], period)
    recent = rsi.iloc[-5:]
    was_oversold = (recent < threshold).any()
    is_rising = (
        float(rsi.iloc[-1]) > float(rsi.iloc[-2])
        and float(rsi.iloc[-2]) > float(rsi.iloc[-3])
    )
    not_overbought = float(rsi.iloc[-1]) < 70
    return was_oversold and is_rising and not_overbought


def _check_momentum(df: pd.DataFrame, days: int = 5) -> bool:
    """N日涨幅为正：当前收盘价高于N日前收盘价"""
    if len(df) < days + 1:
        return False
    return float(df["close"].iloc[-1]) > float(df["close"].iloc[-(days + 1)])


def _calc_volume_ratio(df: pd.DataFrame, period: int = 5) -> float:
    """量比：今日成交量 / 近N日均量（不含今日）"""
    if len(df) < period + 1 or "volume" not in df.columns:
        return float("nan")
    avg = df["volume"].iloc[-(period + 1):-1].mean()
    if avg == 0:
        return float("nan")
    return round(float(df["volume"].iloc[-1] / avg), 2)


# ──────────────────────────── 主筛选函数 ────────────────────────────────────────

def screen(codes: list, params: dict = None, progress_cb=None) -> pd.DataFrame:
    """
    技术面选股：对给定股票代码列表逐一拉取K线并检验技术条件。

    参数：
        codes  - 股票代码列表（6位字符串），通常来自基本面筛选结果
        params - 技术参数字典，缺少的键用 DEFAULT_PARAMS 补全

    返回：
        DataFrame，列：
            code              - 股票代码
            <各已启用条件名>  - 各条件布尔值（仅已启用条件出现）
            signal_count      - 满足条件数量（越多越优先）
    """
    if not codes:
        print("[technical] 代码列表为空，跳过")
        return pd.DataFrame()

    cfg = {**DEFAULT_PARAMS, **(params or {})}
    ma_periods      = cfg["ma_periods"]
    macd_fast       = cfg["macd_fast"]
    macd_slow       = cfg["macd_slow"]
    macd_signal_p   = cfg["macd_signal"]
    k_oversold      = cfg["kdj_k_oversold"]
    vol_ratio       = cfg["volume_amplify_ratio"]
    vol_ma_period   = cfg["volume_ma_period"]
    rsi_period      = cfg["rsi_period"]
    rsi_oversold    = cfg["rsi_oversold"]
    momentum_days   = cfg["momentum_days"]
    history_days    = cfg["history_days"]
    require_all     = cfg["require_all"]

    # 构建条件开关字典
    checks = {
        "ma_bullish":        cfg.get("check_ma_bullish", True),
        "price_above_ma20":  cfg.get("check_price_above_ma20", False),
        "weekly_ma_bullish": cfg.get("check_weekly_ma_bullish", False),
        "macd_golden_cross": cfg.get("check_macd_golden_cross", True),
        "macd_above_zero":   cfg.get("check_macd_above_zero", False),
        "macd_hist_expand":  cfg.get("check_macd_hist_expand", False),
        "kdj_oversold_rec":  cfg.get("check_kdj_oversold_rec", True),
        "kdj_golden_cross":  cfg.get("check_kdj_golden_cross", False),
        "vol_price_match":   cfg.get("check_vol_price", True),
        "rsi_oversold_rec":  cfg.get("check_rsi_oversold_rec", False),
        "momentum":          cfg.get("check_momentum", False),
    }

    enabled_count = sum(checks.values())
    if require_all:
        min_signals = enabled_count
    else:
        min_signals = cfg.get("min_signals", 1)

    records = []
    total = len(codes)

    # 优先从本地数据库读取（毫秒级），缺失的再走网络
    from data.db import manager as _local_db
    history_map: dict[str, pd.DataFrame] = {}
    missing_codes: list[str] = []
    for code in codes:
        df_local = _local_db.get_daily(code)
        if df_local is not None and not df_local.empty:
            history_map[code] = df_local.tail(history_days).reset_index(drop=True)
        else:
            missing_codes.append(code)

    print(f"[technical] 本地数据库命中 {total - len(missing_codes)}/{total} 只")
    if missing_codes:
        print(f"[technical] 网络补充 {len(missing_codes)} 只缺失股票…")
        remote_map = get_stock_history_batch(missing_codes, days=history_days)
        history_map.update(remote_map)

    for idx, code in enumerate(codes, 1):
        print(f"[technical] 处理 {code} ({idx}/{total})...", end="\r")
        if progress_cb:
            progress_cb(idx / total)
        df = history_map.get(code, pd.DataFrame())
        if df.empty or len(df) < max(ma_periods) + 5:
            continue

        # 逐条件计算（只计算已启用的条件）
        result = {}
        if checks["ma_bullish"]:
            result["ma_bullish"] = _check_ma_bullish(df, ma_periods)
        if checks["price_above_ma20"]:
            result["price_above_ma20"] = _check_price_above_ma(df, 20)
        if checks["weekly_ma_bullish"]:
            result["weekly_ma_bullish"] = _check_weekly_ma_bullish(df)
        if checks["macd_golden_cross"]:
            result["macd_golden_cross"] = _check_macd_golden_cross(
                df, macd_fast, macd_slow, macd_signal_p,
                require_above_zero=False,  # 零轴条件由独立的 macd_above_zero 控制，避免双重计分
            )
        if checks["macd_above_zero"]:
            result["macd_above_zero"] = _check_macd_above_zero(df, macd_fast, macd_slow, macd_signal_p)
        if checks["macd_hist_expand"]:
            result["macd_hist_expand"] = _check_macd_hist_expanding(df, macd_fast, macd_slow, macd_signal_p)
        if checks["kdj_oversold_rec"]:
            result["kdj_oversold_rec"] = _check_kdj_oversold_recovery(df, k_oversold)
        if checks["kdj_golden_cross"]:
            result["kdj_golden_cross"] = _check_kdj_golden_cross(df)
        if checks["vol_price_match"]:
            result["vol_price_match"] = _check_volume_price(df, vol_ratio, vol_ma_period)
        if checks["rsi_oversold_rec"]:
            result["rsi_oversold_rec"] = _check_rsi_oversold_recovery(df, rsi_period, rsi_oversold)
        if checks["momentum"]:
            result["momentum"] = _check_momentum(df, momentum_days)

        signal_count = sum(result.values())

        # 过滤：已启用条件中满足数量不足则跳过
        if signal_count < min_signals:
            continue

        row = {"code": code}
        row.update(result)
        row["signal_count"] = signal_count
        row["vol_ratio"] = _calc_volume_ratio(df)
        records.append(row)

    print()  # 换行
    df_result = pd.DataFrame(records)
    if not df_result.empty:
        df_result = df_result.sort_values("signal_count", ascending=False).reset_index(drop=True)

    print(f"[technical] 技术面筛选完成，从 {total} 只中选出 {len(df_result)} 只")
    return df_result


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

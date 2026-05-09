"""strategies/patterns.py — 通信达风格 K 线形态识别"""
import numpy as np
import pandas as pd


# ── 内部工具 ─────────────────────────────────────────────────────────────────

def _ema(s: pd.Series, n: int) -> pd.Series:
    return s.ewm(span=n, adjust=False).mean()


def _macd(close: pd.Series):
    dif = _ema(close, 12) - _ema(close, 26)
    dea = _ema(dif, 9)
    hist = (dif - dea) * 2
    return dif, dea, hist


def _local_minima(arr: np.ndarray, window: int = 3) -> list:
    """返回局部最小值的下标列表。"""
    idxs = []
    for i in range(window, len(arr) - window):
        if arr[i] <= arr[i - window:i].min() and arr[i] <= arr[i + 1:i + window + 1].min():
            idxs.append(i)
    return idxs


# ── 形态检测函数 ──────────────────────────────────────────────────────────────

def check_three_soldiers(df: pd.DataFrame) -> bool:
    """红三兵：连续3日阳线，收盘价依次升高，实体占振幅≥50%。"""
    if len(df) < 3:
        return False
    last3 = df.iloc[-3:]
    closes = []
    for _, r in last3.iterrows():
        if r["close"] <= r["open"]:
            return False
        rng = r["high"] - r["low"]
        if rng == 0 or (r["close"] - r["open"]) / rng < 0.5:
            return False
        closes.append(r["close"])
    return closes[0] < closes[1] < closes[2]


def check_morning_star(df: pd.DataFrame) -> bool:
    """早晨之星：大阴线 + 小实体（星） + 大阳线收于阴线中点以上。"""
    if len(df) < 3:
        return False
    d1, d2, d3 = df.iloc[-3], df.iloc[-2], df.iloc[-1]
    body1 = d1["open"] - d1["close"]     # 阴线实体
    body2 = abs(d2["close"] - d2["open"])
    body3 = d3["close"] - d3["open"]     # 阳线实体
    avg_price = df["close"].tail(20).mean() or 1
    threshold = avg_price * 0.01
    if body1 < threshold * 2 or body3 < threshold * 2:
        return False
    if body2 > body1 * 0.3:
        return False
    mid1 = (d1["open"] + d1["close"]) / 2
    return d3["close"] > mid1


def check_hammer(df: pd.DataFrame) -> bool:
    """锤头线：下影线≥实体2倍，上影线≤实体0.5倍（底部反转信号）。"""
    if len(df) < 1:
        return False
    r = df.iloc[-1]
    body = abs(r["close"] - r["open"])
    if body == 0:
        return False
    lower = min(r["open"], r["close"]) - r["low"]
    upper = r["high"] - max(r["open"], r["close"])
    return lower >= body * 2 and upper <= body * 0.5


def check_macd_divergence(df: pd.DataFrame) -> bool:
    """MACD底背离：近60日内价格创新低，但MACD直方柱不创新低。"""
    if len(df) < 60:
        return False
    close = df["close"]
    _, _, hist = _macd(close)
    n = 60
    p = close.values[-n:]
    h = hist.values[-n:]
    lows = _local_minima(p, window=3)
    if len(lows) < 2:
        return False
    i1, i2 = lows[-2], lows[-1]
    if p[i2] >= p[i1]:
        return False
    return float(h[i2]) > float(h[i1])


def check_ma_convergence(df: pd.DataFrame) -> bool:
    """均线粘合：MA5/10/20互相接近（最大偏差<2%），蓄势待发。"""
    if len(df) < 20:
        return False
    close = df["close"]
    ma5  = close.rolling(5).mean().iloc[-1]
    ma10 = close.rolling(10).mean().iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]
    avg = (ma5 + ma10 + ma20) / 3
    if avg == 0:
        return False
    return (max(ma5, ma10, ma20) - min(ma5, ma10, ma20)) / avg < 0.02


def check_ma60_breakout(df: pd.DataFrame) -> bool:
    """突破60日均线：昨收在MA60下方，今收在MA60上方。"""
    if len(df) < 62:
        return False
    close = df["close"]
    ma60 = close.rolling(60).mean()
    return bool(close.iloc[-2] < ma60.iloc[-2] and close.iloc[-1] > ma60.iloc[-1])


def check_volume_breakout(df: pd.DataFrame) -> bool:
    """放量突破：今日创20日新高，且成交量≥20日均量1.5倍。"""
    if len(df) < 21:
        return False
    prev = df.iloc[-21:-1]
    today = df.iloc[-1]
    return bool(
        today["close"] > prev["high"].max()
        and today["volume"] >= prev["volume"].mean() * 1.5
    )


def check_low_vol_consolidation(df: pd.DataFrame) -> bool:
    """缩量调整：近5日价格区间<3%，且成交量连续萎缩。"""
    if len(df) < 5:
        return False
    last5 = df.iloc[-5:]
    avg_close = last5["close"].mean()
    if avg_close == 0:
        return False
    rng = (last5["high"].max() - last5["low"].min()) / avg_close
    vols = last5["volume"].values
    declining = all(vols[i] >= vols[i + 1] for i in range(len(vols) - 1))
    return rng < 0.03 and declining


def check_double_bottom(df: pd.DataFrame) -> bool:
    """双底（W底）：近60日两个相近低点（差<5%），当前价突破颈线。"""
    if len(df) < 40:
        return False
    n = min(60, len(df))
    p = df["close"].values[-n:]
    lows = _local_minima(p, window=3)
    if len(lows) < 2:
        return False
    i1, i2 = lows[-2], lows[-1]
    avg_low = (p[i1] + p[i2]) / 2
    if avg_low == 0:
        return False
    if abs(p[i1] - p[i2]) / avg_low > 0.05:
        return False
    neckline = p[i1:i2 + 1].max()
    return bool(p[-1] > neckline * 1.01)


def check_oversold_bounce(df: pd.DataFrame) -> bool:
    """超卖反弹：近期RSI曾低于30，且最近2日RSI持续回升。"""
    if len(df) < 16:
        return False
    close = df["close"]
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14).mean()
    loss = (-delta.clip(upper=0)).rolling(14).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    r = rsi.iloc[-6:]
    return bool(r.min() < 30 and rsi.iloc[-1] > rsi.iloc[-2])


def check_golden_cross_ma(df: pd.DataFrame) -> bool:
    """均线金叉：MA5 昨日在MA10下方，今日上穿MA10。"""
    if len(df) < 12:
        return False
    close = df["close"]
    ma5  = close.rolling(5).mean()
    ma10 = close.rolling(10).mean()
    return bool(ma5.iloc[-2] < ma10.iloc[-2] and ma5.iloc[-1] > ma10.iloc[-1])


# ── 形态目录（CATALOG） ───────────────────────────────────────────────────────

CATALOG = [
    {"id": "three_soldiers",        "name": "红三兵",       "desc": "连续3日阳线，收盘依次抬高，强势上升信号",          "fn": check_three_soldiers},
    {"id": "morning_star",          "name": "早晨之星",     "desc": "大阴+小星+大阳，经典三日底部反转形态",            "fn": check_morning_star},
    {"id": "hammer",                "name": "锤头线",       "desc": "下影线≥实体2倍，潜在底部支撑信号",              "fn": check_hammer},
    {"id": "macd_divergence",       "name": "MACD底背离",   "desc": "价格创新低但MACD柱不创新低，反转预警",            "fn": check_macd_divergence},
    {"id": "ma_convergence",        "name": "均线粘合",     "desc": "MA5/10/20高度接近，即将选择突破方向",            "fn": check_ma_convergence},
    {"id": "ma60_breakout",         "name": "突破60日线",   "desc": "收盘价从MA60下方向上穿越，中期趋势转强",          "fn": check_ma60_breakout},
    {"id": "volume_breakout",       "name": "放量突破",     "desc": "创20日新高且量能放大1.5倍，趋势启动信号",         "fn": check_volume_breakout},
    {"id": "low_vol_consolidation", "name": "缩量调整",     "desc": "价格横盘+量能持续萎缩，蓄力蓄势中",              "fn": check_low_vol_consolidation},
    {"id": "double_bottom",         "name": "双底形态",     "desc": "W型底部两低点相近，颈线突破确认反转",             "fn": check_double_bottom},
    {"id": "oversold_bounce",       "name": "超卖反弹",     "desc": "RSI<30后回升，超卖区域抄底反弹信号",             "fn": check_oversold_bounce},
    {"id": "golden_cross_ma",       "name": "均线金叉",     "desc": "MA5上穿MA10，短期趋势转多",                    "fn": check_golden_cross_ma},
]

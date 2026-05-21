"""strategies/patterns.py — 通信达风格 K 线形态识别"""
import numpy as np
import pandas as pd

try:
    from PIL import Image, ImageDraw
    _HAS_PIL = True
except Exception:
    _HAS_PIL = False


# ── 内部工具 ─────────────────────────────────────────────────────────────────

def _board_pct_cap(code: str) -> float:
    """按板块返回单日 |涨跌幅| 上限（含余量）：
    创业板/科创板 20cm → 0.205；北交所 30cm → 0.305；主板 10cm → 0.105。
    """
    code = str(code or "")
    if code.startswith(("300", "301", "688", "689")):
        return 0.205
    if code.startswith(("8", "4", "920")):
        return 0.305
    return 0.105


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
    body1 = d1["open"] - d1["close"]     # 阴线实体（正值）
    body2 = abs(d2["close"] - d2["open"])
    body3 = d3["close"] - d3["open"]     # 阳线实体（正值）
    range1 = d1["high"] - d1["low"]      # 第一根K线振幅
    if range1 == 0 or body1 <= 0 or body3 <= 0:
        return False
    # 第一根须为大阴线：实体占振幅 >= 60%（A股标准）
    if body1 / range1 < 0.6:
        return False
    # 星体须极小：实体不超过第一根振幅的 5%（避免假星）
    if body2 / range1 > 0.05:
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
    if len(df) < 30:
        return False
    close = df["close"]
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(com=13, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=13, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    r = rsi.iloc[-6:]
    return bool(
        r.min() < 30
        and rsi.iloc[-1] > rsi.iloc[-2]
        and rsi.iloc[-2] > rsi.iloc[-3]
    )


def check_golden_cross_ma(df: pd.DataFrame) -> bool:
    """均线金叉：MA5 昨日在MA10下方，今日上穿MA10。"""
    if len(df) < 12:
        return False
    close = df["close"]
    ma5  = close.rolling(5).mean()
    ma10 = close.rolling(10).mean()
    return bool(ma5.iloc[-2] < ma10.iloc[-2] and ma5.iloc[-1] > ma10.iloc[-1])


def check_ma_bullish_arrangement(df: pd.DataFrame) -> bool:
    """多头排列：MA5>MA10>MA20>MA60，均线多头发散，强势趋势确认。"""
    if len(df) < 62:
        return False
    close = df["close"]
    ma5  = close.rolling(5).mean().iloc[-1]
    ma10 = close.rolling(10).mean().iloc[-1]
    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1]
    return bool(ma5 > ma10 > ma20 > ma60)


def check_box_breakout(df: pd.DataFrame) -> bool:
    """箱体突破：近20日形成振幅≤5%箱体，10日内放量突破箱顶>3%且未跌回，确认突破有效。"""
    if len(df) < 30:
        return False
    # 前20根K线作为箱体形成期（不含近10日突破窗口的K线）
    box = df.iloc[-30:-10]
    box_hi = box["high"].max()
    box_lo = box["low"].min()
    if box_lo == 0:
        return False
    if (box_hi - box_lo) / box_lo > 0.05:
        return False
    avg_vol = box["volume"].mean()
    if avg_vol == 0:
        return False
    # 遍历近10日，查找最早满足突破条件的K线
    recent = df.iloc[-10:]
    breakout_idx = None
    for i in range(len(recent)):
        row = recent.iloc[i]
        if row["close"] > box_hi * 1.03 and row["volume"] >= avg_vol * 2:
            breakout_idx = i
            break
    if breakout_idx is None:
        return False
    # 突破日后未跌回箱体：所有后续收盘价均≥箱顶
    post = recent.iloc[breakout_idx + 1:]
    if len(post) > 0 and (post["close"] < box_hi).any():
        return False
    return True


def check_ma_smooth_up(df: pd.DataFrame) -> bool:
    """均线顺畅上行：近20日MA20线性拟合R²≥0.85且斜率为正，趋势平滑无扰动。"""
    if len(df) < 40:
        return False
    close = df["close"]
    ma20 = close.rolling(20).mean().dropna()
    if len(ma20) < 20:
        return False
    y = ma20.values[-20:]
    x = np.arange(len(y), dtype=float)
    coeffs = np.polyfit(x, y, 1)
    slope = coeffs[0]
    if slope <= 0:
        return False
    y_hat = np.polyval(coeffs, x)
    ss_res = float(np.sum((y - y_hat) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2))
    if ss_tot == 0:
        return False
    r2 = 1 - ss_res / ss_tot
    return r2 >= 0.85


def check_low_vol_pullback(df: pd.DataFrame) -> bool:
    """缩量回调：10日内涨幅≥5%后回调未破MA5，今日量≤前5日峰量75%且低于前5日均量，回调≤8%。"""
    if len(df) < 15:
        return False
    close  = df["close"].values
    low    = df["low"].values
    volume = df["volume"].values

    ma5        = close[-5:].mean()
    ma5_5d_ago = close[-10:-5].mean()

    close_10d         = close[-10:]
    highest_close_10d = close_10d.max()
    prior5_vol        = volume[-6:-1]           # 前5日量（不含今日），捕捉近期峰量
    peak_vol_prior5   = float(prior5_vol.max())
    avg_vol_prior5    = float(prior5_vol.mean())

    if ma5 == 0 or peak_vol_prior5 == 0 or avg_vol_prior5 == 0:
        return False
    if (highest_close_10d / close[-10] - 1) < 0.05:              # P1 前期涨幅≥5%
        return False
    if close[-1] >= highest_close_10d * 0.998:                    # C1 已有回落（0.2%即可）
        return False
    if close[-1] < ma5 * 0.995:                                   # C2 收盘未破MA5（0.5%缓冲）
        return False
    if low[-1] < ma5 * 0.99:                                      # C3 低点未破MA5（1%缓冲）
        return False
    if (highest_close_10d - close[-1]) / highest_close_10d > 0.08:  # C4 回调≤8%
        return False
    if volume[-1] > peak_vol_prior5 * 0.75:                       # V1 今日量≤前5日峰量75%
        return False
    if volume[-1] > avg_vol_prior5:                               # V2 今日量低于前5日均量
        return False
    if ma5 <= ma5_5d_ago:                                         # A1 MA5向上倾斜
        return False
    return True


def check_arc_up(df: pd.DataFrame) -> bool:
    """圆弧上行（基于实际 MA10 几何）：60 日内 MA10 呈 U 形圆弧，末段持续上行。

    闸门（12 关）：
      G1  长度 ≥80 且含 volume 列
      G2  60 日内单日 |涨跌幅| ≤ 板块上限（主板10.5%/双创20.5%/北交所30.5%）
      G3  MA10 最低点位于窗口中段 [18, 42]（避开单边趋势和末端尖底）
      G4  前段下行：从底部前的 MA10 局部高点回落 ≤ -1%
      G5  后段上行：(MA10[-1] - MA10[min]) / MA10[min] ≥ 5%
      G6  平滑底：最低点 ±3 日邻居均值 / MA10[min] ≤ 1.02（避免尖 V）
      G7  末段（最后 15 日）MA10 线性斜率/均值 ≥ 0.2%/日
      G8  末段角度 arctan(slope*100) ≤ 70°（圆弧而非火箭）
      G9  窗口 close 净涨幅 ≥ 8%
      G10 量能放大：最低点之后均量 ≥ 之前均量 × 1.1
      G11 末端未拐头：close[-1] / max(close[-7:]) ≥ 0.95（近 7 日从高点回撤 ≤5%）
      G12 收盘在 60 日均线之上：close[-1] ≥ MA60[-1]
    """
    if len(df) < 80 or "volume" not in df.columns:
        return False
    N = 60
    close_full = df["close"].values.astype(float)
    # 停牌期 volume 为 NaN：前向填充（用停牌前最后量能补齐），再判定
    vol_s = pd.Series(df["volume"].values[-N:].astype(float))
    if vol_s.isna().all():
        return False
    vol = vol_s.ffill().bfill().values
    if np.any(vol < 0):
        return False
    close = close_full[-N:]
    if np.isnan(close).any() or close[0] <= 0:
        return False
    pct = pd.Series(close).pct_change().values[1:]
    cap = _board_pct_cap(df.attrs.get("code", "") if hasattr(df, "attrs") else "")
    if np.isnan(pct).any() or np.max(np.abs(pct)) > cap:
        return False

    ma10 = pd.Series(close_full).rolling(10).mean().values[-N:]
    if np.isnan(ma10).any() or ma10[0] <= 0:
        return False

    idx_min = int(np.argmin(ma10))
    if not (18 <= idx_min <= 42):
        return False

    # 前段回落幅度从「底部之前的 MA10 局部高点」度量，而非窗口起点：
    # 否则窗口若以上行开局（起点≈底部水平），会把真实的圆弧回落误判为几乎无回落。
    pre_peak = float(np.max(ma10[:idx_min + 1]))
    if pre_peak <= 0 or (ma10[idx_min] - pre_peak) / pre_peak > -0.01:
        return False

    if ma10[idx_min] <= 0 or (ma10[-1] - ma10[idx_min]) / ma10[idx_min] < 0.05:
        return False

    nb_lo = max(0, idx_min - 3)
    nb_hi = min(N, idx_min + 4)
    neighbors = [ma10[i] for i in range(nb_lo, nb_hi) if i != idx_min]
    if neighbors:
        nb_avg = float(np.mean(neighbors))
        if nb_avg > 0 and nb_avg / ma10[idx_min] > 1.02:
            return False

    tail = ma10[-15:]
    tail_mean = float(np.mean(tail))
    if tail_mean <= 0:
        return False
    s_tail = np.polyfit(np.arange(15, dtype=float), tail, 1)[0] / tail_mean
    if s_tail < 0.002:
        return False
    if np.arctan(s_tail * 100) * 180 / np.pi > 70:
        return False

    if close[-1] / close[0] - 1 < 0.08:
        return False

    vol_pre = float(np.mean(vol[:idx_min]))
    vol_post = float(np.mean(vol[idx_min:]))
    if vol_pre <= 0 or vol_post < vol_pre * 1.1:
        return False

    close_last7 = close[-7:]
    peak7 = float(close_last7.max())
    if peak7 > 0 and close[-1] / peak7 < 0.95:
        return False

    ma60 = pd.Series(close_full).rolling(60).mean().values[-1]
    if np.isnan(ma60) or close[-1] < ma60:
        return False

    return True


# ── 圆弧流畅：可视坐标系（复刻渲染图宽高比）几何度量 ────────────────────────
#
# 设计要点（按图形选，不做归一坐标统计）：
#   1. 主图价格子图的实际渲染宽高比 ≈ 2.8 : 1
#      （容器宽≈720 − 左右边距140 ≈ 580px；总高≈360 − 上下边距80，主图占比0.74 ≈ 207px）
#   2. y 轴量程 = 区间内 K 线 [最低-pad, 最高+pad]（pad=幅度3%），与 build_kline_chart 一致
#   3. 把均线段映射进这个像素盒，再量「角度 / 圆弧贴合度」——肉眼看到的形状即所量
#
# 阈值均为该几何下的角度（度），便于后续调参。
ARC_ASPECT = 2.8       # 主图 宽:高，复刻实际渲染图
ARC_PAD = 0.03         # y 轴上下留白，与图表一致
_RASTER_H = 200        # 栅格图高(px)；宽 = H × ARC_ASPECT，复刻渲染图比例

_FLAT_DEG = 5.0          # 弦角 < 此值 → 太平
_END_STEEP_DEG = 30.0    # 末段切线 > 此值 → 末端拉升过度（追高风险）
_LOCAL_STEEP_DEG = 52.0  # 任一处局部切线 > 此值 → 急拐 / 垂直拉升
_BOW_FULL = 0.016        # close 弓形 ≥ 此值 → 圆弧感满额（曲率充足）
_BOW_MIN = 0.003         # close 弓形 ≤ 此值 → 近直线，圆弧感归底


def _pixel_angles(seg, lo, hi):
    """把序列放进「复刻渲染图」像素盒（宽 ARC_ASPECT × 高 1），返回各点切线角(度)。

    y 轴自适应到该区间 K 线高低，故角度即肉眼在图上看到的斜率。
    """
    n = len(seg)
    if n < 3 or hi - lo < 1e-12:
        return None
    W, H = ARC_ASPECT, 1.0
    x = np.arange(n, dtype=float) / (n - 1) * W
    y = (np.asarray(seg, dtype=float) - lo) / (hi - lo) * H
    ang = np.empty(n)
    ang[0] = np.degrees(np.arctan2(y[1] - y[0], x[1] - x[0]))
    ang[-1] = np.degrees(np.arctan2(y[-1] - y[-2], x[-1] - x[-2]))
    for i in range(1, n - 1):
        ang[i] = np.degrees(np.arctan2(y[i + 1] - y[i - 1], x[i + 1] - x[i - 1]))
    return ang


def _smooth3(a):
    """3 点居中滑动平均（边缘复制）——居中即无滞后，抑制单根 K 线毛刺。"""
    if a is None or len(a) < 3:
        return a
    pad = np.pad(a, 1, mode="edge")
    return np.convolve(pad, np.ones(3) / 3.0, mode="valid")


def _close_bow(seg, lo, hi):
    """量「弓形」：在像素盒里，价格线相对首尾弦的有向偏离（对弦长归一）。

    正值=点在弦下方=凹向上（真圆弧）；负值=凹向下（拱顶/拐头向下）。
    用居中平滑后的原始 close，规避均线滞后在左端伪造的凹向上假象。
    返回 (bow_up, bow_dn)。
    """
    if seg is None or len(seg) < 5 or hi - lo < 1e-12:
        return 0.0, 0.0
    y = (_smooth3(np.asarray(seg, dtype=float)) - lo) / (hi - lo)
    n = len(y)
    x = np.arange(n, dtype=float) / (n - 1) * ARC_ASPECT
    chord = y[0] + (y[-1] - y[0]) * (x - x[0]) / (x[-1] - x[0])
    dev = chord - y
    chord_len = float(np.hypot(x[-1] - x[0], y[-1] - y[0]))
    if chord_len < 1e-9:
        return 0.0, 0.0
    return float(np.max(dev) / chord_len), float(np.min(dev) / chord_len)


def _render_curve(seg, lo, hi):
    """把均线段真正画成栅格图（复刻渲染图宽高比），返回灰度像素矩阵。

    与肉眼一致：x 等距铺满图宽，y 按 [lo,hi] 量程映射，图像行向下为正。
    用 PIL 连成折线（与图表上看到的曲线同一根线），后续只在像素上做形状分析。
    """
    n = len(seg)
    if not _HAS_PIL or n < 2 or hi - lo < 1e-12:
        return None
    h_px = _RASTER_H
    w_px = int(round(h_px * ARC_ASPECT))
    xs = np.arange(n, dtype=float) / (n - 1) * (w_px - 1)
    ys = (1.0 - (np.asarray(seg, dtype=float) - lo) / (hi - lo)) * (h_px - 1)
    img = Image.new("L", (w_px, h_px), 0)
    draw = ImageDraw.Draw(img)
    draw.line(list(zip(xs.tolist(), ys.tolist())), fill=255, width=1)
    return np.asarray(img)


def _curve_centerline(raster):
    """从栅格图逐列提取曲线中心（点亮像素的行均值）——把画出来的线读回成坐标。

    返回 (col, row_up)：col 为像素列，row_up 为「向上为正」的像素行（已翻转图像坐标）。
    """
    if raster is None:
        return None
    h_px, w_px = raster.shape
    row_idx, col_idx = np.nonzero(raster)          # 点亮像素的 (行, 列)
    cnt = np.bincount(col_idx, minlength=w_px)
    rsum = np.bincount(col_idx, weights=row_idx, minlength=w_px)
    mask = cnt > 0
    if int(mask.sum()) < 5:
        return None
    col = np.where(mask)[0].astype(float)
    row_up = (h_px - 1) - (rsum[mask] / cnt[mask])   # 行均值，翻成向上为正
    return col, row_up


def _arc_metrics(ma_seg, lo, hi):
    """把均线段渲染成栅格图，再在「像素」上量圆弧贴合度——按图形选，不用价格数列统计。

    lo/hi 为该区间 K 线的 y 轴量程（含 pad），三条均线共用，保证比例一致。
    返回 fit（圆弧贴合度 0~1）、chord_deg（整段弦角）、turn_deg（切线总旋转，正=凹向上）。
    """
    n = len(ma_seg)
    if n < 5 or hi - lo < 1e-12:
        return None

    raster = _render_curve(ma_seg, lo, hi)
    cl = _curve_centerline(raster)
    if cl is None:
        return None
    x, y = cl                       # 像素列 / 向上为正的像素行
    chord_deg = float(np.degrees(np.arctan2(y[-1] - y[0], x[-1] - x[0])))

    # 切线 / 曲率在「重采样曲线」上量：560 列过采样会把渲染锯齿放大成假抖动，
    # 肉眼追的是整体走向，故等距取 40 点（即沿画出来的线扫读 40 处坡度）再量单调。
    npt = 40
    xi = np.linspace(x[0], x[-1], npt)
    yi = _smooth3(np.interp(xi, x, y))
    ang = np.degrees(np.arctan2(np.gradient(yi), np.gradient(xi)))
    turn_deg = float(ang[-1] - ang[0])

    # 圆弧贴合度：像素点是否落在同一圆上（曲率恒定）。残差对弦长归一，直线半径∞不奖励。
    A = np.column_stack([x, y, np.ones_like(x)])
    b = -(x ** 2 + y ** 2)
    sol, *_ = np.linalg.lstsq(A, b, rcond=None)
    D, E, F = sol
    cx, cy = -D / 2.0, -E / 2.0
    r_sq = cx * cx + cy * cy - F
    chord_len = float(np.hypot(x[-1] - x[0], y[-1] - y[0]))
    if r_sq <= 0 or chord_len < 1e-9:
        rel_resid = 1.0
    else:
        r = np.sqrt(r_sq)
        d = np.sqrt((x - cx) ** 2 + (y - cy) ** 2)
        rel_resid = float(np.sqrt(np.mean((d - r) ** 2)) / chord_len)
    resid_score = 1.0 / (1.0 + (rel_resid / 0.03) ** 2)   # rel=0.03 → 0.5

    # 切线单调（无锯齿）：相邻切线角差应同号；0（持平）不计为翻转
    dsign = np.sign(np.diff(ang))
    nz = dsign[dsign != 0]
    flips = int(np.count_nonzero(nz[:-1] != nz[1:])) if len(nz) > 1 else 0
    mono = max(0.0, 1.0 - flips / max(1, npt - 3))

    fit = 0.6 * resid_score + 0.4 * mono
    return {"fit": fit, "chord_deg": chord_deg, "turn_deg": turn_deg}


def _arc_line_score(metrics: dict) -> float:
    """单条均线的「平滑度」分（0~1）：圆弧贴合度 − 太平惩罚。

    圆弧感（真曲率）与陡度/急拐都不在此判定——均线滞后会伪造曲率、平滑会抹掉急拉，
    二者改在原始 close 上全局判定（见 _close_bow / 末端切线）。
    """
    fit = metrics["fit"]
    chord = metrics["chord_deg"]
    flat_pen = min(0.5, (_FLAT_DEG - chord) / 5.0) if chord < _FLAT_DEG else 0.0
    return max(0.0, fit - flat_pen)


def arc_flow_score(df: pd.DataFrame, window: int = 60) -> float:
    """三线共振圆弧流畅度评分（0~1）——在复刻渲染图的可视坐标系里量形状。

    参照框架：60MA 基准 + 30MA 拐头向上当天的 30MA 值水平线为 X 轴
    主弧 MA10（权重 0.50）+ 辅弧 MA5（0.25）+ MA20（0.25）
    前置条件：至少最近 2 个交易日 MA30 > MA60；MA30 近期有拐头向上点，整段上行腿 ≥ 5 根 K 线。
    """
    if "close" not in df.columns or len(df) < 70:
        return 0.0

    close = df["close"].values.astype(float)
    if np.isnan(close).any() or close[-1] <= 0:
        return 0.0
    has_hl = "high" in df.columns and "low" in df.columns
    high = df["high"].values.astype(float) if has_hl else close
    low = df["low"].values.astype(float) if has_hl else close

    # ── Stage 0: 前置条件 ─────────────────────────────────────────
    ma30 = pd.Series(close).rolling(30).mean().values
    ma60 = pd.Series(close).rolling(60).mean().values
    # 0a. 至少最近 2 个交易日 MA30 高于 MA60
    if np.isnan(ma30[-2:]).any() or np.isnan(ma60[-2:]).any():
        return 0.0
    if not (ma30[-2:] > ma60[-2:]).all():
        return 0.0

    # 0b. MA30 拐头向上：在前 60 日范围内找由跌转涨的最近拐点
    ma5_full = pd.Series(close).rolling(5).mean().values
    ma10_full = pd.Series(close).rolling(10).mean().values
    ma20_full = pd.Series(close).rolling(20).mean().values

    valid = ~np.isnan(ma30)
    if not valid.any():
        return 0.0
    valid_start = int(np.where(valid)[0][0])
    ma30_v = ma30[valid_start:]
    diffs = np.diff(ma30_v)

    search_start = max(1, len(ma30_v) - 60)
    search_end = len(diffs) - 3            # 上行腿 ≥ 5 根 K 线（拐头即可分析）
    turn_idx = -1
    for i in range(search_end - 1, search_start - 1, -1):
        if diffs[i - 1] <= 0 and diffs[i] > 0:
            turn_idx = i
            break
    if turn_idx < 0:
        return 0.0

    turn_idx_full = valid_start + turn_idx

    # ── 区间 = 拐点 → 今天；y 量程取该区间 K 线高低（复刻图表 y 轴）──────
    seg_lo = float(np.nanmin(low[turn_idx_full:]))
    seg_hi = float(np.nanmax(high[turn_idx_full:]))
    pad = (seg_hi - seg_lo) * ARC_PAD
    y_lo, y_hi = seg_lo - pad, seg_hi + pad

    ma5_seg = ma5_full[turn_idx_full:]
    ma10_seg = ma10_full[turn_idx_full:]
    ma20_seg = ma20_full[turn_idx_full:]

    if np.isnan(ma10_seg).any() or len(ma10_seg) < 5:
        return 0.0
    if ma10_seg[-1] <= ma10_seg[0]:
        return 0.0

    # ── Stage 1: MA10 主弧（权重 0.50） ────────────────────────────
    m10 = _arc_metrics(ma10_seg, y_lo, y_hi)
    if m10 is None:
        return 0.0
    ma10_score = _arc_line_score(m10)

    # ── Stage 2: MA5 / MA20 辅弧（各 0.25） ───────────────────────
    m5 = _arc_metrics(ma5_seg, y_lo, y_hi) if (not np.isnan(ma5_seg).any() and ma5_seg[-1] > ma5_seg[0]) else None
    m20 = _arc_metrics(ma20_seg, y_lo, y_hi) if (not np.isnan(ma20_seg).any() and ma20_seg[-1] > ma20_seg[0]) else None
    ma5_score = _arc_line_score(m5) if m5 else 0.0
    ma20_score = _arc_line_score(m20) if m20 else 0.0

    # ── Stage 3: 结构校验 + 综合 ──────────────────────────────────
    ma5_raw, ma10_raw, ma20_raw = ma5_seg, ma10_seg, ma20_seg
    order_ok = (ma5_raw[-1] > ma10_raw[-1]) and (ma10_raw[-1] > ma20_raw[-1])
    order_pen = 0.0 if order_ok else 0.10

    spread = ma5_raw - ma20_raw
    mid = len(spread) // 2
    diverge_ok = float(np.mean(spread[mid:])) > float(np.mean(spread[:mid]))
    diverge_pen = 0.0 if diverge_ok else 0.05

    close_seg = close[turn_idx_full:]

    # 圆弧感（真曲率）：在原始 close（居中平滑、无滞后）上量弓形。
    # 直线 / 太陡线弓形≈0 → 压分；真圆弧弓形充足 → 满额；凹向下（拱顶）→ 重罚。
    bow_up, bow_dn = _close_bow(close_seg, y_lo, y_hi)
    curve_gate = float(np.clip((bow_up - _BOW_MIN) / (_BOW_FULL - _BOW_MIN), 0.30, 1.0))
    if bow_dn < -0.012:
        curve_gate *= 0.4

    # 陡度 / 急拐：挂在原始 close 上量切线角，规避均线平滑掩盖末端急拉。
    # 同一像素盒、同一 y 量程，故角度即肉眼斜率；3 点平滑去掉单根 K 线毛刺。
    steep_pen = 0.0
    close_ang = _pixel_angles(close_seg, y_lo, y_hi)
    if close_ang is not None and len(close_ang) >= 3:
        sm = _smooth3(close_ang)
        end_tan = float(np.mean(sm[-3:]))      # 末端切线 → 末端拉升过度
        max_tan = float(np.max(sm))            # 任一处局部切线 → 急拐 / 垂直拉升
        if end_tan > _END_STEEP_DEG:
            steep_pen = max(steep_pen, min(0.6, (end_tan - _END_STEEP_DEG) / 25.0))
        if max_tan > _LOCAL_STEEP_DEG:
            steep_pen = max(steep_pen, min(0.6, (max_tan - _LOCAL_STEEP_DEG) / 25.0))

    score = (0.50 * ma10_score + 0.25 * ma5_score + 0.25 * ma20_score) * curve_gate
    score -= order_pen + diverge_pen + steep_pen

    # 收盘价拐头检测（规避 MA10 滞后导致顶部仍高分）
    tail_n = min(15, len(close) // 4)
    close_tail = close[-tail_n:]
    peak_idx = int(np.argmax(close_tail))
    peak_val = float(close_tail[peak_idx])
    cur_close = float(close[-1])
    days_from_peak = tail_n - 1 - peak_idx
    if peak_val > 0 and days_from_peak >= 3:
        decline_ratio = (peak_val - cur_close) / peak_val
        if decline_ratio > 0.03:
            severity = min(1.0, decline_ratio * 10)
            score -= 0.05 + severity * 0.25

    return max(0.0, min(1.0, float(score)))


def check_close_above_ma5(df: pd.DataFrame) -> bool:
    """近5日收盘价均在MA5之上：连续5日收盘 >= MA5，短线强势持续信号。"""
    if len(df) < 10:
        return False
    close = df["close"]
    ma5 = close.rolling(5).mean()
    last5_close = close.iloc[-5:]
    last5_ma5 = ma5.iloc[-5:]
    if last5_ma5.isna().any():
        return False
    return bool((last5_close.values >= last5_ma5.values).all())


def check_arc_flow(df: pd.DataFrame, min_score: float = 0.4) -> bool:
    """圆弧流畅度筛选：arc_flow_score >= min_score（默认 0.4，约全市场前 3%）。"""
    return arc_flow_score(df) >= min_score


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
    {"id": "low_vol_pullback",     "name": "缩量回调",     "desc": "涨后回调守住五日线，今日量缩至前5日峰量75%以下",   "fn": check_low_vol_pullback},
    {"id": "double_bottom",         "name": "双底形态",     "desc": "W型底部两低点相近，颈线突破确认反转",             "fn": check_double_bottom},
    {"id": "oversold_bounce",       "name": "超卖反弹",     "desc": "RSI<30后回升，超卖区域抄底反弹信号",             "fn": check_oversold_bounce},
    {"id": "golden_cross_ma",       "name": "均线金叉",     "desc": "MA5上穿MA10，短期趋势转多",                    "fn": check_golden_cross_ma},
    {"id": "ma_bullish_arrangement", "name": "多头排列",     "desc": "MA5>MA10>MA20>MA60，均线多头发散，强趋势信号",   "fn": check_ma_bullish_arrangement},
    {"id": "box_breakout",    "name": "箱体突破",     "desc": "近20日箱体振幅≤5%，10日内放量突破箱顶>3%且未跌回，确认突破有效",  "fn": check_box_breakout},
    {"id": "ma_smooth_up",    "name": "均线顺畅上行",  "desc": "MA20近20日线性拟合R²≥0.85+正斜率，趋势平滑无扰动",  "fn": check_ma_smooth_up},
    {"id": "arc_up",          "name": "圆弧上行",     "desc": "60日三阶段圆弧（筑底→振荡→上行）：MA5/MA10/MA20均先抑后扬，振荡期缩量+上行期放量≥1.1×，单日波动≤板块上限，末端上行角度≤70°", "fn": check_arc_up},
    {"id": "arc_flow",        "name": "圆弧流畅",     "desc": "三线共振圆弧：60MA基底+30MA拐头向上，MA5/MA10/MA20弧形流畅度综合评分≥0.4（扇形弧线形态）", "fn": check_arc_flow},
    {"id": "close_above_ma5", "name": "五日线上方",   "desc": "近5日收盘价均在MA5之上，短线强势持续信号",              "fn": check_close_above_ma5},
]

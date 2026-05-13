"""
data/auto_updater.py — 后台智能增量更新模块

负责在独立守护线程中自动更新本地 SQLite K线数据库：
- 首次运行：全量下载最近3年数据（days=1095）
- 增量运行：从已有 last_date 往前5天拉取（确保无缝衔接）
- 线程安全：模块级 _state dict + threading.Lock，跨 Streamlit rerun 持久
- 容错性强：单只股票失败不中止批次；baostock 空返回按正常处理；非交易日自动适配

典型用法（Streamlit）：
    from data.auto_updater import start_update, get_state, is_running
    start_update()          # 启动后台更新（重复调用安全）
    state = get_state()     # 任意时刻读取进度
"""

import threading
from datetime import datetime, timedelta
from data.sources._baostock_utils import _bs_lock as _baostock_lock

# ---------------------------------------------------------------------------
# 线程安全全局状态
# ---------------------------------------------------------------------------

_lock = threading.Lock()

_state: dict = {
    "status":   "idle",       # idle | running | done | error
    "message":  "尚未开始",
    "progress": 0,
    "total":    0,
    "updated":  0,
    "failed":   0,
    "skipped":  0,
    "last_run": None,          # "YYYY-MM-DD HH:MM"
    "error":    None,
}


def _set_state(**kwargs) -> None:
    """线程安全地批量更新 _state 字段。"""
    with _lock:
        _state.update(kwargs)


# ---------------------------------------------------------------------------
# 交易日工具
# ---------------------------------------------------------------------------

def get_last_trading_day() -> str:
    """
    返回最近交易日（排除周末和法定节假日）的 "YYYY-MM-DD"。
    优先使用 chinese_calendar 判断节假日；不可用时降级为只过滤周末。
    """
    from datetime import date, timedelta
    day = date.today()
    try:
        import chinese_calendar as cc
        for _ in range(30):
            day -= timedelta(days=1)
            if cc.is_workday(day):
                return day.strftime("%Y-%m-%d")
    except ImportError:
        from datetime import datetime
        d = datetime.today()
        for _ in range(20):
            d -= timedelta(days=1)
            if d.weekday() < 5:
                return d.strftime("%Y-%m-%d")
    return (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")


def is_data_fresh(last_date_str: str) -> bool:
    """
    若 last_date_str >= get_last_trading_day() 则视为数据已是最新，返回 True。
    last_date_str 格式为 "YYYY-MM-DD"；为空/None 时返回 False。
    """
    if not last_date_str:
        return False
    return last_date_str >= get_last_trading_day()


def is_data_complete(code: str, last_date_str: str, min_rows: int = 500) -> bool:
    """
    数据完整性检查：date 已是最新 且 K线记录数 >= min_rows（默认500条≈2年交易日）。
    比 is_data_fresh 更严格，可检测首次下载被截断的情况。
    """
    if not is_data_fresh(last_date_str):
        return False
    from data.db.manager import get_daily_count
    return get_daily_count(code) >= min_rows


# ---------------------------------------------------------------------------
# 核心后台更新逻辑
# ---------------------------------------------------------------------------

def _run_update(full_market: bool = True) -> None:
    """
    在后台线程中执行增量/全量 K 线更新。
    调用方通过 _state 读取进度；不直接抛出异常，所有错误写入 _state。
    """
    import baostock as bs
    import pandas as pd

    from data.sources.akshare_source import _baostock_get_all_codes
    from data.db.manager import upsert_daily, upsert_meta, get_meta

    today_str = datetime.today().strftime("%Y-%m-%d")
    end_date  = today_str

    try:
        # ------------------------------------------------------------------
        # Step 1: 获取全市场股票列表
        # ------------------------------------------------------------------
        _set_state(message="正在获取全市场股票列表…")
        stock_list = _baostock_get_all_codes()   # 内含 bs.login/logout

        if not stock_list:
            _set_state(
                status="error",
                message="获取股票列表失败，无法继续更新",
                error="_baostock_get_all_codes() 返回空列表",
            )
            return

        # ------------------------------------------------------------------
        # Step 2: 筛选需要更新的股票，统计 skipped
        # ------------------------------------------------------------------
        to_update = []
        skipped   = 0

        for stock in stock_list:
            code = stock["code"]
            meta = get_meta(code)
            if meta and is_data_complete(code, meta.get("last_date", "")):
                skipped += 1
            else:
                to_update.append(stock)

        total = len(to_update)
        _set_state(
            message=f"共 {len(stock_list)} 只，需更新 {total} 只，跳过 {skipped} 只",
            total=total,
            skipped=skipped,
            progress=0,
            updated=0,
            failed=0,
        )

        if total == 0:
            _set_state(
                status="done",
                message=f"所有 {skipped} 只股票数据均已是最新，无需更新",
                last_run=datetime.today().strftime("%Y-%m-%d %H:%M"),
            )
            return

        # ------------------------------------------------------------------
        # Step 3: 逐只股票更新（per-stock 锁，释放锁间隙供交互式查询使用）
        # ------------------------------------------------------------------
        updated = 0
        failed  = 0

        fields = "date,open,high,low,close,volume,amount,pctChg"

        for idx, stock in enumerate(to_update):
            code = stock["code"]
            name = stock.get("name", "")
            prefix = "sh" if code.startswith("6") else "sz"
            bs_code = f"{prefix}.{code}"

            # _row_data: None=失败, []=停牌/节假日无数据, list=正常数据
            _row_data   = None
            _row_fields = None

            try:
                meta = get_meta(code)

                if meta and meta.get("last_date"):
                    last_dt    = datetime.strptime(meta["last_date"], "%Y-%m-%d")
                    start_date = (last_dt - timedelta(days=5)).strftime("%Y-%m-%d")
                else:
                    start_date = (datetime.today() - timedelta(days=1095)).strftime("%Y-%m-%d")

                # 每只股票独立持锁：login → query → logout → 释放锁
                # 锁持有时间约 1-3s，其余时间允许技术面筛选等交互请求获取锁
                with _baostock_lock:
                    try:
                        login_rs = bs.login()
                        if login_rs.error_code != "0":
                            print(f"[auto_updater] {code} baostock 登录失败: {login_rs.error_msg}")
                        else:
                            rs = bs.query_history_k_data_plus(
                                bs_code,
                                fields,
                                start_date=start_date,
                                end_date=end_date,
                                frequency="d",
                                adjustflag="2",
                            )
                            if rs.error_code != "0":
                                print(f"[auto_updater] {code} query 错误: {rs.error_code} {rs.error_msg}")
                            else:
                                _row_fields = rs.fields
                                _row_data = []
                                while rs.error_code == "0" and rs.next():
                                    _row_data.append(rs.get_row_data())
                    finally:
                        try:
                            bs.logout()
                        except Exception:
                            pass

                # 锁已释放，在锁外处理 DataFrame（纯 CPU，无 baostock 调用）
                if _row_data is None:
                    failed += 1
                elif not _row_data:
                    upsert_meta(code, name, get_last_trading_day())
                    updated += 1
                else:
                    df = pd.DataFrame(_row_data, columns=_row_fields)
                    df = df.rename(columns={"pctChg": "pct_change"})
                    df["date"] = pd.to_datetime(df["date"])
                    for col in ["open", "high", "low", "close", "volume", "amount", "pct_change"]:
                        if col in df.columns:
                            df[col] = pd.to_numeric(df[col], errors="coerce")
                    upsert_daily(code, df)
                    last_date_in_df = df["date"].max().strftime("%Y-%m-%d")
                    upsert_meta(code, name, last_date_in_df)
                    updated += 1

            except Exception as e:
                print(f"[auto_updater] {code} 处理异常: {e}")
                failed += 1

            _set_state(
                progress=idx + 1,
                updated=updated,
                failed=failed,
                message=(
                    f"进度 {idx+1}/{total}，"
                    f"已更新 {updated}，失败 {failed}，跳过 {skipped}"
                ),
            )

        # ------------------------------------------------------------------
        # 完成
        # ------------------------------------------------------------------
        _set_state(
            status="done",
            progress=total,
            updated=updated,
            failed=failed,
            last_run=datetime.today().strftime("%Y-%m-%d %H:%M"),
            message=(
                f"更新完成：共 {len(stock_list)} 只，"
                f"更新 {updated}，失败 {failed}，跳过 {skipped}"
            ),
            error=None,
        )

    except Exception as e:
        _set_state(
            status="error",
            message=f"更新过程发生意外错误: {e}",
            error=str(e),
        )


# ---------------------------------------------------------------------------
# 公共接口
# ---------------------------------------------------------------------------

def start_update(force: bool = False) -> bool:
    """
    启动后台增量更新线程。

    参数：
        force - True 则忽略"今日已完成"检查，强制重跑

    返回：
        True  - 成功启动线程
        False - 线程已在运行，或今日已完成且未强制
    """
    with _lock:
        status   = _state["status"]
        last_run = _state["last_run"]

        if status == "running":
            return False

        if not force and status == "done" and last_run:
            today_prefix = datetime.today().strftime("%Y-%m-%d")
            if last_run.startswith(today_prefix):
                return False

        # 重置状态后再放锁，防止状态撕裂
        _state.update({
            "status":   "running",
            "message":  "正在启动后台更新…",
            "progress": 0,
            "total":    0,
            "updated":  0,
            "failed":   0,
            "skipped":  0,
            "error":    None,
        })

    t = threading.Thread(target=_run_update, daemon=True)
    t.start()
    return True


def get_state() -> dict:
    """线程安全地返回当前状态副本。"""
    with _lock:
        return dict(_state)


def is_running() -> bool:
    """返回后台更新是否正在进行中。"""
    with _lock:
        return _state["status"] == "running"

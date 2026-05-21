"""
data/auto_updater.py — 后台智能增量更新模块（v2 三阶段架构）

三阶段：
  Phase 1 — 股票信息全量同步：拉取全市场股列表，批量 upsert stock_meta
  Phase 2 — 增量K线（已有股票）：只拉 last_date-2 到今天的增量天数
  Phase 3 — 新股票K线（首次入库）：拉最近365天

关键优化：
  - baostock 单次 login 覆盖 Phase 2+3 全部 query，不再逐只 login/logout
  - 批量 COUNT 替代逐只 get_daily_count
  - 批量写入 upsert_daily_batch / upsert_meta_batch
  - 完成后自动 VACUUM
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
    with _lock:
        _state.update(kwargs)


# ---------------------------------------------------------------------------
# 交易日工具
# ---------------------------------------------------------------------------

def get_last_trading_day() -> str:
    """返回最近一个"已收盘"的交易日 (YYYY-MM-DD)。

    15:30 之前触发：当日即便是交易日也算未收盘，回退到前一交易日。
    避免盘中触发后误标 last_date=today，导致次日开盘前被 is_data_fresh 跳过更新。
    """
    from datetime import date, datetime, timedelta, time as dtime
    now = datetime.now()
    closed_today = now.time() >= dtime(15, 30)
    try:
        import chinese_calendar as cc
        day = date.today() if closed_today else date.today() - timedelta(days=1)
        for _ in range(30):
            if cc.is_workday(day) and day.weekday() < 5:
                return day.strftime("%Y-%m-%d")
            day -= timedelta(days=1)
    except ImportError:
        d = date.today() if closed_today else date.today() - timedelta(days=1)
        for _ in range(20):
            if d.weekday() < 5:
                return d.strftime("%Y-%m-%d")
            d -= timedelta(days=1)
    return (date.today() - timedelta(days=1)).strftime("%Y-%m-%d")


def is_data_fresh(last_date_str: str) -> bool:
    if not last_date_str:
        return False
    return last_date_str >= get_last_trading_day()


# ---------------------------------------------------------------------------
# 核心后台更新逻辑（v2 三阶段）
# ---------------------------------------------------------------------------

def _run_update(full_market: bool = True) -> None:
    import baostock as bs
    import pandas as pd

    from data.sources.akshare_source import _baostock_get_all_codes
    from data.db.manager import (
        upsert_daily_batch, upsert_meta_batch, sync_meta_batch,
        get_all_daily_counts, vacuum_db, get_all_metas,
    )

    today_str = datetime.today().strftime("%Y-%m-%d")
    end_date = today_str
    fields = "date,open,high,low,close,volume,amount,pctChg"

    try:
        # ═══════════════════════════════════════════════════════════════════
        # Phase 1: 股票信息全量同步
        # ═══════════════════════════════════════════════════════════════════
        _set_state(status="running", message="Phase 1/3: 正在同步股票基本信息…",
                   progress=0, total=0, updated=0, failed=0, skipped=0)

        stock_list = _baostock_get_all_codes()  # 内含 bs.login/logout
        if not stock_list:
            _set_state(status="error", message="获取股票列表失败",
                       error="_baostock_get_all_codes() 返回空列表")
            return

        # 批量写入 stock_meta（已存在则更新名称，不存在则插入）
        sync_meta_batch(stock_list)
        n_total = len(stock_list)
        _set_state(message=f"Phase 1/3 完成: 已同步 {n_total} 只股票基本信息",
                   total=n_total, skipped=0)

        # ═══════════════════════════════════════════════════════════════════
        # 批量获取所有股票的K线记录数和元信息（各一次查询）
        # ═══════════════════════════════════════════════════════════════════
        _set_state(message="正在统计本地K线数据…")
        all_counts = get_all_daily_counts()       # {code: count}
        all_metas = get_all_metas()               # {code: {"name":..., "last_date":...}}

        # 分类：需要增量更新的 vs 需要首次拉取的 vs 跳过的
        phase2_stocks = []   # (code, name, prefix, bs_code, start_date)
        phase3_stocks = []   # (code, name, prefix, bs_code, start_date)
        skipped = 0

        last_trading = get_last_trading_day()
        for stock in stock_list:
            code = stock["code"]
            name = stock.get("name", "")
            prefix = "sh" if code.startswith("6") else "sz"
            bs_code = f"{prefix}.{code}"

            meta = all_metas.get(code, {})
            count = all_counts.get(code, 0)
            last_date = meta.get("last_date", "") if meta else ""

            if last_date and is_data_fresh(last_date) and count >= 500:
                skipped += 1
                continue

            if last_date and count > 0:
                # 已有数据：增量拉取
                start_dt = datetime.strptime(last_date, "%Y-%m-%d") - timedelta(days=2)
                phase2_stocks.append((code, name, prefix, bs_code, start_dt.strftime("%Y-%m-%d")))
            else:
                # 新股票：首次拉取 365 天
                start_dt = datetime.today() - timedelta(days=365)
                phase3_stocks.append((code, name, prefix, bs_code, start_dt.strftime("%Y-%m-%d")))

        to_update = len(phase2_stocks) + len(phase3_stocks)
        _set_state(
            message=f"Phase 1/3 完成: 共 {n_total} 只，增量 {len(phase2_stocks)}，"
                    f"新入库 {len(phase3_stocks)}，跳过 {skipped}",
            total=to_update, skipped=skipped, progress=0,
            updated=0, failed=0,
        )

        if to_update == 0:
            _set_state(status="done",
                       message=f"所有 {skipped} 只股票数据均已是最新",
                       last_run=datetime.today().strftime("%Y-%m-%d %H:%M"))
            return

        # ═══════════════════════════════════════════════════════════════════
        # Phase 2 & 3: K线数据更新（单次 baostock login）
        # ═══════════════════════════════════════════════════════════════════
        _set_state(message="Phase 2/3: 正在更新增量K线…")

        updated = 0
        failed = 0
        pending_writes = []  # 攒批写入: [(code, df), ...]
        BATCH_SIZE = 50      # 每50只股票批量写入一次DB

        def _flush_writes():
            nonlocal updated
            if pending_writes:
                upsert_daily_batch(pending_writes)
                n_flushed = len(pending_writes)
                # 批量更新 meta
                meta_updates = []
                for code_w, df_w in pending_writes:
                    name_w = name_map.get(code_w, "")
                    last_d = df_w["date"].max().strftime("%Y-%m-%d")
                    meta_updates.append({"code": code_w, "name": name_w, "last_date": last_d})
                upsert_meta_batch(meta_updates)
                updated += n_flushed
                pending_writes.clear()

        with _baostock_lock:
            try:
                login_rs = bs.login()
                if login_rs.error_code != "0":
                    _set_state(status="error",
                               message=f"baostock 登录失败: {login_rs.error_msg}",
                               error=login_rs.error_msg)
                    return

                all_stocks = phase2_stocks + phase3_stocks
                name_map = {c: n for c, n, *_ in all_stocks}
                for idx, (code, name, prefix, bs_code, start_date) in enumerate(all_stocks):
                    try:
                        rs = bs.query_history_k_data_plus(
                            bs_code, fields,
                            start_date=start_date, end_date=end_date,
                            frequency="d", adjustflag="2",
                        )
                        if rs.error_code != "0":
                            failed += 1
                        else:
                            rows = []
                            while rs.error_code == "0" and rs.next():
                                rows.append(rs.get_row_data())
                            if rows:
                                df = pd.DataFrame(rows, columns=rs.fields)
                                df = df.rename(columns={"pctChg": "pct_change"})
                                df["date"] = pd.to_datetime(df["date"])
                                for col in ["open", "high", "low", "close", "volume", "amount", "pct_change"]:
                                    if col in df.columns:
                                        df[col] = pd.to_numeric(df[col], errors="coerce")
                                pending_writes.append((code, df))
                            # 空返回：保持 last_date 不变，避免在盘中触发时把停牌/无成交日误标为已更新
                    except Exception as e:
                        print(f"[auto_updater] {code} 异常: {e}")
                        failed += 1

                    # 攒批写入
                    if len(pending_writes) >= BATCH_SIZE:
                        _flush_writes()

                    # 每 100 只更新一次进度
                    if (idx + 1) % 100 == 0 or idx + 1 == len(all_stocks):
                        phase_label = "2/3" if idx < len(phase2_stocks) else "3/3"
                        _set_state(
                            progress=idx + 1,
                            updated=updated,
                            failed=failed,
                            message=(f"Phase {phase_label}: 进度 {idx+1}/{to_update}，"
                                     f"已更新 {updated}，失败 {failed}，跳过 {skipped}"),
                        )

            finally:
                _flush_writes()
                try:
                    bs.logout()
                except Exception:
                    pass

        # ═══════════════════════════════════════════════════════════════════
        # 完成 & 维护
        # ═══════════════════════════════════════════════════════════════════
        _set_state(
            status="done",
            progress=to_update,
            updated=updated,
            failed=failed,
            last_run=datetime.today().strftime("%Y-%m-%d %H:%M"),
            message=(f"更新完成: 共 {n_total} 只，更新 {updated}，失败 {failed}，"
                     f"跳过 {skipped}，正在执行数据库维护…"),
            error=None,
        )

        try:
            vacuum_db()
            _set_state(message=(f"更新完成: 共 {n_total} 只，更新 {updated}，"
                                f"失败 {failed}，跳过 {skipped}"))
        except Exception as e:
            print(f"[auto_updater] VACUUM 失败: {e}")

    except Exception as e:
        _set_state(status="error", message=f"更新过程发生意外错误: {e}", error=str(e))


# ---------------------------------------------------------------------------
# 公共接口
# ---------------------------------------------------------------------------

def start_update(force: bool = False) -> bool:
    with _lock:
        status   = _state["status"]
        last_run = _state["last_run"]

        if status == "running":
            return False

        if not force and status == "done" and last_run:
            today_prefix = datetime.today().strftime("%Y-%m-%d")
            if last_run.startswith(today_prefix):
                return False

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
    with _lock:
        return dict(_state)


def is_running() -> bool:
    with _lock:
        return _state["status"] == "running"

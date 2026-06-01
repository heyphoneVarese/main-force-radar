"""盘中板块资金流采集(Phase 5.1 PR15)。

跟 data_fetcher.fetch_sector_flow_industry/concept 的区别:
- 它们写 sector_flow_daily,代表"今日收盘"累计
- 本模块写 intraday_sector_flow,每个 snapshot_time 一个快照

为什么不直接改 data_fetcher:
- R 线:"data_fetcher 现有 daily 行为" 不动
- 本模块只 import data_fetcher 的私有工具(_fetch_sector_flow_direct
  和 _safe_float),不修改 data_fetcher 任何函数
- 隔离 intraday 业务逻辑,后续若要改 snapshot 粒度 / 字段不影响 daily

snapshot_time:
- 精确到分钟(seconds/microseconds 抹掉),保证 UniqueConstraint
  (snapshot_time, sector_code) 触发幂等
- 时区 Asia/Shanghai naive datetime(跟项目其它 datetime 字段一致)
"""

from __future__ import annotations

import logging
from datetime import datetime, time
from typing import Any

import pandas as pd
from sqlalchemy.orm import Session

from src.models import IntradaySectorFlow
from src.services.data_fetcher import (
    _fetch_sector_flow_direct,
    _safe_float,
    _with_retry,
)
from src.utils.date_helper import cn_now
from src.utils.money import pct_to_int, wan_yuan_to_int

logger = logging.getLogger(__name__)


# Asia/Shanghai 交易时间窗口。9:35-11:30 + 13:00-14:55。
# 09:30-09:35 集合竞价后到正式开盘 5min 缓冲,数据稳定才采。
# 14:55-15:00 收盘前 5min 缓冲,daily_fetch 15:20 会接力拿真正的收盘累计值。
INTRADAY_WINDOWS: list[tuple[time, time]] = [
    (time(9, 35), time(11, 30)),
    (time(13, 0), time(14, 55)),
]


def is_in_trading_window(now: datetime | None = None) -> bool:
    """now 不传则用 cn_now()。仅检查时间(不查日期/节假日 — 节假日由
    cron `day_of_week='mon-fri'` 大致拦下)。
    """
    now = now or cn_now()
    t = now.time()
    return any(start <= t <= end for start, end in INTRADAY_WINDOWS)


# DB enum 串 ↔ akshare 中文参数串(跟 data_fetcher 同口径)
_AK_TYPE_MAP: dict[str, str] = {
    "industry": "行业资金流",
    "concept": "概念资金流",
}


def _df_to_intraday_rows(
    df: pd.DataFrame,
    *,
    db_sector_type: str,
    snapshot_time: datetime,
) -> list[dict[str, Any]]:
    """DataFrame → list[dict] 待入库的 intraday 行。

    跟 data_fetcher._fetch_sector_flow 的下游解析逻辑近似:
    - "今日主力净流入-净额" 单位元 → 万元 → wan_yuan_to_int
    - "今日涨跌幅" 百分比(2.34 = 2.34%) → fraction → pct_to_int
    - "今日主力净流入-净占比" 同上

    一行解析失败(任何字段) → log + skip,不抛。
    """
    trade_date = snapshot_time.date()
    out: list[dict[str, Any]] = []
    if df is None or df.empty:
        return out

    for _, row in df.iterrows():
        try:
            name = row.get("名称") or row.get("板块")
            if name is None:
                continue
            code = row.get("代码") or row.get("板块代码") or name

            main_inflow_yuan = _safe_float(row.get("今日主力净流入-净额"))
            if main_inflow_yuan is None:
                continue
            main_inflow_wan = main_inflow_yuan / 10_000

            change_pct_raw = _safe_float(row.get("今日涨跌幅"))
            main_inflow_pct_raw = _safe_float(row.get("今日主力净流入-净占比"))

            out.append({
                "trade_date": trade_date,
                "snapshot_time": snapshot_time,
                "sector_code": str(code),
                "sector_name": str(name),
                "sector_type": db_sector_type,
                "main_inflow_wan_x10000": wan_yuan_to_int(main_inflow_wan),
                "main_inflow_pct_x10000": (
                    pct_to_int(main_inflow_pct_raw / 100)
                    if main_inflow_pct_raw is not None
                    else None
                ),
                "change_pct_x10000": (
                    pct_to_int(change_pct_raw / 100)
                    if change_pct_raw is not None
                    else None
                ),
            })
        except Exception as e:
            logger.warning(
                "skip intraday row sector=%s err=%s: %s",
                dict(row), type(e).__name__, e,
            )
            continue
    return out


def fetch_and_store_intraday(
    session: Session,
    *,
    sector_types: tuple[str, ...] = ("industry", "concept"),
    snapshot_time: datetime | None = None,
) -> dict[str, Any]:
    """采集 + 入库一个 snapshot。

    Returns:
        {
          "snapshot_time": datetime,
          "inserted": int,            # 新写入行数
          "skipped": int,             # UniqueConstraint 撞到(已采集过)跳过
          "by_type": {industry: {inserted, skipped}, concept: {...}},
          "errors": [...]             # 单类 fetch 失败的错误消息
        }

    幂等保证:对每一行 select(snapshot_time, sector_code) 已存在 → skip。
    跟 data_fetcher.insert_sector_flow_rows 同口径。

    snapshot_time:不传则用 cn_now().replace(second=0, microsecond=0)。
    传入可用于测试时间穿越。
    """
    if snapshot_time is None:
        snapshot_time = cn_now().replace(second=0, microsecond=0)
    else:
        # 防外部传精确秒,统一对齐到分钟
        snapshot_time = snapshot_time.replace(second=0, microsecond=0)

    stats: dict[str, Any] = {
        "snapshot_time": snapshot_time,
        "inserted": 0,
        "skipped": 0,
        "by_type": {},
        "errors": [],
    }

    for db_type in sector_types:
        ak_type = _AK_TYPE_MAP.get(db_type)
        if ak_type is None:
            stats["errors"].append(f"unknown sector_type: {db_type}")
            continue

        label = f"intraday_{db_type}"

        def _do() -> pd.DataFrame:
            return _fetch_sector_flow_direct(ak_type)

        df = _with_retry(label, _do, None)
        if df is None or df.empty:
            stats["errors"].append(f"{db_type}: fetch returned empty")
            stats["by_type"][db_type] = {"inserted": 0, "skipped": 0}
            continue

        rows = _df_to_intraday_rows(
            df, db_sector_type=db_type, snapshot_time=snapshot_time
        )

        type_inserted = 0
        type_skipped = 0
        for r in rows:
            existing = (
                session.query(IntradaySectorFlow)
                .filter_by(
                    snapshot_time=r["snapshot_time"],
                    sector_code=r["sector_code"],
                )
                .first()
            )
            if existing is not None:
                type_skipped += 1
                continue
            session.add(IntradaySectorFlow(**r))
            type_inserted += 1

        stats["by_type"][db_type] = {
            "inserted": type_inserted,
            "skipped": type_skipped,
        }
        stats["inserted"] += type_inserted
        stats["skipped"] += type_skipped

    session.commit()
    # P0 fix:同 data_fetcher,inserted=0 + errors 非空 → ERROR;
    # skipped 不算成功 — UniqueConstraint 命中只是幂等去重,本次没拿到新数据。
    has_errors = bool(stats["errors"])
    nothing_inserted = stats["inserted"] == 0
    if has_errors and nothing_inserted:
        logger.error(
            "fetch_and_store_intraday FAILED snapshot=%s: inserted=0, "
            "errors=%s, by_type=%s",
            stats["snapshot_time"], stats["errors"], stats["by_type"],
        )
    elif has_errors:
        logger.warning(
            "fetch_and_store_intraday partial snapshot=%s: "
            "inserted=%d errors=%s by_type=%s",
            stats["snapshot_time"], stats["inserted"], stats["errors"],
            stats["by_type"],
        )
    else:
        logger.info(
            "fetch_and_store_intraday done snapshot=%s inserted=%d "
            "skipped=%d by_type=%s",
            stats["snapshot_time"], stats["inserted"], stats["skipped"],
            stats["by_type"],
        )
    return stats

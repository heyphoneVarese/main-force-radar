"""akshare 数据采集封装。

约定:
- 每个 fetcher: try-except + 重试 3 次(失败间隔 2s)
- 返回标准化的 list[dict],金额字段已用 money.py 转 int(R1)
- 任何异常吞掉,记录日志,返回空 list(不抛给上层)
- 不做缓存(R6),不做异步,顺序跑

注意:akshare 各接口的列名/单位会随版本变化。本模块对常见列名做了 fallback,
若实际返回结构差异较大,需根据日志中 'skip ... row' 的内容定位并调整。

【2026-05-30 直连东财】 VPS 上 akshare.stock_sector_fund_flow_rank 报
RemoteDisconnected / ConnectionResetError。根因三条叠加:
  1. akshare 内部写死的 UA 是 Chrome 81(2020),东财对老 UA 直接 reset
  2. 没 Referer 头
  3. push2.eastmoney.com 收盘后 302 → push2delay.eastmoney.com,
     keep-alive 连接在阿里云 NAT 后会被东财半开 reset
本模块自己直连东财 push2 API(_fetch_sector_flow_direct),失败时再 fallback
到 akshare(双保险)。
"""

import logging
import random
import time
from datetime import date, datetime
from typing import Any, Callable, TypeVar

import akshare as ak
import pandas as pd
import requests
from sqlalchemy.orm import Session

from src.models import MarketIndexDaily, SectorFlowDaily
from src.utils.date_helper import cn_today
from src.utils.money import nav_to_int, pct_to_int, wan_yuan_to_int

logger = logging.getLogger(__name__)

T = TypeVar("T")

RETRY_TIMES: int = 3
RETRY_DELAY_SEC: float = 2.0

# =====================================================================
# 直连东财配置(绕过 akshare 老 UA / 无 Referer 的坑)
# =====================================================================
EASTMONEY_CLIST_URL = "https://push2.eastmoney.com/api/qt/clist/get"
# 现代 UA(akshare 写死的 Chrome 81 已经被东财风控)
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
EASTMONEY_REFERER = "https://data.eastmoney.com/bkzj/hy.html"
# ak_sector_type → 东财 fs 参数中的 t: 编号
_SECTOR_TYPE_T_MAP = {
    "行业资金流": "2",
    "概念资金流": "3",
    "地域资金流": "1",
}
# 直连只实现"今日"(R6 不过度设计;其他 indicator 通过 fallback 走 akshare)
_DIRECT_SUPPORTED_INDICATOR = "今日"
# 单页 100 条,够 500+ 板块拆 5-6 页
_DIRECT_PAGE_SIZE = 100
# 页间随机 sleep(秒),avoid 东财速率风控
_DIRECT_SLEEP_MIN_SEC: float = 0.4
_DIRECT_SLEEP_MAX_SEC: float = 1.2
# 单次 HTTP 超时
_DIRECT_HTTP_TIMEOUT_SEC: float = 10.0


def _with_retry(label: str, fn: Callable[[], T], fallback: T) -> T:
    """同步重试。失败 RETRY_TIMES 次后返回 fallback,不抛异常。"""
    last_err: Exception | None = None
    for attempt in range(1, RETRY_TIMES + 1):
        try:
            return fn()
        except Exception as e:
            last_err = e
            logger.warning(
                "fetch [%s] attempt %d/%d failed: %s", label, attempt, RETRY_TIMES, e
            )
            if attempt < RETRY_TIMES:
                time.sleep(RETRY_DELAY_SEC)
    logger.error(
        "fetch [%s] failed after %d attempts, returning fallback. last_err=%s",
        label,
        RETRY_TIMES,
        last_err,
    )
    return fallback


def _safe_float(value: Any) -> float | None:
    """把 akshare 字符串/数字/NaN 安全转 float,NaN 或 None 返回 None。"""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(f):
        return None
    return f


# =====================================================================
# 板块资金流(行业 / 概念)
# =====================================================================


def _direct_get_one_page(
    params: dict[str, Any], session: requests.Session
) -> dict[str, Any]:
    """直连东财抓一页。任何异常抛出去,由调用方 retry/fallback。

    单独抽出来方便 mock。返回 data_json["data"](含 total 和 diff 两个键)。
    """
    headers = {
        "User-Agent": BROWSER_UA,
        "Referer": EASTMONEY_REFERER,
        "Accept": "*/*",
        # 关键:Connection: close 避免阿里云 NAT 后 keep-alive 被东财半开 reset
        "Connection": "close",
    }
    # allow_redirects=True 处理 push2 → push2delay 的 302
    r = session.get(
        EASTMONEY_CLIST_URL,
        params=params,
        headers=headers,
        timeout=_DIRECT_HTTP_TIMEOUT_SEC,
        allow_redirects=True,
    )
    r.raise_for_status()
    body = r.json()
    if body.get("rc") != 0:
        raise RuntimeError(f"eastmoney rc={body.get('rc')} body={body}")
    data = body.get("data") or {}
    return data


def _fetch_sector_flow_direct(ak_sector_type: str) -> pd.DataFrame:
    """直连东财 push2/clist API,返回与 ak.stock_sector_fund_flow_rank('今日') 兼容的
    DataFrame(列名:名称 / 代码 / 今日涨跌幅 / 今日主力净流入-净额 / 今日主力净流入-净占比)。

    只支持 indicator="今日"(R6 不过度设计;5日/10日 走 akshare fallback)。

    多页 sleep + 单页 retry 各自管:
    - 单页失败:就地 retry 3 次(_with_retry)
    - 全部页都拿不到 → raise(让上层 fallback 到 akshare)

    ⚠️ 不在内部吞异常 — 调用方(_fetch_sector_flow)负责 fallback。
    """
    if ak_sector_type not in _SECTOR_TYPE_T_MAP:
        raise ValueError(f"unsupported sector_type: {ak_sector_type}")
    t_code = _SECTOR_TYPE_T_MAP[ak_sector_type]
    base_params: dict[str, Any] = {
        "pz": _DIRECT_PAGE_SIZE,
        "po": 1,
        "np": 1,
        "ut": "b2884a393a59ad64002292a3e90d46a5",
        "fltt": 2,
        "invt": 2,
        "fid0": "f62",          # 今日主力净流入字段(用于排序)
        "fs": f"m:90 t:{t_code}",  # m:90 = 板块市场;t:2/3/1 = 行业/概念/地域
        "stat": 1,
        # 只取真正用到的 5 个 field(减少东财负担、降低风控概率)
        # f12=代码 f14=名称 f3=今日涨跌幅% f62=主力净流入元 f184=主力净流入占比%
        "fields": "f12,f14,f3,f62,f184",
        "rt": 52975239,
    }

    session = requests.Session()
    try:
        # 第 1 页:拿 total 算总页数 + 数据
        first_params = {**base_params, "pn": 1, "_": int(time.time() * 1000)}
        first_data = _direct_get_one_page(first_params, session)
        total: int = int(first_data.get("total") or 0)
        if total <= 0:
            raise RuntimeError(f"eastmoney returned total=0 for {ak_sector_type}")

        all_rows: list[dict[str, Any]] = list(first_data.get("diff") or [])
        total_pages = (total + _DIRECT_PAGE_SIZE - 1) // _DIRECT_PAGE_SIZE

        # 2..N 页
        for page in range(2, total_pages + 1):
            # 随机 sleep,降低风控概率(本机实测 0.1s 就 OK,放宽到 0.4-1.2s 兜底)
            time.sleep(random.uniform(_DIRECT_SLEEP_MIN_SEC, _DIRECT_SLEEP_MAX_SEC))
            page_params = {**base_params, "pn": page, "_": int(time.time() * 1000)}
            try:
                page_data = _direct_get_one_page(page_params, session)
            except Exception as e:
                # 单页失败不致命:记日志后继续,丢一页可接受(R2:数据快照,缺就缺)
                logger.warning(
                    "direct sector_flow page %d/%d failed (skipping): %s: %s",
                    page, total_pages, type(e).__name__, e,
                )
                continue
            all_rows.extend(page_data.get("diff") or [])
    finally:
        session.close()

    if not all_rows:
        raise RuntimeError("eastmoney returned no rows after all pages")

    # 映射成 ak.stock_sector_fund_flow_rank 兼容列名(下游 _fetch_sector_flow 消费的 5 列)
    df = pd.DataFrame(all_rows)
    # 字段重命名:f-codes → 中文列名
    rename_map = {
        "f12": "代码",
        "f14": "名称",
        "f3": "今日涨跌幅",
        "f62": "今日主力净流入-净额",
        "f184": "今日主力净流入-净占比",
    }
    df = df.rename(columns=rename_map)
    # 东财对 "无数据" 的板块会返回 "-"(字符串),pd.to_numeric 转 NaN
    for col in ("今日涨跌幅", "今日主力净流入-净额", "今日主力净流入-净占比"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    logger.info(
        "direct fetch sector_flow ak_type=%s rows=%d (total=%d, pages=%d)",
        ak_sector_type, len(df), total, total_pages,
    )
    return df


def _fetch_sector_flow(
    indicator: str, ak_sector_type: str, db_sector_type: str
) -> list[dict[str, Any]]:
    """通用板块资金流采集。

    ak_sector_type: 传给 akshare 的板块类型(如 '行业资金流' / '概念资金流')
    db_sector_type: 入库的 enum 字符串(industry / concept / region)

    策略:indicator="今日" 时优先走直连东财(绕开 akshare 老 UA 风控);
    失败或 indicator≠"今日" 时 fallback 到 akshare。
    """
    label = f"sector_flow_{db_sector_type}_{indicator}"

    def _do_direct() -> pd.DataFrame:
        return _fetch_sector_flow_direct(ak_sector_type)

    def _do_akshare() -> pd.DataFrame:
        return ak.stock_sector_fund_flow_rank(indicator=indicator, sector_type=ak_sector_type)

    df: pd.DataFrame | None = None
    if indicator == _DIRECT_SUPPORTED_INDICATOR:
        df = _with_retry(f"{label}_direct", _do_direct, None)
        if df is None or df.empty:
            logger.warning(
                "direct fetch failed for %s, falling back to akshare", label
            )

    if df is None or df.empty:
        df = _with_retry(f"{label}_akshare", _do_akshare, None)

    if df is None or df.empty:
        return []

    today = cn_today()
    results: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        try:
            name = row.get("名称") or row.get("板块")
            if name is None:
                continue
            # 行业板块通常没"代码"列,fallback 用 name 作 code
            code = row.get("代码") or row.get("板块代码") or name

            # akshare 返回的"今日主力净流入-净额"单位是元
            main_inflow_yuan = _safe_float(row.get("今日主力净流入-净额"))
            if main_inflow_yuan is None:
                continue
            main_inflow_wan = main_inflow_yuan / 10_000  # 元 → 万元

            change_pct_raw = _safe_float(row.get("今日涨跌幅"))  # 百分比(2.34 = 2.34%)
            main_inflow_pct_raw = _safe_float(row.get("今日主力净流入-净占比"))

            results.append(
                {
                    "trade_date": today,
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
                        pct_to_int(change_pct_raw / 100) if change_pct_raw is not None else None
                    ),
                }
            )
        except Exception as e:
            logger.warning("skip %s row %s: %s", label, dict(row), e)
            continue

    logger.info("fetched %d %s rows", len(results), label)
    return results


def fetch_sector_flow_industry(indicator: str = "今日") -> list[dict[str, Any]]:
    """行业板块资金流。indicator: '今日' / '3日' / '5日' / '10日'。"""
    return _fetch_sector_flow(indicator, "行业资金流", "industry")


def fetch_sector_flow_concept(indicator: str = "今日") -> list[dict[str, Any]]:
    """概念板块资金流。indicator 同上。"""
    return _fetch_sector_flow(indicator, "概念资金流", "concept")


# =====================================================================
# 基金净值(单只)
# =====================================================================


def fetch_fund_nav(code: str) -> list[dict[str, Any]]:
    """开放式基金的最新单位净值。返回 0 或 1 行。

    注:此处只取最新一行;累计净值需另调 indicator='累计净值走势',
    本函数暂用 unit_nav 占位 accum_nav,后续可拆为两次调用合并。
    """
    label = f"fund_nav_{code}"

    def _do() -> pd.DataFrame:
        return ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势")

    df = _with_retry(label, _do, None)
    if df is None or df.empty:
        return []

    try:
        last = df.iloc[-1]
        nav_date_raw = last.get("净值日期")
        unit_nav = _safe_float(last.get("单位净值"))
        daily_growth_pct = _safe_float(last.get("日增长率"))

        if nav_date_raw is None or unit_nav is None:
            return []

        if isinstance(nav_date_raw, date):
            trade_date = nav_date_raw
        else:
            trade_date = date.fromisoformat(str(nav_date_raw))

        return [
            {
                "fund_code": code,
                "trade_date": trade_date,
                "unit_nav_x10000": nav_to_int(unit_nav),
                "accum_nav_x10000": nav_to_int(unit_nav),  # ⚠️ 占位
                "daily_return_x10000": (
                    pct_to_int(daily_growth_pct / 100) if daily_growth_pct is not None else 0
                ),
            }
        ]
    except Exception as e:
        logger.warning("skip %s row parse: %s", label, e)
        return []


# =====================================================================
# 市场指数(单只)
# =====================================================================


def fetch_market_index(code: str) -> list[dict[str, Any]]:
    """大盘指数最新一天(sina 数据源)。code 例:'sh000001'(上证)、
    'sz399001'(深成)、'sz399006'(创业板)、'sh000300'(沪深 300)。

    数据源:akshare 的 stock_zh_index_daily(sina,不走东方财富,绕开 DNS/区域问题)。
    sina 返回列:date / open / high / low / close / volume。无 amount(成交额),
    故 turnover_wan_x10000 永远 None。
    """
    label = f"market_index_{code}"

    def _do() -> pd.DataFrame:
        return ak.stock_zh_index_daily(symbol=code)

    df = _with_retry(label, _do, None)
    if df is None or df.empty:
        return []

    try:
        last = df.iloc[-1]
        trade_date_raw = last.get("date")
        close = _safe_float(last.get("close"))
        if trade_date_raw is None or close is None:
            return []

        if isinstance(trade_date_raw, date):
            trade_date = trade_date_raw
        else:
            trade_date = date.fromisoformat(str(trade_date_raw)[:10])

        # 涨跌幅:用前一日 close 计算
        change_pct = 0.0
        if len(df) >= 2:
            prev_close = _safe_float(df.iloc[-2].get("close"))
            if prev_close is not None and prev_close != 0:
                change_pct = (close - prev_close) / prev_close

        turnover_yuan = _safe_float(last.get("amount"))  # 成交额单位:元
        turnover_wan = turnover_yuan / 10_000 if turnover_yuan is not None else None

        return [
            {
                "index_code": code,
                "index_name": code,  # caller 可覆盖
                "trade_date": trade_date,
                "close_x10000": nav_to_int(close),
                "change_pct_x10000": pct_to_int(change_pct),
                "turnover_wan_x10000": (
                    wan_yuan_to_int(turnover_wan) if turnover_wan is not None else None
                ),
            }
        ]
    except Exception as e:
        logger.warning("skip %s row parse: %s", label, e)
        return []


# =====================================================================
# 基金重仓股(季报)
# =====================================================================


def fetch_fund_holdings(code: str, year: str | None = None) -> list[dict[str, Any]]:
    """基金重仓股(季报披露)。无对应入库表,返回原始 dict 列表。

    year: 4 位年份字符串,如 '2026';默认当年。
    """
    if year is None:
        year = str(cn_today().year)
    label = f"fund_holdings_{code}_{year}"

    def _do() -> pd.DataFrame:
        return ak.fund_portfolio_hold_em(symbol=code, date=year)

    df = _with_retry(label, _do, None)
    if df is None or df.empty:
        return []

    try:
        return df.to_dict("records")
    except Exception as e:
        logger.warning("skip %s parse: %s", label, e)
        return []


# =====================================================================
# 入库 helper + 定时采集编排(Phase 4.x daily_fetch job 用)
# =====================================================================

# 默认采集的 4 个市场指数(与 scripts/fetch_today.py 一致)
DEFAULT_INDICES: list[tuple[str, str]] = [
    ("sh000001", "上证指数"),
    ("sz399001", "深证成指"),
    ("sz399006", "创业板指"),
    ("sh000300", "沪深300"),
]


def insert_sector_flow_rows(session: Session, rows: list[dict[str, Any]]) -> int:
    """幂等入库:(trade_date, sector_code) 已存在则跳过。返回新插入行数。"""
    inserted = 0
    for row in rows:
        exists = (
            session.query(SectorFlowDaily)
            .filter_by(trade_date=row["trade_date"], sector_code=row["sector_code"])
            .first()
        )
        if exists:
            continue
        session.add(SectorFlowDaily(**row))
        inserted += 1
    session.commit()
    return inserted


def insert_market_index_rows(
    session: Session,
    rows: list[dict[str, Any]],
    index_name: str | None = None,
) -> int:
    """幂等入库:(index_code, trade_date) 已存在则跳过。返回新插入行数。

    index_name 非 None 时覆盖 row['index_name'](fetcher 默认用 code 占位)。
    """
    inserted = 0
    for row in rows:
        if index_name:
            row["index_name"] = index_name
        exists = (
            session.query(MarketIndexDaily)
            .filter_by(index_code=row["index_code"], trade_date=row["trade_date"])
            .first()
        )
        if exists:
            continue
        session.add(MarketIndexDaily(**row))
        inserted += 1
    session.commit()
    return inserted


def fetch_and_store_today(session: Session) -> dict[str, int]:
    """收盘后采集今日板块资金流 + 4 大指数,幂等入库。

    流程:
      1. fetch_sector_flow_industry() → sector_flow_daily(UNIQUE 去重)
      2. 4 个市场指数各自 fetch_market_index(code) → market_index_daily(UNIQUE 去重)

    任何一项 fetcher 失败时,已就位 try-except + 重试 3 次后返回空列表,
    不抛异常给上层,其他项继续执行(R2 数据快照原则 — 拿不到就算了,
    幂等可补)。

    返回:统计字典 {sectors_fetched, sectors_inserted, indices_fetched,
    indices_inserted, errors}。errors 是字符串列表,记录哪些项失败了。
    """
    stats: dict[str, Any] = {
        "sectors_fetched": 0,
        "sectors_inserted": 0,
        "indices_fetched": 0,
        "indices_inserted": 0,
        "errors": [],
    }

    # 1. 行业资金流
    try:
        sector_rows = fetch_sector_flow_industry()
        stats["sectors_fetched"] = len(sector_rows)
        if sector_rows:
            stats["sectors_inserted"] = insert_sector_flow_rows(session, sector_rows)
        else:
            # 可观测性:fetcher 内部已吞掉 retry 异常,这里没收到 sector → 一定有问题。
            # 不写 errors 的话上游 cron 完全看不出来。A 股交易日不可能 0 个板块。
            stats["errors"].append(
                "sector_flow_industry: returned 0 rows "
                "(direct + akshare fallback both failed; check container logs "
                "for 'fetch [...] failed after 3 attempts')"
            )
        logger.info(
            "fetch_and_store_today: sector_flow_industry fetched=%d inserted=%d",
            stats["sectors_fetched"], stats["sectors_inserted"],
        )
    except Exception as e:
        msg = f"sector_flow_industry: {type(e).__name__}: {e}"
        logger.error("fetch_and_store_today: %s", msg)
        stats["errors"].append(msg)

    # 2. 4 大市场指数
    for code, name in DEFAULT_INDICES:
        try:
            index_rows = fetch_market_index(code)
            stats["indices_fetched"] += len(index_rows)
            if index_rows:
                stats["indices_inserted"] += insert_market_index_rows(
                    session, index_rows, index_name=name
                )
            else:
                # 同 sectors:fetcher 静默返空也要让上游看见
                stats["errors"].append(
                    f"market_index[{code}/{name}]: returned 0 rows (retries exhausted)"
                )
        except Exception as e:
            msg = f"market_index[{code}/{name}]: {type(e).__name__}: {e}"
            logger.error("fetch_and_store_today: %s", msg)
            stats["errors"].append(msg)

    # P0 fix:静默失败必须升级为 ERROR,否则上游"job executed successfully"
    # 会把数据丢失伪装成正常。inserted=0 + errors 非空 → ERROR;
    # 部分成功也用 WARNING 提示 partial。
    has_errors = bool(stats["errors"])
    nothing_inserted = (
        stats["sectors_inserted"] == 0 and stats["indices_inserted"] == 0
    )
    if has_errors and nothing_inserted:
        logger.error(
            "fetch_and_store_today FAILED: inserted=0, errors=%s, full=%s",
            stats["errors"], stats,
        )
    elif has_errors:
        logger.warning(
            "fetch_and_store_today partial: errors=%s, full=%s",
            stats["errors"], stats,
        )
    else:
        logger.info("fetch_and_store_today done: %s", stats)
    return stats

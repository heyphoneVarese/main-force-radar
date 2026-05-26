"""为 Phase 2.7 信号引擎测试生成 30 个交易日的 sector_flow_daily 数据。

用法(在 backend/ 目录下):
    uv run python -m scripts.mock_sector_flow

策略:
- 覆盖 sector_aliases 表里所有 sector_code 不为 NULL 的板块(23 个)
- 30 个交易日(跳过周末)
- 故意为 4 个板块嵌入"剧本":
    bullish_strong  : 半导体 BK0490        — 最近 4 天大额流入,价升
    bearish_strong  : 5G概念 BK0727        — 最近 4 天大额流出,价跌
    warning         : 人工智能 BK1019      — 价升但持续流出(背离)
    bullish_normal  : 光模块 BK1144        — 最近 3 天中等流入
- 其余 19 个板块 = 随机噪声(主力 ±50 亿,涨跌 ±2%)

幂等:运行前先 DELETE 我们涉及的 sector_code 的所有行,再插入。
"""

import logging
import random
from datetime import date, timedelta

from sqlalchemy import select

from src.db import SessionLocal
from src.models import SectorAlias, SectorFlowDaily
from src.utils.date_helper import cn_today
from src.utils.money import pct_to_int, wan_yuan_to_int

logger = logging.getLogger(__name__)

DAYS = 30  # 交易日数
SEED = 42  # 固定随机种子,跑出来可复现

# (sector_code, scenario)
SCENARIOS: dict[str, str] = {
    "BK0490": "bullish_strong",   # 半导体
    "BK0727": "bearish_strong",   # 5G概念
    "BK1019": "warning",          # 人工智能
    "BK1144": "bullish_normal",   # 光模块
    # 其他都按 "neutral"
}


def trade_days(end: date, n: int) -> list[date]:
    """返回 end 之前(含)的 n 个交易日,按时间升序(老→新)。"""
    out: list[date] = []
    cur = end
    while len(out) < n:
        if cur.weekday() < 5:
            out.append(cur)
        cur -= timedelta(days=1)
    return list(reversed(out))


def _gen_row(scenario: str, days_from_today: int, rng: random.Random) -> tuple[float, float]:
    """返回 (main_inflow_yi, change_pct_decimal)。
    main_inflow_yi 单位亿元(正数=流入,负数=流出)。
    change_pct_decimal 是小数(0.012 = +1.2%)。
    days_from_today: 0 = 最近一天, 29 = 30 天前。
    """
    if scenario == "bullish_strong":
        if days_from_today <= 3:
            # 4 天连续大流入,递增
            base = 80 + (3 - days_from_today) * 5  # 80, 85, 90, 95
            return float(base), 0.012 + (3 - days_from_today) * 0.003
        return rng.uniform(-30, 30), rng.uniform(-0.01, 0.01)

    if scenario == "bearish_strong":
        if days_from_today <= 3:
            # 4 天连续大流出,绝对值递增
            base = -120 - (3 - days_from_today) * 10  # -120, -130, -140, -150
            return float(base), -0.015 - (3 - days_from_today) * 0.005
        return rng.uniform(-30, 30), rng.uniform(-0.01, 0.01)

    if scenario == "warning":
        if days_from_today <= 4:
            # 价升但主力净流出 → 背离,5 天持续
            return -40.0 + days_from_today * 3, 0.014
        return rng.uniform(-20, 20), rng.uniform(-0.01, 0.01)

    if scenario == "bullish_normal":
        if days_from_today <= 2:
            # 3 天中等流入(20-30 亿),持续性 = 2,基础 1-2
            base = 25 + (2 - days_from_today) * 3
            return float(base), 0.008 + (2 - days_from_today) * 0.002
        return rng.uniform(-20, 20), rng.uniform(-0.01, 0.01)

    # neutral / unknown
    return rng.uniform(-40, 40), rng.uniform(-0.02, 0.02)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    rng = random.Random(SEED)

    today = cn_today()
    days = trade_days(today, DAYS)

    with SessionLocal() as session:
        # 收集 23 个 mapped 板块
        aliases = session.scalars(
            select(SectorAlias).where(SectorAlias.sector_code.is_not(None))
        ).all()
        # 去重(多个 label 可能映射到同一 sector_code)
        seen_codes: set[str] = set()
        sectors: list[tuple[str, str]] = []
        for a in aliases:
            if a.sector_code in seen_codes:
                continue
            seen_codes.add(a.sector_code)
            sectors.append((a.sector_code, a.sector_name or a.sector_code))

        logger.info("将为 %d 个板块 × %d 个交易日 = %d 行生成 mock 数据",
                    len(sectors), len(days), len(sectors) * len(days))

        # 幂等:删旧
        codes = [c for c, _ in sectors]
        deleted = session.query(SectorFlowDaily).filter(
            SectorFlowDaily.sector_code.in_(codes)
        ).delete(synchronize_session=False)
        session.commit()
        logger.info("已清理旧 mock: %d 行", deleted)

        # 插新
        inserted = 0
        for code, name in sectors:
            scenario = SCENARIOS.get(code, "neutral")
            # days 是老→新,最新一天 days_from_today=0
            for i, d in enumerate(days):
                days_from_today = len(days) - 1 - i
                inflow_yi, change_pct = _gen_row(scenario, days_from_today, rng)
                # 亿元 → 万元
                inflow_wan = inflow_yi * 10_000
                session.add(SectorFlowDaily(
                    trade_date=d,
                    sector_code=code,
                    sector_name=name,
                    sector_type="industry",
                    main_inflow_wan_x10000=wan_yuan_to_int(inflow_wan),
                    main_inflow_pct_x10000=None,
                    change_pct_x10000=pct_to_int(change_pct),
                ))
                inserted += 1
        session.commit()
        logger.info("mock 数据写入完成: %d 行", inserted)

    # 简短样例:打印最近 3 天 × 4 个剧本板块
    with SessionLocal() as session:
        print("\n样例(最近 3 个交易日 × 4 个剧本板块):")
        print("-" * 80)
        for code in ["BK0490", "BK0727", "BK1019", "BK1144"]:
            rows = session.scalars(
                select(SectorFlowDaily)
                .where(SectorFlowDaily.sector_code == code)
                .order_by(SectorFlowDaily.trade_date.desc())
                .limit(3)
            ).all()
            for r in rows:
                inflow_yi = r.main_inflow_wan_x10000 / 10_000 / 10_000
                pct = (r.change_pct_x10000 or 0) / 100
                print(f"  {r.trade_date} {code} {r.sector_name:<10} "
                      f"主力 {inflow_yi:+.1f}亿  涨跌 {pct:+.2f}%")
            print()


if __name__ == "__main__":
    main()

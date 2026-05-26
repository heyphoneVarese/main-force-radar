"""信号引擎 — Phase 2.7

输入:sector_flow_daily(每日板块资金流) + funds.related_sectors + sector_aliases
输出:sector 级 Signal(写入 signals 表)+ fund 级摘要(service 层聚合)

持续性评分 0-9(D3 决策:跳过板块联动维度,从原 0-10 调整):
- 基础分 (0-4): 当日主力净流入绝对值
    < 10亿:0, 10-30亿:1, 30-50亿:2, 50-100亿:3, > 100亿:4
- 连续性 (0-3): 同向(均流入或均流出)连续天数
    1天:0, 2天:1, 3天:2, ≥4天:3
- 量价匹配 (0-2): 用 main_inflow 绝对值代理"量"(D2)
    齐升/齐跌 (符号同 + |今|>|昨|):2
    背离 (符号相反):1
    其他 (量缩同向 或 价为 0):0

信号类型(D4 决策:缺口填 bearish):
- score ≥ 8 + 流入 → bullish (强)
- score 6-7 + 流入 → bullish (普通)
- score ≥ 8 + 流出 → bearish (强退潮)
- score 6-7 + 流出 → bearish (普通,gap-fill)
- score < 6  + 流出 → bearish (普通退潮)
- score < 6  + 流入 → neutral (流入不强,不算多)
- 4-7 + 背离 → warning(分歧;优先级高于以上 bullish/bearish)
- 其他 → neutral

R3.1: 所有信号词均为情绪/状态描述,绝无 buy/sell/long/short/hold。
"""

import logging
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import Fund, Holding, SectorAlias, SectorFlowDaily, Signal
from src.models.enums import SignalType
from src.services.sector_mapping import get_sectors_for_fund
from src.utils.date_helper import cn_now, cn_today

logger = logging.getLogger(__name__)

# 万元 × 10000 单位的阈值
# 10 亿元 = 100_000 万元 × 10000 = 1_000_000_000
_TIER_10YI = 1_000_000_000
_TIER_30YI = 3_000_000_000
_TIER_50YI = 5_000_000_000
_TIER_100YI = 10_000_000_000

LOOKBACK_DAYS = 10  # 取最近 N 个交易日做连续性判断


@dataclass
class ScoreBreakdown:
    base: int
    continuity: int
    vol_price: int
    vol_price_label: str  # "align" | "divergence" | "other" | "no_prior"
    total: int
    main_inflow_wan_x10000: int
    trade_date: date | None


class SignalEngine:
    def __init__(self, session: Session):
        self.session = session

    # ============ 评分子维度 ============

    @staticmethod
    def _base_score(abs_inflow_wan_x10000: int) -> int:
        if abs_inflow_wan_x10000 > _TIER_100YI:
            return 4
        if abs_inflow_wan_x10000 >= _TIER_50YI:
            return 3
        if abs_inflow_wan_x10000 >= _TIER_30YI:
            return 2
        if abs_inflow_wan_x10000 >= _TIER_10YI:
            return 1
        return 0

    @staticmethod
    def _continuity_score(flows_desc: list[int]) -> int:
        """flows_desc: 按日期降序排列(今日在前)。
        统计今日起同号(都正或都负)的连续天数。"""
        if not flows_desc:
            return 0
        sign = lambda x: 1 if x > 0 else (-1 if x < 0 else 0)
        s0 = sign(flows_desc[0])
        if s0 == 0:
            return 0
        consec = 1
        for f in flows_desc[1:]:
            if sign(f) == s0:
                consec += 1
            else:
                break
        if consec >= 4:
            return 3
        if consec == 3:
            return 2
        if consec == 2:
            return 1
        return 0

    @staticmethod
    def _vol_price_score(today_flow: int, yest_flow: int, today_change_pct_x10000: int) -> tuple[int, str]:
        """D2: 用 main_inflow 绝对值代理"量"。返回 (score, label)。"""
        sign = lambda x: 1 if x > 0 else (-1 if x < 0 else 0)
        fs, ps = sign(today_flow), sign(today_change_pct_x10000)
        if fs == 0 or ps == 0:
            return 0, "other"
        if fs != ps:
            return 1, "divergence"
        # 同号 → 看量是否扩张
        if abs(today_flow) > abs(yest_flow):
            return 2, "align"
        return 0, "other"  # 量缩或量平,即"量缩同向"

    # ============ 顶层算分 ============

    def calculate_persistence_score(
        self, sector_code: str, as_of: date | None = None
    ) -> ScoreBreakdown:
        as_of = as_of or cn_today()
        rows = self.session.scalars(
            select(SectorFlowDaily)
            .where(SectorFlowDaily.sector_code == sector_code)
            .where(SectorFlowDaily.trade_date <= as_of)
            .order_by(SectorFlowDaily.trade_date.desc())
            .limit(LOOKBACK_DAYS)
        ).all()

        if not rows:
            return ScoreBreakdown(
                base=0, continuity=0, vol_price=0, vol_price_label="no_data",
                total=0, main_inflow_wan_x10000=0, trade_date=None,
            )

        today_row = rows[0]
        today_flow = today_row.main_inflow_wan_x10000
        flows = [r.main_inflow_wan_x10000 for r in rows]

        base = self._base_score(abs(today_flow))
        cont = self._continuity_score(flows)
        if len(rows) >= 2:
            vp, vp_label = self._vol_price_score(
                today_flow,
                rows[1].main_inflow_wan_x10000,
                today_row.change_pct_x10000 or 0,
            )
        else:
            vp, vp_label = 0, "no_prior"

        return ScoreBreakdown(
            base=base, continuity=cont, vol_price=vp, vol_price_label=vp_label,
            total=base + cont + vp,
            main_inflow_wan_x10000=today_flow,
            trade_date=today_row.trade_date,
        )

    @staticmethod
    def determine_signal_type(score: int, is_inflow: bool, vp_label: str) -> str:
        """D4: 6-7 + 流出 → bearish(填 gap);流出任意分数 → bearish;
        流入需 ≥ 6 才 bullish;背离 + 4-7 → warning(优先)。"""
        if vp_label == "divergence" and 4 <= score <= 7:
            return SignalType.WARNING.value
        if not is_inflow:
            # 任何流出 → bearish(spec 字面 + gap-fill)
            return SignalType.BEARISH.value
        # 流入
        if score >= 6:
            return SignalType.BULLISH.value
        return SignalType.NEUTRAL.value

    # ============ 构建 Signal 对象 ============

    def calculate_sector_signal(
        self, sector_code: str, sector_name: str = "", as_of: date | None = None
    ) -> Signal | None:
        sb = self.calculate_persistence_score(sector_code, as_of)
        if sb.trade_date is None:
            return None
        is_inflow = sb.main_inflow_wan_x10000 > 0
        signal_type = self.determine_signal_type(sb.total, is_inflow, sb.vol_price_label)
        return Signal(
            trade_date=sb.trade_date,
            signal_type=signal_type,
            target_type="sector",
            target_code=sector_code,
            signal_name=f"{sector_name or sector_code} {signal_type}",
            description=self._describe(sector_name or sector_code, sb, signal_type),
            score_x100=sb.total * 100,  # 0-900,即百分制(R1 兼容)
            persistence_score=sb.total,
            main_inflow_wan_x10000=sb.main_inflow_wan_x10000,
            triggered_at=cn_now(),
            meta={
                "base": sb.base,
                "continuity": sb.continuity,
                "vol_price": sb.vol_price,
                "vol_price_label": sb.vol_price_label,
                "is_inflow": is_inflow,
            },
        )

    @staticmethod
    def _describe(label: str, sb: ScoreBreakdown, signal_type: str) -> str:
        flow_yi = sb.main_inflow_wan_x10000 / 10_000 / 10_000
        direction = "净流入" if flow_yi > 0 else ("净流出" if flow_yi < 0 else "持平")
        return (
            f"{label}: 持续性 {sb.total}/9 (基础 {sb.base}/4 + "
            f"连续 {sb.continuity}/3 + 量价 {sb.vol_price}/2 {sb.vol_price_label}); "
            f"主力{direction} {abs(flow_yi):.1f} 亿; 信号 {signal_type}"
        )

    # ============ 批量:为所有持仓涉及的 sector 生成信号 ============

    def generate_signals_for_holdings(self, as_of: date | None = None) -> list[Signal]:
        """收集所有持仓涉及的 mapped sectors(去重),每个 sector 算一条信号。"""
        holdings = self.session.scalars(select(Holding)).all()
        sector_codes: set[str] = set()
        for h in holdings:
            for code in get_sectors_for_fund(self.session, h.fund_code):
                sector_codes.add(code)

        # 取 sector 名(任意一条 alias 即可)
        name_map: dict[str, str] = {}
        for code in sector_codes:
            alias = self.session.scalar(
                select(SectorAlias).where(SectorAlias.sector_code == code).limit(1)
            )
            name_map[code] = alias.sector_name if alias and alias.sector_name else code

        signals: list[Signal] = []
        for code in sorted(sector_codes):
            sig = self.calculate_sector_signal(code, name_map.get(code, code), as_of)
            if sig is not None:
                signals.append(sig)
        return signals

    def save_signals(self, signals: list[Signal]) -> int:
        """Upsert: (target_type, target_code, trade_date) 相同则覆盖。"""
        saved = 0
        for sig in signals:
            existing = self.session.scalar(
                select(Signal).where(
                    Signal.target_type == sig.target_type,
                    Signal.target_code == sig.target_code,
                    Signal.trade_date == sig.trade_date,
                )
            )
            if existing:
                existing.signal_type = sig.signal_type
                existing.signal_name = sig.signal_name
                existing.description = sig.description
                existing.score_x100 = sig.score_x100
                existing.persistence_score = sig.persistence_score
                existing.main_inflow_wan_x10000 = sig.main_inflow_wan_x10000
                existing.triggered_at = sig.triggered_at
                existing.meta = sig.meta
            else:
                self.session.add(sig)
            saved += 1
        self.session.commit()
        return saved

    # ============ 每只基金的信号摘要(取其 mapped sector 中最强的) ============

    def get_fund_signal_summary(
        self, fund_code: str, as_of: date | None = None
    ) -> dict:
        fund = self.session.get(Fund, fund_code)
        sectors = get_sectors_for_fund(self.session, fund_code) if fund else []
        if not sectors:
            return {
                "fund_code": fund_code,
                "fund_name": fund.fund_name if fund else None,
                "signal_type": SignalType.NOT_APPLICABLE.value,
                "score": 0,
                "via_sector": None,
                "all_sectors": [],
                "reason": "未映射到 A 股行业板块(QDII / 指数 / 债基)",
            }

        per_sector = []
        for code in sectors:
            sig = self.session.scalar(
                select(Signal)
                .where(Signal.target_type == "sector")
                .where(Signal.target_code == code)
                .order_by(Signal.trade_date.desc())
                .limit(1)
            )
            if sig is None:
                continue
            per_sector.append(
                {
                    "sector_code": code,
                    "signal_type": sig.signal_type,
                    "score": sig.persistence_score or 0,
                }
            )

        if not per_sector:
            return {
                "fund_code": fund_code,
                "fund_name": fund.fund_name if fund else None,
                "signal_type": SignalType.NEUTRAL.value,
                "score": 0,
                "via_sector": None,
                "all_sectors": [],
                "reason": "sector 已映射但无 sector_flow 数据,请先采集",
            }
        strongest = max(per_sector, key=lambda x: x["score"])
        return {
            "fund_code": fund_code,
            "fund_name": fund.fund_name if fund else None,
            "signal_type": strongest["signal_type"],
            "score": strongest["score"],
            "via_sector": strongest["sector_code"],
            "all_sectors": per_sector,
            "reason": f"取 {len(per_sector)} 个 mapped sectors 中持续性最强 (score={strongest['score']})",
        }

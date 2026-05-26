"""端到端跑 Phase 2.7 信号引擎,产出"基金 → 信号"汇总。

流程:
  1. 灌 mock sector_flow 数据(如已存在则覆盖)
  2. 跑 SignalEngine.generate_signals_for_holdings + save
  3. 对 52 只持仓逐一打印信号摘要
  4. 打印总览(各 signal_type 计数)

用法(在 backend/ 目录下):
    uv run python -m scripts.run_signal_engine
"""

import logging
from collections import Counter

from sqlalchemy import select

from src.db import SessionLocal
from src.models import Fund, Holding
from src.services.signal_engine import SignalEngine

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    # 先灌 mock 数据(import 而不是 subprocess)
    from scripts.mock_sector_flow import main as mock_main
    print("\n========== Step 1: 灌 mock sector_flow ==========")
    mock_main()

    print("\n========== Step 2: 跑信号引擎 ==========")
    with SessionLocal() as session:
        engine = SignalEngine(session)
        signals = engine.generate_signals_for_holdings()
        saved = engine.save_signals(signals)
        print(f"\n生成并入库 {saved} 条 sector 级信号:\n")
        for s in sorted(signals, key=lambda x: -(x.persistence_score or 0))[:8]:
            print(f"  {s.signal_type:<10} score={s.persistence_score}/9  "
                  f"{s.target_code}  {s.description}")
        if len(signals) > 8:
            print(f"  ... 还有 {len(signals) - 8} 条 score 较低的省略")

    print("\n========== Step 3: 每只基金的信号摘要(52 只)==========\n")
    with SessionLocal() as session:
        engine = SignalEngine(session)
        holdings = session.scalars(select(Holding).order_by(Holding.fund_code)).all()
        type_count: Counter = Counter()

        # 按 signal_type 分组打印
        grouped: dict[str, list[dict]] = {}
        for h in holdings:
            fund = session.get(Fund, h.fund_code)
            summary = engine.get_fund_signal_summary(h.fund_code)
            summary["_fund_name"] = fund.fund_name if fund else h.fund_code
            type_count[summary["signal_type"]] += 1
            grouped.setdefault(summary["signal_type"], []).append(summary)

        # 排序输出
        order = ["bullish", "bearish", "warning", "neutral", "not_applicable"]
        for stype in order:
            items = grouped.get(stype, [])
            if not items:
                continue
            print(f"== {stype} ({len(items)}) ==")
            for s in sorted(items, key=lambda x: -x["score"]):
                via = f" via {s['via_sector']}" if s.get("via_sector") else ""
                print(f"  [{s['fund_code']}] {s['_fund_name']:<32}  "
                      f"score={s['score']}/9{via}")
            print()

    print("========== 总览 ==========")
    print(f"  bullish:        {type_count.get('bullish', 0)}")
    print(f"  bearish:        {type_count.get('bearish', 0)}")
    print(f"  warning:        {type_count.get('warning', 0)}")
    print(f"  neutral:        {type_count.get('neutral', 0)}")
    print(f"  not_applicable: {type_count.get('not_applicable', 0)}  (QDII/指数/债基)")
    print(f"  total:          {sum(type_count.values())}")


if __name__ == "__main__":
    main()

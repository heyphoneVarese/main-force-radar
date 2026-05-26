"""端到端测试 Server酱 推送 (Phase 3.8)。

流程:
  1. 跑 SignalEngine 拿当日信号 (默认从 signals 表读 latest, 没有就现算)
  2. 构建 holdings_by_sector 映射(同 fund_code 横跨持仓 + sector)
  3. 渲染 markdown 预览(终端先看一眼)
  4. 如果 .env 配置了 SERVER_CHAN_SCKEY,实际推送;否则只打印不发

用法(在 backend/ 目录下):
    uv run python -m scripts.test_push
"""

import logging

from sqlalchemy import select

from src.config import settings
from src.db import SessionLocal
from src.models import Fund, Holding
from src.services.notifier import ServerChanNotifier
from src.services.sector_mapping import get_sectors_for_fund
from src.services.signal_engine import SignalEngine

logger = logging.getLogger(__name__)


def build_holdings_by_sector(session) -> dict[str, list[tuple[str, str]]]:
    """sector_code → [(fund_code, fund_name), ...]"""
    out: dict[str, list[tuple[str, str]]] = {}
    holdings = session.scalars(select(Holding)).all()
    for h in holdings:
        fund = session.get(Fund, h.fund_code)
        if fund is None:
            continue
        for sector_code in get_sectors_for_fund(session, h.fund_code):
            out.setdefault(sector_code, []).append((h.fund_code, fund.fund_name))
    return out


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    with SessionLocal() as session:
        engine = SignalEngine(session)
        signals = engine.generate_signals_for_holdings()
        if not signals:
            print("⚠️  signals 为空(可能 sector_flow_daily 没数据,先跑 scripts/mock_sector_flow 或 fetch_today)")
        # 入库一份,顺手做持久化
        engine.save_signals(signals)

        holdings_by_sector = build_holdings_by_sector(session)

    title, content = ServerChanNotifier.build_summary_markdown(signals, holdings_by_sector)

    print()
    print("=" * 72)
    print(f"标题: {title}")
    print("=" * 72)
    print(content)
    print("=" * 72)
    print()

    if not settings.server_chan_sckey:
        print("⚠️  SERVER_CHAN_SCKEY 未配置,只打印预览不发送")
        print("    要发送:在 .env 加  SERVER_CHAN_SCKEY=你的 SCKEY")
        return

    notifier = ServerChanNotifier(settings.server_chan_sckey)
    ok = notifier.send(title, content)
    print("✅ 推送成功,微信应收到一条" if ok else "❌ 推送失败,看上方日志")


if __name__ == "__main__":
    main()

"""端到端测试 Server酱 推送 + (Phase 3.10) 可选 AI 分析师 (Phase 3.8 + 3.10)。

流程:
  1. 跑 SignalEngine 拿当日信号,save 入库
  2. 构建 holdings_by_sector 映射
  3. 如果 ANTHROPIC_API_KEY 配置了 → 跑 AI 分析(否则跳过,只发数据)
  4. 渲染 markdown 预览到终端
  5. 如果 SERVER_CHAN_SCKEY 配置了 → 实际推送;否则只打印不发

用法(在 backend/ 目录下):
    uv run python -m scripts.test_push
"""

import logging

from src.config import settings
from src.db import SessionLocal
from src.services.ai_analyst import AIAnalyst
from src.services.holdings_summary import build_holdings_by_sector
from src.services.notifier import ServerChanNotifier
from src.services.signal_engine import SignalEngine

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    # 1-2. 信号 + 持仓映射
    with SessionLocal() as session:
        engine = SignalEngine(session)
        signals = engine.generate_signals_for_holdings()
        if not signals:
            print("⚠️  signals 为空(先跑 scripts/mock_sector_flow 或 fetch_today)")
        engine.save_signals(signals)
        holdings_by_sector = build_holdings_by_sector(session)

    # 3. AI 分析(可选)
    ai_analysis = ""
    if settings.anthropic_api_key:
        print("\n💬 ANTHROPIC_API_KEY 已配置,调用 AI 分析师...")
        analyst = AIAnalyst(api_key=settings.anthropic_api_key)
        ai_analysis = analyst.analyze_signals(signals, holdings_by_sector)
        if ai_analysis:
            print(f"   生成 {len(ai_analysis)} 字符的分析")
        else:
            print("   ⚠️ AI 返回空(看上方日志,可能 API 调用失败)")
    else:
        print("\nℹ️  ANTHROPIC_API_KEY 未配置,跳过 AI 段,只发数据(向后兼容)")

    # 4. 渲染预览
    title, content = ServerChanNotifier.build_summary_markdown(
        signals, holdings_by_sector, ai_analysis=ai_analysis
    )
    print()
    print("=" * 72)
    print(f"标题: {title}")
    print("=" * 72)
    print(content)
    print("=" * 72)
    print()

    # 5. 推送
    if not settings.server_chan_sckey:
        print("⚠️  SERVER_CHAN_SCKEY 未配置,只打印预览不发送")
        return

    notifier = ServerChanNotifier(settings.server_chan_sckey)
    ok = notifier.send(title, content)
    print("✅ 推送成功,微信应收到一条" if ok else "❌ 推送失败,看上方日志")


if __name__ == "__main__":
    main()

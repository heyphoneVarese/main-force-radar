"""Claude API 驱动的 AI 分析师 — Phase 3.10

输入:sector 级 Signal 列表 + 持仓映射 + 可选宏观背景
输出:300-500 字中文 Markdown 分析,作为 Server酱 推送的「AI 分析师视角」段

R3.1 守门:
- SYSTEM_PROMPT 明确禁用 buy/sell/hold/long/short 等操作指令词
- 返回后扫描禁用词:命中只 logger.warning(不阻断、不替换 —— 你最终把关)

任何异常吞掉,返回 "" 让上层(notifier)决定要不要插入 AI 段。
"""

import logging
from typing import TYPE_CHECKING

import anthropic

from src.models.enums import SignalType
from src.utils.date_helper import cn_today

if TYPE_CHECKING:
    from src.models import Signal

logger = logging.getLogger(__name__)


# R3.1 红线词汇 — 命中会 log warning 但不阻断输出
# 中英都列,LLM 偶尔会切英文
# 注意:中文「持有」已移除 —— 误报率高(状态描述 "你持有的 XXX 基金" ≠ 操作指令 "建议持有")。
# SYSTEM_PROMPT 里仍约束「不要给操作建议」,语义边界由 prompt 守门。
# 英文 "hold" 保留 —— 英文语境下更明确是操作动词。
_FORBIDDEN_WORDS: list[str] = [
    "买入", "卖出", "做多", "做空",
    "止损", "止盈", "建仓", "减仓", "加仓",
    "buy", "sell", "long", "short", "hold",
]


SYSTEM_PROMPT = """你是一位专业的中国 A 股板块资金流分析师。

任务:基于今天的板块信号数据 + 用户持仓,写一段 300-500 字的中文分析报告,
将作为 Server酱 微信推送中的「AI 分析师视角」段落呈现给用户。

==== 严格规则 ====

1. 禁用词汇(R3.1 红线,严禁出现):
   ❌ 买入 / 卖出 / 做多 / 做空 / 止损 / 止盈 / 建仓 / 减仓 / 加仓
   ✅ 可以用:看多 / 看空 / 警惕 / 关注 / 留意 / 观察 / 跟踪
   ✅ 描述用户现有持仓时,可以说"你持有的 XXX"(状态描述),
      但禁止"建议持有 / 应该持有 / 可以持有"(操作指令)

2. 不给操作建议:
   ❌ 不要写 "建议 XX"、"应该 XX"、"可以 XX 操作"
   ✅ 只描述"市场在发生什么" + "对组合的影响"
   ✅ 末尾固定一句:工具只给信号,操作你定。

3. 结构(必须严格按段顺序,段间空一行):
   段 1:今日主线判断(1-2 句,定调)
   段 2:用户持仓中受影响的板块(指明基金代码 + 名字)
   段 3:风险点(警告类信号 / 退潮信号)
   段 4:宏观背景对照(仅当用户提供 macro_context 时输出;否则省略此段)

4. 语气:
   像专业研究员对老客户说话,
   不夸张、不预测具体涨跌幅,
   多用 "可能 / 大概率 / 值得留意 / 需要观察 / 跟踪" 等措辞。

5. 字数控制:300-500 字之间,严格执行。

6. 输出格式:纯 Markdown 文本(允许 **粗体**、## 小标题、列表),
   不要包裹在 ```markdown``` 代码块里。
"""


class AIAnalyst:
    def __init__(
        self,
        api_key: str,
        model: str = "claude-sonnet-4-5",
        max_tokens: int = 800,
        temperature: float = 0.3,
    ):
        self.api_key = api_key
        self.model = model
        self.max_tokens = max_tokens
        self.temperature = temperature
        # 懒初始化 — api_key 为空时 client 一直是 None,analyze 直接返回 ""
        self._client: anthropic.Anthropic | None = None

    @property
    def client(self) -> anthropic.Anthropic | None:
        if not self.api_key:
            return None
        if self._client is None:
            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    # ============ 主入口 ============

    def analyze_signals(
        self,
        signals: "list[Signal]",
        holdings_by_sector: dict[str, list[tuple[str, str]]] | None = None,
        macro_context: str | None = None,
    ) -> str:
        """生成 300-500 字 markdown 分析。失败/无 key → 返回 ""。"""
        if self.client is None:
            logger.info("AIAnalyst: ANTHROPIC_API_KEY 未配置,跳过 AI 分析")
            return ""

        user_prompt = self._build_user_prompt(
            signals, holdings_by_sector or {}, macro_context
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except anthropic.APIError as e:
            logger.error("AIAnalyst: Anthropic API 错误 %s: %s", type(e).__name__, e)
            return ""
        except Exception as e:
            logger.error("AIAnalyst: 未预期异常 %s: %s", type(e).__name__, e)
            return ""

        # 抽取所有 text block 拼起来
        text_parts: list[str] = []
        for block in response.content:
            if getattr(block, "type", None) == "text":
                text_parts.append(block.text)
        if not text_parts:
            logger.warning("AIAnalyst: 响应里没有 text block")
            return ""
        text = "\n".join(text_parts).strip()

        # R3.1 词汇扫描:命中只告警,不阻断
        hits = self.check_forbidden_words(text)
        if hits:
            logger.warning(
                "AIAnalyst: R3.1 禁用词命中 %s — 输出原样返回,人工把关",
                hits,
            )

        # 记录 usage(便于估成本)
        try:
            u = response.usage
            logger.info(
                "AIAnalyst: tokens input=%d output=%d (model=%s)",
                u.input_tokens, u.output_tokens, self.model,
            )
        except Exception:
            pass

        return text

    # ============ R3.1 词汇扫描 ============

    @staticmethod
    def check_forbidden_words(text: str) -> list[str]:
        """返回文本中命中的禁用词列表(去重 + 排序)。"""
        text_lower = text.lower()
        found: set[str] = set()
        for word in _FORBIDDEN_WORDS:
            if word.lower() in text_lower:
                found.add(word)
        return sorted(found)

    # ============ user prompt 构造 ============

    @staticmethod
    def _build_user_prompt(
        signals: "list[Signal]",
        holdings_by_sector: dict[str, list[tuple[str, str]]],
        macro_context: str | None,
    ) -> str:
        today = cn_today()
        actionable = {
            SignalType.BULLISH.value,
            SignalType.BEARISH.value,
            SignalType.WARNING.value,
        }

        sig_lines: list[str] = []
        for s in sorted(signals, key=lambda x: -(x.persistence_score or 0)):
            if s.signal_type not in actionable:
                continue
            flow_yi = (s.main_inflow_wan_x10000 or 0) / 10_000 / 10_000
            direction = "净流入" if flow_yi > 0 else "净流出"
            funds = holdings_by_sector.get(s.target_code or "", [])
            fund_str = ""
            if funds:
                names = " / ".join(f"[{c}]{n}" for c, n in funds[:4])
                if len(funds) > 4:
                    names += f" 等 {len(funds)} 只"
                fund_str = f" — 用户持仓 {len(funds)} 只: {names}"
            sector_name = (s.signal_name or "").split(" ")[0] or s.target_code or "?"
            sig_lines.append(
                f"- {sector_name} ({s.target_code}) "
                f"{s.signal_type} score {s.persistence_score}/9 "
                f"主力{direction} {abs(flow_yi):.1f} 亿{fund_str}"
            )
        signals_md = "\n".join(sig_lines) if sig_lines else "(今日无 actionable 信号)"

        # 持仓概况
        total_funds = sum(len(funds) for funds in holdings_by_sector.values())
        if holdings_by_sector:
            portfolio = (
                f"覆盖 {len(holdings_by_sector)} 个 A 股行业板块,"
                f"共 {total_funds} 只基金持仓暴露"
            )
        else:
            portfolio = "用户当前无 A 股行业板块持仓暴露"

        macro_part = ""
        if macro_context:
            macro_part = f"\n==== 宏观背景 ====\n{macro_context}\n"

        return f"""日期:{today.isoformat()}

==== 今日板块信号(已过滤,只保留 actionable)====
{signals_md}

==== 用户持仓概况 ====
{portfolio}
{macro_part}
==== 任务 ====
请严格按 4 段结构(主线 / 受影响板块 / 风险 / 宏观)写一段 300-500 字中文 markdown 分析。
严禁出现"买入/卖出/持有/做多/做空/止损/止盈/建仓/减仓/加仓"等操作指令词汇。
末尾固定一句:工具只给信号,操作你定。
"""

"""Claude API 驱动的 AI 分析师。

Phase 3.10:接入 Claude API,300-500 字推送分析。
Phase 3.9:按 push_type 派发到 4 个差异化模板
          (src/prompts/{pre_market, intraday, close, weekly}.py)

R3.1 守门:
- 每个 prompts 模块的 SYSTEM_PROMPT 都拼了 _common.BASE_RULES(含红线词清单)
- 返回后扫描禁用词:命中 logger.warning(不阻断、不替换 — 人工把关)

任何异常吞掉,返回 "" 让上层(notifier)决定要不要插入 AI 段。
"""

import logging
from typing import TYPE_CHECKING

import anthropic

from src.models.enums import PushType
from src.prompts import close, intraday, pre_market, weekly

if TYPE_CHECKING:
    from src.models import Signal

logger = logging.getLogger(__name__)


# R3.1 红线词汇 — 命中只 logger.warning 不阻断
# 中文「持有」已移除(误报:"你持有的 XXX 基金" 是状态描述,非操作指令)
# 英文 "hold" 保留(英文语境更明确)
_FORBIDDEN_WORDS: list[str] = [
    "买入", "卖出", "做多", "做空",
    "止损", "止盈", "建仓", "减仓", "加仓",
    "buy", "sell", "long", "short", "hold",
]


# push_type → prompt module(Phase 3.9 派发表)
_PROMPT_MODULES = {
    PushType.MORNING.value: pre_market,
    PushType.MIDDAY.value: intraday,
    PushType.EVENING.value: close,
    PushType.WEEKLY.value: weekly,
}


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
        push_type: str | None = None,
    ) -> str:
        """生成 300-500 字 markdown 分析。失败/无 key → "".

        push_type ∈ {morning, midday, evening, weekly};
        未指定或非法 → fallback 到 evening 模板(保持 Phase 3.10 行为)。
        """
        if self.client is None:
            logger.info("AIAnalyst: ANTHROPIC_API_KEY 未配置,跳过 AI 分析")
            return ""

        # 默认 evening 保持向后兼容(Phase 3.10 行为)
        effective_push_type = push_type or PushType.EVENING.value
        module = _PROMPT_MODULES.get(effective_push_type)
        if module is None:
            logger.warning(
                "AIAnalyst: 未知 push_type=%r,fallback 到 evening 模板",
                push_type,
            )
            module = close
            effective_push_type = PushType.EVENING.value

        system_prompt = module.SYSTEM_PROMPT
        user_prompt = module.build_prompt(
            signals, holdings_by_sector or {}, macro_context
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                temperature=self.temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except anthropic.APIError as e:
            logger.error(
                "AIAnalyst (%s): Anthropic API 错误 %s: %s",
                effective_push_type, type(e).__name__, e,
            )
            return ""
        except Exception as e:
            logger.error(
                "AIAnalyst (%s): 未预期异常 %s: %s",
                effective_push_type, type(e).__name__, e,
            )
            return ""

        text_parts: list[str] = []
        for block in response.content:
            if getattr(block, "type", None) == "text":
                text_parts.append(block.text)
        if not text_parts:
            logger.warning("AIAnalyst (%s): 响应里没有 text block", effective_push_type)
            return ""
        text = "\n".join(text_parts).strip()

        hits = self.check_forbidden_words(text)
        if hits:
            logger.warning(
                "AIAnalyst (%s): R3.1 禁用词命中 %s — 输出原样返回,人工把关",
                effective_push_type, hits,
            )

        try:
            u = response.usage
            logger.info(
                "AIAnalyst (%s): tokens input=%d output=%d (model=%s)",
                effective_push_type, u.input_tokens, u.output_tokens, self.model,
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

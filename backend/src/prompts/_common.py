"""Phase 3.9 — 4 个推送场景共享部分:
- BASE_RULES: R3.1 + 不给操作建议 + 格式约束(每个场景的 SYSTEM_PROMPT 都拼这段尾巴)
- build_user_message: USER message 数据 dump(信号 + 持仓 + 宏观),4 场景结构相同
"""

from datetime import date
from typing import TYPE_CHECKING

from src.models.enums import SignalType
from src.utils.date_helper import cn_today

if TYPE_CHECKING:
    from src.models import Signal


BASE_RULES = """==== 严格规则(所有场景通用)====

1. 禁用词汇(R3.1 红线,严禁出现):
   ❌ 买入 / 卖出 / 做多 / 做空 / 止损 / 止盈 / 建仓 / 减仓 / 加仓
   ✅ 可以用:看多 / 看空 / 警惕 / 关注 / 留意 / 观察 / 跟踪
   ✅ 描述用户现有持仓时,可以说"你持有的 XXX"(状态描述),
      但禁止"建议持有 / 应该持有 / 可以持有"(操作指令)

2. 不给操作建议:
   ❌ 不要写 "建议 XX"、"应该 XX"、"可以 XX 操作"
   ✅ 只描述"市场在发生什么" + "对组合的影响"
   ✅ 末尾固定一句:工具只给信号,操作你定。

3. 语气:像专业研究员对老客户说话,
   不夸张、不预测具体涨跌幅,
   多用 "可能 / 大概率 / 值得留意 / 需要观察 / 跟踪" 等措辞。

4. 字数控制:300-500 字之间,严格执行。

5. 输出格式:纯 Markdown(允许 **粗体**、## 小标题、列表),
   不要包裹在 ```markdown``` 代码块里。
"""


def build_user_message(
    signals: "list[Signal]",
    holdings_by_sector: dict[str, list[tuple[str, str]]] | None = None,
    macro_context: str | None = None,
    as_of: date | None = None,
) -> str:
    """USER message — 数据 dump,4 个场景共用结构。"""
    as_of = as_of or cn_today()
    holdings_by_sector = holdings_by_sector or {}
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
    signals_md = "\n".join(sig_lines) if sig_lines else "(无 actionable 信号)"

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

    return f"""日期:{as_of.isoformat()}

==== 板块信号(已过滤,只保留 actionable)====
{signals_md}

==== 用户持仓概况 ====
{portfolio}
{macro_part}
==== 任务 ====
请严格按场景特定的段落结构写一段 300-500 字中文 markdown 分析。
严禁出现"买入/卖出/做多/做空/止损/止盈/建仓/减仓/加仓"等操作指令词汇。
末尾固定一句:工具只给信号,操作你定。
"""

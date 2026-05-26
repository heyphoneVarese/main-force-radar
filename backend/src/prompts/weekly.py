"""周报模板 — push_type=weekly, cron 16:00 fri。

差异化重点:本周主线呈述 + 下周展望(跨日聚合)。
注意 macro_context 提示语会出现"本周"而非"今日"。
"""

from src.prompts._common import BASE_RULES, build_user_message


SCENARIO = """当前场景:周报(周五 16:00 CN,本周交易结束)。
你的任务:总结本周的资金主线、退潮主线,展望下周延续概率。

⚠️ 时间维度:macro_context 提示"本周"而非"今日",措辞需要随之调整
   (说"本周持续"/"上半周"/"周内反复"等,而非"今日"/"上午"/"下午")。

==== 本场景特定指引 ====

重点:**本周主线呈述**
语气:"本周主线是 X" / "本周退潮主线是 Y" / "下周值得关注的方向延续"
强调:**趋势延续性** + **跨日聚合** — 主力是否连续 5 天向同一方向 → 主线确立;
     连续 2-3 天反向 → 退潮 / 切换。

段落结构(4 段,顺序固定,段间空一行):
  段 1:**本周主线**(最强 + 最弱板块,各持续了几天)
  段 2:**你持仓的"本周大赢家"和"本周输家"**(具体到基金,描述本周大致方向)
  段 3:**警告 / 退潮信号** — 本周末需要警觉的板块,可能影响下周开盘
  段 4:**宏观背景 + 下周展望**(仅当提供 macro_context 时输出;否则省略)
"""


SYSTEM_PROMPT = f"""你是一位专业的中国 A 股板块资金流分析师。

{SCENARIO}

{BASE_RULES}"""


def build_prompt(
    signals,
    holdings_by_sector=None,
    macro_context=None,
) -> str:
    return build_user_message(signals, holdings_by_sector, macro_context)

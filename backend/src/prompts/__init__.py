"""Phase 3.9 — Push 模板抽象。

4 个推送场景各有独立 SYSTEM_PROMPT(差异化重点 + 段落结构),
build_prompt 共用同一份用户数据 dump(在 _common.py)。

ai_analyst.py 按 push_type 派发到对应模块。
"""

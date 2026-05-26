"""Server酱 微信推送通道 (Phase 3.8)。

API:
    POST https://sctapi.ftqq.com/{SCKEY}.send
    body: title, desp (Markdown)
    resp: {"code": 0, ...}  # 0 = 成功

R3.1 红线:推送文案中文显示用「看多 / 看空 / 警告」,代码 enum 仍是
bullish / bearish / warning(数据层不带操作指令词)。
"""

import logging
from datetime import date

import httpx

from src.models import Signal
from src.models.enums import SignalType
from src.utils.date_helper import cn_today

logger = logging.getLogger(__name__)


# 中文显示映射 (R3.1: 仅 UI 层,数据层保持英文 enum)
_SIGNAL_LABEL_CN = {
    SignalType.BULLISH.value: ("🟢 看多", "bullish"),
    SignalType.BEARISH.value: ("🔴 看空", "bearish"),
    SignalType.WARNING.value: ("⚠️ 警告", "warning"),
}

# 推送只关心 actionable 三类
_PUSH_ORDER = [SignalType.BULLISH.value, SignalType.BEARISH.value, SignalType.WARNING.value]


class ServerChanNotifier:
    BASE_URL = "https://sctapi.ftqq.com"
    TIMEOUT_SEC = 10.0

    def __init__(self, sckey: str):
        self.sckey = sckey

    # ============ 原始发送 ============

    def send(self, title: str, content: str) -> bool:
        """同步 POST 到 Server酱。任何异常吞掉,返回 False。"""
        if not self.sckey:
            logger.error("ServerChan SCKEY 未配置,跳过推送")
            return False

        url = f"{self.BASE_URL}/{self.sckey}.send"
        try:
            with httpx.Client(timeout=self.TIMEOUT_SEC) as client:
                resp = client.post(url, data={"title": title, "desp": content})
        except Exception as e:
            logger.error("ServerChan 请求失败: %s", e)
            return False

        if resp.status_code != 200:
            logger.error(
                "ServerChan HTTP %s: %s", resp.status_code, resp.text[:200]
            )
            return False

        try:
            data = resp.json()
        except Exception as e:
            logger.error("ServerChan 响应非 JSON: %s; body=%s", e, resp.text[:200])
            return False

        if data.get("code") != 0:
            logger.error("ServerChan code != 0: %s", data)
            return False

        logger.info("ServerChan 推送成功: title=%r", title)
        return True

    # ============ 信号摘要推送 ============

    def send_signal_summary(
        self,
        signals: list[Signal],
        holdings_by_sector: dict[str, list[tuple[str, str]]] | None = None,
        as_of: date | None = None,
    ) -> bool:
        title, content = self.build_summary_markdown(signals, holdings_by_sector, as_of)
        return self.send(title, content)

    @staticmethod
    def build_summary_markdown(
        signals: list[Signal],
        holdings_by_sector: dict[str, list[tuple[str, str]]] | None = None,
        as_of: date | None = None,
    ) -> tuple[str, str]:
        """渲染 Markdown,返回 (title, desp)。
        holdings_by_sector: sector_code → [(fund_code, fund_name), ...]
        """
        as_of = as_of or cn_today()
        holdings_by_sector = holdings_by_sector or {}

        # 按 signal_type 分组,只保留 bullish/bearish/warning
        grouped: dict[str, list[Signal]] = {st: [] for st in _PUSH_ORDER}
        for s in signals:
            if s.signal_type in grouped:
                grouped[s.signal_type].append(s)

        # 标题
        title = f"📊 主力风向标 · {as_of.isoformat()}"

        # 正文
        lines: list[str] = []
        lines.append(f"### 今日板块信号 ({as_of.isoformat()})")
        lines.append("")
        lines.append(
            f"看多 {len(grouped[SignalType.BULLISH.value])} · "
            f"看空 {len(grouped[SignalType.BEARISH.value])} · "
            f"警告 {len(grouped[SignalType.WARNING.value])}"
        )
        lines.append("")
        lines.append("---")
        lines.append("")

        any_signal = False
        for stype in _PUSH_ORDER:
            section_signals = grouped[stype]
            if not section_signals:
                continue
            any_signal = True
            label_cn, _ = _SIGNAL_LABEL_CN[stype]
            lines.append(f"## {label_cn} ({len(section_signals)})")
            lines.append("")
            # 按持续性 score 降序
            for s in sorted(section_signals, key=lambda x: -(x.persistence_score or 0)):
                lines.extend(_render_signal_lines(s, holdings_by_sector.get(s.target_code or "", [])))
                lines.append("")  # 空行分隔

        if not any_signal:
            lines.append("_今日无板块级信号(可能是无数据,或全部 neutral)_")
            lines.append("")

        lines.append("---")
        lines.append("")
        lines.append("💡 工具只给信号,操作你定")

        return title, "\n".join(lines)


def _render_signal_lines(
    signal: Signal, funds: list[tuple[str, str]]
) -> list[str]:
    """生成单条信号的 markdown(2-3 行)。"""
    score = signal.persistence_score or 0
    flow_yi = (signal.main_inflow_wan_x10000 or 0) / 10_000 / 10_000
    direction = "+" if flow_yi > 0 else ""
    sector_label = _sector_display_name(signal)
    annotation = _annotation(signal)

    # eg: "- 半导体 (BK0490)  score 8/9  主力 +95.0 亿  *强信号*"
    head = (
        f"- **{sector_label}** ({signal.target_code})  "
        f"score {score}/9  主力 {direction}{flow_yi:.1f} 亿"
    )
    if annotation:
        head += f"  *{annotation}*"
    out = [head]

    if funds:
        names = " / ".join(name for _, name in funds[:4])
        if len(funds) > 4:
            names += f" 等 {len(funds)} 只"
        out.append(f"  你持仓 {len(funds)} 只:{names}")
    return out


def _sector_display_name(signal: Signal) -> str:
    """优先用 signal_name 里的板块名(generate_signals_for_holdings 已填),fallback 用 code。"""
    name = signal.signal_name or ""
    # signal_name 格式:"光模块 bullish" → 取空格前
    parts = name.split(" ")
    if len(parts) >= 2 and parts[0]:
        return parts[0]
    return signal.target_code or ""


def _annotation(signal: Signal) -> str:
    """根据 signal 类型 + score 加注释词。"""
    score = signal.persistence_score or 0
    st = signal.signal_type
    if st == SignalType.BULLISH.value and score >= 8:
        return "强信号"
    if st == SignalType.BEARISH.value and score >= 8:
        return "强退潮"
    if st == SignalType.WARNING.value:
        # warning = 4-7 + divergence(分歧)
        return "价量背离"
    return ""

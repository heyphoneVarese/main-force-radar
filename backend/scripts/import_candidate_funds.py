"""一次性导入候选基金池到 funds 表(Phase 5.1 PR14)。

跑法(backend 目录下):
    uv run python scripts/import_candidate_funds.py
    # Docker:
    docker compose exec backend uv run --no-dev python -m scripts.import_candidate_funds

为什么需要这个脚本:
    seed_funds.py 主要塞了用户持仓基金(~52 只)。Dashboard "最强 20 基金候选"
    卡片从整张 funds 表选 Top 20,结果几乎全是 "已持有"(没"候选"对比)。
    本脚本补常见公募基金(ETF / 指数 / 主题主动基金 等),让 funds 表能上 100+,
    Dashboard 才能真显出 "市场上还有这些 候选 你没持仓" 的差异。

【2026-05-30 数据校验】
本候选池中的 58 只 fund_code + fund_name 已逐个在 eastmoney 验证
(https://fund.eastmoney.com/{CODE}.html),全部真实存在且名字对齐。
原 75 只候选中 17 只因 code 实际是其它基金(VR/旅游/农业等)被删除。
verify script (供后续 audit 复跑):
    # 单条:python -c "import urllib.request; ..."
    # 或浏览器直接打 URL 看顶部 H1 标题
若发现仍有错,DELETE FROM funds WHERE fund_code='xxxxxx';
然后改本文件重跑(已存在 → skip,只补改对的)。

数据原则(R3 / R6):
- 不基于"涨幅 / 业绩"挑选 — 只按"覆盖 10 个常见板块方向"挑选
- 只列在 eastmoney 验证过的代码 + 名字
- fund_type 全部硬编码 "其他"(spec:跟 PR13 UI 新增逻辑一致;
  类型不影响信号 / dashboard 渲染,只是显示标签)
- related_sectors 用中文标签(跟 seed_funds.py 一致;sector_aliases 负责
  映射到 eastmoney BK 板块码)

行为:
- 每条:fund_code 已在 funds → 跳过(不覆盖,保留已有的 fund_type 等元信息);
  否则 INSERT
- 最终打印 inserted_count / skipped_count / total_funds_count
"""

from __future__ import annotations

import logging
import sys
from typing import Any

from src.db import SessionLocal
from src.models import Fund
from src.utils.fund_code import is_valid_fund_code

logger = logging.getLogger(__name__)


# =====================================================================
# 候选基金池(58 只,全部 eastmoney 验证过)
# =====================================================================
# 字段:fund_code(6 位)/ fund_name / related_sectors(中文标签数组)
# 不写 fund_type — main() 时统一填 "其他"。
#
# 覆盖方向:
#   主流宽基 ETF(9):上证50/沪深300/中证500/中证1000/红利/H股/创业板...
#   1. 半导体/芯片/集成电路 (6)
#   2. 人工智能/算力/光模块 (4)
#   3. 机器人/智能制造 (2)
#   4. 电力/电网/储能 (1)
#   5. 军工 (2)
#   6. 黄金/有色 (6)
#   7. 红利/银行/券商 (4)
#   8. 消费/白酒/家电 (6)
#   9. 新能源车/电池/光伏 (4)
#   10. 科创/创业板/数字经济 (6)
#   知名主动基金 (3):中欧医疗 / 富国天惠 / 易方达优质精选
#   港股/海外 (5):标普500 / 中概互联 / 恒生科技 / 恒生互联网
# =====================================================================

CANDIDATE_FUNDS: list[dict[str, Any]] = [
    # ============================================================
    # 主流宽基(9)
    # ============================================================
    {"fund_code": "510050", "fund_name": "华夏上证50ETF",
     "related_sectors": ["上证50"]},
    {"fund_code": "510300", "fund_name": "华泰柏瑞沪深300ETF",
     "related_sectors": ["沪深300"]},
    {"fund_code": "510500", "fund_name": "南方中证500ETF",
     "related_sectors": ["中证500"]},
    {"fund_code": "512100", "fund_name": "南方中证1000ETF",
     "related_sectors": ["中证1000"]},
    {"fund_code": "510880", "fund_name": "华泰柏瑞红利ETF",
     "related_sectors": ["红利"]},
    {"fund_code": "510900", "fund_name": "易方达恒生中国企业ETF",
     "related_sectors": ["港股", "恒生H股"]},
    {"fund_code": "110003", "fund_name": "易方达上证50增强A",
     "related_sectors": ["上证50"]},
    {"fund_code": "159915", "fund_name": "易方达创业板ETF",
     "related_sectors": ["创业板"]},
    {"fund_code": "159949", "fund_name": "华安创业板50ETF",
     "related_sectors": ["创业板"]},

    # ============================================================
    # 1. 半导体 / 芯片 / 集成电路 (6)
    # ============================================================
    {"fund_code": "159995", "fund_name": "华夏国证半导体芯片ETF",
     "related_sectors": ["半导体", "芯片", "集成电路"]},
    {"fund_code": "512760", "fund_name": "国泰CES半导体芯片ETF",
     "related_sectors": ["半导体", "芯片"]},
    {"fund_code": "512480", "fund_name": "国联安中证全指半导体ETF",
     "related_sectors": ["半导体", "芯片"]},
    {"fund_code": "008888", "fund_name": "华夏国证半导体芯片ETF联接C",
     "related_sectors": ["半导体", "芯片"]},
    {"fund_code": "588200", "fund_name": "嘉实上证科创板芯片ETF",
     "related_sectors": ["半导体", "芯片", "科创板"]},
    {"fund_code": "159939", "fund_name": "广发中证全指信息技术ETF",
     "related_sectors": ["人工智能", "信息技术"]},

    # ============================================================
    # 2. 人工智能 / 算力 / 光模块 (4)
    # ============================================================
    {"fund_code": "159819", "fund_name": "易方达人工智能ETF",
     "related_sectors": ["人工智能", "算力"]},
    {"fund_code": "515980", "fund_name": "华富人工智能ETF",
     "related_sectors": ["人工智能", "算力"]},
    {"fund_code": "515050", "fund_name": "华夏中证5G通信主题ETF",
     "related_sectors": ["5G通信", "光模块"]},
    {"fund_code": "515880", "fund_name": "国泰中证通信ETF",
     "related_sectors": ["通信设备", "光模块"]},

    # ============================================================
    # 3. 机器人 / 智能制造 (2)
    # ============================================================
    {"fund_code": "562500", "fund_name": "华夏中证机器人ETF",
     "related_sectors": ["机器人", "智能制造"]},
    {"fund_code": "020972", "fund_name": "易方达国证机器人产业ETF联接A",
     "related_sectors": ["机器人"]},

    # ============================================================
    # 4. 电力 / 电网 / 储能 (1)
    # ============================================================
    {"fund_code": "159611", "fund_name": "广发中证全指电力公用事业ETF",
     "related_sectors": ["电力", "公用事业"]},

    # ============================================================
    # 5. 军工 (2)
    # ============================================================
    {"fund_code": "512660", "fund_name": "国泰中证军工ETF",
     "related_sectors": ["军工"]},
    {"fund_code": "512710", "fund_name": "富国中证军工龙头ETF",
     "related_sectors": ["军工"]},

    # ============================================================
    # 6. 黄金 / 有色 (6)
    # ============================================================
    {"fund_code": "518880", "fund_name": "华安黄金ETF",
     "related_sectors": ["黄金"]},
    {"fund_code": "159934", "fund_name": "易方达黄金ETF",
     "related_sectors": ["黄金"]},
    {"fund_code": "518800", "fund_name": "国泰黄金ETF",
     "related_sectors": ["黄金"]},
    {"fund_code": "159980", "fund_name": "大成有色金属ETF",
     "related_sectors": ["有色金属"]},
    {"fund_code": "512400", "fund_name": "南方中证申万有色金属ETF",
     "related_sectors": ["有色金属"]},
    {"fund_code": "000216", "fund_name": "华安黄金ETF联接A",
     "related_sectors": ["黄金"]},

    # ============================================================
    # 7. 红利 / 银行 / 券商 (4)
    # ============================================================
    {"fund_code": "515180", "fund_name": "易方达红利ETF",
     "related_sectors": ["红利"]},
    {"fund_code": "512800", "fund_name": "华宝中证银行ETF",
     "related_sectors": ["银行"]},
    {"fund_code": "512880", "fund_name": "国泰证券ETF",
     "related_sectors": ["证券"]},
    {"fund_code": "512000", "fund_name": "华宝券商ETF",
     "related_sectors": ["证券"]},

    # ============================================================
    # 8. 消费 / 白酒 / 家电 (6)
    # ============================================================
    {"fund_code": "161725", "fund_name": "招商中证白酒指数LOF",
     "related_sectors": ["白酒", "消费"]},
    {"fund_code": "512690", "fund_name": "鹏华中证酒ETF",
     "related_sectors": ["白酒", "酒"]},
    {"fund_code": "159928", "fund_name": "汇添富中证主要消费ETF",
     "related_sectors": ["消费", "主要消费"]},
    {"fund_code": "159996", "fund_name": "国泰中证家用电器ETF",
     "related_sectors": ["家用电器", "消费"]},
    {"fund_code": "110022", "fund_name": "易方达消费行业股票",
     "related_sectors": ["消费"]},
    {"fund_code": "005827", "fund_name": "易方达蓝筹精选混合",
     "related_sectors": ["大消费", "蓝筹"]},

    # ============================================================
    # 9. 新能源车 / 电池 / 光伏 (4)
    # ============================================================
    {"fund_code": "515030", "fund_name": "华夏中证新能源汽车ETF",
     "related_sectors": ["新能源车", "电池"]},
    {"fund_code": "515790", "fund_name": "华泰柏瑞中证光伏产业ETF",
     "related_sectors": ["光伏"]},
    {"fund_code": "516160", "fund_name": "南方中证新能源ETF",
     "related_sectors": ["新能源"]},
    {"fund_code": "159864", "fund_name": "国泰光伏ETF",
     "related_sectors": ["光伏"]},

    # ============================================================
    # 10. 科创 / 创业板 / 数字经济 (6)
    # ============================================================
    {"fund_code": "588000", "fund_name": "华夏上证科创板50成份ETF",
     "related_sectors": ["科创板"]},
    {"fund_code": "588080", "fund_name": "易方达上证科创板50ETF",
     "related_sectors": ["科创板"]},
    {"fund_code": "588050", "fund_name": "工银上证科创板50ETF",
     "related_sectors": ["科创板"]},
    {"fund_code": "159658", "fund_name": "华安数字经济ETF",
     "related_sectors": ["数字经济"]},
    {"fund_code": "159952", "fund_name": "广发创业板ETF",
     "related_sectors": ["创业板"]},
    {"fund_code": "159967", "fund_name": "华夏创业板成长ETF",
     "related_sectors": ["创业板"]},

    # ============================================================
    # 知名主动管理基金(3)
    # ============================================================
    # 注:110011 已从 "易方达中小盘混合"(张坤名作)更名 +
    # 转型为 "易方达优质精选混合(QDII)",fund_code 一致但策略已变。
    {"fund_code": "110011", "fund_name": "易方达优质精选混合(QDII)",
     "related_sectors": ["QDII", "全球精选"]},
    {"fund_code": "003095", "fund_name": "中欧医疗健康混合A",
     "related_sectors": ["医疗"]},
    {"fund_code": "161005", "fund_name": "富国天惠成长混合(LOF)A",
     "related_sectors": ["大盘成长"]},

    # ============================================================
    # 港股 / 海外(5)
    # ============================================================
    {"fund_code": "050025", "fund_name": "博时标普500ETF联接A",
     "related_sectors": ["标普500", "美股"]},
    {"fund_code": "513050", "fund_name": "易方达中概互联50ETF",
     "related_sectors": ["中概互联", "港股"]},
    {"fund_code": "513180", "fund_name": "华夏恒生科技ETF",
     "related_sectors": ["恒生科技", "港股"]},
    {"fund_code": "159740", "fund_name": "大成恒生科技ETF",
     "related_sectors": ["恒生科技", "港股"]},
    {"fund_code": "513330", "fund_name": "华夏恒生互联网ETF",
     "related_sectors": ["港股", "恒生互联网"]},
]


def _normalize(entry: dict[str, Any]) -> dict[str, Any] | None:
    """校验 + 补 fund_type='其他'。code 非法返 None。"""
    code = entry.get("fund_code", "").strip()
    name = entry.get("fund_name", "").strip()
    if not is_valid_fund_code(code):
        logger.warning("skip invalid fund_code: %r", code)
        return None
    if not name:
        logger.warning("skip empty fund_name for code=%s", code)
        return None
    return {
        "fund_code": code,
        "fund_name": name,
        "fund_type": "其他",  # spec:hardcode 默认
        "related_sectors": entry.get("related_sectors") or None,
    }


def run(session) -> dict[str, Any]:
    """主逻辑。返回 stats dict(便于单测断言)。"""
    inserted: list[str] = []
    skipped: list[str] = []
    invalid: list[str] = []

    seen_in_payload: set[str] = set()
    for raw in CANDIDATE_FUNDS:
        norm = _normalize(raw)
        if norm is None:
            invalid.append(raw.get("fund_code", "?"))
            continue
        code = norm["fund_code"]

        # 同一次调用里 payload 内部重复 → 视为 skip(无声跳过,fix 列表时统一)
        if code in seen_in_payload:
            skipped.append(code)
            continue
        seen_in_payload.add(code)

        # DB 已存在 → skip
        existing = session.get(Fund, code)
        if existing is not None:
            skipped.append(code)
            continue

        session.add(Fund(**norm))
        inserted.append(code)

    session.commit()
    total = session.query(Fund).count()
    return {
        "inserted_count": len(inserted),
        "skipped_count": len(skipped),
        "invalid_count": len(invalid),
        "total_funds_count": total,
        "inserted": inserted,
        "skipped": skipped,
        "invalid": invalid,
    }


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    with SessionLocal() as session:
        stats = run(session)

    print("=" * 60)
    print("📊 import_candidate_funds 完成:")
    print(f"  ✅ inserted        : {stats['inserted_count']} 只")
    print(f"  ⏭  skipped (已存在) : {stats['skipped_count']} 只")
    print(f"  ⚠️  invalid         : {stats['invalid_count']} 只")
    print(f"  📦 funds 表总条数    : {stats['total_funds_count']}")
    print("=" * 60)

    if stats["invalid"]:
        print("\n非法 fund_code(已跳过,请检查脚本):")
        for c in stats["invalid"]:
            print(f"  {c}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

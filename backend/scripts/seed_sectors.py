"""一次性灌入 sector_aliases 表(方案 B:静态种子)。

用法(在 backend/ 目录下):
    uv run python -m scripts.seed_sectors

confidence 含义:
- 1.0  用户明确指定 / eastmoney 官方网站已验证
- 0.7  我有合理把握(常识 + 数据特征),建议 VPS 部署后 ak.stock_board_industry_name_em() 二次确认
- 0.5  粗略映射(标签≈某板块,如 '电子' → '半导体')
- 0.0  显式无对应(指数/海外/商品,不存在 eastmoney 行业板块)

幂等:chinese_label 已存在则跳过,允许多次跑。
"""

import logging
from typing import Any

from src.db import SessionLocal
from src.models import SectorAlias
from src.services.sector_mapping import coverage_report

logger = logging.getLogger(__name__)


# ============================================================
# sector_aliases 种子数据 — 39 个标签
# 字段:label, code (BKxxxx 或 None), name (eastmoney 板块名), conf, notes
# ============================================================
SECTOR_ALIASES: list[dict[str, Any]] = [
    # ===== conf=1.0:用户明确给的 4 个 =====
    {"label": "CPO",        "code": "BK1144", "name": "光模块",      "conf": 1.0, "notes": "用户提供"},
    {"label": "光模块",     "code": "BK1144", "name": "光模块",      "conf": 1.0, "notes": "用户提供"},
    {"label": "半导体",     "code": "BK0490", "name": "半导体",      "conf": 1.0, "notes": "用户提供"},
    {"label": "5G通信",     "code": "BK0727", "name": "5G概念",      "conf": 1.0, "notes": "用户提供"},

    # ===== conf=0.7:常识级,VPS 部署后用 ak.stock_board_industry_name_em 二次校对 =====
    {"label": "芯片",         "code": "BK0490", "name": "半导体",       "conf": 0.7, "notes": "芯片 ≈ 半导体,共用 BK"},
    {"label": "存储芯片",     "code": "BK0490", "name": "半导体",       "conf": 0.7, "notes": "存储芯片是半导体子类"},
    {"label": "半导体材料",   "code": "BK0490", "name": "半导体",       "conf": 0.6, "notes": "材料板可能有独立 BK,待 VPS 验证"},
    {"label": "AI",           "code": "BK1019", "name": "人工智能",     "conf": 0.6, "notes": "BK1019 待 VPS 验证"},
    {"label": "人工智能",     "code": "BK1019", "name": "人工智能",     "conf": 0.6, "notes": "同上"},
    {"label": "AI算力",       "code": "BK1019", "name": "人工智能",     "conf": 0.5, "notes": "AI 算力 ≈ 人工智能 + 算力,粗映射"},
    {"label": "机器人",       "code": "BK0594", "name": "机器人概念",   "conf": 0.6, "notes": "BK0594 待 VPS 验证"},
    {"label": "智能装备",     "code": "BK0594", "name": "机器人概念",   "conf": 0.4, "notes": "粗映射;eastmoney 可能有独立智能装备板"},
    {"label": "电子",         "code": "BK0490", "name": "半导体",       "conf": 0.4, "notes": "电子是大行业,粗映射到半导体"},
    {"label": "通信设备",     "code": "BK0736", "name": "通信设备",     "conf": 0.5, "notes": "BK0736 待 VPS 验证"},
    {"label": "通信技术",     "code": "BK0727", "name": "5G概念",       "conf": 0.4, "notes": "通信技术 ≈ 5G/通信,粗映射"},
    {"label": "光伏",         "code": "BK0478", "name": "光伏设备",     "conf": 0.6, "notes": "BK0478 待 VPS 验证"},
    {"label": "电池",         "code": "BK0900", "name": "锂电池",       "conf": 0.5, "notes": "电池 ≈ 锂电池,BK 待验证"},
    {"label": "锂电池",       "code": "BK0900", "name": "锂电池",       "conf": 0.5, "notes": "BK0900 待 VPS 验证"},
    {"label": "新能源",       "code": "BK0493", "name": "新能源车",     "conf": 1.0, "notes": "用户提供"},
    {"label": "黄金",         "code": "BK0480", "name": "黄金概念",     "conf": 0.6, "notes": "BK0480 待 VPS 验证"},
    {"label": "黄金股",       "code": "BK0480", "name": "黄金概念",     "conf": 0.6, "notes": "黄金股 ≈ 黄金概念"},
    {"label": "电网设备",     "code": "BK0428", "name": "电网设备",     "conf": 0.5, "notes": "BK 待 VPS 验证"},
    {"label": "中韩半导体",   "code": "BK0490", "name": "半导体",       "conf": 0.4, "notes": "中韩半导体是国际化指数,粗映射到 A 股半导体"},
    {"label": "商业航天",     "code": None,     "name": None,           "conf": 0.0, "notes": "TODO:商业航天 BK 待查(eastmoney 可能有新概念板)"},
    {"label": "医药",         "code": None,     "name": None,           "conf": 0.0, "notes": "TODO:医药行业 BK 待查(可能是 BK0727 医药制造?待验证)"},

    # ===== conf=0.0:结构性无 eastmoney 行业板块对应 =====
    # 这些不是"找不到代码",而是这类资产**本质上不属于 A 股行业板块**,
    # sector_flow_daily 资金流分析对它们不适用。Phase 2.7 信号引擎应跳过。
    {"label": "沪深300",       "code": None, "name": None, "conf": 0.0, "notes": "市场宽基指数,非行业板块"},
    {"label": "中证500",       "code": None, "name": None, "conf": 0.0, "notes": "市场宽基指数,非行业板块"},
    {"label": "中盘股",        "code": None, "name": None, "conf": 0.0, "notes": "市值因子,非行业板块"},
    {"label": "科创板",        "code": None, "name": None, "conf": 0.0, "notes": "市场板,非行业板块"},
    {"label": "标普500",       "code": None, "name": None, "conf": 0.0, "notes": "海外指数,非 A 股"},
    {"label": "纳指100",       "code": None, "name": None, "conf": 0.0, "notes": "海外指数,非 A 股"},
    {"label": "美股",          "code": None, "name": None, "conf": 0.0, "notes": "海外市场"},
    {"label": "港股",          "code": None, "name": None, "conf": 0.0, "notes": "港股市场,非 A 股板块"},
    {"label": "港股创新药",    "code": None, "name": None, "conf": 0.0, "notes": "港股"},
    {"label": "海外科技",      "code": None, "name": None, "conf": 0.0, "notes": "海外,非 A 股"},
    {"label": "全球科技",      "code": None, "name": None, "conf": 0.0, "notes": "全球,非 A 股"},
    {"label": "全球精选",      "code": None, "name": None, "conf": 0.0, "notes": "全球/海外"},
    {"label": "亚太",          "code": None, "name": None, "conf": 0.0, "notes": "海外区域"},
    {"label": "债券",          "code": None, "name": None, "conf": 0.0, "notes": "固收,非行业板块"},
    {"label": "低波固收",      "code": None, "name": None, "conf": 0.0, "notes": "固收"},
]


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    total = len(SECTOR_ALIASES)
    inserted = 0
    skipped = 0

    with SessionLocal() as session:
        for entry in SECTOR_ALIASES:
            label = entry["label"]
            existing = (
                session.query(SectorAlias).filter_by(chinese_label=label).first()
            )
            if existing is not None:
                skipped += 1
                continue
            session.add(
                SectorAlias(
                    chinese_label=label,
                    sector_code=entry["code"],
                    sector_name=entry["name"],
                    confidence=entry["conf"],
                    notes=entry["notes"],
                )
            )
            inserted += 1
        session.commit()

    print(f"\nseed_sectors done: total={total}, inserted={inserted}, skipped={skipped}")

    # 覆盖率报告
    with SessionLocal() as session:
        report = coverage_report(session)
    print("\n" + "=" * 70)
    print(f"基金 → 板块覆盖率报告")
    print("=" * 70)
    print(f"已映射 (≥1 个 BK 代码): {report['mapped']}/{report['total']} ({report['coverage_pct']}%)")
    print(f"未映射:                {report['unmapped_count']}/{report['total']}")

    if report["unmapped_labels"]:
        print(f"\n⚠️  funds 中出现但 sector_aliases 完全无记录的标签 (需要补充):")
        for lbl in report["unmapped_labels"]:
            print(f"    - {lbl}")
    else:
        print("\n✅ 所有 funds 标签都在 sector_aliases 表里有记录(可能 sector_code=NULL)")

    if report["unmapped_funds"]:
        print(f"\n未映射的基金明细 ({len(report['unmapped_funds'])} 只):")
        for code, name, labels in report["unmapped_funds"]:
            print(f"    [{code}] {name}  labels={labels}")


if __name__ == "__main__":
    main()

"""发现 funds.related_sectors 中所有不重复的中文标签 + 与现有 sector_aliases 对照。

用法(在 backend/ 目录下):
    uv run python -m scripts.build_sector_aliases

这是个**只读诊断脚本**,不写库。用途:
- 列出 funds 表里所有出现过的中文标签 (去重)
- 对照 sector_aliases 表,标出哪些已映射 / 哪些缺失
- 输出可直接 paste 到 seed_sectors.py 的占位 dict

Phase 2.6 的方案 B 是静态种子(seed_sectors.py);本脚本是辅助工具,
用户加新基金后跑一下能快速看到哪些新标签需要补 alias。

未来 VPS 部署后可以扩展:对每个缺失标签调 ak.stock_board_industry_name_em()
做模糊匹配,自动建议 BK 代码 + 给 confidence 评分。
"""

import logging

from sqlalchemy import select

from src.db import SessionLocal
from src.models import Fund, SectorAlias

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    with SessionLocal() as session:
        funds = session.scalars(select(Fund)).all()
        aliases = {
            a.chinese_label: a
            for a in session.scalars(select(SectorAlias)).all()
        }

    # 收集 funds 里出现的所有标签 + 计数
    label_count: dict[str, int] = {}
    for f in funds:
        for lbl in f.related_sectors or []:
            label_count[lbl] = label_count.get(lbl, 0) + 1

    if not label_count:
        print("funds 表为空或没有 related_sectors 数据")
        return

    print(f"\n📊 在 {len(funds)} 只 funds 中发现 {len(label_count)} 个不重复中文标签")
    print("=" * 70)
    print(f"{'标签':<16} {'出现次数':>6} {'状态':<24} {'BK / 备注'}")
    print("-" * 70)

    mapped_with_code = 0
    mapped_no_code = 0
    unknown = 0

    for label, count in sorted(label_count.items(), key=lambda x: -x[1]):
        alias = aliases.get(label)
        if alias is None:
            status = "❌ sector_aliases 缺失"
            extra = "需要 seed_sectors.py 补"
            unknown += 1
        elif alias.sector_code is None:
            status = f"➖ 显式无对应 (conf={alias.confidence:.1f})"
            extra = alias.notes or ""
            mapped_no_code += 1
        else:
            status = f"✅ {alias.sector_code} (conf={alias.confidence:.1f})"
            extra = alias.sector_name or ""
            mapped_with_code += 1

        print(f"{label:<16} {count:>6} {status:<24} {extra}")

    print("-" * 70)
    print(
        f"汇总:已映射 BK={mapped_with_code} 个 / 显式无对应={mapped_no_code} 个 / 缺失={unknown} 个"
    )
    if unknown > 0:
        print("\n⚠️  缺失标签的建议种子条目(粘到 seed_sectors.py 的 SECTOR_ALIASES):")
        for label, _ in sorted(label_count.items()):
            if label not in aliases:
                print(
                    f'    {{"label": "{label}", "code": None, "name": None, '
                    f'"conf": 0.0, "notes": "TODO: 待手动映射"}},'
                )


if __name__ == "__main__":
    main()

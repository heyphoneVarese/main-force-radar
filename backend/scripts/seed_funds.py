"""一次性灌入用户持仓的基金清单。

用法(在 backend/ 目录下):
    uv run python -m scripts.seed_funds

幂等:
- fund_code 已存在 → 跳过
- fund_code 非法 → 跳过并提示(留 "TODO" 之类的占位也会跳过)

related_sectors 是用户在 Phase 1.5a 提供的初版语义标签(中文名,
非 sector_code)。Phase 2 第 6 步「基金→板块关联」会做对齐:
要么把这些 name 映射到真实 sector_code,要么改 schema 加 mapping 表。
"""

import logging

from src.db import SessionLocal
from src.models import Fund
from src.utils.fund_code import is_valid_fund_code

logger = logging.getLogger(__name__)


# ============================================================
# 用户持仓基金清单 — 52 只(用户提供)
# 字段:
#   fund_code        : 6 位数字
#   fund_name        : 中文名
#   fund_type        : 混合型 / 指数型 / QDII / 股票型
#   related_sectors  : 中文标签列表(后续与 sector_flow 表对齐)
# ============================================================
FUNDS_TO_SEED: list[dict] = [
    {"fund_code": "008281", "fund_name": "国泰CES半导体芯片行业ETF联接A", "fund_type": "指数型", "related_sectors": ["半导体", "芯片"]},
    {"fund_code": "014320", "fund_name": "德邦半导体产业混合发起", "fund_type": "混合型", "related_sectors": ["存储芯片", "半导体"]},
    {"fund_code": "018412", "fund_name": "易方达中证芯片产业ETF联接", "fund_type": "指数型", "related_sectors": ["半导体", "芯片"]},
    {"fund_code": "007343", "fund_name": "嘉实科技创新混合", "fund_type": "混合型", "related_sectors": ["半导体"]},
    {"fund_code": "009707", "fund_name": "工银新兴制造混合A", "fund_type": "混合型", "related_sectors": ["半导体"]},
    {"fund_code": "016238", "fund_name": "华夏数字经济龙头混合", "fund_type": "混合型", "related_sectors": ["半导体"]},
    {"fund_code": "005312", "fund_name": "万家经济新动能混合C", "fund_type": "混合型", "related_sectors": ["半导体"]},
    {"fund_code": "019455", "fund_name": "华泰柏瑞中韩半导体ETF联接", "fund_type": "指数型", "related_sectors": ["中韩半导体"]},
    {"fund_code": "017811", "fund_name": "东方人工智能主题混合C", "fund_type": "混合型", "related_sectors": ["半导体材料", "AI"]},
    {"fund_code": "006502", "fund_name": "财通集成电路产业股票A", "fund_type": "股票型", "related_sectors": ["CPO", "半导体"]},
    {"fund_code": "022365", "fund_name": "永赢科技智选混合发起C", "fund_type": "混合型", "related_sectors": ["CPO", "光模块"]},
    {"fund_code": "017103", "fund_name": "大摩数字经济混合C", "fund_type": "混合型", "related_sectors": ["CPO", "AI算力"]},
    {"fund_code": "110029", "fund_name": "易方达科讯混合", "fund_type": "混合型", "related_sectors": ["5G通信"]},
    {"fund_code": "001323", "fund_name": "东吴移动互联混合A", "fund_type": "混合型", "related_sectors": ["5G通信"]},
    {"fund_code": "000979", "fund_name": "景顺长城沪港深精选股票A", "fund_type": "股票型", "related_sectors": ["5G通信", "港股"]},
    {"fund_code": "000698", "fund_name": "宝盈科技30混合", "fund_type": "混合型", "related_sectors": ["5G通信"]},
    {"fund_code": "002771", "fund_name": "安信新回报混合C", "fund_type": "混合型", "related_sectors": ["5G通信"]},
    {"fund_code": "007817", "fund_name": "国泰中证全指通信设备ETF联接", "fund_type": "指数型", "related_sectors": ["通信设备"]},
    {"fund_code": "011891", "fund_name": "易方达先锋成长混合A", "fund_type": "混合型", "related_sectors": ["通信技术"]},
    {"fund_code": "016371", "fund_name": "信澳业绩驱动混合C", "fund_type": "混合型", "related_sectors": ["通信技术"]},
    {"fund_code": "004320", "fund_name": "前海开源沪港深乐享生活", "fund_type": "混合型", "related_sectors": ["通信技术", "港股"]},
    {"fund_code": "008528", "fund_name": "华泰柏瑞质量成长混合A", "fund_type": "混合型", "related_sectors": ["通信技术"]},
    {"fund_code": "001513", "fund_name": "易方达信息产业混合A", "fund_type": "混合型", "related_sectors": ["人工智能"]},
    {"fund_code": "017484", "fund_name": "财通资管数字经济混合", "fund_type": "混合型", "related_sectors": ["人工智能"]},
    {"fund_code": "025505", "fund_name": "华夏创业板人工智能ETF联接", "fund_type": "指数型", "related_sectors": ["人工智能"]},
    {"fund_code": "020973", "fund_name": "易方达国证机器人产业ETF联接", "fund_type": "指数型", "related_sectors": ["机器人"]},
    {"fund_code": "001072", "fund_name": "华安智能装备主题股票A", "fund_type": "股票型", "related_sectors": ["电子", "智能装备"]},
    {"fund_code": "024195", "fund_name": "永赢国证商用卫星通信", "fund_type": "指数型", "related_sectors": ["商业航天"]},
    {"fund_code": "025491", "fund_name": "平安中证卫星产业指数C", "fund_type": "指数型", "related_sectors": ["商业航天"]},
    {"fund_code": "014002", "fund_name": "浦银安盛全球智能科技QDII", "fund_type": "QDII", "related_sectors": ["海外科技"]},
    {"fund_code": "016702", "fund_name": "银华海外数字经济量化QDII", "fund_type": "QDII", "related_sectors": ["海外科技"]},
    {"fund_code": "017731", "fund_name": "嘉实全球产业升级股票QDII", "fund_type": "QDII", "related_sectors": ["全球科技"]},
    {"fund_code": "161125", "fund_name": "易方达标普500指数QDII", "fund_type": "QDII", "related_sectors": ["标普500", "美股"]},
    {"fund_code": "019172", "fund_name": "摩根纳斯达克100指数QDII", "fund_type": "QDII", "related_sectors": ["纳指100", "美股"]},
    {"fund_code": "012920", "fund_name": "易方达全球成长精选混合A", "fund_type": "混合型", "related_sectors": ["全球精选"]},
    {"fund_code": "012922", "fund_name": "易方达全球成长精选混合C", "fund_type": "混合型", "related_sectors": ["全球精选"]},
    {"fund_code": "021189", "fund_name": "南方富时亚太低碳精选ETF联接", "fund_type": "QDII", "related_sectors": ["亚太"]},
    {"fund_code": "007028", "fund_name": "易方达中证500ETF联接A", "fund_type": "指数型", "related_sectors": ["中证500"]},
    {"fund_code": "007339", "fund_name": "易方达沪深300ETF联接C", "fund_type": "指数型", "related_sectors": ["沪深300"]},
    {"fund_code": "023891", "fund_name": "博时上证科创板综合价格指数增强A", "fund_type": "指数型", "related_sectors": ["科创板"]},
    {"fund_code": "023998", "fund_name": "易方达上证科创板综合ETF联接", "fund_type": "指数型", "related_sectors": ["科创板"]},
    {"fund_code": "023902", "fund_name": "博道上证科创板综合指数A", "fund_type": "指数型", "related_sectors": ["科创板"]},
    {"fund_code": "002862", "fund_name": "金信量化精选混合A", "fund_type": "混合型", "related_sectors": ["中盘股"]},
    {"fund_code": "023638", "fund_name": "国泰恒生A股电网设备ETF联接A", "fund_type": "指数型", "related_sectors": ["电网设备"]},
    {"fund_code": "012929", "fund_name": "银华中证光伏产业ETF联接", "fund_type": "指数型", "related_sectors": ["光伏"]},
    {"fund_code": "011967", "fund_name": "招商中证光伏产业指数C", "fund_type": "指数型", "related_sectors": ["光伏"]},
    {"fund_code": "016567", "fund_name": "嘉实中证电池主题ETF联接", "fund_type": "指数型", "related_sectors": ["电池"]},
    {"fund_code": "006122", "fund_name": "华安低碳生活混合A", "fund_type": "混合型", "related_sectors": ["锂电池", "新能源"]},
    {"fund_code": "021363", "fund_name": "易方达中证沪深港黄金股票ETF联接", "fund_type": "指数型", "related_sectors": ["黄金股"]},
    {"fund_code": "002963", "fund_name": "易方达黄金ETF联接C", "fund_type": "指数型", "related_sectors": ["黄金"]},
    {"fund_code": "011393", "fund_name": "中欧融益稳健一年混合A", "fund_type": "混合型", "related_sectors": ["低波固收", "债券"]},
    {"fund_code": "011826", "fund_name": "汇添富健康生活一年持有混合", "fund_type": "混合型", "related_sectors": ["港股创新药", "医药"]},
]


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    skipped_invalid = 0
    skipped_exists = 0
    inserted = 0

    with SessionLocal() as session:
        for entry in FUNDS_TO_SEED:
            code = entry["fund_code"]
            if not is_valid_fund_code(code):
                logger.warning("skip [%s] %s: invalid fund_code", code, entry["fund_name"])
                skipped_invalid += 1
                continue
            if session.get(Fund, code) is not None:
                logger.info("skip [%s] %s: already in funds table", code, entry["fund_name"])
                skipped_exists += 1
                continue
            session.add(Fund(**entry))
            inserted += 1
            logger.info("seeded [%s] %s", code, entry["fund_name"])
        session.commit()

    logger.info(
        "seed_funds done: inserted=%d, skipped_invalid=%d, skipped_exists=%d, total=%d",
        inserted,
        skipped_invalid,
        skipped_exists,
        len(FUNDS_TO_SEED),
    )


if __name__ == "__main__":
    main()

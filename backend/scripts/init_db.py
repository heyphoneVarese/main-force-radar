"""一次性初始化数据库:建表 + 写入 user_config 默认值。

用法(在 backend/ 目录下):
    uv run python -m scripts.init_db

幂等:
- 表存在则跳过(create_all 默认行为)
- user_config 默认 key 已存在则跳过
"""

import logging
from typing import Any

from sqlalchemy import select

from src.db import SessionLocal, init_db
from src.models import UserConfig

logger = logging.getLogger(__name__)

# user_config 默认 key 与初值。单位严格遵循 R1 字段名后缀。
# 阈值仅为占位,用户应在 Settings 页调整。
DEFAULT_USER_CONFIG: dict[str, Any] = {
    "alert_thresholds": {
        # 板块主力净流入 ≥ 5 亿元(=50000 万元)触发利好信号
        # 5 亿元 = 50000 万元 × 10000(WAN_YUAN_SCALE) = 500_000_000
        "sector_main_inflow_wan_x10000": 500_000_000,
        # 持仓基金当日跌幅 ≤ -3% 触发预警(-3% × 10000 = -300)
        "fund_daily_return_x10000_drop": -300,
    },
    # 用户关注的板块代码列表(例如 ["BK0428", "801080"])
    "focus_sectors": [],
    # 推送时刻覆盖。空表示用默认 8:30 / 14:00 / 21:00
    "push_schedule_overrides": {},
}


def seed_user_config() -> None:
    with SessionLocal() as session:
        for key, value in DEFAULT_USER_CONFIG.items():
            exists = session.scalar(select(UserConfig).where(UserConfig.key == key))
            if exists is not None:
                logger.info("user_config[%s] already exists, skip", key)
                continue
            session.add(UserConfig(key=key, value=value))
            logger.info("user_config[%s] seeded", key)
        session.commit()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    logger.info("creating tables...")
    init_db()
    logger.info("tables ready")
    seed_user_config()
    logger.info("done")


if __name__ == "__main__":
    main()

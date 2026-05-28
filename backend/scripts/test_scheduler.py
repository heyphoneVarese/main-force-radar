"""手动触发任意 scheduler job — 验证流程不等 cron。

用法(在 backend/ 目录下):
    # 触发全部 4 个 job,真实推送(微信会收到 4 条!)
    uv run python -m scripts.test_scheduler

    # 触发全部 job,只跑信号 + AI + 渲染预览,不真推送
    uv run python -m scripts.test_scheduler --mock

    # 只跑某个 job
    uv run python -m scripts.test_scheduler --job pre_market
    uv run python -m scripts.test_scheduler --job intraday --mock
    uv run python -m scripts.test_scheduler --job close
    uv run python -m scripts.test_scheduler --job weekly

job_id 取值:pre_market / intraday / close / weekly
"""

import argparse
import logging
from unittest.mock import patch

from src.services.scheduler import JOBS_CONFIG, SignalScheduler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mock",
        action="store_true",
        help="跳过真实 Server酱 推送,只跑信号+AI+渲染预览",
    )
    parser.add_argument(
        "--job",
        choices=[c["job_id"] for c in JOBS_CONFIG] + ["daily_fetch", "all"],
        default="all",
        help="指定要跑的 job(默认 all = 4 个推送 job;daily_fetch 单独触发)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    sched = SignalScheduler()

    # daily_fetch 是采集 job,不发推送,单独处理
    if args.job == "daily_fetch":
        if args.mock:
            print("⚠️  daily_fetch 不支持 --mock(它只采集 akshare,不推送),直接跑真采集")
        print("\n" + "=" * 72)
        print("触发 job: daily_fetch (data collection, no push)")
        print("=" * 72)
        sched._run_fetch_job()
        print("\ntest_scheduler 完成")
        return

    targets = (
        JOBS_CONFIG
        if args.job == "all"
        else [c for c in JOBS_CONFIG if c["job_id"] == args.job]
    )

    for config in targets:
        print()
        print("=" * 72)
        print(
            f"触发 job: {config['job_id']:<12} "
            f"push_type={config['push_type']:<8} "
            f"cron={config['cron']}"
        )
        print("=" * 72)

        if args.mock:
            # 用 patch 拦截 notifier.send,让 _run_push_job 跑完 4 步但不发请求
            captured = {}

            def _fake_send(self, title: str, content: str) -> bool:
                captured["title"] = title
                captured["content"] = content
                return True

            with patch(
                "src.services.notifier.ServerChanNotifier.send",
                _fake_send,
            ):
                sched._run_push_job(
                    push_type=config["push_type"],
                    title_label=config["title_label"],
                    macro_context=config["macro_context"],
                )

            if "title" in captured:
                print(f"\n[MOCK] 标题:{captured['title']}")
                print(f"[MOCK] 长度:{len(captured['content'])} 字符 (没真发)")
                print("[MOCK] === 完整 markdown 内容(下方)===")
                print(captured["content"])
                print("[MOCK] === 内容结束 ===")
            else:
                print("\n[MOCK] notifier.send 未被调用(SERVER_CHAN_SCKEY 未配置)")
        else:
            sched._run_push_job(
                push_type=config["push_type"],
                title_label=config["title_label"],
                macro_context=config["macro_context"],
            )

    print()
    print("test_scheduler 完成")


if __name__ == "__main__":
    main()

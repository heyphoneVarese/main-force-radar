"""一次性批量导入用户真实持仓数据。

用法(在 backend/ 目录下):
    # 1. 编辑本文件,把 HOLDINGS 列表填进去
    # 2. 跑:
    uv run python -m scripts.import_my_holdings

特点:
- 直接调 service 层,不走 HTTP(更快,绕开网络)
- 单条失败:打印原因继续,不中断整批
- 字段校验:
    fund_code 必须在 funds 表存在(强 FK,与 POST /api/holdings 一致)
    cost_nav  > 0(用 nav_to_int 转 cost_nav_x10000,银行家舍入)
    shares    > 0(用 shares_to_int 转 shares_x100)
    bought_at 不能晚于今天
- 幂等:同 fund_code 已有 holding → 跳过(D2: 1 基金 1 持仓)
- 成功的逐条 commit,失败的不影响后续
"""

from datetime import date
from typing import Any

from src.db import SessionLocal
from src.models import Fund, Holding
from src.utils.date_helper import cn_today
from src.utils.fund_code import is_valid_fund_code
from src.utils.money import nav_to_int, shares_to_int


# =============================================================
# 用户真实持仓 — 在这里填数据。空列表跑脚本会提示但不报错。
#
# 字段说明:
#   fund_code  6 位数字字符串,必须先在 funds 表存在
#              (运行 scripts/seed_funds.py 后已有 52 只)
#   cost_nav   持仓成本净值(元),Decimal 字符串(避免 float 精度)
#              例 "1.5234" → 内部存 cost_nav_x10000 = 15234
#   shares     持仓份额,Decimal 字符串
#              例 "1000.5" → 内部存 shares_x100 = 100050
#   bought_at  建仓日 "YYYY-MM-DD",不能晚于今天
#   note       备注,可为 None
#
# 样例(2 行,真填的时候把样例删掉):
#   {"fund_code": "022365", "cost_nav": "2.3456", "shares": "500.5",
#    "bought_at": "2025-12-15", "note": "CPO 主线"},
#   {"fund_code": "008281", "cost_nav": "1.2345", "shares": "2000",
#    "bought_at": "2026-01-10", "note": None},
# =============================================================
HOLDINGS: list[dict[str, Any]] = [
    {"fund_code": "008281", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "半导体"},
    {"fund_code": "014320", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "半导体"},
    {"fund_code": "018412", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "半导体"},
    {"fund_code": "007343", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "半导体"},
    {"fund_code": "009707", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "半导体"},
    {"fund_code": "016238", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "半导体"},
    {"fund_code": "005312", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "半导体"},
    {"fund_code": "019455", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "中韩半导体"},
    {"fund_code": "017811", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "半导体材料"},
    {"fund_code": "006502", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "CPO"},
    {"fund_code": "022365", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "CPO"},
    {"fund_code": "017103", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "CPO"},
    {"fund_code": "110029", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "5G通信"},
    {"fund_code": "001323", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "5G通信"},
    {"fund_code": "000979", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "5G通信"},
    {"fund_code": "000698", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "5G通信"},
    {"fund_code": "002771", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "5G通信"},
    {"fund_code": "007817", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "通信设备"},
    {"fund_code": "011891", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "通信技术"},
    {"fund_code": "016371", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "通信技术"},
    {"fund_code": "004320", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "通信技术"},
    {"fund_code": "008528", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "通信技术"},
    {"fund_code": "001513", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "AI"},
    {"fund_code": "017484", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "AI"},
    {"fund_code": "025505", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "AI"},
    {"fund_code": "020973", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "机器人"},
    {"fund_code": "001072", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "智能装备"},
    {"fund_code": "024195", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "商业航天"},
    {"fund_code": "025491", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "商业航天"},
    {"fund_code": "014002", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "海外科技"},
    {"fund_code": "016702", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "海外科技"},
    {"fund_code": "017731", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "全球科技"},
    {"fund_code": "161125", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "标普500"},
    {"fund_code": "019172", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "纳指100"},
    {"fund_code": "012920", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "全球精选"},
    {"fund_code": "012922", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "全球精选"},
    {"fund_code": "021189", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "亚太"},
    {"fund_code": "007028", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "中证500"},
    {"fund_code": "007339", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "沪深300"},
    {"fund_code": "023891", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "科创板"},
    {"fund_code": "023998", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "科创板"},
    {"fund_code": "023902", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "科创板"},
    {"fund_code": "002862", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "中盘股"},
    {"fund_code": "023638", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "电网设备"},
    {"fund_code": "012929", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "光伏"},
    {"fund_code": "011967", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "光伏"},
    {"fund_code": "016567", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "电池"},
    {"fund_code": "006122", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "锂电池"},
    {"fund_code": "021363", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "黄金股"},
    {"fund_code": "002963", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "黄金"},
    {"fund_code": "011393", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "债券"},
    {"fund_code": "011826", "cost_nav": "1.0000", "shares": "10000", "bought_at": "2025-01-01", "note": "港股创新药"},
]


def import_one(session, entry: dict[str, Any]) -> tuple[bool, str]:
    """校验 + 添加一条到 session(未 commit)。返回 (success, message)。

    Caller 负责在 success=True 时 commit。失败时本函数保证未污染 session
    (要么根本没 add,要么由 caller rollback)。
    """
    code = entry.get("fund_code", "")
    if not is_valid_fund_code(code):
        return False, f"fund_code 格式非法: {code!r}"

    if session.get(Fund, code) is None:
        return False, f"fund_code {code} 不在 funds 表(先跑 seed_funds.py)"

    if session.query(Holding).filter_by(fund_code=code).first() is not None:
        return False, "已有 holding,跳过(D2: 1 基金 1 持仓)"

    # 字段解析 + 转换
    try:
        cost_nav_x10000 = nav_to_int(entry["cost_nav"])
        shares_x100 = shares_to_int(entry["shares"])
        bought_at = date.fromisoformat(entry["bought_at"])
        note = entry.get("note")
    except KeyError as e:
        return False, f"缺字段: {e}"
    except Exception as e:
        return False, f"字段解析失败: {type(e).__name__}: {e}"

    if cost_nav_x10000 <= 0:
        return False, f"cost_nav 必须 > 0: {entry['cost_nav']}"
    if shares_x100 <= 0:
        return False, f"shares 必须 > 0: {entry['shares']}"
    if bought_at > cn_today():
        return False, f"bought_at 不能晚于今天: {entry['bought_at']}"

    session.add(
        Holding(
            fund_code=code,
            cost_nav_x10000=cost_nav_x10000,
            shares_x100=shares_x100,
            bought_at=bought_at,
            note=note,
        )
    )
    return True, ""


def main() -> None:
    total = len(HOLDINGS)
    if total == 0:
        print(
            "⚠️  HOLDINGS 列表是空的,没东西可导入。\n"
            "    请先编辑 backend/scripts/import_my_holdings.py,在 HOLDINGS 列表里贴数据。"
        )
        return

    width = len(str(total))
    success = 0
    failed: list[tuple[str, str]] = []

    with SessionLocal() as session:
        for i, entry in enumerate(HOLDINGS, start=1):
            code = entry.get("fund_code", "<missing>")
            ok, msg = import_one(session, entry)
            if ok:
                try:
                    session.commit()
                    success += 1
                    print(f"[{i:>{width}}/{total}] {code} ✅")
                except Exception as e:
                    session.rollback()
                    failed.append((code, f"commit 失败: {type(e).__name__}: {e}"))
                    print(f"[{i:>{width}}/{total}] {code} ❌ commit 失败: {e}")
            else:
                # import_one 失败前没 add,不需要 rollback;
                # 但如果之前查询打开了未关 transaction,保险起见 rollback
                session.rollback()
                failed.append((code, msg))
                print(f"[{i:>{width}}/{total}] {code} ❌ {msg}")

    print()
    print("=" * 60)
    print(f"导入完成:成功 {success}/{total},失败 {len(failed)}")
    if failed:
        print("\n失败明细:")
        for code, reason in failed:
            print(f"  - {code}: {reason}")


if __name__ == "__main__":
    main()

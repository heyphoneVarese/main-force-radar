"""一次性 UPDATE 用户真实持仓(42 条,从手机 APP 截图 OCR 提取)。

跑法(VPS 容器内):
    docker compose exec backend uv run --no-dev python -m scripts.import_real_holdings

行为:
- 对 REAL_HOLDINGS 里 42 条:UPDATE holdings 表
    cost_nav_x10000 = nav_to_int(cost_nav)   # 银行家舍入,R1 整数
    shares_x100     = shares_to_int(shares)
    updated_at      = cn_now()
- 对 holdings 表里有但 REAL_HOLDINGS 里没有的 N 条:归零(留底)
    cost_nav_x10000 = 0, shares_x100 = 0
  (NOT NULL 约束允许 0,只禁止 NULL;0 = "曾持有,已清空")
- 对 REAL_HOLDINGS 里有但 holdings 表里没有的 M 条:打 warning 跳过,
  让用户决定是先 funds 入库 + INSERT,还是从 PDF 数据里删掉。

幂等:跑多次结果一致(UPDATE 是覆盖,归零是覆盖)。
"""

from typing import Any

from src.db import SessionLocal
from src.models import Holding
from src.utils.date_helper import cn_now
from src.utils.money import nav_to_int, shares_to_int

# =====================================================================
# 42 条真实持仓 — 2026-05-28 OCR 提取(用户已 review 过小数点)
#
# 字段:
#   fund_code  6 位字符串
#   cost_nav   持仓成本价(元),字符串避免 float 精度
#   shares     持有份额,字符串
# =====================================================================
REAL_HOLDINGS: list[dict[str, Any]] = [
    {"fund_code": "023902", "cost_nav": "1.2608", "shares": "2854.93"},
    {"fund_code": "002963", "cost_nav": "3.0544", "shares": "16376.36"},
    {"fund_code": "016371", "cost_nav": "2.3707", "shares": "8691.83"},
    {"fund_code": "012733", "cost_nav": "1.8034", "shares": "2849.69"},
    {"fund_code": "007343", "cost_nav": "3.4119", "shares": "1541.90"},
    {"fund_code": "004320", "cost_nav": "3.6278", "shares": "532.57"},
    {"fund_code": "006479", "cost_nav": "7.1676", "shares": "212.73"},
    {"fund_code": "017811", "cost_nav": "2.8492", "shares": "14218.27"},
    {"fund_code": "161125", "cost_nav": "2.8686", "shares": "728.58"},
    {"fund_code": "001072", "cost_nav": "3.9303", "shares": "1396.14"},
    {"fund_code": "007339", "cost_nav": "1.8742", "shares": "4791.48"},
    {"fund_code": "001323", "cost_nav": "6.6881", "shares": "2988.86"},
    {"fund_code": "005312", "cost_nav": "1.6389", "shares": "2217.11"},
    {"fund_code": "019455", "cost_nav": "1.9921", "shares": "1977.86"},
    {"fund_code": "001513", "cost_nav": "6.3597", "shares": "2333.03"},
    {"fund_code": "007028", "cost_nav": "1.9188", "shares": "10833.35"},
    {"fund_code": "020973", "cost_nav": "1.4807", "shares": "6273.08"},
    {"fund_code": "023891", "cost_nav": "1.5598", "shares": "48118.62"},
    {"fund_code": "017484", "cost_nav": "1.8949", "shares": "982.92"},
    {"fund_code": "012922", "cost_nav": "3.0930", "shares": "782.41"},
    {"fund_code": "025505", "cost_nav": "1.4436", "shares": "3463.46"},
    {"fund_code": "019172", "cost_nav": "1.5328", "shares": "945.97"},
    {"fund_code": "011891", "cost_nav": "2.5439", "shares": "1927.86"},
    {"fund_code": "021189", "cost_nav": "1.3238", "shares": "7067.46"},
    {"fund_code": "023998", "cost_nav": "1.4188", "shares": "6668.02"},
    {"fund_code": "016665", "cost_nav": "3.1460", "shares": "413.22"},
    {"fund_code": "006502", "cost_nav": "4.6236", "shares": "1381.61"},
    {"fund_code": "016238", "cost_nav": "1.6611", "shares": "1381.22"},
    {"fund_code": "012920", "cost_nav": "2.5362", "shares": "8710.98"},
    {"fund_code": "008281", "cost_nav": "2.3070", "shares": "47673.20"},
    {"fund_code": "023638", "cost_nav": "1.9595", "shares": "6452.62"},
    {"fund_code": "014002", "cost_nav": "2.7775", "shares": "3312.39"},
    {"fund_code": "014320", "cost_nav": "2.5321", "shares": "34672.34"},
    {"fund_code": "001361", "cost_nav": "1.2067", "shares": "3637.72"},
    {"fund_code": "006555", "cost_nav": "3.6096", "shares": "221.63"},
    {"fund_code": "017103", "cost_nav": "3.7511", "shares": "1512.55"},
    {"fund_code": "016702", "cost_nav": "1.6784", "shares": "670.26"},
    {"fund_code": "009707", "cost_nav": "3.4033", "shares": "2081.69"},
    {"fund_code": "004450", "cost_nav": "2.2536", "shares": "1335.18"},
    {"fund_code": "000979", "cost_nav": "3.8123", "shares": "2127.96"},
    {"fund_code": "018412", "cost_nav": "1.5414", "shares": "1749.57"},
    {"fund_code": "022365", "cost_nav": "5.4083", "shares": "3812.62"},
]


def run(session) -> dict[str, list[str]]:
    """主逻辑。返回 stats dict(便于单测断言)。

    stats keys:
        updated   — UPDATE 成功的 code 列表
        zeroed    — 归零留底的 code 列表(holdings 有但 REAL_HOLDINGS 没有)
        unmatched — 跳过的 code 列表(REAL_HOLDINGS 有但 holdings 没有)
    """
    real_by_code: dict[str, dict[str, Any]] = {h["fund_code"]: h for h in REAL_HOLDINGS}
    existing: list[Holding] = session.query(Holding).all()
    existing_codes: set[str] = {h.fund_code for h in existing}

    updated: list[str] = []
    zeroed: list[str] = []
    unmatched: list[str] = []
    now = cn_now()

    # 1) holdings 表里每条:有 PDF 数据就 UPDATE,没有就归零
    for h in existing:
        if h.fund_code in real_by_code:
            entry = real_by_code[h.fund_code]
            h.cost_nav_x10000 = nav_to_int(entry["cost_nav"])
            h.shares_x100 = shares_to_int(entry["shares"])
            h.updated_at = now
            updated.append(h.fund_code)
        else:
            h.cost_nav_x10000 = 0
            h.shares_x100 = 0
            h.updated_at = now
            zeroed.append(h.fund_code)

    # 2) PDF 里有但 holdings 没有 — 跳过,只记 warning
    for code in real_by_code:
        if code not in existing_codes:
            unmatched.append(code)

    session.commit()
    return {"updated": updated, "zeroed": zeroed, "unmatched": unmatched}


def main() -> None:
    with SessionLocal() as session:
        stats = run(session)

    print("=" * 60)
    print("📊 import_real_holdings 完成:")
    print(f"  ✅ updated   : {len(stats['updated'])} 条")
    print(f"  🪦 zeroed    : {len(stats['zeroed'])} 条(历史留底)")
    print(f"  ⚠️  unmatched : {len(stats['unmatched'])} 条(PDF 有 / holdings 无,已跳过)")
    print("=" * 60)

    if stats["zeroed"]:
        print("\n归零明细(holdings 表里有,PDF 没有,已归零):")
        for code in sorted(stats["zeroed"]):
            print(f"  {code}")

    if stats["unmatched"]:
        print("\n⚠️  以下 code 在 PDF 里但不在 holdings 表(已跳过):")
        for code in sorted(stats["unmatched"]):
            print(f"  {code}")
        print(
            "\n  要导入这些,需先在 funds 表登记 + 在 import_my_holdings.py 加占位,"
            "再跑一次本脚本。"
        )


if __name__ == "__main__":
    main()

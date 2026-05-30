"""VPS 诊断脚本 — 直接打东财 push2,把网络真相暴露出来。

跑法:
    docker compose exec backend uv run --no-dev python -m scripts.probe_eastmoney

输出涵盖:
  1. 容器内 data_fetcher 模块版本指纹(确认是不是新代码)
  2. DNS 解析(看 push2 / push2delay 解到哪)
  3. 4 种 UA × 是否带 Referer 的组合,逐一打 status/final URL/body 前 300 字符
  4. 一次完整的 fetch_sector_flow_industry() 走 data_fetcher 路径,带日志

根据输出判定:
  - HTTP 200 + JSON: 直连正常,问题在别处
  - HTTP 302 但 final URL 又是 push2delay 200: 跟随重定向 OK
  - HTTP 4xx/5xx: 东财对 VPS IP 风控/限流
  - 连不上 / SSL 错: 阿里云 NAT 出口被屏蔽
  - RemoteDisconnected: 东财半开 reset(就是用户报的症状)
"""

from __future__ import annotations

import json
import logging
import socket
import sys
import time
from typing import Any

import requests

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("probe")


# =====================================================================
# 0. 容器代码版本指纹
# =====================================================================
def fingerprint_module() -> None:
    print("=" * 70)
    print("📦 data_fetcher 模块指纹")
    print("=" * 70)
    from src.services import data_fetcher as df_mod

    has_direct = hasattr(df_mod, "_fetch_sector_flow_direct")
    has_const = hasattr(df_mod, "EASTMONEY_CLIST_URL")
    print(f"  _fetch_sector_flow_direct 函数存在: {has_direct}")
    print(f"  EASTMONEY_CLIST_URL 常量存在    : {has_const}")
    if has_const:
        print(f"  EASTMONEY_CLIST_URL = {df_mod.EASTMONEY_CLIST_URL}")
        print(f"  BROWSER_UA          = {df_mod.BROWSER_UA[:60]}...")
        print(f"  EASTMONEY_REFERER   = {df_mod.EASTMONEY_REFERER}")
    if not (has_direct and has_const):
        print()
        print("❌ 容器跑的是旧代码!")
        print("   修复: docker compose build --no-cache backend "
              "&& docker compose up -d backend")
        sys.exit(2)
    print("  ✅ 新代码已生效")


# =====================================================================
# 1. DNS 解析
# =====================================================================
def probe_dns() -> None:
    print()
    print("=" * 70)
    print("🌐 DNS 解析")
    print("=" * 70)
    for host in ("push2.eastmoney.com", "push2delay.eastmoney.com",
                 "data.eastmoney.com"):
        try:
            ips = socket.gethostbyname_ex(host)
            print(f"  {host:30s} → {ips[2]}")
        except Exception as e:
            print(f"  {host:30s} ❌ {type(e).__name__}: {e}")


# =====================================================================
# 2. 多组合直连测试
# =====================================================================
EASTMONEY_URL = "https://push2.eastmoney.com/api/qt/clist/get"
MODERN_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
OLD_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/81.0.4044.138 Safari/537.36"
)
REFERER = "https://data.eastmoney.com/bkzj/hy.html"

BASE_PARAMS: dict[str, Any] = {
    "pn": 1, "pz": 5, "po": 1, "np": 1,
    "ut": "b2884a393a59ad64002292a3e90d46a5",
    "fltt": 2, "invt": 2,
    "fid0": "f62",
    "fs": "m:90 t:2",
    "stat": 1,
    "fields": "f12,f14,f3,f62,f184",
    "rt": 52975239,
}


def _one_probe(label: str, headers: dict[str, str], use_session: bool,
               allow_redirects: bool) -> None:
    params = {**BASE_PARAMS, "_": int(time.time() * 1000)}
    try:
        if use_session:
            s = requests.Session()
            r = s.get(EASTMONEY_URL, params=params, headers=headers,
                      timeout=10, allow_redirects=allow_redirects)
            s.close()
        else:
            r = requests.get(EASTMONEY_URL, params=params, headers=headers,
                             timeout=10, allow_redirects=allow_redirects)
        body_preview = r.text[:300].replace("\n", " ")
        print(f"  [{label}]")
        print(f"    status        : {r.status_code}")
        print(f"    final url     : {r.url[:100]}")
        if r.status_code in (301, 302, 307, 308):
            print(f"    Location      : {r.headers.get('Location')}")
        print(f"    server header : {r.headers.get('Server')}")
        print(f"    body preview  : {body_preview[:200]}")
        # 试着解析 JSON 拿 total
        try:
            j = r.json()
            data = j.get("data") or {}
            print(f"    rc={j.get('rc')}  total={data.get('total')}")
        except Exception:
            pass
    except Exception as e:
        print(f"  [{label}]")
        print(f"    ❌ {type(e).__name__}: {e}")


def probe_http_combinations() -> None:
    print()
    print("=" * 70)
    print("🔍 HTTP 组合探针(看哪组能拿到 JSON)")
    print("=" * 70)

    combos = [
        ("A: Chrome120 + Referer + Connection:close + Session + 跟302",
         {"User-Agent": MODERN_UA, "Referer": REFERER,
          "Accept": "*/*", "Connection": "close"}, True, True),
        ("B: Chrome120 + Referer + 默认keep-alive + 不跟302",
         {"User-Agent": MODERN_UA, "Referer": REFERER, "Accept": "*/*"},
         False, False),
        ("C: Chrome81(akshare 原版)+ 无 Referer + 默认 + 跟 302",
         {"User-Agent": OLD_UA}, False, True),
        ("D: 裸 requests 默认 UA(无 Referer 无 Chrome)",
         {}, False, True),
    ]
    for label, headers, use_session, allow_redirects in combos:
        _one_probe(label, headers, use_session, allow_redirects)
        time.sleep(0.5)


# =====================================================================
# 3. 直接打 push2delay(绕过 302)
# =====================================================================
def probe_push2delay_direct() -> None:
    print()
    print("=" * 70)
    print("🎯 直接打 push2delay.eastmoney.com(绕过 push2 → push2delay 重定向)")
    print("=" * 70)
    url = "https://push2delay.eastmoney.com/api/qt/clist/get"
    params = {**BASE_PARAMS, "_": int(time.time() * 1000)}
    headers = {"User-Agent": MODERN_UA, "Referer": REFERER,
               "Accept": "*/*", "Connection": "close"}
    try:
        r = requests.get(url, params=params, headers=headers, timeout=10)
        print(f"  status: {r.status_code}")
        print(f"  body  : {r.text[:300]}")
        try:
            j = r.json()
            data = j.get("data") or {}
            print(f"  rc={j.get('rc')}  total={data.get('total')}")
        except Exception:
            pass
    except Exception as e:
        print(f"  ❌ {type(e).__name__}: {e}")


# =====================================================================
# 4. 走 data_fetcher 实际路径
# =====================================================================
def probe_via_data_fetcher() -> None:
    print()
    print("=" * 70)
    print("🚦 走 data_fetcher.fetch_sector_flow_industry() 实际路径(看完整日志)")
    print("=" * 70)
    from src.services.data_fetcher import fetch_sector_flow_industry

    rows = fetch_sector_flow_industry()
    print(f"  返回 {len(rows)} 行")
    if rows:
        print(f"  样本: {json.dumps(rows[0], default=str, ensure_ascii=False)}")


def main() -> None:
    fingerprint_module()
    probe_dns()
    probe_http_combinations()
    probe_push2delay_direct()
    probe_via_data_fetcher()
    print()
    print("=" * 70)
    print("👀 把上面整段输出贴回去 — 判定:")
    print("    - 有任何一组 status=200 且 rc=0 → 东财通,只是代码组合不对")
    print("    - 全部 302 但 final url 是 push2delay 200 → 跟随重定向 OK,代码漏洞")
    print("    - 全部 4xx/5xx → 阿里云 IP 被东财风控/限流")
    print("    - 全部 RemoteDisconnected → 东财对该出口 IP 半开 reset")
    print("    - DNS 解析失败 → 阿里云 DNS 屏蔽东财(改 /etc/resolv.conf)")
    print("=" * 70)


if __name__ == "__main__":
    main()

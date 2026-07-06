#!/usr/bin/env python3
"""
API 响应速度测试

对后端 API 进行响应时间基准测试。
前提条件: 后端服务已启动（默认 http://localhost:8000）

用法:
  python scripts/benchmark_api.py
  python scripts/benchmark_api.py --base-url http://localhost:8000 --rounds 10
"""

import sys
import os

# 提示: 请使用项目虚拟环境运行
# .venv/bin/python3 scripts/benchmark_api.py

import time
import json
import argparse
import urllib.request
import urllib.error

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# ── 测试 API 列表 ────────────────────────────────────────
# (方法, 路径, 请求体, 描述)
API_TESTS = [
    ("GET",  "/device/status",           None,                              "设备状态"),
    ("GET",  "/dashboard/stats",         None,                              "仪表盘统计"),
    ("GET",  "/garmin/overview",         None,                              "Garmin 健康数据"),
    ("GET",  "/medications?user_id=1",   None,                              "药品列表"),
    ("GET",  "/medical_cases?user_id=1", None,                              "病例列表"),
    ("GET",  "/device/reminders/today",  None,                              "今日提醒"),
    ("GET",  "/device/wake/info",        None,                              "唤醒状态"),
    ("POST", "/search_knowledge",        {"question": "高血压怎么办"},       "知识库搜索"),
    ("POST", "/device/intent/classify",  {"text": "帮我看看这个药"},         "意图分类"),
]

# 每个 API 默认测试轮数
DEFAULT_ROUNDS = 5


def _ms(seconds: float) -> float:
    """秒转毫秒，保留 1 位小数"""
    return round(seconds * 1000, 1)


def _request(base_url: str, method: str, path: str, body: dict = None,
             timeout: float = 30.0) -> dict:
    """
    发送 HTTP 请求，返回耗时和状态。

    Returns:
        {"ms": float, "status": int, "ok": bool, "error": str}
    """
    url = base_url.rstrip("/") + path
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, headers=headers, method=method)

    try:
        t0 = time.perf_counter()
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()  # 读完响应体
            elapsed = time.perf_counter() - t0
            return {
                "ms": _ms(elapsed),
                "status": resp.status,
                "ok": 200 <= resp.status < 400,
                "error": "",
            }
    except urllib.error.HTTPError as e:
        elapsed = time.perf_counter() - t0
        return {
            "ms": _ms(elapsed),
            "status": e.code,
            "ok": False,
            "error": f"HTTP {e.code}",
        }
    except urllib.error.URLError as e:
        elapsed = time.perf_counter() - t0
        return {
            "ms": _ms(elapsed),
            "status": 0,
            "ok": False,
            "error": str(e.reason),
        }
    except Exception as e:
        elapsed = time.perf_counter() - t0
        return {
            "ms": _ms(elapsed),
            "status": 0,
            "ok": False,
            "error": str(e),
        }


def _check_server(base_url: str) -> bool:
    """检查后端服务是否可达"""
    try:
        req = urllib.request.Request(base_url.rstrip("/") + "/docs", method="GET")
        with urllib.request.urlopen(req, timeout=5):
            return True
    except Exception:
        # 再试根路径
        try:
            req = urllib.request.Request(base_url.rstrip("/") + "/", method="GET")
            with urllib.request.urlopen(req, timeout=5):
                return True
        except Exception:
            return False


def bench_api(base_url: str, method: str, path: str, body: dict,
              description: str, rounds: int) -> dict:
    """
    对单个 API 执行多轮测试。

    Returns:
        {
            "method": str, "path": str, "description": str,
            "rounds": int, "results": [...],
            "avg_ms": float, "min_ms": float, "max_ms": float,
            "success_rate": float, "errors": [...]
        }
    """
    results = []
    errors = []

    for i in range(rounds):
        r = _request(base_url, method, path, body)
        results.append(r)
        if not r["ok"] and r["error"]:
            errors.append(f"第{i + 1}轮: {r['error']}")

    ms_list = [r["ms"] for r in results]
    ok_count = sum(1 for r in results if r["ok"])

    return {
        "method": method,
        "path": path,
        "description": description,
        "rounds": rounds,
        "results": results,
        "avg_ms": round(sum(ms_list) / len(ms_list), 1) if ms_list else 0,
        "min_ms": round(min(ms_list), 1) if ms_list else 0,
        "max_ms": round(max(ms_list), 1) if ms_list else 0,
        "success_rate": round(ok_count / rounds * 100, 1) if rounds > 0 else 0,
        "errors": errors,
    }


# ── 主函数 ────────────────────────────────────────────────
def main() -> dict:
    """
    执行 API 响应速度测试，返回汇总结果 dict。

    Returns:
        {
            "benchmark": "api",
            "base_url": str,
            "rounds": int,
            "tests": [...],
            "overall_avg_ms": float
        }
    """
    parser = argparse.ArgumentParser(description="API 响应速度测试")
    parser.add_argument(
        "--base-url", default="http://localhost:8000",
        help="后端服务地址 (默认 http://localhost:8000)",
    )
    parser.add_argument(
        "--rounds", type=int, default=DEFAULT_ROUNDS,
        help=f"每个 API 测试轮数 (默认 {DEFAULT_ROUNDS})",
    )
    args = parser.parse_args()

    base_url = args.base_url
    rounds = args.rounds

    print("=" * 60)
    print("  API 响应速度测试 (API Benchmark)")
    print("=" * 60)
    print(f"  后端地址: {base_url}")
    print(f"  测试轮数: {rounds}")
    print()

    # 检查服务是否可达
    print("检查后端服务...", end=" ")
    if not _check_server(base_url):
        print("✗ 无法连接！")
        print(f"  请确保后端服务已启动: {base_url}")
        print("  启动命令: cd backend && uvicorn main:app --host 0.0.0.0 --port 8000")
        return {
            "benchmark": "api",
            "base_url": base_url,
            "rounds": rounds,
            "tests": [],
            "overall_avg_ms": 0,
            "error": "后端服务不可达",
        }
    print("✓ 已连接")
    print()

    # 执行测试
    test_results = []
    for i, (method, path, body, desc) in enumerate(API_TESTS):
        label = f"[{i + 1}/{len(API_TESTS)}] {method:4} {path}"
        print(f"{label:50}", end=" ")
        r = bench_api(base_url, method, path, body, desc, rounds)
        test_results.append(r)

        status = "✓" if r["success_rate"] == 100 else f"✗ ({r['success_rate']}%)"
        print(f"avg={r['avg_ms']:>7.1f}ms  min={r['min_ms']:>7.1f}ms  max={r['max_ms']:>7.1f}ms  {status}")

        # 显示错误信息
        if r["errors"]:
            for err in r["errors"][:2]:  # 最多显示 2 条
                print(f"  {'':50} ⚠ {err}")

    # 汇总
    all_avgs = [r["avg_ms"] for r in test_results if r["success_rate"] > 0]
    overall_avg = round(sum(all_avgs) / len(all_avgs), 1) if all_avgs else 0

    # ── 打印 Markdown 表格 ──
    print(f"\n{'=' * 60}")
    print("  汇总结果 (Markdown)")
    print("=" * 60)
    print()
    print("| API | 描述 | 平均(ms) | 最小(ms) | 最大(ms) | 成功率 |")
    print("|-----|------|---------|---------|---------|--------|")
    for r in test_results:
        api = f"`{r['method']} {r['path']}`"
        print(f"| {api} | {r['description']} | {r['avg_ms']:.1f} | {r['min_ms']:.1f} | {r['max_ms']:.1f} | {r['success_rate']}% |")

    print(f"\n**所有 API 平均响应时间: {overall_avg:.1f}ms**")
    print()

    return {
        "benchmark": "api",
        "base_url": base_url,
        "rounds": rounds,
        "tests": test_results,
        "overall_avg_ms": overall_avg,
    }


if __name__ == "__main__":
    main()

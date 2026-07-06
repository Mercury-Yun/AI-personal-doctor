#!/usr/bin/env python3
"""
系统资源监控基准测试

采集 CPU / 内存 / Swap / 磁盘 / 温度 / NPU / 系统负载等信息。
支持单次快照和持续监控两种模式。

用法:
  python scripts/benchmark_system.py              # 单次快照
  python scripts/benchmark_system.py --monitor 30  # 持续监控 30 秒
"""

import sys
import os

# 提示: 请使用项目虚拟环境运行
# .venv/bin/python3 scripts/benchmark_system.py

import time
import argparse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))


# ── CPU 使用率（通过 /proc/stat 计算）────────────────────
def _read_cpu_times() -> dict:
    """读取 /proc/stat，返回各核心的 CPU 时间"""
    result = {}
    try:
        with open("/proc/stat", "r") as f:
            for line in f:
                if not line.startswith("cpu"):
                    continue
                parts = line.split()
                name = parts[0]  # "cpu", "cpu0", "cpu1", ...
                # user, nice, system, idle, iowait, irq, softirq, steal
                times = [int(x) for x in parts[1:9]]
                total = sum(times)
                idle = times[3] + times[4]  # idle + iowait
                result[name] = {"total": total, "idle": idle}
    except Exception:
        pass
    return result


def _calc_cpu_usage(before: dict, after: dict) -> dict:
    """根据两次采样计算 CPU 使用率"""
    usage = {}
    for name in after:
        if name not in before:
            continue
        d_total = after[name]["total"] - before[name]["total"]
        d_idle = after[name]["idle"] - before[name]["idle"]
        if d_total > 0:
            usage[name] = round((1.0 - d_idle / d_total) * 100, 1)
        else:
            usage[name] = 0.0
    return usage


def get_cpu_usage(interval: float = 0.5) -> dict:
    """采样 CPU 使用率，返回 {cpu: 整体%, cpu0: 核心0%, ...}"""
    before = _read_cpu_times()
    time.sleep(interval)
    after = _read_cpu_times()
    return _calc_cpu_usage(before, after)


# ── 内存信息 ──────────────────────────────────────────────
def get_memory_info() -> dict:
    """读取 /proc/meminfo，返回内存信息（单位: MB）"""
    info = {}
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                parts = line.split()
                key = parts[0].rstrip(":")
                val_kb = int(parts[1])
                info[key] = val_kb
    except Exception:
        return {"error": "无法读取 /proc/meminfo"}

    total = info.get("MemTotal", 0)
    free = info.get("MemFree", 0)
    available = info.get("MemAvailable", 0)
    buffers = info.get("Buffers", 0)
    cached = info.get("Cached", 0)
    used = total - free - buffers - cached

    swap_total = info.get("SwapTotal", 0)
    swap_free = info.get("SwapFree", 0)
    swap_used = swap_total - swap_free

    return {
        "total_mb": round(total / 1024, 1),
        "used_mb": round(used / 1024, 1),
        "available_mb": round(available / 1024, 1),
        "buffers_mb": round(buffers / 1024, 1),
        "cached_mb": round(cached / 1024, 1),
        "swap_total_mb": round(swap_total / 1024, 1),
        "swap_used_mb": round(swap_used / 1024, 1),
        "swap_free_mb": round(swap_free / 1024, 1),
    }


# ── 磁盘使用 ──────────────────────────────────────────────
def get_disk_usage() -> list:
    """获取主要挂载点的磁盘使用信息"""
    disks = []
    try:
        with open("/proc/mounts", "r") as f:
            mounts = f.readlines()
    except Exception:
        return [{"error": "无法读取 /proc/mounts"}]

    seen = set()
    for line in mounts:
        parts = line.split()
        device, mountpoint = parts[0], parts[1]
        # 只关注真实文件系统
        if not device.startswith("/dev/"):
            continue
        if device in seen:
            continue
        seen.add(device)
        try:
            stat = os.statvfs(mountpoint)
            total = stat.f_blocks * stat.f_frsize
            free = stat.f_bfree * stat.f_frsize
            used = total - free
            if total > 0:
                disks.append({
                    "device": device,
                    "mount": mountpoint,
                    "total_gb": round(total / (1024 ** 3), 2),
                    "used_gb": round(used / (1024 ** 3), 2),
                    "free_gb": round(free / (1024 ** 3), 2),
                    "usage_pct": round(used / total * 100, 1),
                })
        except Exception:
            continue

    return disks if disks else [{"error": "未找到挂载的磁盘"}]


# ── 系统温度 ──────────────────────────────────────────────
def get_temperatures() -> list:
    """从 /sys/class/thermal/thermal_zone*/temp 读取温度"""
    temps = []
    thermal_base = "/sys/class/thermal"
    if not os.path.isdir(thermal_base):
        return [{"zone": "N/A", "temp_c": 0, "error": "thermal 目录不存在"}]

    try:
        zones = sorted([
            d for d in os.listdir(thermal_base)
            if d.startswith("thermal_zone")
        ])
    except Exception:
        return [{"zone": "N/A", "temp_c": 0, "error": "无法列举 thermal_zone"}]

    for zone in zones:
        temp_path = os.path.join(thermal_base, zone, "temp")
        type_path = os.path.join(thermal_base, zone, "type")
        try:
            with open(temp_path, "r") as f:
                temp_raw = int(f.read().strip())
            temp_c = round(temp_raw / 1000, 1)
        except Exception:
            temp_c = None

        zone_type = "unknown"
        try:
            with open(type_path, "r") as f:
                zone_type = f.read().strip()
        except Exception:
            pass

        temps.append({
            "zone": zone,
            "type": zone_type,
            "temp_c": temp_c,
        })

    return temps if temps else [{"zone": "N/A", "temp_c": 0, "error": "未找到温度传感器"}]


# ── NPU 状态 ─────────────────────────────────────────────
def get_npu_status() -> dict:
    """尝试读取 RK3588 NPU 信息"""
    npu_paths = [
        "/sys/kernel/debug/rknpu/load",
        "/sys/kernel/debug/rknpu/freq",
        "/proc/rknpu",
    ]

    info = {"available": False, "details": {}}

    for path in npu_paths:
        try:
            with open(path, "r") as f:
                content = f.read().strip()
            if content:
                info["available"] = True
                key = os.path.basename(path)
                info["details"][key] = content[:200]
        except (PermissionError, FileNotFoundError, OSError):
            continue

    # 尝试读取 NPU 设备节点
    if os.path.exists("/dev/rknpu"):
        info["available"] = True
        info["details"]["device"] = "/dev/rknpu 存在"

    if not info["available"]:
        info["details"]["status"] = "NPU 信息不可用（可能需要 root 权限或驱动未加载）"

    return info


# ── 系统负载 ──────────────────────────────────────────────
def get_load_average() -> dict:
    """读取系统负载"""
    try:
        load1, load5, load15 = os.getloadavg()
        return {
            "load_1min": round(load1, 2),
            "load_5min": round(load5, 2),
            "load_15min": round(load15, 2),
        }
    except Exception:
        return {"error": "无法获取系统负载"}


# ── 单次快照 ──────────────────────────────────────────────
def snapshot() -> dict:
    """单次采集系统资源快照"""
    return {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cpu_usage": get_cpu_usage(interval=0.5),
        "memory": get_memory_info(),
        "disk": get_disk_usage(),
        "temperature": get_temperatures(),
        "npu": get_npu_status(),
        "load": get_load_average(),
    }


# ── 持续监控 ──────────────────────────────────────────────
def monitor(duration_sec: float = 60, interval: float = 1.0) -> dict:
    """
    持续监控系统资源，返回平均值和峰值。

    Args:
        duration_sec: 监控持续时间（秒）
        interval: 采样间隔（秒）

    Returns:
        包含平均值、峰值和所有采样点的 dict
    """
    print(f"开始持续监控 {duration_sec}s，采样间隔 {interval}s ...")

    samples = {
        "cpu_overall": [],
        "mem_used_mb": [],
        "mem_available_mb": [],
        "swap_used_mb": [],
        "temperatures": [],  # 最高温度
        "load_1min": [],
    }

    start = time.monotonic()
    sample_count = 0

    while time.monotonic() - start < duration_sec:
        t0 = time.monotonic()

        # CPU（短采样）
        cpu = get_cpu_usage(interval=min(0.3, interval * 0.5))
        mem = get_memory_info()
        temps = get_temperatures()
        load = get_load_average()

        samples["cpu_overall"].append(cpu.get("cpu", 0))
        samples["mem_used_mb"].append(mem.get("used_mb", 0))
        samples["mem_available_mb"].append(mem.get("available_mb", 0))
        samples["swap_used_mb"].append(mem.get("swap_used_mb", 0))

        # 最高温度
        valid_temps = [t["temp_c"] for t in temps if t.get("temp_c") is not None]
        max_temp = max(valid_temps) if valid_temps else 0
        samples["temperatures"].append(max_temp)
        samples["load_1min"].append(load.get("load_1min", 0))

        sample_count += 1
        elapsed = time.monotonic() - t0
        sleep_time = max(0, interval - elapsed)
        if sleep_time > 0:
            time.sleep(sleep_time)

    # 计算统计值
    stats = {}
    for key, values in samples.items():
        if not values:
            continue
        stats[key] = {
            "avg": round(sum(values) / len(values), 1),
            "min": round(min(values), 1),
            "max": round(max(values), 1),
            "last": round(values[-1], 1),
        }

    return {
        "benchmark": "system_monitor",
        "duration_sec": duration_sec,
        "interval_sec": interval,
        "sample_count": sample_count,
        "stats": stats,
    }


# ── 打印快照结果 ──────────────────────────────────────────
def _print_snapshot(data: dict) -> None:
    """将快照结果打印为 Markdown 表格"""

    # CPU
    cpu = data.get("cpu_usage", {})
    print("\n### CPU 使用率\n")
    print("| 核心 | 使用率(%) |")
    print("|------|---------|")
    overall = cpu.get("cpu", 0)
    print(f"| **整体** | **{overall}** |")
    for key in sorted(cpu.keys()):
        if key == "cpu":
            continue
        print(f"| {key} | {cpu[key]} |")

    # 内存
    mem = data.get("memory", {})
    print("\n### 内存\n")
    print("| 项目 | 值(MB) |")
    print("|------|--------|")
    for label, key in [
        ("总量", "total_mb"),
        ("已用", "used_mb"),
        ("可用", "available_mb"),
        ("缓存", "cached_mb"),
        ("Swap 总量", "swap_total_mb"),
        ("Swap 已用", "swap_used_mb"),
    ]:
        print(f"| {label} | {mem.get(key, 'N/A')} |")

    # 磁盘
    disks = data.get("disk", [])
    print("\n### 磁盘\n")
    print("| 设备 | 挂载点 | 总量(GB) | 已用(GB) | 使用率(%) |")
    print("|------|--------|---------|---------|----------|")
    for d in disks:
        if "error" in d:
            print(f"| - | - | - | - | {d['error']} |")
        else:
            print(f"| {d['device']} | {d['mount']} | {d['total_gb']} | {d['used_gb']} | {d['usage_pct']} |")

    # 温度
    temps = data.get("temperature", [])
    print("\n### 系统温度\n")
    print("| 区域 | 类型 | 温度(°C) |")
    print("|------|------|---------|")
    for t in temps:
        temp_val = t.get("temp_c", "N/A")
        if temp_val is None:
            temp_val = "N/A"
        print(f"| {t.get('zone', 'N/A')} | {t.get('type', 'N/A')} | {temp_val} |")

    # NPU
    npu = data.get("npu", {})
    print("\n### NPU 状态\n")
    if npu.get("available"):
        print("| 项目 | 值 |")
        print("|------|-----|")
        for k, v in npu.get("details", {}).items():
            # 多行值替换为单行
            v_oneline = v.replace("\n", " | ")
            print(f"| {k} | {v_oneline} |")
    else:
        status = npu.get("details", {}).get("status", "不可用")
        print(f"NPU 状态: {status}")

    # 负载
    load = data.get("load", {})
    print("\n### 系统负载\n")
    print("| 1 分钟 | 5 分钟 | 15 分钟 |")
    print("|--------|--------|---------|")
    print(f"| {load.get('load_1min', 'N/A')} | {load.get('load_5min', 'N/A')} | {load.get('load_15min', 'N/A')} |")


# ── 打印监控结果 ──────────────────────────────────────────
def _print_monitor(data: dict) -> None:
    """将持续监控结果打印为 Markdown 表格"""
    stats = data.get("stats", {})
    print(f"\n监控时长: {data['duration_sec']}s, 采样数: {data['sample_count']}")
    print()
    print("| 指标 | 平均值 | 最小值 | 最大值(峰值) | 最后值 |")
    print("|------|--------|--------|-------------|--------|")

    labels = {
        "cpu_overall": "CPU 使用率(%)",
        "mem_used_mb": "已用内存(MB)",
        "mem_available_mb": "可用内存(MB)",
        "swap_used_mb": "Swap 已用(MB)",
        "temperatures": "最高温度(°C)",
        "load_1min": "1分钟负载",
    }
    for key in ("cpu_overall", "mem_used_mb", "mem_available_mb", "swap_used_mb", "temperatures", "load_1min"):
        if key not in stats:
            continue
        s = stats[key]
        label = labels.get(key, key)
        print(f"| {label} | {s['avg']} | {s['min']} | {s['max']} | {s['last']} |")


# ── 主函数 ────────────────────────────────────────────────
def main() -> dict:
    """
    执行系统资源监控，返回结果 dict。

    Returns:
        {
            "benchmark": "system",
            "snapshot": {...},
            "monitor": {...} (如果指定了 --monitor)
        }
    """
    parser = argparse.ArgumentParser(description="系统资源监控基准测试")
    parser.add_argument(
        "--monitor", type=float, default=0,
        help="持续监控时长（秒），0 表示仅单次快照",
    )
    parser.add_argument(
        "--interval", type=float, default=1.0,
        help="监控采样间隔（秒）",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  系统资源监控 (System Benchmark)")
    print("=" * 60)

    # 单次快照
    print("\n── 系统快照 ──")
    snap = snapshot()
    _print_snapshot(snap)

    result = {
        "benchmark": "system",
        "snapshot": snap,
    }

    # 持续监控
    if args.monitor > 0:
        print(f"\n── 持续监控 ({args.monitor}s) ──")
        mon = monitor(duration_sec=args.monitor, interval=args.interval)
        _print_monitor(mon)
        result["monitor"] = mon

    print()
    return result


if __name__ == "__main__":
    main()

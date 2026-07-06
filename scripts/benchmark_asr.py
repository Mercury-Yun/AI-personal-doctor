#!/usr/bin/env python3
"""
ASR 性能 Benchmark 脚本

测试本地 Sherpa-ONNX SenseVoice ASR 的识别速度、准确率和资源占用。
用法: python scripts/benchmark_asr.py
"""

import sys
import os

# 提示: 请使用项目虚拟环境运行
# .venv/bin/python3 scripts/benchmark_asr.py

import time
import wave
import threading
from pathlib import Path

# 项目路径设置
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(PROJECT_ROOT))

# 测试音频目录
TEST_WAV_DIR = Path(
    "/home/elf/Qwen_test/sherpa/asr_sensevoice/"
    "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/test_wavs"
)

# 每个音频测试轮数
NUM_RUNS = 5

# 标准答案（用于计算 CER）
GROUND_TRUTH = {
    "zh.wav": "开放时间早上九点至下午五点",
}

# 数字归一化映射（阿拉伯数字 -> 中文数字）
_DIGIT_MAP = {
    "0": "零", "1": "一", "2": "二", "3": "三", "4": "四",
    "5": "五", "6": "六", "7": "七", "8": "八", "9": "九",
}


def _normalize_digits(text: str) -> str:
    """将阿拉伯数字转为中文数字，便于 CER 比较"""
    for d, c in _DIGIT_MAP.items():
        text = text.replace(d, c)
    return text


def _edit_distance(s1: str, s2: str) -> int:
    """计算两个字符串之间的编辑距离（Levenshtein）"""
    m, n = len(s1), len(s2)
    dp = list(range(n + 1))
    for i in range(1, m + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, n + 1):
            temp = dp[j]
            if s1[i - 1] == s2[j - 1]:
                dp[j] = prev
            else:
                dp[j] = 1 + min(prev, dp[j], dp[j - 1])
            prev = temp
    return dp[n]


def compute_cer(hypothesis: str, reference: str) -> float:
    """
    计算字符错误率 (CER)
    CER = edit_distance(hyp, ref) / len(ref)
    先进行数字归一化、去除空格和标点
    """
    import re
    # 归一化：去标点、空格，数字转中文
    def clean(t):
        t = _normalize_digits(t)
        t = re.sub(r"[，。、！？,.!?\s]", "", t)
        return t

    hyp = clean(hypothesis)
    ref = clean(reference)
    if not ref:
        return 0.0
    dist = _edit_distance(hyp, ref)
    return dist / len(ref)


def get_wav_duration_ms(wav_path: str) -> float:
    """读取 WAV 文件时长（毫秒）"""
    with wave.open(wav_path, "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
        return (frames / rate) * 1000.0


class PeakMemoryMonitor:
    """后台线程采样 /proc/self/status VmRSS，记录峰值内存（KB）"""

    def __init__(self, interval: float = 0.01):
        self._interval = interval
        self._peak_kb = 0
        self._running = False
        self._thread = None

    def _read_vmrss(self) -> int:
        """读取当前进程 VmRSS（KB）"""
        try:
            with open("/proc/self/status", "r") as f:
                for line in f:
                    if line.startswith("VmRSS:"):
                        return int(line.split()[1])
        except Exception:
            pass
        return 0

    def _sample_loop(self):
        while self._running:
            rss = self._read_vmrss()
            if rss > self._peak_kb:
                self._peak_kb = rss
            time.sleep(self._interval)

    def start(self):
        self._peak_kb = self._read_vmrss()
        self._running = True
        self._thread = threading.Thread(target=self._sample_loop, daemon=True)
        self._thread.start()

    def stop(self) -> int:
        """停止采样，返回峰值 RSS（KB）"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
        return self._peak_kb


def get_cpu_time_ms() -> float:
    """获取当前进程的 CPU 时间（毫秒），user + system"""
    t = os.times()
    return (t.user + t.system) * 1000.0


def benchmark_model_load() -> dict:
    """测试模型加载时间"""
    from backend.services.local_asr import asr_prewarm, _asr_prewarm_done, _asr_model

    # 如果模型已经加载，无法准确测量
    # 通过检查全局变量判断
    import backend.services.local_asr as asr_mod
    if asr_mod._asr_model is not None:
        return {"load_time_ms": -1, "note": "模型已加载，无法重新测量加载时间"}

    t0 = time.monotonic()
    thread = asr_prewarm()
    thread.join(timeout=60.0)
    t1 = time.monotonic()

    load_ms = (t1 - t0) * 1000.0
    return {"load_time_ms": round(load_ms, 2)}


def benchmark_single_wav(wav_path: str) -> dict:
    """
    对单个 WAV 文件进行多轮 benchmark 测试
    返回包含速度、RTF、内存等指标的 dict
    """
    from backend.services.local_asr import transcribe_wav

    wav_name = os.path.basename(wav_path)
    duration_ms = get_wav_duration_ms(wav_path)

    latencies = []
    cpu_usages = []
    texts = []
    peak_rss_kb = 0

    for i in range(NUM_RUNS):
        # 启动内存监控
        mem_mon = PeakMemoryMonitor(interval=0.005)
        mem_mon.start()

        cpu_before = get_cpu_time_ms()
        t0 = time.monotonic()

        result = transcribe_wav(wav_path)

        t1 = time.monotonic()
        cpu_after = get_cpu_time_ms()
        run_peak = mem_mon.stop()

        elapsed_ms = (t1 - t0) * 1000.0
        cpu_ms = cpu_after - cpu_before

        latencies.append(elapsed_ms)
        cpu_usages.append(cpu_ms)
        if run_peak > peak_rss_kb:
            peak_rss_kb = run_peak

        if result["ok"] and result["text"]:
            texts.append(result["text"])

    # 统计
    avg_ms = sum(latencies) / len(latencies)
    min_ms = min(latencies)
    max_ms = max(latencies)
    rtf = (avg_ms / duration_ms) if duration_ms > 0 else 0.0
    avg_cpu_ms = sum(cpu_usages) / len(cpu_usages)

    # CER 计算（如果有标准答案）
    cer = None
    if wav_name in GROUND_TRUTH and texts:
        # 取最后一次的识别结果计算 CER
        cer = compute_cer(texts[-1], GROUND_TRUTH[wav_name])

    return {
        "file": wav_name,
        "duration_ms": round(duration_ms, 2),
        "num_runs": NUM_RUNS,
        "avg_ms": round(avg_ms, 2),
        "min_ms": round(min_ms, 2),
        "max_ms": round(max_ms, 2),
        "rtf": round(rtf, 4),
        "avg_cpu_ms": round(avg_cpu_ms, 2),
        "peak_rss_mb": round(peak_rss_kb / 1024.0, 2),
        "cer": round(cer, 4) if cer is not None else None,
        "last_text": texts[-1] if texts else "",
    }


def run_benchmark() -> dict:
    """
    执行完整 ASR benchmark，返回结构化结果 dict
    """
    from backend.services.local_asr import is_asr_available

    results = {
        "module": "ASR (Sherpa-ONNX SenseVoice int8)",
        "model_load": None,
        "available": False,
        "files": [],
    }

    # 1. 模型加载时间
    print("=" * 60)
    print("  ASR Benchmark - Sherpa-ONNX SenseVoice (int8)")
    print("=" * 60)
    print()

    print("[1/3] 测量模型加载时间...")
    load_info = benchmark_model_load()
    results["model_load"] = load_info
    if load_info["load_time_ms"] > 0:
        print(f"  模型加载耗时: {load_info['load_time_ms']:.2f} ms")
    else:
        print(f"  模型已预加载，跳过加载时间测量")
    print()

    # 2. 检查 ASR 可用性
    if not is_asr_available():
        print("[错误] ASR 模型不可用，无法进行 benchmark")
        return results
    results["available"] = True

    # 3. 收集测试音频
    if not TEST_WAV_DIR.exists():
        print(f"[错误] 测试音频目录不存在: {TEST_WAV_DIR}")
        return results

    wav_files = sorted(TEST_WAV_DIR.glob("*.wav"))
    if not wav_files:
        print(f"[错误] 测试音频目录下无 WAV 文件: {TEST_WAV_DIR}")
        return results

    print(f"[2/3] 开始测试 {len(wav_files)} 个音频文件，每个 {NUM_RUNS} 轮...")
    print()

    # 4. 逐个音频 benchmark
    for wav_path in wav_files:
        wav_name = wav_path.name
        print(f"  测试: {wav_name} ...", end=" ", flush=True)
        try:
            info = benchmark_single_wav(str(wav_path))
            results["files"].append(info)
            rtf_str = f"RTF={info['rtf']:.4f}"
            cer_str = f"CER={info['cer']:.2%}" if info["cer"] is not None else ""
            print(f"平均 {info['avg_ms']:.1f}ms  {rtf_str}  {cer_str}")
        except Exception as e:
            print(f"失败: {e}")
            results["files"].append({"file": wav_name, "error": str(e)})

    print()

    # 5. 打印汇总表格
    print("[3/3] 结果汇总")
    print()
    _print_markdown_table(results)

    return results


def _print_markdown_table(results: dict):
    """打印 Markdown 格式的结果表格"""
    files = results.get("files", [])
    if not files:
        print("  无测试结果")
        return

    # 模型加载信息
    load_info = results.get("model_load", {})
    if load_info and load_info.get("load_time_ms", -1) > 0:
        print(f"**模型加载时间**: {load_info['load_time_ms']:.2f} ms")
        print()

    # 表头
    print("| 音频文件 | 时长(ms) | 平均耗时(ms) | 最小(ms) | 最大(ms) | RTF | 平均CPU(ms) | 峰值RSS(MB) | CER | 识别文本 |")
    print("|---------|---------|-------------|---------|---------|-----|------------|------------|-----|---------|")

    for f in files:
        if "error" in f:
            print(f"| {f['file']} | - | 错误: {f['error']} | - | - | - | - | - | - | - |")
            continue
        cer_str = f"{f['cer']:.2%}" if f.get("cer") is not None else "N/A"
        text_short = f["last_text"][:20] + "..." if len(f.get("last_text", "")) > 20 else f.get("last_text", "")
        print(
            f"| {f['file']} "
            f"| {f['duration_ms']:.1f} "
            f"| {f['avg_ms']:.2f} "
            f"| {f['min_ms']:.2f} "
            f"| {f['max_ms']:.2f} "
            f"| {f['rtf']:.4f} "
            f"| {f['avg_cpu_ms']:.2f} "
            f"| {f['peak_rss_mb']:.1f} "
            f"| {cer_str} "
            f"| {text_short} |"
        )


def main() -> dict:
    """入口函数，可独立运行也可被 run_all_benchmarks.py 调用"""
    try:
        results = run_benchmark()
    except Exception as e:
        print(f"\n[致命错误] ASR benchmark 失败: {e}")
        import traceback
        traceback.print_exc()
        results = {"module": "ASR", "error": str(e)}
    return results


if __name__ == "__main__":
    main()

"""
本地摄像头拍照模块（不依赖 demo）

支持：
- OpenCV（首选，如果可用）
- fswebcam 命令行（备选）

返回统一格式：{"ok": bool, "width": int, "height": int, "path": str, "error": str}
"""

import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional, Dict, Any

import logging
logger = logging.getLogger(__name__)


def _ensure_capture_dir() -> Path:
    """确保拍照临时目录存在"""
    capture_dir = Path("/tmp/ai_doctor_captures")
    capture_dir.mkdir(parents=True, exist_ok=True)
    return capture_dir


def capture_with_opencv(
    device_index: Optional[int] = None,
    width: int = 1280,
    height: int = 720,
    jpeg_quality: int = 90,
    timeout_sec: float = 5.0
) -> Dict[str, Any]:
    if device_index is None:
        device_index = int(os.getenv("CAMERA_DEVICE_INDEX", "0"))
    """
    使用 OpenCV 拍照（推荐方式）
    """
    try:
        import cv2
    except ImportError:
        return {"ok": False, "error": "OpenCV 未安装", "width": 0, "height": 0, "path": ""}

    capture_dir = _ensure_capture_dir()
    out_path = capture_dir / f"capture_{int(time.time())}.jpg"

    cap = cv2.VideoCapture(device_index)
    if not cap.isOpened():
        return {"ok": False, "error": f"无法打开摄像头 /dev/video{device_index}", "width": 0, "height": 0, "path": ""}

    cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

    start = time.time()
    ret, frame = False, None
    # 丢弃前几帧（摄像头预热），最多等 1.5 秒
    while time.time() - start < min(timeout_sec, 1.5):
        ret, frame = cap.read()
        if ret and frame is not None:
            break
        time.sleep(0.05)

    cap.release()

    if not ret or frame is None:
        return {"ok": False, "error": "摄像头读取超时或失败", "width": 0, "height": 0, "path": ""}

    h, w = frame.shape[:2]
    cv2.imwrite(str(out_path), frame, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])

    logger.info(f"local_camera: OpenCV capture success {w}x{h} -> {out_path}")
    return {"ok": True, "width": w, "height": h, "path": str(out_path), "error": ""}


def capture_with_fswebcam(
    width: int = 1280,
    height: int = 720,
    timeout_sec: float = 8.0
) -> Dict[str, Any]:
    """
    使用 fswebcam 命令行拍照（备选方案）
    """
    capture_dir = _ensure_capture_dir()
    out_path = capture_dir / f"capture_{int(time.time())}.jpg"

    cmd = [
        "fswebcam",
        "-r", f"{width}x{height}",
        "--no-banner",
        "--quiet",
        str(out_path)
    ]

    try:
        result = subprocess.run(
            cmd,
            check=True,
            timeout=timeout_sec,
            capture_output=True,
            text=True
        )
        if out_path.exists():
            logger.info(f"local_camera: fswebcam capture success -> {out_path}")
            return {"ok": True, "width": width, "height": height, "path": str(out_path), "error": ""}
        else:
            return {"ok": False, "error": "fswebcam 未生成文件", "width": 0, "height": 0, "path": ""}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "fswebcam 超时", "width": 0, "height": 0, "path": ""}
    except subprocess.CalledProcessError as e:
        return {"ok": False, "error": f"fswebcam 失败: {e.stderr}", "width": 0, "height": 0, "path": ""}


def capture_photo(
    preferred: str = "auto",
    width: int = 1280,
    height: int = 720,
    timeout_sec: float = 8.0,
    device_index: Optional[int] = None
) -> Dict[str, Any]:
    """
    统一拍照入口

    Args:
        preferred: "auto" | "opencv" | "fswebcam"
        device_index: 指定摄像头设备索引（优先级高于环境变量）
    """
    if device_index is None:
        device_index = int(os.getenv("CAMERA_DEVICE_INDEX", "0"))

    if preferred == "opencv":
        return capture_with_opencv(device_index=device_index, width=width, height=height)
    elif preferred == "fswebcam":
        return capture_with_fswebcam(width=width, height=height, timeout_sec=timeout_sec)

    # auto 模式：优先 OpenCV，失败则回退 fswebcam
    result = capture_with_opencv(device_index=device_index, width=width, height=height)
    if result["ok"]:
        return result

    logger.warning(f"OpenCV 拍照失败，回退 fswebcam: {result.get('error')}")
    return capture_with_fswebcam(width=width, height=height, timeout_sec=timeout_sec)


# ---------------------------------------------------------------------------
# CameraStream 单例 —— 摄像头持续打开 + MJPEG 帧生成
# ---------------------------------------------------------------------------

import threading


class CameraStream:
    """摄像头实时流管理器（单例）"""
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._cap = None
        self._frame = None          # 最新一帧 (numpy array)
        self._frame_lock = threading.Lock()
        self._running = False
        self._thread = None
        self._ref_count = 0         # 引用计数，无人观看时自动关闭
        self._ref_lock = threading.Lock()
        self._device_index = int(os.getenv("CAMERA_DEVICE_INDEX", "11"))
        self._width = 1280
        self._height = 720

    def _capture_loop(self):
        """后台线程持续读取摄像头帧"""
        import cv2
        cap = cv2.VideoCapture(self._device_index)
        if not cap.isOpened():
            logger.error(f"CameraStream: 无法打开摄像头 /dev/video{self._device_index}")
            self._running = False
            return
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self._width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self._height)
        self._cap = cap
        logger.info(f"CameraStream: 摄像头已打开 /dev/video{self._device_index}")

        while self._running:
            ret, frame = cap.read()
            if ret and frame is not None:
                with self._frame_lock:
                    self._frame = frame
            else:
                time.sleep(0.01)

        cap.release()
        self._cap = None
        logger.info("CameraStream: 摄像头已关闭")

    def start(self):
        """启动摄像头流"""
        with self._ref_lock:
            self._ref_count += 1
            if self._running:
                return
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """停止摄像头流"""
        with self._ref_lock:
            self._ref_count = max(0, self._ref_count - 1)
            if self._ref_count > 0:
                return
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        with self._frame_lock:
            self._frame = None

    def force_stop(self):
        """强制停止，忽略引用计数"""
        with self._ref_lock:
            self._ref_count = 0
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None

    @property
    def is_running(self):
        return self._running

    def get_frame_jpeg(self, quality: int = 80) -> bytes | None:
        """获取当前帧的 JPEG 编码"""
        import cv2
        with self._frame_lock:
            if self._frame is None:
                return None
            _, buf = cv2.imencode('.jpg', self._frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
            return buf.tobytes()

    def snapshot(self, jpeg_quality: int = 90) -> dict:
        """截取当前帧并保存到文件（用于拍照识药）"""
        import cv2
        with self._frame_lock:
            if self._frame is None:
                return {"ok": False, "error": "摄像头未就绪", "width": 0, "height": 0, "path": ""}
            frame = self._frame.copy()

        capture_dir = _ensure_capture_dir()
        out_path = capture_dir / f"capture_{int(time.time())}.jpg"
        h, w = frame.shape[:2]
        cv2.imwrite(str(out_path), frame, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
        logger.info(f"CameraStream: snapshot {w}x{h} -> {out_path}")
        return {"ok": True, "width": w, "height": h, "path": str(out_path), "error": ""}

    def generate_mjpeg(self, fps: int = 15):
        """生成 MJPEG 流的 generator（用于 StreamingResponse）"""
        interval = 1.0 / fps
        while self._running:
            jpeg = self.get_frame_jpeg(quality=70)
            if jpeg:
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n\r\n"
                    + jpeg + b"\r\n"
                )
            time.sleep(interval)


def get_camera_stream() -> CameraStream:
    """获取摄像头流单例"""
    return CameraStream()

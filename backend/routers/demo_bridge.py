import http.client
import json
import logging
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_PHOTO_MODE_FLAG = Path(os.path.expanduser("~/AI-Personal-Doctor/logs/.photo_mode_active"))

_demo_lock = threading.Lock()
_capture_gate = threading.Lock()
_capture_in_progress = threading.Event()
_capture_started_at = 0.0
_last_capture_fail_at = 0.0
_CAPTURE_STALE_SEC = 12.0

_DEMO_GRACE_SEC = 90.0
_DEMO_PROBE_MIN_INTERVAL = 2.0
_DEMO_FAST_HEALTH_TIMEOUT = 2

_state_lock = threading.Lock()
_last_health_ok = 0.0
_last_probe_at = 0.0
_cached_online = False
_cached_busy = False


def mark_demo_health_ok() -> None:
    global _last_health_ok, _cached_online, _cached_busy
    now = time.monotonic()
    with _state_lock:
        _last_health_ok = now
        _cached_online = True
        _cached_busy = False


def update_demo_availability(bridge: "DemoBridge | None" = None, *, force: bool = False) -> tuple[bool, bool]:
    global _last_probe_at, _cached_online, _cached_busy, _last_health_ok
    now = time.monotonic()
    with _state_lock:
        if not force and now - _last_probe_at < _DEMO_PROBE_MIN_INTERVAL:
            return _cached_online, _cached_busy

    if bridge is None:
        bridge = get_demo_bridge()

    ok = False
    try:
        ok = bool(bridge.health(timeout=_DEMO_FAST_HEALTH_TIMEOUT).get("ok"))
    except Exception:
        ok = False

    if not ok:
        try:
            bridge.wake_info()
            ok = True
        except Exception:
            ok = False

    capturing = demo_capture_active()
    with _state_lock:
        _last_probe_at = now
        if ok:
            _last_health_ok = now
            _cached_online = True
            _cached_busy = capturing
        elif now - _last_health_ok < _DEMO_GRACE_SEC:
            _cached_online = True
            _cached_busy = capturing
        else:
            _cached_online = False
            _cached_busy = False
        return _cached_online, _cached_busy


def _write_photo_mode_flag(active: bool) -> None:
    try:
        if active:
            _PHOTO_MODE_FLAG.parent.mkdir(parents=True, exist_ok=True)
            _PHOTO_MODE_FLAG.write_text(str(time.time()), encoding="utf-8")
        elif _PHOTO_MODE_FLAG.exists():
            _PHOTO_MODE_FLAG.unlink()
    except Exception as exc:
        logger.warning("photo mode flag: %s", exc)


def _start_demo_process(*, wake_daemon: bool = True) -> None:
    demo_dir = os.path.expanduser(os.environ.get("DEMO_DIR", "~/Qwen_test"))
    demo_bin = os.path.join(demo_dir, "demo")
    root = os.path.expanduser("~/AI-Personal-Doctor")
    log_path = os.path.join(root, "logs", "demo.log")
    encoder = os.environ.get("DEMO_ENCODER", "qwen2_vl_2b_vision_rk3588.rknn")
    llm = os.environ.get("DEMO_LLM", "Qwen2-VL-2B-Instruct.rkllm")
    env = os.environ.copy()
    env["DEMO_CONTROL_PORT"] = os.environ.get("DEMO_CONTROL_PORT", "8765")
    env["DEMO_DAEMON"] = "1"
    env["DEMO_WAKE_DAEMON"] = "1" if wake_daemon else "0"
    env["DEMO_SKIP_NPU"] = os.environ.get("DEMO_SKIP_NPU", "1")
    env["CAMERA_DEVICE_INDEX"] = os.environ.get("CAMERA_DEVICE_INDEX", "11")
    cmd = [demo_bin, encoder, llm, "180", "1024"]
    with open(log_path, "a", encoding="utf-8") as logf:
        subprocess.Popen(
            cmd,
            cwd=demo_dir,
            env=env,
            stdout=logf,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            start_new_session=True,
        )


def _demo_in_camera_mode() -> bool:
    """demo 是否已在无唤醒守护模式且 health 正常。"""
    try:
        out = subprocess.run(
            ["pgrep", "-f", "Qwen_test/demo"],
            capture_output=True,
            text=True,
            check=False,
        )
        pid = (out.stdout or "").strip().split("\n")[0].strip()
        if not pid:
            return False
        raw = Path(f"/proc/{pid}/environ").read_bytes()
        if b"DEMO_WAKE_DAEMON=0" not in raw.replace(b"\x00", b"\n"):
            return False
        return bool(get_demo_bridge().health(timeout=3).get("ok"))
    except Exception:
        return False


def prepare_demo_for_camera_capture() -> None:
    """重启 demo 且关闭后台唤醒守护，释放麦克风给摄像头。"""
    if _demo_in_camera_mode():
        logger.info("demo already in camera mode, skip restart")
        _write_photo_mode_flag(True)
        return
    logger.info("prepare demo for camera (WAKE_DAEMON=0)")
    _write_photo_mode_flag(True)
    _hard_reset_demo()
    _start_demo_process(wake_daemon=False)
    if not _wait_demo_recovered(timeout_sec=35.0):
        raise DemoBridgeError("语音引擎启动失败，请稍后重试", {"ok": False, "camera": True})


def restore_demo_after_camera() -> None:
    """问药结束，恢复带唤醒守护的 demo。"""
    logger.info("restore demo after camera (WAKE_DAEMON=1)")
    _write_photo_mode_flag(False)
    _hard_reset_demo()
    _start_demo_process(wake_daemon=True)
    _wait_demo_recovered(timeout_sec=35.0)


def _hard_reset_demo() -> bool:
    try:
        subprocess.run(
            ["pkill", "-9", "-f", "Qwen_test/demo"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        logger.warning("hard reset demo failed: %s", exc)
        return False
    time.sleep(2.5)
    return True


def recover_stale_capture(*, force: bool = False) -> bool:
    global _capture_started_at
    if not _capture_in_progress.is_set():
        return False
    age = time.monotonic() - _capture_started_at if _capture_started_at else _CAPTURE_STALE_SEC + 1
    if not force and age < _CAPTURE_STALE_SEC:
        return False
    logger.warning("recover stale capture (age=%.1fs force=%s)", age, force)
    if force:
        _hard_reset_demo()
    _capture_in_progress.clear()
    _capture_started_at = 0.0
    return True


def demo_capture_active() -> bool:
    recover_stale_capture()
    return _capture_in_progress.is_set()


class DemoBridge:
    def __init__(self, base_url: str | None = None):
        from ..config import get_settings

        self.base_url = (base_url or get_settings()["demo_control_url"]).rstrip("/")
        parsed = urlparse(self.base_url)
        self._host = parsed.hostname or "127.0.0.1"
        self._port = parsed.port or 80

    def health(self, timeout: int = 5) -> dict:
        return self._request("GET", "/health", timeout=timeout)

    def status(self) -> dict:
        return self._request("GET", "/status")

    def speak(self, text: str, wait: bool = False) -> dict:
        payload = json.dumps(
            {"text": text, "wait": wait},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        with _demo_lock:
            return self._request("POST", "/speak", payload, timeout=60)

    def voice_start(self) -> dict:
        return self._request("POST", "/voice/start")

    def is_capturing(self) -> bool:
        return demo_capture_active()

    def voice_stop(self, *, force: bool = False) -> dict:
        if demo_capture_active() and not force:
            return {"ok": True, "skipped": True}
        return self._request("POST", "/voice/stop", timeout=6)

    def chat(self, prompt: str, speak: bool = False) -> dict:
        payload = json.dumps(
            {"prompt": prompt, "speak": speak},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        with _demo_lock:
            return self._request("POST", "/chat", payload, timeout=180)

    def chat_stream(self, prompt: str, speak: bool = False):
        payload = json.dumps(
            {"prompt": prompt, "speak": speak},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        with _demo_lock:
            conn = http.client.HTTPConnection(self._host, self._port, timeout=180)
            headers = {"Content-Type": "application/json; charset=utf-8"}
            try:
                conn.request("POST", "/chat/stream", body=payload, headers=headers)
                response = conn.getresponse()
                if response.status >= 400:
                    raw = response.read().decode("utf-8", errors="ignore")
                    try:
                        data = json.loads(raw) if raw else {"ok": False}
                    except json.JSONDecodeError:
                        data = {"ok": False, "error": raw or response.reason}
                    raise DemoBridgeError(data.get("error") or response.reason, data)
                while True:
                    line = response.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", errors="ignore").strip()
                    if not text:
                        continue
                    yield json.loads(text)
            except DemoBridgeError:
                raise
            except Exception as exc:
                raise DemoBridgeError(str(exc), {"ok": False, "error": str(exc)}) from exc
            finally:
                conn.close()

    def capture_photo(self) -> dict:
        global _last_capture_fail_at, _capture_started_at

        recover_stale_capture()

        with _capture_gate:
            if _capture_in_progress.is_set():
                raise DemoBridgeError("正在拍照，请稍候", {"ok": False, "busy": True})
            _capture_in_progress.set()
            _capture_started_at = time.monotonic()

        try:
            from .wake_service import enter_photo_mode, photo_mode_active

            if not photo_mode_active():
                enter_photo_mode(120)
            try:
                return self._run_capture_with_timeout(38.0)
            except DemoBridgeError as exc:
                if not _should_retry_camera(exc):
                    _last_capture_fail_at = time.monotonic()
                    raise
                logger.warning("capture retry after demo reset: %s", exc)
                _last_capture_fail_at = time.monotonic()
                recover_stale_capture(force=True)
                enter_photo_mode(120)
                return self._run_capture_with_timeout(38.0)
        finally:
            _capture_in_progress.clear()
            _capture_started_at = 0.0

    def _run_capture_with_timeout(self, timeout_sec: float) -> dict:
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self._capture_photo_once)
            try:
                return future.result(timeout=max(10.0, timeout_sec))
            except FuturesTimeout:
                logger.error("capture hard timeout %.0fs", timeout_sec)
                recover_stale_capture(force=True)
                raise DemoBridgeError(
                    "拍照超时，请把药盒对准摄像头后再试",
                    {"ok": False, "camera": True},
                )

    def _ensure_demo_idle_for_camera(self) -> None:
        from .wake_service import enter_photo_mode

        enter_photo_mode(120)
        time.sleep(0.2)

    def _capture_photo_once(self) -> dict:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            if _demo_lock.acquire(blocking=False):
                try:
                    logger.info("demo bridge: camera capture start")
                    return self._request("POST", "/camera/capture", b"{}", timeout=28)
                finally:
                    _demo_lock.release()
            time.sleep(0.2)
        raise DemoBridgeError("语音引擎正忙，请稍后再试", {"ok": False, "busy": True})

    def prepare_for_capture(self) -> None:
        if demo_capture_active():
            return
        self._ensure_demo_idle_for_camera()

    def fetch_camera_image(self) -> bytes:
        with _demo_lock:
            conn = http.client.HTTPConnection(self._host, self._port, timeout=30)
            try:
                conn.request("GET", "/camera/last")
                response = conn.getresponse()
                if response.status >= 400:
                    raise DemoBridgeError(response.reason or "no capture", {"ok": False})
                return response.read()
            finally:
                conn.close()

    def chat_vision_stream(self, prompt: str, speak: bool = False):
        payload = json.dumps(
            {"prompt": prompt, "speak": speak},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        with _demo_lock:
            conn = http.client.HTTPConnection(self._host, self._port, timeout=180)
            headers = {"Content-Type": "application/json; charset=utf-8"}
            try:
                conn.request("POST", "/chat/vision/stream", body=payload, headers=headers)
                response = conn.getresponse()
                if response.status >= 400:
                    raw = response.read().decode("utf-8", errors="ignore")
                    try:
                        data = json.loads(raw) if raw else {"ok": False}
                    except json.JSONDecodeError:
                        data = {"ok": False, "error": raw or response.reason}
                    raise DemoBridgeError(data.get("error") or response.reason, data)
                while True:
                    line = response.readline()
                    if not line:
                        break
                    text = line.decode("utf-8", errors="ignore").strip()
                    if not text:
                        continue
                    yield json.loads(text)
            except DemoBridgeError:
                raise
            except Exception as exc:
                raise DemoBridgeError(str(exc), {"ok": False, "error": str(exc)}) from exc
            finally:
                conn.close()

    def listen(self, prompt: bool = False, speak_first: str = "") -> dict:
        payload = json.dumps(
            {"prompt": prompt, "speak_first": speak_first or ""},
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        with _demo_lock:
            return self._request("POST", "/listen", payload, timeout=90)

    def wake_info(self) -> dict:
        return self._request("GET", "/wake/info", timeout=8)

    def wait_wake(self, timeout: int = 120) -> bool:
        from .wake_service import photo_mode_active

        if photo_mode_active():
            return False
        result = self._request("POST", "/wake/wait", b"{}", timeout=timeout)
        return bool(result.get("wake"))

    def is_online(self, *, strict: bool = False) -> bool:
        online, busy = update_demo_availability(self)
        if strict:
            return online and not busy
        return online

    def _request(self, method: str, path: str, body: bytes | None = None, timeout: int = 8) -> dict:
        conn = http.client.HTTPConnection(self._host, self._port, timeout=timeout)
        headers = {}
        if body is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
        try:
            conn.request(method, path, body=body, headers=headers)
            response = conn.getresponse()
            raw = response.read().decode("utf-8", errors="ignore")
            if response.status >= 400:
                try:
                    data = json.loads(raw) if raw else {"ok": False}
                except json.JSONDecodeError:
                    data = {"ok": False, "error": raw or response.reason}
                data.setdefault("ok", False)
                raise DemoBridgeError(data.get("error") or response.reason, data)
            mark_demo_health_ok()
            return json.loads(raw) if raw else {"ok": True}
        except DemoBridgeError:
            raise
        except Exception as exc:
            raise DemoBridgeError(str(exc), {"ok": False, "error": str(exc)}) from exc
        finally:
            conn.close()


class DemoBridgeError(Exception):
    def __init__(self, message: str, payload: dict | None = None):
        super().__init__(message)
        self.payload = payload or {"ok": False, "error": message}


_bridge: DemoBridge | None = None


def get_demo_bridge() -> DemoBridge:
    global _bridge
    if _bridge is None:
        _bridge = DemoBridge()
    return _bridge


def _camera_open_failed(exc: DemoBridgeError) -> bool:
    text = str(exc).lower()
    payload = getattr(exc, "payload", None) or {}
    err = str(payload.get("error") or "").lower()
    return "cannot open camera" in text or "cannot open camera" in err or "open camera" in err


def _capture_timed_out(exc: DemoBridgeError) -> bool:
    text = str(exc).lower()
    return "timed out" in text or "timeout" in text


def _should_retry_camera(exc: DemoBridgeError) -> bool:
    if _camera_open_failed(exc):
        return True
    payload = getattr(exc, "payload", None) or {}
    if payload.get("camera"):
        return True
    return _capture_timed_out(exc)


def _wait_demo_recovered(timeout_sec: float = 25.0) -> bool:
    bridge = get_demo_bridge()
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        time.sleep(1.5)
        try:
            if bridge.health(timeout=4).get("ok"):
                time.sleep(0.8)
                return True
        except DemoBridgeError:
            continue
    return False


def _restart_demo_process(timeout_sec: float = 50.0) -> bool:
    return _hard_reset_demo() and _wait_demo_recovered(timeout_sec=timeout_sec)


def friendly_demo_error(exc: DemoBridgeError) -> str:
    message = str(exc).strip()
    lowered = message.lower()
    if "cannot open camera" in lowered or "open camera" in lowered:
        return "摄像头暂不可用（可能过热或被占用），请等半分钟后再试"
    if "no speech" in lowered:
        return "没有听清，请先点按钮，听到提示后再说话"
    if "refused" in lowered or "connection refused" in lowered:
        return "语音引擎重启中，请稍候再试"
    if "busy" in lowered or "timed out" in lowered or "正在拍照" in str(exc):
        return "语音引擎正忙，请稍等几秒再试"
    if "camera" in lowered or "capture" in lowered or "encode" in lowered:
        return "摄像头拍照失败，请检查摄像头连接后重试"
    if "vision not initialized" in lowered:
        return "摄像头模块未就绪，请重启 demo 服务"
    if "vision" in lowered or "no capture" in lowered:
        return "请先拍照，再进行识别"
    return message or "语音服务暂时不可用"

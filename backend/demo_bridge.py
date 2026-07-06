import http.client
import json
import logging
import subprocess
import threading
import time
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_demo_lock = threading.Lock()
_capture_serial = threading.Lock()
_capture_in_progress = threading.Event()
_last_capture_fail_at = 0.0


_DEMO_GRACE_SEC = 90.0
_DEMO_PROBE_MIN_INTERVAL = 2.0
_DEMO_FAST_HEALTH_TIMEOUT = 2

_state_lock = threading.Lock()
_last_health_ok = 0.0
_last_probe_at = 0.0
_cached_online = False
_cached_busy = False


def mark_demo_health_ok() -> None:
    """Successful demo API call — extend grace window."""
    global _last_health_ok, _cached_online, _cached_busy
    now = time.monotonic()
    with _state_lock:
        _last_health_ok = now
        _cached_online = True
        _cached_busy = False


def update_demo_availability(bridge: "DemoBridge | None" = None, *, force: bool = False) -> tuple[bool, bool]:
    """Return (online, busy). busy 仅表示拍照等独占操作进行中，不等同于离线。"""
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
        # demo 可能在等唤醒词，/health 偶发超时；用 /wake/info 再探一次
        try:
            bridge.wake_info()
            ok = True
        except Exception:
            ok = False

    capturing = _capture_in_progress.is_set()
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


def demo_capture_active() -> bool:
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
        return _capture_in_progress.is_set()

    def voice_stop(self, *, force: bool = False) -> dict:
        if _capture_in_progress.is_set() and not force:
            return {"ok": True, "skipped": True}
        return self._request("POST", "/voice/stop")

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
        """拍照独占：先清 demo 唤醒/录音，再拍照；失败自动重启 demo 重试一次。"""
        global _last_capture_fail_at

        if not _capture_serial.acquire(blocking=False):
            raise DemoBridgeError("正在拍照，请稍候", {"ok": False, "busy": True})

        _capture_in_progress.set()
        try:
            self._ensure_demo_idle_for_camera()
            try:
                return self._capture_photo_once()
            except DemoBridgeError as exc:
                if not _should_retry_camera(exc):
                    _last_capture_fail_at = time.monotonic()
                    raise
                logger.warning("demo bridge: capture failed, restarting demo once: %s", exc)
                _last_capture_fail_at = time.monotonic()
                if not _restart_demo_process(timeout_sec=50.0):
                    raise DemoBridgeError(
                        "摄像头暂不可用，请等待约半分钟后重试",
                        {"ok": False, "camera": True},
                    ) from exc
                self._ensure_demo_idle_for_camera()
                return self._capture_photo_once()
        except DemoBridgeError:
            try:
                self.voice_stop(force=True)
            except DemoBridgeError:
                pass
            raise
        finally:
            _capture_in_progress.clear()
            _capture_serial.release()

    def _ensure_demo_idle_for_camera(self) -> None:
        from .wake_service import interrupt_demo_voice, pause_wake_listening, wait_for_wake_session_idle

        pause_wake_listening(120)
        interrupt_demo_voice()
        if not wait_for_wake_session_idle(timeout=12.0):
            interrupt_demo_voice()
            time.sleep(0.5)
            wait_for_wake_session_idle(timeout=6.0)
        time.sleep(0.25)

    def _capture_photo_once(self) -> dict:
        from .wake_service import cancel_pending_wake, interrupt_demo_voice, wait_for_wake_session_idle

        interrupt_demo_voice()
        cancel_pending_wake()
        if not wait_for_wake_session_idle(timeout=15.0):
            interrupt_demo_voice()
            time.sleep(0.5)
            if not wait_for_wake_session_idle(timeout=8.0):
                raise DemoBridgeError("语音引擎正忙，请稍后再试", {"ok": False, "busy": True})

        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if _demo_lock.acquire(blocking=False):
                try:
                    logger.info("demo bridge: camera capture start")
                    return self._request("POST", "/camera/capture", b"{}", timeout=25)
                finally:
                    _demo_lock.release()
            time.sleep(0.3)
        raise DemoBridgeError("语音引擎正忙，请稍后再试", {"ok": False, "busy": True})

    def prepare_for_capture(self) -> None:
        """兼容旧调用：实际清理由 capture_photo 统一完成。"""
        if _capture_in_progress.is_set():
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
        # 不占用 _demo_lock，否则长时间等唤醒会阻塞拍照 capture
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


def _restart_demo_process(timeout_sec: float = 50.0) -> bool:
    """摄像头打不开时重启 demo，交给 watchdog 拉起。"""
    try:
        subprocess.run(
            ["pkill", "-9", "-f", "Qwen_test/demo qwen"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        logger.warning("demo bridge: failed to kill demo for camera recovery: %s", exc)
        return False

    time.sleep(5.0)
    bridge = get_demo_bridge()
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        time.sleep(2.0)
        try:
            if bridge.health(timeout=3).get("ok"):
                time.sleep(3.0)
                return True
        except DemoBridgeError:
            continue
    return False


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

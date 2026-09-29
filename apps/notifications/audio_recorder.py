import math
import os
import subprocess
import threading
import time
import uuid
import wave
from dataclasses import dataclass
from pathlib import Path

from django.conf import settings
from django.core.files import File
from django.db import transaction
from django.utils import timezone

from .backends.pjsip_microphone import PjsipMicrophoneError, PjsuaCliClient
from .models import AudioFile


class AudioRecorderError(RuntimeError):
    """Raised when the local PAO microphone recorder cannot start, stop, or save."""


@dataclass
class RecorderSession:
    session_id: str
    requested_by_id: int | None
    requested_by_username: str
    started_at: object
    temp_path: Path
    log_path: Path
    process: object
    cli: object
    max_duration_seconds: int
    stopping: bool = False


class AudioRecorderManager:
    """Record the PAO Windows microphone to a PJSIP-ready WAV file."""

    def __init__(self):
        self._lock = threading.RLock()
        self._session = None
        self._completed = {}
        self._last_completed_id = None
        self._timer = None

    def status(self):
        with self._lock:
            self._recover_if_exited()
            if not self._session:
                result = {"active": False}
                if self._last_completed_id and self._last_completed_id in self._completed:
                    completed = self._completed[self._last_completed_id]
                    result.update({
                        "completed_session_id": self._last_completed_id,
                        "duration_seconds": completed["duration_seconds"],
                        "format": "WAV / Mono / 8000 Hz / 16-bit PCM",
                    })
                return result
            elapsed = max(0, int((timezone.now() - self._session.started_at).total_seconds()))
            return {
                "active": True,
                "session_id": self._session.session_id,
                "started_at": timezone.localtime(self._session.started_at).isoformat(),
                "elapsed_seconds": elapsed,
                "max_duration_seconds": self._session.max_duration_seconds,
                "requested_by_username": self._session.requested_by_username,
            }

    def start(self, user):
        with self._lock:
            self._recover_if_exited()
            if self._session:
                raise AudioRecorderError("已有進行中的錄音工作階段。")

            session_id = uuid.uuid4().hex
            started_at = timezone.now()
            max_duration = int(getattr(settings, "PJSIP_MIC_MAX_DURATION_SECONDS", 300))
            executable = Path(getattr(settings, "PJSIP_EXECUTABLE_PATH"))
            if not executable.is_file():
                raise AudioRecorderError(f"PJSUA executable not found: {executable}")

            temp_dir = Path(settings.MEDIA_ROOT) / "audio_recordings_tmp"
            log_dir = Path(getattr(settings, "PJSIP_LOG_DIR")) / "audio_recorder"
            temp_dir.mkdir(parents=True, exist_ok=True)
            log_dir.mkdir(parents=True, exist_ok=True)
            temp_path = temp_dir / f"recording_{session_id}.wav"
            log_path = log_dir / f"recording_{session_id}.log"
            log_path.write_text("", encoding="utf-8")

            local_ip = str(getattr(settings, "PJSIP_LOCAL_IP", "") or "").strip()
            if not local_ip:
                raise AudioRecorderError("PJSIP local IP is required.")

            sip_port = int(getattr(settings, "PJSIP_LOCAL_SIP_PORT_BASE", 64882)) + 300
            cli_port = int(getattr(settings, "PJSIP_MIC_CLI_PORT", 23233)) + 1
            capture_device = int(getattr(settings, "PJSIP_MIC_CAPTURE_DEVICE", -1))
            playback_device = int(getattr(settings, "PJSIP_MIC_PLAYBACK_DEVICE", -1))
            log_level = int(getattr(settings, "PJSIP_LOG_LEVEL", 5))
            app_log_level = int(getattr(settings, "PJSIP_APP_LOG_LEVEL", 4))

            command = [
                str(executable),
                f"--log-file={log_path}",
                f"--log-level={log_level}",
                f"--app-log-level={app_log_level}",
                "--no-color",
                "--no-tcp",
                "--no-tones",
                "--use-cli",
                f"--cli-telnet-port={cli_port}",
                "--no-cli-console",
                f"--local-port={sip_port}",
                f"--ip-addr={local_ip}",
                f"--bound-addr={local_ip}",
                "--clock-rate=8000",
                "--snd-clock-rate=8000",
                f"--capture-dev={capture_device}",
                f"--playback-dev={playback_device}",
                f"--rec-file={temp_path}",
            ]

            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            process = None
            cli = None
            try:
                process = subprocess.Popen(
                    command,
                    cwd=str(executable.parent),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creation_flags,
                )
                cli = PjsuaCliClient(cli_port)
                cli.connect(timeout=float(getattr(settings, "PJSIP_MIC_STARTUP_TIMEOUT_SECONDS", 12)))
                # PJSUA conference port 0 is the sound device; --rec-file registers the WAV recorder as port 1.
                response = cli.command("audio conf_con 0 1")
                if "error" in response.lower() or "invalid" in response.lower():
                    response = cli.command("cc 0 1")
                    if "error" in response.lower() or "invalid" in response.lower():
                        raise AudioRecorderError("無法將麥克風音訊連接到 WAV 錄音器。")

                self._session = RecorderSession(
                    session_id=session_id,
                    requested_by_id=getattr(user, "id", None),
                    requested_by_username=user.get_username(),
                    started_at=started_at,
                    temp_path=temp_path,
                    log_path=log_path,
                    process=process,
                    cli=cli,
                    max_duration_seconds=max_duration,
                )
                self._timer = threading.Timer(max_duration, self._timeout_stop, args=(session_id,))
                self._timer.daemon = True
                self._timer.start()
                return self.status()
            except Exception as exc:
                self._shutdown_runtime(process, cli)
                temp_path.unlink(missing_ok=True)
                if isinstance(exc, AudioRecorderError):
                    raise
                raise AudioRecorderError(f"無法啟動錄音：{exc}") from exc

    def stop(self, session_id=None, reason="manual_stop"):
        with self._lock:
            if not self._session:
                raise AudioRecorderError("目前沒有進行中的錄音。")
            if session_id and session_id != self._session.session_id:
                raise AudioRecorderError("錄音工作階段識別碼不符。")
            session = self._session
            if session.stopping:
                raise AudioRecorderError("錄音正在停止。")
            session.stopping = True
            if self._timer:
                self._timer.cancel()
                self._timer = None

            try:
                try:
                    session.cli.command("audio conf_dis 0 1")
                except Exception:
                    pass
                self._shutdown_runtime(session.process, session.cli)
                audio_info = self._validate_wav(session.temp_path)
                completed_at = timezone.now()
                elapsed = max(1, int(math.ceil((completed_at - session.started_at).total_seconds())))
                self._completed[session.session_id] = {
                    "temp_path": session.temp_path,
                    "started_at": session.started_at,
                    "completed_at": completed_at,
                    "duration_seconds": max(elapsed, audio_info["duration_seconds"]),
                    "requested_by_id": session.requested_by_id,
                    "requested_by_username": session.requested_by_username,
                    "reason": reason,
                }
                self._last_completed_id = session.session_id
                result = {
                    "active": False,
                    "session_id": session.session_id,
                    "duration_seconds": self._completed[session.session_id]["duration_seconds"],
                    "format": "WAV / Mono / 8000 Hz / 16-bit PCM",
                }
                self._session = None
                return result
            except Exception:
                session.temp_path.unlink(missing_ok=True)
                self._session = None
                raise

    def save(self, session_id, name):
        with self._lock:
            completed = self._completed.get(session_id)
            if not completed:
                raise AudioRecorderError("找不到已完成且尚未儲存的錄音。")
            temp_path = Path(completed["temp_path"])
            info = self._validate_wav(temp_path)
            name = str(name or "").strip()
            if not name:
                name = timezone.localtime(completed["completed_at"]).strftime("現場錄音 %Y-%m-%d %H:%M:%S")
            if len(name) > 100:
                raise AudioRecorderError("音檔名稱不可超過 100 個字元。")

            now = timezone.localtime(timezone.now())
            base_code = now.strftime("AUD-REC-%Y%m%d-%H%M%S")
            audio_code = base_code
            suffix = 1
            while AudioFile.objects.filter(audio_code=audio_code).exists():
                suffix += 1
                audio_code = f"{base_code}-{suffix:02d}"

            final_filename = f"{audio_code}.wav"
            with transaction.atomic():
                audio = AudioFile(
                    audio_code=audio_code,
                    name=name,
                    audio_type=AudioFile.AUDIO_TYPE_OTHER,
                    duration_seconds=info["duration_seconds"],
                    is_active=True,
                    description="由站區廣播系統錄音機使用 PAO 本機麥克風建立。",
                )
                with temp_path.open("rb") as source:
                    audio.file.save(final_filename, File(source), save=False)
                audio.full_clean()
                audio.save()

            temp_path.unlink(missing_ok=True)
            self._completed.pop(session_id, None)
            if self._last_completed_id == session_id:
                self._last_completed_id = None
            return {
                "audio_file_id": audio.id,
                "audio_code": audio.audio_code,
                "name": audio.name,
                "duration_seconds": audio.duration_seconds,
                "file_name": audio.file.name,
            }

    def discard(self, session_id):
        with self._lock:
            completed = self._completed.pop(session_id, None)
            if completed:
                Path(completed["temp_path"]).unlink(missing_ok=True)
            if self._last_completed_id == session_id:
                self._last_completed_id = None
            return {"discarded": bool(completed)}

    def _timeout_stop(self, session_id):
        try:
            self.stop(session_id=session_id, reason="timeout")
        except Exception:
            pass

    def _recover_if_exited(self):
        if self._session and self._session.process.poll() is not None:
            session = self._session
            self._session = None
            session.temp_path.unlink(missing_ok=True)

    @staticmethod
    def _shutdown_runtime(process, cli):
        if cli is not None:
            try:
                cli.command("shutdown")
            except Exception:
                pass
            try:
                cli.close()
            except Exception:
                pass
        if process is not None and process.poll() is None:
            try:
                process.wait(timeout=3)
            except Exception:
                try:
                    process.terminate()
                    process.wait(timeout=2)
                except Exception:
                    try:
                        process.kill()
                    except Exception:
                        pass

    @staticmethod
    def _validate_wav(path):
        path = Path(path)
        if not path.is_file() or path.stat().st_size <= 44:
            raise AudioRecorderError("錄音檔不存在或沒有有效音訊內容。")
        try:
            with wave.open(str(path), "rb") as wav_file:
                channels = wav_file.getnchannels()
                rate = wav_file.getframerate()
                width = wav_file.getsampwidth()
                frames = wav_file.getnframes()
                compression = wav_file.getcomptype()
        except (wave.Error, EOFError) as exc:
            raise AudioRecorderError(f"錄音 WAV 無效：{exc}") from exc
        if channels != 1 or rate != 8000 or width != 2 or compression != "NONE":
            raise AudioRecorderError(
                f"錄音格式不符：channels={channels}, rate={rate}, width={width}, compression={compression}"
            )
        duration_seconds = max(1, int(math.ceil(frames / rate)))
        return {
            "channels": channels,
            "rate": rate,
            "width": width,
            "frames": frames,
            "duration_seconds": duration_seconds,
        }


audio_recorder_manager = AudioRecorderManager()

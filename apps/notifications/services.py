import subprocess
import sys
import time
import wave
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import BroadcastLog


DEFAULT_PLAYBACK_MODE = "simulation"

PLAYBACK_MODE_SIMULATION = "simulation"
PLAYBACK_MODE_MICROSIP_WINSOUND = "microsip_winsound"

DEFAULT_PLAY_AFTER_DIAL_DELAY_SECONDS = 1
DEFAULT_HANGUP_AFTER_AUDIO_MARGIN_SECONDS = 2

DEFAULT_MICROSIP_PATHS = [
    r"C:\Users\user\Desktop\MicroSIP.lnk",
    r"C:\Users\user\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\MicroSIP\MicroSIP.lnk",
    r"C:\Users\user\AppData\Local\MicroSIP\MicroSIP.exe",
    r"C:\Program Files\MicroSIP\microsip.exe",
    r"C:\Program Files (x86)\MicroSIP\microsip.exe",
]


def process_pending_broadcast_logs(limit=10):
    """
    處理 pending BroadcastLog。

    Step 20-3 支援兩種模式：

    1. simulation
       不實際呼叫 IP Speaker。
       用於 Dashboard / API 流程測試。

    2. microsip_winsound
       使用 Windows SIP URI 呼叫 MicroSIP 撥號，
       再用 winsound 播放本機 wav 音檔，
       播放完成後嘗試自動掛斷 MicroSIP。

    settings.py 可設定：
    BROADCAST_PLAYBACK_MODE = "simulation"
    或
    BROADCAST_PLAYBACK_MODE = "microsip_winsound"
    """

    pending_logs = list(
        BroadcastLog.objects
        .select_related("event", "event__camera", "rule", "speaker", "audio_file")
        .filter(status=BroadcastLog.STATUS_PENDING)
        .order_by("created_at")[:limit]
    )

    results = []
    success_count = 0
    failed_count = 0
    skipped_count = 0

    for log in pending_logs:
        result = process_single_broadcast_log(log)
        results.append(result)

        if result["status"] == BroadcastLog.STATUS_SUCCESS:
            success_count += 1
        elif result["status"] == BroadcastLog.STATUS_FAILED:
            failed_count += 1
        elif result["status"] == BroadcastLog.STATUS_SKIPPED:
            skipped_count += 1

    return {
        "processed_count": len(results),
        "success_count": success_count,
        "failed_count": failed_count,
        "skipped_count": skipped_count,
        "results": results,
    }


def process_single_broadcast_log(log):
    """
    處理單一 BroadcastLog。

    注意：
    真實播放音檔可能需要數秒，因此不要把整個播放流程包在 transaction 裡。

    流程：
    1. transaction 內鎖定資料，檢查資料完整性，標記為 playing。
    2. transaction 外執行播放。
    3. 播放完成後回寫 success / failed。
    """

    prepare_result = prepare_broadcast_log_for_playback(log)

    if not prepare_result["success"]:
        return prepare_result["result"]

    log_id = prepare_result["broadcast_log_id"]

    log = (
        BroadcastLog.objects
        .select_related("event", "event__camera", "rule", "speaker", "audio_file")
        .get(id=log_id)
    )

    speaker = log.speaker
    audio_file = log.audio_file

    playback_result = play_audio_to_speaker(
        speaker=speaker,
        audio_file=audio_file,
        broadcast_log=log,
    )

    if playback_result.get("success"):
        return mark_broadcast_success(
            log=log,
            message=playback_result.get(
                "message",
                "Playback completed successfully.",
            ),
            response_payload=playback_result,
        )

    return mark_broadcast_failed(
        log=log,
        message=playback_result.get(
            "message",
            "Playback failed.",
        ),
        response_payload=playback_result,
    )


@transaction.atomic
def prepare_broadcast_log_for_playback(log):
    """
    鎖定 BroadcastLog，檢查資料完整性，並標記為 playing。
    """

    log = (
        BroadcastLog.objects
        .select_for_update()
        .select_related("event", "event__camera", "rule", "speaker", "audio_file")
        .get(id=log.id)
    )

    if log.status != BroadcastLog.STATUS_PENDING:
        return {
            "success": False,
            "result": {
                "broadcast_log_id": log.id,
                "status": log.status,
                "message": "BroadcastLog is not pending. Skipped.",
            },
        }

    if log.speaker is None:
        failed_result = mark_broadcast_failed(
            log=log,
            message="SpeakerDevice is missing.",
            response_payload={
                "success": False,
                "reason": "speaker_missing",
            },
        )

        return {
            "success": False,
            "result": failed_result,
        }

    if log.audio_file is None:
        failed_result = mark_broadcast_failed(
            log=log,
            message="AudioFile is missing.",
            response_payload={
                "success": False,
                "reason": "audio_file_missing",
            },
        )

        return {
            "success": False,
            "result": failed_result,
        }

    speaker = log.speaker
    audio_file = log.audio_file
    playback_mode = get_broadcast_playback_mode()

    request_payload = build_request_payload(
        playback_mode=playback_mode,
        speaker=speaker,
        audio_file=audio_file,
        broadcast_log=log,
    )

    log.status = BroadcastLog.STATUS_PLAYING
    log.started_at = timezone.now()
    log.request_payload = request_payload
    log.message = f"Playback started. mode={playback_mode}"
    log.save(
        update_fields=[
            "status",
            "started_at",
            "request_payload",
            "message",
            "updated_at",
        ]
    )

    return {
        "success": True,
        "broadcast_log_id": log.id,
    }


def build_request_payload(playback_mode, speaker, audio_file, broadcast_log):
    """
    建立 request_payload，方便後續在 Admin / Dashboard 追蹤播放請求。
    """

    audio_file_name = ""
    audio_file_path = ""

    if audio_file.file:
        audio_file_name = audio_file.file.name

        try:
            audio_file_path = audio_file.file.path
        except NotImplementedError:
            audio_file_path = audio_file.file.name

    existing_payload = broadcast_log.request_payload or {}

    return {
        **existing_payload,
        "mode": playback_mode,
        "broadcast_log_id": broadcast_log.id,

        "speaker_id": speaker.id,
        "speaker_code": speaker.speaker_code,
        "speaker_name": speaker.name,
        "protocol": speaker.protocol,
        "ip_address": str(speaker.ip_address),
        "port": speaker.port,
        "sip_uri": speaker.sip_uri,
        "resolved_sip_uri": speaker.resolved_sip_uri,

        "audio_file_id": audio_file.id,
        "audio_code": audio_file.audio_code,
        "audio_name": audio_file.name,
        "audio_file": audio_file_name,
        "audio_path": audio_file_path,

        "requested_at": timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M:%S"),
    }


def play_audio_to_speaker(speaker, audio_file, broadcast_log):
    """
    播放音檔到 IP Speaker 的總入口。
    """

    playback_mode = get_broadcast_playback_mode()

    if playback_mode == PLAYBACK_MODE_SIMULATION:
        return simulate_play_audio_to_speaker(
            speaker=speaker,
            audio_file=audio_file,
            broadcast_log=broadcast_log,
        )

    if playback_mode == PLAYBACK_MODE_MICROSIP_WINSOUND:
        return play_audio_via_microsip_winsound(
            speaker=speaker,
            audio_file=audio_file,
            broadcast_log=broadcast_log,
        )

    return {
        "success": False,
        "mode": playback_mode,
        "broadcast_log_id": broadcast_log.id,
        "reason": "unsupported_playback_mode",
        "message": f"Unsupported BROADCAST_PLAYBACK_MODE: {playback_mode}",
    }


def simulate_play_audio_to_speaker(speaker, audio_file, broadcast_log):
    """
    模擬播放音檔到 IP Speaker。
    """

    return {
        "success": True,
        "mode": PLAYBACK_MODE_SIMULATION,
        "broadcast_log_id": broadcast_log.id,
        "speaker_code": speaker.speaker_code,
        "speaker_endpoint": speaker.endpoint_base_url,
        "resolved_sip_uri": speaker.resolved_sip_uri,
        "audio_code": audio_file.audio_code,
        "audio_file": audio_file.file.name if audio_file.file else "",
        "played_at": timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M:%S"),
        "message": "Simulation playback completed successfully.",
    }


def play_audio_via_microsip_winsound(speaker, audio_file, broadcast_log):
    """
    使用 MicroSIP + winsound 播放 wav 音檔到 SIP Speaker。

    流程：
    1. 使用 Windows SIP URI handler 呼叫 MicroSIP 撥號。
    2. 等待 MicroSIP 建立通話。
    3. 使用 winsound 同步播放 wav 音檔。
    4. 播放結束後等待 margin。
    5. 嘗試自動掛斷 MicroSIP。

    前提：
    1. Windows 環境。
    2. MicroSIP 已安裝並註冊 sip: URI handler。
    3. MicroSIP 麥克風來源需設定為 Stereo Mix 或 CABLE Output。
    4. 目前第一版只支援 wav 音檔。
    """

    if sys.platform != "win32":
        return {
            "success": False,
            "mode": PLAYBACK_MODE_MICROSIP_WINSOUND,
            "broadcast_log_id": broadcast_log.id,
            "reason": "unsupported_platform",
            "message": "microsip_winsound mode only supports Windows.",
        }

    sip_uri = speaker.resolved_sip_uri

    if not sip_uri:
        return {
            "success": False,
            "mode": PLAYBACK_MODE_MICROSIP_WINSOUND,
            "broadcast_log_id": broadcast_log.id,
            "reason": "sip_uri_missing",
            "message": "Speaker SIP URI is missing.",
        }

    audio_path_result = get_audio_file_absolute_path(audio_file)

    if not audio_path_result["success"]:
        return {
            "success": False,
            "mode": PLAYBACK_MODE_MICROSIP_WINSOUND,
            "broadcast_log_id": broadcast_log.id,
            **audio_path_result,
        }

    audio_path = Path(audio_path_result["audio_path"])

    if audio_path.suffix.lower() != ".wav":
        return {
            "success": False,
            "mode": PLAYBACK_MODE_MICROSIP_WINSOUND,
            "broadcast_log_id": broadcast_log.id,
            "reason": "unsupported_audio_format",
            "audio_path": str(audio_path),
            "message": "microsip_winsound mode currently supports wav only. Please use a wav test audio file.",
        }

    duration_result = get_wav_duration_seconds(audio_path)

    if not duration_result["success"]:
        return {
            "success": False,
            "mode": PLAYBACK_MODE_MICROSIP_WINSOUND,
            "broadcast_log_id": broadcast_log.id,
            **duration_result,
        }

    dial_result = start_sip_call(sip_uri)

    if not dial_result["success"]:
        return {
            "success": False,
            "mode": PLAYBACK_MODE_MICROSIP_WINSOUND,
            "broadcast_log_id": broadcast_log.id,
            **dial_result,
        }

    play_delay = get_play_after_dial_delay_seconds()
    hangup_margin = get_hangup_after_audio_margin_seconds()

    time.sleep(play_delay)

    playback_result = play_wav_file_sync(audio_path)

    if not playback_result["success"]:
        return {
            "success": False,
            "mode": PLAYBACK_MODE_MICROSIP_WINSOUND,
            "broadcast_log_id": broadcast_log.id,
            "sip_uri": sip_uri,
            "audio_path": str(audio_path),
            **playback_result,
        }

    time.sleep(hangup_margin)

    hangup_result = hangup_microsip_call()

    return {
        "success": True,
        "mode": PLAYBACK_MODE_MICROSIP_WINSOUND,
        "broadcast_log_id": broadcast_log.id,

        "speaker_code": speaker.speaker_code,
        "speaker_name": speaker.name,
        "sip_uri": sip_uri,

        "audio_code": audio_file.audio_code,
        "audio_name": audio_file.name,
        "audio_path": str(audio_path),
        "audio_duration_seconds": duration_result["duration_seconds"],

        "play_after_dial_delay_seconds": play_delay,
        "hangup_after_audio_margin_seconds": hangup_margin,

        "dial_result": dial_result,
        "playback_result": playback_result,
        "hangup_result": hangup_result,

        "played_at": timezone.localtime(timezone.now()).strftime("%Y-%m-%d %H:%M:%S"),
        "message": "MicroSIP winsound playback completed successfully.",
    }


def get_audio_file_absolute_path(audio_file):
    """
    取得 AudioFile 的本機絕對路徑。
    """

    if not audio_file.file:
        return {
            "success": False,
            "reason": "audio_file_empty",
            "message": "AudioFile.file is empty.",
        }

    try:
        audio_path = Path(audio_file.file.path)
    except NotImplementedError:
        return {
            "success": False,
            "reason": "audio_storage_not_local",
            "message": "Audio file storage does not provide a local file path.",
        }

    if not audio_path.exists():
        return {
            "success": False,
            "reason": "audio_file_not_found",
            "audio_path": str(audio_path),
            "message": f"Audio file not found: {audio_path}",
        }

    if not audio_path.is_file():
        return {
            "success": False,
            "reason": "audio_path_is_not_file",
            "audio_path": str(audio_path),
            "message": f"Audio path is not a file: {audio_path}",
        }

    return {
        "success": True,
        "audio_path": str(audio_path),
    }


def get_wav_duration_seconds(audio_path):
    """
    讀取 wav 音檔長度。
    """

    try:
        with wave.open(str(audio_path), "rb") as wav_file:
            frames = wav_file.getnframes()
            frame_rate = wav_file.getframerate()

            if frame_rate <= 0:
                return {
                    "success": False,
                    "reason": "invalid_wav_frame_rate",
                    "audio_path": str(audio_path),
                    "message": "Invalid wav frame rate.",
                }

            duration_seconds = frames / float(frame_rate)

            return {
                "success": True,
                "duration_seconds": round(duration_seconds, 3),
            }

    except (wave.Error, OSError) as exc:
        return {
            "success": False,
            "reason": "read_wav_duration_failed",
            "audio_path": str(audio_path),
            "message": f"Failed to read wav duration: {exc}",
        }


def start_sip_call(sip_uri):
    """
    使用 Windows SIP URI handler 啟動 MicroSIP 撥號。
    """

    try:
        subprocess.Popen(
            ["cmd", "/c", "start", "", sip_uri],
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as exc:
        return {
            "success": False,
            "reason": "start_sip_call_failed",
            "sip_uri": sip_uri,
            "message": f"Failed to start SIP call: {exc}",
        }

    return {
        "success": True,
        "sip_uri": sip_uri,
        "message": "SIP call request sent.",
    }


def play_wav_file_sync(audio_path):
    """
    使用 winsound 同步播放 wav 音檔。
    """

    try:
        import winsound

        winsound.PlaySound(
            str(audio_path),
            winsound.SND_FILENAME,
        )

    except RuntimeError as exc:
        return {
            "success": False,
            "reason": "winsound_play_failed",
            "audio_path": str(audio_path),
            "message": f"winsound playback failed: {exc}",
        }

    except OSError as exc:
        return {
            "success": False,
            "reason": "audio_file_os_error",
            "audio_path": str(audio_path),
            "message": f"Audio file OS error: {exc}",
        }

    return {
        "success": True,
        "audio_path": str(audio_path),
        "message": "wav playback completed.",
    }


def hangup_microsip_call():
    """
    嘗試掛斷 MicroSIP。

    優先：
    microsip.exe /hangupall

    備援：
    PowerShell AppActivate('MicroSIP') + ESC
    """

    command_result = try_microsip_hangup_command()

    if command_result["success"]:
        return command_result

    escape_result = try_send_escape_to_microsip()

    if escape_result["success"]:
        return escape_result

    return {
        "success": False,
        "reason": "hangup_failed",
        "command_result": command_result,
        "escape_result": escape_result,
        "message": "Failed to hang up MicroSIP automatically. Please hang up manually.",
    }


def try_microsip_hangup_command():
    """
    使用 microsip.exe /hangupall 掛斷所有通話。
    """

    microsip_exe = find_microsip_exe_path()

    if microsip_exe is None:
        return {
            "success": False,
            "reason": "microsip_exe_not_found",
            "checked_paths": get_microsip_paths(),
            "message": "MicroSIP exe not found. Cannot run /hangupall.",
        }

    try:
        subprocess.Popen(
            [str(microsip_exe), "/hangupall"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    except OSError as exc:
        return {
            "success": False,
            "reason": "microsip_hangup_command_failed",
            "microsip_exe": str(microsip_exe),
            "message": f"Failed to run MicroSIP hangup command: {exc}",
        }

    return {
        "success": True,
        "method": "microsip_hangupall",
        "microsip_exe": str(microsip_exe),
        "message": "MicroSIP /hangupall command sent.",
    }


def try_send_escape_to_microsip():
    """
    備援掛斷方式：
    使用 PowerShell 啟用 MicroSIP 視窗並送 ESC。
    """

    command = (
        "$ws = New-Object -ComObject WScript.Shell; "
        "if ($ws.AppActivate('MicroSIP')) { "
        "Start-Sleep -Milliseconds 200; "
        "$ws.SendKeys('{ESC}'); "
        "exit 0 "
        "} else { "
        "exit 1 "
        "}"
    )

    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
        )

    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "success": False,
            "reason": "send_escape_failed",
            "message": f"Failed to send ESC to MicroSIP: {exc}",
        }

    if result.returncode == 0:
        return {
            "success": True,
            "method": "powershell_send_escape",
            "message": "ESC sent to MicroSIP window.",
        }

    return {
        "success": False,
        "reason": "microsip_window_not_found",
        "message": "MicroSIP window not found. Cannot send ESC.",
    }


def find_microsip_exe_path():
    """
    從設定路徑中找出 microsip.exe。

    注意：
    .lnk 可以用來開啟 MicroSIP，但不能可靠地執行 /hangupall。
    所以掛斷指令只使用 .exe。
    """

    for path_text in get_microsip_paths():
        path = Path(path_text)

        if path.exists() and path.suffix.lower() == ".exe":
            return path

    return None


def get_microsip_paths():
    """
    取得 MicroSIP 可能路徑。
    """

    return getattr(
        settings,
        "BROADCAST_MICROSIP_PATHS",
        DEFAULT_MICROSIP_PATHS,
    )


def get_broadcast_playback_mode():
    """
    取得播放模式。
    """

    return getattr(
        settings,
        "BROADCAST_PLAYBACK_MODE",
        DEFAULT_PLAYBACK_MODE,
    )


def get_play_after_dial_delay_seconds():
    """
    撥號後等待多久才播放音檔。
    """

    value = getattr(
        settings,
        "BROADCAST_PLAY_AFTER_DIAL_DELAY_SECONDS",
        DEFAULT_PLAY_AFTER_DIAL_DELAY_SECONDS,
    )

    try:
        return max(0, float(value))
    except (TypeError, ValueError):
        return DEFAULT_PLAY_AFTER_DIAL_DELAY_SECONDS


def get_hangup_after_audio_margin_seconds():
    """
    音檔播放結束後，等待多久再掛斷。
    """

    value = getattr(
        settings,
        "BROADCAST_HANGUP_AFTER_AUDIO_MARGIN_SECONDS",
        DEFAULT_HANGUP_AFTER_AUDIO_MARGIN_SECONDS,
    )

    try:
        return max(0, float(value))
    except (TypeError, ValueError):
        return DEFAULT_HANGUP_AFTER_AUDIO_MARGIN_SECONDS


def mark_broadcast_success(log, message, response_payload=None):
    """
    將 BroadcastLog 標記為 success。
    """

    log.status = BroadcastLog.STATUS_SUCCESS
    log.finished_at = timezone.now()
    log.message = message
    log.response_payload = response_payload or {}
    log.save(
        update_fields=[
            "status",
            "finished_at",
            "message",
            "response_payload",
            "updated_at",
        ]
    )

    return {
        "broadcast_log_id": log.id,
        "status": log.status,
        "message": message,
        "speaker_code": log.speaker.speaker_code if log.speaker else "",
        "audio_code": log.audio_file.audio_code if log.audio_file else "",
    }


def mark_broadcast_failed(log, message, response_payload=None):
    """
    將 BroadcastLog 標記為 failed。
    """

    log.status = BroadcastLog.STATUS_FAILED
    log.finished_at = timezone.now()
    log.message = message
    log.response_payload = response_payload or {}
    log.save(
        update_fields=[
            "status",
            "finished_at",
            "message",
            "response_payload",
            "updated_at",
        ]
    )

    return {
        "broadcast_log_id": log.id,
        "status": log.status,
        "message": message,
        "speaker_code": log.speaker.speaker_code if log.speaker else "",
        "audio_code": log.audio_file.audio_code if log.audio_file else "",
    }

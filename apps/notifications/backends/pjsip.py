import ipaddress
import re
import socket
import subprocess
import time
import wave
from dataclasses import dataclass
from pathlib import Path


SIP_URI_PATTERN = re.compile(
    r"^sip:(?P<user>[^@:\s]+)@(?P<host>[^:\s]+)(?::(?P<port>\d{1,5}))?$",
    re.IGNORECASE,
)


class PjsipPreflightError(RuntimeError):
    """Raised when a PJSIP dry-run validation fails."""


@dataclass(frozen=True)
class PjsipPlaybackPlan:
    executable_path: Path
    audio_path: Path
    log_path: Path
    target_uri: str
    local_ip: str
    advertise_ip: str
    local_sip_port: int
    local_rtp_port: int
    audio_duration_seconds: float
    command: tuple[str, ...]

    def command_text(self) -> str:
        return subprocess.list2cmdline(list(self.command))


@dataclass(frozen=True)
class PjsipPlaybackResult:
    success: bool
    message: str
    log_path: Path
    confirmed: bool
    media_active: bool
    disconnected: bool
    return_code: int | None


def build_pjsip_playback_plan(
    *,
    executable_path,
    audio_path,
    log_path,
    speaker_ip,
    sip_uri,
    local_ip,
    advertise_ip,
    local_sip_port,
    local_rtp_port,
    disabled_codecs=(),
    log_level=5,
    app_log_level=4,
    check_ports=True,
):
    """Validate inputs and build a PJSUA command without executing it."""

    executable_path = Path(executable_path)
    audio_path = Path(audio_path)
    log_path = Path(log_path)

    _validate_executable(executable_path)
    duration_seconds = _validate_wav(audio_path)

    speaker_ip = _validate_ip(speaker_ip, "Speaker IP")
    local_ip = _validate_ip(local_ip, "PJSIP local IP")
    advertise_ip = _validate_ip(advertise_ip or local_ip, "PJSIP advertise IP")
    target_uri = _validate_sip_uri(sip_uri, speaker_ip)

    local_sip_port = _validate_port(local_sip_port, "Local SIP port")
    local_rtp_port = _validate_port(local_rtp_port, "Local RTP port")

    if local_sip_port == local_rtp_port:
        raise PjsipPreflightError("Local SIP and RTP ports must be different.")

    if check_ports:
        _assert_udp_port_available(local_ip, local_sip_port, "SIP")
        _assert_udp_port_available(local_ip, local_rtp_port, "RTP")

    contact = f"sip:{advertise_ip}:{local_sip_port};ob"
    command = [
        str(executable_path),
        f"--log-file={log_path}",
        f"--log-level={int(log_level)}",
        f"--app-log-level={int(app_log_level)}",
        "--no-tcp",
        f"--local-port={local_sip_port}",
        f"--ip-addr={advertise_ip}",
        f"--bound-addr={local_ip}",
        f"--id=sip:{advertise_ip}",
        f"--contact={contact}",
        f"--rtp-port={local_rtp_port}",
        "--ptime=20",
        "--no-vad",
        "--clock-rate=8000",
        "--snd-clock-rate=8000",
    ]

    for codec in disabled_codecs:
        codec = str(codec).strip()
        if codec:
            command.append(f"--dis-codec={codec}")

    command.extend(
        [
            "--null-audio",
            f"--play-file={audio_path}",
            "--auto-play",
            "--auto-play-hangup",
            target_uri,
        ]
    )

    return PjsipPlaybackPlan(
        executable_path=executable_path,
        audio_path=audio_path,
        log_path=log_path,
        target_uri=target_uri,
        local_ip=local_ip,
        advertise_ip=advertise_ip,
        local_sip_port=local_sip_port,
        local_rtp_port=local_rtp_port,
        audio_duration_seconds=duration_seconds,
        command=tuple(command),
    )


def execute_pjsip_playback_plan(plan, extra_wait_seconds=8.0):
    """Execute one pre-built plan and verify SIP/media success in its log."""

    plan.log_path.parent.mkdir(parents=True, exist_ok=True)
    plan.log_path.write_text("", encoding="utf-8")
    timeout = plan.audio_duration_seconds + max(2.0, float(extra_wait_seconds))
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    try:
        process = subprocess.Popen(
            list(plan.command),
            cwd=str(plan.executable_path.parent),
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            creationflags=creation_flags,
        )
    except OSError as exc:
        raise PjsipPreflightError(f"Failed to start PJSUA: {exc}") from exc

    deadline = time.monotonic() + timeout
    confirmed = False
    media_active = False
    disconnected = False

    try:
        while time.monotonic() < deadline:
            log_text = _read_log(plan.log_path)
            confirmed = confirmed or "Call 0 state changed to CONFIRMED" in log_text
            media_active = media_active or (
                "status is Active" in log_text and "PCMU" in log_text
            )
            disconnected = disconnected or (
                "Call 0 is DISCONNECTED [reason=200 (OK)]" in log_text
            )

            failure = _find_call_failure(log_text)
            if failure:
                _stop_process(process)
                return PjsipPlaybackResult(
                    success=False,
                    message=failure,
                    log_path=plan.log_path,
                    confirmed=confirmed,
                    media_active=media_active,
                    disconnected=disconnected,
                    return_code=process.poll(),
                )

            if confirmed and media_active and disconnected:
                _stop_process(process)
                return PjsipPlaybackResult(
                    success=True,
                    message="PJSIP call confirmed, PCMU media active, and call disconnected normally.",
                    log_path=plan.log_path,
                    confirmed=True,
                    media_active=True,
                    disconnected=True,
                    return_code=process.poll(),
                )

            if process.poll() is not None:
                break

            time.sleep(0.2)
    finally:
        if process.poll() is None:
            _stop_process(process)

    log_text = _read_log(plan.log_path)
    confirmed = confirmed or "Call 0 state changed to CONFIRMED" in log_text
    media_active = media_active or (
        "status is Active" in log_text and "PCMU" in log_text
    )
    disconnected = disconnected or (
        "Call 0 is DISCONNECTED [reason=200 (OK)]" in log_text
    )
    failure = _find_call_failure(log_text)

    if failure:
        message = failure
    elif process.returncode is not None and process.returncode != 0:
        message = f"PJSUA exited with code {process.returncode}."
    else:
        message = (
            "PJSIP playback verification timed out or required success markers "
            "were not found."
        )

    return PjsipPlaybackResult(
        success=False,
        message=message,
        log_path=plan.log_path,
        confirmed=confirmed,
        media_active=media_active,
        disconnected=disconnected,
        return_code=process.returncode,
    )


def _validate_executable(executable_path):
    if not executable_path.is_file():
        raise PjsipPreflightError(f"PJSUA executable not found: {executable_path}")

    required_dlls = (
        executable_path.parent / "libssl-3-x64.dll",
        executable_path.parent / "libcrypto-3-x64.dll",
    )
    missing = [str(path) for path in required_dlls if not path.is_file()]
    if missing:
        raise PjsipPreflightError(
            "PJSUA OpenSSL dependencies are missing: " + ", ".join(missing)
        )


def _validate_wav(audio_path):
    if not audio_path.is_file():
        raise PjsipPreflightError(f"Audio file not found: {audio_path}")
    if audio_path.suffix.lower() != ".wav":
        raise PjsipPreflightError("PJSIP playback currently supports WAV files only.")

    try:
        with wave.open(str(audio_path), "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_rate = wav_file.getframerate()
            sample_width = wav_file.getsampwidth()
            frames = wav_file.getnframes()
    except (OSError, wave.Error) as exc:
        raise PjsipPreflightError(f"Cannot read WAV file: {exc}") from exc

    if channels != 1 or sample_rate != 8000 or sample_width != 2:
        raise PjsipPreflightError(
            "WAV must be mono, 8000 Hz, 16-bit PCM. "
            f"Received channels={channels}, rate={sample_rate}, width={sample_width}."
        )
    if frames <= 0:
        raise PjsipPreflightError("WAV file contains no audio frames.")

    return round(frames / float(sample_rate), 3)


def _validate_ip(value, label):
    value = str(value or "").strip()
    if not value:
        raise PjsipPreflightError(f"{label} is required.")
    try:
        return str(ipaddress.ip_address(value))
    except ValueError as exc:
        raise PjsipPreflightError(f"{label} is invalid: {value}") from exc


def _validate_sip_uri(value, expected_ip):
    value = str(value or "").strip()
    match = SIP_URI_PATTERN.fullmatch(value)
    if not match:
        raise PjsipPreflightError(
            "SIP URI must use the form sip:user@ip:port."
        )

    uri_ip = _validate_ip(match.group("host"), "SIP URI host")
    if uri_ip != expected_ip:
        raise PjsipPreflightError(
            f"SIP URI host {uri_ip} does not match Speaker IP {expected_ip}."
        )

    port = _validate_port(match.group("port") or 5060, "Speaker SIP port")
    return f"sip:{match.group('user')}@{uri_ip}:{port}"


def _validate_port(value, label):
    try:
        value = int(value)
    except (TypeError, ValueError) as exc:
        raise PjsipPreflightError(f"{label} must be an integer.") from exc
    if not 1 <= value <= 65535:
        raise PjsipPreflightError(f"{label} must be between 1 and 65535.")
    return value


def _assert_udp_port_available(local_ip, port, label):
    udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        udp_socket.bind((local_ip, port))
    except OSError as exc:
        raise PjsipPreflightError(
            f"Local {label} UDP port {local_ip}:{port} is unavailable: {exc}"
        ) from exc
    finally:
        udp_socket.close()


def _read_log(log_path):
    try:
        return log_path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _find_call_failure(log_text):
    checks = (
        ("WSAEADDRINUSE", "PJSIP local SIP or RTP port is already in use."),
        ("Address already in use", "PJSIP local SIP or RTP port is already in use."),
        ("bind() error", "PJSIP could not bind the configured local port."),
        ("Response msg 404/INVITE", "Speaker returned SIP 404 Not Found."),
        ("Response msg 408/INVITE", "Speaker call timed out with SIP 408."),
        ("Response msg 480/INVITE", "Speaker is temporarily unavailable (SIP 480)."),
        ("Response msg 486/INVITE", "Speaker is busy (SIP 486)."),
        ("Response msg 503/INVITE", "Speaker service is unavailable (SIP 503)."),
    )
    for marker, message in checks:
        if marker in log_text:
            return message
    return None


def _stop_process(process):
    if process.poll() is not None:
        return
    try:
        if process.stdin:
            process.stdin.write("h\nq\n")
            process.stdin.flush()
        process.wait(timeout=4)
    except (OSError, subprocess.TimeoutExpired):
        process.terminate()
        try:
            process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)

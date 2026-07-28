import ipaddress
import re
import socket
import struct
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
    """Raised when a PJSIP dry-run validation or startup fails."""


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
    audio_gain_percent: float = 100.0

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
    preferred_codec="",
    log_level=5,
    app_log_level=4,
    audio_gain_percent=100.0,
    check_ports=True,
):
    """Validate inputs and build a PJSUA command without placing a call."""

    executable_path = Path(executable_path)
    source_audio_path = Path(audio_path)
    log_path = Path(log_path)

    _validate_executable(executable_path)
    source_duration_seconds = _validate_wav(source_audio_path)

    gain_percent = _validate_gain(audio_gain_percent)
    prepared_audio_path = _prepare_audio_file(
        source_audio_path,
        log_path.parent,
        gain_percent,
    )
    duration_seconds = (
        source_duration_seconds
        if prepared_audio_path == source_audio_path
        else _validate_wav(prepared_audio_path)
    )

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

    preferred_codec = str(preferred_codec or "").strip()
    if preferred_codec and preferred_codec.upper() != "PCMU/8000":
        command.append(f"--add-codec={preferred_codec}")

    for codec in disabled_codecs:
        codec = str(codec).strip()
        if codec:
            command.append(f"--dis-codec={codec}")

    command.extend(
        [
            "--null-audio",
            f"--play-file={prepared_audio_path}",
            "--auto-play",
            "--auto-play-hangup",
            target_uri,
        ]
    )

    return PjsipPlaybackPlan(
        executable_path=executable_path,
        audio_path=prepared_audio_path,
        log_path=log_path,
        target_uri=target_uri,
        local_ip=local_ip,
        advertise_ip=advertise_ip,
        local_sip_port=local_sip_port,
        local_rtp_port=local_rtp_port,
        audio_duration_seconds=duration_seconds,
        audio_gain_percent=gain_percent,
        command=tuple(command),
    )


def execute_pjsip_playback_plan(plan, extra_wait_seconds=8.0):
    """Execute one plan and verify SIP/media progress from the PJSUA log."""

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
        raise PjsipPreflightError(_format_startup_error(exc, plan.executable_path)) from exc

    # The verified standalone implementation waits briefly and reports an
    # immediate process exit. This exposes WDAC, missing runtime, and invalid
    # command failures before waiting for the whole audio timeout.
    time.sleep(0.5)
    if process.poll() is not None:
        log_text = _read_log(plan.log_path)
        failure = _find_call_failure(log_text)
        message = failure or (
            f"PJSUA exited immediately with code {process.returncode}. "
            f"Check {plan.log_path}."
        )
        return PjsipPlaybackResult(
            success=False,
            message=message,
            log_path=plan.log_path,
            confirmed=False,
            media_active=False,
            disconnected=False,
            return_code=process.returncode,
        )

    deadline = time.monotonic() + timeout
    confirmed = False
    media_active = False
    disconnected = False

    try:
        while time.monotonic() < deadline:
            log_text = _read_log(plan.log_path)
            confirmed = confirmed or _log_has_confirmed(log_text)
            media_active = media_active or _log_has_media_active(log_text)
            disconnected = disconnected or _log_has_disconnected(log_text)

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

            # A normal verified call may finish before every PJSUA build emits
            # exactly the same disconnect wording. Confirmed + active media is
            # therefore sufficient when the process exits with code 0.
            if process.poll() is not None:
                break

            if confirmed and media_active and disconnected:
                _stop_process(process)
                return PjsipPlaybackResult(
                    success=True,
                    message="PJSIP call confirmed, audio media active, and call disconnected normally.",
                    log_path=plan.log_path,
                    confirmed=True,
                    media_active=True,
                    disconnected=True,
                    return_code=process.poll(),
                )

            time.sleep(0.2)
    finally:
        if process.poll() is None:
            _stop_process(process)

    log_text = _read_log(plan.log_path)
    confirmed = confirmed or _log_has_confirmed(log_text)
    media_active = media_active or _log_has_media_active(log_text)
    disconnected = disconnected or _log_has_disconnected(log_text)
    failure = _find_call_failure(log_text)

    if failure:
        message = failure
        success = False
    elif confirmed and media_active and process.returncode in (None, 0):
        message = "PJSIP call confirmed and audio media became active."
        success = True
    elif process.returncode is not None and process.returncode != 0:
        message = f"PJSUA exited with code {process.returncode}. Check {plan.log_path}."
        success = False
    else:
        message = (
            "PJSIP playback verification timed out or required call/media "
            "markers were not found."
        )
        success = False

    return PjsipPlaybackResult(
        success=success,
        message=message,
        log_path=plan.log_path,
        confirmed=confirmed,
        media_active=media_active,
        disconnected=disconnected,
        return_code=process.returncode,
    )


def _validate_executable(executable_path):
    """Validate only the executable itself.

    The verified speaker package ships a standalone pjsua.exe without the two
    OpenSSL DLL files previously hard-coded by the Django adapter. Windows is
    allowed to report any real runtime dependency when the process starts.
    """

    if not executable_path.is_file():
        raise PjsipPreflightError(f"PJSUA executable not found: {executable_path}")


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
            compression = wav_file.getcomptype()
            frames = wav_file.getnframes()
    except (OSError, wave.Error) as exc:
        raise PjsipPreflightError(f"Cannot read WAV file: {exc}") from exc

    if channels != 1 or sample_rate != 8000 or sample_width != 2 or compression != "NONE":
        raise PjsipPreflightError(
            "WAV must be mono, 8000 Hz, 16-bit uncompressed PCM. "
            f"Received channels={channels}, rate={sample_rate}, "
            f"width={sample_width}, compression={compression}."
        )
    if frames <= 0:
        raise PjsipPreflightError("WAV file contains no audio frames.")

    return round(frames / float(sample_rate), 3)


def _validate_gain(value):
    try:
        value = float(value)
    except (TypeError, ValueError) as exc:
        raise PjsipPreflightError("PJSIP audio gain must be numeric.") from exc
    return max(0.0, min(200.0, value))


def _prepare_audio_file(audio_path, output_dir, gain_percent):
    if abs(gain_percent - 100.0) < 0.01:
        return audio_path

    output_dir.mkdir(parents=True, exist_ok=True)
    safe_gain = str(round(gain_percent, 2)).replace(".", "_")
    output_path = output_dir / f"_pjsua_gain_{safe_gain}_{audio_path.name}"

    try:
        with wave.open(str(audio_path), "rb") as source:
            params = source.getparams()
            frames = source.readframes(source.getnframes())

        samples = struct.unpack(f"<{len(frames) // 2}h", frames)
        factor = gain_percent / 100.0
        adjusted = [max(-32768, min(32767, int(sample * factor))) for sample in samples]
        output_frames = struct.pack(f"<{len(adjusted)}h", *adjusted)

        with wave.open(str(output_path), "wb") as target:
            target.setparams(params)
            target.writeframes(output_frames)
    except (OSError, wave.Error, struct.error) as exc:
        raise PjsipPreflightError(f"Unable to prepare gain-adjusted WAV: {exc}") from exc

    return output_path


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
        raise PjsipPreflightError("SIP URI must use the form sip:user@ip:port.")

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


def _log_has_confirmed(text):
    return "state changed to CONFIRMED" in text or "CONFIRMED" in text


def _log_has_media_active(text):
    return (
        ("status is Active" in text or "media is active" in text.lower())
        and ("PCMU" in text or "ulaw" in text.lower())
    )


def _log_has_disconnected(text):
    return (
        "Call 0 is DISCONNECTED" in text
        or "Response msg 200/BYE" in text
        or "DISCONNECTED [reason=200" in text
    )


def _find_call_failure(log_text):
    checks = (
        ("WSAEADDRINUSE", "PJSIP local SIP or RTP port is already in use."),
        ("Address already in use", "PJSIP local SIP or RTP port is already in use."),
        ("bind() error", "PJSIP could not bind the configured local port."),
        ("Unable to open sound device", "PJSUA could not open the selected audio device."),
        ("Invalid audio device", "PJSUA audio device setting is invalid."),
        ("Response msg 401/INVITE", "Speaker returned SIP 401 Unauthorized."),
        ("Response msg 403/INVITE", "Speaker returned SIP 403 Forbidden."),
        ("Response msg 404/INVITE", "Speaker returned SIP 404 Not Found."),
        ("Response msg 408/INVITE", "Speaker call timed out with SIP 408."),
        ("Response msg 480/INVITE", "Speaker is temporarily unavailable (SIP 480)."),
        ("Response msg 486/INVITE", "Speaker is busy (SIP 486)."),
        ("Response msg 488/INVITE", "Speaker rejected the offered media/codec (SIP 488)."),
        ("Response msg 503/INVITE", "Speaker service is unavailable (SIP 503)."),
    )
    for marker, message in checks:
        if marker in log_text:
            return message
    return None


def _format_startup_error(exc, executable_path):
    text = str(exc)
    lower = text.lower()
    winerror = getattr(exc, "winerror", None)
    if winerror in (577, 1260) or "application control policy" in lower:
        return (
            "Windows Application Control/WDAC blocked pjsua.exe. "
            f"Request an allow rule or signed executable for: {executable_path}"
        )
    if winerror == 126 or "specified module could not be found" in lower:
        return (
            "Windows could not load pjsua.exe or one of its actual runtime dependencies. "
            f"Executable: {executable_path}. Original error: {exc}"
        )
    return f"Failed to start PJSUA: {exc}"


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

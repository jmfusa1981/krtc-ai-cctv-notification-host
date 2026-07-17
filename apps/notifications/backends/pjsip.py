import ipaddress
import re
import socket
import subprocess
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


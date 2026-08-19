import ipaddress
import re
import socket
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

SIP_URI_PATTERN = re.compile(
    r"^sip:(?P<user>[^@:\s]+)@(?P<host>[^:\s]+)(?::(?P<port>\d{1,5}))?$",
    re.IGNORECASE,
)


class PjsipMicrophoneError(RuntimeError):
    """Raised when live microphone PJSUA startup or validation fails."""


@dataclass(frozen=True)
class SpeakerTarget:
    speaker_code: str
    sip_uri: str


@dataclass(frozen=True)
class PjsipMultiMicrophonePlan:
    executable_path: Path
    log_path: Path
    targets: tuple[SpeakerTarget, ...]
    local_ip: str
    advertise_ip: str
    local_sip_port: int
    local_rtp_port: int
    cli_port: int
    capture_device: int
    playback_device: int
    volume_percent: int
    command: tuple[str, ...]

    def command_text(self) -> str:
        return subprocess.list2cmdline(list(self.command))


@dataclass
class PjsipCallResult:
    speaker_code: str
    sip_uri: str
    state: str = "connecting"
    call_id: int | None = None
    sip_status: str = ""
    message: str = ""
    confirmed: bool = False
    media_active: bool = False


@dataclass
class PjsipMultiMicrophoneRuntime:
    process: object
    cli: object
    results: dict[str, PjsipCallResult] = field(default_factory=dict)


def build_pjsip_multi_microphone_plan(
    *, executable_path, log_path, speakers, local_ip, advertise_ip,
    local_sip_port, local_rtp_port, cli_port, capture_device=-1,
    playback_device=-1, disabled_codecs=(), preferred_codec="",
    log_level=5, app_log_level=4, max_duration_seconds=300,
    volume_percent=100, check_ports=True,
):
    executable_path = Path(executable_path)
    log_path = Path(log_path)
    _validate_executable(executable_path)
    local_ip = _validate_ip(local_ip, "PJSIP local IP")
    advertise_ip = _validate_ip(advertise_ip or local_ip, "PJSIP advertise IP")
    local_sip_port = _validate_port(local_sip_port, "Local SIP port")
    local_rtp_port = _validate_port(local_rtp_port, "Local RTP port")
    cli_port = _validate_port(cli_port, "PJSUA CLI port")
    volume_percent = max(0, min(200, int(volume_percent)))
    if len({local_sip_port, local_rtp_port, cli_port}) != 3:
        raise PjsipMicrophoneError("SIP, RTP, and CLI ports must be different.")
    if check_ports:
        _assert_udp_port_available(local_ip, local_sip_port, "SIP")
        _assert_udp_port_available(local_ip, local_rtp_port, "RTP")
        _assert_tcp_port_available("127.0.0.1", cli_port, "CLI")

    targets=[]
    for speaker in speakers:
        speaker_ip=_validate_ip(speaker.ip_address, f"{speaker.speaker_code} IP")
        targets.append(SpeakerTarget(speaker.speaker_code, _validate_sip_uri(speaker.resolved_sip_uri, speaker_ip)))
    if not targets: raise PjsipMicrophoneError("At least one Speaker target is required.")
    max_duration_seconds=int(max_duration_seconds)
    if not 10 <= max_duration_seconds <= 3600:
        raise PjsipMicrophoneError("Live microphone duration must be between 10 and 3600 seconds.")

    contact=f"sip:{advertise_ip}:{local_sip_port};ob"
    command=[str(executable_path), f"--log-file={log_path}", f"--log-level={int(log_level)}",
        f"--app-log-level={int(app_log_level)}", "--no-color", "--no-tcp", "--no-tones",
        "--auto-conf", "--use-cli", f"--cli-telnet-port={cli_port}", "--no-cli-console",
        f"--max-calls={max(4,len(targets))}", f"--local-port={local_sip_port}",
        f"--ip-addr={advertise_ip}", f"--bound-addr={local_ip}", f"--id=sip:{advertise_ip}",
        f"--contact={contact}", f"--rtp-port={local_rtp_port}", "--ptime=20", "--no-vad",
        "--clock-rate=8000", "--snd-clock-rate=8000", f"--capture-dev={int(capture_device)}",
        f"--playback-dev={int(playback_device)}", f"--duration={max_duration_seconds}"]
    preferred_codec=str(preferred_codec or '').strip()
    if preferred_codec and preferred_codec.upper() != 'PCMU/8000': command.append(f"--add-codec={preferred_codec}")
    for codec in disabled_codecs:
        codec=str(codec or '').strip()
        if codec: command.append(f"--dis-codec={codec}")
    return PjsipMultiMicrophonePlan(executable_path,log_path,tuple(targets),local_ip,advertise_ip,
        local_sip_port,local_rtp_port,cli_port,int(capture_device),int(playback_device),volume_percent,tuple(command))


class PjsuaCliClient:
    def __init__(self, port):
        self.port=port; self.sock=None
    def connect(self, timeout=8):
        deadline=time.monotonic()+timeout; last=None
        while time.monotonic()<deadline:
            try:
                self.sock=socket.create_connection(('127.0.0.1',self.port),timeout=1)
                self.sock.settimeout(0.5); self._drain(); return
            except OSError as exc: last=exc; time.sleep(0.2)
        raise PjsipMicrophoneError(f"Unable to connect to PJSUA CLI port {self.port}: {last}")
    def command(self, text):
        if not self.sock: raise PjsipMicrophoneError('PJSUA CLI is not connected.')
        self.sock.sendall((text.strip()+'\r\n').encode('utf-8'))
        time.sleep(0.08); return self._drain()
    def _drain(self):
        chunks=[]
        if not self.sock: return ''
        while True:
            try:
                data=self.sock.recv(4096)
                if not data: break
                # Remove common telnet negotiation bytes while preserving printable output.
                data=re.sub(rb'\xff[\xfb-\xfe].',b'',data)
                chunks.append(data)
            except socket.timeout: break
            except OSError: break
        return b''.join(chunks).decode('utf-8','replace')
    def close(self):
        if self.sock:
            try:self.sock.close()
            except OSError:pass
            self.sock=None


def start_pjsip_multi_microphone(plan, per_call_timeout=10):
    plan.log_path.parent.mkdir(parents=True,exist_ok=True); plan.log_path.write_text('',encoding='utf-8')
    creation_flags=getattr(subprocess,'CREATE_NO_WINDOW',0)
    try:
        process=subprocess.Popen(list(plan.command),cwd=str(plan.executable_path.parent),stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=creation_flags)
    except OSError as exc: raise PjsipMicrophoneError(f"Unable to start PJSUA microphone session: {exc}") from exc
    cli=PjsuaCliClient(plan.cli_port)
    runtime=PjsipMultiMicrophoneRuntime(process,cli,{t.speaker_code:PjsipCallResult(t.speaker_code,t.sip_uri) for t in plan.targets})
    try:
        cli.connect()
        _apply_volume(cli,plan.volume_percent)
        for target in plan.targets:
            if process.poll() is not None: break
            result=runtime.results[target.speaker_code]
            offset=_log_size(plan.log_path)
            cli.command(f"call new {target.sip_uri}")
            _wait_one_call(plan.log_path,offset,result,process,per_call_timeout)
        return runtime
    except Exception:
        stop_pjsip_runtime(runtime); raise


def _apply_volume(cli, volume_percent):
    # PJSUA CLI exposes 'audio adjust_vol'. Values are normalized where 1.0 = 100%.
    level=max(0.0,min(2.0,float(volume_percent)/100.0))
    response=cli.command(f"audio adjust_vol {level:.2f} {level:.2f}")
    if 'error' in response.lower() or 'invalid' in response.lower():
        # Older builds expose the shortcut with the same two arguments.
        cli.command(f"V {level:.2f} {level:.2f}")


def _wait_one_call(log_path,offset,result,process,timeout):
    deadline=time.monotonic()+timeout; last=''
    while time.monotonic()<deadline:
        if process.poll() is not None:
            result.state='failed'; result.message=f'PJSUA exited with code {process.returncode}'; return
        text=_read_log_from(log_path,offset); last=text; lower=text.lower()
        call_ids=re.findall(r'call\s+(\d+)',lower)
        if call_ids and result.call_id is None: result.call_id=int(call_ids[-1])
        status_match=re.search(r'\b(1\d\d|2\d\d|3\d\d|4\d\d|5\d\d|6\d\d)\b[^\n]*(ringing|ok|busy|timeout|not found|forbidden|unavailable)?',lower)
        if status_match: result.sip_status=status_match.group(0).strip()[:100]
        result.confirmed=bool(re.search(r'state changed to confirmed|\bconfirmed\b',lower))
        result.media_active=bool(re.search(r'media is active|status is active|media active|stream #\d+: audio|audio updated',lower))
        failure=_failure_message(lower)
        if result.confirmed and result.media_active:
            result.state='active'; result.message='SIP confirmed and audio media active.'; return
        if failure and not result.confirmed:
            result.state='failed'; result.message=failure; return
        time.sleep(0.2)
    result.state='failed'; result.message=_failure_message(last.lower()) or 'SIP/media connection timeout.'


def inspect_runtime(runtime, log_path):
    # Preserve per-target results collected at dial time; update global process state only.
    return {code:{'speaker_code':r.speaker_code,'sip_uri':r.sip_uri,'state':r.state,'call_id':r.call_id,
        'sip_status':r.sip_status,'message':r.message,'confirmed':r.confirmed,'media_active':r.media_active}
        for code,r in runtime.results.items()}


def stop_pjsip_runtime(runtime):
    if runtime is None:return
    try:
        if runtime.cli:
            try:runtime.cli.command('call hangup_all')
            except Exception:pass
            try:runtime.cli.command('shutdown')
            except Exception:pass
            runtime.cli.close()
    finally:
        process=runtime.process
        if process is not None and process.poll() is None:
            try:process.wait(timeout=3)
            except Exception:
                try:process.terminate(); process.wait(timeout=2)
                except Exception:
                    try:process.kill()
                    except Exception:pass


def _failure_message(lower):
    mapping=(('busy here','486 Busy Here'),('request timeout','408 Request Timeout'),('not found','404 Not Found'),
        ('forbidden','403 Forbidden'),('temporarily unavailable','480 Temporarily Unavailable'),
        ('unable to open sound device','Unable to open sound device'),('no suitable audio device','No suitable audio device'),
        ('error opening sound device','Error opening sound device'))
    for pattern,msg in mapping:
        if pattern in lower:return msg
    return ''

def _log_size(path):
    try:return Path(path).stat().st_size
    except OSError:return 0

def _read_log_from(path,offset):
    try:
        with Path(path).open('rb') as f:f.seek(offset); return f.read().decode('utf-8','replace')
    except OSError:return ''

def _validate_executable(path):
    if not path.is_file():raise PjsipMicrophoneError(f"PJSUA executable not found: {path}")
def _validate_ip(value,label):
    value=str(value or '').strip()
    if not value:raise PjsipMicrophoneError(f"{label} is required.")
    try:return str(ipaddress.ip_address(value))
    except ValueError as exc:raise PjsipMicrophoneError(f"Invalid {label}: {value}") from exc
def _validate_port(value,label):
    try:value=int(value)
    except (TypeError,ValueError) as exc:raise PjsipMicrophoneError(f"Invalid {label}: {value}") from exc
    if not 1<=value<=65535:raise PjsipMicrophoneError(f"Invalid {label}: {value}")
    return value
def _validate_sip_uri(value,expected_ip):
    value=str(value or '').strip(); match=SIP_URI_PATTERN.match(value)
    if not match:raise PjsipMicrophoneError(f"Invalid SIP URI: {value}")
    if match.group('host')!=expected_ip:raise PjsipMicrophoneError(f"SIP URI host {match.group('host')} does not match Speaker IP {expected_ip}.")
    if match.group('port'):_validate_port(match.group('port'),'SIP target port')
    return value
def _assert_udp_port_available(local_ip,port,label):
    sock=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    try:sock.bind((local_ip,port))
    except OSError as exc:raise PjsipMicrophoneError(f"Local {label} UDP port {port} is unavailable on {local_ip}: {exc}") from exc
    finally:sock.close()
def _assert_tcp_port_available(local_ip,port,label):
    sock=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
    try:sock.bind((local_ip,port))
    except OSError as exc:raise PjsipMicrophoneError(f"Local {label} TCP port {port} is unavailable: {exc}") from exc
    finally:sock.close()

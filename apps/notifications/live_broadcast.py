import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from django.conf import settings
from django.db import close_old_connections, transaction
from django.utils import timezone
from .backends.pjsip_microphone import (PjsipMicrophoneError,build_pjsip_multi_microphone_plan,
    inspect_runtime,start_pjsip_multi_microphone,stop_pjsip_runtime)
from .models import BroadcastLog
from .services import SOURCE_PRIORITY_LIVE, active_broadcast_logs_for_speakers, broadcast_log_priority, clear_stale_schedule_broadcast_locks, interrupt_lower_priority_broadcasts

@dataclass
class LiveSession:
    session_id:str; requested_by_id:int|None; requested_by_username:str; started_at:object
    max_duration_seconds:int; speaker_codes:list[str]; log_ids:list[int]; log_by_code:dict[str,int]
    log_path:Path; runtime:object; volume_percent:int; speaker_status:dict[str,dict]=field(default_factory=dict)
    stopping:bool=False

class LiveBroadcastManager:
    def __init__(self):
        self._lock=threading.RLock(); self._session=None; self._timer=None
    def status(self):
        with self._lock:
            self._recover_if_process_exited()
            if not self._session:return {'active':False}
            self._session.speaker_status=inspect_runtime(self._session.runtime,self._session.log_path)
            elapsed=max(0,int((timezone.now()-self._session.started_at).total_seconds()))
            active=[c for c,s in self._session.speaker_status.items() if s['state']=='active']
            failed=[c for c,s in self._session.speaker_status.items() if s['state']=='failed']
            return {'active':True,'session_id':self._session.session_id,
                'started_at':timezone.localtime(self._session.started_at).isoformat(),'elapsed_seconds':elapsed,
                'max_duration_seconds':self._session.max_duration_seconds,'speaker_codes':self._session.speaker_codes,
                'active_speakers':active,'failed_speakers':failed,'speaker_status':self._session.speaker_status,
                'volume_percent':self._session.volume_percent,'requested_by_username':self._session.requested_by_username}
    def start(self,speakers,user,volume_percent=100):
        with self._lock:
            self._recover_if_process_exited()
            if self._session:raise PjsipMicrophoneError('已有進行中的人聲廣播工作階段。')
            speakers=list(speakers); max_speakers=int(getattr(settings,'PJSIP_MIC_MAX_SPEAKERS',4))
            if not speakers:raise PjsipMicrophoneError('至少必須選擇一顆 Speaker。')
            if len(speakers)>max_speakers:raise PjsipMicrophoneError(f'人聲廣播一次最多選擇 {max_speakers} 顆 Speaker。')
            volume_percent=max(0,min(200,int(volume_percent)))
            self._clear_stale_live_logs()
            clear_stale_schedule_broadcast_locks()
            interrupt_lower_priority_broadcasts(speakers, SOURCE_PRIORITY_LIVE, 'live_microphone_start')
            busy=[log for log in active_broadcast_logs_for_speakers(speakers) if broadcast_log_priority(log)>=SOURCE_PRIORITY_LIVE]
            if busy:raise PjsipMicrophoneError('Speaker 忙碌中：'+', '.join(sorted({x.speaker.speaker_code for x in busy if x.speaker})))
            codecs={str(s.preferred_codec or 'PCMU/8000').strip() for s in speakers}
            if len(codecs)>1:raise PjsipMicrophoneError('多 Speaker 人聲廣播必須使用相同 Codec。')
            preferred_codec=next(iter(codecs)) if codecs else 'PCMU/8000'
            session_id=uuid.uuid4().hex; started_at=timezone.now(); max_duration=int(getattr(settings,'PJSIP_MIC_MAX_DURATION_SECONDS',300))
            local_ip=str(getattr(settings,'PJSIP_LOCAL_IP','') or '').strip(); advertise_ip=str(getattr(settings,'PJSIP_ADVERTISE_IP',local_ip) or '').strip()
            if not local_ip:raise PjsipMicrophoneError('PJSIP local IP is required.')
            logs=[]
            with transaction.atomic():
                for speaker in speakers:
                    logs.append(BroadcastLog.objects.create(speaker=speaker,audio_file=None,status=BroadcastLog.STATUS_PLAYING,
                        request_payload={'source':'live_microphone','session_id':session_id,'requested_by_id':getattr(user,'id',None),
                        'requested_by_username':user.get_username(),'speaker_code':speaker.speaker_code,
                        'capture_device':int(getattr(settings,'PJSIP_MIC_CAPTURE_DEVICE',-1)),'max_duration_seconds':max_duration,
                        'multi_speaker_count':len(speakers),'architecture':'single_pjsua_cli_multi_call','no_tones':True,
                        'volume_percent':volume_percent},message='即時人聲廣播正在建立 SIP 通話。',requested_at=started_at,started_at=started_at))
            sip_port=int(getattr(settings,'PJSIP_LOCAL_SIP_PORT_BASE',64882))+200
            rtp_port=int(getattr(settings,'PJSIP_LOCAL_RTP_PORT_BASE',4004))+200
            cli_port=int(getattr(settings,'PJSIP_MIC_CLI_PORT',23233))
            log_path=Path(getattr(settings,'PJSIP_LOG_DIR'))/'live_microphone'/f'live_{session_id}_multi.log'
            plan=build_pjsip_multi_microphone_plan(executable_path=getattr(settings,'PJSIP_EXECUTABLE_PATH'),log_path=log_path,
                speakers=speakers,local_ip=local_ip,advertise_ip=advertise_ip,local_sip_port=sip_port,local_rtp_port=rtp_port,
                cli_port=cli_port,capture_device=int(getattr(settings,'PJSIP_MIC_CAPTURE_DEVICE',-1)),
                playback_device=int(getattr(settings,'PJSIP_MIC_PLAYBACK_DEVICE',-1)),disabled_codecs=getattr(settings,'PJSIP_DISABLED_CODECS',()),
                preferred_codec=preferred_codec,log_level=int(getattr(settings,'PJSIP_LOG_LEVEL',5)),app_log_level=int(getattr(settings,'PJSIP_APP_LOG_LEVEL',4)),
                max_duration_seconds=max_duration,volume_percent=volume_percent)
            runtime=None
            try:
                runtime=start_pjsip_multi_microphone(plan,per_call_timeout=float(getattr(settings,'PJSIP_MIC_PER_CALL_TIMEOUT_SECONDS',10)))
                statuses=inspect_runtime(runtime,log_path); active=[c for c,s in statuses.items() if s['state']=='active']
                for log in logs:
                    st=statuses.get(log.speaker.speaker_code,{})
                    if st.get('state')=='active':
                        log.message='即時人聲廣播已連線。'; log.response_payload={'source':'live_microphone',**st,'volume_percent':volume_percent}; log.save(update_fields=['message','response_payload','updated_at'])
                    else:
                        log.status=BroadcastLog.STATUS_FAILED; log.message=st.get('message','SIP 呼叫失敗。'); log.finished_at=timezone.now();
                        log.response_payload={'source':'live_microphone',**st,'volume_percent':volume_percent}; log.save(update_fields=['status','message','finished_at','response_payload','updated_at'])
                if not active:raise PjsipMicrophoneError('所有 Speaker 均未建立可用的 SIP／音訊連線。')
                active_logs=[x for x in logs if x.speaker.speaker_code in active]
                session=LiveSession(session_id,getattr(user,'id',None),user.get_username(),started_at,max_duration,
                    [s.speaker_code for s in speakers],[x.id for x in active_logs],{x.speaker.speaker_code:x.id for x in active_logs},log_path,runtime,volume_percent,statuses)
                self._session=session; self._timer=threading.Timer(max_duration,self._timeout_stop,args=(session_id,)); self._timer.daemon=True; self._timer.start(); self._start_monitor(session_id)
                return self.status()
            except Exception as exc:
                stop_pjsip_runtime(runtime)
                now=timezone.now()
                for log in logs:
                    if log.status in [BroadcastLog.STATUS_PENDING,BroadcastLog.STATUS_PLAYING]:
                        log.status=BroadcastLog.STATUS_FAILED; log.message=str(exc); log.finished_at=now; log.save(update_fields=['status','message','finished_at','updated_at'])
                self._session=None; raise
    def stop(self,session_id=None,reason='manual_stop'):
        with self._lock:
            if not self._session:return {'active':False,'message':'目前沒有人聲廣播。'}
            if session_id and session_id!=self._session.session_id:raise PjsipMicrophoneError('人聲廣播工作階段識別碼不符。')
            session=self._session
            if session.stopping:return {'active':True,'message':'人聲廣播正在停止。'}
            session.stopping=True
            if self._timer:self._timer.cancel(); self._timer=None
            stop_pjsip_runtime(session.runtime)
            logs=list(BroadcastLog.objects.filter(pk__in=session.log_ids)); self._finish_logs(logs,'success',reason,'即時人聲廣播已停止。')
            result={'active':False,'session_id':session.session_id,'speaker_codes':session.speaker_codes,'end_reason':reason}; self._session=None; return result
    def _start_monitor(self,session_id):
        t=threading.Thread(target=self._monitor,args=(session_id,),name='krtc-live-microphone-monitor',daemon=True); t.start()
    def _monitor(self,session_id):
        close_old_connections()
        try:
            while True:
                time.sleep(1)
                with self._lock:
                    if not self._session or self._session.session_id!=session_id or self._session.stopping:return
                    if self._session.runtime.process.poll() is not None:self.stop(session_id=session_id,reason='process_error'); return
        finally:close_old_connections()
    def _timeout_stop(self,session_id):
        close_old_connections()
        try:self.stop(session_id=session_id,reason='timeout')
        finally:close_old_connections()
    def _recover_if_process_exited(self):
        if self._session and not self._session.stopping and self._session.runtime.process.poll() is not None:
            logs=list(BroadcastLog.objects.filter(pk__in=self._session.log_ids)); self._finish_logs(logs,'failed','process_error','PJSUA process ended unexpectedly.'); self._session=None
    def _clear_stale_live_logs(self):
        now=timezone.now()
        for log in BroadcastLog.objects.filter(status__in=[BroadcastLog.STATUS_PENDING,BroadcastLog.STATUS_PLAYING],request_payload__source='live_microphone'):
            log.status=BroadcastLog.STATUS_FAILED; log.message='前次人聲廣播未正常結束，已解除忙碌狀態。'; log.finished_at=now
            log.response_payload={'source':'live_microphone','end_reason':'server_restart','finished_at':now.isoformat()}; log.save(update_fields=['status','message','finished_at','response_payload','updated_at'])
    @staticmethod
    def _finish_logs(logs,outcome,reason,message):
        now=timezone.now(); status=BroadcastLog.STATUS_SUCCESS if outcome=='success' else BroadcastLog.STATUS_FAILED
        for log in logs:
            payload=dict(log.response_payload or {}); payload.update({'source':'live_microphone','end_reason':reason,'finished_at':now.isoformat(),
                'duration_seconds':max(0,int((now-log.started_at).total_seconds())) if log.started_at else None})
            log.status=status; log.response_payload=payload; log.message=message; log.finished_at=now; log.save(update_fields=['status','response_payload','message','finished_at','updated_at'])
live_broadcast_manager=LiveBroadcastManager()

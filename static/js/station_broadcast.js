(() => {
  const form = document.getElementById('manualBroadcastForm');
  if (!form) return;

  const scopeSelect = document.getElementById('broadcastScope');
  const areaFilter = document.getElementById('areaFilter');
  const speakerSelect = document.getElementById('speakerSelect');
  const audioSelect = document.getElementById('audioSelect');
  const preview = document.getElementById('selectionPreview');
  const submitButton = document.getElementById('broadcastSubmitButton');
  const clearButton = document.getElementById('clearSelectionButton');
  const statusBox = document.getElementById('broadcastStatus');
  const refreshButton = document.getElementById('refreshPageButton');
  const csrf = form.querySelector('[name=csrfmiddlewaretoken]').value;
  const manualVolume = document.getElementById('manualVolume');
  const manualVolumeValue = document.getElementById('manualVolumeValue');
  manualVolume?.addEventListener('input', () => { manualVolumeValue.textContent = `${manualVolume.value}%`; });

  const speakerOptions = () => [...speakerSelect.options].filter((option) => option.value);

  function selectedSpeakerOptions() {
    const scope = scopeSelect.value;
    if (scope === 'all') return speakerOptions();
    if (scope === 'area') {
      const area = areaFilter.value;
      return speakerOptions().filter((option) => area && option.dataset.area === area);
    }
    const selected = speakerSelect.selectedOptions[0];
    return selected?.value ? [selected] : [];
  }

  function updateSpeakerFilter() {
    const area = areaFilter.value;
    speakerOptions().forEach((option) => {
      option.hidden = Boolean(area && option.dataset.area !== area);
    });
    const selected = speakerSelect.selectedOptions[0];
    if (selected && selected.hidden) speakerSelect.value = '';
    updateScopeState();
  }

  function updateScopeState() {
    const scope = scopeSelect.value;
    speakerSelect.disabled = scope !== 'single';
    areaFilter.disabled = scope === 'all';
    speakerSelect.required = scope === 'single';
    updatePreview();
  }

  function updatePreview() {
    const targets = selectedSpeakerOptions();
    const audio = audioSelect.selectedOptions[0];
    const ready = targets.length > 0 && audioSelect.value;
    submitButton.disabled = !ready;

    if (!ready) {
      preview.innerHTML = '<strong>尚未完成選擇</strong><span>請選擇有效的廣播範圍與音檔。</span>';
      return;
    }

    const names = targets.map((option) => option.textContent.trim());
    const targetText = names.length <= 3
      ? names.join('、')
      : `${names.slice(0, 3).join('、')} 等 ${names.length} 顆 Speaker`;
    preview.innerHTML = `<strong>${targetText}</strong><span>播放：${audio.textContent.trim()}</span>`;
  }

  function setStatus(kind, title, message) {
    statusBox.className = `broadcast-status is-${kind}`;
    statusBox.innerHTML = `<strong>${title}</strong><span>${message}</span>`;
  }

  scopeSelect.addEventListener('change', updateScopeState);
  areaFilter.addEventListener('change', updateSpeakerFilter);
  speakerSelect.addEventListener('change', updatePreview);
  audioSelect.addEventListener('change', updatePreview);

  clearButton.addEventListener('click', () => {
    scopeSelect.value = 'single';
    areaFilter.value = '';
    speakerSelect.value = '';
    audioSelect.value = '';
    updateSpeakerFilter();
  });

  refreshButton?.addEventListener('click', () => location.reload());

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const targets = selectedSpeakerOptions();
    if (!targets.length || !audioSelect.value) return;

    const speakerIds = targets.map((option) => Number(option.value));
    submitButton.disabled = true;
    setStatus(
      'working',
      '廣播執行中',
      `正在對 ${speakerIds.length} 顆 Speaker 建立播放任務，請勿重複操作。`
    );

    try {
      const response = await fetch(form.dataset.submitUrl, {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf},
        body: JSON.stringify({speaker_ids: speakerIds, audio_file_id: Number(audioSelect.value),
          volume_percent: Number(manualVolume?.value || 100)})
      });
      const data = await response.json();
      if (!response.ok || !data.success) {
        const failed = data.failed_speakers?.length
          ? ` 失敗：${data.failed_speakers.join(', ')}`
          : '';
        throw new Error((data.message || '廣播失敗') + failed);
      }
      setStatus(
        'success',
        '廣播完成',
        `${data.successful_speakers.join(', ')} 已完成播放 ${data.audio_code}。`
      );
      setTimeout(() => location.reload(), 1200);
    } catch (error) {
      setStatus('error', '廣播失敗', error.message);
      submitButton.disabled = false;
    }
  });

  updateSpeakerFilter();
})();

(() => {
  const form = document.getElementById('broadcastScheduleForm');
  if (!form) return;

  const scheduleType = document.getElementById('scheduleType');
  const runAtField = document.getElementById('runAtField');
  const dailyTimeField = document.getElementById('dailyTimeField');
  const runAt = document.getElementById('scheduleRunAt');
  const dailyTime = document.getElementById('scheduleDailyTime');
  const status = document.getElementById('scheduleFormStatus');
  const csrf = form.querySelector('[name=csrfmiddlewaretoken]').value;

  function syncTypeFields() {
    const isDaily = scheduleType.value === 'daily';
    runAtField.hidden = isDaily;
    dailyTimeField.hidden = !isDaily;
    runAt.required = !isDaily;
    dailyTime.required = isDaily;
    if (isDaily) runAt.value = '';
    else dailyTime.value = '';
  }

  function showStatus(message, isError = false) {
    status.textContent = message;
    status.className = `schedule-form-status ${isError ? 'is-error' : 'is-success'}`;
  }

  scheduleType.addEventListener('change', syncTypeFields);
  syncTypeFields();

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const submit = form.querySelector('[type=submit]');
    submit.disabled = true;
    status.textContent = '正在建立排程…';
    status.className = 'schedule-form-status';
    try {
      const response = await fetch(form.dataset.createUrl, {
        method: 'POST',
        headers: {'X-CSRFToken': csrf},
        body: new FormData(form)
      });
      const data = await response.json();
      if (!response.ok || !data.success) {
        const errors = data.errors ? JSON.stringify(data.errors) : '';
        throw new Error(`${data.message || '建立失敗'} ${errors}`.trim());
      }
      showStatus(`排程已建立，下次執行：${data.next_run_at || '未啟用'}`);
      setTimeout(() => location.reload(), 800);
    } catch (error) {
      showStatus(error.message, true);
      submit.disabled = false;
    }
  });

  document.querySelectorAll('.schedule-toggle, .schedule-delete').forEach((button) => {
    button.addEventListener('click', async () => {
      if (button.classList.contains('schedule-delete') && !confirm('確定刪除此排程？')) return;
      button.disabled = true;
      try {
        const response = await fetch(button.dataset.url, {
          method: 'POST',
          headers: {'X-CSRFToken': csrf}
        });
        const data = await response.json();
        if (!response.ok || !data.success) throw new Error(data.message || '操作失敗');
        location.reload();
      } catch (error) {
        alert(error.message);
        button.disabled = false;
      }
    });
  });
})();

(() => {
  const form = document.getElementById('liveMicrophoneForm');
  if (!form) return;

  const speakerSelect = document.getElementById('liveSpeakerSelect');
  const startButton = document.getElementById('liveStartButton');
  const stopButton = document.getElementById('liveStopButton');
  const statusBox = document.getElementById('liveMicrophoneStatus');
  const badge = document.getElementById('liveMicrophoneBadge');
  const liveVolume = document.getElementById('liveVolume');
  const liveVolumeValue = document.getElementById('liveVolumeValue');
  liveVolume?.addEventListener('input', () => { liveVolumeValue.textContent = `${liveVolume.value}%`; });
  const csrf = form.querySelector('[name=csrfmiddlewaretoken]').value;
  const maxSpeakers = Number(form.dataset.maxSpeakers || 4);
  let activeSessionId = null;
  let statusTimer = null;

  function selectedIds() {
    return [...speakerSelect.selectedOptions]
      .map((option) => Number(option.value))
      .filter(Boolean);
  }

  function renderStatus(kind, title, message) {
    statusBox.className = `live-microphone-status is-${kind}`;
    statusBox.innerHTML = `<strong>${title}</strong><span>${message}</span>`;
    badge.className = `live-status-badge is-${kind}`;
    badge.textContent = kind === 'active' ? '廣播中' : kind === 'error' ? '異常' : '待命';
  }

  function syncButtons(active = Boolean(activeSessionId)) {
    const count = selectedIds().length;
    startButton.disabled = active || count < 1 || count > maxSpeakers;
    stopButton.disabled = !active;
    speakerSelect.disabled = active;
  }

  async function loadStatus() {
    try {
      const response = await fetch(form.dataset.statusUrl, {credentials: 'same-origin'});
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.message || '無法讀取狀態');
      if (data.active) {
        activeSessionId = data.session_id;
        const speakers = (data.speaker_codes || []).join(', ');
        renderStatus(
          'active',
          '即時人聲廣播中',
          `${speakers}｜已進行 ${data.elapsed_seconds || 0} 秒｜請使用停止按鈕結束。`
        );
      } else {
        activeSessionId = null;
        renderStatus('idle', '尚未開始', '請選擇 Speaker，再按下開始人聲廣播。');
      }
      syncButtons();
    } catch (error) {
      renderStatus('error', '狀態讀取失敗', error.message);
      syncButtons(false);
    }
  }

  speakerSelect.addEventListener('change', () => {
    const count = selectedIds().length;
    if (count > maxSpeakers) {
      renderStatus('error', '選擇數量超過限制', `一次最多選擇 ${maxSpeakers} 顆 Speaker。`);
    } else if (!activeSessionId) {
      renderStatus('idle', '已選擇播放目標', count ? `目前選擇 ${count} 顆 Speaker。` : '請選擇 Speaker。');
    }
    syncButtons();
  });

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const speakerIds = selectedIds();
    if (!speakerIds.length || speakerIds.length > maxSpeakers) return;

    startButton.disabled = true;
    renderStatus('working', '正在建立實體 SIP 通話', `正在連線 ${speakerIds.length} 顆 Speaker，請稍候。`);

    try {
      const response = await fetch(form.dataset.startUrl, {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf},
        body: JSON.stringify({speaker_ids: speakerIds, volume_percent: Number(liveVolume?.value || 100)})
      });
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.message || '人聲廣播啟動失敗');
      activeSessionId = data.session_id;
      renderStatus(
        'active',
        '即時人聲廣播中',
        `上線：${(data.active_speakers || []).join(', ') || '無'}；失敗：${(data.failed_speakers || []).join(', ') || '無'}；音量 ${data.volume_percent || 100}%。`
      );
      syncButtons(true);
    } catch (error) {
      activeSessionId = null;
      renderStatus('error', '人聲廣播啟動失敗', error.message);
      syncButtons(false);
    }
  });

  stopButton.addEventListener('click', async () => {
    if (!activeSessionId) return;
    stopButton.disabled = true;
    renderStatus('working', '正在停止', '正在結束所有 SIP 通話並寫入正式紀錄。');
    try {
      const response = await fetch(form.dataset.stopUrl, {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf},
        body: JSON.stringify({session_id: activeSessionId})
      });
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.message || '停止失敗');
      activeSessionId = null;
      renderStatus('idle', '人聲廣播已停止', `${(data.speaker_codes || []).join(', ')} 已正常結束。`);
      syncButtons(false);
      setTimeout(() => location.reload(), 900);
    } catch (error) {
      renderStatus('error', '停止失敗', error.message);
      stopButton.disabled = false;
    }
  });

  loadStatus();
  statusTimer = window.setInterval(loadStatus, 2000);
  window.addEventListener('beforeunload', () => window.clearInterval(statusTimer));
})();

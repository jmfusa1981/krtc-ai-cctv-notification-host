(() => {
  const form = document.getElementById('manualBroadcastForm');
  if (!form) return;
  const areaFilter = document.getElementById('areaFilter');
  const speakerSelect = document.getElementById('speakerSelect');
  const audioSelect = document.getElementById('audioSelect');
  const preview = document.getElementById('selectionPreview');
  const submitButton = document.getElementById('broadcastSubmitButton');
  const clearButton = document.getElementById('clearSelectionButton');
  const statusBox = document.getElementById('broadcastStatus');
  const refreshButton = document.getElementById('refreshPageButton');
  const csrf = form.querySelector('[name=csrfmiddlewaretoken]').value;

  function updateSpeakerFilter() {
    const area = areaFilter.value;
    [...speakerSelect.options].forEach((option, index) => {
      if (index === 0) return;
      option.hidden = Boolean(area && option.dataset.area !== area);
    });
    const selected = speakerSelect.selectedOptions[0];
    if (selected && selected.hidden) speakerSelect.value = '';
    updatePreview();
  }

  function updatePreview() {
    const speaker = speakerSelect.selectedOptions[0];
    const audio = audioSelect.selectedOptions[0];
    const ready = speakerSelect.value && audioSelect.value;
    submitButton.disabled = !ready;
    if (!ready) {
      preview.innerHTML = '<strong>尚未完成選擇</strong><span>請選擇 Speaker 與音檔。</span>';
      return;
    }
    preview.innerHTML = `<strong>${speaker.textContent.trim()}</strong><span>播放：${audio.textContent.trim()}</span>`;
  }

  function setStatus(kind, title, message) {
    statusBox.className = `broadcast-status is-${kind}`;
    statusBox.innerHTML = `<strong>${title}</strong><span>${message}</span>`;
  }

  areaFilter.addEventListener('change', updateSpeakerFilter);
  speakerSelect.addEventListener('change', updatePreview);
  audioSelect.addEventListener('change', updatePreview);
  clearButton.addEventListener('click', () => {
    areaFilter.value = '';
    speakerSelect.value = '';
    audioSelect.value = '';
    updateSpeakerFilter();
  });
  refreshButton?.addEventListener('click', () => location.reload());

  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    if (!speakerSelect.value || !audioSelect.value) return;
    submitButton.disabled = true;
    setStatus('working', '廣播執行中', '正在建立並執行播放任務，請勿重複操作。');
    try {
      const response = await fetch(form.dataset.submitUrl, {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-CSRFToken': csrf},
        body: JSON.stringify({speaker_id: speakerSelect.value, audio_file_id: audioSelect.value})
      });
      const data = await response.json();
      if (!response.ok || !data.success) throw new Error(data.message || '廣播失敗');
      setStatus('success', '廣播完成', `${data.speaker_code} 已完成播放 ${data.audio_code}。`);
      setTimeout(() => location.reload(), 1200);
    } catch (error) {
      setStatus('error', '廣播失敗', error.message);
      submitButton.disabled = false;
    }
  });

  updatePreview();
})();

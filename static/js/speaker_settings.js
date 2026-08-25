(() => {
  const modal = document.getElementById("speaker-modal");
  const form = document.getElementById("speaker-form");
  if (!modal || !form) return;
  const byId = (id) => document.getElementById(id);
  const fields = {
    id: byId("speaker-id"), speaker_code: byId("speaker-code"), name: byId("speaker-name"),
    area: byId("speaker-area"), location_note: byId("speaker-location-note"),
    network_mode: byId("speaker-network-mode"), ip_address: byId("speaker-ip-address"),
    port: byId("speaker-port"), username: byId("speaker-username"),
    preferred_codec: byId("speaker-codec"), deployment_state: byId("speaker-deployment-state"),
    health_monitor_enabled: byId("speaker-health-monitor"), is_active: byId("speaker-active")
  };
  const errors = byId("speaker-form-errors");
  function openModal(data = null) {
    form.reset(); fields.id.value = ""; fields.port.value = "5060"; fields.deployment_state.value = "planned"; fields.health_monitor_enabled.checked = false; fields.is_active.checked = true;
    byId("speaker-modal-title").textContent = data ? `編輯 ${data.speaker_code}` : "新增 Speaker";
    if (data) Object.entries(fields).forEach(([key, element]) => {
      if (!(key in data)) return;
      if (key === "is_active" || key === "health_monitor_enabled") element.checked = Boolean(data[key]); else element.value = data[key] ?? "";
    });
    errors.hidden = true; errors.textContent = ""; modal.hidden = false;
  }
  function closeModal() { modal.hidden = true; }
  byId("speaker-add-button")?.addEventListener("click", () => openModal());
  document.querySelectorAll(".speaker-edit-button").forEach((button) => button.addEventListener("click", () => {
    try { openModal(JSON.parse(button.dataset.speaker)); } catch (_) { alert("Speaker 資料無法讀取。"); }
  }));
  byId("speaker-modal-close").addEventListener("click", closeModal);
  byId("speaker-modal-cancel").addEventListener("click", closeModal);
  modal.addEventListener("click", (event) => { if (event.target === modal) closeModal(); });
  form.addEventListener("submit", async (event) => {
    event.preventDefault(); errors.hidden = true;
    const response = await fetch(form.action, { method: "POST", body: new FormData(form), headers: {"X-Requested-With": "XMLHttpRequest"} });
    const result = await response.json();
    if (!response.ok || !result.success) {
      const messages = [];
      Object.entries(result.errors || {}).forEach(([field, items]) => items.forEach((item) => messages.push(`${field}: ${item.message}`)));
      errors.textContent = messages.join("；") || result.message || "儲存失敗。"; errors.hidden = false; return;
    }
    window.location.reload();
  });
})();

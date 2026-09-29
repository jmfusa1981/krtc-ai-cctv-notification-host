document.addEventListener("DOMContentLoaded", () => {
    const tabs = Array.from(document.querySelectorAll("[data-tab]"));
    const panels = Array.from(document.querySelectorAll("[data-panel]"));
    const resultBox = document.getElementById("diagnostic-result");
    const settingsForm = document.querySelector(".local-settings-form");
    const maintenanceHostInput = document.getElementById("id_maintenance_host_url");
    const runAllButton = document.getElementById("run-all-diagnostics");
    const issueList = document.getElementById("dynamic-issue-list");
    const issueCountBadge = document.querySelector(".issue-overview-heading span");
    const progressBar = document.getElementById("check-progress-bar");
    const progressText = document.getElementById("check-progress-text");
    const countSuccess = document.getElementById("check-success-count");
    const countWarning = document.getElementById("check-warning-count");
    const countFailure = document.getElementById("check-failure-count");
    const countPending = document.getElementById("check-pending-count");
    const requestedTab = new URLSearchParams(window.location.search).get("tab");

    tabs.forEach((tab) => {
        tab.addEventListener("click", () => {
            const target = tab.dataset.tab;
            tabs.forEach((item) => item.classList.toggle("is-active", item === tab));
            panels.forEach((panel) => {
                const active = panel.dataset.panel === target;
                panel.classList.toggle("is-active", active);
                panel.hidden = !active;
            });
        });
    });

    if (requestedTab) {
        const targetTab = tabs.find((item) => item.dataset.tab === requestedTab);
        if (targetTab) targetTab.click();
    }

    function getCookie(name) {
        const cookie = document.cookie
            .split(";")
            .map((item) => item.trim())
            .find((item) => item.startsWith(`${name}=`));
        return cookie ? decodeURIComponent(cookie.split("=").slice(1).join("=")) : "";
    }

    function formatResult(data, isSuccess) {
        const elapsed = Number.isFinite(data.elapsed_ms) ? `｜${data.elapsed_ms} ms` : "";
        const testedAt = data.tested_at ? `｜${data.tested_at}` : "";
        return `${isSuccess ? "測試成功" : "測試失敗"}｜${data.message || "未回傳訊息"}${elapsed}${testedAt}`;
    }

    function updateDynamicStatus(button, data) {
        const statusTargetId = button.dataset.statusTarget || "";
        const timeTargetId = button.dataset.statusTimeTarget || "";
        if (statusTargetId && data.status) {
            const statusTarget = document.getElementById(statusTargetId);
            if (statusTarget) {
                statusTarget.className = `status status-${data.status}`;
                statusTarget.textContent = data.status_label || (data.status === "online" ? "連線正常" : "離線");
            }
        }
        if (timeTargetId && data.tested_at) {
            const timeTarget = document.getElementById(timeTargetId);
            if (timeTarget) timeTarget.textContent = data.tested_at;
        }
    }

    function showResult(data, isSuccess, targetId = "") {
        const message = formatResult(data, isSuccess);
        if (resultBox) {
            resultBox.hidden = false;
            resultBox.classList.toggle("is-success", isSuccess);
            resultBox.classList.toggle("is-error", !isSuccess);
            resultBox.textContent = message;
        }
        if (targetId) {
            const target = document.getElementById(targetId);
            if (target) {
                target.textContent = message;
                target.classList.toggle("is-success", isSuccess);
                target.classList.toggle("is-error", !isSuccess);
            }
        }
    }

    async function runDiagnostic(button, showToast = true) {
        const originalText = button.textContent;
        button.disabled = true;
        button.textContent = "測試中…";

        const payload = { id: button.dataset.objectId || null };
        if (button.dataset.testKind === "maintenance-host" && maintenanceHostInput) {
            payload.url = maintenanceHostInput.value.trim();
        }

        try {
            const response = await fetch(button.dataset.testUrl, {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": getCookie("csrftoken"),
                },
                body: JSON.stringify(payload),
            });
            const data = await response.json();
            const success = response.ok && data.success;
            updateDynamicStatus(button, data);
            if (showToast) {
                showResult(data, success, button.dataset.resultTarget || "");
            } else if (button.dataset.resultTarget) {
                const target = document.getElementById(button.dataset.resultTarget);
                if (target) {
                    target.textContent = formatResult(data, success);
                    target.classList.toggle("is-success", success);
                    target.classList.toggle("is-error", !success);
                }
            }
            return {
                success,
                category: button.dataset.checkCategory || "診斷",
                label: button.dataset.checkLabel || originalText,
                message: data.message || "未回傳訊息",
            };
        } catch (error) {
            const data = { message: `前端請求失敗：${error.message}` };
            if (showToast) {
                showResult(data, false, button.dataset.resultTarget || "");
            }
            return {
                success: false,
                category: button.dataset.checkCategory || "診斷",
                label: button.dataset.checkLabel || originalText,
                message: data.message,
            };
        } finally {
            button.disabled = false;
            button.textContent = originalText;
        }
    }

    document.querySelectorAll(".test-button[data-test-url]").forEach((button) => {
        button.addEventListener("click", () => runDiagnostic(button, true));
    });

    function updateCheckSummary({ success, warning, failure, pending, completed, total }) {
        if (countSuccess) countSuccess.textContent = success;
        if (countWarning) countWarning.textContent = warning;
        if (countFailure) countFailure.textContent = failure;
        if (countPending) countPending.textContent = pending;
        if (progressBar) progressBar.style.width = total ? `${Math.round((completed / total) * 100)}%` : "0%";
        if (progressText) progressText.textContent = total ? `已完成 ${completed}/${total} 項檢查。` : "沒有可執行的診斷項目。";
    }

    function renderIssues(issues) {
        if (!issueList) return;
        issueList.innerHTML = "";
        if (issueCountBadge) issueCountBadge.textContent = `${issues.length} 項`;
        if (!issues.length) {
            const item = document.createElement("li");
            item.className = "is-ok";
            item.textContent = "全部檢查通過，未發現異常。";
            issueList.appendChild(item);
            return;
        }
        issues.forEach((issue) => {
            const item = document.createElement("li");
            item.textContent = `${issue.category} ${issue.label}：${issue.message}`;
            issueList.appendChild(item);
        });
    }

    if (runAllButton) {
        runAllButton.addEventListener("click", async () => {
            const dynamicButtons = Array.from(document.querySelectorAll(".diagnostic-item"));
            const staticItems = Array.from(document.querySelectorAll(".static-diagnostic-item"));
            const total = dynamicButtons.length + staticItems.length;
            const issues = [];
            let success = 0;
            let warning = 0;
            let failure = 0;
            let completed = 0;

            runAllButton.disabled = true;
            runAllButton.textContent = "系統檢查中…";
            updateCheckSummary({ success, warning, failure, pending: total, completed, total });

            staticItems.forEach((item) => {
                const ok = item.dataset.staticOk === "1";
                completed += 1;
                if (ok) {
                    success += 1;
                } else {
                    warning += 1;
                    issues.push({
                        category: item.dataset.checkCategory || "設定",
                        label: item.dataset.checkLabel || "未命名項目",
                        message: "設定完整性檢查未通過。",
                    });
                }
                updateCheckSummary({ success, warning, failure, pending: total - completed, completed, total });
            });

            for (const button of dynamicButtons) {
                const result = await runDiagnostic(button, false);
                completed += 1;
                if (result.success) {
                    success += 1;
                } else {
                    failure += 1;
                    issues.push(result);
                }
                updateCheckSummary({ success, warning, failure, pending: total - completed, completed, total });
            }

            renderIssues(issues);
            if (progressText) {
                progressText.textContent = `系統檢查完成：正常 ${success}、警告 ${warning}、異常 ${failure}。`;
            }
            if (resultBox) {
                resultBox.hidden = false;
                resultBox.classList.toggle("is-success", failure === 0 && warning === 0);
                resultBox.classList.toggle("is-error", failure > 0 || warning > 0);
                resultBox.textContent = `本站系統檢查完成｜正常 ${success}｜警告 ${warning}｜異常 ${failure}`;
            }
            runAllButton.disabled = false;
            runAllButton.textContent = "重新執行本站系統檢查";
        });
    }

    if (settingsForm) {
        settingsForm.addEventListener("submit", () => {
            const submitButton = settingsForm.querySelector("button[type='submit']");
            if (submitButton) {
                submitButton.disabled = true;
                submitButton.textContent = "儲存中…";
            }
        });
    }

    // Preserve the operator's current viewport after deleting a device.
    document.querySelectorAll(".preserve-scroll-delete-form").forEach((form) => {
        form.addEventListener("submit", () => {
            const field = form.querySelector('input[name="return_scroll_y"]');
            if (field) field.value = String(Math.max(0, Math.round(window.scrollY || 0)));
        });
    });

    const scrollParam = new URLSearchParams(window.location.search).get("scroll_y");
    if (scrollParam !== null) {
        const targetY = Number.parseInt(scrollParam, 10);
        if (Number.isFinite(targetY) && targetY >= 0) {
            requestAnimationFrame(() => window.scrollTo({ top: targetY, left: 0, behavior: "auto" }));
        }
        const cleanUrl = new URL(window.location.href);
        cleanUrl.searchParams.delete("scroll_y");
        window.history.replaceState({}, "", `${cleanUrl.pathname}${cleanUrl.search}${cleanUrl.hash}`);
    }

    const loginBackgroundInput = document.getElementById("id_login_background");
    const loginBackgroundPreview = document.getElementById("loginBackgroundPreview");
    const initialLoginPreview = loginBackgroundPreview ? loginBackgroundPreview.innerHTML : "";
    let loginPreviewUrl = "";

    if (loginBackgroundInput && loginBackgroundPreview) {
        loginBackgroundInput.addEventListener("change", () => {
            if (loginPreviewUrl) {
                URL.revokeObjectURL(loginPreviewUrl);
                loginPreviewUrl = "";
            }
            const selectedFile = loginBackgroundInput.files[0];
            if (!selectedFile) {
                loginBackgroundPreview.innerHTML = initialLoginPreview;
                return;
            }
            loginPreviewUrl = URL.createObjectURL(selectedFile);
            const image = document.createElement("img");
            image.src = loginPreviewUrl;
            image.alt = "待儲存的登入背景預覽";
            loginBackgroundPreview.replaceChildren(image);
            loginBackgroundPreview.classList.remove("is-default");
        });
    }

    const alertSoundForm = document.getElementById("alertSoundForm");
    const alertSoundInput = document.getElementById("id_alert_sound");
    const testAlertSoundButton = document.getElementById("testAlertSoundButton");
    let alertPreviewUrl = "";
    let alertPreviewAudio = null;
    let alertPreviewContext = null;

    function stopAlertPreview() {
        if (alertPreviewAudio) {
            alertPreviewAudio.pause();
            alertPreviewAudio.currentTime = 0;
            alertPreviewAudio = null;
        }
    }

    function playDefaultAlertPreview() {
        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        if (!AudioContextClass) return;
        alertPreviewContext = alertPreviewContext || new AudioContextClass();
        const startedAt = alertPreviewContext.currentTime;
        const oscillator = alertPreviewContext.createOscillator();
        const gain = alertPreviewContext.createGain();
        oscillator.type = "sawtooth";
        oscillator.frequency.setValueAtTime(720, startedAt);
        oscillator.frequency.setValueAtTime(980, startedAt + 0.35);
        gain.gain.setValueAtTime(0.16, startedAt);
        gain.gain.exponentialRampToValueAtTime(0.0001, startedAt + 0.8);
        oscillator.connect(gain);
        gain.connect(alertPreviewContext.destination);
        oscillator.start(startedAt);
        oscillator.stop(startedAt + 0.8);
    }

    if (alertSoundInput) {
        alertSoundInput.addEventListener("change", () => {
            stopAlertPreview();
            if (alertPreviewUrl) {
                URL.revokeObjectURL(alertPreviewUrl);
                alertPreviewUrl = "";
            }
            const selectedFile = alertSoundInput.files[0];
            if (selectedFile) alertPreviewUrl = URL.createObjectURL(selectedFile);
        });
    }

    if (testAlertSoundButton && alertSoundForm) {
        testAlertSoundButton.addEventListener("click", async () => {
            stopAlertPreview();
            const sourceUrl = alertPreviewUrl || alertSoundForm.dataset.currentSoundUrl || "";
            if (!sourceUrl) {
                playDefaultAlertPreview();
                return;
            }
            alertPreviewAudio = new Audio(sourceUrl);
            try {
                await alertPreviewAudio.play();
            } catch (error) {
                console.warn("無法播放事件警示音預覽。", error);
            }
        });
    }

    const ntpSettingsForm = document.getElementById("ntpSettingsForm");
    if (ntpSettingsForm) {
        const enabledInput = ntpSettingsForm.querySelector('input[name="enabled"]');
        const guardedButtons = Array.from(
            ntpSettingsForm.querySelectorAll("[data-ntp-requires-enabled]")
        );
        const updateNtpActionState = () => {
            const enabled = Boolean(enabledInput && enabledInput.checked);
            guardedButtons.forEach((button) => {
                button.disabled = !enabled;
                button.setAttribute("aria-disabled", String(!enabled));
            });
        };
        if (enabledInput) enabledInput.addEventListener("change", updateNtpActionState);
        updateNtpActionState();
    }

    document.querySelectorAll(".frontend-asset-reset-form").forEach((form) => {
        form.addEventListener("submit", (event) => {
            if (!window.confirm("確定恢復系統預設設定？")) event.preventDefault();
        });
    });

    window.addEventListener("pagehide", () => {
        stopAlertPreview();
        if (loginPreviewUrl) URL.revokeObjectURL(loginPreviewUrl);
        if (alertPreviewUrl) URL.revokeObjectURL(alertPreviewUrl);
    });
});

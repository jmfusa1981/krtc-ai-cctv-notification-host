document.addEventListener("DOMContentLoaded", () => {
    const tabs = Array.from(document.querySelectorAll("[data-tab]"));
    const panels = Array.from(document.querySelectorAll("[data-panel]"));
    const resultBox = document.getElementById("diagnostic-result");
    const settingsForm = document.querySelector(".local-settings-form");
    const maintenanceHostInput = document.getElementById("id_maintenance_host_url");
    const runAllButton = document.getElementById("run-all-diagnostics");
    const issueList = document.getElementById("dynamic-issue-list");
    const progressBar = document.getElementById("check-progress-bar");
    const progressText = document.getElementById("check-progress-text");
    const countSuccess = document.getElementById("check-success-count");
    const countWarning = document.getElementById("check-warning-count");
    const countFailure = document.getElementById("check-failure-count");
    const countPending = document.getElementById("check-pending-count");

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

    document.querySelectorAll(".test-button").forEach((button) => {
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
});

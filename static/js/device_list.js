document.addEventListener("DOMContentLoaded", function () {
    const tabs = Array.from(document.querySelectorAll("[data-device-tab]"));
    const panels = Array.from(document.querySelectorAll("[data-device-panel]"));
    let activeTab = "camera";

    const systemDateTime = document.getElementById("systemDateTime");
    let serverClockOffsetMs = 0;

    function formatSystemTime(date) {
        return new Intl.DateTimeFormat("zh-TW", {
            year: "numeric",
            month: "2-digit",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
            hour12: false,
        }).format(date);
    }

    function renderSystemClock() {
        if (!systemDateTime) {
            return;
        }
        systemDateTime.textContent = formatSystemTime(
            new Date(Date.now() + serverClockOffsetMs)
        );
    }

    async function syncSystemClock() {
        if (!systemDateTime) {
            return;
        }

        try {
            const requestStartedAt = Date.now();
            const response = await fetch(window.location.href, {
                method: "HEAD",
                cache: "no-store",
                credentials: "same-origin",
            });
            const requestFinishedAt = Date.now();
            const serverDateHeader = response.headers.get("Date");

            if (serverDateHeader) {
                const serverTimeMs = Date.parse(serverDateHeader);
                if (!Number.isNaN(serverTimeMs)) {
                    const estimatedClientAtResponse =
                        requestStartedAt + ((requestFinishedAt - requestStartedAt) / 2);
                    serverClockOffsetMs = serverTimeMs - estimatedClientAtResponse;
                }
            }
        } catch (error) {
            const initialServerTime = systemDateTime.dataset.serverTime;
            const parsedInitialTime = Date.parse(initialServerTime || "");
            if (!Number.isNaN(parsedInitialTime)) {
                serverClockOffsetMs = parsedInitialTime - Date.now();
            }
        }

        renderSystemClock();
    }

    function switchTab(tabName) {
        activeTab = tabName;
        tabs.forEach(function (tab) {
            tab.classList.toggle("is-active", tab.dataset.deviceTab === tabName);
        });
        panels.forEach(function (panel) {
            const isActive = panel.dataset.devicePanel === tabName;
            panel.hidden = !isActive;
            panel.classList.toggle("is-active", isActive);
        });
    }

    tabs.forEach(function (tab) {
        tab.addEventListener("click", function () {
            switchTab(tab.dataset.deviceTab);
        });
    });

    switchTab(activeTab);

    syncSystemClock();
    window.setInterval(renderSystemClock, 1000);
    window.setInterval(syncSystemClock, 60000);
});

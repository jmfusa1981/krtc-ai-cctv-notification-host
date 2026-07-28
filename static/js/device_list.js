document.addEventListener("DOMContentLoaded", function () {
    const tabs = Array.from(document.querySelectorAll("[data-device-tab]"));
    const panels = Array.from(document.querySelectorAll("[data-device-panel]"));
    const searchInput = document.getElementById("deviceSearchInput");
    const searchEmpty = document.getElementById("deviceSearchEmpty");
    const clock = document.getElementById("devicePageClock");
    let activeTab = "camera";

    function updateClock() {
        if (!clock) return;
        clock.textContent = new Intl.DateTimeFormat("zh-TW", {
            year: "numeric",
            month: "2-digit",
            day: "2-digit",
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
            hour12: false,
        }).format(new Date());
    }

    function filterRows() {
        const panel = document.querySelector(`[data-device-panel="${activeTab}"]`);
        if (!panel) return;

        const query = (searchInput?.value || "").trim().toLowerCase();
        const rows = Array.from(panel.querySelectorAll("[data-device-row]"));
        let visibleCount = 0;

        rows.forEach(function (row) {
            const text = (row.dataset.searchText || "").toLowerCase();
            const isVisible = !query || text.includes(query);
            row.hidden = !isVisible;
            if (isVisible) visibleCount += 1;
        });

        if (searchEmpty) {
            searchEmpty.hidden = rows.length === 0 || visibleCount > 0;
        }
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
        filterRows();
    }

    tabs.forEach(function (tab) {
        tab.addEventListener("click", function () {
            switchTab(tab.dataset.deviceTab);
        });
    });

    searchInput?.addEventListener("input", filterRows);
    updateClock();
    window.setInterval(updateClock, 1000);
    switchTab(activeTab);
});

document.addEventListener("DOMContentLoaded", function () {
    const cards = Array.from(document.querySelectorAll("[data-snapshot-card]"));
    const searchInput = document.getElementById("snapshotSearch");
    const resultCount = document.getElementById("snapshotResultCount");
    const dialog = document.getElementById("snapshotDialog");
    const dialogImage = document.getElementById("snapshotDialogImage");
    const dialogTitle = document.getElementById("snapshotDialogTitle");
    const dialogClose = document.getElementById("snapshotDialogClose");
    const systemDateTime = document.getElementById("systemDateTime");
    let serverClockOffsetMs = 0;

    function normalize(value) {
        return String(value || "").trim().toLocaleLowerCase("zh-TW");
    }

    function applySearch() {
        const keyword = normalize(searchInput ? searchInput.value : "");
        let visibleCount = 0;

        cards.forEach(function (card) {
            const visible = !keyword || normalize(card.dataset.search).includes(keyword);
            card.hidden = !visible;
            if (visible) visibleCount += 1;
        });

        if (resultCount) resultCount.textContent = `顯示 ${visibleCount} 筆`;
    }

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
        if (!systemDateTime) return;
        systemDateTime.textContent = formatSystemTime(new Date(Date.now() + serverClockOffsetMs));
    }

    async function syncSystemClock() {
        if (!systemDateTime) return;
        try {
            const startedAt = Date.now();
            const response = await fetch(window.location.href, {
                method: "HEAD",
                cache: "no-store",
                credentials: "same-origin",
            });
            const finishedAt = Date.now();
            const serverDateHeader = response.headers.get("Date");
            if (serverDateHeader) {
                const serverTimeMs = Date.parse(serverDateHeader);
                if (!Number.isNaN(serverTimeMs)) {
                    serverClockOffsetMs = serverTimeMs - (startedAt + ((finishedAt - startedAt) / 2));
                }
            }
        } catch (error) {
            const parsed = Date.parse(systemDateTime.dataset.serverTime || "");
            if (!Number.isNaN(parsed)) serverClockOffsetMs = parsed - Date.now();
        }
        renderSystemClock();
    }

    function openPreview(button) {
        const url = button.dataset.previewUrl;
        if (!url || !dialog || !dialogImage) return;
        dialogImage.src = url;
        dialogTitle.textContent = button.dataset.previewTitle || "事件快照";
        if (typeof dialog.showModal === "function") dialog.showModal();
    }

    document.querySelectorAll("[data-preview-url]").forEach(function (button) {
        button.addEventListener("click", function () { openPreview(button); });
    });

    document.querySelectorAll(".snapshot-preview-button img").forEach(function (image) {
        image.addEventListener("error", function () {
            const button = image.closest(".snapshot-preview-button");
            if (button) button.classList.add("is-error");
            image.hidden = true;
        });
    });

    if (searchInput) searchInput.addEventListener("input", applySearch);
    if (dialogClose) dialogClose.addEventListener("click", function () { dialog.close(); });
    if (dialog) {
        dialog.addEventListener("click", function (event) {
            if (event.target === dialog) dialog.close();
        });
        dialog.addEventListener("close", function () { dialogImage.removeAttribute("src"); });
    }

    syncSystemClock();
    window.setInterval(renderSystemClock, 1000);
    window.setInterval(syncSystemClock, 60000);
});

/* KRTC V5.13 snapshot auto refresh - begin */
(function () {
    "use strict";

    const REFRESH_INTERVAL_MS = 10000;
    const STORAGE_KEY_SEARCH = "krtcSnapshotSearch";
    const STORAGE_KEY_REFRESHED = "krtcSnapshotAutoRefreshed";

    function getSearchInput() {
        return document.getElementById("snapshotSearch");
    }

    function getGrid() {
        return document.getElementById("snapshotGrid");
    }

    function getCountNode() {
        return document.getElementById("snapshotResultCount");
    }

    function restoreSearch() {
        const input = getSearchInput();
        if (!input) return;

        const saved = sessionStorage.getItem(STORAGE_KEY_SEARCH);
        if (saved !== null) {
            input.value = saved;
            input.dispatchEvent(new Event("input", { bubbles: true }));
        }
    }

    function saveUiStateBeforeReload() {
        const input = getSearchInput();
        sessionStorage.setItem(STORAGE_KEY_SEARCH, input ? input.value : "");
        sessionStorage.setItem(STORAGE_KEY_REFRESHED, "1");
    }

    function normalizeHtml(value) {
        return String(value || "").replace(/\s+/g, " ").trim();
    }

    async function checkForSnapshotUpdates() {
        if (document.hidden) return;

        const dialog = document.getElementById("snapshotDialog");
        if (dialog && dialog.open) return;

        try {
            const response = await fetch(window.location.href, {
                method: "GET",
                credentials: "same-origin",
                cache: "no-store",
                headers: {
                    "X-KRTC-Snapshot-Refresh": "1"
                }
            });

            if (!response.ok) return;

            const html = await response.text();
            const nextDocument = new DOMParser().parseFromString(html, "text/html");
            const currentGrid = getGrid();
            const nextGrid = nextDocument.getElementById("snapshotGrid");

            if (!currentGrid || !nextGrid) return;

            const currentCount = getCountNode();
            const nextCount = nextDocument.getElementById("snapshotResultCount");

            const gridChanged =
                normalizeHtml(currentGrid.innerHTML) !== normalizeHtml(nextGrid.innerHTML);
            const countChanged =
                normalizeHtml(currentCount ? currentCount.textContent : "") !==
                normalizeHtml(nextCount ? nextCount.textContent : "");

            if (!gridChanged && !countChanged) return;

            saveUiStateBeforeReload();
            window.location.reload();
        } catch (error) {
            console.debug("KRTC snapshot auto refresh skipped:", error);
        }
    }

    document.addEventListener("DOMContentLoaded", function () {
        restoreSearch();

        const refreshed = sessionStorage.getItem(STORAGE_KEY_REFRESHED) === "1";
        if (refreshed) {
            sessionStorage.removeItem(STORAGE_KEY_REFRESHED);

            if ("scrollRestoration" in history) {
                history.scrollRestoration = "manual";
            }

            requestAnimationFrame(function () {
                window.scrollTo({ top: 0, left: 0, behavior: "auto" });
            });

            window.setTimeout(function () {
                window.scrollTo({ top: 0, left: 0, behavior: "auto" });
            }, 50);
        }

        window.setInterval(checkForSnapshotUpdates, REFRESH_INTERVAL_MS);
    });
})();
/* KRTC V5.13 snapshot auto refresh - end */


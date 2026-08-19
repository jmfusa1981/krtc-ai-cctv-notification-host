(() => {
    "use strict";

    const form = document.getElementById("recordFilterForm");
    const exportButtons = document.querySelectorAll("[data-export-url]");
    const dialog = document.getElementById("snapshotDialog");
    const dialogImage = document.getElementById("snapshotDialogImage");
    const dialogTitle = document.getElementById("snapshotDialogTitle");
    const dialogClose = document.getElementById("snapshotDialogClose");

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
        if (!systemDateTime) return;
        systemDateTime.textContent = formatSystemTime(
            new Date(Date.now() + serverClockOffsetMs)
        );
    }

    async function syncSystemClock() {
        if (!systemDateTime) return;

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

    syncSystemClock();
    window.setInterval(renderSystemClock, 1000);
    window.setInterval(syncSystemClock, 60000);

    exportButtons.forEach((button) => {
        button.addEventListener("click", () => {
            const params = new URLSearchParams(new FormData(form));
            const baseUrl = button.dataset.exportUrl;
            window.location.href = params.toString() ? `${baseUrl}?${params}` : baseUrl;
        });
    });

    document.querySelectorAll("[data-snapshot-url]").forEach((button) => {
        button.addEventListener("click", () => {
            if (!dialog || !dialogImage) return;
            dialogImage.src = button.dataset.snapshotUrl || "";
            dialogTitle.textContent = button.dataset.snapshotTitle || "事件快照";
            dialog.showModal();
        });
    });

    if (dialogClose) {
        dialogClose.addEventListener("click", () => dialog.close());
    }

    if (dialog) {
        dialog.addEventListener("click", (event) => {
            if (event.target === dialog) dialog.close();
        });
    }


    // KRTC V5.17.7 EVENT RECORDING PLAYBACK / DOWNLOAD / AUTO REFRESH
    const recordingVideoDialog = document.getElementById("recordingVideoDialog");
    const recordingVideoDialogTitle = document.getElementById("recordingVideoDialogTitle");
    const recordingVideoDialogClose = document.getElementById("recordingVideoDialogClose");
    const recordingVideoPlayer = document.getElementById("recordingVideoPlayer");
    const recordingVideoPath = document.getElementById("recordingVideoPath");
    const recordingDownloadDialog = document.getElementById("recordingDownloadDialog");
    const recordingDownloadDialogClose = document.getElementById("recordingDownloadDialogClose");
    const recordingDownloadLocalPath = document.getElementById("recordingDownloadLocalPath");
    const recordingDownloadUrl = document.getElementById("recordingDownloadUrl");
    const recordingDownloadLink = document.getElementById("recordingDownloadLink");

    document.querySelectorAll(".recording-play-button").forEach((button) => {
        button.addEventListener("click", () => {
            if (!recordingVideoDialog || !recordingVideoPlayer) return;
            const url = button.dataset.videoUrl || "";
            if (!url) return;
            recordingVideoDialogTitle.textContent = button.dataset.videoTitle || "Event recording";
            recordingVideoPath.textContent = button.dataset.videoPath || "PAO local event video";
            recordingVideoPlayer.src = url;
            recordingVideoPlayer.load();
            recordingVideoDialog.showModal();
        });
    });

    function closeRecordingVideoDialog() {
        if (recordingVideoPlayer) {
            recordingVideoPlayer.pause();
            recordingVideoPlayer.removeAttribute("src");
            recordingVideoPlayer.load();
        }
        if (recordingVideoDialog && recordingVideoDialog.open) {
            recordingVideoDialog.close();
        }
    }

    if (recordingVideoDialogClose) {
        recordingVideoDialogClose.addEventListener("click", closeRecordingVideoDialog);
    }
    if (recordingVideoDialog) {
        recordingVideoDialog.addEventListener("close", closeRecordingVideoDialog);
    }

    document.querySelectorAll(".recording-download-button[data-download-url]").forEach((button) => {
        button.addEventListener("click", () => {
            if (!recordingDownloadDialog || !recordingDownloadLink) return;
            const url = button.dataset.downloadUrl || "";
            if (!url) return;
            recordingDownloadLocalPath.textContent = button.dataset.downloadPath || "PAO local event video";
            recordingDownloadUrl.textContent = new URL(url, window.location.origin).href;
            recordingDownloadLink.href = url;
            recordingDownloadDialog.showModal();
        });
    });

    if (recordingDownloadDialogClose) {
        recordingDownloadDialogClose.addEventListener("click", () => recordingDownloadDialog.close());
    }

    function anyDialogOpen() {
        return Boolean(document.querySelector("dialog[open]"));
    }

    function getRecordSignature(root) {
        const body = root.querySelector(".record-table tbody");
        if (!body) return "";
        return body.textContent.replace(/\s+/g, " ").trim();
    }

    const currentRecordSignature = getRecordSignature(document);

    async function checkRecordUpdates() {
        if (document.hidden || anyDialogOpen()) return;
        try {
            const response = await fetch(window.location.href, {
                method: "GET",
                cache: "no-store",
                credentials: "same-origin",
                headers: { "X-Requested-With": "XMLHttpRequest" },
            });
            if (!response.ok) return;
            const html = await response.text();
            const nextDocument = new DOMParser().parseFromString(html, "text/html");
            const nextSignature = getRecordSignature(nextDocument);
            if (nextSignature && currentRecordSignature && nextSignature !== currentRecordSignature) {
                window.location.reload();
            }
        } catch (error) {
            console.debug("[KRTC event records auto refresh]", error);
        }
    }

    window.setInterval(checkRecordUpdates, 10000);

})();

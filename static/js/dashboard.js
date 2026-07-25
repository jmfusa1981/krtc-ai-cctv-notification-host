document.addEventListener("DOMContentLoaded", function () {
    const body = document.body;
    const cameraGrid = document.getElementById("cameraGrid");
    const primaryCameraStage = document.getElementById("primaryCameraStage");
    const eventList = document.getElementById("eventList");
    const eventListCount = document.getElementById("eventListCount");
    const broadcastLogContainer = document.getElementById("broadcastLogTableBody");
    const systemDateTime = document.getElementById("systemDateTime");
    const eventCarouselButton = document.getElementById("eventCarouselButton");

    const stationCameraCount = document.getElementById("stationCameraCount");
    const latestEventType = document.getElementById("latestEventType");
    const latestEventCamera = document.getElementById("latestEventCamera");
    const latestEventTime = document.getElementById("latestEventTime");
    const dashboardPollingStatus = document.getElementById("dashboardPollingStatus");
    const crowdFlowMetric = document.getElementById("crowdFlowMetric");
    const crowdFlowValue = document.getElementById("crowdFlowValue");
    const crowdFlowSummary = document.getElementById("crowdFlowSummary");
    const inferenceHostMetric = document.getElementById("inferenceHostMetric");
    const inferenceHostStatus = document.getElementById("inferenceHostStatus");
    const inferenceHostDetail = document.getElementById("inferenceHostDetail");
    const eventWarningLight = document.getElementById("eventWarningLight");

    const detailEventType = document.getElementById("detailEventType");
    const detailEventId = document.getElementById("detailEventId");
    const detailEventStatus = document.getElementById("detailEventStatus");
    const detailInferenceHost = document.getElementById("detailInferenceHost");
    const detailCamera = document.getElementById("detailCamera");
    const detailLocation = document.getElementById("detailLocation");
    const detailDetectedAt = document.getElementById("detailDetectedAt");
    const detailCreatedAt = document.getElementById("detailCreatedAt");
    const detailConfirmButton = document.getElementById("detailConfirmButton");
    const detailCloseButton = document.getElementById("detailCloseButton");
    const detailBroadcastButton = document.getElementById("detailBroadcastButton");
    const detailActionMessage = document.getElementById("detailActionMessage");

    const processPendingBroadcastButton = document.getElementById("processPendingBroadcastButton");
    const processBroadcastStatus = document.getElementById("processBroadcastStatus");

    const dashboardActionToast = document.getElementById("dashboardActionToast");
    const dashboardActionToastTitle = document.getElementById("dashboardActionToastTitle");
    const dashboardActionToastMessage = document.getElementById("dashboardActionToastMessage");
    const dashboardActionToastClose = document.getElementById("dashboardActionToastClose");

    const liveStateApiUrl = body.dataset.dashboardLiveStateUrl;
    const processPendingBroadcastApiUrl = body.dataset.processPendingBroadcastUrl;
    const confirmEventUrlPrefix = body.dataset.confirmEventUrlPrefix || "/api/events/";
    const manualBroadcastUrlPrefix =
        body.dataset.manualBroadcastUrlPrefix ||
        "/api/notifications/broadcast/event/";
    const canProcessEvents = body.dataset.canProcessEvents === "true";
    const broadcastPlaybackModeLabel =
        body.dataset.broadcastPlaybackModeLabel || "模擬測試";
    const broadcastPlaybackIsLive =
        body.dataset.broadcastPlaybackIsLive === "true";

    let currentEvents = [];
    let currentCameras = [];
    let selectedEventId = null;
    let selectedCameraId = null;
    let lastLatestEventId = null;
    let localAlarmEnabled = true;
    let localAlarmUnlocked = false;
    let localAlarmAudioContext = null;
    let localAlarmStopTimer = null;

    let cameraSignature = "";
    let toastTimer = null;
    let primaryMediaMode = "live";
    let renderedPrimaryKey = "";
    let carouselEnabled = true;
    let carouselTimer = null;
    let manualSelectionUntil = 0;

    function escapeHtml(value) {
        if (value === null || value === undefined) {
            return "";
        }

        return String(value)
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }

    function normalizeText(value, fallback) {
        if (value === null || value === undefined || value === "") {
            return fallback || "";
        }
        return value;
    }

    function getCookie(name) {
        const cookies = document.cookie ? document.cookie.split(";") : [];

        for (const cookie of cookies) {
            const item = cookie.trim();
            const separatorIndex = item.indexOf("=");
            const key = separatorIndex >= 0 ? item.slice(0, separatorIndex) : item;

            if (key === name) {
                const value =
                    separatorIndex >= 0 ? item.slice(separatorIndex + 1) : "";
                return decodeURIComponent(value);
            }
        }

        return "";
    }

    function setPollingStatus(message, isError) {
        if (!dashboardPollingStatus) {
            return;
        }

        dashboardPollingStatus.textContent = message;
        dashboardPollingStatus.classList.toggle("error", Boolean(isError));
    }

    function setDetailMessage(message, type) {
        if (!detailActionMessage) {
            return;
        }

        detailActionMessage.textContent = message || "";
        detailActionMessage.classList.remove("success", "error");

        if (type) {
            detailActionMessage.classList.add(type);
        }
    }

    function updateClock() {
        if (!systemDateTime) {
            return;
        }

        systemDateTime.textContent = new Intl.DateTimeFormat(
            "zh-TW",
            {
                year: "numeric",
                month: "2-digit",
                day: "2-digit",
                hour: "2-digit",
                minute: "2-digit",
                second: "2-digit",
                hour12: false,
            }
        ).format(new Date());
    }

    function hideToast() {
        if (toastTimer !== null) {
            window.clearTimeout(toastTimer);
            toastTimer = null;
        }

        if (dashboardActionToast) {
            dashboardActionToast.hidden = true;
        }
    }

    function showToast(title, message, type, duration) {
        if (!dashboardActionToast) {
            return;
        }

        dashboardActionToast.classList.remove(
            "is-success",
            "is-error",
            "is-pending"
        );
        dashboardActionToast.classList.add(`is-${type || "pending"}`);
        dashboardActionToast.hidden = false;

        if (dashboardActionToastTitle) {
            dashboardActionToastTitle.textContent = title;
        }

        if (dashboardActionToastMessage) {
            dashboardActionToastMessage.textContent = message;
        }

        if (toastTimer !== null) {
            window.clearTimeout(toastTimer);
        }

        if (duration > 0) {
            toastTimer = window.setTimeout(hideToast, duration);
        }
    }

    function getCameraById(cameraId) {
        return (
            currentCameras.find(function (camera) {
                return String(camera.id) === String(cameraId);
            }) || null
        );
    }

    function getEventById(eventId) {
        return (
            currentEvents.find(function (event) {
                return String(event.id) === String(eventId);
            }) || null
        );
    }

    function getSelectedEvent() {
        return getEventById(selectedEventId);
    }

    function updateCameraSelectionClasses() {
        if (!cameraGrid) {
            return;
        }

        cameraGrid.querySelectorAll("[data-camera-card]").forEach(function (card) {
            card.classList.toggle(
                "selected-event-camera-card",
                String(card.dataset.cameraId) === String(selectedCameraId)
            );
        });
    }

    function setMediaMode(mode) {
        primaryMediaMode = mode;

        document.querySelectorAll("[data-media-mode]").forEach(function (button) {
            button.classList.toggle(
                "is-active",
                button.dataset.mediaMode === primaryMediaMode
            );
        });

        renderPrimaryMedia(true);
    }

    function renderPrimaryMedia(force) {
        const event = getSelectedEvent();
        const camera = getCameraById(selectedCameraId);

        let mediaKey = primaryMediaMode;

        if (primaryMediaMode === "live") {
            mediaKey += `:${camera ? camera.id : "none"}`;
        } else if (primaryMediaMode === "snapshot") {
            mediaKey += `:${event ? event.snapshot_url : ""}`;
        } else if (primaryMediaMode === "annotated") {
            mediaKey += `:${event ? event.annotated_snapshot_url : ""}`;
        } else if (primaryMediaMode === "video") {
            mediaKey += `:${event ? event.video_url : ""}`;
        }

        if (!force && mediaKey === renderedPrimaryKey) {
            return;
        }

        renderedPrimaryKey = mediaKey;

        if (primaryMediaMode === "live") {
            renderLiveCamera(camera);
            return;
        }

        if (!event) {
            primaryCameraStage.innerHTML = `
                <div class="media-unavailable">
                    <strong>尚未選取事件</strong>
                    <span>請先從左側選取事件。</span>
                </div>
            `;
            return;
        }

        if (primaryMediaMode === "snapshot") {
            renderImageMedia(
                event.snapshot_url,
                "事件快照",
                "推論主機尚未提供事件快照。"
            );
            return;
        }

        if (primaryMediaMode === "annotated") {
            renderImageMedia(
                event.annotated_snapshot_url,
                "AI 標定影像",
                "推論主機尚未提供 AI 標定影像。"
            );
            return;
        }

        renderVideoMedia(event.video_url);
    }

    function renderLiveCamera(camera) {
        if (!camera) {
            primaryCameraStage.innerHTML = `
                <div class="empty-camera-stage">
                    <strong>尚未選取事件攝影機</strong>
                    <span>請從左側事件清單選取事件</span>
                </div>
            `;
            return;
        }

        const streamUrl = normalizeText(
            camera.stream_url,
            `/api/cameras/${camera.id}/stream/`
        );
        const code = normalizeText(camera.camera_code, `CAM-${camera.id}`);
        const name = normalizeText(camera.name, code);
        const area = normalizeText(camera.area, "未設定區域");
        const statusDisplay = normalizeText(camera.status_display, "狀態未知");

        primaryCameraStage.innerHTML = `
            <img src="${escapeHtml(streamUrl)}" alt="${escapeHtml(code)}" id="primaryCameraStream">
            <div class="primary-camera-overlay">
                <div>
                    <h3>${escapeHtml(code)}｜${escapeHtml(name)}</h3>
                    <p>${escapeHtml(area)}</p>
                </div>
                <span class="camera-status status-${escapeHtml(camera.status || "unknown")}">
                    ${escapeHtml(statusDisplay)}
                </span>
            </div>
        `;

        const stream = document.getElementById("primaryCameraStream");

        if (stream) {
            stream.addEventListener("error", function () {
                primaryCameraStage.innerHTML = `
                    <div class="primary-camera-error">
                        <strong>${escapeHtml(code)}</strong>
                        <span>無法取得即時影像</span>
                    </div>
                `;
            });
        }
    }

    function renderImageMedia(url, title, unavailableMessage) {
        if (!url) {
            primaryCameraStage.innerHTML = `
                <div class="media-unavailable">
                    <strong>${escapeHtml(title)}</strong>
                    <span>${escapeHtml(unavailableMessage)}</span>
                </div>
            `;
            return;
        }

        primaryCameraStage.innerHTML = `
            <img src="${escapeHtml(url)}" alt="${escapeHtml(title)}" id="primaryEventMedia">
            <div class="primary-camera-overlay">
                <div>
                    <h3>${escapeHtml(title)}</h3>
                    <p>由 AI 推論主機提供</p>
                </div>
            </div>
        `;

        const image = document.getElementById("primaryEventMedia");

        if (image) {
            image.addEventListener("error", function () {
                primaryCameraStage.innerHTML = `
                    <div class="media-unavailable">
                        <strong>${escapeHtml(title)}載入失敗</strong>
                        <span>請檢查推論主機媒體網址與網路連線。</span>
                    </div>
                `;
            });
        }
    }

    function renderVideoMedia(url) {
        if (!url) {
            primaryCameraStage.innerHTML = `
                <div class="media-unavailable">
                    <strong>事件錄影尚未提供</strong>
                    <span>事件錄影應由推論主機或 NVR/VMS 保存並提供連結。</span>
                </div>
            `;
            return;
        }

        primaryCameraStage.innerHTML = `
            <div class="video-link-stage">
                <strong>事件錄影已提供</strong>
                <span>影片將於新分頁開啟。</span>
                <a
                    href="${escapeHtml(url)}"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="video-open-button"
                >
                    開啟事件錄影
                </a>
            </div>
        `;
    }

    function selectCamera(cameraId) {
        selectedCameraId = cameraId ? String(cameraId) : null;
        updateCameraSelectionClasses();

        if (primaryMediaMode === "live") {
            renderPrimaryMedia(false);
        }
    }

    function updateDetailPanel(event) {
        if (!event) {
            detailEventType.textContent = "尚未選取事件";
            detailEventId.textContent = "--";
            detailEventStatus.textContent = "--";
            detailInferenceHost.textContent = "尚未提供";
            detailCamera.textContent = "--";
            detailLocation.textContent = "尚未提供";
            detailDetectedAt.textContent = "--";
            detailCreatedAt.textContent = "--";

            detailConfirmButton.disabled = true;
            detailCloseButton.disabled = true;
            detailBroadcastButton.disabled = true;
            return;
        }

        detailEventType.textContent = normalizeText(
            event.event_type_display,
            event.event_type || "未知事件"
        );
        detailEventId.textContent = event.id;
        detailEventStatus.textContent = normalizeText(
            event.status_display,
            event.status || "未知"
        );

        const sourceHost = [event.source_host_code, event.source_host_name]
            .filter(Boolean)
            .join("｜");
        detailInferenceHost.textContent = sourceHost || "尚未提供";

        detailCamera.textContent = event.camera_id
            ? `${normalizeText(event.camera_code, "")}｜${normalizeText(event.camera_name, "")}`
            : "未指定攝影機";

        detailLocation.textContent = normalizeText(
            event.area || event.camera_area,
            "尚未提供"
        );
        detailDetectedAt.textContent = normalizeText(
            event.detected_at,
            "未提供"
        );
        detailCreatedAt.textContent = normalizeText(event.created_at, "--");

        const status = event.status || "unknown";
        detailConfirmButton.disabled =
            !canProcessEvents || !["new", "processing"].includes(status);
        detailCloseButton.disabled =
            !canProcessEvents || status !== "confirmed";
        detailBroadcastButton.disabled =
            !canProcessEvents ||
            !event.broadcast_rule_code ||
            !event.speaker_code ||
            !event.audio_code;
    }

    function selectEvent(eventId, manualSelection) {
        const event = getEventById(eventId);

        if (!event) {
            return;
        }

        const previousEventId = selectedEventId;
        selectedEventId = String(event.id);

        if (manualSelection) {
            manualSelectionUntil = Date.now() + 30000;
        }

        document.querySelectorAll("[data-event-id]").forEach(function (item) {
            item.classList.toggle(
                "selected-ai-event",
                String(item.dataset.eventId) === selectedEventId
            );
        });

        if (event.camera_id) {
            selectCamera(event.camera_id);
        }

        updateDetailPanel(event);
        setDetailMessage("", "");

        const eventChanged =
            String(previousEventId) !== String(selectedEventId);

        if (event.snapshot_url && (manualSelection || eventChanged)) {
            setMediaMode("snapshot");
            return;
        }

        renderPrimaryMedia(false);
    }

    function renderEventList(events) {
        eventList.innerHTML = "";

        if (!events.length) {
            eventList.innerHTML = `<div class="empty-state">目前尚無事件資料。</div>`;
            return;
        }

        events.forEach(function (event) {
            const item = document.createElement("article");
            item.className = "event-item clickable-event-item";
            item.dataset.eventId = event.id;

            if (event.camera_id) {
                item.dataset.eventCameraId = event.camera_id;
            }

            if (String(event.id) === String(selectedEventId)) {
                item.classList.add("selected-ai-event");
            }

            item.innerHTML = `
                <div class="event-card-top">
                    <h3>${escapeHtml(normalizeText(event.event_type_display, event.event_type || "未知事件"))}</h3>
                    <span class="event-status-tag status-${escapeHtml(event.status || "unknown")}">
                        ${escapeHtml(normalizeText(event.status_display, event.status || "未知"))}
                    </span>
                </div>
                <p>${
                    event.camera_id
                        ? `${escapeHtml(normalizeText(event.camera_code, ""))}｜${escapeHtml(normalizeText(event.camera_name, ""))}`
                        : "未指定攝影機"
                }</p>
                <div class="event-card-bottom">
                    <span>事件編號 ${escapeHtml(event.id)}</span>
                    <time>${escapeHtml(normalizeText(event.detected_at || event.created_at, ""))}</time>
                </div>
            `;

            item.addEventListener("click", function () {
                const isSameEvent =
                    String(selectedEventId) === String(event.id);

                selectEvent(event.id, true);

                if (isSameEvent && event.snapshot_url) {
                    setMediaMode("snapshot");
                }
            });

            eventList.appendChild(item);
        });
    }

    function getCameraListSignature(cameras) {
        return JSON.stringify(
            cameras.map(function (camera) {
                return [
                    camera.id,
                    camera.camera_code,
                    camera.name,
                    camera.area,
                    camera.status,
                    camera.stream_url,
                ];
            })
        );
    }

    function bindThumbnailStreamHandlers() {
        document.querySelectorAll("[data-dashboard-camera-stream]").forEach(function (stream) {
            const screen = stream.closest(".camera-thumbnail-screen");
            const overlay = screen
                ? screen.querySelector("[data-dashboard-stream-overlay]")
                : null;

            stream.addEventListener("load", function () {
                if (overlay) {
                    overlay.classList.add("hidden");
                }
            });

            stream.addEventListener("error", function () {
                if (overlay) {
                    overlay.classList.remove("hidden");
                    overlay.innerHTML = `
                        <span>${escapeHtml(stream.alt || "攝影機")}</span>
                        <small>無法取得即時影像</small>
                    `;
                }
            });
        });
    }

    function renderCameraGrid(cameras) {
        const newSignature = getCameraListSignature(cameras);

        if (newSignature === cameraSignature) {
            updateCameraSelectionClasses();
            return;
        }

        cameraSignature = newSignature;
        cameraGrid.innerHTML = "";

        if (!cameras.length) {
            cameraGrid.innerHTML = `<div class="empty-state">目前尚無事件相關攝影機。</div>`;
            return;
        }

        cameras.forEach(function (camera) {
            const button = document.createElement("button");
            button.type = "button";
            button.className = "camera-thumbnail";
            button.dataset.cameraCard = "";
            button.dataset.cameraId = camera.id;

            const streamUrl = normalizeText(
                camera.stream_url,
                `/api/cameras/${camera.id}/stream/`
            );
            const code = normalizeText(camera.camera_code, `CAM-${camera.id}`);
            const name = normalizeText(camera.name, code);

            button.innerHTML = `
                <div class="camera-thumbnail-screen">
                    <img
                        src="${escapeHtml(streamUrl)}"
                        alt="${escapeHtml(code)}"
                        data-dashboard-camera-stream
                    >
                    <div class="thumbnail-overlay" data-dashboard-stream-overlay>
                        <span>${escapeHtml(code)}</span>
                        <small>載入即時影像中</small>
                    </div>
                </div>
                <div class="camera-thumbnail-info">
                    <strong>${escapeHtml(code)}</strong>
                    <span>${escapeHtml(name)}</span>
                </div>
            `;

            button.addEventListener("click", function () {
                selectCamera(camera.id);
                setMediaMode("live");
            });

            cameraGrid.appendChild(button);
        });

        bindThumbnailStreamHandlers();
        updateCameraSelectionClasses();
    }

    function renderBroadcastLogs(logs) {
        broadcastLogContainer.innerHTML = "";

        if (!logs.length) {
            broadcastLogContainer.innerHTML = `<div class="empty-state">目前尚無廣播任務。</div>`;
            return;
        }

        logs.slice(0, 6).forEach(function (log) {
            const item = document.createElement("div");
            item.className = "broadcast-log-item";
            item.innerHTML = `
                <div>
                    <strong>${escapeHtml(normalizeText(log.event_type_display, log.event_type || "無事件"))}</strong>
                    <span>${escapeHtml(normalizeText(log.created_at, ""))}</span>
                </div>
                <span class="broadcast-status broadcast-status-${escapeHtml(log.status || "unknown")}">
                    ${escapeHtml(normalizeText(log.status_display, log.status || "未知"))}
                </span>
            `;
            broadcastLogContainer.appendChild(item);
        });
    }

    function updateCrowdFlowSummary(crowdFlow) {
        if (
            !crowdFlowMetric ||
            !crowdFlowValue ||
            !crowdFlowSummary
        ) {
            return;
        }

        const summary = crowdFlow || {};
        const hasCount =
            summary.count !== null &&
            summary.count !== undefined &&
            summary.count !== "";
        const isAbnormal = Boolean(summary.is_abnormal);

        crowdFlowMetric.classList.toggle("is-abnormal", isAbnormal);
        crowdFlowMetric.classList.toggle("is-normal", !isAbnormal);

        crowdFlowValue.textContent = isAbnormal
            ? "異常"
            : hasCount
                ? String(summary.count)
                : "--";

        const rangeLabel = normalizeText(
            summary.range_label,
            "尚未設定正常範圍"
        );

        crowdFlowSummary.textContent = hasCount
            ? `目前 ${summary.count} 人｜${rangeLabel}`
            : `尚無人流統計資料｜${rangeLabel}`;
    }

    function updateInferenceHostSummary(inferenceHosts) {
        if (
            !inferenceHostMetric ||
            !inferenceHostStatus ||
            !inferenceHostDetail
        ) {
            return;
        }

        const summary = inferenceHosts || {};
        const isAbnormal = Boolean(summary.is_abnormal);

        inferenceHostMetric.classList.toggle("is-abnormal", isAbnormal);
        inferenceHostMetric.classList.toggle("is-normal", !isAbnormal);

        inferenceHostStatus.textContent = normalizeText(
            summary.status_label,
            "尚未設定"
        );

        inferenceHostDetail.textContent = normalizeText(
            summary.detail_label,
            "尚未設定推論主機"
        );
    }

    function getLocalAlarmAudioContext() {
        if (localAlarmAudioContext) {
            return localAlarmAudioContext;
        }

        const AudioContextClass =
            window.AudioContext || window.webkitAudioContext;

        if (!AudioContextClass) {
            return null;
        }

        localAlarmAudioContext = new AudioContextClass();
        return localAlarmAudioContext;
    }

    async function unlockLocalAlarmAudio() {
        const audioContext = getLocalAlarmAudioContext();

        if (!audioContext) {
            localAlarmUnlocked = false;
            return false;
        }

        try {
            if (audioContext.state === "suspended") {
                await audioContext.resume();
            }

            localAlarmUnlocked = audioContext.state === "running";
        } catch (error) {
            console.warn("無法啟用本機警報聲：", error);
            localAlarmUnlocked = false;
        }

        return localAlarmUnlocked;
    }

    async function playLocalEventAlarm() {
        if (!localAlarmEnabled) {
            return;
        }

        const unlocked = await unlockLocalAlarmAudio();

        if (!unlocked) {
            showToast(
                "本機警報聲尚未啟用",
                "請先點擊頁面任意位置，完成瀏覽器音訊授權。",
                "error",
                8000
            );
            return;
        }

        const audioContext = getLocalAlarmAudioContext();
        const startTime = audioContext.currentTime;
        const durationSeconds = 4.2;

        const masterGain = audioContext.createGain();
        masterGain.gain.setValueAtTime(0.0001, startTime);
        masterGain.gain.exponentialRampToValueAtTime(0.22, startTime + 0.05);
        masterGain.gain.setValueAtTime(0.22, startTime + durationSeconds - 0.15);
        masterGain.gain.exponentialRampToValueAtTime(
            0.0001,
            startTime + durationSeconds
        );
        masterGain.connect(audioContext.destination);

        const oscillatorA = audioContext.createOscillator();
        const oscillatorB = audioContext.createOscillator();

        oscillatorA.type = "sawtooth";
        oscillatorB.type = "square";

        oscillatorA.frequency.setValueAtTime(720, startTime);
        oscillatorB.frequency.setValueAtTime(520, startTime);

        const modulationInterval = 0.35;
        const modulationSteps = Math.ceil(
            durationSeconds / modulationInterval
        );

        for (let index = 0; index <= modulationSteps; index += 1) {
            const time = startTime + index * modulationInterval;
            const highPhase = index % 2 === 0;

            oscillatorA.frequency.setValueAtTime(
                highPhase ? 980 : 720,
                time
            );
            oscillatorB.frequency.setValueAtTime(
                highPhase ? 680 : 520,
                time
            );
        }

        const oscillatorAGain = audioContext.createGain();
        const oscillatorBGain = audioContext.createGain();

        oscillatorAGain.gain.value = 0.72;
        oscillatorBGain.gain.value = 0.28;

        oscillatorA.connect(oscillatorAGain);
        oscillatorB.connect(oscillatorBGain);
        oscillatorAGain.connect(masterGain);
        oscillatorBGain.connect(masterGain);

        oscillatorA.start(startTime);
        oscillatorB.start(startTime);
        oscillatorA.stop(startTime + durationSeconds);
        oscillatorB.stop(startTime + durationSeconds);

        if (localAlarmStopTimer) {
            window.clearTimeout(localAlarmStopTimer);
        }

        localAlarmStopTimer = window.setTimeout(() => {
            try {
                masterGain.disconnect();
            } catch (error) {
                console.debug("本機警報聲節點已釋放。", error);
            }
        }, (durationSeconds + 0.5) * 1000);
    }

    function initializeLocalAlarm() {
        const unlockOnce = () => {
            unlockLocalAlarmAudio();
        };

        document.addEventListener("pointerdown", unlockOnce, {
            once: true,
            passive: true,
        });

        document.addEventListener("keydown", unlockOnce, {
            once: true,
        });
    }

    function updateEventWarningLight(isActive) {
        if (!eventWarningLight) {
            return;
        }

        const active = Boolean(isActive);

        eventWarningLight.classList.toggle("is-active", active);
        eventWarningLight.setAttribute(
            "aria-label",
            active ? "收到未處理的推論事件" : "事件警示燈待命"
        );
    }

    function updateSummary(data) {
        const cameras = data.cameras || [];
        const events = data.events || [];
        const latestEvent = events[0] || null;
        if (stationCameraCount) {
            stationCameraCount.textContent = String(
                data.station_camera_count ?? 0
            );
        }

        eventListCount.textContent = String(events.length);

        updateCrowdFlowSummary(data.crowd_flow);
        updateInferenceHostSummary(data.inference_hosts);
        updateEventWarningLight(data.event_alert_active);

        if (latestEvent) {
            latestEventType.textContent = normalizeText(
                latestEvent.event_type_display,
                latestEvent.event_type || "未知事件"
            );
            latestEventCamera.textContent = latestEvent.camera_id
                ? `${normalizeText(latestEvent.camera_code, "")}｜${normalizeText(latestEvent.camera_name, "")}`
                : "未指定攝影機";
            latestEventTime.textContent = normalizeText(
                latestEvent.detected_at || latestEvent.created_at,
                "--"
            );
        } else {
            latestEventType.textContent = "目前無事件";
            latestEventCamera.textContent = "系統正在等待 AI 推論事件";
            latestEventTime.textContent = "--";
        }
    }

    function getCarouselEvents() {
        const activeStatuses = new Set(["new", "processing", "confirmed"]);
        const activeEvents = currentEvents.filter(function (event) {
            return activeStatuses.has(event.status);
        });

        return activeEvents.length >= 2 ? activeEvents : currentEvents;
    }

    function rotateEvent() {
        if (!carouselEnabled || Date.now() < manualSelectionUntil) {
            return;
        }

        const events = getCarouselEvents();

        if (events.length < 2) {
            return;
        }

        const currentIndex = events.findIndex(function (event) {
            return String(event.id) === String(selectedEventId);
        });
        const nextIndex = currentIndex >= 0
            ? (currentIndex + 1) % events.length
            : 0;

        selectEvent(events[nextIndex].id, false);
    }

    function updateCarouselButton() {
        if (!eventCarouselButton) {
            return;
        }

        eventCarouselButton.textContent = carouselEnabled
            ? "輪播中"
            : "已暫停";
        eventCarouselButton.classList.toggle("is-paused", !carouselEnabled);
    }

    async function confirmSelectedEvent() {
        const event = getSelectedEvent();

        if (!event || detailConfirmButton.disabled) {
            return;
        }

        const eventId = event.id;
        detailConfirmButton.disabled = true;
        detailConfirmButton.textContent = "確認中...";
        setDetailMessage("", "");

        try {
            const response = await fetch(
                `${confirmEventUrlPrefix}${encodeURIComponent(eventId)}/confirm/`,
                {
                    method: "POST",
                    headers: {
                        "Accept": "application/json",
                        "X-Requested-With": "XMLHttpRequest",
                        "X-CSRFToken": getCookie("csrftoken"),
                    },
                }
            );

            const data = await response.json().catch(function () {
                return {};
            });

            if (!response.ok || !data.success) {
                throw new Error(data.message || `HTTP ${response.status}`);
            }

            detailConfirmButton.textContent = "已確認";
            setDetailMessage("事件已確認。", "success");

            await fetchDashboardLiveState();

            const refreshedEvent = getEventById(eventId);
            if (refreshedEvent) {
                selectedEventId = String(eventId);
                updateDetailPanel(refreshedEvent);
            }
        } catch (error) {
            detailConfirmButton.textContent = "確認事件";
            detailConfirmButton.disabled = false;
            setDetailMessage(`確認失敗：${error.message}`, "error");
        }
    }

    async function closeSelectedEvent() {
        const event = getSelectedEvent();

        if (!event || detailCloseButton.disabled) {
            return;
        }

        if (!window.confirm("確定要解除這筆事件？解除後狀態將變更為「已解除」。")) {
            return;
        }

        detailCloseButton.disabled = true;
        detailCloseButton.textContent = "解除中...";

        try {
            const response = await fetch(
                `${confirmEventUrlPrefix}${encodeURIComponent(event.id)}/close/`,
                {
                    method: "POST",
                    headers: {
                        "Accept": "application/json",
                        "X-Requested-With": "XMLHttpRequest",
                        "X-CSRFToken": getCookie("csrftoken"),
                    },
                }
            );
            const data = await response.json().catch(function () {
                return {};
            });

            if (!response.ok || !data.success) {
                throw new Error(data.message || `HTTP ${response.status}`);
            }

            setDetailMessage("事件已解除。", "success");
            await fetchDashboardLiveState();
        } catch (error) {
            setDetailMessage(`解除失敗：${error.message}`, "error");
        } finally {
            detailCloseButton.textContent = "解除事件";
        }
    }

    async function broadcastSelectedEvent() {
        const event = getSelectedEvent();

        if (!event || detailBroadcastButton.disabled) {
            return;
        }

        const warning = broadcastPlaybackIsLive
            ? `目前後端模式為「${broadcastPlaybackModeLabel}」，此操作可能讓現場廣播喇叭發聲。`
            : `目前後端模式為「${broadcastPlaybackModeLabel}」，不會呼叫實體廣播喇叭。`;

        if (!window.confirm(
            `${warning}\n\n事件編號：${event.id}\n廣播喇叭：${event.speaker_code}\n音檔：${event.audio_code}\n\n確定要執行手動廣播？`
        )) {
            return;
        }

        detailBroadcastButton.disabled = true;
        detailBroadcastButton.textContent = "廣播中...";

        try {
            const response = await fetch(
                `${manualBroadcastUrlPrefix}${encodeURIComponent(event.id)}/manual/`,
                {
                    method: "POST",
                    headers: {
                        "Accept": "application/json",
                        "X-Requested-With": "XMLHttpRequest",
                        "X-CSRFToken": getCookie("csrftoken"),
                    },
                }
            );
            const data = await response.json().catch(function () {
                return {};
            });

            if (!response.ok || !data.success) {
                throw new Error(data.message || `HTTP ${response.status}`);
            }

            setDetailMessage("手動廣播已完成。", "success");
            await fetchDashboardLiveState();
        } catch (error) {
            setDetailMessage(`廣播失敗：${error.message}`, "error");
        } finally {
            detailBroadcastButton.textContent = "手動廣播";
        }
    }

    async function processPendingBroadcastLogs() {
        processPendingBroadcastButton.disabled = true;
        processPendingBroadcastButton.textContent = "處理中...";
        processBroadcastStatus.textContent = "正在處理待播放廣播任務...";
        processBroadcastStatus.classList.remove("success", "error");

        try {
            const response = await fetch(processPendingBroadcastApiUrl, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                    "X-CSRFToken": getCookie("csrftoken"),
                },
                body: JSON.stringify({limit: 10}),
            });
            const data = await response.json().catch(function () {
                return {};
            });

            if (!response.ok || !data.success) {
                throw new Error(data.message || `HTTP ${response.status}`);
            }

            processBroadcastStatus.textContent =
                `處理完成：${data.processed_count} 筆，成功 ${data.success_count} 筆，失敗 ${data.failed_count} 筆，剩餘 ${data.pending_count} 筆。`;
            processBroadcastStatus.classList.add("success");
            await fetchDashboardLiveState();
        } catch (error) {
            processBroadcastStatus.textContent = `處理失敗：${error.message}`;
            processBroadcastStatus.classList.add("error");
        } finally {
            processPendingBroadcastButton.disabled = false;
            processPendingBroadcastButton.textContent = "處理待播放任務";
        }
    }

    async function fetchDashboardLiveState() {
        try {
            const response = await fetch(liveStateApiUrl, {
                method: "GET",
                headers: {"X-Requested-With": "XMLHttpRequest"},
            });

            if (!response.ok) {
                setPollingStatus(`資料更新失敗：HTTP ${response.status}`, true);
                return;
            }

            const data = await response.json();
            currentCameras = data.cameras || [];
            currentEvents = data.events || [];
            const logs = data.broadcast_logs || [];

            updateSummary(data);
            renderCameraGrid(currentCameras);
            renderEventList(currentEvents);
            renderBroadcastLogs(logs);

            if (currentEvents.length) {
                const latestEvent = currentEvents[0];

                if (
                    lastLatestEventId !== null &&
                    String(latestEvent.id) !== String(lastLatestEventId)
                ) {
                    selectedEventId = String(latestEvent.id);
                    selectedCameraId = latestEvent.camera_id
                        ? String(latestEvent.camera_id)
                        : null;

                    showToast(
                        "收到新的 AI 推論事件",
                        `${normalizeText(latestEvent.event_type_display, latestEvent.event_type || "未知事件")}｜${normalizeText(latestEvent.camera_code, "未指定攝影機")}`,
                        "error",
                        8000
                    );

                    playLocalEventAlarm();
                }

                lastLatestEventId = latestEvent.id;

                if (!selectedEventId || !getEventById(selectedEventId)) {
                    selectedEventId = String(latestEvent.id);
                }

                selectEvent(selectedEventId, false);
            } else {
                selectedEventId = null;
                selectedCameraId = null;
                updateDetailPanel(null);
                renderPrimaryMedia(false);
            }

            setPollingStatus(
                `資料更新：${data.server_time || "完成"}`,
                false
            );
        } catch (error) {
            console.error("Dashboard live state error:", error);
            setPollingStatus("資料更新失敗，請檢查 API 或瀏覽器主控台。", true);
        }
    }

    document.querySelectorAll("[data-media-mode]").forEach(function (button) {
        button.addEventListener("click", function () {
            setMediaMode(button.dataset.mediaMode);
        });
    });

    document.querySelectorAll("[data-planned-feature]").forEach(function (button) {
        button.addEventListener("click", function () {
            showToast(
                button.dataset.plannedFeature,
                "此快捷入口已納入介面，功能頁面將於後續階段接入。",
                "pending",
                4500
            );
        });
    });

    detailConfirmButton.addEventListener("click", confirmSelectedEvent);
    detailCloseButton.addEventListener("click", closeSelectedEvent);
    detailBroadcastButton.addEventListener("click", broadcastSelectedEvent);
    processPendingBroadcastButton.addEventListener(
        "click",
        processPendingBroadcastLogs
    );
    dashboardActionToastClose.addEventListener("click", hideToast);

    eventCarouselButton.addEventListener("click", function () {
        carouselEnabled = !carouselEnabled;
        updateCarouselButton();
    });

    updateClock();
    window.setInterval(updateClock, 1000);
    updateCarouselButton();
    carouselTimer = window.setInterval(rotateEvent, 8000);

    fetchDashboardLiveState();
    window.setInterval(fetchDashboardLiveState, 1000);
});

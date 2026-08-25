document.addEventListener("DOMContentLoaded", function () {
    const body = document.body;
    const cameraGrid = document.getElementById("cameraGrid");
    const primaryCameraStage = document.getElementById("primaryCameraStage");
    const eventList = document.getElementById("eventList");
    const eventListCount = document.getElementById("eventListCount");
    const systemDateTime = document.getElementById("systemDateTime");
    const eventCarouselButton = document.getElementById("eventCarouselButton");

    const stationCameraCount = document.getElementById("stationCameraCount");
    const latestEventType = document.getElementById("latestEventType");
    const latestEventCamera = document.getElementById("latestEventCamera");
    const latestEventTime = document.getElementById("latestEventTime");
    const dashboardPollingStatus = document.getElementById("dashboardPollingStatus");
    const inferenceHostMetric = document.getElementById("inferenceHostMetric");
    const inferenceHostStatus = document.getElementById("inferenceHostStatus");
    const inferenceHostDetail = document.getElementById("inferenceHostDetail");
    const crowdFlowMetric = document.getElementById("crowdFlowMetric");
    const areaFlowGrid = document.getElementById("areaFlowGrid");
    const areaFlowPageStatus = document.getElementById("areaFlowPageStatus");
    const eventWarningLight = document.getElementById("eventWarningLight");

    const AREA_FLOW_PAGE_SIZE = 3;
    const AREA_FLOW_ROTATE_MS = 5000;
    let areaFlowItems = [];
    let areaFlowPageIndex = 0;
    let areaFlowRotateTimer = null;
    let areaFlowCameraSignature = "";
    const resolveAllAlertEventsButton = document.getElementById(
        "resolveAllAlertEventsButton"
    );

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
    const manualBroadcastModal = document.getElementById("manualBroadcastModal");
    const manualBroadcastClose = document.getElementById("manualBroadcastClose");
    const manualBroadcastCancel = document.getElementById("manualBroadcastCancel");
    const manualBroadcastSubmit = document.getElementById("manualBroadcastSubmit");
    const manualBroadcastSpeaker = document.getElementById("manualBroadcastSpeaker");
    const manualBroadcastAudio = document.getElementById("manualBroadcastAudio");
    const manualBroadcastEventSummary = document.getElementById("manualBroadcastEventSummary");
    const manualBroadcastHint = document.getElementById("manualBroadcastHint");

    const dashboardActionToast = document.getElementById("dashboardActionToast");
    const dashboardActionToastTitle = document.getElementById("dashboardActionToastTitle");
    const dashboardActionToastMessage = document.getElementById("dashboardActionToastMessage");
    const dashboardActionToastClose = document.getElementById("dashboardActionToastClose");

    const liveStateApiUrl = body.dataset.dashboardLiveStateUrl;
    const closeActiveAlertsUrl = body.dataset.closeActiveAlertsUrl;
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
    let localAlarmEnabled = true;
    let localAlarmUnlocked = false;
    let localAlarmAudioContext = null;
    let localAlarmRepeatTimer = null;
    let localAlarmNodes = [];
    let knownEventIds = null;
    const alarmEventIds = new Set();

    let cameraSignature = "";
    let toastTimer = null;
    let primaryMediaMode = "live";
    let renderedPrimaryKey = "";
    let carouselEnabled = true;
    let carouselTimer = null;
    let manualSelectionUntil = 0;
    let manualSelectionResumeTimer = null;

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

        detailInferenceHost.textContent = normalizeText(
            event.source_host_name,
            event.source_host_code || "尚未提供"
        );

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
            !canProcessEvents || ["dismissed", "closed"].includes(status);
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
            scheduleManualCarouselResume();
            updateCarouselButton();
        }

        document.querySelectorAll("[data-event-id]").forEach(function (item) {
            item.classList.toggle(
                "selected-ai-event",
                String(item.dataset.eventId) === selectedEventId
            );
        });

        if (event.camera_id) {
            selectCamera(event.camera_id);
        } else {
            // Unmapped events must not retain the previous camera selection.
            // This applies to both manual selection and automatic carousel changes.
            selectCamera(null);
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
        const isUnconfigured = Boolean(summary.is_unconfigured) ||
            Number(summary.configured_count || 0) === 0;

        inferenceHostMetric.classList.toggle("is-abnormal", isAbnormal);
        inferenceHostMetric.classList.toggle("is-unconfigured", isUnconfigured);
        inferenceHostMetric.classList.toggle(
            "is-normal",
            !isAbnormal && !isUnconfigured
        );

        inferenceHostStatus.textContent = normalizeText(
            summary.status_label,
            "未設定主機"
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

    function stopLocalEventAlarm() {
        if (localAlarmRepeatTimer) {
            window.clearTimeout(localAlarmRepeatTimer);
            localAlarmRepeatTimer = null;
        }

        localAlarmNodes.forEach(function (node) {
            try {
                node.stop();
            } catch (error) {
                // The oscillator may already have stopped naturally.
            }

            try {
                node.disconnect();
            } catch (error) {
                // The node may already be disconnected.
            }
        });
        localAlarmNodes = [];
    }

    async function playLocalEventAlarm() {
        if (!localAlarmEnabled || alarmEventIds.size === 0) {
            stopLocalEventAlarm();
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
            return false;
        }

        stopLocalEventAlarm();

        const audioContext = getLocalAlarmAudioContext();
        const startTime = audioContext.currentTime;
        const durationSeconds = 2.4;

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

        localAlarmNodes = [
            oscillatorA,
            oscillatorB,
            oscillatorAGain,
            oscillatorBGain,
            masterGain,
        ];

        localAlarmRepeatTimer = window.setTimeout(function () {
            localAlarmNodes.forEach(function (node) {
                try {
                    node.disconnect();
                } catch (error) {
                    // The node may already be disconnected.
                }
            });
            localAlarmNodes = [];
            localAlarmRepeatTimer = null;

            if (alarmEventIds.size > 0) {
                playLocalEventAlarm();
            }
        }, (durationSeconds + 1.2) * 1000);

        return true;
    }

    function initializeLocalAlarm() {
        const unlockOnce = async () => {
            const unlocked = await unlockLocalAlarmAudio();
            if (unlocked && alarmEventIds.size > 0 && !localAlarmRepeatTimer) {
                playLocalEventAlarm();
            }
        };

        document.addEventListener("pointerdown", unlockOnce, {
            once: true,
            passive: true,
        });

        document.addEventListener("keydown", unlockOnce, {
            once: true,
        });
    }

    function reconcileLocalEventAlarm(events, localAlarmState) {
        const currentIds = new Set(
            events.map(function (event) {
                return String(event.id);
            })
        );
        const previousAlarmIds = new Set(alarmEventIds);
        const serverAlarmIds = new Set(
            (localAlarmState && localAlarmState.enabled
                ? localAlarmState.active_event_ids || []
                : []
            ).map(String)
        );

        const newActiveEvents = events.filter(function (event) {
            const eventId = String(event.id);
            return serverAlarmIds.has(eventId) && !previousAlarmIds.has(eventId);
        });

        alarmEventIds.clear();
        serverAlarmIds.forEach(function (eventId) {
            alarmEventIds.add(eventId);
        });

        knownEventIds = currentIds;

        if (alarmEventIds.size === 0) {
            stopLocalEventAlarm();
        } else if (!localAlarmRepeatTimer) {
            playLocalEventAlarm();
        }

        return newActiveEvents;
    }

    function escapeAreaFlowText(value, fallback = "--") {
        const text = String(value ?? "").trim();
        return text || fallback;
    }

    function renderAreaFlowPage() {
        if (!areaFlowGrid) {
            return;
        }

        const totalPages = Math.max(1, Math.ceil(areaFlowItems.length / AREA_FLOW_PAGE_SIZE));
        areaFlowPageIndex = Math.min(areaFlowPageIndex, totalPages - 1);

        const pageStart = areaFlowPageIndex * AREA_FLOW_PAGE_SIZE;
        const pageItems = areaFlowItems.slice(pageStart, pageStart + AREA_FLOW_PAGE_SIZE);
        const cells = [];

        pageItems.forEach(function (item) {
            const zoneLabel = escapeAreaFlowText(item.zone_label, "未命名區域");
            const cameraCode = escapeAreaFlowText(item.camera_code ?? item.camera_id, "--");
            const hasCount = item.count !== null && item.count !== undefined;
            const countText = hasCount ? `${item.count} 人` : "--";
            const abnormalClass = item.is_abnormal ? " is-abnormal" : "";

            cells.push(`
                <div class="area-flow-cell${abnormalClass}" data-zone-key="${escapeHtml(item.zone_key ?? "")}" title="${escapeHtml(cameraCode)}">
                    <span class="area-flow-camera">${escapeHtml(zoneLabel)}</span>
                    <span class="area-flow-area">${escapeHtml(cameraCode)}</span>
                    <strong class="area-flow-count">${escapeHtml(countText)}</strong>
                </div>
            `);
        });

        while (cells.length < AREA_FLOW_PAGE_SIZE) {
            cells.push(`
                <div class="area-flow-cell is-empty">
                    <span class="area-flow-camera">--</span>
                    <span class="area-flow-area">${areaFlowItems.length ? "等待區域資料" : "尚無區域人流資料"}</span>
                    <strong class="area-flow-count">--</strong>
                </div>
            `);
        }

        areaFlowGrid.innerHTML = cells.join("");

        if (areaFlowPageStatus) {
            areaFlowPageStatus.textContent = totalPages > 1
                ? `${areaFlowPageIndex + 1}/${totalPages}`
                : `${areaFlowItems.length} 個區域`;
        }
    }

    function restartAreaFlowCarousel() {
        if (areaFlowRotateTimer) {
            window.clearInterval(areaFlowRotateTimer);
            areaFlowRotateTimer = null;
        }

        if (areaFlowItems.length <= AREA_FLOW_PAGE_SIZE) {
            return;
        }

        areaFlowRotateTimer = window.setInterval(function () {
            const totalPages = Math.ceil(areaFlowItems.length / AREA_FLOW_PAGE_SIZE);
            areaFlowPageIndex = (areaFlowPageIndex + 1) % totalPages;
            renderAreaFlowPage();
        }, AREA_FLOW_ROTATE_MS);
    }

    function updateAreaCrowdFlow(items) {
        if (!crowdFlowMetric || !areaFlowGrid) {
            return;
        }

        const nextItems = Array.isArray(items) ? items : [];
        const nextSignature = nextItems.map(function (item) {
            return String(item.zone_key ?? `${item.camera_id ?? ""}:${item.zone_label ?? ""}`);
        }).join("|");

        areaFlowItems = nextItems;

        if (nextSignature !== areaFlowCameraSignature) {
            areaFlowCameraSignature = nextSignature;
            areaFlowPageIndex = 0;
            restartAreaFlowCarousel();
        }

        renderAreaFlowPage();
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

    function updateActiveAlarmControls(localAlarmState) {
        const activeCount = Number(localAlarmState?.active_count || 0);

        if (resolveAllAlertEventsButton) {
            resolveAllAlertEventsButton.disabled =
                !canProcessEvents || activeCount === 0;
            resolveAllAlertEventsButton.title =
                activeCount > 0
                    ? `一鍵解除目前 ${activeCount} 筆告警事件`
                    : "目前沒有告警事件需要解除";
            resolveAllAlertEventsButton.setAttribute(
                "aria-label",
                resolveAllAlertEventsButton.title
            );
        }
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

        updateInferenceHostSummary(data.inference_hosts);
        updateAreaCrowdFlow(data.crowd_flow_items);
        updateEventWarningLight(data.event_alert_active);
        updateActiveAlarmControls(data.local_alarm || {});

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
        // Only unresolved cards shown as "待處理" participate in rotation.
        // Support both the canonical backend status and the localized display label.
        return currentEvents.filter(function (event) {
            const status = String(event.status || "").trim().toLowerCase();
            const statusDisplay = String(event.status_display || "").trim();
            return status === "new" || statusDisplay === "待處理";
        });
    }

    function isCarouselPaused() {
        return !carouselEnabled || Date.now() < manualSelectionUntil;
    }

    function scheduleManualCarouselResume() {
        if (manualSelectionResumeTimer) {
            window.clearTimeout(manualSelectionResumeTimer);
        }

        const delay = Math.max(0, manualSelectionUntil - Date.now());
        manualSelectionResumeTimer = window.setTimeout(function () {
            manualSelectionResumeTimer = null;
            manualSelectionUntil = 0;
            updateCarouselButton();
        }, delay + 20);
    }

    function rotateEvent() {
        if (isCarouselPaused()) {
            updateCarouselButton();
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

        const paused = isCarouselPaused();
        eventCarouselButton.textContent = paused ? "已暫停" : "輪播中";
        eventCarouselButton.classList.toggle("is-paused", paused);
        eventCarouselButton.setAttribute("aria-pressed", paused ? "true" : "false");
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

    async function closeAllActiveAlarmEvents() {
        if (
            !resolveAllAlertEventsButton ||
            resolveAllAlertEventsButton.disabled ||
            !closeActiveAlertsUrl
        ) {
            return;
        }

        if (!window.confirm("確定要解除目前所有告警事件？解除後警示燈與本機警報聲會停止。")) {
            return;
        }

        resolveAllAlertEventsButton.disabled = true;
        resolveAllAlertEventsButton.textContent = "解除中...";
        setDetailMessage("", "");

        try {
            const response = await fetch(closeActiveAlertsUrl, {
                method: "POST",
                headers: {
                    "Accept": "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                    "X-CSRFToken": getCookie("csrftoken"),
                },
            });
            const data = await response.json().catch(function () {
                return {};
            });

            if (!response.ok || !data.success) {
                throw new Error(data.message || `HTTP ${response.status}`);
            }

            alarmEventIds.clear();
            stopLocalEventAlarm();
            updateEventWarningLight(false);
            updateActiveAlarmControls({active_count: 0});

            showToast(
                "告警事件已解除",
                `已解除 ${data.closed_count || 0} 筆目前告警事件。`,
                "success",
                6000
            );
            await fetchDashboardLiveState();
        } catch (error) {
            showToast(
                "一鍵解除失敗",
                error.message || "請稍後再試或檢查後端 API。",
                "error",
                8000
            );
        } finally {
            resolveAllAlertEventsButton.textContent = "解除全部事件";
        }
    }

    function closeManualBroadcastModal() {
        manualBroadcastModal.hidden = true;
        manualBroadcastHint.textContent = "";
    }

    async function openManualBroadcastModal() {
        const event = getSelectedEvent();
        if (!event || detailBroadcastButton.disabled) {
            return;
        }

        manualBroadcastSpeaker.innerHTML = '<option value="">載入中...</option>';
        manualBroadcastAudio.innerHTML = '<option value="">載入中...</option>';
        manualBroadcastEventSummary.textContent = `事件 ${event.id}｜${normalizeText(event.event_type_display, event.event_type || "未知事件")}`;
        manualBroadcastHint.textContent = "";
        manualBroadcastSubmit.disabled = false;
        manualBroadcastModal.hidden = false;

        try {
            const response = await fetch(
                `${manualBroadcastUrlPrefix}${encodeURIComponent(event.id)}/manual/`,
                {headers: {"Accept": "application/json", "X-Requested-With": "XMLHttpRequest"}}
            );
            const data = await response.json().catch(function () { return {}; });
            if (!response.ok || !data.success) {
                throw new Error(data.message || `HTTP ${response.status}`);
            }

            manualBroadcastSpeaker.innerHTML = '<option value="">請選擇廣播喇叭</option>' +
                data.speakers.map(function (speaker) {
                    const statusText = speaker.available ? "正常" : `狀態：${speaker.status_display || speaker.status}`;
                    return `<option value="${speaker.id}" ${String(data.default.speaker_id) === String(speaker.id) ? "selected" : ""}>${escapeHtml(speaker.code)}｜${escapeHtml(speaker.name)}（${escapeHtml(statusText)}）</option>`;
                }).join("");

            manualBroadcastAudio.innerHTML = '<option value="">請選擇廣播音檔</option>' +
                data.audio_files.map(function (audio) {
                    const suffix = audio.file_available ? "" : "（檔案缺失）";
                    return `<option value="${audio.id}" ${String(data.default.audio_file_id) === String(audio.id) ? "selected" : ""}>${escapeHtml(audio.code)}｜${escapeHtml(audio.name)}${escapeHtml(suffix)}</option>`;
                }).join("");

            if (data.default.rule_code) {
                manualBroadcastHint.textContent = `已帶入規則 ${data.default.rule_code} 的 Speaker 與音檔，可自行調整。`;
            } else {
                manualBroadcastHint.textContent = "此事件沒有既有廣播規則，請手動選擇 Speaker 與音檔。";
            }
        } catch (error) {
            manualBroadcastHint.textContent = `載入失敗：${error.message}`;
            manualBroadcastSubmit.disabled = true;
        }
    }

    async function submitManualBroadcast() {
        const event = getSelectedEvent();
        const speakerId = manualBroadcastSpeaker.value;
        const audioFileId = manualBroadcastAudio.value;
        if (!event || !speakerId || !audioFileId) {
            manualBroadcastHint.textContent = "請選擇廣播喇叭與音檔。";
            return;
        }

        const speakerText = manualBroadcastSpeaker.options[manualBroadcastSpeaker.selectedIndex].text;
        const audioText = manualBroadcastAudio.options[manualBroadcastAudio.selectedIndex].text;
        const warning = broadcastPlaybackIsLive
            ? `目前後端模式為「${broadcastPlaybackModeLabel}」，此操作可能讓現場廣播喇叭發聲。`
            : `目前後端模式為「${broadcastPlaybackModeLabel}」，不會呼叫實體廣播喇叭。`;
        if (!window.confirm(`${warning}

事件編號：${event.id}
廣播喇叭：${speakerText}
音檔：${audioText}

確定要執行手動廣播？`)) {
            return;
        }

        manualBroadcastSubmit.disabled = true;
        manualBroadcastSubmit.textContent = "廣播中...";
        try {
            const response = await fetch(
                `${manualBroadcastUrlPrefix}${encodeURIComponent(event.id)}/manual/`,
                {
                    method: "POST",
                    headers: {
                        "Accept": "application/json",
                        "Content-Type": "application/json",
                        "X-Requested-With": "XMLHttpRequest",
                        "X-CSRFToken": getCookie("csrftoken"),
                    },
                    body: JSON.stringify({speaker_id: Number(speakerId), audio_file_id: Number(audioFileId)}),
                }
            );
            const data = await response.json().catch(function () { return {}; });
            if (!response.ok || !data.success) {
                throw new Error(data.message || `HTTP ${response.status}`);
            }
            closeManualBroadcastModal();
            setDetailMessage(`手動廣播已完成：${data.speaker_code}｜${data.audio_code}`, "success");
            await fetchDashboardLiveState();
        } catch (error) {
            manualBroadcastHint.textContent = `廣播失敗：${error.message}`;
        } finally {
            manualBroadcastSubmit.disabled = false;
            manualBroadcastSubmit.textContent = "開始廣播";
        }
    }

    async function broadcastSelectedEvent() {
        await openManualBroadcastModal();
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

            updateSummary(data);
            renderCameraGrid(currentCameras);
            renderEventList(currentEvents);

            const newAlarmEvents = reconcileLocalEventAlarm(
                currentEvents,
                data.local_alarm || {}
            );

            if (currentEvents.length) {
                const latestEvent = currentEvents[0];

                if (newAlarmEvents.length > 0) {
                    const newestAlarmEvent = newAlarmEvents[0];
                    selectedEventId = String(newestAlarmEvent.id);
                    selectedCameraId = newestAlarmEvent.camera_id
                        ? String(newestAlarmEvent.camera_id)
                        : null;

                    showToast(
                        newAlarmEvents.length > 1
                            ? `收到 ${newAlarmEvents.length} 筆新的 AI 推論事件`
                            : "收到新的 AI 推論事件",
                        `${normalizeText(newestAlarmEvent.event_type_display, newestAlarmEvent.event_type || "未知事件")}｜${normalizeText(newestAlarmEvent.camera_code, "未指定攝影機")}`,
                        "error",
                        8000
                    );
                }

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
    manualBroadcastClose.addEventListener("click", closeManualBroadcastModal);
    manualBroadcastCancel.addEventListener("click", closeManualBroadcastModal);
    manualBroadcastSubmit.addEventListener("click", submitManualBroadcast);
    manualBroadcastModal.addEventListener("click", function (event) {
        if (event.target === manualBroadcastModal) {
            closeManualBroadcastModal();
        }
    });
    if (resolveAllAlertEventsButton) {
        resolveAllAlertEventsButton.addEventListener(
            "click",
            closeAllActiveAlarmEvents
        );
    }
    dashboardActionToastClose.addEventListener("click", hideToast);

    eventCarouselButton.addEventListener("click", function () {
        if (Date.now() < manualSelectionUntil) {
            manualSelectionUntil = 0;
            carouselEnabled = true;
            if (manualSelectionResumeTimer) {
                window.clearTimeout(manualSelectionResumeTimer);
                manualSelectionResumeTimer = null;
            }
            updateCarouselButton();
            rotateEvent();
            return;
        }

        carouselEnabled = !carouselEnabled;
        updateCarouselButton();
    });

    updateClock();
    window.setInterval(updateClock, 1000);
    updateCarouselButton();
    initializeLocalAlarm();
    carouselTimer = window.setInterval(rotateEvent, 2000);

    fetchDashboardLiveState();
    window.setInterval(fetchDashboardLiveState, 1000);
});

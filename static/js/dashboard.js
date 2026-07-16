document.addEventListener("DOMContentLoaded", function () {
    const cameraGrid = document.getElementById("cameraGrid");
    const eventList = document.getElementById("eventList");
    const broadcastLogTableBody = document.getElementById("broadcastLogTableBody");
    const eventCameraCount = document.getElementById("eventCameraCount");
    const recentEventsCount = document.getElementById("recentEventsCount");
    const pendingBroadcastLogsCount = document.getElementById("pendingBroadcastLogsCount");
    const pendingBroadcastMetric = document.getElementById("pendingBroadcastMetric");
    const latestEventType = document.getElementById("latestEventType");
    const latestEventCamera = document.getElementById("latestEventCamera");
    const latestEventTime = document.getElementById("latestEventTime");
    const dashboardPollingStatus = document.getElementById("dashboardPollingStatus");
    const processPendingBroadcastButton = document.getElementById("processPendingBroadcastButton");
    const processBroadcastStatus = document.getElementById("processBroadcastStatus");

    const liveStateApiUrl = document.body.dataset.dashboardLiveStateUrl;
    const processPendingBroadcastApiUrl = document.body.dataset.processPendingBroadcastUrl;
    const confirmEventUrlPrefix = document.body.dataset.confirmEventUrlPrefix || "/api/events/";
    const canProcessEvents = document.body.dataset.canProcessEvents === "true";

    let lastLatestEventId = null;
    let lastSelectedCameraId = null;
    let lastSelectedEventId = null;

    if (!cameraGrid) {
        return;
    }

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
            const trimmedCookie = cookie.trim();
            const separatorIndex = trimmedCookie.indexOf("=");
            const cookieName = separatorIndex >= 0
                ? trimmedCookie.slice(0, separatorIndex)
                : trimmedCookie;

            if (cookieName === name) {
                const cookieValue = separatorIndex >= 0
                    ? trimmedCookie.slice(separatorIndex + 1)
                    : "";
                return decodeURIComponent(cookieValue);
            }
        }

        return "";
    }

    function setPollingStatus(message, isError) {
        if (!dashboardPollingStatus) {
            return;
        }

        dashboardPollingStatus.textContent = message;

        if (isError) {
            dashboardPollingStatus.classList.add("error");
        } else {
            dashboardPollingStatus.classList.remove("error");
        }
    }

    function setProcessBroadcastStatus(message, statusType) {
        if (!processBroadcastStatus) {
            return;
        }

        processBroadcastStatus.textContent = message;
        processBroadcastStatus.classList.remove("success", "error");

        if (statusType === "success") {
            processBroadcastStatus.classList.add("success");
        }

        if (statusType === "error") {
            processBroadcastStatus.classList.add("error");
        }
    }

    function focusEventCamera(cameraId) {
        if (!cameraId) {
            return;
        }

        lastSelectedCameraId = String(cameraId);

        const cameraCards = cameraGrid.querySelectorAll("[data-camera-card]");
        const targetCard = cameraGrid.querySelector(`[data-camera-id="${cameraId}"]`);

        cameraCards.forEach(function (card) {
            card.classList.remove("selected-event-camera-card");
        });

        if (!targetCard) {
            return;
        }

        cameraGrid.prepend(targetCard);
        targetCard.classList.add("selected-event-camera-card");

        targetCard.scrollIntoView({
            behavior: "smooth",
            block: "center",
        });
    }

    function bindEventItemClickHandlers() {
        const eventItems = document.querySelectorAll("[data-event-camera-id]");

        eventItems.forEach(function (item) {
            item.addEventListener("click", function () {
                const cameraId = item.dataset.eventCameraId;
                const eventId = item.dataset.eventId;

                lastSelectedCameraId = cameraId ? String(cameraId) : null;
                lastSelectedEventId = eventId ? String(eventId) : null;

                eventItems.forEach(function (eventItem) {
                    eventItem.classList.remove("selected-ai-event");
                });

                item.classList.add("selected-ai-event");

                if (cameraId) {
                    focusEventCamera(cameraId);
                }
            });
        });
    }

    function buildConfirmEventButton(eventId, eventStatus) {
        if (!canProcessEvents) {
            return "";
        }

        if (eventStatus === "new" || eventStatus === "processing") {
            return `
                <div class="event-actions">
                    <button
                        type="button"
                        class="confirm-event-button"
                        data-confirm-event
                        data-event-id="${escapeHtml(eventId)}"
                    >
                        \u78ba\u8a8d\u4e8b\u4ef6
                    </button>
                    <span class="event-action-message" data-event-action-message></span>
                </div>
            `;
        }

        if (eventStatus === "confirmed") {
            return `
                <div class="event-actions">
                    <button
                        type="button"
                        class="confirm-event-button is-confirmed"
                        disabled
                    >
                        \u5df2\u78ba\u8a8d
                    </button>
                </div>
            `;
        }

        return "";
    }

    async function confirmEvent(button) {
        const eventId = button.dataset.eventId;
        const actions = button.closest(".event-actions");
        const message = actions
            ? actions.querySelector("[data-event-action-message]")
            : null;

        if (!eventId || button.disabled) {
            return;
        }

        button.disabled = true;
        button.textContent = "\u78ba\u8a8d\u4e2d...";

        if (message) {
            message.textContent = "";
            message.classList.remove("success", "error");
        }

        try {
            const response = await fetch(
                `${confirmEventUrlPrefix}${encodeURIComponent(eventId)}/confirm/`,
                {
                    method: "POST",
                    headers: {
                        "Accept": "application/json",
                        "X-Requested-With": "XMLHttpRequest",
                        "X-CSRFToken": getCookie("csrftoken")
                    }
                }
            );
            const data = await response.json().catch(function () {
                return {};
            });

            if (!response.ok || !data.success) {
                throw new Error(data.message || `HTTP ${response.status}`);
            }

            button.textContent = "\u5df2\u78ba\u8a8d";
            button.classList.add("is-confirmed");

            if (message) {
                message.textContent = "\u4e8b\u4ef6\u5df2\u78ba\u8a8d";
                message.classList.add("success");
            }

            await fetchDashboardLiveState();
        } catch (error) {
            console.error("Failed to confirm event:", error);
            button.disabled = false;
            button.textContent = "\u78ba\u8a8d\u4e8b\u4ef6";

            if (message) {
                message.textContent = `\u78ba\u8a8d\u5931\u6557\uff1a${error.message}`;
                message.classList.add("error");
            }
        }
    }

    function bindConfirmEventHandlers() {
        const confirmButtons = document.querySelectorAll("[data-confirm-event]");

        confirmButtons.forEach(function (button) {
            button.addEventListener("click", function (event) {
                event.preventDefault();
                event.stopPropagation();
                confirmEvent(button);
            });
        });
    }

    function bindStreamHandlers() {
        const dashboardStreams = document.querySelectorAll("[data-dashboard-camera-stream]");

        dashboardStreams.forEach(function (stream) {
            stream.addEventListener("load", function () {
                const card = stream.closest("[data-camera-card]");

                if (!card) {
                    return;
                }

                const overlay = card.querySelector("[data-dashboard-stream-overlay]");

                if (overlay) {
                    overlay.classList.add("hidden");
                }
            });

            stream.addEventListener("error", function () {
                const card = stream.closest("[data-camera-card]");

                if (!card) {
                    return;
                }

                const overlay = card.querySelector("[data-dashboard-stream-overlay]");

                if (overlay) {
                    overlay.classList.remove("hidden");
                    overlay.innerHTML = `
                        <div>
                            <div class="camera-code">${escapeHtml(stream.alt || "CAMERA")}</div>
                            <div class="placeholder-text">Stream unavailable</div>
                        </div>
                    `;
                }
            });

            setTimeout(function () {
                const card = stream.closest("[data-camera-card]");

                if (!card) {
                    return;
                }

                const overlay = card.querySelector("[data-dashboard-stream-overlay]");

                if (!overlay || overlay.classList.contains("hidden")) {
                    return;
                }

                overlay.innerHTML = `
                    <div>
                        <div class="camera-code">${escapeHtml(stream.alt || "CAMERA")}</div>
                        <div class="placeholder-text">Still loading live stream...</div>
                    </div>
                `;
            }, 15000);
        });
    }

    function getCameraStreamUrl(camera) {
        if (camera.stream_url) {
            return camera.stream_url;
        }

        return `/api/cameras/${camera.id}/stream/`;
    }

    function renderCameraGrid(cameras, highlightedCameraId) {
        cameraGrid.innerHTML = "";

        if (!cameras || cameras.length === 0) {
            cameraGrid.innerHTML = `
                <div class="empty-state">
                    \u76ee\u524d\u5c1a\u7121\u4e8b\u4ef6\u76f8\u95dc\u651d\u5f71\u6a5f\u3002\u8acb\u5148\u900f\u904e AI Event Trigger \u5efa\u7acb\u4e8b\u4ef6\u3002
                </div>
            `;

            if (eventCameraCount) {
                eventCameraCount.textContent = "0";
            }

            return;
        }

        cameras.forEach(function (camera) {
            const cameraId = camera.id;
            const cameraCode = normalizeText(camera.camera_code, "CAM-" + cameraId);
            const cameraName = normalizeText(camera.name, cameraCode);
            const area = normalizeText(camera.area, "\u672a\u8a2d\u5b9a\u5340\u57df");
            const status = normalizeText(camera.status, "unknown");
            const statusDisplay = normalizeText(camera.status_display, status);
            const description = normalizeText(camera.description, "");
            const streamUrl = getCameraStreamUrl(camera);

            const isHighlighted = String(cameraId) === String(highlightedCameraId);
            const isSelected = String(cameraId) === String(lastSelectedCameraId);
            const shouldHighlight = lastSelectedCameraId ? isSelected : isHighlighted;

            const card = document.createElement("div");
            card.className = "camera-card event-camera-card";

            if (shouldHighlight) {
                card.classList.add("selected-event-camera-card");
            }

            card.dataset.cameraCard = "";
            card.dataset.cameraId = cameraId;

            card.innerHTML = `
                <div class="camera-screen">
                    <img
                        src="${escapeHtml(streamUrl)}"
                        alt="${escapeHtml(cameraCode)}"
                        class="dashboard-camera-stream"
                        data-dashboard-camera-stream
                    >

                    <div class="dashboard-stream-overlay" data-dashboard-stream-overlay>
                        <div>
                            <div class="camera-code">${escapeHtml(cameraCode)}</div>
                            <div class="placeholder-text">Loading live stream...</div>
                        </div>
                    </div>

                    <div class="event-camera-badge">
                        \u4e8b\u4ef6\u651d\u5f71\u6a5f
                    </div>
                </div>

                <div class="camera-info">
                    <div>
                        <h3>${escapeHtml(cameraName)}</h3>
                        <p>${escapeHtml(area)}</p>
                    </div>

                    <span class="camera-status status-${escapeHtml(status)}">
                        ${escapeHtml(statusDisplay)}
                    </span>
                </div>

                ${
                    description
                        ? `<div class="camera-description">${escapeHtml(description)}</div>`
                        : ""
                }
            `;

            cameraGrid.appendChild(card);
        });

        if (eventCameraCount) {
            eventCameraCount.textContent = String(cameras.length);
        }

        bindStreamHandlers();
    }

    function renderEventList(events) {
        if (!eventList) {
            return;
        }

        eventList.innerHTML = "";

        if (!events || events.length === 0) {
            eventList.innerHTML = `
                <div class="empty-state">
                    \u76ee\u524d\u5c1a\u7121\u4e8b\u4ef6\u8cc7\u6599\u3002
                </div>
            `;

            if (recentEventsCount) {
                recentEventsCount.textContent = "0";
            }

            return;
        }

        events.forEach(function (event) {
            const eventId = event.id;
            const cameraId = event.camera_id;
            const eventType = normalizeText(event.event_type_display, event.event_type || "\u672a\u77e5\u4e8b\u4ef6");
            const status = normalizeText(event.status_display, event.status || "unknown");
            const statusCode = normalizeText(event.status, "unknown");
            const cameraCode = normalizeText(event.camera_code, "");
            const cameraName = normalizeText(event.camera_name, "");
            const createdAt = normalizeText(event.created_at, "");
            const confidence = event.confidence;

            const item = document.createElement("div");
            item.className = "event-item clickable-event-item";

            if (String(eventId) === String(lastSelectedEventId)) {
                item.classList.add("selected-ai-event");
            }

            item.dataset.eventId = eventId;

            if (cameraId) {
                item.dataset.eventCameraId = cameraId;
            }

            const cameraText = cameraId
                ? `\u651d\u5f71\u6a5f\uff1a${escapeHtml(cameraCode)} - ${escapeHtml(cameraName)}`
                : "\u651d\u5f71\u6a5f\uff1a\u672a\u6307\u5b9a";

            item.innerHTML = `
                <h3 class="event-type">${escapeHtml(eventType)}</h3>
                <p class="event-meta">${cameraText}</p>
                <p class="event-status" data-event-status>\u72c0\u614b\uff1a${escapeHtml(status)}</p>
                ${
                    confidence !== null && confidence !== undefined && confidence !== ""
                        ? `<p>\u4fe1\u5fc3\u5206\u6578\uff1a${escapeHtml(confidence)}</p>`
                        : ""
                }
                <p>\u6642\u9593\uff1a${escapeHtml(createdAt)}</p>
                ${buildConfirmEventButton(eventId, statusCode)}
            `;

            eventList.appendChild(item);
        });

        if (recentEventsCount) {
            recentEventsCount.textContent = String(events.length);
        }

        bindEventItemClickHandlers();
        bindConfirmEventHandlers();
    }

    function renderBroadcastLogs(logs) {
        if (!broadcastLogTableBody) {
            return;
        }

        broadcastLogTableBody.innerHTML = "";

        if (!logs || logs.length === 0) {
            broadcastLogTableBody.innerHTML = `
                <tr>
                    <td colspan="7" class="empty-table-message">
                        \u5c1a\u672a\u5efa\u7acb\u5ee3\u64ad\u4efb\u52d9\u3002\u53ef\u900f\u904e POST /api/events/trigger/ \u5efa\u7acb\u6e2c\u8a66\u4e8b\u4ef6\u3002
                    </td>
                </tr>
            `;
            return;
        }

        logs.forEach(function (log) {
            const createdAt = normalizeText(log.created_at, "");
            const eventType = normalizeText(log.event_type_display, log.event_type || "\u7121\u4e8b\u4ef6");
            const eventCameraCode = normalizeText(log.event_camera_code, "");
            const eventCameraName = normalizeText(log.event_camera_name, "");
            const ruleCode = normalizeText(log.rule_code, "\u7121\u898f\u5247");
            const ruleName = normalizeText(log.rule_name, "");
            const speakerCode = normalizeText(log.speaker_code, "\u7121 Speaker");
            const speakerName = normalizeText(log.speaker_name, "");
            const sipUri = normalizeText(log.resolved_sip_uri, log.sip_uri || "-");
            const audioCode = normalizeText(log.audio_code, "\u7121\u97f3\u6a94");
            const audioName = normalizeText(log.audio_file_name, log.audio_name || "");
            const status = normalizeText(log.status, "unknown");
            const statusDisplay = normalizeText(log.status_display, status);

            const eventCameraText = eventCameraCode || eventCameraName
                ? `<div class="broadcast-sub-text">${escapeHtml(eventCameraCode)} - ${escapeHtml(eventCameraName)}</div>`
                : "";

            const ruleSubText = ruleName
                ? `<div class="broadcast-sub-text">${escapeHtml(ruleName)}</div>`
                : "";

            const speakerSubText = speakerName
                ? `<div class="broadcast-sub-text">${escapeHtml(speakerName)}</div>`
                : "";

            const audioSubText = audioName
                ? `<div class="broadcast-sub-text">${escapeHtml(audioName)}</div>`
                : "";

            const row = document.createElement("tr");

            row.innerHTML = `
                <td>
                    <div class="broadcast-main-text">${escapeHtml(createdAt)}</div>
                </td>

                <td>
                    <div class="broadcast-main-text">${escapeHtml(eventType)}</div>
                    ${eventCameraText}
                </td>

                <td>
                    <div class="broadcast-main-text">${escapeHtml(ruleCode)}</div>
                    ${ruleSubText}
                </td>

                <td>
                    <div class="broadcast-main-text">${escapeHtml(speakerCode)}</div>
                    ${speakerSubText}
                </td>

                <td>
                    <div class="broadcast-main-text">${escapeHtml(sipUri)}</div>
                </td>

                <td>
                    <div class="broadcast-main-text">${escapeHtml(audioCode)}</div>
                    ${audioSubText}
                </td>

                <td>
                    <span class="broadcast-status broadcast-status-${escapeHtml(status)}">
                        ${escapeHtml(statusDisplay)}
                    </span>
                </td>
            `;

            broadcastLogTableBody.appendChild(row);
        });
    }

    function updateSummary(data) {
        const cameras = data.cameras || [];
        const events = data.events || [];
        const latestEvent = events[0] || null;
        const pendingCount =
            data.pending_broadcast_count ??
            data.pending_broadcast_logs ??
            0;

        if (eventCameraCount) {
            eventCameraCount.textContent = String(cameras.length);
        }

        if (recentEventsCount) {
            recentEventsCount.textContent = String(events.length);
        }

        if (pendingBroadcastLogsCount) {
            pendingBroadcastLogsCount.textContent = String(pendingCount);
        }

        if (pendingBroadcastMetric) {
            pendingBroadcastMetric.classList.toggle("is-clear", Number(pendingCount) === 0);
        }

        if (latestEvent) {
            if (latestEventType) {
                latestEventType.textContent = normalizeText(
                    latestEvent.event_type_display,
                    latestEvent.event_type || "\u672a\u77e5\u4e8b\u4ef6"
                );
            }

            if (latestEventCamera) {
                const cameraCode = normalizeText(latestEvent.camera_code, "");
                const cameraName = normalizeText(latestEvent.camera_name, "");
                latestEventCamera.textContent =
                    cameraCode || cameraName
                        ? `${cameraCode}\uff5c${cameraName}`
                        : "\u672a\u6307\u5b9a\u651d\u5f71\u6a5f";
            }

            if (latestEventTime) {
                latestEventTime.textContent = normalizeText(latestEvent.created_at, "--");
            }
        } else {
            if (latestEventType) {
                latestEventType.textContent = "\u76ee\u524d\u7121\u4e8b\u4ef6";
            }

            if (latestEventCamera) {
                latestEventCamera.textContent = "\u7cfb\u7d71\u6b63\u5728\u7b49\u5f85 AI \u63a8\u8ad6\u4e8b\u4ef6";
            }

            if (latestEventTime) {
                latestEventTime.textContent = "--";
            }
        }
    }

    async function processPendingBroadcastLogs() {
        if (!processPendingBroadcastButton) {
            return;
        }

        processPendingBroadcastButton.disabled = true;
        processPendingBroadcastButton.textContent = "\u8655\u7406\u4e2d...";
        setProcessBroadcastStatus("\u6b63\u5728\u8655\u7406 pending \u5ee3\u64ad\u4efb\u52d9...", "");

        try {
            const response = await fetch(processPendingBroadcastApiUrl, {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-Requested-With": "XMLHttpRequest"
                },
                body: JSON.stringify({
                    limit: 10
                })
            });

            if (!response.ok) {
                setProcessBroadcastStatus(`\u8655\u7406\u5931\u6557\uff1aHTTP ${response.status}`, "error");
                return;
            }

            const data = await response.json();

            if (!data.success) {
                setProcessBroadcastStatus(
                    data.message || "\u8655\u7406\u5931\u6557\uff1aAPI \u56de\u50b3 success=false",
                    "error"
                );
                return;
            }

            setProcessBroadcastStatus(
                `\u8655\u7406\u5b8c\u6210\uff1a${data.processed_count} \u7b46\uff0c\u6210\u529f ${data.success_count} \u7b46\uff0c\u5931\u6557 ${data.failed_count} \u7b46\uff0c\u5269\u9918 pending ${data.pending_count} \u7b46`,
                "success"
            );

            await fetchDashboardLiveState();

        } catch (error) {
            console.error("Failed to process pending broadcast logs:", error);
            setProcessBroadcastStatus("\u8655\u7406\u5931\u6557\uff1a\u8acb\u6aa2\u67e5 API \u6216 console", "error");

        } finally {
            processPendingBroadcastButton.disabled = false;
            processPendingBroadcastButton.textContent = "\u8655\u7406\u5f85\u64ad\u653e\u4efb\u52d9";
        }
    }

    async function fetchDashboardLiveState() {
        try {
            const response = await fetch(liveStateApiUrl, {
                method: "GET",
                headers: {
                    "X-Requested-With": "XMLHttpRequest"
                }
            });

            if (!response.ok) {
                setPollingStatus(`Dashboard polling\uff1aAPI error ${response.status}`, true);
                return;
            }

            const data = await response.json();

            const cameras = data.cameras || [];
            const events = data.events || [];
            const logs = data.broadcast_logs || data.recent_broadcast_logs || [];
            const highlightedCameraId = data.highlighted_camera_id;

            updateSummary(data);
            renderCameraGrid(cameras, highlightedCameraId);
            renderEventList(events);
            renderBroadcastLogs(logs);

            if (events.length > 0) {
                const latestEventId = events[0].id;

                if (lastLatestEventId !== null && String(latestEventId) !== String(lastLatestEventId)) {
                    const targetCameraId = highlightedCameraId || events[0].camera_id;

                    lastSelectedEventId = String(latestEventId);
                    lastSelectedCameraId = targetCameraId ? String(targetCameraId) : null;

                    if (targetCameraId) {
                        focusEventCamera(targetCameraId);
                    }
                }

                lastLatestEventId = latestEventId;
            }

            const serverTime = data.server_time || new Date().toLocaleString();
            setPollingStatus(`Dashboard polling\uff1a\u5df2\u66f4\u65b0 ${serverTime}`, false);

        } catch (error) {
            console.error("Failed to fetch dashboard live state:", error);
            setPollingStatus("Dashboard polling\uff1a\u66f4\u65b0\u5931\u6557\uff0c\u8acb\u6aa2\u67e5 API \u6216 console", true);
        }
    }

    if (processPendingBroadcastButton) {
        processPendingBroadcastButton.addEventListener("click", function () {
            processPendingBroadcastLogs();
        });
    }

    bindEventItemClickHandlers();
    bindConfirmEventHandlers();
    bindStreamHandlers();

    fetchDashboardLiveState();

    setInterval(function () {
        fetchDashboardLiveState();
    }, 5000);
});

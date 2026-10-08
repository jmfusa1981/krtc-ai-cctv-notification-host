document.addEventListener("DOMContentLoaded", function () {
    const monitorGrid = document.getElementById("monitorGrid");
    const monitorMosaic = document.getElementById("monitorMosaic");
    const monitorMosaicStream = document.getElementById("monitorMosaicStream");
    const monitorMosaicOverlay = document.getElementById("monitorMosaicOverlay");
    const monitorMosaicInteractionGrid = document.getElementById(
        "monitorMosaicInteractionGrid"
    );
    const buttons = document.querySelectorAll(".grid-mode-btn");
    const cameraCards = document.querySelectorAll("[data-monitor-camera-card]");
    const cameraStreams = document.querySelectorAll("[data-camera-stream]");
    const webrtcPlayers = document.querySelectorAll("[data-mediamtx-player]");
    const monitorContent = document.getElementById("monitorContent");
    const cameraSidebar = document.getElementById("cameraSidebar");
    const cameraTreeToggle = document.getElementById("cameraTreeToggle");
    const cameraSearchInput = document.getElementById("cameraSearchInput");
    const cameraTreeItems = document.querySelectorAll("[data-camera-tree-item]");
    const previousCameraGroup = document.getElementById("previousCameraGroup");
    const nextCameraGroup = document.getElementById("nextCameraGroup");
    const cameraGroupStatus = document.getElementById("cameraGroupStatus");
    const carouselToggle = document.getElementById("carouselToggle");
    const carouselInterval = document.getElementById("carouselInterval");
    const carouselStatus = document.getElementById("carouselStatus");
    const liveStateUrl = document.body.dataset.liveStateUrl;
    const monitorEventAlert = document.getElementById("monitorEventAlert");
    const monitorEventType = document.getElementById("monitorEventType");
    const monitorEventCamera = document.getElementById("monitorEventCamera");
    const monitorEventTime = document.getElementById("monitorEventTime");
    const dismissMonitorEventAlert = document.getElementById("dismissMonitorEventAlert");
    const monitorDateTime = document.getElementById("monitorDateTime");
    const backDashboardLink = document.querySelector(".back-dashboard-link");
    const monitorMediaMode = monitorGrid
        ? monitorGrid.dataset.mediaMode || "legacy"
        : "legacy";
    const mediaStatusUrl = monitorGrid
        ? monitorGrid.dataset.mediaStatusUrl || ""
        : "";
    const mediaProfileUrl = monitorGrid
        ? monitorGrid.dataset.mediaProfileUrl || ""
        : "";
    const mediaTransitionAckUrl = monitorGrid
        ? monitorGrid.dataset.mediaTransitionAckUrl || ""
        : "";
    const profileLayoutMapElement = document.getElementById(
        "monitorProfileLayoutMap"
    );
    const monitorProfileLayoutMap = profileLayoutMapElement
        ? JSON.parse(profileLayoutMapElement.textContent)
        : {};
    const csrfTokenInput = document.querySelector(
        'input[name="csrfmiddlewaretoken"]'
    );
    const MAX_SLOT_COUNT = 16;
    let monitorSlots = [];
    let selectedSlot = null;
    let currentGridSize = 4;
    let currentGroupIndex = 0;
    let carouselTimer = null;
    let isCarouselRunning = false;
    let lastObservedEventId = null;
    let eventPollingTimer = null;
    let eventHighlightTimer = null;
    let streamActivationGeneration = 0;
    let monitorClockTimer = null;
    let healthCheckTimer = null;
    let monitorMediaRefreshTimer = null;
    let monitorProfileSwitchTimer = null;
    let monitorTransitionPollTimer = null;
    let lastRequestedMonitorProfile = "";
    let pendingRequestedMonitorProfile = "";
    let monitorTransitionRequestDeadline = 0;
    let activeTransitionId = "";
    let acknowledgedTransitionId = "";
    let transitionSwapInFlight = false;
    let transitionWasObserved = false;
    let monitorPageExiting = false;
    let mosaicOrderKey = "";
    let mosaicCameraOrder = [];
    let monitorMediaStatus = null;
    let monitorMediaStatusPromise = null;
    const STREAM_ACTIVATION_STAGGER_MS = 200;
    const STREAM_IDLE_RELEASE_MS = 15000;
    const EVENT_HIGHLIGHT_DURATION_MS = 8000;
    const STREAM_RELEASE_PLACEHOLDER =
        "data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=";
    const streamReleaseTimers = new Map();
    const webrtcReconnectTimers = new Map();
    const webrtcRetryCounts = new Map();
    const healthCheckControllers = new Map();
    const WEBRTC_RECONNECT_BASE_MS = 2000;
    const WEBRTC_RECONNECT_MAX_MS = 15000;
    const WEBRTC_MAX_RETRIES = 3;
    const WEBRTC_STABLE_READER_SAMPLES = 2;
    const WEBRTC_STALE_READER_SAMPLES = 3;
    const WEBRTC_STARTUP_GRACE_MS = 20000;
    const WEBRTC_REBUILD_COOLDOWN_MS = 30000;
    const MEDIA_STATUS_REFRESH_MS = 5000;
    const MONITOR_PROFILE_SWITCH_DEBOUNCE_MS = 1500;
    const MONITOR_PROFILE_TRANSITION_POLL_MS = 500;
    const MONITOR_PROFILE_TRANSITION_WAIT_MS = 12000;

    if (!monitorGrid || buttons.length === 0) {
        return;
    }


    function updateMonitorDateTime() {
        if (!monitorDateTime) {
            return;
        }

        const now = new Date();
        const year = now.getFullYear();
        const month = String(now.getMonth() + 1).padStart(2, "0");
        const day = String(now.getDate()).padStart(2, "0");
        const hours = String(now.getHours()).padStart(2, "0");
        const minutes = String(now.getMinutes()).padStart(2, "0");
        const seconds = String(now.getSeconds()).padStart(2, "0");

        monitorDateTime.textContent =
            `${year}/${month}/${day} ${hours}:${minutes}:${seconds}`;
        monitorDateTime.dateTime = now.toISOString();
    }

    function createEmptySlot(slotIndex) {
        const slotNumber = String(slotIndex + 1).padStart(2, "0");
        const slot = document.createElement("div");

        slot.className = "monitor-slot";
        slot.dataset.monitorSlot = "";
        slot.dataset.slotIndex = String(slotIndex);
        slot.innerHTML = `
            <span class="monitor-slot-label">SLOT ${slotNumber}</span>
            <div class="monitor-slot-empty">
                <div>
                    <strong>\u5c1a\u672a\u914d\u7f6e\u651d\u5f71\u6a5f</strong>
                    <span>Camera slot ${slotNumber}</span>
                </div>
            </div>
        `;

        return slot;
    }

    function prepareMonitorSlots() {
        monitorSlots = Array.from(
            monitorGrid.querySelectorAll("[data-monitor-slot]")
        );

        for (let index = monitorSlots.length; index < MAX_SLOT_COUNT; index += 1) {
            const slot = createEmptySlot(index);
            monitorGrid.appendChild(slot);
            monitorSlots.push(slot);
        }
    }

    function ensureEmptyPlaceholder(slot) {
        let placeholder = slot.querySelector(".monitor-slot-empty");

        if (!placeholder) {
            const slotNumber = String(Number(slot.dataset.slotIndex) + 1).padStart(2, "0");
            placeholder = document.createElement("div");
            placeholder.className = "monitor-slot-empty";
            placeholder.innerHTML = `
                <div>
                    <strong>\u5c1a\u672a\u914d\u7f6e\u651d\u5f71\u6a5f</strong>
                    <span>Camera slot ${slotNumber}</span>
                </div>
            `;
            slot.appendChild(placeholder);
        }

        return placeholder;
    }

    function applySlotPosition(slot) {
        const slotIndex = Number(slot.dataset.slotIndex);
        const slotNumber = String(slotIndex + 1).padStart(2, "0");
        const label = slot.querySelector(".monitor-slot-label");
        const emptySlotCaption = slot.querySelector(".monitor-slot-empty span");

        slot.style.order = String(slotIndex);

        if (label) {
            label.textContent = `SLOT ${slotNumber}`;
        }

        if (emptySlotCaption) {
            emptySlotCaption.textContent = `Camera slot ${slotNumber}`;
        }
    }

    function syncSlotState(slot) {
        const card = slot.querySelector("[data-monitor-camera-card]");
        const placeholder = ensureEmptyPlaceholder(slot);

        slot.classList.toggle("is-occupied", Boolean(card));
        placeholder.hidden = Boolean(card);
    }

    function selectSlot(slot) {
        if (!slot || slot.hidden) {
            return;
        }

        monitorSlots.forEach(function (item) {
            item.classList.remove("is-selected");
        });

        selectedSlot = slot;
        selectedSlot.classList.add("is-selected");
    }

    function updateTreeAssignments() {
        cameraTreeItems.forEach(function (item) {
            const cameraId = item.dataset.cameraId;
            const assignment = item.querySelector("[data-camera-assignment]");
            const card = Array.from(cameraCards).find(function (candidate) {
                return String(candidate.dataset.cameraId) === String(cameraId);
            });
            const slot = card ? card.closest("[data-monitor-slot]") : null;

            item.classList.toggle("is-assigned", Boolean(slot));

            if (assignment) {
                assignment.textContent = slot
                    ? `SLOT ${String(Number(slot.dataset.slotIndex) + 1).padStart(2, "0")}`
                    : "\u5c1a\u672a\u914d\u7f6e";
            }
        });
    }

    function moveCameraToSlot(cameraId, targetSlot) {
        const cameraCard = Array.from(cameraCards).find(function (card) {
            return String(card.dataset.cameraId) === String(cameraId);
        });

        if (!cameraCard || !targetSlot) {
            return null;
        }

        const sourceSlot = cameraCard.closest("[data-monitor-slot]");

        if (!sourceSlot || sourceSlot === targetSlot) {
            updateTreeAssignments();
            return {sourceSlot: sourceSlot, changed: false};
        }

        const sourceIndex = sourceSlot.dataset.slotIndex;
        const targetIndex = targetSlot.dataset.slotIndex;

        sourceSlot.dataset.slotIndex = targetIndex;
        targetSlot.dataset.slotIndex = sourceIndex;

        applySlotPosition(sourceSlot);
        applySlotPosition(targetSlot);

        syncSlotState(sourceSlot);
        syncSlotState(targetSlot);
        updateTreeAssignments();

        return {sourceSlot: sourceSlot, changed: true};
    }

    function moveCameraToSelectedSlot(cameraId) {
        if (isMosaicMode()) {
            return;
        }

        if (!selectedSlot) {
            const firstVisibleSlot = monitorSlots.find(function (slot) {
                return !slot.hidden;
            });
            selectSlot(firstVisibleSlot);
        }

        const result = moveCameraToSlot(cameraId, selectedSlot);
        if (!result || !result.changed) {
            return;
        }

        selectSlot(result.sourceSlot);
        renderCurrentCameraGroup();
    }

    function bindSlotSelection() {
        monitorSlots.forEach(function (slot) {
            slot.addEventListener("click", function () {
                selectSlot(slot);
            });
        });

        const firstVisibleSlot = monitorSlots.find(function (slot) {
            return !slot.hidden;
        });
        selectSlot(firstVisibleSlot);
    }

    function clearDragOverStates() {
        monitorSlots.forEach(function (slot) {
            slot.classList.remove("is-drag-over");
        });
        clearMosaicDragState();
    }

    function bindCameraDragAndDrop() {
        cameraTreeItems.forEach(function (item) {
            item.addEventListener("dragstart", function (event) {
                const cameraId = item.dataset.cameraId;

                if (!cameraId || !event.dataTransfer) {
                    event.preventDefault();
                    return;
                }

                event.dataTransfer.effectAllowed = "move";
                event.dataTransfer.setData("text/plain", cameraId);
                item.classList.add("is-dragging");
            });

            item.addEventListener("dragend", function () {
                item.classList.remove("is-dragging");
                clearDragOverStates();
            });
        });

        monitorSlots.forEach(function (slot) {
            slot.addEventListener("dragenter", function (event) {
                event.preventDefault();
                clearDragOverStates();
                slot.classList.add("is-drag-over");
            });

            slot.addEventListener("dragover", function (event) {
                event.preventDefault();

                if (event.dataTransfer) {
                    event.dataTransfer.dropEffect = "move";
                }

                slot.classList.add("is-drag-over");
            });

            slot.addEventListener("dragleave", function (event) {
                const nextElement = event.relatedTarget;

                if (nextElement instanceof Node && slot.contains(nextElement)) {
                    return;
                }

                slot.classList.remove("is-drag-over");
            });

            slot.addEventListener("drop", function (event) {
                event.preventDefault();

                const cameraId = event.dataTransfer
                    ? event.dataTransfer.getData("text/plain")
                    : "";

                clearDragOverStates();

                if (!cameraId) {
                    return;
                }

                selectSlot(slot);
                moveCameraToSelectedSlot(cameraId);
            });
        });
    }

    function bindCameraTree() {
        cameraTreeItems.forEach(function (item) {
            item.addEventListener("click", function () {
                moveCameraToSelectedSlot(item.dataset.cameraId);
            });
        });

        if (cameraSearchInput) {
            cameraSearchInput.addEventListener("input", function () {
                const keyword = cameraSearchInput.value.trim().toLocaleLowerCase();

                cameraTreeItems.forEach(function (item) {
                    const searchText = (item.dataset.cameraSearch || "").toLocaleLowerCase();
                    item.hidden = Boolean(keyword) && !searchText.includes(keyword);
                });
            });
        }

        if (cameraTreeToggle && monitorContent) {
            cameraTreeToggle.classList.add("active");

            cameraTreeToggle.addEventListener("click", function () {
                const isCollapsed = monitorContent.classList.toggle("sidebar-collapsed");
                cameraTreeToggle.classList.toggle("active", !isCollapsed);
                cameraTreeToggle.setAttribute("aria-expanded", String(!isCollapsed));
            });
        }
    }

    function clearEventHighlights() {
        monitorSlots.forEach(function (slot) {
            slot.classList.remove("has-event-alert");
        });

        cameraCards.forEach(function (card) {
            card.classList.remove("has-event-alert");
        });

        cameraTreeItems.forEach(function (item) {
            item.classList.remove("has-event-alert");
        });

        if (monitorMosaicInteractionGrid) {
            monitorMosaicInteractionGrid
                .querySelectorAll(".has-event-alert")
                .forEach(function (tile) {
                    tile.classList.remove("has-event-alert");
                });
        }

        if (eventHighlightTimer !== null) {
            window.clearTimeout(eventHighlightTimer);
            eventHighlightTimer = null;
        }
    }

    function cameraMatchesEvent(element, cameraId, cameraCode) {
        const elementCameraId = String(element.dataset.cameraId || "");
        const elementCameraCode = String(element.dataset.cameraCode || "").toUpperCase();
        const eventCameraId = String(cameraId || "");
        const eventCameraCode = String(cameraCode || "").toUpperCase();

        return (
            (eventCameraId && elementCameraId === eventCameraId) ||
            (eventCameraCode && elementCameraCode === eventCameraCode)
        );
    }

    function focusMonitorEventCamera(cameraId, cameraCode) {
        clearEventHighlights();

        const cameraCard = Array.from(cameraCards).find(function (card) {
            return cameraMatchesEvent(card, cameraId, cameraCode);
        });
        const cameraTreeItem = Array.from(cameraTreeItems).find(function (item) {
            return cameraMatchesEvent(item, cameraId, cameraCode);
        });

        const assignedSlot = cameraCard
            ? cameraCard.closest("[data-monitor-slot]")
            : null;

        if (assignedSlot) {
            const slotIndex = Number(assignedSlot.dataset.slotIndex);
            currentGroupIndex = Math.floor(slotIndex / currentGridSize);
            renderCurrentCameraGroup();
        }

        if (isMosaicMode() && monitorMosaicInteractionGrid) {
            const mosaicTile = Array.from(
                monitorMosaicInteractionGrid.querySelectorAll(
                    ".monitor-mosaic-tile-overlay"
                )
            ).find(function (tile) {
                return cameraMatchesEvent(tile, cameraId, cameraCode);
            });
            if (mosaicTile) {
                mosaicTile.classList.add("has-event-alert");
            }
        } else if (cameraCard && assignedSlot) {
            selectSlot(assignedSlot);
            assignedSlot.classList.add("has-event-alert");
            cameraCard.classList.add("has-event-alert");
        }

        if (cameraTreeItem) {
            cameraTreeItem.classList.add("has-event-alert");
        }

        if (isMosaicMode()) {
            eventHighlightTimer = window.setTimeout(function () {
                clearEventHighlights();
            }, EVENT_HIGHLIGHT_DURATION_MS);
        }
    }

    function showMonitorEventAlert(event) {
        if (!event || !monitorEventAlert) {
            return;
        }

        const eventType =
            event.event_type_display ||
            event.event_type ||
            "\u672a\u77e5\u4e8b\u4ef6";
        const cameraCode = event.camera_code || "";
        const cameraName = event.camera_name || "";
        const cameraText =
            cameraCode || cameraName
                ? `${cameraCode}\uff5c${cameraName}`
                : "\u672a\u6307\u5b9a\u651d\u5f71\u6a5f";

        if (monitorEventType) {
            monitorEventType.textContent = eventType;
        }

        if (monitorEventCamera) {
            monitorEventCamera.textContent = cameraText;
        }

        if (monitorEventTime) {
            monitorEventTime.textContent = event.created_at || "--";
        }

        monitorEventAlert.hidden = false;

        if (event.camera_id || cameraCode) {
            focusMonitorEventCamera(event.camera_id, cameraCode);
        }
    }

    function hideMonitorEventAlert() {
        if (monitorEventAlert) {
            monitorEventAlert.hidden = true;
        }

        clearEventHighlights();
    }

    async function pollMonitorEvents() {
        if (!liveStateUrl) {
            return;
        }

        try {
            const response = await fetch(liveStateUrl, {
                method: "GET",
                cache: "no-store",
                headers: {
                    "Accept": "application/json",
                    "X-Requested-With": "XMLHttpRequest"
                }
            });

            if (!response.ok) {
                throw new Error(`Monitor event polling HTTP ${response.status}`);
            }

            const data = await response.json();
            const events = Array.isArray(data.events) ? data.events : [];
            const latestEvent = events[0] || null;

            if (!latestEvent || latestEvent.id === undefined || latestEvent.id === null) {
                return;
            }

            if (lastObservedEventId === null) {
                lastObservedEventId = String(latestEvent.id);
                return;
            }

            if (String(latestEvent.id) !== String(lastObservedEventId)) {
                lastObservedEventId = String(latestEvent.id);
                showMonitorEventAlert(latestEvent);
            }
        } catch (error) {
            console.error("Failed to poll monitor events:", error);
        }
    }

    function bindMonitorEventNotifications() {
        if (dismissMonitorEventAlert) {
            dismissMonitorEventAlert.addEventListener("click", function () {
                hideMonitorEventAlert();
            });
        }

        pollMonitorEvents();

        eventPollingTimer = window.setInterval(function () {
            pollMonitorEvents();
        }, 5000);

        window.addEventListener("beforeunload", function () {
            if (eventPollingTimer !== null) {
                window.clearInterval(eventPollingTimer);
            }

            if (eventHighlightTimer !== null) {
                window.clearTimeout(eventHighlightTimer);
            }
        });
    }

    function getCarouselIntervalMilliseconds() {
        const seconds = carouselInterval
            ? parseInt(carouselInterval.value, 10)
            : 10;

        return Math.max(1, seconds) * 1000;
    }

    function updateCarouselUi() {
        const totalGroups = getTotalCameraGroups();
        const canRun = totalGroups > 1;

        if (carouselToggle) {
            carouselToggle.disabled = !canRun;
            carouselToggle.classList.toggle("is-running", isCarouselRunning);
            carouselToggle.textContent = isCarouselRunning
                ? "停止"
                : "輪播";
        }

        if (carouselInterval) {
            carouselInterval.disabled = !canRun;
        }

        if (carouselStatus) {
            carouselStatus.textContent = isCarouselRunning
                ? `${Math.round(getCarouselIntervalMilliseconds() / 1000)} 秒`
                : (canRun ? "待命" : "單組");
        }
    }

    function clearCarouselTimer() {
        if (carouselTimer !== null) {
            window.clearInterval(carouselTimer);
            carouselTimer = null;
        }
    }

    function stopCarousel() {
        clearCarouselTimer();
        isCarouselRunning = false;
        updateCarouselUi();
    }

    function scheduleCarousel() {
        clearCarouselTimer();

        if (!isCarouselRunning || getTotalCameraGroups() <= 1) {
            return;
        }

        carouselTimer = window.setInterval(function () {
            const totalGroups = getTotalCameraGroups();

            if (totalGroups <= 1) {
                stopCarousel();
                return;
            }

            currentGroupIndex = (currentGroupIndex + 1) % totalGroups;
            renderCurrentCameraGroup();
        }, getCarouselIntervalMilliseconds());
    }

    function startCarousel() {
        if (getTotalCameraGroups() <= 1) {
            stopCarousel();
            return;
        }

        isCarouselRunning = true;
        updateCarouselUi();
        scheduleCarousel();
    }

    function bindCarouselControls() {
        if (carouselToggle) {
            carouselToggle.addEventListener("click", function () {
                if (isCarouselRunning) {
                    stopCarousel();
                } else {
                    startCarousel();
                }
            });
        }

        if (carouselInterval) {
            carouselInterval.addEventListener("change", function () {
                updateCarouselUi();

                if (isCarouselRunning) {
                    scheduleCarousel();
                }
            });
        }

        window.addEventListener("beforeunload", function () {
            clearCarouselTimer();
        });
    }

    function getOccupiedSlotExtent() {
        let highestOccupiedIndex = -1;

        monitorSlots.forEach(function (slot) {
            if (slot.querySelector("[data-monitor-camera-card]")) {
                highestOccupiedIndex = Math.max(
                    highestOccupiedIndex,
                    Number(slot.dataset.slotIndex)
                );
            }
        });

        return Math.max(cameraCards.length, highestOccupiedIndex + 1, 1);
    }

    function getTotalCameraGroups() {
        return Math.max(
            1,
            Math.ceil(getOccupiedSlotExtent() / currentGridSize)
        );
    }

    function updateCameraGroupControls() {
        const totalGroups = getTotalCameraGroups();

        if (currentGroupIndex >= totalGroups) {
            currentGroupIndex = totalGroups - 1;
        }

        if (cameraGroupStatus) {
            cameraGroupStatus.textContent = `${currentGroupIndex + 1} / ${totalGroups}`;
        }

        if (previousCameraGroup) {
            previousCameraGroup.disabled = currentGroupIndex <= 0;
        }

        if (nextCameraGroup) {
            nextCameraGroup.disabled = currentGroupIndex >= totalGroups - 1;
        }

        if (totalGroups <= 1 && isCarouselRunning) {
            stopCarousel();
        } else {
            updateCarouselUi();
        }
    }

    function getMonitorStreamProfile() {
        if (currentGridSize === 1) {
            return "single";
        }
        if (currentGridSize === 4) {
            return "grid4";
        }
        if (currentGridSize === 9) {
            return "grid9";
        }
        return "grid16";
    }

    function isMosaicMode() {
        return monitorMediaMode !== "mediamtx"
            && (currentGridSize === 9 || currentGridSize === 16);
    }

    function getMosaicOrderKey() {
        return `grid${currentGridSize}:group${currentGroupIndex}`;
    }

    function buildDefaultMosaicCameraOrder() {
        const groupStart = currentGroupIndex * currentGridSize;
        const cameraIds = [];

        for (let offset = 0; offset < currentGridSize; offset += 1) {
            const slotIndex = groupStart + offset;
            const slot = monitorSlots.find(function (candidate) {
                return Number(candidate.dataset.slotIndex) === slotIndex;
            });
            const card = slot ? slot.querySelector("[data-monitor-camera-card]") : null;
            if (card && card.dataset.cameraId) {
                cameraIds.push(String(card.dataset.cameraId));
            }
        }
        return cameraIds;
    }

    function ensureMosaicCameraOrder() {
        const nextKey = getMosaicOrderKey();
        if (mosaicOrderKey !== nextKey) {
            mosaicOrderKey = nextKey;
            mosaicCameraOrder = buildDefaultMosaicCameraOrder();
        }
        return mosaicCameraOrder;
    }

    function getMosaicCameraDetails(cameraId) {
        const cameraCard = Array.from(cameraCards).find(function (card) {
            return String(card.dataset.cameraId) === String(cameraId);
        });
        const name = cameraCard
            ? cameraCard.querySelector(".monitor-camera-name h3")
            : null;
        const description = cameraCard
            ? cameraCard.querySelector(".monitor-camera-name p")
            : null;
        const badge = cameraCard
            ? cameraCard.querySelector("[data-status-badge]")
            : null;
        const statusClass = badge
            ? Array.from(badge.classList).find(function (className) {
                return className.startsWith("status-");
            })
            : null;

        return {
            cameraCode: cameraCard
                ? String(cameraCard.dataset.cameraCode || "")
                : "",
            name: name ? name.textContent.trim() : `Camera ${cameraId}`,
            description: description
                ? description.textContent.trim()
                : "未設定區域",
            statusClass: statusClass || "status-unknown",
            statusLabel: badge ? badge.textContent.trim() : "Unknown"
        };
    }

    function moveSidebarCameraToMosaicSlot(cameraId, mosaicSlotIndex) {
        const absoluteSlotIndex = (
            currentGroupIndex * currentGridSize + mosaicSlotIndex
        );
        const targetSlot = monitorSlots.find(function (slot) {
            return Number(slot.dataset.slotIndex) === absoluteSlotIndex;
        });
        const result = moveCameraToSlot(cameraId, targetSlot);

        if (!result || !result.changed) {
            return false;
        }

        mosaicCameraOrder = buildDefaultMosaicCameraOrder();
        return true;
    }

    function clearMosaicDragState() {
        if (!monitorMosaicInteractionGrid) {
            return;
        }
        monitorMosaicInteractionGrid
            .querySelectorAll(".is-dragging, .is-drag-over")
            .forEach(function (tile) {
                tile.classList.remove("is-dragging", "is-drag-over");
            });
    }

    function renderMosaicInteractionGrid() {
        if (!monitorMosaicInteractionGrid || !isMosaicMode()) {
            return;
        }

        const cameraIds = ensureMosaicCameraOrder();
        monitorMosaicInteractionGrid.replaceChildren();
        monitorMosaicInteractionGrid.classList.remove("grid-9", "grid-16");
        monitorMosaicInteractionGrid.classList.add(`grid-${currentGridSize}`);

        for (let slotIndex = 0; slotIndex < currentGridSize; slotIndex += 1) {
            const cameraId = cameraIds[slotIndex] || "";
            const cameraDetails = cameraId
                ? getMosaicCameraDetails(cameraId)
                : null;
            const tile = document.createElement("div");
            tile.className = "monitor-mosaic-tile-overlay";
            tile.dataset.slot = String(slotIndex);
            tile.dataset.cameraId = cameraId;
            tile.dataset.cameraCode = cameraDetails
                ? cameraDetails.cameraCode
                : "";
            tile.setAttribute(
                "aria-label",
                cameraId
                    ? `Mosaic slot ${slotIndex + 1}: ${cameraDetails.name}`
                    : `Mosaic slot ${slotIndex + 1}`
            );
            const slotLabel = document.createElement("span");
            slotLabel.className = "monitor-slot-label monitor-mosaic-slot-label";
            slotLabel.textContent = (
                `SLOT ${String(slotIndex + 1).padStart(2, "0")}`
            );
            tile.appendChild(slotLabel);

            const cameraInfo = document.createElement("div");
            cameraInfo.className = "monitor-camera-info monitor-mosaic-camera-info";
            const cameraName = document.createElement("div");
            cameraName.className = "monitor-camera-name";
            const cameraHeading = document.createElement("h3");
            const cameraDescription = document.createElement("p");
            cameraHeading.textContent = cameraDetails
                ? cameraDetails.name
                : "尚未配置攝影機";
            cameraDescription.textContent = cameraDetails
                ? cameraDetails.description
                : `Camera slot ${slotIndex + 1}`;
            cameraName.append(cameraHeading, cameraDescription);
            cameraInfo.appendChild(cameraName);

            if (cameraDetails) {
                const statusBadge = document.createElement("span");
                statusBadge.className = (
                    `camera-status ${cameraDetails.statusClass}`
                );
                statusBadge.textContent = cameraDetails.statusLabel;
                cameraInfo.appendChild(statusBadge);
            }
            tile.appendChild(cameraInfo);

            tile.addEventListener("dragenter", function (event) {
                event.preventDefault();
                clearMosaicDragState();
                tile.classList.add("is-drag-over");
            });
            tile.addEventListener("dragover", function (event) {
                event.preventDefault();
                if (event.dataTransfer) {
                    event.dataTransfer.dropEffect = "move";
                }
                tile.classList.add("is-drag-over");
            });
            tile.addEventListener("dragleave", function (event) {
                const nextElement = event.relatedTarget;
                if (nextElement instanceof Node && tile.contains(nextElement)) {
                    return;
                }
                tile.classList.remove("is-drag-over");
            });
            tile.addEventListener("drop", function (event) {
                event.preventDefault();
                const draggedCameraId = event.dataTransfer
                    ? event.dataTransfer.getData("text/plain")
                    : "";
                const targetIndex = Number(tile.dataset.slot);
                clearMosaicDragState();

                if (
                    !draggedCameraId
                    || targetIndex < 0
                    || targetIndex >= currentGridSize
                ) {
                    return;
                }

                if (moveSidebarCameraToMosaicSlot(draggedCameraId, targetIndex)) {
                    renderMosaicInteractionGrid();
                    activateMosaicStream();
                }
            });
            monitorMosaicInteractionGrid.appendChild(tile);
        }
    }

    function buildMosaicStreamUrl() {
        if (!monitorMosaic) {
            return "";
        }

        const baseUrl = monitorMosaic.dataset.mosaicBaseUrl;
        if (!baseUrl) {
            return "";
        }

        const parameters = new URLSearchParams({
            layout: `grid${currentGridSize}`,
            group: String(currentGroupIndex),
            ts: String(Date.now())
        });
        const cameraIds = ensureMosaicCameraOrder();
        if (cameraIds.length === currentGridSize) {
            parameters.set("camera_ids", cameraIds.join(","));
        }
        return `${baseUrl}?${parameters.toString()}`;
    }

    function setMosaicOverlay(title, message, hidden) {
        if (!monitorMosaicOverlay) {
            return;
        }

        monitorMosaicOverlay.innerHTML = `<strong>${title}</strong><span>${message}</span>`;
        monitorMosaicOverlay.hidden = Boolean(hidden);
    }

    function releaseMosaicStream() {
        if (!monitorMosaicStream) {
            return;
        }

        monitorMosaicStream.src = STREAM_RELEASE_PLACEHOLDER;
        monitorMosaicStream.removeAttribute("src");
        monitorMosaicStream.dataset.layout = "";
        monitorMosaicStream.dataset.group = "";
        monitorMosaicStream.dataset.order = "";
    }

    function activateMosaicStream() {
        if (!monitorMosaic || !monitorMosaicStream || !isMosaicMode()) {
            return;
        }

        const layout = `grid${currentGridSize}`;
        const group = String(currentGroupIndex);
        const order = ensureMosaicCameraOrder().join(",");
        const sameLayout = Boolean(
            monitorMosaicStream.getAttribute("src")
            && monitorMosaicStream.dataset.layout === layout
            && monitorMosaicStream.dataset.group === group
            && monitorMosaicStream.dataset.order === order
        );
        if (sameLayout) {
            return;
        }

        releaseMosaicStream();
        monitorMosaicStream.dataset.layout = layout;
        monitorMosaicStream.dataset.group = group;
        monitorMosaicStream.dataset.order = order;
        monitorMosaic.classList.remove("is-loaded", "is-error");
        monitorMosaic.classList.add("is-loading");
        setMosaicOverlay(
            "MOSAIC CONNECTING",
            "正在建立多攝影機合成串流",
            false
        );
        monitorMosaicStream.src = buildMosaicStreamUrl();
    }

    function updateMosaicInteractionState() {
        cameraTreeItems.forEach(function (item) {
            item.draggable = true;
            item.disabled = false;
            item.title = isMosaicMode()
                ? "拖曳攝影機至 Mosaic 目標格位"
                : "";
        });
    }

    function buildMonitorStreamUrl(stream, profile) {
        const baseUrl = stream.dataset.streamUrl;

        if (!baseUrl) {
            return "";
        }

        const separator = baseUrl.includes("?") ? "&" : "?";
        return `${baseUrl}${separator}profile=${encodeURIComponent(profile)}&ts=${Date.now()}`;
    }

    function getStreamReleaseKey(card) {
        return card ? String(card.dataset.cameraId || card.dataset.cameraCode || "") : "";
    }

    function cancelScheduledStreamRelease(card) {
        const key = getStreamReleaseKey(card);
        if (!key || !streamReleaseTimers.has(key)) {
            return;
        }

        window.clearTimeout(streamReleaseTimers.get(key));
        streamReleaseTimers.delete(key);
    }

    function hasExistingStream(stream) {
        return window.KRTCMediaPlayer.hasMjpegSource(stream);
    }

    function hasExistingWebRTCPlayer(player) {
        return window.KRTCMediaPlayer.hasWebRTCSource(player);
    }

    function getCurrentWebRTCPlayer(card) {
        return card
            ? card.querySelector('[data-mediamtx-player][data-player-role="current"]')
            : null;
    }

    function getNextWebRTCPlayer(card) {
        return card
            ? card.querySelector('[data-mediamtx-player][data-player-role="next"]')
            : null;
    }

    function clearWebRTCReconnect(player) {
        if (!player || !webrtcReconnectTimers.has(player)) {
            return;
        }
        window.clearTimeout(webrtcReconnectTimers.get(player));
        webrtcReconnectTimers.delete(player);
    }

    function beginWebRTCStartup(player, detail) {
        const now = Date.now();
        const generation = Number(player.dataset.playerGeneration || 0) + 1;

        player.dataset.playerGeneration = String(generation);
        player.dataset.startupAt = String(now);
        player.dataset.playerLifecycleState = "warming";
        player.dataset.iframeLoaded = "false";
        player.dataset.readerEverEstablished = "false";
        player.dataset.readerStableSamples = "0";
        player.dataset.readerStaleSamples = "0";
        player.dataset.lastOutboundBytes = String(
            Number((detail || {}).outbound_bytes || 0)
        );
        return generation;
    }

    function isWithinWebRTCStartupGrace(player, now) {
        const startupAt = Number(player.dataset.startupAt || 0);
        return startupAt <= 0 || now - startupAt < WEBRTC_STARTUP_GRACE_MS;
    }

    function isWithinWebRTCRebuildCooldown(player, now) {
        const lastRebuildAt = Number(player.dataset.lastRebuildAt || 0);
        return lastRebuildAt > 0 && now - lastRebuildAt < WEBRTC_REBUILD_COOLDOWN_MS;
    }

    function activateWebRTCPlayer(card, player) {
        if (!player) {
            return;
        }
        const playerUrl = player.dataset.playerUrl;
        if (!playerUrl) {
            return;
        }
        clearWebRTCReconnect(player);
        player.dataset.playerActive = "true";
        player.hidden = player.dataset.fallbackActive === "true";
        player.setAttribute(
            "aria-hidden",
            player.dataset.fallbackActive === "true" ? "true" : "false"
        );

        if (hasExistingWebRTCPlayer(player)) {
            if (card.classList.contains("stream-loaded")) {
                hideOverlay(card);
            }
            return;
        }

        setCardState(card, "loading");
        setOverlay(
            card,
            "",
            card.dataset.cameraCode || "CAMERA",
            "Loading stream...",
            "正在連接MediaMTX WebRTC串流"
        );
        const detail = getCameraMediaDetail(card);
        beginWebRTCStartup(player, detail);
        window.KRTCMediaPlayer.activateWebRTC(player, playerUrl);
    }

    function releaseWebRTCPlayer(player) {
        if (!player) {
            return;
        }
        clearWebRTCReconnect(player);
        player.dataset.playerActive = "false";
        player.dataset.playerLifecycleState = "released";
        window.KRTCMediaPlayer.releaseWebRTC(player);
    }

    function releaseFallbackStream(card) {
        const fallback = card
            ? card.querySelector("[data-media-fallback]")
            : null;
        if (!fallback) {
            return;
        }
        fallback.dataset.streamActive = "false";
        fallback.dataset.streamProfile = "";
        window.KRTCMediaPlayer.releaseMjpeg(fallback);
        fallback.hidden = true;
    }

    function activateCameraFallback(card, player) {
        const fallback = card.querySelector("[data-media-fallback]");
        if (!fallback || !fallback.dataset.streamUrl) {
            setCardState(card, "error");
            setStatusBadge(card, "UNAVAILABLE", "error");
            setOverlay(
                card,
                "error",
                card.dataset.cameraCode || "CAMERA",
                "Media stream unavailable",
                "WebRTC端點無法連線且未啟用MJPEG fallback"
            );
            return;
        }

        if (
            player.dataset.fallbackActive === "true" &&
            hasExistingStream(fallback)
        ) {
            fallback.dataset.streamActive = "true";
            fallback.hidden = false;
            if (card.classList.contains("stream-loaded")) {
                hideOverlay(card);
            }
            return;
        }

        releaseWebRTCPlayer(player);
        player.hidden = true;
        player.dataset.fallbackActive = "true";
        fallback.hidden = false;
        fallback.dataset.streamActive = "true";
        fallback.dataset.streamProfile = getMonitorStreamProfile();
        setCardState(card, "loading");
        setOverlay(
            card,
            "warning",
            card.dataset.cameraCode || "CAMERA",
            "Loading fallback stream...",
            "WebRTC暫時無法連線，改用MJPEG fallback"
        );
        window.KRTCMediaPlayer.activateMjpeg(
            fallback,
            buildMonitorStreamUrl(fallback, fallback.dataset.streamProfile)
        );
    }

    function scheduleWebRTCReconnect(player, expectedGeneration) {
        if (!player || webrtcReconnectTimers.has(player)) {
            return;
        }
        const reconnectGeneration = expectedGeneration === undefined
            ? Number(player.dataset.playerGeneration || 0)
            : expectedGeneration;
        const retryCount = (webrtcRetryCounts.get(player) || 0) + 1;
        webrtcRetryCounts.set(player, retryCount);
        const card = player.closest("[data-monitor-camera-card]");
        if (retryCount > WEBRTC_MAX_RETRIES) {
            if (card) {
                activateCameraFallback(card, player);
            }
            return;
        }
        const reconnectDelay = Math.min(
            WEBRTC_RECONNECT_BASE_MS * (2 ** (retryCount - 1)),
            WEBRTC_RECONNECT_MAX_MS
        );
        const timer = window.setTimeout(function () {
            webrtcReconnectTimers.delete(player);
            const slot = card ? card.closest("[data-monitor-slot]") : null;
            if (
                !card ||
                !slot ||
                slot.hidden ||
                monitorPageExiting ||
                Number(player.dataset.playerGeneration || 0) !== reconnectGeneration
            ) {
                return;
            }
            releaseWebRTCPlayer(player);
            activateWebRTCPlayer(card, player);
        }, reconnectDelay);
        webrtcReconnectTimers.set(player, timer);
    }

    function activateCameraStream(card, profile) {
        if (!card) {
            return;
        }

        cancelScheduledStreamRelease(card);

        const player = getCurrentWebRTCPlayer(card);
        if (player) {
            if (player.dataset.fallbackActive === "true") {
                const fallback = card.querySelector("[data-media-fallback]");
                if (hasExistingStream(fallback)) {
                    fallback.dataset.streamActive = "true";
                    return;
                }
                player.dataset.fallbackActive = "false";
            }
            activateWebRTCPlayer(card, player);
            return;
        }

        const stream = card.querySelector("[data-camera-stream]");
        if (!stream) {
            return;
        }

        // The actual <img src> is the source of truth. If it already exists,
        // preserve the current MJPEG/RTSP request regardless of a stale
        // data-stream-active flag or a grid profile change.
        if (hasExistingStream(stream)) {
            stream.dataset.streamActive = "true";

            if (card.classList.contains("stream-loaded")) {
                hideOverlay(card);
            }
            return;
        }

        const requestedProfile = profile || getMonitorStreamProfile();
        stream.dataset.streamActive = "true";
        stream.dataset.streamProfile = requestedProfile;
        setCardState(card, "loading");
        setOverlay(
            card,
            "",
            card.dataset.cameraCode || "CAMERA",
            "Loading stream...",
            "正在連接攝影機串流"
        );
        stream.src = buildMonitorStreamUrl(stream, requestedProfile);
    }

    function releaseCameraStream(card) {
        if (!card) {
            return;
        }

        cancelScheduledStreamRelease(card);

        const player = getCurrentWebRTCPlayer(card);
        if (player) {
            card.querySelectorAll("[data-mediamtx-player]").forEach(function (item) {
                releaseWebRTCPlayer(item);
                item.hidden = true;
            });
            releaseFallbackStream(card);
            player.dataset.fallbackActive = "false";
            return;
        }

        const stream = card.querySelector("[data-camera-stream]");
        if (!stream || !hasExistingStream(stream)) {
            return;
        }

        stream.dataset.streamActive = "false";
        stream.dataset.streamProfile = "";
        stream.src = STREAM_RELEASE_PLACEHOLDER;
        stream.removeAttribute("src");
    }

    function abortHealthChecks() {
        healthCheckControllers.forEach(function (controller) {
            controller.abort();
        });
        healthCheckControllers.clear();
    }

    function releaseAllCameraStreams() {
        streamActivationGeneration += 1;
        streamReleaseTimers.forEach(function (timer) {
            window.clearTimeout(timer);
        });
        streamReleaseTimers.clear();
        webrtcReconnectTimers.forEach(function (timer) {
            window.clearTimeout(timer);
        });
        webrtcReconnectTimers.clear();
        webrtcRetryCounts.clear();
        cameraCards.forEach(releaseCameraStream);
    }

    function cleanupMonitorPage() {
        if (monitorPageExiting) {
            return;
        }

        monitorPageExiting = true;
        clearCarouselTimer();
        abortHealthChecks();
        releaseAllCameraStreams();
        releaseMosaicStream();
        clearMosaicDragState();
        mosaicOrderKey = "";
        mosaicCameraOrder = [];

        if (eventPollingTimer !== null) {
            window.clearInterval(eventPollingTimer);
            eventPollingTimer = null;
        }
        if (eventHighlightTimer !== null) {
            window.clearTimeout(eventHighlightTimer);
            eventHighlightTimer = null;
        }
        if (monitorClockTimer !== null) {
            window.clearInterval(monitorClockTimer);
            monitorClockTimer = null;
        }
        if (healthCheckTimer !== null) {
            window.clearInterval(healthCheckTimer);
            healthCheckTimer = null;
        }
        if (monitorMediaRefreshTimer !== null) {
            window.clearInterval(monitorMediaRefreshTimer);
            monitorMediaRefreshTimer = null;
        }
        if (monitorProfileSwitchTimer !== null) {
            window.clearTimeout(monitorProfileSwitchTimer);
            monitorProfileSwitchTimer = null;
        }
        if (monitorTransitionPollTimer !== null) {
            window.clearTimeout(monitorTransitionPollTimer);
            monitorTransitionPollTimer = null;
        }
    }

    function bindDashboardNavigation() {
        if (!backDashboardLink) {
            return;
        }

        backDashboardLink.addEventListener("click", function (event) {
            if (
                event.button !== 0 ||
                event.metaKey ||
                event.ctrlKey ||
                event.shiftKey ||
                event.altKey
            ) {
                return;
            }

            event.preventDefault();
            const targetUrl = backDashboardLink.href;
            cleanupMonitorPage();

            // Give the browser one task to cancel the long-lived MJPEG requests.
            window.setTimeout(function () {
                window.location.assign(targetUrl);
            }, 0);
        });
    }

    function scheduleCameraStreamRelease(card) {
        if (!card) {
            return;
        }

        const stream = card.querySelector("[data-camera-stream]");
        const player = getCurrentWebRTCPlayer(card);
        const key = getStreamReleaseKey(card);

        if (
            !key ||
            (!hasExistingStream(stream) && !hasExistingWebRTCPlayer(player)) ||
            streamReleaseTimers.has(key)
        ) {
            return;
        }

        const timer = window.setTimeout(function () {
            streamReleaseTimers.delete(key);

            const slot = card.closest("[data-monitor-slot]");
            if (slot && slot.hidden) {
                releaseCameraStream(card);
            }
        }, STREAM_IDLE_RELEASE_MS);

        streamReleaseTimers.set(key, timer);
    }

    function loadMonitorMediaStatus(forceRefresh) {
        if (forceRefresh === true && !monitorMediaStatusPromise) {
            monitorMediaStatus = null;
        }
        if (monitorMediaStatus) {
            return Promise.resolve(monitorMediaStatus);
        }
        if (monitorMediaStatusPromise) {
            return monitorMediaStatusPromise;
        }
        if (!mediaStatusUrl) {
            monitorMediaStatus = {reachable: false, paths: {}};
            return Promise.resolve(monitorMediaStatus);
        }

        monitorMediaStatusPromise = fetch(mediaStatusUrl, {
            method: "GET",
            credentials: "same-origin",
            cache: "no-store",
            headers: {
                "Accept": "application/json",
                "X-Requested-With": "XMLHttpRequest"
            }
        })
            .then(function (response) {
                return response.json();
            })
            .then(function (payload) {
                monitorMediaStatus = {
                    reachable: payload.reachable === true,
                    paths: payload.paths && typeof payload.paths === "object"
                        ? payload.paths
                        : {},
                    pathDetails: payload.path_details &&
                        typeof payload.path_details === "object"
                        ? payload.path_details
                        : {},
                    transition: payload.transition && typeof payload.transition === "object"
                        ? payload.transition
                        : null
                };
                return monitorMediaStatus;
            })
            .catch(function () {
                monitorMediaStatus = {
                    reachable: false,
                    paths: {},
                    pathDetails: {},
                    transition: null
                };
                return monitorMediaStatus;
            })
            .finally(function () {
                monitorMediaStatusPromise = null;
            });

        return monitorMediaStatusPromise;
    }

    function refreshMonitorMediaStatus() {
        if (monitorPageExiting || monitorMediaMode !== "mediamtx") {
            return;
        }
        loadMonitorMediaStatus(true).then(function () {
            if (!monitorPageExiting) {
                syncMonitorProfileTransition();
                syncVisibleWebRTCPlayers();
            }
        });
    }

    function isCameraMediaReady(card) {
        if (!monitorMediaStatus || monitorMediaStatus.reachable !== true) {
            return false;
        }
        const cameraCode = String(card.dataset.cameraCode || "").toUpperCase();
        const detail = monitorMediaStatus.pathDetails
            ? monitorMediaStatus.pathDetails[cameraCode] || {}
            : {};
        if (Object.prototype.hasOwnProperty.call(detail, "playback_allowed")) {
            return detail.playback_allowed === true;
        }
        return monitorMediaStatus.paths[cameraCode] === true;
    }

    function getCameraMediaDetail(card) {
        const cameraCode = String(
            card ? card.dataset.cameraCode || "" : ""
        ).toUpperCase();
        return monitorMediaStatus && monitorMediaStatus.pathDetails
            ? monitorMediaStatus.pathDetails[cameraCode] || {}
            : {};
    }

    function verifyVisibleWebRTCPlayer(card, player) {
        const detail = getCameraMediaDetail(card);
        const now = Date.now();
        const iframeLoaded = player.dataset.iframeLoaded === "true";
        const readerEstablished = Number(detail.webrtc_reader_count || 0) > 0;
        if (readerEstablished) {
            player.dataset.readerEverEstablished = "true";
        }
        const stableSamples = iframeLoaded && readerEstablished
            ? Number(player.dataset.readerStableSamples || 0) + 1
            : 0;
        player.dataset.readerStableSamples = String(stableSamples);

        const outboundBytes = Number(detail.outbound_bytes || 0);
        const previousOutboundBytes = Number(
            player.dataset.lastOutboundBytes || 0
        );
        const stalled = (
            card.classList.contains("stream-loaded") &&
            readerEstablished &&
            outboundBytes > 0 &&
            outboundBytes <= previousOutboundBytes
        );
        player.dataset.lastOutboundBytes = String(outboundBytes);

        if (stableSamples >= WEBRTC_STABLE_READER_SAMPLES && !stalled) {
            player.dataset.readerStaleSamples = "0";
            player.dataset.playerLifecycleState = "online";
            clearWebRTCReconnect(player);
            webrtcRetryCounts.delete(player);
            releaseFallbackStream(card);
            player.dataset.fallbackActive = "false";
            player.hidden = false;
            player.setAttribute("aria-hidden", "false");
            setCardState(card, "loaded");
            setStatusBadge(card, "ONLINE", "online");
            hideOverlay(card);
            return;
        }

        // iframe 導航後先保留完整啟動寬限；此期間 reader、session 或流量為零都不是 stale。
        if (isWithinWebRTCStartupGrace(player, now)) {
            player.dataset.readerStaleSamples = "0";
            player.dataset.playerLifecycleState = "warming";
            return;
        }

        const staleSamples = (!readerEstablished || stalled)
            ? Number(player.dataset.readerStaleSamples || 0) + 1
            : 0;
        player.dataset.readerStaleSamples = String(staleSamples);
        if (staleSamples >= WEBRTC_STALE_READER_SAMPLES) {
            if (isWithinWebRTCRebuildCooldown(player, now)) {
                player.dataset.playerLifecycleState = "cooldown";
                return;
            }
            const generation = Number(player.dataset.playerGeneration || 0);
            player.dataset.lastRebuildAt = String(now);
            setCardState(card, "warning");
            setStatusBadge(card, "CONNECTING", "warning");
            setOverlay(
                card,
                "warning",
                card.dataset.cameraCode || "CAMERA",
                "WebRTC reconnecting...",
                "偵測到 stale reader/player，正在重建單一 Camera 播放工作階段"
            );
            releaseWebRTCPlayer(player);
            player.dataset.playerLifecycleState = "recovering";
            scheduleWebRTCReconnect(player, generation);
        }
    }

    function scheduleMonitorTransitionPoll() {
        if (monitorPageExiting || monitorTransitionPollTimer !== null) {
            return;
        }
        monitorTransitionPollTimer = window.setTimeout(function () {
            monitorTransitionPollTimer = null;
            refreshMonitorMediaStatus();
        }, MONITOR_PROFILE_TRANSITION_POLL_MS);
    }

    function resetNextWebRTCPlayers() {
        cameraCards.forEach(function (card) {
            const player = getNextWebRTCPlayer(card);
            if (!player) {
                return;
            }
            releaseWebRTCPlayer(player);
            player.dataset.playerUrl = "";
            player.dataset.transitionId = "";
            player.dataset.transitionLoaded = "false";
            player.hidden = true;
            player.setAttribute("aria-hidden", "true");
        });
        activeTransitionId = "";
        transitionSwapInFlight = false;
    }

    function getTransitionPairs(transition) {
        const pairs = [];
        const cameras = transition && transition.cameras
            ? transition.cameras
            : {};
        Object.keys(cameras).forEach(function (cameraCode) {
            const camera = cameras[cameraCode];
            if (!camera.next_path) {
                return;
            }
            const card = Array.from(cameraCards).find(function (item) {
                return String(item.dataset.cameraCode || "").toUpperCase() === cameraCode;
            });
            const currentPlayer = getCurrentWebRTCPlayer(card);
            const nextPlayer = getNextWebRTCPlayer(card);
            if (card && currentPlayer && nextPlayer) {
                const fallback = card.querySelector("[data-media-fallback]");
                pairs.push({
                    card,
                    cameraCode,
                    camera,
                    currentPlayer,
                    nextPlayer,
                    fallback,
                    fallbackWasActive: (
                        currentPlayer.dataset.fallbackActive === "true" &&
                        hasExistingStream(fallback)
                    )
                });
            }
        });
        return pairs;
    }

    function acknowledgePreparedTransition(transition, pairs) {
        if (
            transitionSwapInFlight ||
            acknowledgedTransitionId === transition.transition_id ||
            pairs.length !== Number(transition.profile_transition_camera_count || 0) ||
            pairs.some(function (item) {
                return (
                    item.nextPlayer.dataset.transitionLoaded !== "true" ||
                    item.camera.next_ready !== true ||
                    Number(item.camera.next_reader_count || 0) < 1
                );
            })
        ) {
            return;
        }

        transitionSwapInFlight = true;
        pairs.forEach(function (item) {
            item.currentPlayer.dataset.playerRole = "next";
            item.currentPlayer.hidden = true;
            item.currentPlayer.setAttribute("aria-hidden", "true");
            item.nextPlayer.dataset.playerRole = "current";
            item.nextPlayer.dataset.fallbackActive = "false";
            item.nextPlayer.hidden = false;
            item.nextPlayer.setAttribute("aria-hidden", "false");
            if (item.fallback) {
                item.fallback.hidden = true;
            }
            setCardState(item.card, "loaded");
            setStatusBadge(item.card, "ONLINE", "online");
            hideOverlay(item.card);
        });

        const body = new URLSearchParams({
            transition_id: transition.transition_id,
            camera_codes: pairs.map(function (item) {
                return item.cameraCode;
            }).join(",")
        });
        fetch(mediaTransitionAckUrl, {
            method: "POST",
            credentials: "same-origin",
            headers: {
                "Content-Type": "application/x-www-form-urlencoded",
                "X-CSRFToken": csrfTokenInput.value,
                "X-Requested-With": "XMLHttpRequest"
            },
            body: body.toString()
        })
            .then(function (response) {
                if (!response.ok) {
                    throw new Error(`Monitor transition ACK HTTP ${response.status}`);
                }
                acknowledgedTransitionId = transition.transition_id;
                pairs.forEach(function (item) {
                    releaseFallbackStream(item.card);
                    releaseWebRTCPlayer(item.currentPlayer);
                    item.currentPlayer.dataset.playerUrl = "";
                    item.currentPlayer.dataset.transitionId = "";
                    item.currentPlayer.dataset.transitionLoaded = "false";
                });
            })
            .catch(function (error) {
                pairs.forEach(function (item) {
                    releaseWebRTCPlayer(item.nextPlayer);
                    item.nextPlayer.dataset.playerRole = "next";
                    item.nextPlayer.hidden = true;
                    item.nextPlayer.setAttribute("aria-hidden", "true");
                    item.currentPlayer.dataset.playerRole = "current";
                    item.currentPlayer.dataset.playerActive = "true";
                    item.currentPlayer.dataset.fallbackActive = item.fallbackWasActive
                        ? "true"
                        : "false";
                    item.currentPlayer.hidden = item.fallbackWasActive;
                    item.currentPlayer.setAttribute(
                        "aria-hidden",
                        item.fallbackWasActive ? "true" : "false"
                    );
                    if (item.fallbackWasActive && item.fallback) {
                        item.fallback.hidden = false;
                    }
                });
                console.error("Failed to acknowledge monitor transition:", error);
            })
            .finally(function () {
                transitionSwapInFlight = false;
                scheduleMonitorTransitionPoll();
            });
    }

    function prepareMonitorProfileTransition(transition) {
        if (!transition.transition_id || !mediaTransitionAckUrl || !csrfTokenInput) {
            return;
        }
        if (acknowledgedTransitionId === transition.transition_id) {
            return;
        }
        if (activeTransitionId && activeTransitionId !== transition.transition_id) {
            resetNextWebRTCPlayers();
        }
        activeTransitionId = transition.transition_id;
        const pairs = getTransitionPairs(transition);
        pairs.forEach(function (item) {
            if (
                !item.camera.next_ready ||
                !item.camera.next_player_url ||
                item.nextPlayer.dataset.transitionId === transition.transition_id
            ) {
                return;
            }
            releaseWebRTCPlayer(item.nextPlayer);
            item.nextPlayer.dataset.playerUrl = item.camera.next_player_url;
            item.nextPlayer.dataset.transitionId = transition.transition_id;
            item.nextPlayer.dataset.transitionLoaded = "false";
            item.nextPlayer.dataset.playerActive = "true";
            beginWebRTCStartup(item.nextPlayer, {});
            item.nextPlayer.hidden = false;
            item.nextPlayer.setAttribute("aria-hidden", "true");
            item.nextPlayer.src = item.camera.next_player_url;
        });
        acknowledgePreparedTransition(transition, pairs);
    }

    function syncMonitorProfileTransition() {
        const transition = monitorMediaStatus
            ? monitorMediaStatus.transition
            : null;
        if (!transition) {
            if (
                pendingRequestedMonitorProfile &&
                Date.now() < monitorTransitionRequestDeadline
            ) {
                scheduleMonitorTransitionPoll();
            }
            return;
        }

        const state = transition.profile_transition_state || "idle";
        if (["starting", "preloading", "committing"].includes(state)) {
            transitionWasObserved = true;
            scheduleMonitorTransitionPoll();
        }
        if (state === "preloading") {
            prepareMonitorProfileTransition(transition);
            return;
        }
        if (state === "failed" || state === "cancelled") {
            resetNextWebRTCPlayers();
            transitionWasObserved = false;
            if (
                !pendingRequestedMonitorProfile ||
                transition.profile_transition_to === pendingRequestedMonitorProfile
            ) {
                pendingRequestedMonitorProfile = "";
                lastRequestedMonitorProfile = "";
                monitorTransitionRequestDeadline = 0;
            } else {
                scheduleMonitorTransitionPoll();
            }
            return;
        }
        if (state === "idle") {
            const cameras = transition.cameras || {};
            cameraCards.forEach(function (card) {
                const cameraCode = String(card.dataset.cameraCode || "").toUpperCase();
                const camera = cameras[cameraCode];
                const player = getCurrentWebRTCPlayer(card);
                if (
                    camera &&
                    player &&
                    camera.active_player_url &&
                    !hasExistingWebRTCPlayer(player)
                ) {
                    player.dataset.playerUrl = camera.active_player_url;
                }
            });
            if (transitionWasObserved) {
                pendingRequestedMonitorProfile = "";
                monitorTransitionRequestDeadline = 0;
                transitionWasObserved = false;
                activeTransitionId = "";
            } else if (
                pendingRequestedMonitorProfile &&
                Date.now() < monitorTransitionRequestDeadline
            ) {
                scheduleMonitorTransitionPoll();
            } else {
                pendingRequestedMonitorProfile = "";
                monitorTransitionRequestDeadline = 0;
            }
        }
    }

    function syncVisibleWebRTCPlayers() {
        if (monitorMediaMode !== "mediamtx") {
            return;
        }

        if (!monitorMediaStatus) {
            loadMonitorMediaStatus().then(function () {
                if (!monitorPageExiting) {
                    syncMonitorProfileTransition();
                    syncVisibleWebRTCPlayers();
                }
            });
        }

        monitorSlots.forEach(function (slot) {
            const card = slot.querySelector("[data-monitor-camera-card]");
            const player = card
                ? getCurrentWebRTCPlayer(card)
                : null;

            if (!card || !player) {
                return;
            }

            if (slot.hidden) {
                scheduleCameraStreamRelease(card);
                return;
            }

            cancelScheduledStreamRelease(card);
            if (!monitorMediaStatus) {
                setCardState(card, "loading");
                setOverlay(
                    card,
                    "",
                    card.dataset.cameraCode || "CAMERA",
                    "Checking MediaMTX stream...",
                    "正在確認MediaMTX path狀態"
                );
                return;
            }
            if (isCameraMediaReady(card)) {
                activateWebRTCPlayer(card, player);
                if (hasExistingWebRTCPlayer(player)) {
                    verifyVisibleWebRTCPlayer(card, player);
                }
            } else {
                activateCameraFallback(card, player);
            }
        });
    }

    function syncVisibleCameraStreams() {
        const activationGeneration = ++streamActivationGeneration;
        const requestedProfile = getMonitorStreamProfile();
        const pendingCards = [];

        monitorSlots.forEach(function (slot) {
            const card = slot.querySelector("[data-monitor-camera-card]");

            if (!card) {
                return;
            }

            if (slot.hidden) {
                scheduleCameraStreamRelease(card);
                return;
            }

            cancelScheduledStreamRelease(card);

            const stream = card.querySelector("[data-camera-stream]");
            const player = getCurrentWebRTCPlayer(card);
            if (player) {
                return;
            }
            if (hasExistingStream(stream)) {
                if (stream) {
                    stream.dataset.streamActive = "true";
                }
                if (card.classList.contains("stream-loaded")) {
                    hideOverlay(card);
                }
                return;
            }

            pendingCards.push(card);
        });

        pendingCards.forEach(function (card, index) {
            window.setTimeout(function () {
                if (activationGeneration !== streamActivationGeneration) {
                    return;
                }

                const slot = card.closest("[data-monitor-slot]");
                if (!slot || slot.hidden) {
                    return;
                }

                activateCameraStream(card, requestedProfile);
            }, index * STREAM_ACTIVATION_STAGGER_MS);
        });
    }

    function checkVisibleCameraHealth() {
        if (isMosaicMode() || monitorMediaMode === "mediamtx") {
            return;
        }

        monitorSlots.forEach(function (slot) {
            if (slot.hidden) {
                return;
            }

            const card = slot.querySelector("[data-monitor-camera-card]");
            if (card) {
                checkCameraHealth(card);
            }
        });
    }

    function renderCurrentCameraGroup() {
        const groupStart = currentGroupIndex * currentGridSize;
        const groupEnd = groupStart + currentGridSize;

        monitorSlots.forEach(function (slot) {
            const slotIndex = Number(slot.dataset.slotIndex);
            const isVisible = slotIndex >= groupStart && slotIndex < groupEnd;

            slot.hidden = !isVisible;
            slot.style.order = isVisible
                ? String(slotIndex - groupStart)
                : String(slotIndex);
        });

        if (isMosaicMode()) {
            releaseAllCameraStreams();
            monitorGrid.hidden = true;
            if (monitorMosaic) {
                monitorMosaic.hidden = false;
            }
            renderMosaicInteractionGrid();
            activateMosaicStream();
        } else {
            releaseMosaicStream();
            clearMosaicDragState();
            mosaicOrderKey = "";
            mosaicCameraOrder = [];
            if (monitorMosaic) {
                monitorMosaic.hidden = true;
            }
            monitorGrid.hidden = false;
            syncVisibleWebRTCPlayers();
            syncVisibleCameraStreams();
        }

        if (!selectedSlot || selectedSlot.hidden) {
            const firstVisibleSlot = monitorSlots.find(function (slot) {
                return !slot.hidden;
            });
            selectSlot(firstVisibleSlot);
        }

        updateCameraGroupControls();
    }

    function bindCameraGroupNavigation() {
        if (previousCameraGroup) {
            previousCameraGroup.addEventListener("click", function () {
                if (currentGroupIndex <= 0) {
                    return;
                }

                currentGroupIndex -= 1;
                renderCurrentCameraGroup();

                if (isCarouselRunning) {
                    scheduleCarousel();
                }
            });
        }

        if (nextCameraGroup) {
            nextCameraGroup.addEventListener("click", function () {
                if (currentGroupIndex >= getTotalCameraGroups() - 1) {
                    return;
                }

                currentGroupIndex += 1;
                renderCurrentCameraGroup();

                if (isCarouselRunning) {
                    scheduleCarousel();
                }
            });
        }
    }

    function scheduleMonitorProfileSwitch(gridSize) {
        if (
            monitorMediaMode !== "mediamtx" ||
            !mediaProfileUrl ||
            !csrfTokenInput
        ) {
            return;
        }
        const profileName = monitorProfileLayoutMap[String(gridSize)] || "";
        if (!profileName || profileName === lastRequestedMonitorProfile) {
            return;
        }
        if (monitorProfileSwitchTimer !== null) {
            window.clearTimeout(monitorProfileSwitchTimer);
        }
        monitorProfileSwitchTimer = window.setTimeout(function () {
            monitorProfileSwitchTimer = null;
            const body = new URLSearchParams({profile: profileName});
            fetch(mediaProfileUrl, {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "Content-Type": "application/x-www-form-urlencoded",
                    "X-CSRFToken": csrfTokenInput.value,
                    "X-Requested-With": "XMLHttpRequest"
                },
                body: body.toString()
            })
                .then(function (response) {
                    if (!response.ok) {
                        throw new Error(`Monitor profile HTTP ${response.status}`);
                    }
                    lastRequestedMonitorProfile = profileName;
                    pendingRequestedMonitorProfile = profileName;
                    monitorTransitionRequestDeadline = (
                        Date.now() + MONITOR_PROFILE_TRANSITION_WAIT_MS
                    );
                    transitionWasObserved = false;
                    scheduleMonitorTransitionPoll();
                })
                .catch(function (error) {
                    console.error("Failed to switch monitor profile:", error);
                });
        }, MONITOR_PROFILE_SWITCH_DEBOUNCE_MS);
    }

    function setGridMode(gridSize) {
        if (isCarouselRunning) {
            stopCarousel();
        }

        currentGridSize = parseInt(gridSize, 10);
        currentGroupIndex = 0;
        updateMosaicInteractionState();

        monitorGrid.classList.remove("grid-1", "grid-4", "grid-9", "grid-16");
        monitorGrid.classList.add("grid-" + gridSize);
        renderCurrentCameraGroup();
        scheduleMonitorProfileSwitch(gridSize);

        buttons.forEach(function (btn) {
            if (btn.dataset.grid === gridSize) {
                btn.classList.add("active");
            } else {
                btn.classList.remove("active");
            }
        });
    }

    function setCardState(card, state) {
        card.classList.remove(
            "stream-loading",
            "stream-loaded",
            "stream-warning",
            "stream-error"
        );

        card.classList.add("stream-" + state);
    }

    function setStatusBadge(card, statusText, statusClass) {
        const badge = card.querySelector("[data-status-badge]");

        if (!badge) {
            return;
        }

        badge.className = "camera-status status-" + statusClass;
        badge.textContent = statusText;
    }

    function setOverlay(card, type, title, message, smallText) {
        const overlay = card.querySelector("[data-stream-overlay]");

        if (!overlay) {
            return;
        }

        overlay.classList.remove(
            "hidden",
            "stream-overlay-warning",
            "stream-overlay-error"
        );

        if (type === "warning") {
            overlay.classList.add("stream-overlay-warning");
        }

        if (type === "error") {
            overlay.classList.add("stream-overlay-error");
        }

        overlay.innerHTML = `
            <div>
                <div class="stream-overlay-title">${title}</div>
                <div class="stream-overlay-message">${message}</div>
                ${smallText ? `<div class="stream-overlay-small">${smallText}</div>` : ""}
            </div>
        `;
    }

    function hideOverlay(card) {
        const overlay = card.querySelector("[data-stream-overlay]");

        if (overlay) {
            overlay.classList.add("hidden");
        }
    }

    function markWebRTCPlayerLoaded(player) {
        if (player.dataset.playerActive !== "true") {
            return;
        }

        if (player.dataset.playerRole === "next") {
            player.dataset.transitionLoaded = "true";
            const transition = monitorMediaStatus
                ? monitorMediaStatus.transition
                : null;
            if (
                transition &&
                transition.transition_id === player.dataset.transitionId
            ) {
                scheduleMonitorTransitionPoll();
            }
            return;
        }

        const card = player.closest("[data-monitor-camera-card]");
        if (!card) {
            return;
        }
        player.dataset.iframeLoaded = "true";
        player.dataset.readerStableSamples = "0";
        setCardState(card, "loading");
        setStatusBadge(card, "CONNECTING", "warning");
        setOverlay(
            card,
            "",
            card.dataset.cameraCode || "CAMERA",
            "Loading stream...",
            "播放器已載入，正在確認 MediaMTX reader 與媒體流量"
        );
        refreshMonitorMediaStatus();
    }

    function markStreamLoaded(imageElement) {
        if (imageElement.dataset.streamActive !== "true") {
            return;
        }

        const card = imageElement.closest("[data-monitor-camera-card]");

        if (!card) {
            return;
        }

        setCardState(card, "loaded");
        setStatusBadge(card, "ONLINE", "online");
        hideOverlay(card);
    }

    function markStreamError(imageElement) {
        if (imageElement.dataset.streamActive !== "true") {
            return;
        }

        const card = imageElement.closest("[data-monitor-camera-card]");

        if (!card) {
            return;
        }

        const cameraCode = card.dataset.cameraCode || "CAMERA";

        setCardState(card, "error");
        setStatusBadge(card, "ERROR", "error");

        setOverlay(
            card,
            "error",
            cameraCode,
            "Stream unavailable",
            "\u4e32\u6d41\u7aef\u9ede\u7121\u6cd5\u8f09\u5165\uff0c\u8acb\u6aa2\u67e5 IP Camera \u6216\u5f8c\u7aef\u4e32\u6d41\u670d\u52d9"
        );
    }

    async function checkCameraHealth(card) {
        const checkUrl = card.dataset.checkUrl;
        const cameraCode = card.dataset.cameraCode || "CAMERA";
        const healthCheckKey = getStreamReleaseKey(card);

        if (!checkUrl || !healthCheckKey || monitorPageExiting) {
            return;
        }

        const previousController = healthCheckControllers.get(healthCheckKey);
        if (previousController) {
            previousController.abort();
        }

        const controller = new AbortController();
        healthCheckControllers.set(healthCheckKey, controller);

        setStatusBadge(card, "CHECKING", "checking");

        try {
            const response = await fetch(checkUrl, {
                method: "GET",
                cache: "no-store",
                headers: {
                    "Accept": "application/json"
                },
                signal: controller.signal
            });

            if (!response.ok) {
                throw new Error("Health check HTTP error");
            }

            const data = await response.json();

            const isOnline =
                data.is_online === true ||
                data.online === true ||
                data.status === "online" ||
                data.status === "success";

            if (isOnline) {
                setStatusBadge(card, "ONLINE", "online");

                if (!card.classList.contains("stream-loaded")) {
                    setCardState(card, "warning");
                    setOverlay(
                        card,
                        "warning",
                        cameraCode,
                        "Camera online, stream loading",
                        "Health check \u5df2\u901a\u904e\uff0c\u7b49\u5f85 MJPEG \u5f71\u50cf\u8f09\u5165"
                    );
                }
            } else {
                setCardState(card, "error");
                setStatusBadge(card, "OFFLINE", "offline");

                setOverlay(
                    card,
                    "error",
                    cameraCode,
                    "Camera offline",
                    "Health check \u672a\u901a\u904e\uff0c\u8acb\u78ba\u8a8d\u651d\u5f71\u6a5f\u9023\u7dda\u72c0\u614b"
                );
            }
        } catch (error) {
            if (error.name === "AbortError" || monitorPageExiting) {
                return;
            }

            setCardState(card, "error");
            setStatusBadge(card, "ERROR", "error");

            setOverlay(
                card,
                "error",
                cameraCode,
                "Health check failed",
                "\u7121\u6cd5\u53d6\u5f97\u651d\u5f71\u6a5f\u5065\u5eb7\u6aa2\u67e5\u7d50\u679c"
            );
        } finally {
            if (healthCheckControllers.get(healthCheckKey) === controller) {
                healthCheckControllers.delete(healthCheckKey);
            }
        }
    }

    updateMonitorDateTime();
    monitorClockTimer = window.setInterval(updateMonitorDateTime, 1000);

    prepareMonitorSlots();
    monitorSlots.forEach(function (slot) {
        applySlotPosition(slot);
        syncSlotState(slot);
    });
    bindSlotSelection();
    bindCameraTree();
    bindCameraDragAndDrop();
    bindCameraGroupNavigation();
    bindCarouselControls();
    bindMonitorEventNotifications();
    bindDashboardNavigation();
    updateTreeAssignments();

    window.addEventListener("pagehide", cleanupMonitorPage, {once: true});
    window.addEventListener("beforeunload", cleanupMonitorPage, {once: true});

    cameraStreams.forEach(function (stream) {
        stream.addEventListener("load", function () {
            markStreamLoaded(stream);
        });

        stream.addEventListener("error", function () {
            markStreamError(stream);
        });

        setTimeout(function () {
            const card = stream.closest("[data-monitor-camera-card]");

            if (!card) {
                return;
            }

            if (card.classList.contains("stream-loaded") || card.classList.contains("stream-error")) {
                return;
            }

            const cameraCode = card.dataset.cameraCode || "CAMERA";

            setCardState(card, "warning");

            setOverlay(
                card,
                "warning",
                cameraCode,
                "Still loading stream...",
                "\u4e32\u6d41\u8f09\u5165\u6642\u9593\u8f03\u9577\uff0c\u7cfb\u7d71\u5c07\u6301\u7e8c\u6aa2\u67e5 Camera \u72c0\u614b"
            );
        }, 15000);
    });

    webrtcPlayers.forEach(function (player) {
        player.addEventListener("load", function () {
            markWebRTCPlayerLoaded(player);
        });

        player.addEventListener("error", function () {
            if (player.dataset.playerActive !== "true") {
                return;
            }
            if (player.dataset.playerRole === "next") {
                releaseWebRTCPlayer(player);
                player.dataset.transitionId = "";
                player.dataset.transitionLoaded = "false";
                player.hidden = true;
                player.setAttribute("aria-hidden", "true");
                scheduleMonitorTransitionPoll();
                return;
            }
            const card = player.closest("[data-monitor-camera-card]");
            if (card) {
                setCardState(card, "warning");
                setOverlay(
                    card,
                    "warning",
                    card.dataset.cameraCode || "CAMERA",
                    "WebRTC reconnecting...",
                    "MediaMTX播放端點暫時無法連線，系統將自動重試"
                );
            }
            scheduleWebRTCReconnect(player);
        });
    });

    if (monitorMosaicStream) {
        monitorMosaicStream.addEventListener("load", function () {
            if (!isMosaicMode() || !monitorMosaicStream.getAttribute("src")) {
                return;
            }
            monitorMosaic.classList.remove("is-loading", "is-error");
            monitorMosaic.classList.add("is-loaded");
            setMosaicOverlay("", "", true);
        });

        monitorMosaicStream.addEventListener("error", function () {
            if (!isMosaicMode() || !monitorMosaicStream.getAttribute("src")) {
                return;
            }
            monitorMosaic.classList.remove("is-loading", "is-loaded");
            monitorMosaic.classList.add("is-error");
            setMosaicOverlay(
                "MOSAIC ERROR",
                "合成串流無法載入，請檢查後端狀態",
                false
            );
        });
    }

    healthCheckTimer = window.setInterval(function () {
        checkVisibleCameraHealth();
    }, 30000);

    if (monitorMediaMode === "mediamtx" && mediaStatusUrl) {
        monitorMediaRefreshTimer = window.setInterval(
            refreshMonitorMediaStatus,
            MEDIA_STATUS_REFRESH_MS
        );
    }

    buttons.forEach(function (button) {
        button.addEventListener("click", function () {
            setGridMode(button.dataset.grid);
        });
    });

    setGridMode("4");
    checkVisibleCameraHealth();
});

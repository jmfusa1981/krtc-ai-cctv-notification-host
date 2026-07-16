document.addEventListener("DOMContentLoaded", function () {
    const monitorGrid = document.getElementById("monitorGrid");
    const buttons = document.querySelectorAll(".grid-mode-btn");
    const cameraCards = document.querySelectorAll("[data-monitor-camera-card]");
    const cameraStreams = document.querySelectorAll("[data-camera-stream]");
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
    const layoutNameInput = document.getElementById("layoutNameInput");
    const savedLayoutSelect = document.getElementById("savedLayoutSelect");
    const saveLayoutButton = document.getElementById("saveLayoutButton");
    const loadLayoutButton = document.getElementById("loadLayoutButton");
    const deleteLayoutButton = document.getElementById("deleteLayoutButton");
    const layoutStatus = document.getElementById("layoutStatus");
    const LAYOUT_STORAGE_KEY = "krtc.monitor.layouts.v1";
    const MAX_SLOT_COUNT = 16;
    let monitorSlots = [];
    let selectedSlot = null;
    let currentGridSize = 4;
    let currentGroupIndex = 0;
    let carouselTimer = null;
    let isCarouselRunning = false;

    if (!monitorGrid || buttons.length === 0) {
        return;
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

    function moveCameraToSelectedSlot(cameraId) {
        if (!selectedSlot) {
            const firstVisibleSlot = monitorSlots.find(function (slot) {
                return !slot.hidden;
            });
            selectSlot(firstVisibleSlot);
        }

        const cameraCard = Array.from(cameraCards).find(function (card) {
            return String(card.dataset.cameraId) === String(cameraId);
        });

        if (!cameraCard || !selectedSlot) {
            return;
        }

        const sourceSlot = cameraCard.closest("[data-monitor-slot]");

        if (!sourceSlot || sourceSlot === selectedSlot) {
            updateTreeAssignments();
            return;
        }

        const sourceIndex = sourceSlot.dataset.slotIndex;
        const targetIndex = selectedSlot.dataset.slotIndex;

        sourceSlot.dataset.slotIndex = targetIndex;
        selectedSlot.dataset.slotIndex = sourceIndex;

        applySlotPosition(sourceSlot);
        applySlotPosition(selectedSlot);

        syncSlotState(sourceSlot);
        syncSlotState(selectedSlot);
        selectSlot(sourceSlot);
        updateTreeAssignments();
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

    function setLayoutStatus(message) {
        if (layoutStatus) {
            layoutStatus.textContent = message;
        }
    }

    function readSavedLayouts() {
        try {
            const rawValue = window.localStorage.getItem(LAYOUT_STORAGE_KEY);
            const layouts = rawValue ? JSON.parse(rawValue) : [];

            return Array.isArray(layouts) ? layouts : [];
        } catch (error) {
            console.error("Failed to read monitor layouts:", error);
            return [];
        }
    }

    function writeSavedLayouts(layouts) {
        try {
            window.localStorage.setItem(
                LAYOUT_STORAGE_KEY,
                JSON.stringify(layouts)
            );
            return true;
        } catch (error) {
            console.error("Failed to save monitor layouts:", error);
            setLayoutStatus("\u5132\u5b58\u5931\u6557");
            return false;
        }
    }

    function updateLayoutButtons() {
        const hasSelection = Boolean(
            savedLayoutSelect && savedLayoutSelect.value
        );

        if (loadLayoutButton) {
            loadLayoutButton.disabled = !hasSelection;
        }

        if (deleteLayoutButton) {
            deleteLayoutButton.disabled = !hasSelection;
        }
    }

    function renderSavedLayouts(preferredName) {
        if (!savedLayoutSelect) {
            return;
        }

        const layouts = readSavedLayouts();
        savedLayoutSelect.innerHTML =
            '<option value="">\u9078\u64c7 Layout</option>';

        layouts
            .slice()
            .sort(function (left, right) {
                return left.name.localeCompare(right.name);
            })
            .forEach(function (layout) {
                const option = document.createElement("option");
                option.value = layout.name;
                option.textContent = layout.name;
                savedLayoutSelect.appendChild(option);
            });

        if (preferredName && layouts.some(function (layout) {
            return layout.name === preferredName;
        })) {
            savedLayoutSelect.value = preferredName;
        }

        updateLayoutButtons();
    }

    function captureCurrentLayout(name) {
        const assignments = Array.from(cameraCards).map(function (card) {
            const slot = card.closest("[data-monitor-slot]");

            return {
                cameraId: String(card.dataset.cameraId || ""),
                slotIndex: slot ? Number(slot.dataset.slotIndex) : null
            };
        }).filter(function (assignment) {
            return assignment.cameraId && Number.isInteger(assignment.slotIndex);
        });

        return {
            name: name,
            gridSize: currentGridSize,
            assignments: assignments,
            carouselSeconds: carouselInterval
                ? parseInt(carouselInterval.value, 10)
                : 10,
            sidebarCollapsed: Boolean(
                monitorContent &&
                monitorContent.classList.contains("sidebar-collapsed")
            ),
            updatedAt: new Date().toISOString()
        };
    }

    function saveCurrentLayout() {
        if (!layoutNameInput) {
            return;
        }

        const name = layoutNameInput.value.trim();

        if (!name) {
            setLayoutStatus("\u8acb\u8f38\u5165\u540d\u7a31");
            layoutNameInput.focus();
            return;
        }

        const layouts = readSavedLayouts();
        const nextLayout = captureCurrentLayout(name);
        const existingIndex = layouts.findIndex(function (layout) {
            return layout.name === name;
        });

        if (existingIndex >= 0) {
            layouts[existingIndex] = nextLayout;
        } else {
            layouts.push(nextLayout);
        }

        if (!writeSavedLayouts(layouts)) {
            return;
        }

        renderSavedLayouts(name);
        setLayoutStatus(existingIndex >= 0 ? "\u5df2\u8986\u5beb" : "\u5df2\u5132\u5b58");
    }

    function restoreLayoutAssignments(assignments) {
        const desiredByCameraId = new Map();
        const reservedIndices = new Set();
        const assignedSlots = new Set();
        const availableCameraIds = new Set(
            Array.from(cameraCards).map(function (card) {
                return String(card.dataset.cameraId || "");
            })
        );

        (Array.isArray(assignments) ? assignments : []).forEach(function (assignment) {
            const slotIndex = Number(assignment.slotIndex);
            const cameraId = String(assignment.cameraId || "");

            if (
                cameraId &&
                availableCameraIds.has(cameraId) &&
                Number.isInteger(slotIndex) &&
                slotIndex >= 0 &&
                slotIndex < MAX_SLOT_COUNT &&
                !reservedIndices.has(slotIndex)
            ) {
                desiredByCameraId.set(cameraId, slotIndex);
                reservedIndices.add(slotIndex);
            }
        });

        cameraCards.forEach(function (card) {
            const cameraId = String(card.dataset.cameraId || "");
            const desiredIndex = desiredByCameraId.get(cameraId);
            const slot = card.closest("[data-monitor-slot]");

            if (slot && desiredIndex !== undefined) {
                slot.dataset.slotIndex = String(desiredIndex);
                assignedSlots.add(slot);
            }
        });

        const remainingIndices = Array.from(
            { length: MAX_SLOT_COUNT },
            function (_, index) {
                return index;
            }
        ).filter(function (index) {
            return !reservedIndices.has(index);
        });

        monitorSlots
            .filter(function (slot) {
                return !assignedSlots.has(slot);
            })
            .forEach(function (slot, index) {
                slot.dataset.slotIndex = String(remainingIndices[index]);
            });

        monitorSlots.forEach(function (slot) {
            applySlotPosition(slot);
            syncSlotState(slot);
        });

        updateTreeAssignments();
    }

    function loadSelectedLayout() {
        if (!savedLayoutSelect || !savedLayoutSelect.value) {
            return;
        }

        const selectedName = savedLayoutSelect.value;
        const layout = readSavedLayouts().find(function (item) {
            return item.name === selectedName;
        });

        if (!layout) {
            setLayoutStatus("\u627e\u4e0d\u5230 Layout");
            renderSavedLayouts();
            return;
        }

        stopCarousel();

        if (carouselInterval && layout.carouselSeconds) {
            carouselInterval.value = String(layout.carouselSeconds);
        }

        restoreLayoutAssignments(layout.assignments);
        setGridMode(String(layout.gridSize || 4));

        if (monitorContent) {
            monitorContent.classList.toggle(
                "sidebar-collapsed",
                Boolean(layout.sidebarCollapsed)
            );
        }

        if (cameraTreeToggle) {
            const isCollapsed = Boolean(layout.sidebarCollapsed);
            cameraTreeToggle.classList.toggle("active", !isCollapsed);
            cameraTreeToggle.setAttribute("aria-expanded", String(!isCollapsed));
        }

        if (layoutNameInput) {
            layoutNameInput.value = layout.name;
        }

        updateCarouselUi();
        setLayoutStatus("\u5df2\u8f09\u5165");
    }

    function deleteSelectedLayout() {
        if (!savedLayoutSelect || !savedLayoutSelect.value) {
            return;
        }

        const selectedName = savedLayoutSelect.value;
        const shouldDelete = window.confirm(
            `\u78ba\u5b9a\u522a\u9664 Layout\u300c${selectedName}\u300d\uff1f`
        );

        if (!shouldDelete) {
            return;
        }

        const layouts = readSavedLayouts().filter(function (layout) {
            return layout.name !== selectedName;
        });

        if (!writeSavedLayouts(layouts)) {
            return;
        }

        renderSavedLayouts();
        setLayoutStatus("\u5df2\u522a\u9664");
    }

    function bindLayoutControls() {
        if (saveLayoutButton) {
            saveLayoutButton.addEventListener("click", saveCurrentLayout);
        }

        if (loadLayoutButton) {
            loadLayoutButton.addEventListener("click", loadSelectedLayout);
        }

        if (deleteLayoutButton) {
            deleteLayoutButton.addEventListener("click", deleteSelectedLayout);
        }

        if (savedLayoutSelect) {
            savedLayoutSelect.addEventListener("change", function () {
                updateLayoutButtons();
                setLayoutStatus("");
            });
        }

        if (layoutNameInput) {
            layoutNameInput.addEventListener("keydown", function (event) {
                if (event.key === "Enter") {
                    event.preventDefault();
                    saveCurrentLayout();
                }
            });
        }

        renderSavedLayouts();
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
                ? "\u505c\u6b62\u8f2a\u64ad"
                : "\u958b\u59cb\u8f2a\u64ad";
        }

        if (carouselInterval) {
            carouselInterval.disabled = !canRun;
        }

        if (carouselStatus) {
            carouselStatus.textContent = isCarouselRunning
                ? `${Math.round(getCarouselIntervalMilliseconds() / 1000)} \u79d2\u8f2a\u64ad\u4e2d`
                : (canRun ? "\u8f2a\u64ad\u5f85\u547d" : "\u50c5\u4e00\u7d44");
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

    function setGridMode(gridSize) {
        if (isCarouselRunning) {
            stopCarousel();
        }

        currentGridSize = parseInt(gridSize, 10);
        currentGroupIndex = 0;

        monitorGrid.classList.remove("grid-1", "grid-4", "grid-9", "grid-16");
        monitorGrid.classList.add("grid-" + gridSize);
        renderCurrentCameraGroup();

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

    function markStreamLoaded(imageElement) {
        const card = imageElement.closest("[data-monitor-camera-card]");

        if (!card) {
            return;
        }

        setCardState(card, "loaded");
        setStatusBadge(card, "ONLINE", "online");
        hideOverlay(card);
    }

    function markStreamError(imageElement) {
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

        if (!checkUrl) {
            return;
        }

        setStatusBadge(card, "CHECKING", "checking");

        try {
            const response = await fetch(checkUrl, {
                method: "GET",
                cache: "no-store",
                headers: {
                    "Accept": "application/json"
                }
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
            setCardState(card, "error");
            setStatusBadge(card, "ERROR", "error");

            setOverlay(
                card,
                "error",
                cameraCode,
                "Health check failed",
                "\u7121\u6cd5\u53d6\u5f97\u651d\u5f71\u6a5f\u5065\u5eb7\u6aa2\u67e5\u7d50\u679c"
            );
        }
    }

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
    bindLayoutControls();
    updateTreeAssignments();

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

    cameraCards.forEach(function (card) {
        checkCameraHealth(card);
    });

    setInterval(function () {
        cameraCards.forEach(function (card) {
            checkCameraHealth(card);
        });
    }, 30000);

    buttons.forEach(function (button) {
        button.addEventListener("click", function () {
            setGridMode(button.dataset.grid);
        });
    });

    setGridMode("4");
});

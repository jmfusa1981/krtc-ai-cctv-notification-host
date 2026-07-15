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
    const MAX_SLOT_COUNT = 16;
    let monitorSlots = [];
    let selectedSlot = null;

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

    function setGridMode(gridSize) {
        const maxVisible = parseInt(gridSize, 10);

        monitorGrid.classList.remove("grid-1", "grid-4", "grid-9", "grid-16");
        monitorGrid.classList.add("grid-" + gridSize);

        monitorSlots.forEach(function (slot) {
            slot.hidden = Number(slot.dataset.slotIndex) >= maxVisible;
        });

        if (!selectedSlot || selectedSlot.hidden) {
            const firstVisibleSlot = monitorSlots.find(function (slot) {
                return !slot.hidden;
            });
            selectSlot(firstVisibleSlot);
        }

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

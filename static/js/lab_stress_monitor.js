document.addEventListener("DOMContentLoaded", function () {
    "use strict";

    const body = document.body;
    const grid = document.getElementById("stressGrid");
    const summary = document.getElementById("stressSummary");
    const statusUrl = body.dataset.stressStatusUrl;
    const telemetryUrl = body.dataset.stressTelemetryUrl;
    const csrfToken = document.querySelector("[name=csrfmiddlewaretoken]").value;
    const tiles = Array.from(grid.querySelectorAll("[data-stress-tile]"));
    const loadingStartedAt = new Map();
    const PLAYER_TIMEOUT_MS = 10000;
    const STATUS_POLL_MS = 1000;
    const RETRY_DELAY_MS = 5000;
    let visibleCount = 9;
    let pageSuspended = false;

    function overlayMessage(tile, message) {
        const node = tile.querySelector("[data-stress-overlay] span");
        if (node) {
            node.textContent = message;
        }
    }

    function releaseTile(tile, state, message) {
        const player = tile.querySelector("[data-stress-player]");
        window.KRTCMediaPlayer.releaseWebRTC(player);
        tile.dataset.state = state || "idle";
        tile.dataset.loadingStartedAt = "";
        loadingStartedAt.delete(tile.dataset.path);
        if (message) {
            overlayMessage(tile, message);
        }
    }

    function reportTelemetry(eventName, recoveredPath, recoveryDuration) {
        const form = new FormData();
        const loadingPaths = tiles
            .filter(function (tile) {
                return !tile.hidden && tile.dataset.state === "loading";
            })
            .map(function (tile) {
                return tile.dataset.path;
            });
        const oldestLoadingStartedAt = Array.from(loadingStartedAt.values())
            .sort(function (left, right) {
                return left - right;
            })[0];
        form.append("visible_stream_count", String(visibleCount));
        form.append("loading_paths", loadingPaths.join(","));
        form.append("recovered_path", recoveredPath || "");
        form.append("recovery_duration_ms", String(recoveryDuration || 0));
        form.append("event", eventName);
        form.append("timestamp", new Date().toISOString());
        form.append(
            "oldest_loading_started_at",
            oldestLoadingStartedAt
                ? new Date(oldestLoadingStartedAt).toISOString()
                : ""
        );
        fetch(telemetryUrl, {
            method: "POST",
            headers: {"X-CSRFToken": csrfToken},
            body: form,
            keepalive: true,
        }).catch(function () {
            return null;
        });
    }

    function activateTile(tile) {
        if (
            pageSuspended ||
            tile.hidden ||
            tile.dataset.state === "loading" ||
            tile.dataset.state === "loaded"
        ) {
            return;
        }
        const retryAt = Number(tile.dataset.retryAt || 0);
        if (retryAt > Date.now()) {
            return;
        }
        const player = tile.querySelector("[data-stress-player]");
        const playerUrl = player.dataset.playerUrl;
        const startedAt = Date.now();
        loadingStartedAt.set(tile.dataset.path, startedAt);
        tile.dataset.loadingStartedAt = new Date(startedAt).toISOString();
        tile.dataset.documentLoaded = "false";
        tile.dataset.state = "loading";
        overlayMessage(tile, "Still loading stream...");
        player.onload = function () {
            tile.dataset.documentLoaded = "true";
        };
        player.onerror = function () {
            releaseTile(tile, "unavailable", "WebRTC player unavailable");
            tile.dataset.retryAt = String(Date.now() + RETRY_DELAY_MS);
        };
        window.KRTCMediaPlayer.activateWebRTC(player, playerUrl);
        reportTelemetry("loading");
    }

    function markTileLoaded(tile) {
        if (tile.dataset.state !== "loading") {
            return;
        }
        const startedAt = loadingStartedAt.get(tile.dataset.path) || Date.now();
        const duration = Date.now() - startedAt;
        tile.dataset.state = "loaded";
        tile.dataset.recoveryDurationMs = String(duration);
        loadingStartedAt.delete(tile.dataset.path);
        reportTelemetry("recovered", tile.dataset.path, duration);
    }

    function setGrid(count) {
        visibleCount = count;
        grid.className = `stress-grid stress-grid--${count}`;
        grid.dataset.visibleCount = String(count);
        tiles.forEach(function (tile, index) {
            const shouldShow = index < count;
            tile.hidden = !shouldShow;
            if (!shouldShow) {
                releaseTile(tile, "hidden", "Hidden stream released");
            }
        });
        document.querySelectorAll("[data-stress-grid]").forEach(function (button) {
            button.classList.toggle(
                "active",
                Number(button.dataset.stressGrid) === count
            );
        });
        reportTelemetry("layout");
    }

    async function pollStatus() {
        if (pageSuspended) {
            return;
        }
        try {
            const response = await fetch(statusUrl, {cache: "no-store"});
            const payload = await response.json();
            if (!response.ok || !payload.success) {
                throw new Error(payload.error || "status_unavailable");
            }
            tiles.forEach(function (tile) {
                if (tile.hidden) {
                    return;
                }
                const detail = payload.paths[tile.dataset.path] || {};
                tile.dataset.pathReady = String(detail.ready === true);
                tile.dataset.readerCount = String(detail.reader_count || 0);
                if (
                    tile.dataset.state === "loading" &&
                    tile.dataset.documentLoaded === "true" &&
                    detail.ready === true &&
                    Number(detail.webrtc_reader_count || 0) > 0
                ) {
                    markTileLoaded(tile);
                    return;
                }
                if (
                    tile.dataset.state === "loading" &&
                    Date.now() - Number(loadingStartedAt.get(tile.dataset.path) || 0) >
                        PLAYER_TIMEOUT_MS
                ) {
                    releaseTile(tile, "timeout", "Loading timeout; retry pending");
                    tile.dataset.retryAt = String(Date.now() + RETRY_DELAY_MS);
                    reportTelemetry("timeout");
                    return;
                }
                if (tile.dataset.state === "loaded" && detail.ready !== true) {
                    releaseTile(tile, "unavailable", "Stream path unavailable");
                    tile.dataset.retryAt = String(Date.now() + RETRY_DELAY_MS);
                    return;
                }
                if (detail.ready === true) {
                    activateTile(tile);
                } else if (tile.dataset.state !== "loading") {
                    tile.dataset.state = "unavailable";
                    overlayMessage(tile, "Stream path unavailable");
                }
            });
            summary.textContent = [
                `ready=${payload.ready_stress_path_count}/16`,
                `stress_sessions=${payload.stress_webrtc_session_count}`,
                `readers=${payload.active_reader_count}`,
                `visible=${visibleCount}`,
            ].join(" | ");
        } catch (error) {
            summary.textContent = `MediaMTX diagnostics unavailable: ${error.message}`;
        }
    }

    function scheduleAutomaticProfile() {
        const params = new URLSearchParams(window.location.search);
        if (params.get("auto") !== "1") {
            return;
        }
        [
            [5, 16],
            [10, 4],
            [11, 9],
            [12, 16],
            [13, 4],
            [14, 16],
        ].forEach(function (entry) {
            window.setTimeout(function () {
                setGrid(entry[1]);
            }, entry[0] * 60 * 1000);
        });
    }

    document.querySelectorAll("[data-stress-grid]").forEach(function (button) {
        button.addEventListener("click", function () {
            setGrid(Number(button.dataset.stressGrid));
        });
    });
    window.addEventListener("pagehide", function () {
        pageSuspended = true;
        tiles.forEach(function (tile) {
            releaseTile(tile, "released", "Page session released");
        });
        reportTelemetry("heartbeat");
    });

    setGrid(9);
    scheduleAutomaticProfile();
    pollStatus();
    window.setInterval(pollStatus, STATUS_POLL_MS);
    window.setInterval(function () {
        reportTelemetry("heartbeat");
    }, 5000);
});

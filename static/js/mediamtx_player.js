(function (global) {
    "use strict";

    const RELEASE_PLACEHOLDER =
        "data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=";

    function hasWebRTCSource(player) {
        const source = player ? player.getAttribute("src") : "";
        return Boolean(source && source !== "about:blank");
    }

    function activateWebRTC(player, playerUrl) {
        if (!player || !playerUrl) {
            return false;
        }
        player.dataset.playerActive = "true";
        player.dataset.playerUrl = playerUrl;
        if (!hasWebRTCSource(player) || player.getAttribute("src") !== playerUrl) {
            player.src = playerUrl;
        }
        return true;
    }

    function releaseWebRTC(player) {
        if (!player) {
            return;
        }
        player.dataset.playerActive = "false";
        if (hasWebRTCSource(player)) {
            // 移除iframe文件可同步終止其內部RTCPeerConnection與WHEP工作階段。
            player.src = "about:blank";
            player.removeAttribute("src");
        }
    }

    function hasMjpegSource(image) {
        return Boolean(image && image.getAttribute("src"));
    }

    function activateMjpeg(image, streamUrl) {
        if (!image || !streamUrl) {
            return false;
        }
        image.dataset.streamActive = "true";
        if (!hasMjpegSource(image) || image.getAttribute("src") !== streamUrl) {
            image.src = streamUrl;
        }
        return true;
    }

    function releaseMjpeg(image) {
        if (!image) {
            return;
        }
        image.dataset.streamActive = "false";
        image.src = RELEASE_PLACEHOLDER;
        image.removeAttribute("src");
    }

    global.KRTCMediaPlayer = Object.freeze({
        activateMjpeg: activateMjpeg,
        activateWebRTC: activateWebRTC,
        hasMjpegSource: hasMjpegSource,
        hasWebRTCSource: hasWebRTCSource,
        releaseMjpeg: releaseMjpeg,
        releaseWebRTC: releaseWebRTC,
    });
})(window);

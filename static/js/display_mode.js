(function () {
    "use strict";

    const storageKey = "krtc-display-mode";
    const root = document.documentElement;

    function normalizeLandscapeMode() {
        root.dataset.displayMode = "landscape";
        try {
            if (window.localStorage.getItem(storageKey) !== "landscape") {
                window.localStorage.setItem(storageKey, "landscape");
            }
        } catch (error) {
            // 強化或私密瀏覽環境可能禁止存取Storage，橫式runtime仍可正常運作。
        }
        window.dispatchEvent(new CustomEvent("krtc:display-mode-change", {
            detail: {mode: "landscape"},
        }));
    }

    normalizeLandscapeMode();
}());

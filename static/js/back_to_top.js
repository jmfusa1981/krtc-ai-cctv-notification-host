/* KRTC V6.4.6.1 - shared Back to Top behavior */
(function () {
    "use strict";

    const buttons = document.querySelectorAll("[data-krtc-back-to-top]");
    if (!buttons.length) return;

    buttons.forEach(function (button) {
        const selector = (button.getAttribute("data-scroll-target") || "").trim();
        const target = selector ? document.querySelector(selector) : null;
        const threshold = 220;

        function currentScrollTop() {
            if (target) return target.scrollTop || 0;
            return window.scrollY || document.documentElement.scrollTop || 0;
        }

        function updateVisibility() {
            button.classList.toggle("is-visible", currentScrollTop() > threshold);
        }

        if (target) {
            target.addEventListener("scroll", updateVisibility, { passive: true });
        } else {
            window.addEventListener("scroll", updateVisibility, { passive: true });
        }

        button.addEventListener("click", function () {
            if (target) {
                target.scrollTo({ top: 0, behavior: "smooth" });
            } else {
                window.scrollTo({ top: 0, behavior: "smooth" });
            }
        });

        updateVisibility();
    });
})();

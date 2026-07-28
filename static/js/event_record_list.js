(() => {
    "use strict";

    const form = document.getElementById("recordFilterForm");
    const exportButtons = document.querySelectorAll("[data-export-url]");
    const dialog = document.getElementById("snapshotDialog");
    const dialogImage = document.getElementById("snapshotDialogImage");
    const dialogTitle = document.getElementById("snapshotDialogTitle");
    const dialogClose = document.getElementById("snapshotDialogClose");

    exportButtons.forEach((button) => {
        button.addEventListener("click", () => {
            const params = new URLSearchParams(new FormData(form));
            const baseUrl = button.dataset.exportUrl;
            window.location.href = params.toString() ? `${baseUrl}?${params}` : baseUrl;
        });
    });

    document.querySelectorAll("[data-snapshot-url]").forEach((button) => {
        button.addEventListener("click", () => {
            if (!dialog || !dialogImage) return;
            dialogImage.src = button.dataset.snapshotUrl || "";
            dialogTitle.textContent = button.dataset.snapshotTitle || "事件快照";
            dialog.showModal();
        });
    });

    if (dialogClose) {
        dialogClose.addEventListener("click", () => dialog.close());
    }

    if (dialog) {
        dialog.addEventListener("click", (event) => {
            if (event.target === dialog) dialog.close();
        });
    }
})();

document.addEventListener("DOMContentLoaded", function () {
    const cards = Array.from(document.querySelectorAll("[data-snapshot-card]"));
    const searchInput = document.getElementById("snapshotSearch");
    const storageFilter = document.getElementById("snapshotStorageFilter");
    const resultCount = document.getElementById("snapshotResultCount");
    const dialog = document.getElementById("snapshotDialog");
    const dialogImage = document.getElementById("snapshotDialogImage");
    const dialogTitle = document.getElementById("snapshotDialogTitle");
    const dialogClose = document.getElementById("snapshotDialogClose");

    function normalize(value) {
        return String(value || "").trim().toLocaleLowerCase("zh-TW");
    }

    function applyFilters() {
        const keyword = normalize(searchInput ? searchInput.value : "");
        const storage = storageFilter ? storageFilter.value : "all";
        let visibleCount = 0;

        cards.forEach(function (card) {
            const matchesSearch = !keyword || normalize(card.dataset.search).includes(keyword);
            const matchesStorage = storage === "all" || card.dataset.storage === storage;
            const visible = matchesSearch && matchesStorage;
            card.hidden = !visible;
            if (visible) visibleCount += 1;
        });

        if (resultCount) resultCount.textContent = `顯示 ${visibleCount} 筆`;
    }

    function openPreview(button) {
        const url = button.dataset.previewUrl;
        if (!url || !dialog || !dialogImage) return;
        dialogImage.src = url;
        dialogTitle.textContent = button.dataset.previewTitle || "事件快照";
        if (typeof dialog.showModal === "function") dialog.showModal();
    }

    document.querySelectorAll("[data-preview-url]").forEach(function (button) {
        button.addEventListener("click", function () {
            openPreview(button);
        });
    });

    document.querySelectorAll(".snapshot-preview-button img").forEach(function (image) {
        image.addEventListener("error", function () {
            const button = image.closest(".snapshot-preview-button");
            if (button) button.classList.add("is-error");
            image.hidden = true;
        });
    });

    if (searchInput) searchInput.addEventListener("input", applyFilters);
    if (storageFilter) storageFilter.addEventListener("change", applyFilters);
    if (dialogClose) dialogClose.addEventListener("click", function () { dialog.close(); });
    if (dialog) {
        dialog.addEventListener("click", function (event) {
            if (event.target === dialog) dialog.close();
        });
        dialog.addEventListener("close", function () { dialogImage.removeAttribute("src"); });
    }
});

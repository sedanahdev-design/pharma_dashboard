// Lives outside the htmx-swapped #dashboard-content region, so event
// delegation on `document` keeps working after every partial swap.
(function () {
    let lastSearchValue = "";

    function normalize(text) {
        return (text || "").toLowerCase();
    }

    function applyFilter(query) {
        const q = normalize(query.trim());
        const categoryItems = document.querySelectorAll("#filterable-categories > .category-editor-item");
        const resultCards = document.querySelectorAll("#filterable-results > .result-category");
        let anyCategoryVisible = false;
        let anyResultVisible = false;

        categoryItems.forEach((el) => {
            const match = !q || normalize(el.dataset.search).includes(q);
            el.hidden = !match;
            if (match) anyCategoryVisible = true;
        });
        resultCards.forEach((el) => {
            const match = !q || normalize(el.dataset.search).includes(q);
            el.hidden = !match;
            if (match) anyResultVisible = true;
        });

        const noCategoryMatch = document.getElementById("no-category-match");
        if (noCategoryMatch) noCategoryMatch.style.display = categoryItems.length && !anyCategoryVisible ? "block" : "none";
        const noResultMatch = document.getElementById("no-result-match");
        if (noResultMatch) noResultMatch.style.display = resultCards.length && !anyResultVisible ? "block" : "none";
    }

    function showToast(message) {
        let toast = document.getElementById("toast");
        if (!toast) {
            toast = document.createElement("div");
            toast.id = "toast";
            document.body.appendChild(toast);
        }
        toast.textContent = message;
        toast.classList.add("show");
        clearTimeout(toast._hideTimer);
        toast._hideTimer = setTimeout(() => toast.classList.remove("show"), 2200);
    }

    function jumpToResult(targetId) {
        const searchInput = document.getElementById("global-search");
        if (searchInput && searchInput.value) {
            searchInput.value = "";
            applyFilter("");
        }
        const el = document.getElementById(targetId);
        if (!el) {
            showToast("لا توجد نتيجة لهذا التصنيف بعد — لم يُباع منه شيء هذا الشهر");
            return;
        }
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        el.classList.remove("flash-highlight");
        // Force reflow so the animation can restart if clicked twice in a row.
        void el.offsetWidth;
        el.classList.add("flash-highlight");
        setTimeout(() => el.classList.remove("flash-highlight"), 1500);
    }

    document.addEventListener("input", (e) => {
        if (e.target && e.target.id === "global-search") {
            lastSearchValue = e.target.value;
            applyFilter(lastSearchValue);
        }
    });

    document.addEventListener("click", (e) => {
        const btn = e.target.closest("[data-jump-to]");
        if (btn) {
            jumpToResult(btn.dataset.jumpTo);
        }
    });

    // htmx re-renders #dashboard-content from scratch on every category/item
    // edit, so the search box would otherwise reset - restore its value and
    // re-apply the filter against the fresh markup.
    document.body.addEventListener("htmx:afterSwap", () => {
        const searchInput = document.getElementById("global-search");
        if (searchInput && lastSearchValue) {
            searchInput.value = lastSearchValue;
            applyFilter(lastSearchValue);
        }
    });
})();

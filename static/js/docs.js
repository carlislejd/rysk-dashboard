(() => {
    const base = String(window.DOCS_API_BASE || window.location.origin || "").replace(/\/+$/, "");
    const input = document.getElementById("docs-address-input");
    const applyBtn = document.getElementById("docs-apply-address");
    const statusEl = document.getElementById("docs-address-status");
    const outputEl = document.getElementById("docs-live-output");
    const selectedEl = document.getElementById("docs-selected-endpoint");
    const openEndpointEl = document.getElementById("docs-open-endpoint");
    const expandBtn = document.getElementById("docs-output-expand");
    const links = Array.from(document.querySelectorAll(".docs-endpoint[data-path]"));
    const ADDRESS_RE = /^0x[0-9a-fA-F]{40}$/;
    let currentPreviewUrl = "";

    if (!input || !applyBtn || !statusEl || !outputEl || !selectedEl || !openEndpointEl || !expandBtn || !base) return;

    function setStatus(message, isError) {
        statusEl.textContent = message;
        statusEl.style.color = isError ? "var(--color-error)" : "var(--text-muted)";
    }

    function applyAddress() {
        const address = String(input.value || "").trim();
        if (!ADDRESS_RE.test(address)) {
            setStatus("Enter a valid wallet address (0x + 40 hex chars).", true);
            links.forEach((link) => {
                link.href = "#";
                link.dataset.resolvedPath = "";
            });
            currentPreviewUrl = "";
            selectedEl.textContent = "No endpoint selected.";
            openEndpointEl.href = "#";
            openEndpointEl.classList.add("disabled");
            return false;
        }

        links.forEach((link) => {
            const template = link.getAttribute("data-path") || "";
            const path = template.replace("{address}", encodeURIComponent(address));
            link.dataset.resolvedPath = path;
            link.href = `${window.location.origin}${path}`;
        });

        setStatus("Address applied. Click any endpoint card.", false);
        return true;
    }

    async function previewEndpoint(link) {
        const path = link.dataset.resolvedPath || "";
        if (!path) {
            setStatus("Provide a valid address first.", true);
            return;
        }

        outputEl.textContent = "Loading...";
        selectedEl.textContent = link.querySelector("span")?.textContent || path;
        try {
            const response = await fetch(path, { method: "GET" });
            const text = await response.text();
            let formatted = text;
            try {
                formatted = JSON.stringify(JSON.parse(text), null, 2);
            } catch (_) {
                // Leave non-JSON responses as raw text.
            }
            outputEl.textContent = formatted;
            currentPreviewUrl = `${window.location.origin}${path}`;
            openEndpointEl.href = `${base}${path}`;
            openEndpointEl.classList.remove("disabled");
            setStatus("Preview loaded. Open endpoint if needed.", false);
        } catch (error) {
            outputEl.textContent = `Preview failed: ${String(error)}`;
            currentPreviewUrl = "";
            openEndpointEl.href = "#";
            openEndpointEl.classList.add("disabled");
            setStatus("Preview failed. Try opening endpoint directly.", true);
        }
    }

    links.forEach((link) => {
        link.addEventListener("click", (event) => {
            event.preventDefault();
            previewEndpoint(link);
        });
    });

    expandBtn.addEventListener("click", () => {
        outputEl.classList.toggle("expanded");
        expandBtn.textContent = outputEl.classList.contains("expanded") ? "Collapse" : "Expand";
    });

    openEndpointEl.addEventListener("click", (event) => {
        if (!currentPreviewUrl) {
            event.preventDefault();
        }
    });

    applyBtn.addEventListener("click", applyAddress);
    input.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
            event.preventDefault();
            applyAddress();
        }
    });

    if (String(input.value || "").trim()) {
        applyAddress();
    } else {
        setStatus("Provide an address to enable endpoint links.", false);
    }
})();

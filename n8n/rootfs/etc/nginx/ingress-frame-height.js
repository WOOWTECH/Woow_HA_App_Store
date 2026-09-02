(function () {
    "use strict";

    var frame = window.frameElement;
    if (!frame) return;

    var root = frame.getRootNode && frame.getRootNode();
    var host = root && root.host;
    if (!host || host.localName !== "ha-panel-app") return;

    var hostHeight = window.CSS && CSS.supports("height", "100dvh")
        ? "100dvh"
        : "100vh";
    var parentWindow = window.parent;
    var observer = null;
    var parentListening = false;
    var active = false;
    var applying = false;

    function applyHeight() {
        if (applying) return;
        applying = true;

        var changed = false;
        if (host.style.height !== hostHeight) {
            host.style.height = hostHeight;
            changed = true;
        }
        if (frame.style.height !== "100%") {
            frame.style.height = "100%";
            changed = true;
        }

        applying = false;
        if (changed) {
            window.dispatchEvent(new Event("resize"));
        }
    }

    function start() {
        if (active) {
            applyHeight();
            return;
        }
        active = true;

        window.addEventListener("resize", applyHeight);
        try {
            parentWindow.addEventListener("resize", applyHeight);
            parentListening = true;
        } catch (_error) {
            parentListening = false;
        }

        if (window.ResizeObserver) {
            if (!observer) observer = new ResizeObserver(applyHeight);
            observer.observe(frame);
        }

        applyHeight();
    }

    function stop() {
        if (!active) return;
        active = false;

        window.removeEventListener("resize", applyHeight);
        if (parentListening) {
            try {
                parentWindow.removeEventListener("resize", applyHeight);
            } catch (_error) {
                // The parent can disappear during document navigation.
            }
            parentListening = false;
        }
        if (observer) observer.disconnect();
    }

    window.addEventListener("pageshow", start);
    window.addEventListener("pagehide", stop);
    start();
})();

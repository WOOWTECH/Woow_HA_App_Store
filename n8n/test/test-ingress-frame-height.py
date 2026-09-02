#!/usr/bin/env python3
"""Browser regression test for the Home Assistant ingress frame-height adapter."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import sync_playwright


ADDON_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ADDON_DIR / "rootfs/etc/nginx/ingress-frame-height.js"
RESOURCE_PATH = "/_woow/ingress-frame-height.js"

PARENT_HTML = """<!doctype html>
<meta charset="utf-8">
<style>
  html, body { margin: 0; }
  ha-panel-app { display: block; height: 40vh; }
  iframe { display: block; width: 100%; height: 100%; border: 0; }
</style>
<ha-panel-app></ha-panel-app>
<script>
  window.parentResizeListeners = new Set();
  window.parentResizeAdds = 0;
  window.parentResizeRemoves = 0;
  window.activeChildObservers = 0;
  const nativeAddEventListener = window.addEventListener;
  const nativeRemoveEventListener = window.removeEventListener;
  window.addEventListener = function(type, listener, options) {
    if (type === 'resize') {
      window.parentResizeListeners.add(listener);
      window.parentResizeAdds += 1;
    }
    return nativeAddEventListener.call(this, type, listener, options);
  };
  window.removeEventListener = function(type, listener, options) {
    if (type === 'resize' && window.parentResizeListeners.delete(listener)) {
      window.parentResizeRemoves += 1;
    }
    return nativeRemoveEventListener.call(this, type, listener, options);
  };
</script>
"""

CHILD_HTML = f"""<!doctype html>
<meta charset="utf-8">
<script>
  window.syntheticResizeCount = 0;
  addEventListener('resize', (event) => {{
    if (!event.isTrusted) window.syntheticResizeCount += 1;
  }});
  const NativeResizeObserver = window.ResizeObserver;
  window.activeObserverCount = 0;
  window.createdObserverCount = 0;
  window.ResizeObserver = class extends NativeResizeObserver {{
    constructor(callback) {{
      super(callback);
      this.adapterActive = false;
      window.createdObserverCount += 1;
    }}
    observe(target, options) {{
      if (!this.adapterActive) {{
        this.adapterActive = true;
        window.activeObserverCount += 1;
        window.parent.activeChildObservers += 1;
      }}
      return super.observe(target, options);
    }}
    disconnect() {{
      if (this.adapterActive) {{
        this.adapterActive = false;
        window.activeObserverCount -= 1;
        window.parent.activeChildObservers -= 1;
      }}
      return super.disconnect();
    }}
  }};
  requestAnimationFrame(() => {{
    window.baselineHeight = innerHeight;
    const script = document.createElement('script');
    script.src = '{RESOURCE_PATH}';
    script.onload = () => window.adapterLoaded = true;
    document.head.appendChild(script);
  }});
</script>
"""

DIRECT_HTML = f"""<!doctype html>
<meta charset="utf-8">
<body style="height: 41px">
<script>
  window.syntheticResizeCount = 0;
  addEventListener('resize', (event) => {{
    if (!event.isTrusted) window.syntheticResizeCount += 1;
  }});
  window.beforeStyle = document.body.getAttribute('style');
</script>
<script src="{RESOURCE_PATH}"></script>
<script>window.adapterLoaded = true;</script>
"""


class Handler(BaseHTTPRequestHandler):
    script_requests = 0

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = self.path.partition("?")[0]
        if path == "/parent":
            content_type, body = "text/html; charset=utf-8", PARENT_HTML.encode()
        elif path == "/child":
            content_type, body = "text/html; charset=utf-8", CHILD_HTML.encode()
        elif path == "/direct":
            content_type, body = "text/html; charset=utf-8", DIRECT_HTML.encode()
        elif path == RESOURCE_PATH:
            type(self).script_requests += 1
            content_type, body = "application/javascript", SCRIPT_PATH.read_bytes()
        else:
            self.send_error(404)
            return

        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        pass


def approximately(actual: float, expected: float, tolerance: float = 2) -> None:
    assert abs(actual - expected) <= tolerance, (actual, expected)


def main() -> None:
    if not SCRIPT_PATH.is_file():
        raise FileNotFoundError(f"production JavaScript is absent: {SCRIPT_PATH}")

    Handler.script_requests = 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"

    errors: list[str] = []
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(
                viewport={"width": 1280, "height": 857}, device_scale_factor=1
            )
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))

            page.goto(f"{origin}/parent")
            page.evaluate(
                """() => {
                  const host = document.querySelector('ha-panel-app');
                  const root = host.attachShadow({mode: 'open'});
                  const frame = document.createElement('iframe');
                  frame.style.cssText = 'display:block;width:100%;height:100%;border:0';
                  frame.src = '/child';
                  root.appendChild(frame);
                }"""
            )
            page.wait_for_function(
                """() => {
                  const frame = document.querySelector('ha-panel-app').shadowRoot
                    .querySelector('iframe');
                  return frame.contentWindow.location.pathname === '/child';
                }"""
            )
            child = next(
                frame for frame in page.frames if frame.url == f"{origin}/child"
            )
            child.wait_for_function("window.adapterLoaded === true")
            page.wait_for_function(
                """() => Math.abs(
                  document.querySelector('ha-panel-app').getBoundingClientRect().height - 857
                ) <= 2"""
            )

            dimensions = page.evaluate(
                """() => {
                  const host = document.querySelector('ha-panel-app');
                  const frame = host.shadowRoot.querySelector('iframe');
                  return {
                    host: host.getBoundingClientRect().height,
                    frame: frame.getBoundingClientRect().height,
                  };
                }"""
            )
            dimensions["baseline"] = child.evaluate("window.baselineHeight")
            dimensions["child"] = child.evaluate("window.innerHeight")
            dimensions["syntheticResizes"] = child.evaluate(
                "window.syntheticResizeCount"
            )

            approximately(dimensions["baseline"], 857 * 0.4)
            approximately(dimensions["host"], 857)
            approximately(dimensions["frame"], 857)
            approximately(dimensions["child"], 857)
            assert dimensions["syntheticResizes"] == 1, dimensions
            assert page.evaluate("window.parentResizeListeners.size") == 1
            assert page.evaluate("window.activeChildObservers") == 1
            assert child.evaluate(
                """({
                  active: window.activeObserverCount,
                  created: window.createdObserverCount,
                })"""
            ) == {"active": 1, "created": 1}

            # pageshow and parent resize repair later collapses and emit one child
            # resize per real correction without registering duplicates.
            page.evaluate(
                "document.querySelector('ha-panel-app').style.height = '40vh'"
            )
            child.evaluate("dispatchEvent(new PageTransitionEvent('pageshow'))")
            page.wait_for_function(
                "document.querySelector('ha-panel-app').getBoundingClientRect().height > 850"
            )
            assert child.evaluate("window.syntheticResizeCount") == 2
            assert page.evaluate("window.parentResizeListeners.size") == 1
            assert page.evaluate("window.activeChildObservers") == 1
            assert child.evaluate("window.createdObserverCount") == 1

            page.evaluate(
                "document.querySelector('ha-panel-app').style.height = '40vh'"
            )
            page.evaluate("dispatchEvent(new Event('resize'))")
            page.wait_for_function(
                "document.querySelector('ha-panel-app').getBoundingClientRect().height > 850"
            )
            assert child.evaluate("window.syntheticResizeCount") == 3

            # A child resize with no style correction must not recurse or emit a
            # second resize.
            child.evaluate("dispatchEvent(new Event('resize'))")
            page.wait_for_timeout(100)
            assert child.evaluate("window.syntheticResizeCount") == 4

            # A real child navigation must clean the old document's parent
            # listener before the new adapter starts.
            child.goto(f"{origin}/child?reload=1")
            child.wait_for_function("window.adapterLoaded === true")
            assert page.evaluate(
                """({
                  active: window.parentResizeListeners.size,
                  adds: window.parentResizeAdds,
                  removes: window.parentResizeRemoves,
                })"""
            ) == {"active": 1, "adds": 2, "removes": 1}
            assert page.evaluate("window.activeChildObservers") == 1
            assert child.evaluate(
                """({
                  resizes: window.syntheticResizeCount,
                  active: window.activeObserverCount,
                  created: window.createdObserverCount,
                })"""
            ) == {"resizes": 0, "active": 1, "created": 1}

            # Model a BFCache freeze/restore. Cleanup disconnects the retained
            # observer and parent listener; pageshow restores each exactly once
            # and repairs a collapse while reusing the same observer.
            child.evaluate(
                "dispatchEvent(new PageTransitionEvent('pagehide', {persisted: true}))"
            )
            assert page.evaluate("window.parentResizeListeners.size") == 0
            assert page.evaluate("window.activeChildObservers") == 0
            assert child.evaluate("window.activeObserverCount") == 0
            page.evaluate(
                "document.querySelector('ha-panel-app').style.height = '40vh'"
            )
            child.evaluate(
                "dispatchEvent(new PageTransitionEvent('pageshow', {persisted: true}))"
            )
            page.wait_for_function(
                "document.querySelector('ha-panel-app').getBoundingClientRect().height > 850"
            )
            assert page.evaluate(
                """({
                  active: window.parentResizeListeners.size,
                  adds: window.parentResizeAdds,
                  removes: window.parentResizeRemoves,
                })"""
            ) == {"active": 1, "adds": 3, "removes": 2}
            assert page.evaluate("window.activeChildObservers") == 1
            assert child.evaluate(
                """({
                  resizes: window.syntheticResizeCount,
                  active: window.activeObserverCount,
                  created: window.createdObserverCount,
                })"""
            ) == {"resizes": 1, "active": 1, "created": 1}

            # Repeat a real navigation and repair to prove old registrations do
            # not accumulate across documents and the new document remains live.
            child.goto(f"{origin}/child?reload=2")
            child.wait_for_function("window.adapterLoaded === true")
            assert page.evaluate(
                """({
                  active: window.parentResizeListeners.size,
                  adds: window.parentResizeAdds,
                  removes: window.parentResizeRemoves,
                })"""
            ) == {"active": 1, "adds": 4, "removes": 3}
            assert page.evaluate("window.activeChildObservers") == 1
            assert child.evaluate("window.activeObserverCount") == 1
            page.evaluate(
                "document.querySelector('ha-panel-app').style.height = '40vh'"
            )
            child.evaluate("dispatchEvent(new Event('resize'))")
            page.wait_for_function(
                "document.querySelector('ha-panel-app').getBoundingClientRect().height > 850"
            )
            page.wait_for_timeout(100)
            assert child.evaluate("window.syntheticResizeCount") == 2

            lifecycle = page.evaluate(
                """({
                  activeParentListeners: window.parentResizeListeners.size,
                  parentListenerAdds: window.parentResizeAdds,
                  parentListenerRemoves: window.parentResizeRemoves,
                  parentTrackedObservers: window.activeChildObservers,
                })"""
            )
            lifecycle.update(
                child.evaluate(
                    """({
                      activeObservers: window.activeObserverCount,
                      createdObservers: window.createdObserverCount,
                    })"""
                )
            )

            direct = context.new_page()
            direct.on("pageerror", lambda error: errors.append(str(error)))
            direct.goto(f"{origin}/direct")
            direct.wait_for_function("window.adapterLoaded === true")
            direct_result = direct.evaluate(
                """() => ({
                  frameElement: window.frameElement,
                  beforeStyle: window.beforeStyle,
                  afterStyle: document.body.getAttribute('style'),
                  syntheticResizes: window.syntheticResizeCount,
                })"""
            )
            assert direct_result == {
                "frameElement": None,
                "beforeStyle": "height: 41px",
                "afterStyle": "height: 41px",
                "syntheticResizes": 0,
            }, direct_result
            assert Handler.script_requests == 4, Handler.script_requests
            assert errors == [], errors

            context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    print(
        json.dumps(
            {
                "baseline": round(dimensions["baseline"]),
                "corrected": {
                    "host": round(dimensions["host"]),
                    "iframe": round(dimensions["frame"]),
                    "child": round(dimensions["child"]),
                },
                "directTopLevelNoOp": True,
                "lifecycle": lifecycle,
                "pageErrors": errors,
            },
            sort_keys=True,
        )
    )
    print("ingress frame height browser test passed")


if __name__ == "__main__":
    main()

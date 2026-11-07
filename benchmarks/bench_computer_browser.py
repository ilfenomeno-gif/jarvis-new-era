"""Run the ten Phase A2 tasks against isolated local pages in real Chromium."""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import clipboard  # noqa: E402
from core.audit_log import AuditLog  # noqa: E402
from core.browser_automation import BrowserAutomation, PlaywrightBrowser  # noqa: E402
from core.computer_loop import ComputerLoop  # noqa: E402
from core.memory_store import MemoryStore  # noqa: E402

_VIDEO_HTML = """<!doctype html>
<title>Video fixture</title>
<canvas id="source" width="32" height="32"></canvas>
<video id="video" muted></video>
<script>
const canvas = document.querySelector("#source");
const context = canvas.getContext("2d");
const stream = canvas.captureStream(10);
const chunks = [];
const recorder = new MediaRecorder(stream);
recorder.ondataavailable = event => event.data.size && chunks.push(event.data);
recorder.onstop = () => {
  const video = document.querySelector("#video");
  video.src = URL.createObjectURL(new Blob(chunks, {type: recorder.mimeType}));
  video.onloadedmetadata = () => video.setAttribute("data-ready", "true");
};
recorder.start();
let frames = 0;
const draw = () => {
  context.fillStyle = frames++ % 2 ? "#123456" : "#654321";
  context.fillRect(0, 0, canvas.width, canvas.height);
};
draw();
const timer = setInterval(draw, 100);
setTimeout(() => { clearInterval(timer); recorder.stop(); }, 900);
</script>"""


def _page(title: str, body: str, script: str = "") -> str:
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        f"<title>{title}</title></head><body>{body}<script>{script}</script></body></html>"
    )


class _FixtureHandler(BaseHTTPRequestHandler):
    def log_message(self, _format, *_args):
        return

    def _send(self, body: str, status: int = 200) -> None:
        content = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self):
        route = urlsplit(self.path).path
        pages = {
            "/": _page("Jarvis Fixture Home", "<h1>Home</h1>"),
            "/form": _page(
                "Form Fixture",
                """<form id="signup" method="post" action="/form/submit">
                <input name="name"><input name="city"><button>Submit</button></form>""",
            ),
            "/click": _page(
                "Click Fixture",
                "<button>Run action</button><p id='result'></p>",
                "document.querySelector('button').onclick = () => "
                "document.querySelector('#result').textContent = 'clicked';",
            ),
            "/read": _page(
                "Read Fixture",
                "<p id='paragraph'>DOM text extraction succeeded.</p>",
            ),
            "/history": _page(
                "History Fixture",
                "<a href='/page-two'>Open second page</a>",
            ),
            "/page-two": _page("Second Fixture Page", "<p>second page</p>"),
            "/clipboard": _page(
                "Clipboard Fixture",
                "<p id='source'>clipboard-from-page</p><input id='target'>",
            ),
            "/video": _VIDEO_HTML,
            "/delayed": _page(
                "Wait Fixture",
                "<div id='delayed' hidden>Ready</div>",
                "setTimeout(() => { const el = document.querySelector('#delayed'); "
                "el.hidden = false; }, 350);",
            ),
            "/screenshot": _page("Screenshot Fixture", "<h1>Screenshot checkpoint</h1>"),
            "/cookie": _page(
                "Cookie Fixture",
                """<aside id="banner"><button>Accept cookies</button></aside>
                <button id="main">Continue</button><p id="result"></p>""",
                "document.querySelector('#banner button').onclick = () => "
                "document.querySelector('#banner').remove(); "
                "document.querySelector('#main').onclick = () => "
                "document.querySelector('#result').textContent = 'main action executed';",
            ),
        }
        self._send(pages.get(route, _page("Not found", "<p>Not found</p>")), 404 if route not in pages else 200)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        values = parse_qs(self.rfile.read(length).decode("utf-8"))
        name = values.get("name", [""])[0]
        city = values.get("city", [""])[0]
        self._send(
            _page(
                "Form Received",
                f"<h1>Received {name} from {city}</h1>",
            )
        )


class _FixtureServer:
    def __enter__(self):
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), _FixtureHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"
        return self

    def __exit__(self, *_args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=3)


class _MemoryClipboard:
    def __init__(self):
        self.value = ""

    def get(self) -> str:
        return self.value

    def set(self, text: str) -> None:
        self.value = text


def _chromium_executable() -> Path:
    configured = os.environ.get("PLAYWRIGHT_EXECUTABLE_PATH")
    if configured:
        path = Path(configured).expanduser().resolve()
        if path.is_file():
            return path
        raise RuntimeError(f"PLAYWRIGHT_EXECUTABLE_PATH does not exist: {path}")
    cache = Path.home() / "AppData" / "Local" / "ms-playwright"
    candidates = sorted(cache.glob("chromium-*/chrome-win64/chrome.exe"))
    if not candidates:
        raise RuntimeError(
            "No installed Chromium executable found. Install the Playwright browser "
            "with `python -m playwright install chromium` or set "
            "PLAYWRIGHT_EXECUTABLE_PATH."
        )
    return candidates[-1]


def _step(description: str, operation: str, **values):
    verify = values.pop("verify", {})
    return {
        "description": description,
        "action": {"type": "browser", "operation": operation, **values},
        "verify": verify,
    }


def _auto_confirm(_key, _title, _detail, run, **_kwargs):
    run()
    return "[CONFIRMATION_PENDING]"


def _plan(base: str) -> dict[str, list[dict]]:
    return {
        "1_open_read_title": [
            _step(
                "Open the home page",
                "navigate",
                url=f"{base}/",
                verify={"title_contains": "Jarvis Fixture Home"},
            ),
            _step(
                "Read the page title",
                "read_title",
                verify={"stdout_contains": "Jarvis Fixture Home"},
            ),
        ],
        "2_fill_submit_form": [
            _step("Open the form", "navigate", url=f"{base}/form"),
            _step("Fill the name", "fill", selector="input[name=name]", text="Ada"),
            _step("Fill the city", "fill", selector="input[name=city]", text="London"),
            _step(
                "Submit the local form",
                "submit_form",
                selector="form#signup",
                verify={"title_contains": "Form Received", "stdout_contains": "Submitted"},
            ),
        ],
        "3_click_named_button": [
            _step("Open the click fixture", "navigate", url=f"{base}/click"),
            _step("Click the named button", "click", text="Run action"),
            _step("Verify the click result", "read_text", selector="#result",
                  verify={"stdout_contains": "clicked"}),
        ],
        "4_extract_paragraph": [
            _step("Open the text fixture", "navigate", url=f"{base}/read"),
            _step("Read the paragraph", "read_text", selector="#paragraph",
                  verify={"stdout_contains": "DOM text extraction succeeded."}),
        ],
        "5_navigate_back": [
            _step("Open the history fixture", "navigate", url=f"{base}/history"),
            _step("Open the second page", "click", text="Open second page"),
            _step("Navigate back", "back", verify={"url_equals": f"{base}/history"}),
        ],
        "6_copy_and_paste": [
            _step("Open the clipboard fixture", "navigate", url=f"{base}/clipboard"),
            _step("Copy the selected DOM text", "copy_selection", selector="#source",
                  verify={"stdout_contains": "clipboard-from-page"}),
            _step("Paste into the field", "paste", selector="#target",
                  verify={
                      "input_selector": "#target",
                      "input_value_equals": "clipboard-from-page",
                  }),
        ],
        "7_control_video": [
            _step("Open the generated video fixture", "navigate", url=f"{base}/video"),
            _step("Wait for video metadata", "wait_for", selector="video[data-ready=true]"),
            _step("Play the HTML5 video", "video_control", selector="#video", control="play",
                  verify={"video_paused": False}),
            _step("Pause and read currentTime", "video_control", selector="#video",
                  control="pause", verify={"video_paused": True}),
        ],
        "8_wait_for_element": [
            _step("Open the delayed element fixture", "navigate", url=f"{base}/delayed"),
            _step("Wait for the delayed element", "wait_for", selector="#delayed",
                  timeout_ms=4000, verify={"selector_visible": "#delayed"}),
        ],
        "9_take_verification_screenshot": [
            _step("Open the screenshot fixture", "navigate", url=f"{base}/screenshot"),
            _step("Capture the page", "screenshot", path="screenshots/task9.png",
                  verify={"path_exists": "screenshots/task9.png"}),
        ],
        "10_close_cookie_banner": [
            _step("Open the cookie fixture", "navigate", url=f"{base}/cookie"),
            _step("Dismiss the cookie banner", "click", text="Accept cookies"),
            _step("Continue with the page", "click", text="Continue"),
            _step("Verify the main action", "read_text", selector="#result",
                  verify={"stdout_contains": "main action executed"}),
        ],
    }


def _run_task(loop, name: str, steps: list[dict], workspace: Path) -> dict:
    loop.planner = lambda *_args, planned=steps: planned
    started = time.perf_counter()
    result = loop.run(name.replace("_", " "), workspace=workspace)
    elapsed_ms = (time.perf_counter() - started) * 1000
    return {
        "task": name,
        "status": result.status,
        "success": result.status == "completed",
        "steps": len(result.steps),
        "retries": result.retry_count,
        "elapsed_ms": round(elapsed_ms, 2),
        "summary": result.summary,
        "failures": [
            {
                "attempt": item.attempt,
                "operation": item.operation,
                "verification": item.verification,
            }
            for item in result.steps
            if not item.success
        ],
        "outputs": [item.stdout for item in result.steps if item.success],
    }


def run_benchmark() -> dict:
    previous_clipboard = clipboard.set_backend(_MemoryClipboard())
    with tempfile.TemporaryDirectory(prefix="jarvis-browser-loop-") as directory:
        workspace = Path(directory).resolve()
        executable = _chromium_executable()
        browser = BrowserAutomation(
            PlaywrightBrowser(headless=True, executable_path=str(executable))
        )
        loop = ComputerLoop(
            memory_store=MemoryStore(workspace / "memory.sqlite3"),
            audit_log=AuditLog(workspace / "audit.jsonl"),
            browser_automation=browser,
            planner=lambda *_: [],
            confirmation_requester=_auto_confirm,
            timeout_seconds=30,
        )
        try:
            with _FixtureServer() as server:
                plans = _plan(server.base_url)
                results = [
                    _run_task(loop, name, steps, workspace)
                    for name, steps in plans.items()
                ]
        finally:
            browser.close()
            loop.close()
            clipboard.set_backend(previous_clipboard)

    passed = sum(item["success"] for item in results)
    return {
        "schema_version": 1,
        "browser": "Playwright Chromium headless",
        "executable": str(executable),
        "fixture": "ephemeral HTTP server bound to 127.0.0.1",
        "confirmation": "auto-accepted only for local disposable fixture clicks/submission",
        "tasks": results,
        "passed": passed,
        "total": len(results),
        "checkpoint_passed": passed >= 8,
    }


if __name__ == "__main__":
    print(json.dumps(run_benchmark(), ensure_ascii=True, indent=2))

import asyncio
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from actions.capture_and_analyze_screen import plain_speech_text
from actions.organize_chat import organize_chat
from core.tool_router import ToolRouter


def test_organize_chat_uses_recent_messages_and_returns_markdown():
    prompts = []
    summary = "**Punti chiave**\n\n- Primo punto\n- Secondo punto"
    result = organize_chat(
        {"count": 2},
        conversation_history=["User: vecchio", "Jarvis: nuovo", "User: altro"],
        conversation_summarizer=lambda prompt: prompts.append(prompt) or summary,
    )
    assert result == summary
    assert "Riassumi e organizza questa conversazione in punti chiave" in prompts[0]
    assert "vecchio" not in prompts[0]
    assert "Jarvis: nuovo" in prompts[0] and "User: altro" in prompts[0]
    assert plain_speech_text(result) == "Punti chiave. Primo punto. Secondo punto"


def test_organize_chat_empty_history_and_invalid_count():
    assert "Non ci sono" in organize_chat(
        conversation_history=[], conversation_summarizer=lambda _prompt: "no",
    )
    with pytest.raises(ValueError):
        organize_chat({"count": 41}, conversation_history=[], conversation_summarizer=lambda _prompt: "no")
    with pytest.raises(RuntimeError, match="non ha restituito"):
        organize_chat(conversation_history=["User: ciao"], conversation_summarizer=lambda _prompt: "")


@pytest.mark.parametrize("phrase", [
    "Jarvis, organizza la conversazione",
    "Jarvis, riassumi cosa abbiamo detto",
    "riassumi la chat",
])
def test_summary_routes_to_correct_tool(phrase):
    declarations = [{"name": "organize_chat"}, {"name": "quick_notes"}, {"name": "web_search"}]
    assert [item["name"] for item in ToolRouter().select_for_request(phrase, declarations)] == ["organize_chat"]


def test_plain_speech_preserves_underscores_in_filenames():
    assert plain_speech_text("**File**: mio_file.txt\n* pronto") == "File: mio_file.txt. pronto"


def test_speak_cleans_markdown_before_live_delivery():
    import main

    sent = []

    class Session:
        async def send_client_content(self, **kwargs):
            sent.append(kwargs)

    async def run():
        live = object.__new__(main.JarvisLive)
        live._loop = asyncio.get_running_loop()
        live.session = Session()
        live._set_task_idle = lambda _idle: None
        await asyncio.to_thread(live.speak, "**Titolo**\n- primo")
        for _ in range(50):
            if sent:
                break
            await asyncio.sleep(.01)

    asyncio.run(run())
    assert sent[0]["turns"]["parts"][0]["text"] == "Titolo. primo"


def test_qt_chat_renders_markdown_and_stream_without_html_injection(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    from gev_chat import GevJarvisChat

    app = QApplication.instance() or QApplication([])
    chat = GevJarvisChat()
    chat.add_message("assistant", "**Titolo**\n\n- uno\n- due\n\n<script>injected</script>")
    html = chat._transcript.toHtml()
    assert "font-weight:700" in html
    assert "<li" in html and "uno" in html and "due" in html
    assert "<script>" not in html
    chat.add_message("stream", "start\n")
    chat.add_message("stream", "append\n**Cia")
    chat.add_message("stream", "append\no**\n- fine")
    chat.add_message("stream", "end\n")
    assert "Ciao" in chat._transcript.toPlainText()
    assert chat._transcript.toPlainText().count("Ciao") == 1
    assert "fine" in chat._transcript.toPlainText()
    chat.close()
    assert app is not None


def test_hud_markdown_uses_safe_dom_nodes():
    source = (Path(__file__).resolve().parents[1] / "core" / "jarvis_hud.html").read_text(encoding="utf-8")
    function = source[source.index("function renderChatMarkdown("):source.index("window.jarvisHudMessage=")]
    script = """
class Element {
  constructor(tag) { this.tag=tag; this.children=[]; this.textContent=''; }
  replaceChildren() { this.children=[]; }
  appendChild(child) { this.children.push(child); }
}
const document={createElement: tag => new Element(tag), createTextNode: text => ({text})};
""" + function + """
const root=new Element('root');
renderChatMarkdown(root, '**Title**\\n\\n- first\\n- <img src=x>');
const assert=require('assert');
assert.equal(root.children[0].children[1].tag,'strong');
const list=root.children.find(x=>x.tag==='ul');
assert.equal(list.children.length,2);
assert.equal(list.children[1].children[0].text,'<img src=x>');
"""
    subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)


def test_summary_tool_dispatch_displays_formatted_result(monkeypatch):
    import main
    from core.action_loader import discover_actions

    registry = discover_actions(Path(main.BASE_DIR) / "actions", logger=lambda _text: None)
    live = object.__new__(main.JarvisLive)
    live._action_registry = registry
    live._brain_router = SimpleNamespace(backend="gemini")
    live._last_user_text = "organizza la conversazione"
    live._session_log = ["User: primo", "Jarvis: secondo"]
    live._asst_name = "Jarvis"
    live.ui = SimpleNamespace(muted=False, set_state=lambda _state: None, write_log=lambda _text: None)
    messages = []
    live._hud = SimpleNamespace(push_chat=lambda role, text: messages.append((role, text)))
    prompts = []
    live._summarize_chat_text = lambda prompt: prompts.append(prompt) or "**Punti**\n- primo"
    live._observe_pattern_tool_result = lambda *_args: None
    monkeypatch.setattr(main, "require_policy_file", lambda: None)
    call = SimpleNamespace(id="1", name="organize_chat", args={})

    response = asyncio.run(live._execute_tool(call))
    assert response.response["result"] == "**Punti**\n- primo"
    assert messages == [("assistant", "**Punti**\n- primo")]
    assert "User: primo" in prompts[0] and "Jarvis: secondo" in prompts[0]


def test_local_summary_displays_and_queues_speech(monkeypatch):
    import main
    from core.action_loader import discover_actions

    registry = discover_actions(Path(main.BASE_DIR) / "actions", logger=lambda _text: None)
    class Brain:
        backend = "local"

        def stream_chat(self, messages, tools=None):
            if tools is not None:
                return iter([
                    {"type": "tool_call", "name": "organize_chat", "args": {}, "id": "1"},
                    {"type": "done"},
                ])
            assert "User: precedente" in messages[0]["content"]
            return iter([{"type": "content", "text": "**Sintesi**\n- dettaglio"}, {"type": "done"}])

    live = object.__new__(main.JarvisLive)
    live._action_registry = registry
    live._plugin_registry = SimpleNamespace(get_tool_declarations=lambda: [])
    live._brain_router = Brain()
    live._tool_router = ToolRouter()
    live._local_messages = [{"role": "system", "content": "test"}]
    live._local_pending_confirmation = None
    live._local_chat_lock = asyncio.Lock()
    live._session_log = ["User: precedente", "Jarvis: risposta"]
    live._asst_name = "Jarvis"
    logs, shown, spoken, idle = [], [], [], []
    live.ui = SimpleNamespace(muted=False, set_state=lambda _state: None, write_log=logs.append)
    live._hud = SimpleNamespace(push_chat=lambda role, text: shown.append((role, text)))
    live._set_task_idle = idle.append
    live.session = object()
    live._loop = object()
    live.speak = spoken.append
    live._observe_pattern_tool_result = lambda *_args: None
    monkeypatch.setattr(main, "require_policy_file", lambda: None)

    asyncio.run(live._handle_local_text("organizza la conversazione"))
    assert shown == [("assistant", "**Sintesi**\n- dettaglio")]
    assert spoken and spoken[0].endswith("**Sintesi**\n- dettaglio")
    assert logs[-1] == "Jarvis: **Sintesi**\n- dettaglio"
    assert idle == [False]

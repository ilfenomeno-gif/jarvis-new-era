"""Keyword-based tool selection: pick which function declarations to send to Gemini.

Pure logic, no Qt and no network. The Live API takes the tool list when a session is
opened (and again on every reconnect), so this narrows what is declared at that moment;
it cannot change the list mid-session.

Rules that keep it safe:
- ALWAYS tools (quit, undo, skills) are never dropped.
- A tool that appears in no group is kept (fail-open), so a new tool is never hidden.
- Text that matches no group gets BASE, a small general-purpose set.
- Tools already used in the session are kept so a follow-up never loses them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable

ALWAYS = frozenset({"shutdown_jarvis", "undo", "use_skill"})
BASE = frozenset({"web_search", "open_app", "app_launcher", "system_status", "save_memory", "recall_memory", "ui_layout"})

_GEV_TOOLS = frozenset({"gev"})  # gev_mcp_* are matched by prefix


@dataclass(frozen=True)
class Group:
    name: str
    pattern: re.Pattern
    tools: frozenset
    prefixes: tuple = ()


def _group(name: str, keywords: str, tools: Iterable[str], prefixes: tuple = ()) -> Group:
    return Group(name, re.compile(keywords, re.IGNORECASE), frozenset(tools), prefixes)


GROUPS: tuple[Group, ...] = (
    _group("3d", r"3d|ologramm|hologram|modell|\bmodel|globo|globe|sedia|chair|esplod|explod|evidenzia|highlight|genera|generate|blueprint|materiale|material|textur|realistic|toon|flat|smonta|spiega|motore|engine|cambio|gearbox|\bpc\b|computer|guardando|che cos.{1,3}\s+quest|what is this|what am i looking|mouse|\bfly\b|cerca|trova|scarica|search|download|\bauto\b|\bcar\b|ferrari|arma|weapon|edificio|building|passo dopo passo|step by step|poi |then ",
           {"generate_3d_model", "search_3d_model", "viewer_3d", "ui_layout",
            "task_runner_start", "task_runner_status", "task_runner_cancel", "task_runner_confirm"}),
    _group("flights", r"\bvol[oi]\b|flight|aere[oi]|aircraft|\bplane|aeroport|airport|biglietto|opensky",
           {"flight_finder", "viewer_3d", "gev"}, ("gev_mcp_aircraft", "gev_mcp_find_aircraft", "gev_mcp_get_aircraft")),
    _group("gev", r"\bgev\b|god'?s eye|occhio di dio|satellit|\bnav[ei]\b|vessel|\bship|terremot|earthquake|incendi|\bfire|cicl|cyclon|telecamer|cctv|traffico|traffic|cavi sottomarin|cable|milit|datacenter|\bdig[ah]\b|\bdam\b|situazione|mappa|\bmap\b|lancio|launch|inondaz|flood|elevazione|elevation|quota|imagery|immagini satellitari",
           _GEV_TOOLS, ("gev_mcp_",)),
    _group("weather", r"meteo|weather|pioggia|piove|temperatur|forecast|previsioni|neve|vento|ombrello",
           {"weather_report", "gev_mcp_get_weather_map"}),
    _group("memory_save", r"\bmemorizza\b|\bsalva (?:in )?memoria\b|\bremember that\b",
           {"save_memory"}),
    _group("memory_recall", r"\bwhat (?:did|do) i tell you\b|\bcosa ti ho (?:detto|chiesto)\b|\bcosa ricordi di me\b|\brecall memory\b",
           {"recall_memory"}),
    _group("system_status", r"\bstato (?:del )?sistema\b|\bsystem status\b|\bcpu\b|\bram\b|\bmemoria ram\b|\butilizzo del sistema\b|\bbatteria\b|\bbattery\b|\brisorse del (?:pc|sistema)\b",
           {"system_status"}),
    _group("reminders", r"ricord|promemoria|remind|sveglia|alarm|timer|pomodoro|appuntament|calendar|agenda|\bnot[ae]\b|\bnotes?\b|evento",
           {"reminder", "calendar_agenda", "pomodoro_timer", "quick_notes"}),
    _group("messaging", r"messagg|whatsapp|telegram|\bsms\b|message|scrivi a|\binvia|\bmail|email|gmail",
           {"send_message", "connector_call", "connectors_status"}),
    _group("connectors", r"github|gmail|connett|connector|drive|\bissue|pull request|\bpr\b",
           {"connector_call", "connectors_status"}),
    _group("files", r"\bfile|cartell|folder|document|\bpdf|excel|\bword\b|\btxt\b|copia|sposta|elimin|rinomin|appunti|clipboard|cestino|scarica|download|riassum|leggi il",
           {"file_controller", "large_file_reader", "file_processor", "clipboard_manager", "gestisci_testo"}),
    _group("desktop", r"computer use|computer input|usa il computer|clicc|click|digita|scrivi|\btype\b|\btast|\bpress|volume|luminos|brightness|wifi|bluetooth|monitor|desktop|mouse|schermata|finestra|window|scorciatoi|shortcut|gesti|\bmano\b",
           {"desktop_control", "computer_control", "press_key", "computer_settings", "manage_monitor",
            "accessibility_read_screen", "ada_computer_use", "automation_shortcuts",
            "computer_input"}),
    _group("vision", r"ocr|uia|accessibilit|cattura|cambiamento sullo schermo|screen change|schermo|screen|camera|webcam|guarda|\bvedi|\blook|foto|immagine|screenshot|cosa c'?è",
           {"screen_process", "close_camera", "accessibility_read_screen",
            "computer_perception"}),
    _group("browser", r"browser|pagina|\bsito|\bsite|\bweb\b|\burl\b|http|www|google|chrome|edge|youtube|video|netflix|prime|scheda|\btab\b|leggi|cerca|search",
           {"browser_control", "read_active_page", "read_page", "stop_reading", "open_website", "click_link",
            "youtube_video", "streaming_services", "web_search"}),
    _group("code", r"codice|\bcode\b|vscode|programm|script|\bbug|debug|python|funzion|repository|\brepo\b|\bgit\b|commit|svilupp|ricerc|research|\bcad\b|openscad|stampa 3d",
           {"vscode_agent", "vscode_control", "vscode_web", "code_helper", "dev_agent", "coder_agent", "debugger_agent",
            "supervisor_agent", "research_agent", "ada_cad_printer", "llm_api_bridge"}),
    _group("home", r"\bluce\b|\bluci\b|lampad|\bpresa\b|termostat|\bcasa\b|smart|kasa|\blight",
           {"kasa_smart_home", "smart_device_control"}),
    _group("music", r"spotify|music|canzon|\bplay\b|pausa|brano|playlist|album",
           {"spotify_music_control", "streaming_services"}),
    _group("utility", r"calcol|quanto fa|convert|password|\bqr\b|calori|\bpasto|\bchat\b",
           {"calculator", "password_generator", "qr_code_generator", "calorie_counter", "gemini_chat"}),
    _group("proxy", r"proxy|\bvpn\b", {"proxy_launcher"}),
    _group("applications", r"\b(apri|aprimi|avvia|avvii|lancia|launch|open|start)\b",
           {"app_launcher"}),
    _group("terminal", r"\bterminal(?:e)?\b|\bcomando shell\b|\besegui (?:il )?comando\b|\brun (?:the )?command\b",
           {"terminal_run"}),
    _group("agent", r"\b(?:fai|compila|esegui|automatizza|agent|loop|obiettivo)\b",
           {"agent_loop"}),
    _group("games", r"gioc|\bgame|steam|\bepic\b", {"game_updater"}),
    _group("ui", r"pannell|panel|layout|focus|\bdock|workspace|nascondi|\bhide|mostra|\bshow|\blog\b|interfaccia|chiudi il|apri il",
           {"ui_layout"}),
)


class ToolRouter:
    def __init__(self, groups: tuple[Group, ...] = GROUPS, always: frozenset = ALWAYS, base: frozenset = BASE):
        self._groups = groups
        self._always = always
        self._base = base

    def mapped(self, name: str) -> bool:
        """True when a tool is covered by ALWAYS, BASE or a group; unmapped tools are always sent."""
        if name in self._always or name in self._base:
            return True
        return any(name in g.tools or name.startswith(g.prefixes) for g in self._groups if g.prefixes or g.tools)

    def matched_groups(self, text: str) -> list[str]:
        return [g.name for g in self._matched_groups(text or "")]

    def _matched_groups(self, text: str) -> list[Group]:
        hits = [group for group in self._groups if group.pattern.search(text)]
        terminal_request = re.search(
            r"\bterminal(?:e)?\b|\bcomando shell\b|"
            r"\besegui (?:il )?comando\b|\brun (?:the )?command\b",
            text,
            re.IGNORECASE,
        )
        explicit_agent_request = re.search(
            r"\b(?:fai|compila|automatizza|agent|loop|obiettivo)\b",
            text,
            re.IGNORECASE,
        )
        if terminal_request and not explicit_agent_request:
            hits = [group for group in hits if group.name != "agent"]
        return hits

    def select(self, text: str, declarations: list[dict], used: Iterable[str] = ()) -> list[dict]:
        names = set(self._always) | set(used)
        hits = self._matched_groups(text or "")
        if not hits:
            names |= self._base
        keep_all_prefixes: list[str] = []
        for g in hits:
            names |= g.tools
            keep_all_prefixes.extend(g.prefixes)
        prefixes = tuple(keep_all_prefixes)
        selected = []
        for decl in declarations:
            name = decl["name"]
            if name in names or (prefixes and name.startswith(prefixes)) or not self.mapped(name):
                selected.append(decl)
        return selected

    def select_for_request(self, text: str, declarations: list[dict]) -> list[dict]:
        """Return only tools explicitly mapped to this request, without session defaults."""
        routing_text = text or ""
        opening_app = re.search(
            r"\b(?:apri|aprimi|avvia|avvii|lancia|launch|open|start)\b",
            routing_text,
            re.I,
        )
        notepad_target = re.search(r"\b(?:blocco note|notepad)\b", routing_text, re.I)
        if opening_app and notepad_target:
            routing_text = re.sub(r"\b(?:blocco note|notepad)\b", " ", routing_text, flags=re.I)
            hits = [
                group
                for group in self._matched_groups(routing_text)
                if group.name != "ui" and group.pattern.search(routing_text)
            ]
        else:
            hits = self._matched_groups(routing_text)
        if not hits:
            return []

        names = set().union(*(group.tools for group in hits))
        prefixes = tuple(prefix for group in hits for prefix in group.prefixes)
        return [
            declaration
            for declaration in declarations
            if declaration["name"] in names
            or (prefixes and declaration["name"].startswith(prefixes))
        ]

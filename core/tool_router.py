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
from collections.abc import Iterable
from dataclasses import dataclass

ALWAYS = frozenset({"shutdown_jarvis", "undo", "use_skill"})
BASE = frozenset({"web_search", "open_app", "app_launcher", "system_status", "save_memory", "recall_memory", "ui_layout"})
HIDDEN_TOOLS = frozenset({"screen_process"})

_GEV_TOOLS = frozenset({"gev"})  # gev_mcp_* are matched by prefix

_CONNECTOR_CONNECT_VERB = re.compile(
    r"\b(?:connetti|collega|accedi|connect|link|sign\s+in|log\s*in)\b",
    re.IGNORECASE,
)
_CONNECTOR_ALIASES = {
    "github": ("git hub", "github.com"),
    "spotify": ("spotify",),
    "google-workspace": ("google", "google workspace", "gmail", "google drive"),
    "public-apis": ("public apis", "public apis catalog", "catalogo api"),
    "n8n": ("n8n",),
    "canva": ("canva",),
    "higgsfield": ("higgsfield",),
}

_SCREEN_ANALYSIS_REQUEST = re.compile(
    r"\b(?:cosa\s+c['’]?è\s+(?:sullo\s+schermo|a\s+schermo)|"
    r"cosa\s+vedi(?:\s+(?:sullo\s+schermo|a\s+schermo))?|"
    r"cosa\s+c['’]?è\s+qui|"
    r"usa\s+(?:google\s+)?lens|google\s+lens|"
    r"analizza(?:\s+questa)?\s+(?:schermata|immagine)|"
    r"amplifica(?:\s+la)?\s+schermata)\b",
    re.IGNORECASE,
)
_PAGE_READING_REQUEST = re.compile(
    r"\bleggi(?:\s+questa|\s+la)?\s+pagina\b", re.IGNORECASE,
)
_BROWSER_INTERACTION_REQUEST = re.compile(
    r"\b(?:clicca|clic|click|apri|open|segui|follow|premi|press)\b.*"
    r"\b(?:link|collegamento|pulsante|button)\b|"
    r"\b(?:link|collegamento|pulsante|button)\b.*"
    r"\b(?:clicca|clic|click|apri|open|segui|follow|premi|press)\b",
    re.IGNORECASE,
)
_LOCAL_OCR_REQUEST = re.compile(
    r"\b(?:ocr|riconoscimento\s+testo\s+locale|"
    r"senza\s+(?:inviare|mandare)\s+(?:lo\s+)?screenshot|"
    r"senza\s+cloud)\b",
    re.IGNORECASE,
)


def is_connector_connection_request(text: str) -> bool:
    return bool(_CONNECTOR_CONNECT_VERB.search(text or ""))


def connector_connection_id(
    text: str,
    connectors: Iterable[dict],
) -> str | None:
    """Resolve an explicit connect command to exactly one registered service."""
    if not is_connector_connection_request(text):
        return None
    normalized_text = re.sub(r"[^a-z0-9]+", " ", (text or "").casefold()).strip()
    matches: set[str] = set()
    for connector in connectors:
        connector_id = str(connector.get("id", "")).strip()
        if not connector_id:
            continue
        aliases = [
            connector_id.replace("-", " "),
            str(connector.get("name", "")),
            *_CONNECTOR_ALIASES.get(connector_id.casefold(), ()),
        ]
        for alias in aliases:
            normalized_alias = re.sub(r"[^a-z0-9]+", " ", alias.casefold()).strip()
            if normalized_alias and re.search(
                rf"(?<![a-z0-9]){re.escape(normalized_alias)}(?![a-z0-9])",
                normalized_text,
            ):
                matches.add(connector_id)
                break
    return next(iter(matches)) if len(matches) == 1 else None


@dataclass(frozen=True)
class Group:
    name: str
    pattern: re.Pattern
    tools: frozenset
    prefixes: tuple = ()


def _group(name: str, keywords: str, tools: Iterable[str], prefixes: tuple = ()) -> Group:
    return Group(name, re.compile(keywords, re.IGNORECASE), frozenset(tools), prefixes)


GROUPS: tuple[Group, ...] = (
    _group("chromium_errors", r"\b(?:errori|log)\b.*\bchromium\b|\bchromium\b.*\b(?:errori|log)\b",
           {"read_chromium_errors"}),
    _group("diagnostic_report", r"\breport\s+(?:del|di|dello)\s+sistema\b|\b(?:che|quali)\s+errori\b|\bcheck[ -]?up\b",
           {"diagnostic_report"}),
    _group("symbiosis_pulse", r"\b(?:cpu|ram|processore|memoria ram|disco|batteria|gpu|temperatura|hardware|prestazioni|velocità rete)\b",
           {"system_pulse", "check_system", "check_cpu", "check_ram", "check_disk",
            "check_battery", "check_gpu", "check_network_speed", "check_temperature"}),
    _group("symbiosis_process", r"\b(?:process[oi]|processes|zombie|consumo cpu|consumo ram)\b",
           {"list_processes", "kill_process", "restart_process", "find_zombies",
            "top_ram_processes", "top_cpu_processes", "monitor_hogs", "find_suspicious"}),
    _group("symbiosis_clipboard", r"\b(?:appunti|clipboard|incolla)\b",
           {"get_last_clipboard", "paste_last_clipboard", "search_clipboard",
            "list_clipboard_history", "clear_clipboard_history"}),
    _group("symbiosis_network", r"\b(?:wifi|wi-fi|rete|firewall|vpn|indirizzo ip|porte aperte|ping|network)\b",
           {"check_wifi", "check_public_ip", "check_vpn", "check_firewall",
            "list_open_ports", "list_network_devices", "speed_test", "network_security"}),
    _group("symbiosis_monitor", r"\b(?:monitor|scherm[oi]|finestr[ae]|layout|affianca|scambia|sostituisciti)\b|"
           r"\bsposta\s+jarvis\b.*\b(?:destra|sinistra)\b",
           {"get_active_monitor", "list_monitors", "move_window_to_monitor",
            "arrange_windows", "save_layout", "restore_layout", "swap_active_window"}),
    _group(
        "terminal_app_launch",
        r"\b(?:apri|aprimi|avvia|lancia|open|start)\b.*"
        r"\b(?:tramite|attraverso|dal|con|via)\s+(?:il\s+)?(?:terminale|terminal|cmd)\b|"
        r"\b(?:esegui|lancia|run)\b.*\b(?:per|to)\s+(?:aprire|avviare|open|launch)\b",
        {"open_app_via_terminal"},
    ),
    _group(
        "organize_chat",
        r"\b(?:organizza|riassumi)\b.*\b(?:conversazione|chat|dialogo|"
        r"cosa\s+(?:abbiamo|ci siamo)\s+detto|quello\s+che\s+(?:abbiamo|ci siamo)\s+detto)\b",
        {"organize_chat"},
    ),
    _group(
        "notes_save",
        r"\b(?:prendi|prenda|prendimi|scrivi|salva)\s+(?:un[oa]?\s+)?(?:appunto|nota)\b|"
        r"\bsegna\s+che\b",
        {"save_note"},
    ),
    _group(
        "notes_list",
        r"\b(?:mostra(?:mi)?|elenca|leggi|cerca|trova|quali sono)\b.*"
        r"\b(?:appunt[oi]|not[ae])\b",
        {"list_notes"},
    ),
    _group(
        "notes_export",
        r"\b(?:stacca|esporta)\b.*\b(?:appunt[oi]|not[ae]|categoria)\b",
        {"list_notes", "export_note_to_file"},
    ),
    _group(
        "notes_delete",
        r"\b(?:cancella|elimina|rimuovi)\b.*\b(?:appunt[oi]|not[ae])\b",
        {"list_notes", "delete_note"},
    ),
    _group(
        "screen_analysis",
        _SCREEN_ANALYSIS_REQUEST.pattern + "|" + _PAGE_READING_REQUEST.pattern,
        {"capture_and_analyze_screen"},
    ),
    _group(
        "local_ocr",
        _LOCAL_OCR_REQUEST.pattern,
        {
            "accessibility_read_screen",
            "computer_perception",
            "computer_read_screen",
        },
    ),
    _group(
        "connector_connect",
        r"\b(?:connetti|collega|accedi|connect|link|sign\s+in|log\s*in)\b"
        r".*\b(?:github|spotify|google|gmail|drive|canva|higgsfield|n8n|"
        r"public[- ]?apis)\b",
        {"connect_service"},
    ),
    _group(
        "github_user_repositories",
        r"\b(?:github|git hub)\b.*\b(?:miei?\s+repo(?:sitory)?|"
        r"repo(?:sitory)?\s+ho|repo(?:sitory)?\s+possiedo|"
        r"repository\s+di\s+mia\s+propriet[aà])\b|"
        r"\b(?:quanti|elenca|mostra|lista)\b.*\b(?:miei?\s+repo(?:sitory)?|"
        r"repo(?:sitory)?\s+ho)\b",
        {"github_user_repositories"},
    ),
    _group(
        "github_repository_search",
        r"\b(?:cerca|ricerca|trova|search|find)\b.*"
        r"\b(?:repo(?:sitory)?|repositories)\b|"
        r"\b(?:repo(?:sitory)?|repositories)\b.*"
        r"\b(?:cerca|ricerca|trova|search|find)\b",
        {"github_search_repositories"},
    ),
    _group(
        "knowledge_research",
        r"\b(?:storia|storico|storica|chi\s+era|"
        r"quando\s+è\s+avvenut[oa])\b|"
        r"\braccontami\b.*\bstoria\b",
        {"web_search"},
    ),
    _group("3d", r"3d|ologramm|hologram|modell|\bmodel|globo|globe|sedia|chair|esplod|explod|evidenzia|highlight|genera|generate|blueprint|materiale|material|textur|realistic|toon|flat|smonta|spiega|motore|engine|cambio|gearbox|\bpc\b|computer|guardando|che cos.{1,3}\s+quest|what is this|what am i looking|mouse|\bfly\b|cerca|trova|scarica|search|download|\bauto\b|\bcar\b|ferrari|arma|weapon|edificio|building|passo dopo passo|step by step|poi |then ",
           {"generate_3d_model", "search_3d_model", "viewer_3d", "ui_layout",
            "task_runner_start", "task_runner_status", "task_runner_cancel", "task_runner_confirm"}),
    _group("flights", r"\bvol[oi]\b|flight|aere[oi]|aircraft|\bplane|aeroport|airport|biglietto|opensky",
           {"flight_finder", "viewer_3d", "gev"}, ("gev_mcp_aircraft", "gev_mcp_find_aircraft", "gev_mcp_get_aircraft")),
    _group("gev", r"\bgev\b|god'?s eye|occhio di dio|satellit|\bnav[ei]\b|vessel|\bship|terremot|earthquake|incendi|\bfire|cicl|cyclon|telecamer|cctv|traffico|traffic|cavi sottomarin|cable|milit|datacenter|\bdig[ah]\b|\bdam\b|situazione|mappa|\bmap\b|lancio|launch|inondaz|flood|elevazione|elevation|quota|imagery|immagini satellitari",
           _GEV_TOOLS, ("gev_mcp_",)),
    _group("weather", r"meteo|weather|pioggia|piove|temperatur|forecast|previsioni|neve|vento|ombrello",
           {"weather_report", "gev_mcp_get_weather_map", "schedule_task"}),
    _group("briefing", r"briefing|rassegna|notizie.*mattin",
           {"morning_briefing", "schedule_task"}),
    _group("public_apis", r"\bpublic[- ]?apis\b|\bapi\b|\bapis\b|catalogo\s+(?:di\s+)?api|api\s+(?:gratuit|free|senza autenticazione|senza auth|no auth|meteo|weather|finanz|finance)",
           {"search_public_apis", "get_public_api_details", "filter_apis_by_auth"}),
    _group("memory_save", r"\bmemorizza\b|\bsalva (?:in )?memoria\b|\bremember that\b|\bricorda che\b",
           {"save_memory", "save_preference"}),
    _group("memory_recall", r"\bwhat (?:did|do) i tell you\b|\bcosa ti ho (?:detto|chiesto)\b|\bcosa ricordi di me\b|\brecall memory\b",
           {"recall_memory"}),
    _group("system_status", r"\bstato (?:del )?sistema\b|\bsystem status\b|\bcpu\b|\bram\b|\bmemoria ram\b|\butilizzo del sistema\b|\bbatteria\b|\bbattery\b|\brisorse del (?:pc|sistema)\b",
           {"system_status"}),
    _group("context", r"cosa sto facendo|che cosa sto facendo|contesto attuale|what am i doing|current context|"
           r"\bqual[ei]\s+(?:app|applicazione|programma)\s+(?:sto usando|uso|ho aperto)\b",
           {"check_context"}),
    _group("reminders", r"ricord|promemoria|remind|sveglia|alarm|timer|pomodoro|appuntament|calendar|agenda|\bnot[ae]\b|\bnotes?\b|evento",
           {"reminder", "calendar_agenda", "pomodoro_timer", "quick_notes", "schedule_task"}),
    _group("messaging", r"messagg|whatsapp|telegram|\bsms\b|message|scrivi a|\binvia|\bmail|email|gmail",
           {"send_message", "connector_call", "connectors_status"}),
    _group("connectors", r"github|gmail|connett|connector|drive|\bissue|pull request|\bpr\b|\bn8n\b|workflow|automatizza|automazione|integrazione",
           {"connector_call", "connectors_status", "n8n_bridge"}),
    _group("files", r"\bfile|cartell|folder|document|\bpdf|excel|\bword\b|\btxt\b|copia|sposta|elimin|rinomin|appunti|clipboard|cestino|scarica|download|riassum|leggi il",
           {"file_controller", "large_file_reader", "file_processor", "clipboard_manager", "gestisci_testo", "deck_pipeline", "workspace_reader"}),
    _group("desktop", r"computer use|computer input|computer stop|stop computer|computer pause|pause computer|computer screenshot|usa il computer|clicc|click|digita|scrivi|\btype\b|\btast|\bpress|volume|luminos|brightness|wifi|bluetooth|monitor|desktop|mouse|schermata|finestra|window|scorciatoi|shortcut|gesti|\bmano\b",
           {"desktop_control", "computer_control", "press_key", "computer_settings", "manage_monitor",
            "accessibility_read_screen", "ada_computer_use", "automation_shortcuts",
            "computer_input", "computer_task", "computer_screenshot", "computer_click",
            "computer_type", "computer_move", "computer_key", "computer_stop",
            "computer_use_loop"}),
    _group("vision", r"ocr|uia|accessibilit|cattura|cambiamento sullo schermo|screen change|schermo|screen|camera|webcam|guarda|\bvedi|\blook|foto|immagine|screenshot|cosa c'?è",
           {"close_camera", "accessibility_read_screen",
            "computer_perception", "computer_read_screen", "computer_task",
            "computer_screenshot"}),
    _group("browser", r"browser|pagina|\bsito|\bsite|\bweb\b|\burl\b|http|www|google|chrome|edge|youtube|video|netflix|prime|scheda|\btab\b|leggi|cerca|search",
           {"browser_control", "read_active_page", "read_page", "stop_reading", "open_website", "click_link",
                "youtube_video", "streaming_services", "web_search", "browser_automation", "computer_task"}),
    _group("fables", r"\bfables(?:\.gg)?\b|play\.fables\.gg|friends\s*(?:&|and)\s*fables",
           {"fables_workflow", "supervisor_agent", "research_agent",
                "debugger_agent", "browser_automation"}),
    _group("code", r"codice|\bcode\b|vscode|programm|script|\bbug|debug|python|funzion|repository|\brepo\b|\bgit\b|commit|svilupp|ricerc|research|\bcad\b|openscad|stampa 3d",
           {"vscode_agent", "vscode_control", "vscode_web", "code_helper", "dev_agent", "coder_agent", "debugger_agent", "file_processor",
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
    _group("terminal", r"\bterminal(?:e)?\b|\bcomando shell\b|\besegui (?:il )?comando\b|\besegui\s+ipconfig\b|\brun (?:the )?command\b",
           {"terminal_run", "terminal_exec"}),
    _group("terminal_open", r"\b(?:apri|aprimi|avvia|lancia|open|start)\s+(?:il\s+)?(?:terminale|terminal|cmd|prompt dei comandi)\b",
           {"terminal_open", "terminal_open_ext"}),
    _group("chatbot", r"\bchatbot\b|chat\s*bot|pianifica(?:re)?\s+(?:i\s+)?contenuti|plan\s+content",
           {"chatbot_plan"}),
    _group("agent", r"\b(?:fai|compila|esegui|automatizza|agent|loop|obiettivo)\b",
           {"agent_loop"}),
    _group("games", r"gioc|\bgame|steam|\bepic\b", {"game_updater", "subway_surfer"}),
    _group("ui", r"pannell|panel|layout|focus|\bdock|workspace|nascondi|\bhide|mostra|\bshow|\blog\b|interfaccia|chiudi il|apri il",
           {"ui_layout", "interface_studio"}),
    _group("hud_map", r"\bhud\b|mappa 3d|\bmappa\b|pianet|sistema solare|\btour\b|scenario|apri (?:il )?sistema|mostra (?:il )?(?:sistema|modulo|pianeta)",
           {"hud_control"}),
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
        if any(group.name == "terminal_app_launch" for group in hits):
            return [group for group in hits if group.name == "terminal_app_launch"]
        if any(group.name == "organize_chat" for group in hits):
            return [group for group in hits if group.name == "organize_chat"]
        note_hits = [group for group in hits if group.name.startswith("notes_")]
        if note_hits:
            return note_hits
        explicit_browser_interaction = (
            _PAGE_READING_REQUEST.search(text) and _BROWSER_INTERACTION_REQUEST.search(text)
        )
        screen_request = _SCREEN_ANALYSIS_REQUEST.search(text) or (
            _PAGE_READING_REQUEST.search(text) and not explicit_browser_interaction
        )
        if screen_request and not _LOCAL_OCR_REQUEST.search(text):
            return [group for group in hits if group.name == "screen_analysis"]
        if _LOCAL_OCR_REQUEST.search(text):
            return [group for group in hits if group.name == "local_ocr"]
        if explicit_browser_interaction:
            hits = [group for group in hits if group.name != "screen_analysis"]
        if any(group.name == "connector_connect" for group in hits):
            return [group for group in hits if group.name == "connector_connect"]
        if any(group.name == "github_user_repositories" for group in hits):
            return [group for group in hits if group.name == "github_user_repositories"]
        if any(group.name == "github_repository_search" for group in hits):
            return [group for group in hits if group.name == "github_repository_search"]
        if any(group.name == "knowledge_research" for group in hits):
            return [group for group in hits if group.name == "knowledge_research"]
        if any(group.name == "fables" for group in hits):
            hits = [group for group in hits if group.name != "browser"]
        terminal_request = re.search(
            r"\bterminal(?:e)?\b|\bcomando shell\b|"
            r"\besegui (?:il )?comando\b|\besegui\s+ipconfig\b|\brun (?:the )?command\b",
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
            if name in HIDDEN_TOOLS:
                continue
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
        if opening_app and notepad_target and not any(
            group.name == "terminal_app_launch" for group in self._matched_groups(routing_text)
        ):
            routing_text = re.sub(r"\b(?:blocco note|notepad)\b", " ", routing_text, flags=re.I)
            hits = [
                group
                for group in self._matched_groups(routing_text)
                if group.name != "ui" and group.pattern.search(routing_text)
            ]
        else:
            hits = self._matched_groups(routing_text)
        if any(group.name == "fables" for group in hits):
            hits = [
                group
                for group in hits
                if group.name != "browser"
            ]
        if re.search(
            r"\b(?:mappa\s+(?:dei\s+moduli|la\s+cartella)|cerca\s+nella\s+cartella|"
            r"workspace\s+map|folder\s+map)\b",
            routing_text,
            re.IGNORECASE,
        ):
            hits = [group for group in hits if group.name == "files"]
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

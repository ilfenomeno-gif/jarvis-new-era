"""Staged, approval-gated presentation production with role-isolated workers."""
from __future__ import annotations

import concurrent.futures
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

MAX_PARALLEL = 20
MIN_SOURCES_PER_SLIDE = 3
MAX_SLIDES = 30

# Every role has an explicit model assignment. No model-ladder fallback is used.
ROLE_MODELS = {
    role: os.environ.get(f"JARVIS_DECK_MODEL_{role.upper()}", "gemini-flash-latest")
    for role in ("brief", "research", "outline", "slide", "visual_qa", "critic")
}

_SLIDE_SCHEMA = {
    "type": "object",
    "required": ["title", "takeaway", "bullets", "source_urls"],
    "properties": {
        "title": {"type": "string"},
        "takeaway": {"type": "string"},
        "bullets": {"type": "array", "items": {"type": "string"}},
        "source_urls": {"type": "array", "items": {"type": "string"}},
    },
}


def history_root() -> Path:
    configured = os.environ.get("JARVIS_DECK_HISTORY")
    return Path(configured).expanduser() if configured else Path.home() / ".jarvis" / "deck_history"


def _default_agent_call(role: str, prompt: str) -> str:
    from core.api_keys import gemini_api_key
    from google import genai

    base_dir = Path(__file__).resolve().parents[1]
    key = gemini_api_key(base_dir / "config")
    if not key:
        raise RuntimeError("The Gemini API key is not configured in the protected SecretStore.")
    model = ROLE_MODELS[role]
    response = genai.Client(api_key=key).models.generate_content(
        model=model,
        contents=prompt,
    )
    text = getattr(response, "text", None)
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError(f"The {role} agent ({model}) returned an empty response.")
    return text.strip()


def _default_vision_call(role: str, prompt: str, image_path: Path) -> str:
    from core.api_keys import gemini_api_key
    from google import genai
    from google.genai import types

    base_dir = Path(__file__).resolve().parents[1]
    key = gemini_api_key(base_dir / "config")
    if not key:
        raise RuntimeError("The Gemini API key is not configured in the protected SecretStore.")
    model = ROLE_MODELS[role]
    image = types.Part.from_bytes(
        data=image_path.read_bytes(),
        mime_type="image/png",
    )
    response = genai.Client(api_key=key).models.generate_content(
        model=model,
        contents=[prompt, image],
    )
    text = getattr(response, "text", None)
    if not isinstance(text, str) or not text.strip():
        raise RuntimeError(f"The {role} agent ({model}) returned an empty response.")
    return text.strip()


def _parse_json(value: Any, role: str) -> dict[str, Any]:
    if isinstance(value, dict):
        parsed = value
    elif isinstance(value, str):
        text = value.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{role} agent did not return valid JSON.") from exc
    else:
        raise ValueError(f"{role} agent output must be a JSON object.")
    if not isinstance(parsed, dict):
        raise ValueError(f"{role} agent output must be a JSON object.")
    return parsed


def _default_search(topic: str) -> list[dict[str, str]]:
    from actions.web_search import _ddg_search

    return _ddg_search(topic, max_results=8)


def _safe_text(value: Any, field: str, *, max_length: int = 500) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > max_length:
        raise ValueError(f"{field} must contain 1-{max_length} characters.")
    return value.strip()


def _require_single_sentence(value: str, field: str) -> str:
    sentences = [part for part in re.split(r"(?<=[.!?])\s+", value) if part.strip()]
    if len(sentences) != 1:
        raise ValueError(f"{field} must express exactly one sentence.")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False
    ) as stream:
        temp_path = Path(stream.name)
        json.dump(value, stream, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)


def _project_path(root: Path, project_id: str) -> Path:
    if not re.fullmatch(r"[a-f0-9]{32}", project_id or ""):
        raise ValueError("project_id is invalid.")
    path = (root / project_id).resolve()
    if path.parent != root.resolve():
        raise ValueError("project_id resolves outside the deck history.")
    return path


def _load_project(root: Path, project_id: str | None = None) -> tuple[Path, dict[str, Any]]:
    root = root.resolve()
    if not project_id:
        latest = root / "latest.json"
        if not latest.is_file():
            raise ValueError("No presentation project is waiting for an action.")
        project_id = json.loads(latest.read_text(encoding="utf-8")).get("project_id")
    path = _project_path(root, str(project_id))
    state_path = path / "state.json"
    if not state_path.is_file():
        raise ValueError("The presentation project state is missing.")
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if state.get("project_id") != project_id:
        raise ValueError("The presentation project state does not match its ID.")
    return path, state


def _save_state(path: Path, state: dict[str, Any], root: Path) -> None:
    _write_json(path / "state.json", state)
    _write_json(root / "latest.json", {"project_id": state["project_id"]})


def _write_brief(path: Path, brief: dict[str, Any]) -> None:
    topics = "\n".join(f"- {topic}" for topic in brief["research_topics"])
    constraints = "\n".join(f"- {item}" for item in brief["constraints"]) or "- Nessun vincolo aggiuntivo"
    text = (
        f"# Brief: {brief['title']}\n\n"
        f"- **Pubblico:** {brief['audience']}\n"
        f"- **Obiettivo verificabile:** {brief['objective']}\n"
        f"- **Tono:** {brief['tone']}\n"
        f"- **Budget slide:** {brief['slide_count']}\n\n"
        f"## Vincoli\n{constraints}\n\n## Sotto-temi di ricerca\n{topics}\n"
    )
    (path / "brief.md").write_text(text, encoding="utf-8")


def _validate_brief(value: dict[str, Any], slide_budget: int) -> dict[str, Any]:
    topics = value.get("research_topics")
    constraints = value.get("constraints", [])
    if not isinstance(topics, list) or not 1 <= len(topics) <= MAX_PARALLEL:
        raise ValueError("Brief Analyst must return 1-20 research topics.")
    if not isinstance(constraints, list) or any(not isinstance(item, str) for item in constraints):
        raise ValueError("Brief Analyst constraints must be a list of strings.")
    return {
        "title": _safe_text(value.get("title"), "brief.title", max_length=140),
        "audience": _safe_text(value.get("audience"), "brief.audience", max_length=160),
        "objective": _require_single_sentence(
            _safe_text(value.get("objective"), "brief.objective", max_length=300),
            "brief.objective",
        ),
        "tone": _safe_text(value.get("tone"), "brief.tone", max_length=100),
        "slide_count": slide_budget,
        "constraints": [_safe_text(item, "brief.constraint", max_length=200) for item in constraints[:20]],
        "research_topics": [_safe_text(item, "brief.research_topic", max_length=180) for item in topics],
    }


def _create_brief(
    request: str,
    audience: str,
    slide_budget: int,
    agent_call: Callable[[str, str], Any],
) -> dict[str, Any]:
    prompt = (
        "RUOLO: Brief Analyst. Trasforma la richiesta grezza nel brief editoriale "
        "di una presentazione. Obiettivo in UNA frase verificabile, pubblico, tono, "
        "vincoli e sotto-temi distinti da ricercare. Non inventare dati.\n"
        f"Richiesta: {request}\nPubblico richiesto: {audience or 'deduci dalla richiesta'}\n"
        f"Numero slide richiesto: {slide_budget}\n"
        "Rispondi SOLO JSON con title, audience, objective, tone, constraints (array) "
        "e research_topics (array di 1-20 stringhe)."
    )
    return _validate_brief(_parse_json(agent_call("brief", prompt), "Brief Analyst"), slide_budget)


def _collect_research(
    path: Path,
    brief: dict[str, Any],
    agent_call: Callable[[str, str], Any],
    search_fn: Callable[[str], list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    def research_one(index_topic: tuple[int, str]) -> dict[str, Any]:
        index, topic = index_topic
        results = search_fn(topic)
        unique: dict[str, dict[str, str]] = {}
        for item in results:
            if not isinstance(item, dict):
                continue
            url = item.get("url")
            title = item.get("title")
            snippet = item.get("snippet")
            if (
                isinstance(url, str)
                and url.startswith(("https://", "http://"))
                and isinstance(title, str)
                and isinstance(snippet, str)
            ):
                unique[url] = {"url": url, "title": title[:240], "snippet": snippet[:1200]}
        sources = list(unique.values())[:8]
        if len(sources) < MIN_SOURCES_PER_SLIDE:
            raise RuntimeError(
                f"Research Agent '{topic}' found {len(sources)} usable sources; "
                f"at least {MIN_SOURCES_PER_SLIDE} are required."
            )
        prompt = (
            "RUOLO: Research Agent. Sintetizza i risultati forniti, separando fatti "
            "verificati da limiti/incertezze. Usa solo queste fonti e conserva gli URL.\n"
            f"Sotto-tema: {topic}\nFonti: {json.dumps(sources, ensure_ascii=False)}\n"
            "Rispondi in Markdown conciso con fatti, incertezze e riferimenti."
        )
        summary = agent_call("research", prompt)
        if not isinstance(summary, str) or not summary.strip():
            raise RuntimeError(f"Research Agent '{topic}' returned an empty summary.")
        result = {"topic": topic, "summary": summary.strip(), "sources": sources}
        (path / "research").mkdir(parents=True, exist_ok=True)
        (path / "research" / f"research-{index + 1}.md").write_text(
            f"# Research: {topic}\n\n{summary.strip()}\n\n"
            + "\n".join(f"- [{s['title']}]({s['url']})" for s in sources),
            encoding="utf-8",
        )
        return result

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=min(MAX_PARALLEL, len(brief["research_topics"])),
        thread_name_prefix="jarvis-deck-research",
    ) as pool:
        return list(pool.map(research_one, enumerate(brief["research_topics"])))


def _build_outline(
    brief: dict[str, Any],
    research: list[dict[str, Any]],
    agent_call: Callable[[str, str], Any],
) -> list[dict[str, Any]]:
    prompt = (
        "RUOLO: Outline Architect. Crea una sequenza narrativa presentabile, non un "
        "riassunto piatto. Ogni slide deve sostenere UNA sola conclusione, collegata "
        "alla precedente e alla successiva. Non aggiungere fatti assenti dalla ricerca.\n"
        f"Brief: {json.dumps(brief, ensure_ascii=False)}\n"
        f"Ricerca: {json.dumps(research, ensure_ascii=False)}\n"
        f"Restituisci esattamente {brief['slide_count']} slide in JSON: "
        '{"slides":[{"title":"...","takeaway":"una conclusione","research_topic":"..."}]}'
    )
    value = _parse_json(agent_call("outline", prompt), "Outline Architect")
    slides = value.get("slides")
    if not isinstance(slides, list) or len(slides) != brief["slide_count"]:
        raise ValueError("Outline Architect must return exactly the requested slide count.")
    topics = {entry["topic"] for entry in research}
    result = []
    for index, slide in enumerate(slides, 1):
        if not isinstance(slide, dict):
            raise ValueError(f"Outline slide {index} must be an object.")
        topic = slide.get("research_topic")
        if topic not in topics:
            topic = research[(index - 1) % len(research)]["topic"]
        result.append({
            "number": index,
            "title": _safe_text(slide.get("title"), f"outline[{index}].title", max_length=120),
            "takeaway": _require_single_sentence(
                _safe_text(slide.get("takeaway"), f"outline[{index}].takeaway", max_length=280),
                f"outline[{index}].takeaway",
            ),
            "research_topic": topic,
        })
    return result


def _make_slide(
    outline: dict[str, Any],
    research: dict[str, Any],
    revision: str,
    agent_call: Callable[[str, str], Any],
) -> dict[str, Any]:
    prompt = (
        "RUOLO: Slide Agent. Produci una sola slide professionale, autonoma e coerente "
        "con la conclusione assegnata. Usa al massimo 5 bullet, ciascuno breve. Ogni "
        "affermazione fattuale deve essere sostenuta dalle fonti elencate. source_urls "
        "deve contenere almeno 3 URL ESATTI presenti nelle fonti fornite. Nessun HTML.\n"
        f"Brief della presentazione: {json.dumps(research.get('brief', {}), ensure_ascii=False)}\n"
        f"Contesto della sola slide: {json.dumps(outline, ensure_ascii=False)}\n"
        f"Research rilevante: {json.dumps(research, ensure_ascii=False)}\n"
        f"Istruzioni di revisione (se presenti): {revision or 'nessuna'}\n"
        f"Schema JSON: {json.dumps(_SLIDE_SCHEMA)}"
    )
    value = _parse_json(agent_call("slide", prompt), f"Slide Agent {outline['number']}")
    title = _safe_text(value.get("title"), "slide.title", max_length=120)
    takeaway = _require_single_sentence(
        _safe_text(value.get("takeaway"), "slide.takeaway", max_length=280),
        "slide.takeaway",
    )
    bullets = value.get("bullets")
    urls = value.get("source_urls")
    if not isinstance(bullets, list) or not 1 <= len(bullets) <= 5:
        raise ValueError(f"Slide {outline['number']} must contain 1-5 bullets.")
    if not isinstance(urls, list):
        raise ValueError(f"Slide {outline['number']} source_urls must be a list.")
    allowed = {source["url"] for source in research["sources"]}
    selected_urls = list(dict.fromkeys(url for url in urls if isinstance(url, str) and url in allowed))
    if len(selected_urls) < MIN_SOURCES_PER_SLIDE:
        raise ValueError(
            f"Slide {outline['number']} cites fewer than {MIN_SOURCES_PER_SLIDE} verified research URLs."
        )
    return {
        "number": outline["number"],
        "title": title,
        "takeaway": takeaway,
        "bullets": [_safe_text(item, "slide.bullet", max_length=200) for item in bullets],
        "source_urls": selected_urls,
        "research_topic": outline["research_topic"],
    }


def _write_slide_files(path: Path, slides: list[dict[str, Any]]) -> None:
    slide_dir = path / "slides"
    slide_dir.mkdir(parents=True, exist_ok=True)
    for slide in slides:
        number = slide["number"]
        _write_json(slide_dir / f"slide-{number}.json", slide)
        bullets = "".join(f"<li>{html.escape(item)}</li>" for item in slide["bullets"])
        sources = "".join(
            f'<li><a href="{html.escape(url, quote=True)}">{html.escape(url)}</a></li>'
            for url in slide["source_urls"]
        )
        document = f"""<!doctype html>
<html lang="it"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(slide['title'])}</title>
<style>
*{{box-sizing:border-box}}html,body{{margin:0;width:100%;height:100%;font-family:Segoe UI,Arial,sans-serif;background:#06111b;color:#f4f7fb}}
body{{display:grid;place-items:center;padding:24px}}.slide{{width:min(1280px,100%);height:min(720px,calc(100vh - 48px));min-height:520px;padding:58px 72px 38px;display:grid;grid-template-rows:auto auto auto 1fr auto;gap:20px;background:radial-gradient(ellipse at 85% 12%,#123d52 0,transparent 36%),linear-gradient(145deg,#0b1c2a,#07111c 68%);border:1px solid #1b5367;border-radius:20px;box-shadow:0 24px 70px #0009}}
.kicker{{color:#4dd7ef;text-transform:uppercase;letter-spacing:.18em;font-size:13px}}h1{{font-size:clamp(34px,4vw,54px);line-height:1.04;margin:0;max-width:1000px}}.takeaway{{font-size:23px;line-height:1.35;color:#9cecff;border-left:4px solid #21b7d0;padding:4px 0 4px 18px;max-width:1080px}}
.bullets{{font-size:21px;line-height:1.4;padding-left:28px;display:grid;align-content:center;gap:14px;max-width:1050px}}.sources{{font-size:10px;color:#8da4b2;max-height:62px;overflow:hidden}}.sources ul{{display:flex;gap:14px;flex-wrap:wrap;margin:5px 0 0;padding:0;list-style:none}}a{{color:#7edff1}}
@media(max-width:700px){{body{{display:block;padding:12px}}.slide{{width:100%;height:auto;min-height:calc(100vh - 24px);padding:28px 20px 20px;gap:14px;border-radius:12px}}h1{{font-size:clamp(28px,10vw,40px)}}.takeaway{{font-size:18px}}.bullets{{font-size:16px;gap:10px;padding-left:22px}}.sources{{max-height:none;overflow-wrap:anywhere}}.sources ul{{display:grid;gap:4px}}.sources li{{overflow-wrap:anywhere}}}}
</style><main class="slide"><div class="kicker">JARVIS DECK · {number:02d}</div>
<h1 class="slide-title">{html.escape(slide['title'])}</h1>
<div class="takeaway">{html.escape(slide['takeaway'])}</div>
<ul class="bullets">{bullets}</ul>
<footer class="sources"><strong>FONTI</strong><ul>{sources}</ul></footer>
</main></html>"""
        (slide_dir / f"slide-{number}.html").write_text(document, encoding="utf-8")


def _visual_qa(
    path: Path,
    slides: list[dict[str, Any]],
    vision_call: Callable[[str, str, Path], Any],
) -> dict[int, list[str]]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is required for slide screenshot QA.") from exc

    issues: dict[int, list[str]] = {}
    shots = path / "qa"
    shots.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 720}, device_scale_factor=1)
            for slide in slides:
                number = slide["number"]
                page.goto((path / "slides" / f"slide-{number}.html").resolve().as_uri())
                page.screenshot(path=str(shots / f"slide-{number}.png"), full_page=True)
                metrics = page.evaluate("""() => {
                    const root = document.querySelector('.slide');
                    const selectors = ['.slide-title','.takeaway','.bullets','.sources'];
                    const boxes = selectors.map(s => {
                        const r = document.querySelector(s).getBoundingClientRect();
                        return {name:s,x:r.x,y:r.y,right:r.right,bottom:r.bottom,width:r.width,height:r.height};
                    });
                    const overlap = [];
                    for (let i=0;i<boxes.length;i++) for (let j=i+1;j<boxes.length;j++) {
                        const a=boxes[i],b=boxes[j];
                        if (Math.min(a.right,b.right)>Math.max(a.x,b.x)+2 &&
                            Math.min(a.bottom,b.bottom)>Math.max(a.y,b.y)+2) overlap.push(a.name+' overlaps '+b.name);
                    }
                    return {scrollWidth:document.documentElement.scrollWidth,scrollHeight:document.documentElement.scrollHeight,
                        clientWidth:document.documentElement.clientWidth,clientHeight:document.documentElement.clientHeight,boxes,overlap};
                }""")
                local_issues = list(metrics["overlap"])
                if metrics["scrollWidth"] > metrics["clientWidth"] or metrics["scrollHeight"] > metrics["clientHeight"]:
                    local_issues.append("Slide content overflows the viewport.")
                for width, height in ((360, 800), (768, 1024)):
                    page.set_viewport_size({"width": width, "height": height})
                    responsive = page.evaluate(
                        "() => ({width:document.documentElement.scrollWidth,height:document.documentElement.scrollHeight,"
                        "viewportWidth:document.documentElement.clientWidth,viewportHeight:document.documentElement.clientHeight})"
                    )
                    if responsive["width"] > width or responsive["height"] > height:
                        local_issues.append(f"Slide overflows the {width}px responsive viewport.")
                page.set_viewport_size({"width": 1280, "height": 720})
                page.goto((path / "slides" / f"slide-{number}.html").resolve().as_uri())
                prompt = (
                    "RUOLO: Visual QA Agent. Esamina screenshot e misure layout della slide. "
                    "Segnala solo collisioni, clipping, illeggibilità o gerarchia visiva rotta. "
                    "Rispondi SOLO JSON {\"passed\":boolean,\"issues\":[string,...]}.\n"
                    f"Misure: {json.dumps(metrics, ensure_ascii=False)}"
                )
                visual = _parse_json(
                    vision_call("visual_qa", prompt, shots / f"slide-{number}.png"),
                    f"Visual QA slide {number}",
                )
                reported = visual.get("issues")
                if not isinstance(reported, list) or visual.get("passed") is not True:
                    local_issues.extend(
                        item for item in reported if isinstance(item, str)
                    ) if isinstance(reported, list) else local_issues.append(
                        "Visual QA Agent returned an invalid issue list."
                    )
                    if not local_issues:
                        local_issues.append("Visual QA Agent did not approve the slide.")
                if local_issues:
                    issues[number] = list(dict.fromkeys(local_issues))
        finally:
            browser.close()
    return issues


def _run_agents(
    path: Path,
    state: dict[str, Any],
    agent_call: Callable[[str, str], Any],
    search_fn: Callable[[str], list[dict[str, Any]]],
    vision_call: Callable[[str, str, Path], Any],
    qa_fn: Callable[[Path, list[dict[str, Any]], Callable], dict[int, list[str]]] | None = None,
) -> None:
    brief = state["brief"]
    state["status"] = "research"
    _save_state(path, state, path.parent)
    research = _collect_research(path, brief, agent_call, search_fn)
    state["research"] = research

    state["status"] = "outline"
    _save_state(path, state, path.parent)
    outline = _build_outline(brief, research, agent_call)
    (path / "outline.md").write_text(
        "# Outline\n\n" + "\n".join(
            f"{slide['number']}. **{slide['title']}** — {slide['takeaway']}"
            for slide in outline
        ),
        encoding="utf-8",
    )

    state["status"] = "slides"
    _save_state(path, state, path.parent)
    research_by_topic = {item["topic"]: item for item in research}

    def render_outline(slide_outline: dict[str, Any], revision: str = "") -> dict[str, Any]:
        relevant = dict(research_by_topic[slide_outline["research_topic"]])
        relevant["brief"] = brief
        return _make_slide(slide_outline, relevant, revision, agent_call)

    slides: list[dict[str, Any]] = []
    for start in range(0, len(outline), MAX_PARALLEL):
        batch = outline[start:start + MAX_PARALLEL]
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=min(MAX_PARALLEL, len(batch)),
            thread_name_prefix="jarvis-deck-slide",
        ) as pool:
            slides.extend(pool.map(render_outline, batch))
    _write_slide_files(path, slides)

    check_visuals = qa_fn or _visual_qa
    state["status"] = "quality_review"
    _save_state(path, state, path.parent)

    def critique_slides(current_slides: list[dict[str, Any]], *, final: bool = False) -> dict[str, Any]:
        prompt = (
            "RUOLO: Consistency Critic. Verifica coerenza narrativa, tono e terminologia "
            "tra tutte le slide. Separa ogni riscrittura alla singola slide interessata.\n"
            f"Brief: {json.dumps(brief, ensure_ascii=False)}\n"
            f"Slide: {json.dumps(current_slides, ensure_ascii=False)}\n"
            "Rispondi SOLO JSON {\"consistent\":boolean,\"rewrites\":[{\"slide\":int,\"instructions\":string}]}."
        )
        if final:
            prompt += "\nSe la coerenza non è raggiunta, rispondi consistent=false e indica la slide da correggere."
        return _parse_json(agent_call("critic", prompt), "Consistency Critic")

    with concurrent.futures.ThreadPoolExecutor(
        max_workers=2, thread_name_prefix="jarvis-deck-quality"
    ) as pool:
        qa_future = pool.submit(check_visuals, path, slides, vision_call)
        critic_future = pool.submit(critique_slides, list(slides))
        qa_issues = qa_future.result()
        critique = critic_future.result()

    if not isinstance(qa_issues, dict):
        raise ValueError("Visual QA must return a slide-to-issues mapping.")
    rewrites = critique.get("rewrites")
    if not isinstance(rewrites, list):
        raise ValueError("Consistency Critic rewrites must be a list.")
    if not rewrites and critique.get("consistent") is not True:
        raise RuntimeError("Consistency Critic did not approve the deck.")

    requested_rewrites: dict[int, list[str]] = {}
    for number, reported in qa_issues.items():
        if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= len(slides):
            raise ValueError("Visual QA referenced a slide outside this deck.")
        if not isinstance(reported, list) or any(not isinstance(item, str) for item in reported):
            raise ValueError(f"Visual QA issues for slide {number} must be a list of strings.")
        requested_rewrites.setdefault(number, []).append(
            "Correggi solo questa slide. Problemi Visual QA: " + "; ".join(reported)
        )
    for item in rewrites:
        if not isinstance(item, dict):
            raise ValueError("Consistency Critic rewrite entries must be objects.")
        number, instructions = item.get("slide"), item.get("instructions")
        if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= len(slides):
            raise ValueError("Consistency Critic referenced a slide outside this deck.")
        requested_rewrites.setdefault(number, []).append(
            _safe_text(instructions, "critic.instructions", max_length=500)
        )

    if requested_rewrites:
        state["status"] = "slide_rewrite"
        _save_state(path, state, path.parent)
        for number, instructions in requested_rewrites.items():
            slides[number - 1] = render_outline(
                outline[number - 1],
                " ".join(instructions),
            )
        _write_slide_files(path, slides)
        remaining = check_visuals(
            path, [slides[number - 1] for number in requested_rewrites], vision_call
        )
        if remaining:
            raise RuntimeError(
                f"Visual QA fails after targeted rewrite on slides: {', '.join(map(str, remaining))}."
            )
        final_critique = critique_slides(slides, final=True)
        if final_critique.get("consistent") is not True or final_critique.get("rewrites"):
            raise RuntimeError("Consistency Critic did not accept the surgical slide revisions.")
        critique = final_critique

    state["slides"] = slides
    state["status"] = "awaiting_export_approval"
    if "brief_approval_turn_id" in state:
        state["export_ready_turn_id"] = state["brief_approval_turn_id"]
    _save_state(path, state, path.parent)
    (path / "critique.md").write_text(
        "# Consistency Critic\n\n"
        + ("Coerenza narrativa, tono e terminologia approvati.\n"
           if critique.get("consistent") is True
           else "Le riscritture mirate sono state applicate e verificate.\n"),
        encoding="utf-8",
    )


def _export_pptx(path: Path, state: dict[str, Any]) -> Path:
    try:
        from pptx import Presentation
        from pptx.dml.color import RGBColor
        from pptx.enum.text import PP_ALIGN
        from pptx.util import Inches, Pt
    except ImportError as exc:
        raise RuntimeError("The python-pptx package is required for editable PowerPoint export.") from exc

    presentation = Presentation()
    presentation.slide_width = Inches(13.333)
    presentation.slide_height = Inches(7.5)
    blank = presentation.slide_layouts[6]
    for item in state["slides"]:
        slide = presentation.slides.add_slide(blank)
        background = slide.background.fill
        background.solid()
        background.fore_color.rgb = RGBColor(6, 17, 27)

        def textbox(x: float, y: float, w: float, h: float, text: str, size: int, color, bold=False):
            shape = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
            frame = shape.text_frame
            frame.word_wrap = True
            frame.margin_left = Inches(0.06)
            frame.margin_right = Inches(0.06)
            frame.margin_top = Inches(0.03)
            frame.margin_bottom = Inches(0.03)
            paragraph = frame.paragraphs[0]
            paragraph.text = text
            paragraph.font.name = "Aptos"
            paragraph.font.size = Pt(size)
            paragraph.font.bold = bold
            paragraph.font.color.rgb = RGBColor(*color)
            return shape

        textbox(0.7, 0.3, 12, 0.35, f"JARVIS DECK  /  {item['number']:02d}", 10, (77, 215, 239), True)
        textbox(0.7, 0.82, 11.9, 1.05, item["title"], 31, (244, 247, 251), True)
        textbox(0.75, 2.0, 11.8, 0.9, item["takeaway"], 20, (156, 236, 255), True)
        body = slide.shapes.add_textbox(Inches(0.95), Inches(3.05), Inches(11.5), Inches(3.2))
        frame = body.text_frame
        frame.word_wrap = True
        for index, bullet in enumerate(item["bullets"]):
            paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
            paragraph.text = bullet
            paragraph.level = 0
            paragraph.font.name = "Aptos"
            paragraph.font.size = Pt(19)
            paragraph.font.color.rgb = RGBColor(220, 232, 241)
            paragraph.space_after = Pt(14)
        sources = "FONTI: " + "  ·  ".join(item["source_urls"])
        footer = textbox(0.75, 6.72, 11.9, 0.45, sources, 7, (141, 164, 178))
        for paragraph in footer.text_frame.paragraphs:
            paragraph.alignment = PP_ALIGN.LEFT
    output = path / "presentation.pptx"
    presentation.save(output)
    return output


def _export_pdf(pptx_path: Path) -> Path | None:
    converter = shutil.which("soffice") or shutil.which("libreoffice")
    if not converter:
        return None
    result = subprocess.run(
        [converter, "--headless", "--convert-to", "pdf", "--outdir", str(pptx_path.parent), str(pptx_path)],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    pdf_path = pptx_path.with_suffix(".pdf")
    if result.returncode != 0 or not pdf_path.is_file():
        detail = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
        raise RuntimeError(f"PDF conversion failed: {detail}")
    return pdf_path


def run_pipeline(
    parameters: dict[str, Any],
    *,
    agent_call: Callable[[str, str], Any] | None = None,
    search_fn: Callable[[str], list[dict[str, Any]]] | None = None,
    vision_call: Callable[[str, str, Path], Any] | None = None,
    qa_fn: Callable[[Path, list[dict[str, Any]], Callable], dict[int, list[str]]] | None = None,
    root: Path | None = None,
) -> dict[str, Any]:
    params = parameters or {}
    operation = params.get("operation", "start")
    if not isinstance(operation, str) or operation not in {
        "start", "approve_brief", "approve_export", "cancel", "status"
    }:
        raise ValueError("operation must be start, approve_brief, approve_export, cancel, or status.")
    root = (root or history_root()).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if operation == "start":
        request = _safe_text(params.get("request"), "request", max_length=4000)
        audience = str(params.get("audience", "")).strip()[:160]
        slide_budget = params.get("slide_budget", 10)
        if isinstance(slide_budget, bool) or not isinstance(slide_budget, int) or not 3 <= slide_budget <= MAX_SLIDES:
            raise ValueError(f"slide_budget must be between 3 and {MAX_SLIDES}.")
        call = agent_call or _default_agent_call
        brief = _create_brief(request, audience, slide_budget, call)
        project_id = uuid.uuid4().hex
        path = _project_path(root, project_id)
        path.mkdir(parents=True, exist_ok=False)
        state = {
            "project_id": project_id,
            "created_at": datetime.now().astimezone().isoformat(),
            "request": request,
            "status": "awaiting_brief_approval",
            "brief": brief,
            "models": dict(ROLE_MODELS),
        }
        created_turn = params.get("_approval_turn_id")
        if isinstance(created_turn, int) and not isinstance(created_turn, bool):
            state["created_user_turn_id"] = created_turn
        _write_brief(path, brief)
        _save_state(path, state, root)
        return {
            "status": state["status"],
            "project_id": project_id,
            "brief": brief,
            "brief_path": str(path / "brief.md"),
            "next_step": f"Approva il brief con operation=approve_brief e project_id={project_id}.",
        }

    path, state = _load_project(root, params.get("project_id"))
    if operation == "status":
        return {"status": state["status"], "project_id": state["project_id"], "path": str(path)}
    if operation == "cancel":
        if state["status"] in {"complete", "cancelled"}:
            raise ValueError(f"Project is already {state['status']}.")
        state["status"] = "cancelled"
        _save_state(path, state, root)
        return {"status": "cancelled", "project_id": state["project_id"]}
    if operation == "approve_brief":
        if state["status"] != "awaiting_brief_approval":
            raise ValueError(f"Brief approval is not valid while project is {state['status']}.")
        approval_turn = params.get("_approval_turn_id")
        created_turn = state.get("created_user_turn_id")
        if (
            isinstance(created_turn, int)
            and (
                isinstance(approval_turn, bool)
                or not isinstance(approval_turn, int)
                or approval_turn <= created_turn
            )
        ):
            raise ValueError("Brief approval must arrive in a later user turn than brief creation.")
        if isinstance(approval_turn, int) and not isinstance(approval_turn, bool):
            state["brief_approval_turn_id"] = approval_turn
        try:
            _run_agents(
                path,
                state,
                agent_call or _default_agent_call,
                search_fn or _default_search,
                vision_call or _default_vision_call,
                qa_fn,
            )
        except Exception as exc:
            state["status"] = "failed"
            state["error"] = str(exc)
            _save_state(path, state, root)
            raise
        return {
            "status": state["status"],
            "project_id": state["project_id"],
            "slides": len(state["slides"]),
            "outline_path": str(path / "outline.md"),
            "next_step": f"Esamina gli artefatti e approva l'export con operation=approve_export e project_id={state['project_id']}.",
        }
    if state["status"] != "awaiting_export_approval":
        raise ValueError(f"Export approval is not valid while project is {state['status']}.")
    approval_turn = params.get("_approval_turn_id")
    export_ready_turn = state.get("export_ready_turn_id")
    if (
        isinstance(export_ready_turn, int)
        and (
            isinstance(approval_turn, bool)
            or not isinstance(approval_turn, int)
            or approval_turn <= export_ready_turn
        )
    ):
        raise ValueError("Export approval must arrive in a later user turn than the export request.")
    pptx_path = _export_pptx(path, state)
    pdf_path = _export_pdf(pptx_path)
    state["status"] = "complete"
    state["exports"] = {
        "pptx": str(pptx_path),
        "pdf": str(pdf_path) if pdf_path else None,
    }
    _save_state(path, state, root)
    return {
        "status": "complete",
        "project_id": state["project_id"],
        "pptx": str(pptx_path),
        "pdf": str(pdf_path) if pdf_path else None,
        "pdf_note": None if pdf_path else "LibreOffice non è installato; il PPTX modificabile è pronto.",
    }

import json
from pathlib import Path

from pptx import Presentation
import pytest

from actions import deck_pipeline as deck_action
from core.deck_pipeline import run_pipeline
from core.tool_router import ToolRouter


def _fake_agent(role, prompt):
    if role == "brief":
        return {
            "title": "Energia pulita",
            "audience": "Investitori",
            "objective": "Valutare le opportunità di investimento nell'energia pulita.",
            "tone": "Professionale",
            "constraints": ["Usare dati con fonti verificabili"],
            "research_topics": ["mercato rinnovabili", "tecnologie accumulo"],
        }
    if role == "research":
        return "Fonti raccolte e limiti dei dati dichiarati."
    if role == "outline":
        return {
            "slides": [
                {"title": f"Titolo {n}", "takeaway": f"Conclusione {n}", "research_topic": topic}
                for n, topic in enumerate(
                    ["mercato rinnovabili", "tecnologie accumulo", "mercato rinnovabili"], 1
                )
            ]
        }
    if role == "slide":
        outline = json.loads(
            prompt.split("Contesto della sola slide: ", 1)[1].split("\nResearch rilevante:", 1)[0]
        )
        research = json.loads(
            prompt.split("\nResearch rilevante: ", 1)[1].split("\nIstruzioni di revisione", 1)[0]
        )
        return {
            "title": outline["title"],
            "takeaway": outline["takeaway"],
            "bullets": ["Evidenza verificata", "Implicazione strategica"],
            "source_urls": [item["url"] for item in research["sources"][:3]],
        }
    if role == "critic":
        return {"consistent": True, "rewrites": []}
    raise AssertionError(f"Unexpected agent role: {role}")


def _fake_search(topic):
    safe_topic = topic.replace(" ", "-")
    return [
        {
            "url": f"https://research.example/{safe_topic}/{index}",
            "title": f"Fonte {index}",
            "snippet": f"Informazione documentata {index}",
        }
        for index in range(1, 4)
    ]


def _fake_qa(path, slides, vision_call):
    for slide in slides:
        assert (path / "slides" / f"slide-{slide['number']}.html").is_file()
        assert (path / "slides" / f"slide-{slide['number']}.json").is_file()
    return {}


@pytest.mark.pre_existing(reason="ToolRouter non seleziona deck_pipeline e web_search per la richiesta")
@pytest.mark.xfail(
    reason="ToolRouter non seleziona deck_pipeline e web_search per la richiesta",
    strict=False,
)
def test_presentation_request_is_routed_automatically_without_deck_command():
    declarations = [{"name": "deck_pipeline"}, {"name": "web_search"}]
    selected = {
        item["name"]
        for item in ToolRouter().select_for_request(
            "Prepara una presentazione per gli investitori sul mercato solare",
            declarations,
        )
    }

    assert selected == {"deck_pipeline", "web_search"}
    assert "AUTOMATICAMENTE" in deck_action.TOOL["description"]
    assert "senza richiedere /deck" in deck_action.TOOL["description"]


def test_pipeline_runs_approved_stages_and_exports_editable_pptx(tmp_path):
    call = lambda operation, **extra: run_pipeline(
        {"operation": operation, "project_id": project_id, **extra},
        agent_call=_fake_agent,
        search_fn=_fake_search,
        vision_call=lambda *_: {"passed": True, "issues": []},
        qa_fn=_fake_qa,
        root=tmp_path,
    )
    started = run_pipeline(
        {"operation": "start", "request": "Mercato e opportunità energia pulita", "slide_budget": 3},
        agent_call=_fake_agent,
        root=tmp_path,
    )
    project_id = started["project_id"]
    assert started["status"] == "awaiting_brief_approval"
    assert Path(started["brief_path"]).is_file()

    prepared = call("approve_brief")
    assert prepared["status"] == "awaiting_export_approval"
    assert prepared["slides"] == 3
    assert (tmp_path / project_id / "research" / "research-1.md").is_file()
    assert (tmp_path / project_id / "slides" / "slide-1.html").is_file()
    assert len(json.loads((tmp_path / project_id / "slides" / "slide-1.json").read_text())["source_urls"]) == 3

    exported = call("approve_export")
    deck_path = Path(exported["pptx"])
    assert exported["status"] == "complete"
    assert deck_path.is_file()
    deck = Presentation(deck_path)
    assert len(deck.slides) == 3
    assert "Conclusione 1" in "\n".join(
        shape.text for shape in deck.slides[0].shapes if shape.has_text_frame
    )


def test_model_cannot_approve_a_brief_or_export_on_user_behalf(monkeypatch, tmp_path):
    monkeypatch.setattr(
        deck_action,
        "run_pipeline",
        lambda params: {"status": "advanced", "operation": params["operation"]},
    )
    assert '"approval_required"' in deck_action.deck_pipeline(
        {"operation": "approve_brief"}, user_text="Crea una presentazione"
    )
    assert '"approval_required"' in deck_action.deck_pipeline(
        {"operation": "approve_export"}, user_text="Sì, approvo il brief"
    )
    assert '"status": "advanced"' in deck_action.deck_pipeline(
        {"operation": "approve_brief"}, user_text="Sì, approvo il brief"
    )
    assert '"status": "advanced"' in deck_action.deck_pipeline(
        {"operation": "approve_export"}, user_text="Sì, approvo l'export PPTX"
    )


def test_approval_is_rejected_in_the_same_turn_that_created_the_brief(tmp_path):
    started = run_pipeline(
        {
            "operation": "start",
            "request": "Mercato e opportunità energia pulita",
            "slide_budget": 3,
            "_approval_turn_id": 12,
        },
        agent_call=_fake_agent,
        root=tmp_path,
    )
    with pytest.raises(ValueError, match="later user turn"):
        run_pipeline(
            {
                "operation": "approve_brief",
                "project_id": started["project_id"],
                "_approval_turn_id": 12,
            },
            agent_call=_fake_agent,
            root=tmp_path,
        )
    assert run_pipeline(
        {"operation": "status", "project_id": started["project_id"]}, root=tmp_path
    )["status"] == "awaiting_brief_approval"

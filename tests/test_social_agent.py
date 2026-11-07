import sqlite3

import pytest

from agents.social_agent import SocialAgent, SocialPublishError
from core.social_publishers import MockPublisher


def _agent(tmp_path, *, confirm=None, autopilot=False):
    publisher = MockPublisher("instagram")
    agent = SocialAgent(
        {"instagram": publisher},
        database_path=tmp_path / "social.sqlite3",
        confirm=confirm,
        autopilot=autopilot,
    )
    return agent, publisher


def _status(agent, draft_id):
    with sqlite3.connect(agent.database_path) as connection:
        return connection.execute(
            "SELECT status, publication_id FROM social_publications WHERE draft_id = ?",
            (draft_id,),
        ).fetchone()


def test_prepare_post_saves_a_draft_without_publishing(tmp_path):
    agent, publisher = _agent(tmp_path)

    draft = agent.prepare_post("instagram", "A caption")

    assert draft.platform == "instagram"
    assert draft.text == "A caption"
    assert publisher.calls == []
    assert _status(agent, draft.draft_id) == ("draft", "")


def test_publish_requests_explicit_confirmation_before_sending(tmp_path):
    confirmations = []
    agent, publisher = _agent(
        tmp_path, confirm=lambda summary: confirmations.append(summary) or True
    )
    draft = agent.prepare_post("instagram", "Approved caption")

    result = agent.publish("instagram", draft)

    assert len(confirmations) == 1
    assert draft.draft_id in confirmations[0]
    assert publisher.calls == [("Approved caption", None)]
    assert result is not None and result.status == "published"
    assert _status(agent, draft.draft_id) == ("published", result.publication_id)


def test_cancelled_confirmation_blocks_publishing(tmp_path):
    agent, publisher = _agent(tmp_path, confirm=lambda _summary: False)
    draft = agent.prepare_post("instagram", "Do not publish")

    result = agent.publish("instagram", draft)

    assert result is None
    assert publisher.calls == []
    assert _status(agent, draft.draft_id) == ("cancelled", "")


def test_missing_confirmation_fails_closed(tmp_path):
    agent, publisher = _agent(tmp_path)
    draft = agent.prepare_post("instagram", "Needs confirmation")

    with pytest.raises(SocialPublishError, match="Explicit user confirmation"):
        agent.publish("instagram", draft)

    assert publisher.calls == []
    assert _status(agent, draft.draft_id) == ("draft", "")


def test_autopilot_only_bypasses_confirmation_when_explicitly_enabled(tmp_path):
    agent, publisher = _agent(tmp_path, autopilot=True)
    draft = agent.prepare_post("instagram", "Configured autopilot")

    result = agent.publish("instagram", draft)

    assert result is not None and result.status == "published"
    assert publisher.calls == [("Configured autopilot", None)]


def test_default_mode_does_not_infer_autopilot_from_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_SOCIAL_AUTOPILOT", "true")
    agent, publisher = _agent(tmp_path, confirm=lambda _: False)
    draft = agent.prepare_post("instagram", "Still requires confirmation")

    assert agent.publish("instagram", draft) is None
    assert publisher.calls == []


def test_successful_or_cancelled_drafts_cannot_be_submitted_twice(tmp_path):
    agent, publisher = _agent(tmp_path, confirm=lambda _: True)
    draft = agent.prepare_post("instagram", "One publication only")
    agent.publish("instagram", draft)

    with pytest.raises(SocialPublishError, match="already attempted"):
        agent.publish("instagram", draft)

    assert publisher.calls == [("One publication only", None)]


def test_failed_publisher_logs_only_error_type_not_sensitive_details(tmp_path):
    logs = []

    class LeakingFailurePublisher(MockPublisher):
        def publish(self, content, media_path=None):
            raise RuntimeError("OAuth token was TOP_SECRET_TOKEN")

    publisher = LeakingFailurePublisher("instagram")
    agent = SocialAgent(
        {"instagram": publisher},
        database_path=tmp_path / "social.sqlite3",
        confirm=lambda _: True,
        logger=logs.append,
    )
    draft = agent.prepare_post("instagram", "Caption")

    with pytest.raises(SocialPublishError, match="sensitive details were not logged"):
        agent.publish("instagram", draft)

    assert "TOP_SECRET_TOKEN" not in "\n".join(logs)
    assert _status(agent, draft.draft_id) == ("failed", "")
    with sqlite3.connect(agent.database_path) as connection:
        error_type = connection.execute(
            "SELECT error_type FROM social_publications WHERE draft_id = ?",
            (draft.draft_id,),
        ).fetchone()
    assert error_type == ("RuntimeError",)


def test_publish_rejects_platform_mismatch_and_invalid_draft(tmp_path):
    agent, publisher = _agent(tmp_path, confirm=lambda _: True)
    draft = agent.prepare_post("instagram", "Caption")

    with pytest.raises(ValueError, match="does not match"):
        agent.publish("tiktok", draft)
    assert publisher.calls == []

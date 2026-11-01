import json
from .supervisor_agent import _get_model

def run_research(topic: str) -> str:
    """
    Research Agent searches for documentation and API references.
    """
    model = _get_model()
    prompt = f"You are the Research Agent. Research the following topic and provide technical details, code snippets, and API references:\n\nTopic: {topic}"
    try:
        response = model.generate_content(prompt)
        return response.text.strip()
    except Exception as e:
        return f"Research error: {e}"

def research_action(parameters: dict, **kwargs) -> str:
    topic = parameters.get("topic", "")
    if not topic:
        return "Research Agent needs a topic."
    return run_research(topic)

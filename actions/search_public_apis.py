"""Search the opt-in Public APIs MCP catalog."""

from core.jarvis_runtime import get_runtime

TOOL = {
    "name": "search_public_apis",
    "description": (
        "Search Jarvis's read-only Public APIs catalog for free or public APIs "
        "by topic, keyword, or category. Use for spoken requests such as finding "
        "weather, finance, or unauthenticated APIs. No user confirmation is "
        "needed; the catalog must first be activated in Plugins & Connections."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query": {
                "type": "STRING",
                "description": "Keyword, topic, or category to search for.",
            },
            "limit": {
                "type": "INTEGER",
                "description": "Maximum number of matches, from 1 to 50.",
            },
        },
        "required": ["query"],
    },
    "handler": lambda parameters: get_runtime().public_apis.search(
        parameters["query"], parameters.get("limit", 10)
    ),
    "risk_class": "read",
}

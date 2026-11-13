"""Filter Public APIs search results by authentication requirements."""

from core.jarvis_runtime import get_runtime

TOOL = {
    "name": "filter_apis_by_auth",
    "description": (
        "Find public APIs matching a topic and return only those that do not "
        "require authentication (auth none). Use for spoken requests such as "
        "finding free weather APIs without a key. This is a read-only catalog "
        "lookup and needs no user confirmation; the catalog must be active."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "query": {
                "type": "STRING",
                "description": "Topic or category to search.",
            },
            "auth": {
                "type": "STRING",
                "description": "Use 'none' to return APIs requiring no authentication.",
            },
            "limit": {
                "type": "INTEGER",
                "description": "Maximum number of candidate APIs to check, from 1 to 50.",
            },
        },
        "required": ["query"],
    },
    "handler": lambda parameters: get_runtime().public_apis.filter_by_auth(
        parameters["query"],
        parameters.get("auth", "none"),
        parameters.get("limit", 10),
    ),
    "risk_class": "read",
}

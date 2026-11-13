"""Retrieve complete metadata for an API in the public catalog."""

from core.jarvis_runtime import get_runtime

TOOL = {
    "name": "get_public_api_details",
    "description": (
        "Get the URL, authentication type, category, and other metadata for an "
        "API returned by search_public_apis. This is a read-only catalog lookup "
        "and needs no user confirmation; the catalog must be active."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "id": {
                "type": "STRING",
                "description": "Unique API ID returned by search_public_apis.",
            }
        },
        "required": ["id"],
    },
    "handler": lambda parameters: get_runtime().public_apis.details(
        parameters["id"]
    ),
    "risk_class": "read",
}

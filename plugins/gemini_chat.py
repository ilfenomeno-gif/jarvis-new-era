"""Voice/UI entry point for opening the separate Gemini text chat."""

PLUGIN = {
    "name": "gemini_chat",
    "description": (
        "Opens JARVIS's separate Gemini text-chat window when the user asks "
        "to chat with Gemini or open Gemini chat."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "action": {
                "type": "STRING",
                "description": "Use open to show the Gemini chat window.",
                "enum": ["open"],
            },
        },
        "required": [],
    },
}


def run(parameters: dict, player=None) -> str:
    if not callable(getattr(player, "show_gemini_chat", None)):
        raise RuntimeError("The JARVIS UI cannot open the Gemini chat window.")
    player.show_gemini_chat()
    return "Opened the separate Gemini chat window."

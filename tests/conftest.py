import os
import tempfile

# Tests that open the real window must never read or overwrite the user's saved HUD layout.
os.environ.setdefault("JARVIS_UI_LAYOUT", os.path.join(tempfile.mkdtemp(prefix="jarvis_layout_"), "ui_layout.json"))

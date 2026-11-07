# JARVIS desktop and workspace capabilities

JARVIS composes its existing Windows desktop, browser, OCR, file, and web-search
actions with the read-only `workspace_reader` action. The action router exposes
the relevant tools for the request instead of placing every tool in every model
call.

## Local workspace

`workspace_reader` accepts an explicit absolute path and one of four actions:

- `map`: bounded recursive file inventory, file-type counts, and source-module
  definitions/imports.
- `read`: local extraction from common text/code formats, HTML, PDF, DOCX,
  PPTX, XLSX, images with local Tesseract OCR, and ZIP member names.
- `search`: bounded text search in supported text/code files.
- `plan_reorganization`: advisory groups by file type; it never changes files.

Traversal skips symbolic links, hidden/secret files and directories, common
dependency/build directories, and caps depth, file count, file size, and result
characters. A user must provide the path; JARVIS does not infer a folder to
scan. An unsupported or encrypted format is reported rather than silently
treated as readable. Existing `file_processor` actions handle supported
individual media operations; `large_file_reader` remains the option for large
text files.

File creation and editing remain separate through the existing file-management
actions. The workspace reader itself never writes, moves, deletes, or executes
files. Script inspection and explanations are distinct from script execution.
Running a Python script through `file_processor` now requires a separate user
confirmation bound to the exact resolved script path; a model-supplied
`confirmed=true` alone is not authorization.

## Screen and computer

- `computer_perception` provides local OCR, a bounded UI Automation tree,
  screen metadata, and a time-limited screen-change wait. Set `include_ocr=true`
  on `wait_for_change` to OCR the new frame locally. This is one bounded
  observation, not an always-on monitor.
- `computer_input` sends one confirmed mouse or keyboard action at a time to an
  allowlisted foreground Windows process. Ctrl+Alt+Esc is the emergency stop.
- `accessibility_read_screen` and the existing screen reader provide direct
  screen text reading; the existing browser tools read and interact with the
  integrated HTML page.

OCR results, extracted file text, and browser content are returned to the
currently selected JARVIS model. Local capture does not save or upload a
screenshot, but text supplied to a cloud model is still sent as conversation
content.

## Web, browser, and scripts

JARVIS reuses the existing `web_search`, `browser_control`, `read_active_page`,
`read_page`, `computer_input`, `file_processor`, and `terminal_run` actions.
Web research requires network access. Browser interaction is distinct from
desktop input; the desktop input allowlist and confirmation rules continue to
apply to mouse and keyboard actions. Script execution remains on the existing
confirmed, policy-guarded command path and is not part of workspace scanning.

## Dependencies and limitations

Core folder maps and text reads use the Python standard library. PDF, DOCX,
PPTX, XLSX, and image OCR need their existing optional packages, and image OCR
also requires the local Tesseract executable and the requested language data.
On Windows, JARVIS checks `PATH` and the standard Tesseract installation folders
for that executable. Screen OCR defaults to English (`eng`); other languages
such as Italian require their matching `*.traineddata` file. The reader does not
claim support for every proprietary or encrypted format; it identifies
unsupported content and points to the existing file-processing route where
applicable.

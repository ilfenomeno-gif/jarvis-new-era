# Harness H1 — adapter runtime

## Decision record

### 1. Orchestrate, do not absorb

`HarnessRuntime` dispatches through `AgentLoopAdapter` and
`ComputerLoopAdapter`; the established loops and their result formats stay
unchanged. This preserves the separate confirmation, foreground, and emergency
stop behavior, limits regressions, and makes adapter selection/result mapping
testable. Absorbing either loop would duplicate or rewrite tested control logic.

### 2. Approval authority and confirmation ownership

When enabled, the Harness policy is the pre-dispatch authority. It uses
`risk_class` only when explicitly declared, respects the ActionRegistry's
declared-risks API, applies the config overrides, and treats missing or invalid
risk as `destructive`. `file_controller`, `desktop_control`, `proxy_launcher`,
`vscode_control`, `file_processor`, and `shutdown_jarvis` are conservatively
overridden to destructive even if a tool declares a lower class. When declared
risk and registry risk disagree, the more restrictive class wins.

An unapproved write/destructive session is rejected before adapter execution.
`main.py` uses its existing exact-argument confirmation flow for
`computer_use_loop`; `agent_loop` retains its existing session approval.
Explicitly delegated tools use their existing confirmation/guard path instead
of a second generic Harness prompt. `computer_stop` is also delegated as a
safety control so an emergency stop can never be delayed by an approval
dialog. ComputerLoop's per-action confirmation and TerminalGuard remain active
for protected operations; these approve specific operations, not a second copy
of the Harness task approval. Invalid policy denylist patterns fail with an
error.

The Harness does not trust a tool's `confirmed` parameter as proof of approval:
the runtime requires `HarnessSession.status == "approved"` unless a future
adapter is explicitly assigned confirmation ownership. H2 should replace the
current hand-maintained delegated-tool list with typed confirmation capabilities.

### 3. Checkpoint ownership, recovery, and privacy

Harness owns an append-only JSONL checkpoint journal rather than reusing
MemoryStore or AuditLog. MemoryStore accepts arbitrary application state;
AuditLog records tool arguments and free-form detail. The Harness journal
whitelists trace/session IDs, agent/status, timestamps, numeric usage,
artifact type/status/hash/size, and history role plus content length/hash.
Goal and history text, prompts, responses, artifact names/paths, and arbitrary
usage fields are not persisted.

Restore is deliberately metadata-only and cannot resume execution: retaining
replayable context requires a separate private content store and a retention/
consent decision. H2 must define that store before enabling durable replay.

## Integration and opt-in

- `JARVIS_HARNESS=1` enables the optional runtime wiring in `main.py`; default
  remains off and preserves the existing dispatch path. With the flag enabled,
  write/destructive calls enter the existing exact-argument confirmation flow
  unless their existing action guard is listed in
  `confirmation_delegated_tools`.
- `JARVIS_COMPUTER_LOOP=1` is still required to instantiate ComputerLoop.
- Runtime adapter keys are `agent_loop` and `computer_use_loop`.
- The existing loop implementations retain their own lifecycle, retries,
  foreground checks, terminal policy, and emergency stop.
- `HarnessRuntime.step()` returns an explicit unsupported result when an
  adapter has no single-step API.
- `HarnessRuntime.stop()` forwards only to an adapter-provided hook; otherwise
  it raises `NotImplementedError`. Use the existing Ctrl+Alt+Esc/loop stop
  mechanisms. A unified interrupt hook remains H2.
- `resume()` refuses metadata-only checkpoints rather than replaying
  incomplete or fabricated context.

## Verification

- `python -m pytest -q` → 1098 passed, 16 skipped, 7 xfailed.
- `python -m pytest -q -m "not pre_existing"` → 1098 passed, 16 skipped,
  7 deselected.
- One filtered-suite attempt terminated with a native access violation in
  `tests/test_workspace_reader.py::test_read_extracts_spreadsheet_values`;
  an immediate rerun passed with the counts above. No code change was made to
  that unrelated test.
- Targeted H0/H1/router/terminal-guard/action-wiring tests → 52 passed.
- `py_compile` passed for all touched Python files.
- Ruff passed for new/updated Harness modules and the H1 tests. Repository-wide
  `python -m ruff check .` still reports 856 existing findings (same count as
  the preceding baseline); no findings point to the new Harness modules or H1
  tests.
- `git diff --check` passed for H1-scoped files.

## Alternatives considered

1. **Rewrite both loops into the Harness:** rejected because confirmation,
   result, and emergency-stop semantics differ and are already exercised.
2. **Use ActionRegistry's default `write` as authoritative for missing
   metadata:** rejected because it loses the distinction between declared and
   implicit risk; the registry now exposes that distinction.
3. **Persist complete session history in AuditLog/MemoryStore:** rejected due
   free-form prompt/response retention and over-broad tool argument logging.
4. **Resume directly from hashed checkpoint metadata:** rejected because hashes
   cannot reconstruct user intent or tool context.

## H2 follow-up

- Add a typed approval/capability protocol across every action, including
  `shutdown_jarvis`, without bypassing existing guardrails.
- Add an interrupt hook for both adapters and test stop races.
- Decide on user consent, retention, and protected storage for replayable
  session content; only then implement resumable checkpoints.
- Add a provider-backed plan/observe loop and judge-based evaluation. H1 adapts
  the existing planners; it does not replace them with a new LLM harness loop.
- Run Ruff cleanups as a separately scoped baseline task; do not fold legacy
  lint repairs into this integration.

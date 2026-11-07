# Harness H2 — cooperative interrupt and bounded single-step

## Priority and decision

This iteration implements priority 2: a shared cooperative interrupt protocol
and bounded single-step adapters for both existing loops.

- Interrupts are cooperative and checked at action boundaries; ongoing native
  calls/subprocesses are not forcibly terminated.
- Each `HarnessRuntime.run()` or `.step()` owns a temporary
  `InterruptController`, addressable by the `HarnessSession.id`.
- `pause(id)`, `continue_session(id)`, and `stop(id)` act on that active
  controller. Calls for an inactive session fail explicitly.
- A single step is one bounded AgentLoop action or at most one ComputerLoop
  planned action. ComputerLoop reports `paused` when its original plan had
  remaining actions; it does not claim that the full goal completed.
- The runtime and integration remain opt-in with `JARVIS_HARNESS=1`.

The loops retain their existing foreground validation, emergency kill switch,
terminal guard, and per-operation confirmations. Stop wakes a paused loop and
is observed before its next action; a currently running blocking operation may
finish before the stop takes effect.

## Alternatives considered

1. Rewriting either loop into a single asynchronous state machine was rejected:
   it would duplicate mature loop behavior and risk its guards.
2. Killing worker threads or subprocesses was rejected because Python cannot
   safely terminate arbitrary threads and ComputerLoop does not own all action
   subprocess lifetimes.
3. Treating every one-action result as full task success was rejected. Single
   step is bounded and marked `paused` when the planner produced more work.
4. Extending checkpoints to replay partial plans was rejected for this
   iteration; current checkpoint storage remains metadata-only.

## Contract

`core.harness.interrupt.Interrupt` defines `stop()`, `pause()`, `resume()`,
and `checkpoint(timeout=None)`. `InterruptController` is thread-safe. Loop
hooks are optional and default to `None`, so direct, non-Harness usage keeps
its previous behavior.

`HarnessRuntime.step(session)` uses the selected adapter's one-action path and
retains the same approval gate as `run()`. The returned `HarnessResult` carries
the normalized result; the session status is `paused` after a successful
single-step. Repeated calls replan from the current environment and require the
caller to provide an approved session again when policy requires confirmation.

`AgentLoopAdapter` caps its one-step AgentLoop to one action. Its existing
`max_steps` response is normalized as a successful partial step, not a goal
completion. `ComputerLoopAdapter` passes `max_steps=1` to its newly optional
run parameter and preserves the original `LoopResult` contract.

## Deferred to H3

- Typed tool capability/effect/sensitive-argument declarations; current
  `risk_class` policy and fail-closed behavior remain.
- Replayable persistence with explicit content consent. Checkpoints remain
  hash/metadata-only and `resume()` refuses to replay them.
- Configurable LLM/rule judge integration. Existing `run_eval(..., judge=None)`
  remains optional and does not access the network.
- Preemption of an operation already blocked inside a native API or external
  subprocess.

## Verification

H2-specific tests cover both adapter single-step paths, runtime pause/stop
behavior, metadata-only replay refusal, and a local rule-based optional eval
judge.

- `python -m pytest -q` → 1103 passed, 16 skipped, 7 xfailed.
- `python -m pytest -q -m "not pre_existing"` → 1103 passed, 16 skipped,
  7 deselected.
- Targeted H0-H2 and loop tests → 45 passed.
- `py_compile`, TOML parsing (no BOM), and H2-scoped `git diff --check` passed.
- Ruff found four existing findings in `core/agent_loop.py` (import ordering,
  legacy `Callable` import, and timeout alias); no findings were reported in
  the new/updated Harness files, `core/computer_loop.py`, or H2 tests.

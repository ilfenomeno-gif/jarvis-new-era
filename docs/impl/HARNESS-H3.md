# Harness H3 — typed capabilities, read-only contract, and local eval

## Decisions

1. **Typed capability contract.** `core/harness/capabilities.py` defines
   `Capability` with a versioned parameter schema, effects, risk, confirmation,
   scope, optional rate limit, and deprecation state. `ActionRegistry.get_capability`
   is additive; the H1 `risk_class()` and `risk_class_declared()` APIs remain.
   Existing legacy `ToolCapabilities` metadata is translated without changing
   the action's H1 risk behavior.
2. **Local schema validation.** No new dependency was added. The validator
   supports JSON types, object properties, required fields, enum, pattern,
   items, additional properties, length/item bounds, and numeric bounds. It
   rejects malformed schemas and unsupported keywords rather than silently
   treating them as validated. It is intentionally not a complete
   JSON-Schema implementation; `$ref`, combinators, formats, and remote schema
   resolution are not supported.
3. **Fail-closed approval.** `ApprovalPolicy.evaluate()` prefers a valid
   registry or tool `Capability`, validates arguments against its schema, and
   denies invalid/mismatched capability contracts. If no new contract exists,
   it retains the H1 legacy capability/risk fallback. Explicit typed
   `capability` declarations must provide effects and risk; those fields are
   not inferred for a declared contract. Confirmation remains a single
   pre-dispatch policy decision; action-level destructive confirmation is
   unchanged.
4. **Read-only API and deterministic eval.** `GET /capabilities` is installed
   only when `JARVIS_HARNESS_API=1`, and uses the dashboard's existing bearer
   token authentication. `run_eval()` defaults to a local `RuleBasedJudge`;
   configured rules include equality, substring, regex, length, JSON, truthy,
   and exit-code checks. LLM judging is a network-free H4 stub.

## Effects and scope

Effects describe possible side effects (`read`, `write`, `delete`, `network`,
`subprocess`, `filesystem`, `desktop`, `approval`) and are separate from
`risk_class` (`read`, `write`, `destructive`). Scope is a descriptive boundary,
for example `filesystem:workspace`, `desktop:screen`, or `network:external`.
Legacy `capabilities.effects` values (`read`/`write`/`destructive`) are treated
as risk levels and converted to inferred effects.

## API/mobile surface

The versioned read-only payload is
`{"contractVersion": 1, "capabilities": [...]}`. The dashboard route is
available only when both `JARVIS_HARNESS=1` and `JARVIS_HARNESS_API=1` are set,
and requires its existing bearer token. No remote invocation, approval, or
event-stream endpoint is added.
There is no CLI contract exporter in H3; the opt-in dashboard route is the
selected API surface.

## Eval

Rules live under `eval.judge.rules` in `config/harness_policy.yaml`. A case can
select one with `metadata.rule`; `run_configured_eval()` uses the configured
default rule. Bare `run_eval()` uses the `RuleBasedJudge` but leaves a case
unevaluated (`ok=None`) when no local rule is selected, preserving H2 behavior.
The `LLMJudge` class requires `JARVIS_HARNESS_JUDGE_LLM=1` (the previous
`JARVIS_HARNESS_LLM_JUDGE=1` flag remains an alias), and requires an existing
adapter. Its `score()` is deliberately unimplemented and performs no network
calls; provider-backed judging is H4.

## Preserved H1/H2 behavior

- `ActionRegistry.risk_class()` and `risk_class_declared()` are unchanged.
- Existing `ToolCapabilities` remains available for legacy declarations.
- The default risk for an action with no explicit risk remains `write`.
- `run_eval()` without a selected rule leaves the case unjudged, as in H2.
- Harness loop adapters, confirmation delegation, replay consent, and
  metadata-only recovery are unchanged.

## H4

- Remote invocation (`POST /invoke`), mobile approval/push, and event delivery.
- Consensual replay UX and its authorization/audit lifecycle.
- A provider-backed `LLMJudge` with explicit adapter contracts and tests.
- Full JSON Schema or a deliberate dependency choice if richer schema features
  become necessary.
- Concurrency and soak testing before expanding API exposure.

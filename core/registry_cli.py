"""
Management CLI for connectors and skills.

    python -m core.registry_cli status
    python -m core.registry_cli connect <connector-id>        # prompts for the token
    python -m core.registry_cli grant <connector-id> <scope> [<scope> ...]
    python -m core.registry_cli revoke <connector-id>
    python -m core.registry_cli skill-diff <skill>
    python -m core.registry_cli skill-approve <skill> --reviewer <name>
    python -m core.registry_cli set-tripo-key                 # hidden prompt, for generate_3d_model
    python -m core.registry_cli set-3d-backend auto|local|tripo
    python -m core.registry_cli cache-3d list|size|clear       # inspect or clear local generation cache
    python -m core.registry_cli download-cad-models           # multi-part CAD models for explode_model
    python -m core.registry_cli reload_hud_states             # validate and notify running HUDs

Tokens are read with a hidden prompt, never from argv, and stored via SecretStore.
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.connectors import ConnectorError  # noqa: E402
from core.jarvis_runtime import BASE_DIR, Runtime, build_runtime  # noqa: E402
from core.skills import SkillError  # noqa: E402


def run(argv: list[str], runtime: Runtime | None, read_token: Callable[[str], str] = getpass.getpass) -> str:
    parser = argparse.ArgumentParser(prog="registry_cli")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    app_search = sub.add_parser("app-search")
    app_search.add_argument("name")
    for name in ("connect", "revoke"):
        sub.add_parser(name).add_argument("connector")
    grant = sub.add_parser("grant")
    grant.add_argument("connector")
    grant.add_argument("scopes", nargs="+")
    sub.add_parser("skill-diff").add_argument("skill")
    migrate = sub.add_parser("migrate-api-key")
    migrate.add_argument("--remove-plain", action="store_true")
    sub.add_parser("set-tripo-key")
    backend_cmd = sub.add_parser("set-3d-backend")
    backend_cmd.add_argument("backend", choices=("auto", "local", "tripo"))
    sub.add_parser("download-cad-models")
    sub.add_parser("reload_hud_states")
    cache = sub.add_parser("cache-3d")
    cache_sub = cache.add_subparsers(dest="cache_action", required=True)
    cache_sub.add_parser("list")
    cache_sub.add_parser("size")
    cache_clear = cache_sub.add_parser("clear")
    cache_clear.add_argument("--yes", action="store_true")
    sub.add_parser("patterns-list")
    sub.add_parser("patterns-delete").add_argument("id")
    patterns_clear = sub.add_parser("patterns-clear")
    patterns_clear.add_argument("--yes", action="store_true")
    approve = sub.add_parser("skill-approve")
    approve.add_argument("skill")
    approve.add_argument("--reviewer", required=True)
    args = parser.parse_args(argv)

    try:
        if args.command == "app-search":
            from actions import app_launcher
            if not app_launcher.enabled():
                return "error: app_launcher is disabled by JARVIS_APP_LAUNCHER=0"
            executable = app_launcher.find_executable(args.name)
            return str(executable) if executable else f"error: application '{args.name}' was not found"
        if args.command == "cache-3d":
            from core import local_3d_gen
            try:
                if args.cache_action == "list":
                    entries = local_3d_gen.cache_entries()
                    if not entries:
                        return "3D cache is empty"
                    return "\n".join(
                        f"{' '.join(str(entry.get('prompt') or '').split())[:160]} | "
                        f"{entry.get('backend', 'unknown')} | "
                        f"{entry.get('size_bytes', 0)} bytes | "
                        f"{entry.get('created_at', 'unknown')}"
                        for entry in entries
                    )
                if args.cache_action == "size":
                    size = local_3d_gen.cache_size_bytes()
                    return f"3D cache: {size} bytes ({size / 1024**2:.2f} MiB)"
                removed = local_3d_gen.clear_cache(confirmed=args.yes)
                return f"3D cache cleared ({removed} files removed)"
            except (OSError, ValueError) as exc:
                return f"error: {exc}"
        if args.command == "reload_hud_states":
            from core.hud_animator import HudAnimator, request_reload
            config_dir = BASE_DIR / "config"
            HudAnimator(config_dir).reload()
            request_reload(config_dir)
            return "HUD states validated; reload requested for running Jarvis instances."
        if args.command == "patterns-list":
            from core import pattern_learner
            try:
                patterns = pattern_learner.list_patterns()
            except (OSError, ValueError) as exc:
                return f"error: {exc}"
            if not patterns:
                return "No learned patterns"
            return "\n".join(
                f"{item['id']} | {item['type']} | {item['context']} | "
                f"{item['observation']} | confidence {item['confidence']:.2f} | "
                f"{item['occurrences']} occurrences | {item['last_seen']}"
                for item in patterns
            )
        if args.command == "patterns-delete":
            from core import pattern_learner
            try:
                deleted = pattern_learner.delete_pattern(args.id)
            except (OSError, ValueError) as exc:
                return f"error: {exc}"
            if not deleted:
                return f"error: pattern '{args.id}' not found"
            return f"{args.id}: deleted"
        if args.command == "patterns-clear":
            if not args.yes:
                return "error: this erases ALL learned patterns; run again with --yes to confirm"
            from core import pattern_learner
            try:
                removed = pattern_learner.clear()
            except (OSError, ValueError) as exc:
                return f"error: {exc}"
            return f"learned patterns cleared ({removed} patterns removed)"
        if args.command == "status":
            return json.dumps({"connectors": runtime.connectors.view(),
                               "skills": runtime.skills.view()}, indent=2, ensure_ascii=False)
        if args.command == "connect":
            descriptor = runtime.connectors.get(args.connector)
            token = "" if descriptor.auth == "none" else read_token(f"Token for {descriptor.name}: ")
            return f"{descriptor.id}: {runtime.connectors.authenticate(descriptor.id, token)}"
        if args.command == "grant":
            runtime.connectors.grant(args.connector, args.scopes)
            return f"{args.connector}: granted {', '.join(args.scopes)}"
        if args.command == "revoke":
            runtime.connectors.revoke(args.connector)
            return f"{args.connector}: revoked (dependent skills moved to review_required)"
        if args.command == "migrate-api-key":
            from core.api_keys import migrate
            result = migrate(BASE_DIR / "config", runtime.secrets, args.remove_plain)
            return result if result.startswith("error:") else f"gemini_api_key: {result}"
        if args.command == "set-3d-backend":
            from core import model_gen
            model_gen.set_backend(args.backend)
            return f"3D backend: {args.backend}"
        if args.command == "set-tripo-key":
            from core.model_gen import SECRET_NAME
            key = read_token("Tripo API key: ").strip()
            if not key:
                return "error: empty key, nothing stored"
            runtime.secrets.set(SECRET_NAME, key)
            return f"{SECRET_NAME}: stored in the SecretStore"
        if args.command == "download-cad-models":
            from core import cad_models
            results = cad_models.download_cad_models()
            lines = [f"{name}: {outcome}" for name, outcome in results.items()]
            try:
                from core import make_pc_cad
                lines.append(f"pc.glb: generated ({make_pc_cad.make_pc_cad().stat().st_size} bytes)")
            except RuntimeError as exc:
                lines.append(f"pc.glb: skipped ({exc})")
            if any(o.startswith("FAILED") for o in results.values()):
                return "error: some models failed\n" + "\n".join(lines)
            return "\n".join(lines) + "\nSaved in assets/viewer3d/models/cad/ (see NOTICE.txt there)."
        if args.command == "skill-diff":
            return json.dumps(runtime.skills.diff(args.skill), indent=2)
        runtime.skills.approve(args.skill, args.reviewer)
        return f"{args.skill}: approved by {args.reviewer}"
    except (ConnectorError, SkillError) as exc:
        return f"error: {exc}"


def main() -> int:
    argv = sys.argv[1:]
    standalone = {"app-search", "cache-3d", "patterns-list", "patterns-delete", "patterns-clear"}
    runtime = None if argv == ["reload_hud_states"] or (argv and argv[0] in standalone) else build_runtime()
    output = run(argv, runtime)
    print(output)
    return 1 if output.startswith("error:") else 0


if __name__ == "__main__":
    raise SystemExit(main())

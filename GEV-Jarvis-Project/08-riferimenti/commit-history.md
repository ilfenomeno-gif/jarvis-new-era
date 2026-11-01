# Commit history dell'integrazione

Output ricostruito con `git log --oneline --all`, `git log --stat -10`, `git log main..feat/gev-integration`, `git show` e `git diff main..feat/gev-integration`. Hash integrali dalla repo Jarvis locale.

| Hash | Tipo | Messaggio | Passo |
|---|---|---|---|
| `949e2ed114f83bf067ad9f1afbfde42a788e8835` | build | `build: pin PyQt6 and add QtWebEngine 6.11.0` | 1 |
| `a57413bb74c20400bbe0ff39dc50cf80f91a1dc8` | feat | `feat: add plugin lifecycle hooks` | 2 |
| `29c198de07ecbabbce95674d6028e7be5f3cc5d9` | feat(main) | `feat(main): wire shutdown signal for plugin lifecycle` | 3 |
| `4ecff3ac647ce8f311b47cf7045f1d3915be44ae` | security(guardrails) | `security(guardrails): whitelist node.exe for local GEV startup` | 4a prerequisito |
| `bbdcff8dc9cb2c2f950c8bdd90246ff84f6f4f5e` | feat(plugins) | `feat(plugins): gev_plugin lifecycle with portable Node runtime` | 4a |

## Base e ref

- `main` / merge-base: `b6bb1eddf46dfa8b6d30090185235d8840e1460e` — `Initial commit: Mark-LIV project with writing_assistant plugin`.
- Branch d'integrazione e Jarvis HEAD: `feat/gev-integration` / `bbdcff8dc9cb2c2f950c8bdd90246ff84f6f4f5e`.
- Branch GEV locale: `feat/gev-integration`, HEAD `aa16b7c3b0166a89d8c7a6089e0aff53a22faaee`; questo hash appartiene alla repo GEV, non alla sequenza di commit Jarvis.

L'ordine cronologico (dal log) è requirements, lifecycle plugin, main hooks, guardrail, plugin GEV. La working tree contiene un diff locale non committato a `plugins/gev_plugin.py`; non gli è attribuito un hash. I commit successivi di host/checkpoint sul branch non cambiano il fatto che il range `main..feat/gev-integration` contiene cinque commit funzionali.


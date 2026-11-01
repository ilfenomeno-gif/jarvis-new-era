# Verifica H — Guardrails

## Obiettivo

Controllare autorizzazione subprocess Node e vincolo sul runtime portatile.

## Cosa è stato verificato

`_ALLOWED_EXECUTABLES` include `node` e `node.exe` (`core/guardrails.py:23-33`); commit `4ecff3a`. Il plugin forma il percorso `.node/node.exe`, verifica che il file esista e confronta il percorso risolto con quello atteso (`plugins/gev_plugin.py:155-174`). La documentazione avverte che la whitelist vale per tutte le invocazioni Node subprocess Jarvis, mentre la restrizione al binario portatile è locale al plugin (`docs/GEV_INTEGRATION.md:18-36`).

## Come

- Lettura guardrail, plugin e documentazione.
- `git show 4ecff3ac647ce8f311b47cf7045f1d3915be44ae`.

## Risultato e stato

**Verificato staticamente**. Non è stata eseguita una prova che verifichi rifiuto di un Node di sistema, né una valutazione di tutte le chiamate subprocess possibili.

> Da verificare: copertura runtime della policy e test negativi/positivi del guardrail su Windows.


# Passo 0 — Pulizia/generazione Node portatile

## Obiettivo

Rendere disponibile il runtime Node nella cartella GEV `.node/`, necessaria al plugin (`plugins/gev_plugin.py:19-22`, `:155-174`).

## File/cartelle coinvolti osservati

- Checkout GEV: `.node/` esiste ma è segnalata non tracciata (`git status --short --branch`); `git check-ignore` non la segnala come ignorata, e `.gitignore:1` contiene invece la regola `node_modules`.
- Jarvis: il loader si aspetta `.node/node.exe` e `node_modules/npm/bin/npm-cli.js` (`plugins/gev_plugin.py:155-174`).

## Diff, commit, test

Nessun commit Jarvis dedicato alla generazione/rimozione del runtime è presente in `git log main..feat/gev-integration`. La directory GEV non tracciata non equivale a un'implementazione archivistica verificata.

> Da verificare: origine, versione e integrità di `.node/`; nessun comando di download/esecuzione è stato lanciato. Contrariamente a quanto ipotizzato nel commento dell'utente, il checkout esaminato non mostra una regola che ignori `.node/`.

Test eseguiti: nessuno. Versione Node richiesta dall'integrazione descritta qui: **> Da verificare**. Il package GEV dichiara `>=24.14.0 <25 || >=26 <27` (`package.json:17-19`).

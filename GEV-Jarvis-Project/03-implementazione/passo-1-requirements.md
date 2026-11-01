# Passo 1 — Requirements UI

## Obiettivo

Pin delle dipendenze PyQt6 e PyQt6-WebEngine.

## File toccati

- `requirements.txt`: PyQt6 e PyQt6-WebEngine entrambi pin `6.11.0` (`requirements.txt:1-2`).

## Modifica chiave e commit

Commit `949e2ed114f83bf067ad9f1afbfde42a788e8835` — `build: pin PyQt6 and add QtWebEngine 6.11.0`. Diff: da `PyQt6` non pin-nato alle due specifiche versionate, come attestato da `git show 949e2ed -- requirements.txt`.

## Test e note

Output test: non eseguiti in questa raccolta. Il pin non prova che WebEngine sia effettivamente usato nella UI (`ui.py:21-34`).

> Da verificare: install pulita e caricamento QWebEngine nell'ambiente desktop target.


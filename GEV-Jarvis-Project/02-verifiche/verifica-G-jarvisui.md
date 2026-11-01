# Verifica G — JarvisUI

## Obiettivo

Verificare API wrapper `JarvisUI`, costruzione della finestra e possibilità di inviare messaggi alla pagina GEV.

## Cosa è stato verificato

`JarvisUI` crea o riusa `QApplication`, istanzia `MainWindow` e la mostra (`ui.py:4156-4162`). Il wrapper espone callbacks, logging, widget e segnali UI (`ui.py:4177-4258`, `:4260-4332`). `MainWindow` eredita `QMainWindow` (`ui.py:2379`) e crea la finestra HUD. Non è stato trovato `send_to_gev`, `QWebEngineView` o un bridge postMessage nei file UI/main cercati.

## Come

- Lettura `ui.py:21-34`, `:2379-2410`, `:4156-4332`.
- Ricerca `send_to_gev`, `QWebEngine`, `QWebChannel`, `postMessage` in `ui.py` e `main.py`.

## Risultato e stato

**Verificato**: framework e API esistente. **Non verificato**: che nessun modulo esterno alla UI implementi un bridge; la ricerca limitata all'integrazione principale non sostituisce un audit globale.

> Da verificare: dove e con quale contratto si collegherebbe l'azione dispatcher alle API `gev:view` di GEV.


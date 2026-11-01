# Verifica A — Framework UI

## Obiettivo

Accertare framework UI Jarvis e disponibilità di componenti WebEngine.

## Cosa è stato verificato

**Verificato nel codice**: `ui.py` importa PyQt6 QtCore, QtGui e QtWidgets; `JarvisUI` istanzia `QApplication` e `MainWindow`. `requirements.txt` pinna sia `PyQt6==6.11.0` sia `PyQt6-WebEngine==6.11.0`. Nel blocco import UI osservato non compare `QWebEngineView`.

## Come

- Letti `ui.py:21-34`, `ui.py:4156-4162`, `requirements.txt:1-2`.
- Consultata la storia: commit `949e2ed114f83bf067ad9f1afbfde42a788e8835` (“build: pin PyQt6 and add QtWebEngine 6.11.0”).
- Ricerca testuale nel file `ui.py` per `QWebEngine`.

## Risultato e stato

**Verificato**: UI desktop PyQt6. **Non verificato**: effettivo uso del pacchetto WebEngine o embed di GEV in una finestra Jarvis. L'assenza di import nel file letto non dimostra che nessun altro modulo carichi QtWebEngine.

> Da verificare: se l'architettura prevista richiede un `QWebEngineView` embedded oppure una finestra browser separata.


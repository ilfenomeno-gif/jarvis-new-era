# M02 — Active web interaction

## Obiettivo

Consentire a Jarvis di premere tasti whitelisted e cliccare link visibili per
testo nella pagina del browser integrato, senza permettere script injection o
accessi Qt fuori dal thread GUI.

## 1. Diagnosi (stato reale del repo, rischi, dipendenze)

- M1 implementa `JarvisUI.open_url_in_webview`, signal Qt e
  `MainWindow._browser_view` / `_browser_page`; la navigazione live è ancora
  bloccata, ma il codice è presente nel branch di base M2.
- `actions/browser_control.py` usa Playwright per browser esterni e
  `actions/computer_settings.py` usa PyAutoGUI per il desktop; nessuno dei due
  fornisce gli strumenti limitati al browser QWebEngine integrato.
- La UI possiede `_browser_view`; le richieste Gemini/async devono inviare
  segnali Qt e gli slot GUI sono l'unico punto autorizzato a toccare il widget.
- `QWebEnginePage.runJavaScript` è già usato per il bridge GEV, ma il browser
  integrato non esegue JS fornito dall'utente. Ogni testo tasto/link va
  serializzato con `json.dumps`.
- Il DOM di una pagina arbitraria è non attendibile; un link testuale ambiguo
  non deve portare a un click casuale. Gli eventi JS sono `isTrusted=false`;
  il fallback Qt è disponibile quando il dispatch JS fallisce, ma non si può
  osservare in modo generale se un gioco ignora silenziosamente un evento.

## 2. Procedura (sotto-passi atomici: file → modifica → criterio di successo)

1. `core/browser_interaction.py` → canonicalizzare chiavi whitelistate e
   costruire script keyboard/link con parametri JSON. Criterio: unit test per
   mapping, rifiuti e input di click contenente virgolette/caratteri speciali.
2. `ui.py` → aggiungere signal `press_key`/`click_link`, slot GUI e fallback
   `QTest.keyClick` sul QWebEngineView focalizzato. Criterio: nessun accesso ai
   widget dal thread del tool; mancato/ambiguo link riportato esplicitamente.
3. `main.py` → dichiarare tool Gemini `press_key(key)` e
   `click_link(link_text)` e instradarli nel wrapper signal. Criterio: nomi e
   schema richiesto non collidono con tool esistenti.
4. `tests/test_browser_interaction.py` → verificare whitelist, escaping JSON,
   payload e tool declarations senza avviare un WebEngine Qt isolato.
5. Aggiornare `PROGRESS.md` e registro esecuzione con test ed evidenza runtime
   effettivamente disponibile.

## 3. Modifiche per file

- `core/browser_interaction.py` (nuovo): whitelist, normalizzazione tasti,
  payload JSON per KeyboardEvent e ricerca link visibile.
- `ui.py`: signal/slot, focus del browser, `runJavaScript`, click e fallback
  QTest sul thread GUI.
- `main.py`: function declarations e dispatch per `press_key` e `click_link`.
- `tests/test_browser_interaction.py` (nuovo): test parser/script/schema.
- `docs/impl/M02-web-interaction.md`, `PROGRESS.md`: piano e recap.

## 4. Test plan (automatici + manuali)

- Chiavi ammesse: frecce (nomi e alias), spazio, invio, ESC, A–Z; verifica
  `key`, `code`, `keyCode` e coppia `keydown`/`keyup`.
- Rifiuti: stringa vuota, tasti non ammessi, combinazioni/controlli.
- Link: escaping `json.dumps` per apici, doppi apici, newline e payload simili
  a codice; nessun match non visibile; testo ambiguo non clicca.
- Verifica dispatch signal wrapper e declarations Gemini via test.
- Regression: suite Jarvis e `compileall`; smoke app/GEV. Servire
  `tests/fixtures/`, aprire `http://127.0.0.1:<porta>/snake.html`, premere le
  frecce e osservare il canvas/la posizione della testa; aprire
  `page_simple.html` e cliccare `Leggi pagina successiva`. Usare Jarvis reale,
  non un harness Qt isolato. Provare separatamente il fallback su una pagina
  che ignora gli eventi JS sintetici.

## 5. Criteri di accettazione (checklist PASS/FAIL)

- [ ] Su `http://127.0.0.1:<porta>/snake.html`, i comandi freccia muovono lo
  Snake nel canvas 20x20; game over e Restart sono disponibili.
- [ ] Su `http://127.0.0.1:<porta>/page_simple.html`, cliccare
  `Leggi pagina successiva` apre la pagina locale corretta.
- [x] Input con virgolette/apici/caratteri speciali è JSON-escaped nei payload
  generati e non interpolato come codice.
- [x] Tasto fuori whitelist viene rifiutato con errore; richiesta widget
  attraversa signal Qt e lo slot fa l'accesso GUI.
- [ ] Fallback Qt/QTest funziona su una pagina che ignora eventi JS sintetici.
- [ ] GEV e tool browser esterni non regrediscono.

**Esito criteri:** PASS parziale. I criteri unit-testabili di whitelist,
payload/escaping, signal e fallback su errore di dispatch sono verificati;
Snake/click effettivi, fallback su pagina che ignora eventi e smoke GEV live
restano non verificati.

## 6. Analisi di fattibilità del presente file (checklist GO/NO-GO + esito)

- [x] `JarvisUI`, signals, QWebEngineView, `runJavaScript` e tool dispatcher
  esistono; helper/test nuovi sono marcati come da creare.
- [x] PyQt6 QtTest è incluso nel pacchetto PyQt6 già installato.
- [x] M2 si limita al browser integrato; non modifica i tool Playwright/desktop
  né il bridge GEV.
- [x] Test automatici puri eseguibili senza avviare un nuovo processo
  QWebEngine, dato il crash nativo dei precedenti harness.
- [x] Rollback definito.

**Esito: GO.**

## 7. Rollback (come tornare indietro)

Usare commit inversi del branch `feat/m02-web-interaction` in ordine; non
modificare i commit M0/M1, non cancellare configurazioni, non forzare push.

## 8. Registro esecuzione (data, esito verifica, esito convalida)

- 2026-10-04: diagnosi sui sorgenti reali; GO prima dell'implementazione.
- 2026-10-04: implementati helper, declarations Gemini, wrapper signal, slot
  Qt e fallback QTest. `pytest -q`: 99 passed; `compileall` sui file Python
  modificati: PASS; Problems/Pylance: nessun errore; `git diff --check`: PASS.
- 2026-10-05: criteri live aggiornati alle fixture locali Snake e link; prova
  nell'app non eseguita perché non c'era un processo Jarvis attivo e Gemini
  non è stato convalidato.
- 2026-10-05: suite cumulativa `pytest -q`: 115 passed; fixture servite
  correttamente via HTTP locale, ma nessun tasto/link è stato provato nel
  browser integrato.
- Convalida manuale: BLOCKED; nessun processo Jarvis/Gemini attivo durante il
  controllo e il runtime WebEngine live ha il blocker nativo registrato in M1.
  Il listener 4173 osservato appartiene a `node`; non è stato avviato un
  secondo server GEV.

## 9. Recap finale

Implementata l'interazione attiva del browser integrato in modo fail-closed
per chiavi non consentite e link ambigui. Le fixture locali rendono ripetibili
Snake e click; M2 resta BLOCKED finché i criteri non sono osservati nel Jarvis
live.

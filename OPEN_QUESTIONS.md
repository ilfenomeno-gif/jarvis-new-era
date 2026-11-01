# Open questions

## Preflight e stato osservato — 2026-10-05

- Checkout confermato dall'utente come `ilfenomeno-gif/jarvis-ultimate`;
  storia locale e remote canonico condividono la base GEV `419fc90`. I remote
  configurati `origin`/`upstream` puntano però a `donnadonna9911-afk/jarvis`,
  mentre `myfork` punta a `ilfenomeno-gif/jarvis`; nessun alias è stato
  modificato e non vanno usati per push.
- Baseline L1 `python -m pytest -q`: 125 passed.
- `config/api_keys.json` e `.env.local` sono ignorati; `.env.local` è
  presente ma non è stato letto. Nessuna credenziale trasmessa.
- Gemini: ultimo indicatore disponibile è il log storico `startup_stdout.log`
  del 2026-09-08 con `Connecting...`; nessun `JARVIS online` corrente
  osservato. L'utente deve fornire l'esito della diagnostica diretta e della
  sessione Live senza chiavi o log contenenti segreti.
- M1 ha raggiunto L2: fixture HTTP locali servite e URL non sicuro rifiutato.
  L3 richiede prova visiva dell'utente nell'app; L4 richiede Gemini/microfono.

## Gemini — connessione Live (blocco trasversale M1-M3)

- Il repository carica la credenziale da `config/api_keys.json`; il campo è
  stato verificato presente senza leggerne o stamparne il valore. `.env.local`
  esiste ma non è stato aperto.
- La chiamata diretta autenticata a Gemini non è stata eseguita: validità
  della chiave e accessibilità del modello non sono confermate. Non dichiarare
  la chiave scaduta senza un errore di autenticazione osservato; se Jarvis lo
  mostra, l'utente deve rigenerarla.
- Il modello Live configurato nel sorgente è
  `models/gemini-2.5-flash-native-audio-preview-12-2025`. Non c'era un processo
  Jarvis attivo né un log recente `JARVIS online`; disponibilità corrente del
  modello non verificata tramite una sessione autenticata. La documentazione
  pubblica Gemini lo elenca ancora tra i modelli Live e non lo marca come
  deprecato; raccomanda Gemini 3.8 Live come default per nuove integrazioni.
  Fonte: https://ai.google.dev/gemini-api/docs/models e
  https://ai.google.dev/gemini-api/docs/live-api/capabilities.
- Per riprovare: avviare Jarvis e controllare localmente la connessione senza
  copiare chiavi o log che le contengano. Se il log riporta modello non
  disponibile, aggiornare a un modello Live stabile supportato e annotare il
  cambio in `PROGRESS.md`.

## M0 — Baseline

- La finestra Jarvis e il plugin GEV sono stati osservati all'avvio; la
  connessione Gemini era ancora in stato `Connecting...` al termine
  dell'osservazione. Il backend audio MME ha segnalato che l'output host non
  produceva audio e lo ha saltato. Ripetere una verifica funzionale vocale/audio
  dopo i cicli UI; non si presume che l'audio funzioni.
- Qt ha emesso `SetProcessDpiAwarenessContext() failed: Accesso negato`; la
  finestra è stata comunque enumerata e il processo è rimasto attivo. Registrato
  come warning baseline, da distinguere da eventuali regressioni.

## M4 — NVIDIA (scelta utente)

Scelta confermata: **C — nvidia-smi / monitoraggio GPU**, implementata sul
branch locale `feat/m4-gpu-monitor`. La convalida vocale live è ancora bloccata
dal mancato accertamento dello stato Gemini e richiede la prova dell'utente.
Il vecchio branch `feat/m04-moonlight-sunshine` è **SCARTATO**, resta intatto e
non va unito.

## M1 — Convalida browser integrato (bloccante)

- L2 PASS: `normalize_http_url` e server loopback hanno caricato le fixture
  `page_simple.html` e `page_simple_2.html` con HTTP 200; schema JavaScript
  rifiutato.
- L3 non eseguito: manca la prova visiva dentro il pannello QWebEngine
  nell'app Jarvis (titolo, cronologia, controlli e redirect). Richiede
  l'intervento dell'utente sulla finestra.
- L4/Gemini: non verificato in questa sessione. L'indicatore `Connecting...`
  disponibile è in un log storico del 2026-09-08; nessuna chiamata
  autenticata è stata fatta dall'agente.

**Azione:** avviare Jarvis, verificare localmente `JARVIS online`, quindi
servire `tests/fixtures/` (porta stampata da `python tests/serve_fixtures.py`)
e verificare nella finestra i criteri L3 in
`docs/impl/M01-integrated-browser.md`: pagina semplice, link, back/forward/
reload/close e redirect. Riferire solo esito, senza segreti/log sensibili.

Stato: IMPLEMENTATA – NON CONVALIDATA (raggiunto L2); il codice resta sul
branch M1 e non va unito prima del PASS UI richiesto.

## M2 — Convalida interazione browser (bloccante)

- I test automatici verificano whitelist, payload JavaScript JSON-escaped,
  wrapper signal, schema tools e fallback `QTest` quando il dispatch JavaScript
  fallisce.
- Le fixture locali esistono, ma non è stato verificato il comportamento in
  una pagina reale: nessuna sessione Jarvis/Gemini era attiva nel controllo.
- Un dispatch JavaScript riuscito non dimostra che un gioco accetti l'evento
  sintetico (`isTrusted=false`); il fallback Qt scatta solo su fallimento del
  dispatch, per evitare doppie pressioni non sicure.

**Azione di convalida futura:** con Jarvis e GEV/browser funzionanti, servire
le fixture e testare Snake, link visibile e fallback su pagina che richiede
input `isTrusted`; verificare che link ambiguo/non trovato non venga cliccato.

Stato: BLOCKED; non serve una scelta per proseguire con M3.

## M3 — Convalida voce screen reader (bloccante)

- I test coprono testo vuoto/lunghissimo, limite di estrazione, chunk <=800,
  worker separato, richiesta stop, engine fake pilotato solo dal thread worker
  e callback che sopprime l'audio Gemini.
- `pyttsx3` è importabile nell'interprete selezionato; il backend audio host
  della baseline però è stato saltato perché non produceva audio. Non è stata
  eseguita sintesi reale, perciò la risposta del dispositivo e l'interruzione
  audio in tempo reale con il driver Windows non sono note.
- Le fixture per testo lungo/vuoto sono disponibili, ma la lettura dipende dal
  browser M1 e da un dispositivo audio funzionante; nessuna prova live è stata
  eseguita.

**Azione di convalida futura:** con audio funzionante e una pagina aperta in
Jarvis, verificare lettura fluida, GUI reattiva, stop entro pochi secondi e
assenza di voce Gemini sovrapposta. Verificare pagina vuota e testo lungo anche
nel browser; i test unitari coprono già le funzioni di limite.

Stato: BLOCKED; nessuna nuova credenziale è richiesta, si può passare alla
scelta M4.

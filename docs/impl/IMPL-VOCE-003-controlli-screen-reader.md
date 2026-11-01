# IMPL-VOCE-003 — Navigazione del lettore schermo

Stato: IMPLEMENTATA-NON-VALIDATA — test automatici completati; GUI live aperta
Branch: `feat/voice-reader-navigation`

## 1. Diagnosi (F1)

Il lettore pagine esistente estrae solo il testo completo del DOM. Non dispone di
modalità per titoli, link visibili o testo selezionato. Lo stop è già disponibile.
Il TTS Kokoro configurabile è implementato nella meccanica VOCE-001; manca una
scelta della velocità nell'interfaccia.

Stato: **PARZIALE**. Worker, estrazione pagina e stop sono presenti; la navigazione
semantica del DOM e la velocità selezionabile sono assenti.

## 2. Procedura (F2)

1. Aggiungere quattro modalità DOM fisse: pagina, titoli, link e selezione.
2. Rifiutare modalità non riconosciute prima di inoltrare il comando alla UI.
3. Collegare la modalità al tool `read_page` e al worker esistente, senza inserire
   contenuti DOM nel codice JavaScript.
4. Aggiungere una selezione di velocità locale per Kokoro, con `1.0x` predefinito.
5. Testare costruzione script, limite testo, tool e persistenza della velocità.

## 3. Verdetto (F4)

**GO**. Le modifiche riusano WebEngine, `PageSpeechWorker` e configurazione locale.
Gli script sono scelti da una allowlist statica; nessun click o invio di dati DOM a
servizi esterni viene aggiunto.

## 4. Criteri di accettazione

| Criterio | Esito |
|---|---|
| `read_page` supporta pagina, titoli, link e selezione | OK — test del tool/UI e script DOM |
| Modalità non ammesse vengono rifiutate | OK — allowlist e test unitario |
| L'estrazione mantiene il limite di 20.000 caratteri | OK — script testato |
| Velocità Kokoro selezionabile e persistente, default `1.0x` | OK — persistenza testata; non verificata con sintesi reale |
| DOM dinamico, resa vocale e usabilità in GUI | DA VALIDARE LIVE |

## 5. Implementazione e verifica (F5-F6)

- `core/page_reader.py`: script DOM statici per pagina, titoli visibili, testi dei
  link visibili e selezione; limiti applicati prima della segmentazione.
- `main.py`: parametro opzionale `mode` dichiarato con enumerazione sul tool
  `read_page`; valori inattesi sono rifiutati.
- `ui.py`: modalità instradata al worker esistente; stop e gate audio invariati.
- `memory/config_manager.py`: velocità locale `0.75x`, `1.0x`, `1.25x` o `1.5x`,
  conservata in `config/voice_settings.json`; input fuori allowlist rifiutati.
- Test aggiornati in `tests/test_page_reader.py` e `tests/test_voice_settings.py`.

Output reale:

| Verifica | Esito |
|---|---|
| `pytest -q` | `149 passed in 1.60s` |
| `compileall` dei file modificati | PASS |
| `git diff --check` | PASS |

## 6. Convalida manuale (F7)

1. Aprire una pagina con titoli e link; dire **«Leggi i titoli della pagina»**.
   Devono essere letti solo i titoli visibili.
2. Dire **«Leggi i link della pagina»**. Devono essere pronunciati i testi dei link
   visibili, senza navigare.
3. Selezionare una frase nella pagina e dire **«Leggi il testo selezionato»**.
   Deve essere letta solo la selezione.
4. Dire **«Leggi la pagina»**, poi **«Smetti di leggere»**. La lettura deve
   interrompersi.
5. Selezionare `KOKORO NEURAL`, impostare una velocità e riavviare Jarvis.
   La velocità deve restare configurata.

## 7. Recap (F8)

Ancora da completare.

## 8. Rollback

Ripristinare le modifiche a `read_page` e la preferenza di velocità al default.
Rimuovere solo i test/documenti di questa meccanica. Nessuna pagina o selezione è
scritta su disco.

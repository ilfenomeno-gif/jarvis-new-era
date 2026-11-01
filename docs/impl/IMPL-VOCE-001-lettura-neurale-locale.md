# IMPL-VOCE-001 — Lettura pagina con TTS neurale locale

Stato: IMPLEMENTATA-NON-VALIDATA — verifica automatica completata; prova live aperta
Branch: `feat/voice-neural-reader`

## 1. Obiettivo e diagnosi (F1)

Integrare il motore neurale Kokoro già presente nel lettore pagine Jarvis, mantenendo
`pyttsx3` come comportamento predefinito e senza inviare il testo delle pagine a
servizi cloud.

Evidenze nel codice:

- `core/tts.py` contiene `KokoroTTSEngine`, ma non è collegato al lettore né dispone
  di un percorso di cancellazione.
- `core/page_reader.py` limita il testo a 20.000 caratteri, lo divide in blocchi e
  gestisce l'arresto del backend.
- `ui.py` crea `PageSpeechWorker` senza una factory, quindi usa `Pyttsx3Backend`.
- `core/accessibility.py` fornisce il backend locale di sistema.
- I test di `tests/test_page_reader.py` coprono chunking, arresto e segnali, ma non
  l'integrazione Kokoro.

Stato: **PARZIALE**. La sintesi neurale locale esiste; il lettore non la può
selezionare e non può interromperla durante la riproduzione.

## 2. Procedura (F2)

1. Aggiungere un'impostazione esplicita in `config/voice_settings.json` (esclusa da
   Git), con valori ammessi `system` e `kokoro`; mantenere `system` come default e
   non modificare il file delle API key.
2. Riutilizzare `KokoroTTSEngine` e aggiungere cancellazione cooperativa della
   sintesi/riproduzione, senza bloccare il thread GUI.
3. Collegare la scelta all'interfaccia di personalizzazione e al `PageSpeechWorker`.
4. Aggiungere test unitari per scelta predefinita, scelta Kokoro, invalidazione dei
   valori e interruzione della riproduzione simulata.
5. Eseguire compilazione e suite richieste; annotare come `DA VALIDARE LIVE` il
   download iniziale del modello, il dispositivo audio e la qualità percepita.

## 3. Fattibilità (F4)

**GO CON MODIFICHE**:

- Si riutilizza il modello Kokoro già presente, senza introdurre servizi a pagamento
  o nuove dipendenze.
- `system` resta il default per non cambiare il comportamento esistente.
- Il modello Kokoro può richiedere un download iniziale di circa 330 MB quando
  l'utente seleziona esplicitamente quel backend; la prova di download non sarà
  avviata automaticamente durante sviluppo e test.
- L'arresto è verificabile con un motore audio simulato; il comportamento hardware
  resta da validare live.

## 4. Criteri di accettazione (F7)

| Criterio | Esito |
|---|---|
| Senza preferenza configurata il lettore usa `pyttsx3` come prima | OK — test unitario della factory |
| Il motore Kokoro riceve voce e velocità configurate | OK — factory simulata; nessuna sintesi o rete invocata |
| `stop_reading` interrompe la riproduzione Kokoro in corso | OK — playback simulato; da confermare con dispositivo audio |
| Valori di configurazione non ammessi non attivano motori imprevisti | OK — test unitari su factory e persistenza |
| La preferenza non tocca `api_keys.json` ed è esclusa da Git | OK — test su file temporaneo e `.gitignore` |
| GUI, dispositivo audio, download iniziale modello e qualità voce | DA VALIDARE LIVE |

## 5. Implementazione e verifica (F5-F6)

- `core/page_reader.py`: factory guidata da impostazione locale; default `system`;
  voce non vuota e velocità limitata a 0,5–2,0 per Kokoro.
- `core/tts.py`: cancellazione cooperativa, interruzione di `sounddevice` e
  propagazione degli errori di sintesi/riproduzione.
- `core/accessibility.py`: factory estesa per riutilizzare `KokoroTTSEngine`.
- `memory/config_manager.py` e `.gitignore`: preferenza `config/voice_settings.json`
  separata dalle API key e ignorata da Git.
- `ui.py`: selezione del backend nella finestra Customize; `system` rimane default.
- Test aggiunti in `tests/test_page_reader.py` e `tests/test_voice_settings.py`.

Output raccolti con Python 3.13.7 nel virtualenv del progetto:

| Verifica | Output reale |
|---|---|
| `pytest -q` | `129 passed in 1.61s` |
| `compileall` dei file Python modificati | PASS |
| `compileall .` | FALLITO su `.venv/Lib/site-packages/mediapipe/tasks/python/test/text/text_embedder_test.py:113`, carattere U+2202 non valido; file nel virtualenv, non modificato |
| `unittest discover -s tests -v` | `Ran 0 tests`; exit code 5. La suite effettiva usa pytest. |
| `git diff --check` | PASS, nessun errore di whitespace |

## 6. Convalida live (F7)

La feature è **DA VALIDARE LIVE** per interfaccia Qt effettiva, installazione/modello
Kokoro, output audio, lingua/qualità e stop su dispositivo reale. Il test mock non
prova questi aspetti.

Checklist manuale:

1. Aprire **Customize**, lasciare `SYSTEM VOICE (offline)`, applicare e verificare
   che `config/voice_settings.json` riporti `system`.
2. Selezionare `KOKORO NEURAL`, leggere l'avviso sul download iniziale del modello,
   applicare e verificare che `config/voice_settings.json` riporti `kokoro`.
3. Aprire una pagina locale con testo e dire: **«Leggi ad alta voce la pagina»**.
   Attendere la fine dell'eventuale setup/modello e verificare che il testo venga
   letto senza bloccare la GUI.
4. Durante la lettura dire: **«Smetti di leggere»**. La riproduzione deve fermarsi,
   la GUI restare reattiva e il gate audio tornare inattivo.
5. Tornare a **Customize**, selezionare `SYSTEM VOICE (offline)` e ripetere lettura
   e arresto per verificare il default/fallback locale.

## 7. Recap (F8)

Completata l'integrazione software del TTS Kokoro nel lettore pagine, con
configurazione opt-in, persistenza separata dalle credenziali, arresto simulato e
test automatici. La qualità e il funzionamento su hardware restano non validati;
la meccanica non è dichiarata `VALIDATA`. Nessun push è stato eseguito.

## 8. Rollback

Ripristinare la preferenza `page_reader_engine` a `system`. Rimuovere i soli
collegamenti e test aggiunti per questa meccanica; non eliminare il motore Kokoro
preesistente né modificare configurazioni o credenziali dell'utente.

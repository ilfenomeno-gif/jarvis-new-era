# IMPL-VOCE-004 — Dettatura offline con revisione

Stato: IMPLEMENTATA-NON-VALIDATA — test automatici completati; prova microfono aperta
Branch: `feat/voice-offline-dictation`

## 1. Diagnosi (F1)

`core/stt.py` contiene `WhisperSTT` e `VoskSTT`, ma il flusso microfono attivo non li
usa. In `main.py` i frame sono inviati a Gemini Live; non esiste una sessione locale
di dettatura. Il test di ambiente ha verificato che `faster_whisper` e `vosk` non
sono installati nel virtualenv attivo.

Stato: **PARZIALE**. I motori offline esistono nel codice; manca acquisizione e
presentazione sicura di una trascrizione.

## 2. Procedura (F2)

1. Aggiungere buffer RAM di lunghezza massima 60 secondi, consumato dal callback
   microfono quando l'utente attiva il pulsante dedicato.
2. Sospendere l'invio a Gemini durante quella cattura.
3. Trascrivere in thread separato con Whisper in modalità cache-only: mai installare
   pacchetti o scaricare modelli automaticamente.
4. Inserire il testo trascritto nel campo comando Jarvis, senza inviarlo né
   iniettarlo in altre applicazioni. Consentire revisione/correzione manuale.
5. Scartare l'audio dalla RAM dopo la trascrizione e testare limiti, lifecycle e
   percorso senza pacchetto/modello.

## 3. Verdetto (F4)

**GO CON MODIFICHE**. L'integrazione è locale e limitata; `WhisperSTT` deve accettare
`local_files_only=True` per impedire download involontari. L'app non installa le
dipendenze né i pesi del modello. Se manca uno di questi prerequisiti, la dettatura
deve fallire esplicitamente e lasciare disponibile l'input testuale.

## 4. Criteri di accettazione

| Criterio | Esito |
|---|---|
| L'audio catturato è limitato a 60 secondi e volatile | OK — buffer unit test |
| Durante la dettatura i frame non vengono inoltrati a Gemini | OK — route unit test |
| La trascrizione usa Whisper in cache-only | OK — mock verifica una sola costruzione local-only |
| Il risultato è revisionabile prima dell'invio | OK — campo comando riempito, nessun invio automatico |
| Assenza di Whisper/modello produce errore esplicito | OK — errore propagato a UI; non installa/download |
| Accuratezza, microfono e tempi reali | DA VALIDARE LIVE |

## 5. Implementazione e verifica (F5-F6)

- `core/stt.py`: buffer int16 mono con limite di 60 secondi, acquisizione volatile,
  conversione a float32 e cancellazione; route locale che non inoltra i frame
  durante la dettatura.
- `WhisperSTT` supporta `local_files_only=True`; il percorso di dettatura non
  tenta retry o download. Vosk resta disponibile ma non collegato alla UI.
- `main.py`: pulsante esplicito usa lo stesso flusso microfono, sospende l'upload
  Gemini, trascrive in un thread di lavoro e azzera il buffer audio al termine.
- `ui.py`: pulsante start/stop nel drawer; la trascrizione viene inserita nel
  campo comando per revisione, senza invio automatico.
- Alla chiusura o riconnessione del flusso microfono, una cattura in corso viene
  scartata.
- Ambiente rilevato: né `faster_whisper` né `vosk` risultano installati; non è
  stata avviata alcuna installazione o richiesta di download modello.

Output reale:

| Verifica | Output |
|---|---|
| `pytest tests/test_stt.py tests/test_wake_word.py tests/test_voice_settings.py -q` | `27 passed in 0.30s` |
| `pytest -q` | `158 passed in 1.55s` |
| `compileall` dei file modificati | PASS |
| `unittest discover -s tests -v` | `Ran 0 tests`; exit code 5. Il repository usa pytest. |
| `git diff --check` | PASS |

## 6. Convalida manuale (F7)

1. Con un modello Whisper già installato nella cache locale e `faster-whisper`
   disponibile, attivare **OFFLINE DICTATION**.
2. Dettare una frase innocua, per esempio: **«La riunione è alle tre»**; fermare la
   cattura.
3. Verificare che il testo venga mostrato nel campo comando e non sia inviato fino
   alla pressione esplicita di **Invia**.
4. Ripetere senza modello/package: deve comparire l'errore local-only e i frame
   non devono essere inoltrati a Gemini durante la cattura.

## 7. Recap (F8)

Funzionalità implementata con salvaguardia local-only e revisione esplicita. I test
non provano riconoscimento o microfono; il package Whisper e il modello locale non
sono presenti nell'ambiente. Nessun audio o transcript è scritto su disco; nessun
push eseguito.

## 8. Rollback

Disattivare il pulsante di dettatura; i frame non salvati in RAM si eliminano al
termine o all'arresto. Nessun file audio viene creato.

# IMPL-VOCE-002 — Wake word locale opt-in

Stato: IMPLEMENTATA-NON-VALIDATA — verifica automatica completata; prova live aperta
Branch: `feat/voice-wake-word`

## 1. Obiettivo e diagnosi (F1)

Integrare il rilevatore locale `openwakeword` già presente, senza attivarlo per
default e senza inviare al modello Gemini i frame audio raccolti prima della
rilevazione.

Evidenze nel codice:

- `core/wake_word.py` implementa installazione esplicita, download del modello,
  coda limitata e inferenza in thread separato.
- Nessuna chiamata a `WakeWordDetector` esiste in `main.py` o `ui.py`.
- `main.py::_listen_audio` invia i frame del microfono a Gemini in modo continuo,
  eccetto quando Jarvis parla, l'utente silenzia l'audio o è attivo il telefono.
- La frequenza microfono di invio è 16 kHz, la stessa dichiarata dal rilevatore.
- `CustomizeOverlay` e `config/voice_settings.json` supportano ora impostazioni
  vocali locali, ma non ancora la wake word.

Stato: **PARZIALE**. Detector presente ma non integrato; il flusso audio resta
sempre aperto verso Gemini.

## 2. Procedura (F2)

1. Salvare `wake_word_enabled` come opt-in predefinito falso, nello stesso file
   locale ignorato da Git.
2. Aggiungere in Customize un toggle esplicito e un pulsante distinto per
   installare pacchetto/modelli; nessuna installazione o rete all'avvio.
3. Integrare il gate nel callback microfono: frame pre-rilevazione restano in un
   buffer RAM limitato, passano a Gemini solo dopo la parola d'attivazione e il
   gate si richiude a `turn_complete`.
4. Se il detector o i modelli non sono disponibili, mantenere il microfono remoto
   chiuso e segnalare l'errore; i comandi testuali restano utilizzabili.
5. Testare gate, buffer limitato, chiusura/riapertura e persistenza con mock.

## 3. Fattibilità (F4)

**GO CON MODIFICHE**:

- Si riutilizzano detector e helper di installazione esistenti.
- La modalità è opt-in e il valore predefinito non cambia il flusso Live attuale.
- Il pulsante di setup è l'unico percorso che invoca `pip` o scarica modelli.
- L'audio pre-rilevazione è volatile, in RAM e limitato; nessuna registrazione su
  disco.
- Il test automatico non sostituisce la prova del microfono reale, la latenza di
  rilevazione o la verifica che il comando successivo venga riconosciuto.

## 4. Criteri di accettazione (F7)

| Criterio | Esito |
|---|---|
| Modalità disattivata mantiene il percorso microfono precedente | DA VERIFICARE |
| Modalità attiva non invia audio prima della rilevazione | DA VERIFICARE |
| Dopo la rilevazione il buffer volatile è trasmesso e il gate si richiude al turno | DA VERIFICARE |
| Detector/modello non disponibile non apre il flusso remoto | DA VERIFICARE |
| Installazione/download richiedono l'azione esplicita del pulsante | DA VERIFICARE |
| Microfono, wake phrase, latenza e comando completo | DA VALIDARE LIVE |

## 5. Implementazione e verifica (F5-F6)

- `config/voice_settings.json`: opt-in `wake_word_enabled`, default `false`;
  preferenza locale esclusa da Git.
- `ui.py`: checkbox di opt-in e pulsante separato per installare `openwakeword` e
  scaricare esplicitamente i modelli; il lavoro avviene fuori dal thread GUI.
- `core/wake_word.py`: `WakeWordAudioGate` mantiene solo un buffer RAM limitato
  (massimo 20 frame) e non inoltra audio finché il detector non segnala la phrase.
- `main.py`: il detector viene avviato solo su opt-in; gate non pronto significa
  audio PC non inviato a Gemini; il gate si riapre a ogni `turn_complete`.
- Test aggiunti per buffer limitato, pre-detection, re-arm, detector indisponibile,
  default opt-out e persistenza.

Verifiche reali:

| Comando | Output |
|---|---|
| `pytest tests/test_wake_word.py tests/test_voice_settings.py tests/test_page_reader.py -q` | `33 passed in 0.41s` (before final wake UI test addition) |
| `pytest -q` | `136 passed in 1.48s` |
| `compileall` dei file modificati | PASS |
| `git diff --check` | PASS |

La suite non installa pacchetti, non scarica modelli e non apre microfoni.

## 6. Convalida live (F7)

Stato: **DA VALIDARE LIVE**. La rilevazione del detector non è stata eseguita su
microfono reale.

Checklist:

1. Lasciare disattivata l'opzione in **Customize**, avviare Jarvis e dire:
   **«Rispondi: test microfono senza wake word»**. Il flusso attuale deve rispondere
   come prima.
2. Aprire **Customize**, selezionare **Enable local wake phrase (Hey Jarvis)**,
   applicare e riavviare la sessione. Verificare nel log lo stato attivo e che i
   frame restino locali prima del trigger.
3. Dire: **«Hey Jarvis»**, attendere il messaggio del log e poi dire:
   **«Che ora è?»**. Il secondo enunciato deve raggiungere Gemini e ricevere risposta.
4. Dopo la risposta, parlare senza wake phrase: non deve essere inviato. Ripetere
   **«Hey Jarvis»** per riaprire il gate.
5. Disabilitare temporaneamente il pacchetto/modello o selezionare il setup solo
   dopo consenso: verificare un errore esplicito e che l'audio PC non sia inviato.
6. Tornare a **Customize**, togliere il flag, applicare; verificare la persistenza
   `false` e il comportamento standard.

## 7. Recap (F8)

Collegamento software completato in opt-in e senza persistenza dei frame. Il
percorso standard rimane invariato quando la wake word è spenta. Modello,
microfono, latenza e sequenza di riarmo restano **DA VALIDARE LIVE**. Nessun push
eseguito.

## 8. Rollback

Disattivare `wake_word_enabled` e selezionare il percorso predefinito. Rimuovere
solo il wiring introdotto in questa meccanica; non cancellare pacchetti, modelli,
preferenze o registrazioni dell'utente.

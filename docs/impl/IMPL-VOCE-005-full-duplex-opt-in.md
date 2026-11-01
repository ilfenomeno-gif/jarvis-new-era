# IMPL-VOCE-005 — Interruzione vocale full-duplex opt-in

Stato: IMPLEMENTATA — test automatici superati; **DA VALIDARE LIVE**
Branch: `feat/voice-echo-guarded-interrupt`

## 1. Diagnosi (F1)

Gemini Live riceve audio e genera audio, ma il callback microfono scarta tutti i
frame mentre Jarvis parla. `core/echo.py` contiene già un `EchoGuard` che confronta
le bande audio dell'uscita con il microfono; non è collegato al flusso reale.

Stato: **PARZIALE**. Stream Live bidirezionali e classificatore anti-eco esistono;
l'interruzione vocale durante la riproduzione è assente.

## 2. Procedura (F2)

1. Rendere l'interruzione vocale una preferenza opt-in, default disattivato.
2. Passare all'EchoGuard i campioni emessi dagli speaker.
3. Durante la voce di Jarvis, conservare solo un buffer RAM molto breve; inoltrarlo
   quando l'EchoGuard rileva una voce distinta, quindi mantenere il flusso aperto
   fino alla fine del turno.
4. Riutilizzare `interrupt()` e mantenere Wake Word e full-duplex mutuamente
   esclusivi: la wake word ha priorità se entrambe le impostazioni risultano attive.
5. Testare gating, buffer, allowlist impostazioni e algoritmo sintetico; segnare
   come live ogni prova che dipende dall'acustica e dal microfono.

## 3. Verdetto (F4)

**GO CON MODIFICHE**. La funzione resta disattivata per default. Il classificatore
non ha evidenza acustica raccolta sul dispositivo attivo. Un falso positivo può
interrompere la risposta; una falsa classificazione può perdere parole iniziali.
La funzione deve restare esplicitamente sperimentale e richiedere una prova
manuale prima dell'uso continuativo.

## 4. Criteri di accettazione

| Criterio | Esito |
|---|---|
| Full-duplex disattivato per default e preferenza salvata localmente | PASS — test automatici |
| L'opt-in apre il gate dopo blocchi consecutivi classificati come voce | PASS — test sintetici |
| Il pre-roll è limitato a 24 frame in RAM e viene azzerato a fine playback | PASS — test automatici |
| L'evento rilevato richiama `interrupt()` e instrada il pre-roll al flusso Live | PASS — wiring verificato e compilato; non provato live |
| Wake word ha precedenza; la UI disattiva l'altra modalità | PASS — wiring verificato; click UI DA VALIDARE LIVE |
| Eco, falsi positivi e latenze su speaker/microfono reali | DA VALIDARE LIVE |

## 5. Implementazione e verifica (F5-F6)

Preferenza locale `full_duplex_enabled`, opt-in e disattivata per default.
L'uscita Live alimenta `EchoGuard`; il microfono usa `FullDuplexAudioGate` con
pre-roll massimo di 24 callback. L'interruzione richiede blocchi vocali consecutivi
e invoca il percorso `interrupt()` esistente. Wake word e full-duplex non vengono
attivati contemporaneamente; se la configurazione è incoerente, prevale la wake word.

Sono stati corretti due bypass collegati nella logica di `EchoGuard`: la soglia
di blocchi consecutivi ora si applica sia alla voce sovrapposta sia ai blocchi
senza riferimento d'uscita. Dopo il trigger, il gate mantiene aperto il flusso e
richiama `interrupt()` una sola volta per turno.

Verifiche eseguite nel venv Python 3.13.7:

- `pytest -q`: **165 passed in 1.56s**.
- `compileall` sui moduli e test modificati: **PASS**.
- `python -m compileall .`: **FAIL** su
  `.venv/Lib/site-packages/mediapipe/tasks/python/test/text/text_embedder_test.py:113`,
  carattere U+2202 non valido in Python; errore in un file del virtualenv non modificato.
- `python -m unittest discover -s tests -v`: **Ran 0 tests**, exit code 5;
  il repository esegue la suite con pytest.

## 6. Convalida manuale (F7)

1. Con opzione spenta, dire **«Rispondi con una frase lunga»**, parlare mentre
   Jarvis risponde e verificare che non ci siano interruzioni spontanee.
2. Attivare **Voice interruption (experimental)** in Customize e riavviare la
   sessione.
3. Dire **«Rispondi con una frase lunga»**; mentre Jarvis parla, interromperlo con
   **«Aspetta, dimmi solo il risultato»**. Verificare l'interruzione e la risposta
   al secondo comando.
4. Ripetere con speaker a volume normale e alto; verificare falsi trigger dell'eco.
5. Attivare una modalità per volta: wake phrase oppure full-duplex.

Esito live: **DA VALIDARE**. Il microfono, gli speaker e la qualità della
classificazione acustica non sono stati provati in questa sessione.

## 7. Recap (F8)

Implementata l'interruzione vocale sperimentale dietro opt-in, con preferenza
locale, buffer temporaneo limitato e integrazione al flusso audio Live. I test
automatici passano; il comportamento acustico resta DA VALIDARE LIVE. Nessun
pacchetto o modello è stato installato o scaricato. Nessun push o merge eseguito.

## 8. Rollback

Disattivare l'opzione full-duplex; il percorso audio predefinito resta quello
corrente. La cronologia acustica vive solo in memoria e viene svuotata a fine turno.

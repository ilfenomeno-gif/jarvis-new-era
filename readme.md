# JARVIS Mio

Assistente personale AI per desktop, progettato per ascoltare comandi vocali, comprendere il contesto dello schermo e svolgere azioni verificabili sul computer.

Questo repository contiene una versione personalizzata di JARVIS basata su Python, Gemini Live API e una HUD desktop in PyQt6. Il progetto unisce conversazione vocale in tempo reale, automazione del sistema operativo, memoria persistente, controllo del browser, strumenti per file e giochi e un dashboard remoto locale.

Questa app è un componente del repository multi-progetto
[jarvis-new-gen](../README.md); per la mappa completa, GEV, ASTRALIS e le
licenze, consulta il README e [LICENSES.md](../LICENSES.md) della root.

## Cosa fa

- Conversazione vocale bidirezionale con input da microfono e risposta audio.
- Pannello interno di chat testuale Gemini, accessibile dalla UI e tramite comando vocale, con finestra separata di fallback.
- Routing degli intenti prima dell'esecuzione degli strumenti, con domande di chiarimento quando una richiesta e ambigua.
- Controllo di applicazioni, finestre, volume, luminosita, Wi-Fi, scorciatoie e alimentazione.
- Lettura dello schermo tramite OCR locale opzionale e fallback a visione multimodale.
- Apertura e controllo del browser con percorso DOM-first e fallback visivo.
- Apertura di Netflix e Prime Video e ricerca dei titoli nel browser integrato di JARVIS.
- Ricerca, lettura, riepilogo, spostamento, copia e scrittura di file locali.
- Avvio e aggiornamento di giochi tramite Steam ed Epic, con rilevamento degli eseguibili installati.
- Invio assistito di messaggi, controllo di YouTube, ricerche web, meteo e ricerca voli.
- Memoria lunga locale con indicizzazione dei file, profili prompt e continuita della sessione.
- Undo per molte operazioni reversibili e conferma umana per spegnimento, riavvio e Wi-Fi.
- Plugin estendibili tramite un singolo file Python nella cartella `plugins/`.
- Dashboard web locale per il controllo remoto tramite token temporanei e connessione cifrata.
- Accessibilita opzionale: screen reader, OCR locale e scorciatoie globali configurabili.

## Architettura

```text
main.py                 Avvio e ciclo principale Gemini Live
ui.py                   HUD PyQt6, log, waveform e controlli
core/                   Audio, prompt, memoria, guardrail, conferme e undo
actions/                Strumenti operativi per sistema, browser, file e web
plugins/                Estensioni caricabili senza modificare il core
dashboard/              Server e interfaccia per il controllo remoto locale
memory/                 Gestione della memoria persistente locale
tests/                  Test automatici dei contratti di automazione
```

## Generazione 3D locale

Il generatore predefinito usa TripoSR in locale (GPU); la durata dipende da GPU,
cache e descrizione. SF3D resta selezionabile impostando
`JARVIS_3D_BACKEND=sf3d` nell'ambiente del processo. Per ridurre i tempi di
inferenza, SF3D usa una texture da 512 px invece di 1024: il risultato ha meno
dettaglio, ma il baking e l'inferenza sono più leggeri. Per ripristinare la
risoluzione maggiore si può impostare `JARVIS_3D_TEXTURE=1024`.

Durante la generazione l'HUD mostra backend e tempo trascorso. Se SF3D supera
180 secondi, JARVIS chiede se interromperlo e riprovare con TripoSR; il fallback
avviene solo dopo conferma.

Le generazioni locali valide sono riutilizzate dalla cache persistente
`cache/3d/` (prompt normalizzato, backend e parametri fanno parte della chiave;
gli input immagine sono identificati dal contenuto). Per ispezionarla:

```powershell
python -m core.registry_cli cache-3d list
python -m core.registry_cli cache-3d size
python -m core.registry_cli cache-3d clear --yes
```

La cache è attiva per default; `JARVIS_3D_CACHE=0` la disabilita.
`JARVIS_3D_CACHE_TTL_DAYS` e `JARVIS_3D_CACHE_MAX_GB` configurano scadenza
(default 30 giorni) e tetto (default 5 GiB); impostare a `0` disabilita il
rispettivo limite. Il pre-warm non è disponibile: il worker è un processo
separato per generazione e il benchmark attuale individua SD-Turbo, non il
caricamento TripoSR, come fase fredda prevalente.

## Pattern Learner

Jarvis apprende preferenze ripetute sullo stile 3D, fallimenti di ricerca e correzioni esplicite. Gli hint entrano nel prompt dopo tre osservazioni concordi, con un limite di tre e 200 caratteri. `JARVIS_PATTERN_LEARNER=0` disattiva apprendimento e iniezione. I dati restano in `memory/learned_patterns.json` e si gestiscono con:

```powershell
python -m core.registry_cli patterns-list
python -m core.registry_cli patterns-delete <id>
python -m core.registry_cli patterns-clear --yes
```

## Requisiti

- Windows 10/11, macOS o Linux.
- Python 3.11, 3.12 o una versione compatibile con le dipendenze installate.
- Microfono e altoparlanti per l'interazione vocale.
- Una chiave API Gemini configurata localmente.
- Tesseract OCR opzionale per il grounding locale dei testi sullo schermo.

## Installazione

```bash
git clone https://github.com/ilfenomeno-gif/jarvis-new-gen.git
cd jarvis-new-gen/Mark-LIV-main
python -m venv .venv
```

Su Windows:

```powershell
.\.venv\Scripts\Activate.ps1
```

Installare le dipendenze e i browser Playwright:

```bash
python -m pip install -r requirements.txt
python -m playwright install
```

Configurare la chiave API nel file locale `config/api_keys.json`, che e escluso dal controllo versione:

```json
{
  "gemini_api_key": "inserire-la-propria-chiave"
}
```

La chat testuale usa la stessa configurazione Gemini del core JARVIS. La chiave
rimane nel file locale escluso dal controllo versione: non inserirla nel codice
o nei commit.

La chat Gemini si apre nel pannello centrale di JARVIS; il pulsante di ritorno
ripristina la vista precedente. Se il pannello non e disponibile, JARVIS tenta
di aprire la finestra di chat separata. La chat testuale usa il client REST
configurato in `core/gemini.py` con il modello testuale `gemini-flash-latest`;
non usa il payload audio di Gemini Live. La chiave API resta quella in
`config/api_keys.json`.

I comandi `streaming_services` aprono Netflix o Prime Video e i risultati di
ricerca nel browser integrato di JARVIS. Qt WebEngine non include Widevine DRM:
la riproduzione protetta non funziona nel pannello interno. Per un comando
`play`, JARVIS mostra l'avviso «La riproduzione protetta (DRM) non e supportata
nel pannello interno. Apro in Chrome?» e apre la stessa pagina in Chrome solo
dopo la conferma esplicita. Se il browser integrato non e disponibile, il plugin
usa `browser_control` come fallback. Il login resta gestito dal servizio nel
browser; JARVIS non memorizza credenziali, non rimuove protezioni password e
non avvia automaticamente acquisti o noleggi.

Avviare JARVIS con:

```bash
python main.py
```

In alternativa, `python setup.py` installa le dipendenze, prepara Playwright e verifica l'integrazione Windows quando disponibile.

## HUD browser

`python main.py` carica la mappa 3D interattiva in
`core/jarvis_hud.html` direttamente nell'area centrale Qt. Il bridge locale
(`127.0.0.1:8765`) invia telemetria via SSE: CPU, RAM, disco, rete, uptime e
processi da `psutil` (se installato), GPU NVIDIA da `nvidia-smi`. Temperatura e
GPU restano `N/D` quando il sistema non espone i sensori. Stato assistente e
TaskRunner arrivano dal runtime. La chat invia testo alla sessione Gemini Live;
i toggle plugin riflettono il registry reale, salvano la configurazione e
ricreano la sessione mantenendo il contesto. I pulsanti `DEMO` animano percorsi
illustrativi e non eseguono azioni. La HUD non modifica audio, dashboard remota,
avvio automatico o preferenze; questi controlli restano nella UI nativa.
La visualizzazione 3D richiede Three.js dal CDN, quindi una connessione internet.
Se la pagina incorporata non si carica, la UI ripristina la HUD Qt nativa.

Per provare solo il ponte senza avviare JARVIS, eseguire
`python core/hud_bridge.py`: l'HUD mostra le statistiche disponibili e risponde
alla chat con un'eco demo; in questa modalità i toggle plugin non hanno un
registry Jarvis collegato.

## Sicurezza e privacy

- Le chiavi API, i certificati, la memoria lunga e i log locali sono esclusi dal repository.
- Le azioni irreversibili richiedono una conferma esplicita nell'interfaccia.
- I percorsi vengono validati dai guardrail prima delle operazioni sui file.
- La memoria viene conservata localmente in `memory/long_term.json` e non viene pubblicata.
- Il dashboard deve essere usato su una rete fidata; token e certificati non vanno condivisi.
- Le azioni automatiche possono interagire con applicazioni reali: verificare sempre destinatari, percorsi e finestre prima di operazioni sensibili.

## Test e verifica

Eseguire i test automatici con:

```bash
python -m pytest -q
```

Per verificare la sintassi dell'intero progetto:

```bash
python -m compileall .
```

Le prove GUI su Steam, browser e messaggistica richiedono ancora un ambiente interattivo reale. L'OCR locale richiede sia il pacchetto Python `pytesseract` sia l'eseguibile Tesseract installato nel sistema.

## Accessibilita

Il modulo [core/accessibility.py](core/accessibility.py) aggiunge un ponte opt-in per la lettura dello schermo:

- usa l'OCR locale su tutto lo schermo o su una regione `(x, y, larghezza, altezza)`;
- invia il testo al TTS gia configurato da JARVIS oppure a `pyttsx3` come fallback offline;
- usa `nvdaControllerClient.dll` quando NVDA e installato su Windows;
- registra `Ctrl+Alt+R` per leggere lo schermo e `Ctrl+Alt+S` per lo stato solo dopo una chiamata esplicita a `start_hotkeys()`;
- rimuove le scorciatoie con `stop_hotkeys()`.

Le hotkey globali non vengono attivate automaticamente all'avvio. Per NVDA e necessario rendere disponibile `nvdaControllerClient.dll`; per l'OCR servono `pytesseract` e l'eseguibile Tesseract.

## Documentazione tecnica

- [Piano tecnico e diagnostica](PIANO_TECNICO_JARVIS.md)
- [Profili prompt](core/prompts/)
- [Template per plugin](plugins/_template.py)
- [Suite di test](tests/)

## Stato del progetto

Il progetto e in sviluppo attivo. La base include routing degli intenti, memoria locale, OCR opzionale, guardrail, undo, profili prompt, dashboard e strumenti per l'automazione desktop. Le integrazioni che dipendono da una GUI reale, da driver audio, da API esterne o da launcher installati devono essere validate sulla macchina dell'utente.

## Licenza

Consultare [LICENSE](LICENSE) per i termini di distribuzione del progetto.
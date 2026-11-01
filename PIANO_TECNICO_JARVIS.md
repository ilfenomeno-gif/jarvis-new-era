# Piano Tecnico e Analisi di Progetto: Potenziamento di JARVIS

Questo documento contiene l'analisi del progetto, la diagnostica dell'attuale architettura e un piano tecnico progettuale per rendere Jarvis significativamente più intelligente nell'interazione con il sistema operativo, le applicazioni, il browser e la lettura dello schermo.

## Analisi e Diagnostica Attuale

Dalla scansione del codice sorgente (es. `send_message.py`, `screen_processor.py`, `open_app.py`, `browser_control.py`), emergono le seguenti criticità e limitazioni dell'approccio attuale:

1. **Automazione Cieca (Blind Automation):** Molte funzioni di controllo (come invio messaggi o apertura app) si basano su `pyautogui` con attese fisse (`time.sleep`) e sequenze di tasti predefinite (es. `win`, incolla nome, `enter`). Se il PC è lento o un popup si intromette, l'automazione fallisce.
2. **Interazione col Browser:** Attualmente Jarvis fatica a contestualizzare dinamicamente una pagina web già aperta. Non possiede un meccanismo robusto per mappare gli elementi visivi del browser in coordinate cliccabili in tempo reale.
3. **Lettura Schermo Limitata:** Il processamento dello schermo è basilare. Serve un sistema di "Visual Grounding" che associ il testo o gli elementi dell'interfaccia a coordinate X/Y precise.
4. **Gestione Giochi (Installazione/Avvio):** Basarsi solo sui percorsi fissi o sui click pre-programmati rende difficile interagire con client complessi (es. Steam, Epic Games, Battle.net) dove i tasti cambiano posizione o lingua.

## Proposed Changes (Piano Tecnico)

Il progetto prevede l'implementazione di un motore di **Agentic Computer Control** (Controllo Computerizzato Agente) basato su input multimodali.

### 1. Modulo di "Visual Grounding" (Lettura Schermo Avanzata)

- Sostituiremo le macro "cieche" con una libreria di visione informatica o un OCR avanzato (Tesseract/EasyOCR) integrato con il modello multimodale.
- **Flusso:** Jarvis scatterà uno screenshot, identificherà le coordinate dei bottoni (es. "Installa", "Invia", la barra degli indirizzi di Chrome) e cliccherà *esattamente* su quelle coordinate invece di usare `Tab` o tempistiche fisse.

### 2. Gestione Intelligente del Browser e delle App

- **Browser:** Integrazione con protocolli di automazione (es. Playwright/Selenium) o estensioni per leggere il DOM e analizzare la pagina *già aperta* dall'utente. Se non è possibile usare il DOM, Jarvis userà il modulo Visual Grounding per leggere lo schermo, identificare i campi di testo e i link, ed emulare il mouse in modo chirurgico.
- **App & Messaggi:** Prima di inviare un messaggio su Whatsapp/Telegram, Jarvis verificherà visivamente che la chat corretta sia in focus, digitando il messaggio e premendo Invia solo dopo conferma visiva.

### 3. Procedure di Installazione e Avvio Giochi

- Implementazione di flussi adattivi: Jarvis capirà visivamente in quale launcher si trova. Se vede il pulsante "Installa" o "Gioca", calcolerà la posizione e cliccherà. Includeremo la gestione dinamica degli errori (es. "Spazio insufficiente sul disco" letto tramite OCR).

### Fasi di Implementazione

1. **Aggiornamento Core:** Miglioramento di `screen_processor.py` aggiungendo logica OCR per estrarre il testo e le coordinate (BBox).
2. **Refactoring Automazioni:** Sostituzione dei `time.sleep()` in `send_message.py` e `open_app.py` con cicli di attesa basati su conferme visive.
3. **Integrazione Browser e Giochi:** Aggiunta di funzioni specializzate in `browser_control.py` e `game_updater.py` per interagire con l'UI analizzata.

### Piano tecnico implementativo — accessibilità nativa

#### Obiettivo

Integrare lettura dello schermo OCR, sintesi vocale e scorciatoie globali nel ciclo di vita di JARVIS, riutilizzando i componenti già presenti invece di aggiungere un secondo listener o un secondo motore OCR.

#### Architettura e vincoli

- `core.accessibility.AccessibilityController` resta il punto d'ingresso per lettura schermo, feedback vocale e scorciatoie.
- Il riconoscimento resta locale tramite `pytesseract`; la sintesi usa la sessione JARVIS attiva. Non si inviano screenshot a servizi remoti per la lettura OCR.
- `Ctrl+Alt+R` legge il testo visibile e `Ctrl+Alt+S` comunica lo stato. Le scorciatoie globali sono opt-in tramite `JARVIS_ACCESSIBILITY_HOTKEYS=1`; se non configurate, l'avvio e l'uso ordinario non installano hook globali.
- La digitazione avviene solo dopo un risultato OCR verificato. Le API dipendenti da `keyboard`, PyAutoGUI e Tesseract restano lazy e gli errori devono essere comunicati esplicitamente.
- Non si aggiunge un thread di polling: il pacchetto `keyboard` gestisce gli hook e il controller esistente usa il canale vocale thread-safe di JARVIS.

#### Fasi e criteri di accettazione

1. **F1 — Diagnosi:** verificare controller, OCR, tool, dipendenze e teardown. Esito: componenti riusabili identificati; nessuna duplicazione della classe dell'esempio.
2. **F2 — Piano:** definire opt-in, hotkey, lifecycle e verifiche. Esito: piano approvato e rischi espliciti.
3. **F3 — Implementazione:** attivare le hotkey solo con opt-in esplicito, mostrare eventuali errori di registrazione e rimuoverle sempre all'arresto di `JarvisLive`.
4. **F4 — Test automatici:** verificare OCR/speech con mock, esito vuoto e errore, callback delle hotkey, idempotenza di start/stop e comportamento di default senza hook globali.
5. **F5 — Verifica:** eseguire i test mirati e poi la suite pertinente; verificare diff e sintassi senza acquisire o cliccare sul desktop reale.
6. **F6 — Convalida manuale residua:** con Tesseract disponibile, provare le due hotkey su una schermata innocua e confermare che la chiusura rimuova gli hook. Il piano non dichiara validata la GUI finché questa prova non è eseguita.

#### Loop operativo

Per ogni fase: **pianifica → implementa un cambiamento circoscritto → verifica con il test più mirato → registra esito e blocchi in questo file**. Se una verifica fallisce, correggere la causa e ripetere la stessa verifica prima di passare alla fase successiva. Non segnare come completati i test manuali che richiedono una GUI o un motore Tesseract non disponibili.

#### Stato di avanzamento

- F1 — Diagnosi: **completata**; il controller e l'OCR esistono, l'avvio delle hotkey e la loro pulizia automatica mancano.
- F2 — Piano: **completata**.
- F3 — Implementazione: **completata**; `JARVIS_ACCESSIBILITY_HOTKEYS=1` abilita l'avvio, gli errori sono riportati nel log e il teardown rimuove gli hook.
- F4 — Test automatici: **completata**; 19 test mirati passano con OCR, tastiera e mouse simulati.
- F5 — Verifica tecnica: **completata**; sintassi dei moduli modificati e `git diff --check` verificati.
- F6 — Convalida manuale GUI: **da eseguire**; richiede Tesseract nativo e una schermata innocua, quindi non è stata simulata.

#### Implementazione e risultati

- Riutilizzato `core.accessibility.AccessibilityController`; nessun secondo thread listener è stato aggiunto.
- Le hotkey restano disabilitate per default. L'utente può abilitarle impostando `JARVIS_ACCESSIBILITY_HOTKEYS=1` nell'ambiente del processo; valori `true`, `yes` e `on` sono accettati.
- La registrazione parziale viene annullata in caso di errore; all'arresto di `JarvisLive` gli hook vengono rimossi e gli errori di cleanup vengono riportati.
- La lettura vocale è limitata ai primi 300 caratteri, mentre il valore OCR completo è restituito al chiamante.
- Verifica eseguita: `pytest -q tests\test_accessibility.py` — **19 passed**; `pytest -q` — **208 passed**; controlli Pylance syntax per `core/accessibility.py` e `main.py` — **nessun errore**; `git diff --check` — **nessun errore**.

IMPORTANT

**User Review Required** Questo piano modificherà profondamente il modo in cui Jarvis muove il mouse e legge lo schermo, rendendolo molto più autonomo ma anche richiedendo una maggiore potenza di calcolo (per analizzare gli screenshot in tempo reale). Sei d'accordo con questo approccio architetturale basato sulla visione e sui clic precisi (Computer Vision/OCR)?

## Open Questions

- Vuoi che l'interazione con le pagine web avvenga puramente tramite analisi visiva (screenshot + clic simulati) o preferisci che Jarvis usi librerie web nascoste per "leggere" nativamente il codice della pagina web (DOM)?
- Il motore OCR locale previsto è Tesseract. Va installato separatamente dal pacchetto Python `pytesseract`; senza il binario l'errore viene comunicato e la lettura non è dichiarata riuscita.

## Verification Plan

1. **Test Singoli Clic:** Chiederemo a Jarvis di cliccare l'icona di Google Chrome sul desktop.
2. **Test Lettura Browser:** Con una pagina aperta su Chrome, chiederemo a Jarvis di leggerla, riassumerla e cliccare su un articolo specifico visibile a schermo.
3. **Test Messaggistica:** Chiederemo l'invio di un messaggio di test tramite l'app Desktop di Telegram/Whatsapp e valuteremo se Jarvis riesce a posizionarsi sulla barra di testo corretta senza errori.

## Stato di Implementazione e Diagnostica Automatica

Questa sezione viene aggiornata insieme alle modifiche del progetto e contiene solo risultati verificati.

### Completato

- `core.guardrails.resolve_safe_path()` espande variabili d'ambiente Windows (`%USERPROFILE%`) e `~`, rimuovendo anche virgolette esterne dai percorsi copiati dalla chat.
- Le trascrizioni cumulative Gemini Live vengono unite senza ripetere frammenti già ricevuti, riducendo echi e duplicazioni nel log e nella memoria di sessione.
- Il prompt e le regole autorizzano opinioni personali motivate: JARVIS distingue giudizi da fatti e non inventa esperienze personali.
- `core/intent_router.py` classifica i target come gioco/app, file/documento o ambiguo prima dell'esecuzione dei tool.
Per integrare queste funzioni direttamente come metodi nativi all'interno della classe principale del tuo assistente in jarvis-mio, puoi strutturare il codice creando una classe dedicata o aggiungendo i metodi direttamente al core del tuo Jarvis.

Ecco come puoi implementare l'accessibilità (Screen Reader, OCR e comandi da tastiera) come funzioni interne native:

Python
import threading
import time
import keyboard
import pyautogui
import pytesseract
from PIL import Image
import pyttsx3

class JarvisAccessibility:
    def __init__(self, jarvis_instance=None):
        self.jarvis = jarvis_instance  # Riferimento al core di Jarvis (se vuoi passare dati o loggare)
        
        # Inizializzazione del motore vocale nativo
        self.engine = pyttsx3.init()
        self.is_active = True
        
        # Configura i comandi nativi all'avvio del modulo
        self._register_native_hotkeys()

    def speak(self, text):
        """Funzione nativa di Screen Reader / Sintesi Vocale."""
        print(f"[Jarvis ScreenReader]: {text}")
        # Gestione per evitare conflitti di thread con il TTS
        self.engine.say(text)
        self.engine.runAndWait()

    def ocr_screen(self):
        """Funzione nativa OCR: legge il testo visibile sullo schermo."""
        self.speak("Analisi visiva dello schermo in corso...")
        try:
            screenshot = pyautogui.screenshot()
            text = pytesseract.image_to_string(screenshot, lang='ita')
            
            if text.strip():
                # Pulizia del testo e lettura
                clean_text = " ".join(text.split())
                self.speak("Ecco cosa ho trovato sullo schermo: " + clean_text[:300]) # Legge i primi 300 caratteri per evitare blocchi lunghi
            else:
                self.speak("Non ho rilevato alcun testo leggibile sullo schermo.")
        except Exception as e:
            self.speak("Errore durante l'acquisizione OCR dello schermo.")
            print(f"Errore OCR: {e}")

    def click_and_type(self, target_text, text_to_type):
        """Funzione nativa di interazione: cerca un testo sullo schermo e ci interagisce."""
        self.speak(f"Cerco l'elemento {target_text} sullo schermo...")
        # Nota: Qui puoi integrare una ricerca basata su OCR per trovare le coordinate del testo
        # Per semplicità, simuliamo un'azione rapida da tastiera/mouse
        pyautogui.write(text_to_type)
        self.speak("Fatto.")

    def _register_native_hotkeys(self):
        """Registra le scorciatoie globali che attivano le funzioni native di Jarvis."""
        try:
            # Ctrl + Alt + R -> Attiva la lettura OCR dello schermo
            keyboard.add_hotkey('ctrl+alt+r', self.ocr_screen)
            
            # Ctrl + Alt + S -> Legge lo stato di Jarvis
            keyboard.add_hotkey('ctrl+alt+s', lambda: self.speak("I sistemi di accessibilità di Jarvis sono operativi."))
            
            print("[Jarvis] Scorciatoie di accessibilità native registrate con successo.")
        except Exception as e:
            print(f"Impossibile registrare le hotkey globali: {e}")

    def run_listener(self):
        """Mantiene attivo il listener dei comandi da tastiera in background."""
        while self.is_active:
            time.sleep(1)

# Esempio di integrazione nel main del tuo progetto jarvis-mio
if __name__ == "__main__":
    print("Avvio del core di Jarvis con modulo di accessibilità nativo...")
    
    # Inizializza il modulo
    accessibility = JarvisAccessibility()
    accessibility.speak("Jarvis online con supporto accessibilità integrato.")
    
    # Avvia il loop di ascolto tastiera in un thread separato per non bloccare l'assistente
    listener_thread = threading.Thread(target=accessibility.run_listener, daemon=True)
    listener_thread.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        accessibility.is_active =iccation = False
        print("Arresto di Jarvis in corso...")
Come collegarlo alla struttura esistente di jarvis-mio:
Crea un file accessibility.py (o inserisci la classe JarvisAccessibility dentro i tuoi moduli esistenti).

Istanzialo nel file principale (es. main.py o jarvis.py) quando avvii l'applicazione.

Usando threading, il sistema di scorciatoie da tastiera (ctrl+alt+r per l'OCR dello schermo, ecc.) girerà in background permettendoti di richiamare le funzioni di accessibilità in qualsiasi momento, indipendentemente da cosa sta facendo il resto del programma.- I titoli di gioco esatti passano al launcher corretto; i nomi parziali ambigui vengono bloccati con una domanda formale invece di essere cercati alla cieca.
- Una categoria esplicitamente pronunciata dall'utente viene salvata in `memory/long_term.json` come associazione persistente `target_intent_<nome>`; i test usano mock e non modificano la memoria reale.
- Le ricerche generiche non possono più assorbire una richiesta esplicita di gioco, e i tool file non indovinano in caso ambiguo.
- `file_controller.py` indicizza automaticamente ogni file trovato o letto con chiavi `file_path_<nome>` e percorso assoluto in memoria lunga.
- Le aperture successive con solo nome o parola chiave consultano prima l'indice; se il percorso memorizzato non esiste più, la ricerca ricorsiva può ricostruire l'associazione.
- `game_updater.py` legge `appmanifest_*.acf`, ricostruisce la cartella `Steam\common\<installdir>` e individua gli eseguibili locali dei giochi installati.
- `computer_control.py` usa ora il testo OCR locale per `screen_find` e `screen_click` prima del fallback Gemini, permettendo di trovare etichette come `Play`, `Gioca` e `Invia` senza coordinate indovinate.
- `youtube_video.py` applica la riproduzione completa: estrae il primo risultato pertinente, apre il link `watch` e restituisce il link diretto; se l'estrazione o l'apertura fallisce, apre e restituisce la ricerca YouTube mirata.
- `core/prompt.txt` contiene una direttiva globale di esecuzione end-to-end: nessun successo dichiarato per azioni parziali, URL mirati per i contenuti, verifica osservabile e fallback funzionale trasparente.
- L'avvio Steam dei giochi usa prima l'eseguibile locale (con Steam avviato in background per la licenza); per Victoria 3 privilegia `binaries\win64\v3.exe` e salva il percorso trovato in memoria lunga.
- Diagnostica reale del PC: Steam trovato in `C:\Program Files (x86)\Steam`, ma `Victoria 3` non risulta attualmente installato o non ha un manifest rilevabile; nessun percorso `.exe` è stato inventato o salvato.
- Pulizia memoria verificata: `memory/long_term.json` non contiene associazioni Victoria 3 verso file locali o percorsi errati.
- La priorità di avvio giochi è ora esplicita: Steam/Epic e `game_updater` precedono sempre ricerca file e ricerca generica.
- Rimosso il residuo obsoleto `target_intent_victoria_3 = game:launcher`; `Victoria` resta ambiguo, mentre `Victoria 3` con richiesta Steam viene instradato esplicitamente a Steam.
- Aggiunto `core/prompt_router.py` con profili dinamici `developer_mode`, `strategic_mode`, `quick_command` e `standard_assistant`, caricati da `core/prompts/` con fallback sicuro.
- Collegato come sorgente documentata il repository prompt [`ilfenomeno-gif/repo-prompt`](https://github.com/ilfenomeno-gif/repo-prompt); i profili locali restano prioritari e il runtime non scarica contenuti remoti automaticamente.
- Integrati nel cuore permanente di `core/prompt.txt` gli otto principi adattati del repository: selezione tool, chiarificazione, comunicazione strutturata, contesto, iterazione, verifica, automazione graduata e rifinitura umana.
- I comandi testuali ricevono il profilo dinamico prima dell'esecuzione; i comandi vocali restano protetti dal system prompt e dall'intent router dei tool. Il ragionamento interno non viene esposto all'utente.
- OCR: `pytesseract`, PyAutoGUI e Pillow installati nell'ambiente `.venv`; l'eseguibile nativo Tesseract resta una dipendenza Windows separata. Il comando Python globale usato in precedenza da JARVIS deve usare lo stesso ambiente o installare il wrapper anche lì.
- `screen_processor.py` espone OCR opzionale con testo, confidence e bounding box in coordinate assolute.
- Il grounding prova prima l'OCR locale e usa Gemini come fallback per elementi non testuali o quando l'OCR non e disponibile.
- L'attesa OCR termina immediatamente quando il backend non e installato; non introduce ritardi artificiali.
- `send_message.py` non considera riuscito il click del campo messaggio se non ha ottenuto coordinate verificate.
- `open_app.py` riconosce varianti vocali di GeoGuessr e i giochi Steam.
- L'avvio dei giochi Steam segue il flusso interattivo: avvio Steam, focus della finestra, ricerca nella Libreria e click visuale su `Play`, `Gioca`, `Launch` o `Avvia`.
- `browser_control.py` mantiene il percorso DOM-first con fallback a visione per la lettura della pagina attiva.
- `game_updater.py` usa il grounding visuale per i pulsanti del launcher e verifica errori di spazio insufficiente quando l'OCR e disponibile.

### Test automatici eseguiti

Comando: `python -m unittest discover -s tests -v`

Risultato verificato: **28 test superati**. I test coprono anche la direttiva globale di completamento end-to-end.

Compilazione verificata con Python 3.13: `main.py` e i moduli di automazione compilano senza errori.

### Diagnostica dell'ambiente corrente

- Python: 3.13.7 su Windows 11.
- Disponibili: `pyautogui`, `pygetwindow`, `mss`, Pillow, Playwright, `psutil`, `google.genai`.
- Non disponibili nell'interprete usato da JARVIS: modulo Python `pytesseract` ed eseguibile Tesseract.
- Il rilevamento ora verifica entrambi i componenti separatamente e disabilita l'OCR senza introdurre attese false quando manca l'eseguibile.
- Conseguenza: il grounding OCR locale non e ancora attivo; il fallback Gemini resta operativo.
- Steam non e nel `PATH`; il rilevamento usa comunque registro Windows e percorsi standard (`Program Files`, `C:\Steam`, ecc.).
- Startup diagnostico verificato: `main.py` resta attivo oltre 6 secondi e inizializza plugin, audio e dashboard senza errori applicativi.
- Rimane un warning Qt non bloccante relativo a `SetProcessDpiAwarenessContext` e ai permessi DPI di Windows.
- Startup diagnostic successivo ai fix: processo vivo oltre 5 secondi; plugin, audio e dashboard inizializzati, nessun crash applicativo.

### Test manuali ancora necessari

Questi test richiedono la GUI reale e non vengono simulati automaticamente per evitare azioni indesiderate:

1. Aprire un gioco installato tramite Steam e verificare ricerca Libreria e click `Play`.
2. Aprire Chrome, leggere la pagina attiva tramite DOM e verificare il fallback visivo su una pagina non accessibile al DOM.
3. Inviare un messaggio di prova solo dopo aver confermato visivamente chat, destinatario e campo di testo.

### Prossimo incremento

Installare e validare Tesseract nell'interprete Python 3.13 corretto, aggiungere test con screenshot sintetici per OCR, introdurre un controllo post-click del processo di gioco e validare il clic reale su Steam/Telegram/Chrome. Il piano non considera conclusa l'automazione finche questi test manuali non avranno esito positivo.

## Analisi Diagnostica Completa del Progetto

### Architettura verificata

- `main.py` è l'entrypoint: inizializza Qt, audio, Gemini Live, memoria, plugin, dashboard e task di monitoraggio.
- `core/` contiene guardrail subprocess, memoria, conferme, undo, prompt statico e routing dinamico dei prompt.
- `actions/` contiene i tool operativi per file, browser, desktop, messaggistica, OCR/visione, giochi, sistema, web e sviluppo. I moduli che dichiarano `TOOL` sono scoperti, dichiarati al modello e instradati tramite `core/action_loader.py`.
- `plugins/` viene scoperta e validata all'avvio; i nomi che collidono con tool core o azioni registrate vengono rifiutati.
- `dashboard/` espone il controllo remoto locale con token temporanei e cifratura dei messaggi.
- Le azioni dichiarative non sostituiscono ancora i rami statici di `main.py`; skill procedurali e workflow multi-step non sono ancora implementati.

### Finding critici risolti

1. Il guard globale dei subprocess bloccava `steam.exe`, `cmd.exe`, `netsh` e gli eseguibili dei giochi. La whitelist ora include i comandi supportati e consente eseguibili `.exe` solo in librerie Steam/Epic riconoscibili.
2. L'avvio URL Windows usava `shell=True`, incompatibile con il guard. `open_app.py` usa ora `os.startfile()` per URI e percorsi Windows interessati.
3. Il controllo giochi, file, OCR e prompt dinamici era coperto da test isolati ma non da una diagnosi globale. Ora sono presenti test di contratto per routing, launcher, memoria, OCR, sicurezza e profili prompt.

### Rischi residui

- Il dashboard tenta ancora un comando `.bat` con `shell=True` per la configurazione firewall; il guard lo rifiuta intenzionalmente e il codice passa al fallback UAC `ShellExecuteW`. La configurazione automatica può quindi richiedere privilegi amministrativi.
- L'OCR locale richiede l'eseguibile nativo Tesseract oltre al pacchetto Python `pytesseract`; senza di esso viene usato Gemini.
- L'interazione PyAutoGUI e il click Steam dipendono dalla finestra attiva, dalla lingua dei pulsanti e dalla risoluzione DPI. Il percorso ha attese/grounding, ma richiede ancora prova GUI reale.
- Il dashboard è raggiungibile sulla rete locale; token, chiavi TLS e regole firewall devono essere trattati come superficie di sicurezza separata.
- Le chiamate Gemini, DDG, Playwright e TTS dipendono da rete, API key, quota e sessioni browser; i fallback riducono ma non eliminano questi vincoli.

### Verifica globale eseguita

- **44** file Python importati senza errori.
- `compileall` sull'intero progetto superato.
- **25/25** test automatici superati.
- Memoria lunga invariata durante i test.
- Startup reale verificato: processo vivo oltre 6 secondi con plugin, audio e dashboard inizializzati.
- Warning Qt `SetProcessDpiAwarenessContext` rilevato, non bloccante e legato ai permessi DPI di Windows.

### Ordine consigliato dei prossimi test manuali

1. Con Steam aperto e un gioco realmente installato, verificare risoluzione manifest, avvio eseguibile locale e presenza Steam per la licenza.
2. Con Tesseract installato, mostrare un pulsante `Play` o `Gioca` e verificare `screen_find`/`screen_click` su una schermata controllata.
3. Aprire una pagina in Chrome e verificare DOM-first, fallback visivo e comportamento su elemento non trovato.
4. Eseguire un messaggio di prova con destinatario non ambiguo e confermare che chat e campo di testo siano identificati prima dell'invio.

## Fase 5a-server

### Stato di avanzamento

- F1 — Diagnosi: **completata**; `core.gemini_chat.ask_gemini(prompt, history=None, timeout_ms=30000)` è disponibile; `PluginRegistry.run(name, parameters, player=None, session_memory=None)` è il punto di dispatch; `websockets` era installato nell'ambiente ma mancava dal manifest.
- F2 — Piano: **approvato**; server loopback, autenticazione token, dispatch asincrono fuori dall'event loop e test senza bind reale.
- F3 — Implementazione: **completata**; aggiunto `core/ws_server.py`, senza avvio automatico da `main.py`.
- F4 — Test automatici: **completata**; test protocollo, auth, chat, plugin, ping/pong, errori, lifecycle mockato e rotazione log.
- F5 — Verifica tecnica: **completata**; test, `py_compile`, `git diff --check` e controllo assenza di import Qt superati.
- F6 — Convalida manuale: **PARZIALE — DA ESEGUIRE**; avviato il listener loopback reale e verificati auth valido, ping/pong, rifiuto auth (codice 4001) e chat multi-turno Gemini. La prova di `command` con un plugin resta da eseguire.

### Implementazione e risultati

- `start_server(host="127.0.0.1", port=8765, plugin_registry=None)` rifiuta indirizzi non loopback e serve finché `stop_server()` non chiude il listener.
- Il primo messaggio deve autenticare con `{"type":"auth","token":"..."}`. Un token assente viene generato con `secrets.token_urlsafe` e persistito come `ws_token` in `config/api_keys.json` al primo avvio effettivo; token mancanti/errati chiudono la connessione con codice 4001. Il token non viene scritto nei log.
- `chat` inoltra testo e history a `ask_gemini` in un thread di lavoro; `command` inoltra nome e argomenti a `PluginRegistry.run`. Entrambi emettono stati `busy` e poi `ready`, oppure `error`. `ping` risponde `pong`.
- Il log è `logs/ws_server.log` con `RotatingFileHandler`, rotazione a 1.000.000 byte e tre backup. Aggiunta la dipendenza `websockets>=14.0`.
- I test del lifecycle sostituiscono `websockets.serve` con un fake e non eseguono bind; per la verifica manuale il server è stato avviato separatamente su `127.0.0.1:8765`. Il token effettivo è stato generato e persistito in `config/api_keys.json`; non riportarlo in log o documentazione.
- Verifica: `pytest tests\test_ws_server.py -q` — **17 passed**; `pytest tests -q` — **313 passed**; `python -m py_compile core\ws_server.py tests\test_ws_server.py` — superato; `git diff --check` — superato; nessun import PyQt/PySide in `core/ws_server.py`.

### Prova manuale residua

Prova reale eseguita con client WebSocket locale: auth valido → `auth_ok` e stato `ready`; `ping` → `pong`; token errato → chiusura **4001**. Dopo i precedenti errori transitori `503 UNAVAILABLE`, `504 DEADLINE_EXCEEDED` e un timeout SDK, la chat multi-turno è riuscita con `gemini-3.8-flash`: “Mi chiamo Marco” → risposta di conferma → “Come mi chiamo?” → “Ti chiami Marco.” La prova di `command` con un plugin abilitato resta da eseguire. Questa convalida è **PARZIALE — DA ESEGUIRE**; il server non viene avviato automaticamente da JARVIS.

## Fase 5b-extension-base

### Stato di avanzamento

- F1 — Diagnosi protocollo: **completata**; handshake `auth`/`auth_ok`, `ping`/`pong`, stati `ready|busy|error`, messaggi `chat` e `command`, chiusura 4001 per autenticazione rifiutata.
- F2 — Piano: **approvato**; estensione isolata in `C:\Users\PC\Documents\project jarvis ultra\jarvis-vscode-extension`, esterna a `Mark-LIV-main`.
- F3 — Implementazione: **completata**; sidebar WebView, client WebSocket, token configurabile o da ambiente e riconnessione con massimo cinque tentativi.
- F4 — Test: **completata**; compilazione TypeScript e 3 test unitari passati; VSIX generata senza pubblicazione.
- F5 — Verifica tecnica: **completata**; audit npm senza vulnerabilità note e verifica che tutti i file dell'estensione siano fuori da `Mark-LIV-main`.
- F6 — Convalida manuale: **PARZIALE — DA ESEGUIRE**; VSIX installata in VS Code, ma il pannello non è stato aperto e l'handshake dal webview non è stato osservato.

### Implementazione e risultati

- File creati: `package.json`, `package-lock.json`, `tsconfig.json`, `.vscodeignore`, `.gitignore`, `src/extension.ts`, `src/protocol.ts`, `src/webview/index.html`, `src/webview/main.js`, `media/style.css`, `media/icon.svg` e `test/protocol.test.cjs`.
- Comandi registrati: `jarvis.openPanel` e `jarvis.setConnectionToken`; la vista laterale JARVIS usa il WebSocket locale `127.0.0.1` e la porta `jarvis.wsPort` (predefinita 8765). Il token viene letto prima da `JARVIS_WS_TOKEN`, poi da VS Code SecretStorage. I precedenti valori `jarvis.wsToken` vengono migrati e rimossi dalle impostazioni utente al primo collegamento; se VS Code non può rimuoverli, mostra un avviso.
- L'estensione invia auth e ping, interpreta auth/status/pong/reply e applica backoff esponenziale con massimo cinque tentativi. L'invio nel pannello è solo locale e chiarisce che la chat Gemini arriverà nella fase 5c.
- Verifica: `npm test` — compilazione TypeScript superata, **3 passed**; `npx vsce package --no-dependencies` — VSIX generata in `jarvis-vscode-extension\jarvis-vscode-extension-0.1.0.vsix`; `npm audit` — **0 vulnerabilità**.
- Il packaging segnala che il manifest non dichiara `repository` e che non è presente un file LICENSE; la generazione della VSIX riesce comunque. L'SVG è usato come icona della vista laterale, non come icona di pacchetto.

### Prova manuale residua

VSIX installata tramite VS Code CLI come `jarvis-local.jarvis-vscode-extension@0.1.0`. Da fare nell'editor: avviare JARVIS, eseguire **JARVIS: Set Connection Token** (oppure impostare `JARVIS_WS_TOKEN` nell'ambiente dell'Extension Host), aprire **JARVIS: Open Panel** e verificare che la vista riceva lo stato autenticato dal server reale. La prova visuale e l'handshake dal WebView restano **DA ESEGUIRE**.

## Fase 5c-chat-extension

### Stato di avanzamento

- F1 — Diagnosi: **completata**; il server accetta `history` come lista di turni `user`/`model`, ciascuno con `parts: [{"text": ...}]`; `ask_gemini` passa questi turni a Gemini prima del prompt corrente.
- F2 — Piano: **completato**; UI a messaggi, cronologia limitata agli ultimi 20 turni, UUID per richiesta, un invio alla volta, massimo 3 riconnessioni transitorie.
- F3 — Implementazione: **completata** nella cartella esterna `jarvis-vscode-extension`; nessuna modifica al server o agli altri file Python di JARVIS.
- F4 — Test: **completata**; compilazione strict e 10 test Node superati, compresi costruzione chat, history, trim, errori e policy retry.
- F5 — Verifica tecnica: **completata**; `npm run compile`, `npm test`, `npx vsce package --no-dependencies`, `npm audit` e `git diff --check` superati.
- F6 — Convalida manuale: **DA ESEGUIRE**; il test backend WebSocket multi-turno ora riesce con `gemini-3.8-flash`, ma la prova completa nella WebView di VS Code (incluso “Mi chiamo Marco” → “Come mi chiamo?”) non è stata eseguita.

### Implementazione e risultati

- Aggiornati `src/extension.ts`, `src/protocol.ts`, `src/webview/index.html`, `src/webview/main.js` e `media/style.css`; aggiunto `src/webview/chat-state.js`; ampliato `test/protocol.test.cjs`.
- La WebView invia `{type:"chat", id, text, history}` con ID UUID e cronologia Gemini in formato `user`/`model`. I turni vengono aggiunti alla cronologia solo dopo una risposta riuscita; history in uscita e mantenuta sono limitate agli ultimi 20 turni.
- Input multilinea con invio tramite pulsante o Ctrl/⌘+Enter; composer disabilitato mentre la richiesta è in corso e stato “JARVIS sta pensando…”. I messaggi `reply` sono associati all'ID; errori server/offline ripristinano il prompt e mostrano un errore senza inserire turni falliti nella history.
- Connessione offline e auth rifiutata sono mostrate nel pannello. Le disconnessioni transitorie consentono al massimo 3 tentativi; il rifiuto token (codice 4001) non viene ritentato automaticamente.
- Verifica mirata: `npm test` — **10 passed**, inclusa compilazione TypeScript strict; `npx vsce package --no-dependencies` — VSIX rigenerata con gli asset WebView della chat; `npm audit` — **0 vulnerabilità**. Il packaging mostra avvisi non bloccanti per i campi repository e LICENSE mancanti.
- Anche la verifica manuale del multi-turno nel pannello Gemini interno di JARVIS resta **DA ESEGUIRE**: riavviare JARVIS, aprire Gemini, inviare “Mi chiamo Marco” e poi “Come mi chiamo?”. Il test backend WebSocket, effettuato separatamente, è riuscito ma non sostituisce questa prova GUI.

### Prova manuale residua

La VSIX aggiornata è stata generata e installata, ma la prova completa richiede ancora di aprire il pannello nell'editor. Avviare JARVIS e il suo WebSocket locale, eseguire **JARVIS: Set Connection Token** (o impostare `JARVIS_WS_TOKEN`), aprire il pannello e inviare “Mi chiamo Marco”, poi “Come mi chiamo?”. Atteso: la risposta usa la cronologia locale e ricorda Marco. Il percorso Gemini backend ha risposto correttamente usando `gemini-3.8-flash`; la convalida visuale della WebView resta **DA ESEGUIRE**.

## GEV e thinking nativo Gemini

### Stato

- F1 — Diagnosi: **completata**; la GEV caricata da JARVIS usa la WebView con `?ui=panels`, `style.css` aggrega gli asset CSS e la chat REST usa `generate_content` senza thinking nativo.
- F2 — Piano: **completato**; restyling limitato al CSS embed della GEV, config thinking per Gemini REST e Live, profili HIGH/LOW, riepiloghi collassabili e fallback circoscritti.
- F3 — Restyling GEV: **implementato** in `_gev-clone/src/ui/styles/embed.css`; nessuna modifica alla logica JavaScript.
- F4 — Thinking Gemini e riepiloghi: **implementati** nella chat REST; `ask_gemini` mantiene la risposta `str` per retrocompatibilità e `ask_gemini_with_thoughts` restituisce risposta e parti marcate `thought`.
- F5 — Thinking JARVIS: **parziale**; la sessione Live usa HIGH e disattiva solo la config thinking se il server la rifiuta. `PromptRouter` assegna HIGH ai profili complessi e LOW ai comandi rapidi, applicati alla chat REST. La sessione Live persistente non espone un aggiornamento per turno: non viene riconnessa ad ogni frase per evitare regressioni a audio e resumption, quindi i comandi vocali rapidi restano con il livello HIGH della sessione.
- F6 — Verifica tecnica: **completata**; `pytest tests -q` — **320 passed**; test mirati Gemini/UI/router — **27 passed**; `py_compile` sui file Python modificati e `git diff --check` superati.
- F7 — Convalida manuale: **DA ESEGUIRE**; estetica GEV e visualizzazione dei riepiloghi richiedono JARVIS/GEV in GUI. Non è stato avviato alcun server né fatta una chiamata di rete.

### Implementazione e limiti

- `core.gemini_chat.ask_gemini` accetta `thinking_level` e `include_thoughts`, passa `GenerateContentConfig(ThinkingConfig(...))` e continua a restituire una stringa. La nuova funzione `ask_gemini_with_thoughts` estrae i testi delle parti che l'SDK marca `thought`, mantenendo separata la risposta visibile.
- Il fallback REST ripete la richiesta senza config solo per errori API 400 esplicitamente riferiti al thinking; errori di rete o provider non generano un secondo tentativo. Per Live, una config non supportata viene disabilitata e la connessione riprova senza di essa.
- La finestra Gemini mostra le parti thought in un riquadro collassabile solo quando il provider le restituisce; i pensieri non vengono aggiunti alla cronologia della conversazione. La richiesta usa LOW per `quick_command` e HIGH per gli altri profili.
- `_gev-clone/src/ui/styles/embed.css` affina carattere, spaziature, vetro, bordi, ombre, focus e transizioni quando la GEV è incorporata in JARVIS.
- Il build CSS headless non è stato eseguito: la copia GEV non ha `node_modules`; non sono state installate dipendenze. La verifica visuale resta manuale.

## Routing geografico e storico verso GEV

### Stato

- F1 — Diagnosi: **completata**; `show_in_gods_eye_view` accetta `area.place` e restituisce `data.view`; il bridge embedded applica coordinate, annotazioni e snapshot storici già supportati.
- F2 — Piano: **completato**; classificazione conservativa a regex, estrazione locale dell'entità/anno, riuso MCP per risolvere il luogo e fallback al normale turno Gemini se GEV non è disponibile.
- F3 — Implementazione: **completata** in `core/intent_router.py`, `core/geo_router.py`, `main.py`, `plugins/gev_plugin.py` e `ui.py`; le domande vocali e testuali esplicite programmano `open_with_context` senza interrompere la risposta Gemini.
- F4 — Test: **completata**; aggiunti test mockati per classificazione, ambiguità, risoluzione MCP, camera, annotazione, anno e validazione.
- F5 — Verifica tecnica: **completata**; test mirati — **37 passed**; suite completa — **329 passed**; `py_compile` e `git diff --check` superati.
- F6 — Convalida manuale: **DA ESEGUIRE**; verificare in JARVIS che “Dov'è Roma?” apra Roma, “La battaglia di Waterloo nel 1815” mostri il contesto storico e “Come stai?” non apra la GEV.

### Implementazione e limiti

- La classificazione e l'estrazione sono locali e conservative: se manca un'entità risolvibile o la confidenza è bassa, il routing non parte.
- `open_with_context` chiama il tool GEV esistente con `area: {"place": ...}`, legge `structuredContent.data.view.camera`, attende che l'embed sia pronto, quindi invia camera e annotazione con il bridge esistente. Un anno esplicito per richieste storiche usa `historical_map show`; l'epoca testuale resta nell'annotazione.
- Non esiste un protocollo embedded per temi storici liberi: il tema viene annotato e non viene inventata un'API. La risoluzione del nome dipende dal resolver/servizio luoghi della GEV.
- Se plugin, resolver o embed falliscono, l'errore è scritto nel log e il testo originale continua al normale flusso Gemini. I test non hanno usato rete reale né avviato processi GEV.
- La verifica GUI e la risoluzione reale dei luoghi restano non verificate; il checkout GEV non è stato modificato.

## Test manuale GUI — GEV + thinking + geo-routing

| Fase | Esito | Note |
|---|---|---|
| F0 — Preflight | **PASS** | Verificati `jarvis.wsPort=8765` e token VS Code uguale a quello server senza stamparlo. JARVIS e il listener WS sono attivi su `127.0.0.1:8765`; handshake autenticato (`auth_ok`, stato `ready`) e ping/pong riusciti. Non è stata inviata una richiesta a Gemini in questa verifica. Nei log precedenti restano errori Gemini transitori `503 UNAVAILABLE`/`504 DEADLINE_EXCEEDED`. |
| F1 — Estetica GEV | **DA ESEGUIRE** | JARVIS è stato avviato e il log segnala GEV pronto, ma l'interfaccia non è stata ispezionata visivamente e non è stato acquisito uno screenshot. |
| F2 — Thinking di Google | **DA ESEGUIRE** | Nessuna GUI disponibile; risposta SDK breve riuscita ma nessun thought summary osservato. |
| F3 — Multi-turno Gemini | **DA ESEGUIRE** | Nessuna GUI disponibile per verificare memoria tra turni e ripristino della vista. |
| F4 — Auto-routing geografico | **DA ESEGUIRE** | Nessuna GUI disponibile per inviare e osservare le query geografiche. |
| F5 — Auto-routing storico | **DA ESEGUIRE** | Nessuna GUI disponibile per inviare e osservare le query storiche. |
| F6 — Fallback GEV offline | **DA ESEGUIRE** | Non eseguito come test di fallback; GEV si è arrestato insieme alla terminazione di JARVIS, non in seguito a una prova controllata. |
| F7 — Estensione VS Code | **DA ESEGUIRE** | L'artefatto VSIX e l'estensione installata attuali contengono `node_modules/ws`; `npm test` compila l'estensione e passa 10 test, e il backend supera l'handshake autenticato e ping/pong (vedi F0). Il precedente errore `command 'jarvis.openPanel' not found` resta documentato in [F7-command-not-found.png](./test-evidence/F7-command-not-found.png), ma non è stato riprodotto dopo questo controllo. Reload effettivo di VS Code, apertura del pannello e chat multi-turno non confermati; nessuna GUI verificata. |
| F8 — Regressioni | **DA ESEGUIRE** | Nessuna GUI disponibile per verificare globo, browser e chiusura; non sono stati terminati processi. |

### Problemi rilevati e blocchi

1. **Instabilità transitoria Gemini:** il nome `gemini-3.8-flash` è presente nell'elenco restituito dall'API e sia la chiamata SDK sia la chat WS hanno risposto; restano nei log precedenti errori `503 UNAVAILABLE` e `504 DEADLINE_EXCEEDED`.
2. **F7 — convalida GUI residua:** il precedente errore di comando è stato associato all'assenza di `ws` nel pacchetto allora esaminato. Il VSIX e l'installazione attuali contengono la dipendenza; compilazione e 10 test automatici passano. Resta da ricaricare VS Code, invocare il comando e verificare visivamente il pannello; non dichiarare F7 superato prima di questa prova.
3. **Prove GUI rimanenti:** F1–F6 e F8 restano DA ESEGUIRE; nessuno screenshot GEV è stato acquisito e non sono stati simulati esiti. Nessuna prova distruttiva è stata eseguita.

Per riprendere, eseguire **Developer: Reload Window** da VS Code, aprire **JARVIS: Open Panel** e ripetere F7, inclusa la chat multi-turno. Eseguire F1–F6 e F8 in una GUI JARVIS osservabile. Se Gemini torna a fallire con `503`/`504`, registrare l'esito e ripetere F0 prima di proseguire.

## Fix: GEV porta 4173 + lingua risposta

| Fase | Stato | Esito |
|---|---|---|
| F1 — Diagnosi | **COMPLETATA** | Il plugin avviava Vite sul loopback alla porta 4173, controllava solo la connessione TCP e poteva selezionare checkout GEV ascendenti in base alla presenza di `node_modules`. Il path `Downloads` nei log non coincideva con il checkout sotto `Mark-LIV-main`. Il prompt Live è `core/prompt.txt`; non imponeva l'italiano e il fallback in `main.py` non aveva logging di provenienza. |
| F2 — Piano | **APPROVATO** | Approvato riuso solo dopo HTTP 200 e titolo GEV atteso, senza acquisire o terminare il processo esterno; path checkout deterministico; diagnostica d'uscita Vite con codice e output; direttiva italiana nel prompt e fallback; log INFO della sola provenienza. |
| F3 — Implementazione | **COMPLETATA** | `GEV_DIR` è ancorata al percorso del plugin sotto `Mark-LIV-main`; una porta occupata viene riusata solo dopo health check HTTP che verifica il titolo `God's Eye View`. Il server esterno non viene assegnato a `_process`, quindi `stop()` non lo termina. Gli errori Vite includono exit code e stdout/stderr raccolti. `core/prompt.txt` e il fallback contengono la direttiva italiana richiesta; `main.py` registra a livello INFO il percorso del prompt oppure `fallback`, senza loggarne il contenuto. Il resolver legacy resta disponibile per compatibilità con il test esistente, ma non determina il checkout runtime. |
| F4 — Test automatici | **PASS** | Test mirati `tests\test_gev_plugin.py tests\test_prompt_router.py tests\test_gev_mcp_client.py`: **40 passed**. Suite completa `pytest tests -q`: **336 passed**. I test d'avvio mockano socket e subprocess; non sono stati avviati JARVIS o Vite. |
| F5 — Verifica tecnica | **PASS** | `py_compile` su `plugins\gev_plugin.py` e `main.py`; `git diff --check` sui file autorizzati: nessun errore. |
| F6 — Convalida manuale | **DA ESEGUIRE** | Richiede GUI/JARVIS reali: verificare che il server GEV parta o venga riusato, e che le risposte vocali a “Jarvis, come stai?” e “Jarvis, chi era Giulio Cesare?” siano solo in italiano. Nessuna risposta vocale è stata simulata o dichiarata verificata. |

### Runtime e blocchi residui

- Per preparare il checkout deterministico sono stati copiati localmente `node_modules`, `.node\node_modules` e launcher npm/npx mancanti dal checkout in `Downloads`, come autorizzato. Non è stato eseguito `npm install` né alcun accesso alla rete. I quattro prerequisiti (`vite.js`, `npm-cli.js`, `node.exe`, `stdio.js`) sono stati verificati presenti.
- L'health check usa il titolo HTML della pagina iniziale come identificatore pratico: una pagina GEV che cambi titolo può essere rifiutata; un altro servizio che imiti esattamente quel titolo potrebbe essere accettato. In caso di errore o risposta non GEV, il plugin fallisce senza terminare il processo esistente.
- Il test automatico verifica la direttiva, non garantisce il comportamento generativo del modello. La verifica lingua e il lifecycle GEV con GUI restano subordinati a F6.

### Correzione lingua briefing di avvio

| Fase | Stato | Esito |
|---|---|---|
| F1 — Diagnosi | **COMPLETATA** | `_send_startup_briefing()` inseriva la lingua memorizzata direttamente nei prompt di entrambe le fasi. La memoria conteneva `Traditional Chinese`, in conflitto con la direttiva italiana del prompt di sistema. |
| F3 — Implementazione | **COMPLETATA** | I prompt di saluto e notizie impongono ora l'italiano indipendentemente dalla lingua salvata; il nome e il contesto dell'ultima sessione restano invariati. La memoria persistente non è stata modificata. |
| F4/F5 — Test e verifica tecnica | **PASS** | Test mirato `tests\test_prompt_router.py`: **6 passed**; suite `pytest -q tests`: **344 passed**; `py_compile` e `git diff --check` superati. |
| F6 — Convalida manuale | **DA ESEGUIRE** | Riavviare JARVIS e verificare in GUI/ascolto che saluto e briefing notizie siano interamente in italiano. Il comportamento generativo/vocale non è certificato dai test automatici. |

## UI: animazioni e stati reattivi

| Fase | Stato | Esito |
|---|---|---|
| F1 — Diagnosi | **COMPLETATA** | `HudCanvas` aveva già un timer da 16 ms, anelli/scanner, respiro dell'alone e reattività audio; lo stato arrivava tramite `_state_sig` e `_apply_state`. Gli errori erano mostrati nel log ma non come stato HUD. |
| F2 — Piano | **APPROVATO PER PROCEDERE** | Riutilizzare `HudCanvas` e il suo timer invece di aggiungere un secondo loop; esporre `JarvisUI.set_jarvis_state`, mappare gli stati correnti, attivare feedback errori dal log e ridurre gli effetti continui con `JARVIS_REDUCED_MOTION=1`. |
| F3 — Implementazione | **COMPLETATA** | L'HUD mostra stati idle/listening/thinking/speaking/error con accenti della palette esistente; thinking accelera gli anelli, speaking mantiene la reattività audio, errori `ERR:` attivano il pulse rosso/ambra. Il timer gira a 17 ms (~59 FPS), o 33 ms (~30 FPS) in reduced motion; quest'ultimo ferma anelli, scanner, pulse rings e particelle. Aggiunti tema QSS palette-aware, glow animato sul titolo e scanline diagonale sull'HUD; questi ultimi due effetti non partono in reduced motion. Timer fermati esplicitamente alla chiusura. Nessuna dipendenza aggiunta. |
| F4 — Test automatici | **PASS** | `tests\test_animations.py`: **7 passed**; suite completa `pytest tests -q`: **343 passed**. Tutte le prove Qt eseguite con `QT_QPA_PLATFORM=offscreen`; nessuna rete o audio reale. |
| F5 — Verifica tecnica | **PASS** | `py_compile` su `ui.py`, `core\animations.py` e `tests\test_animations.py`; `git diff --check` pulito. Grab headless idle/thinking acquisiti in `test-evidence\UI-animation-idle-headless.png` e `test-evidence\UI-animation-thinking-headless.png`. |
| F6 — Convalida manuale | **DA ESEGUIRE** | Non eseguita: serve GUI reale per osservare la transizione completa, verificare fluidità e CPU sotto il 15% in idle e provare `JARVIS_REDUCED_MOTION=1`. Gli screenshot headless verificano il rendering, non sostituiscono la prova visiva manuale. |

### Limiti e blocchi residui

- In reduced motion il HUD continua ad aggiornarsi a circa 30 FPS per mostrare il feedback audio; gli effetti di rotazione, scanner, particelle e pulse continui sono disattivati.
- La scanline è contenuta nel solo HUD e ignora gli eventi mouse; il titolo usa una `QPropertyAnimation` sull'effetto glow. Entrambi vengono fermati alla chiusura e non vengono creati/avviati quando `JARVIS_REDUCED_MOTION=1`.
- Lo stato ERROR resta visibile fino al successivo aggiornamento di stato; il log è la sorgente per gli errori che arrivano attraverso `JarvisUI.write_log`.
- I grab headless mostrano la differenza di stato ma non certificano leggibilità dei font, fluidità o consumo CPU nel runtime desktop. Il tentativo di acquisire l'intera `MainWindow` in modalità offscreen termina con un crash nativo; le immagini disponibili sono quindi preview HUD isolate, non screenshot dell'applicazione completa. F6 resta necessario prima di dichiarare convalidata l'esperienza GUI.

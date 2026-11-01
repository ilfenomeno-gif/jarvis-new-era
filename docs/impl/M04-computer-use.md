# Computer Use — percezione locale e input confermato

Questa fase aggiunge strumenti deterministici per lo schermo Windows; non avvia
un loop agentico e non gestisce attività o sequenze automatiche.

## Percezione

`computer_perception` offre:

- `capture`: dimensioni, posizione, data UTC e pHash del monitor primario. Lo
  screenshot resta in memoria e non viene salvato o caricato.
- `ocr`: parole e coordinate tramite Tesseract locale.
- `uia`: albero limitato della finestra attiva tramite UI Automation, solo per
  processi consentiti.
- `wait_for_change`: confronta pHash successivi per un massimo di 30 secondi.

Per descrizioni visive libere resta disponibile il tool preesistente
`screen_process`, che usa Gemini; non è il backend dei nuovi strumenti.
OCR e UI Automation vengono eseguiti localmente, ma il testo restituito viene
passato al cervello attivo: Gemini in modalità cloud oppure Qwen in modalità
locale.

## Input

`computer_input` accetta una sola azione per chiamata (click, click su testo UIA,
doppio click, trascinamento, movimento, pressione tasto, scorciatoia, scroll o
digitazione). Ogni chiamata viene associata agli argomenti esatti e richiede una
conferma dell'utente in un turno separato. Un `confirmed=true` fornito dal modello
non autorizza l'azione.

L'input è ammesso solo nella finestra attiva e solo per processi nella allowlist.
La conferma è legata all'azione esatta e alla finestra/processo in primo piano:
se il focus cambia prima dell'esecuzione, l'input viene annullato.
Per modificarla, impostare `JARVIS_INPUT_ALLOWLIST` con nomi eseguibili separati
da virgole, ad esempio `notepad.exe,chrome.exe`. Se la variabile è vuota, nessun
processo è autorizzato. La allowlist predefinita contiene Notepad, Chrome, Edge,
Firefox e VS Code; PowerShell, terminali e prompt di sistema non sono inclusi.

`Ctrl+Alt+Esc` è il kill switch globale. Dopo l'attivazione, gli input restano
bloccati fino al riavvio di Jarvis. Se il listener del tasto di emergenza non può
essere installato, nessun input viene eseguito. Le coordinate devono ricadere
nello schermo primario; la digitazione è limitata a 1000 caratteri per chiamata.

## Dipendenze e verifiche

I pacchetti usati (`mss`, Pillow, NumPy, pytesseract, pywinauto, PyAutoGUI,
keyboard e psutil) sono già elencati in `requirements.txt`; non sono aggiunte
nuove dipendenze Python. OCR richiede inoltre l'installazione locale del binario
Tesseract. I test unitari simulano schermo, UIA e input. Le prove con una finestra
reale devono essere avviate separatamente su una sessione Windows interattiva.

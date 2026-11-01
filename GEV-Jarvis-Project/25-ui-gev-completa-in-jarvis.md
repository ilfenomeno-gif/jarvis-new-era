# 25 – UI GEV completa (pannelli e menu) dentro Jarvis

Ciclo secondo `PROCEDURA_IMPLEMENTATIVA_GEV_JARVIS.md`.
Stato fasi (2026-10-04): **0 completata · 1 completata (H1-H4 confermate) · 2/3 aggiornate · 4 implementata · 5 verificata · 6 completata (GEV in Jarvis) · 7 aggiornata · 8 recap**.
Il ciclo 05 (fly-to) resta in coda e passa dopo questo.

## Fase 1 — Scheda diagnosi

**Meccanica:** mostrare nella finestra GEV integrata in Jarvis gli stessi menu
della versione standalone (DATA LAYERS a sinistra, DISPLAY a destra, barra
LOCATION / VISUAL PRESETS in basso, controlli in alto) e farli funzionare.
Il dock MIC nativo resta nascosto per non contendere il microfono a Jarvis.

**Classe:** B (da esporre). La UI esiste già in GEV; manca la sua attivazione
nell'embed.

### Cosa si vede negli screenshot (osservato)

| Osservazione | Fonte |
|---|---|
| GEV standalone (VS Code, `127.0.0.1:4173`) mostra tutti i pannelli: Data Layers, Display (HUD, DETECT, 3D, SCOPE, DRAW, CELESTIAL, CLEAN UI, BLOOM, SHARPEN), Location, Visual Presets, POWER UP | Immagine 1 |
| GEV dentro Jarvis mostra solo il globo ritagliato in un cerchio con sfumatura nera, più l'attribuzione Cesium/Esri. Nessun pannello | Immagine 2 |
| Nella standalone compare "VOICE SYSTEM ERROR – OPENAI_API_KEY is not set" e "POWER UP · 8 KEYS WAITING" | Immagine 1 |
| Log Jarvis: `Plugin 'gev' failed during start(): GEV: conflitto, la porta 4173 è già occupata; non termino il processo esistente.` Poi `open` → `ready` funziona lo stesso | Immagine 2 |

### Esiti della diagnosi H1-H4

- **H1 — confermata.** L'embed usa `?embed=1` o `GEV_EMBED_INLINE`; il CSS
  `ui-embed` nasconde dock e pannelli. Prima non esisteva una modalità UI
  selezionabile.
- **H2 — confermata.** Il cerchio è la maschera GEV in `src/scopeMask.js`
  (`#scope-mask`), non una maschera del widget Jarvis. Jarvis crea una
  `QWebEngineView` ordinaria senza `setMask()` o clipping circolare.
- **H3 — confermata a runtime.** Nella prova Jarvis la finestra misurava
  1986×1471 px fisici; `QWebEngineView` aveva viewport CSS 492×624 a DPR 2
  (984×1248 px fisici). La prima prova ha trovato il pannello Data Layers
  largo quanto quasi tutta la viewport: il selettore responsive era meno
  specifico di quello mobile. La regola è stata corretta; nella prova finale
  Data Layers misura 280 px CSS e il rail Context 290 px. Context è raggiungibile
  scorrendo il rail inferiore.
- **H4 — confermata.** Il controllo vocale viene inserito in `#command-dock`;
  l'embed nasconde quel controllo e il setup POWER UP. Non occorrono chiavi o
  modifiche al provider.

### Dipendenze e rischi

- **Porta 4173 occupata.** Il plugin `gev` non è partito da solo: la pagina
  caricata da Jarvis viene da un server avviato da altri (VS Code/agente).
  Se quel server serve una build vecchia, **le modifiche non si vedranno**.
  Prima di ogni prova fermare il processo duplicato a mano (il plugin non lo
  termina).
- **Stato non sincronizzato.** Un toggle fatto nel pannello GEV non passa dal
  bridge Jarvis: Jarvis non lo sa. L'azione `reset` può azzerare layer attivati
  dai pannelli. Da dichiarare nell'inventario.
- **Voce.** Due consumatori del microfono. Da evitare per costruzione.
- **POWER UP** è limitato al dev server (`src/keySetup.js`): non ha senso
  nell'embed.

**Lacune (Da verificare):** se i pannelli GEV debbano essere ridimensionabili
dall'utente; il layout corrente li rende scrollabili/compatti nella viewport.

## Fase 2 — Piano

### Obiettivo

Nell'embed Jarvis: pannelli **Data Layers**, **Display**, **Location**,
**Visual Presets** visibili e utilizzabili con mouse; globo non più ritagliato
a cerchio (o cerchio disattivabile).

### Fuori perimetro

- Voce nativa GEV (dock MIC) e POWER UP: **nascosti** nell'embed.
- Nuovi comandi vocali Jarvis per i singoli pannelli (restano ai cicli 09-18).
- Modifiche ai provider/chiavi.

### Interfaccia (proposta)

- GEV: modalità UI a tre livelli, scelta da parametro URL (ad esempio `ui=`):
  `globe` (comportamento attuale), `panels` (nuovo: pannelli senza voce né POWER UP),
  `full` (standalone). Default dell'embed invariato (`globe`) per non rompere
  nulla.
- Jarvis: caricare l'embed con `ui=panels`; rimuovere/rendere configurabile la
  maschera circolare; consentire ridimensionamento/schermo intero della finestra
  GEV.
- Nessun nuovo messaggio bridge `gev:*`.

*Nome parametro e punto d'ingresso sono provvisori: vanno confermati leggendo
`src/app/embed.js`.*

### Modifiche per file (da confermare in fase 3)

| Repo | File | Modifica |
|---|---|---|
| GEV | `src/app/embed.js` e `src/ui/styles/embed.css` | distinguere il livello UI dal bridge; esporre i pannelli in `panels`, nascondendo voce e POWER UP |
| GEV | CSS/layout e `style.css` | compattare i pannelli sotto 820 px di altezza e tenere il dock nei limiti del viewport stretto |
| GEV | `src/app/embed.test.mjs` | test parsing e comportamento UI; `cyberTheme.test.mjs` tutela l'ordine degli stili |
| Jarvis | `ui.py` (widget `QWebEngineView`) | URL `?ui=panels`; espandere i pannelli rail e lasciare i due tray inferiori selezionabili uno alla volta |
| Jarvis | `tests/test_gev_mcp_client.py` | test sul livello UI dell'URL |
| Jarvis | `tests/test_gev_mcp_client.py` | test sulla costruzione dell'URL |
| Docs | `MECCANICHE_GEV_JARVIS.md`, `GEV_INTEGRATION.md` | nuova voce + limite "stato non sincronizzato" |

### Test automatici

- Node: livello UI assente → `globe`; valore valido → applicato; valore non
  valido → `globe`.
- Python: l'URL dell'embed contiene il livello atteso; la suite attuale (25 test)
  resta verde.

### Prova manuale (testuale → visiva)

1. Avvio Jarvis con **un solo** server GEV sulla 4173.
2. "Jarvis, apri God's Eye View" → compaiono Data Layers, Display, Location,
   Visual Presets; nessun errore voce, nessun POWER UP.
3. Con il mouse: attivare un layer (es. Active Fires), cambiare stile
   (Visual Presets), usare la barra Location. I due tray inferiori sono
   esclusivi: si aprono uno alla volta.
4. Verificare che i comandi già validati (zoom, tilt, rotate, reset camera,
   `open`, layer vocali) funzionino ancora con i pannelli aperti.
5. Una cattura prima/dopo per ogni punto, salvata in `impl/`.

### Criteri di accettazione

- [x] Data Layers e Display sono visibili; Context è raggiungibile scorrendo il rail; Location e Visual Presets si aprono in modo esclusivo. Verificati `open_tab`, disclosure dei rail, ricerca Location e passaggio Visual Presets `retro` → `normal` in QWebEngine Jarvis.
- [x] `ui=panels` rimuove la maschera circolare; verificato con stile computato nel browser.
- [x] Nessun controllo voce o chip POWER UP in `ui=panels`; verificato nella WebView Jarvis.
- [x] I cicli 01-04 hanno prove testuali/visive già registrate in `impl/01-zoom-incrementale.md`–`impl/04-reset-camera.md`; questo ciclo non modifica il bridge camera.
- [x] Suite Jarvis: 41 passati; GEV: 5.618 test, 5.608 passati, 10 skipped, 0 falliti.
- [x] `globe` resta il default dell'embed e i test di parsing sono verdi.

### Rollback

Un revert per repo; il default invariato rende sicuro il ripristino.

## Fase 3 — Verdetto di fattibilità

| # | Controllo | Esito |
|---|---|---|
| 1 | File e funzioni citati esistono | SÌ — letti `embed.js`, CSS, template e widget |
| 2 | Compatibile col protocollo embed | SÌ — `ui` controlla solo la presentazione, `gev:*` non cambia |
| 3 | Nessuna collisione con azioni/tool esistenti | SÌ — nessuna nuova azione o messaggio bridge |
| 4 | Dipendenze disponibili | SÌ per build/test e GEV locale; host Jarvis non controllato nella prova live |
| 5 | Prova definita | SÌ — test automatici, controllo browser locale e prova live QWebEngine Jarvis |
| 6 | Rollback con un revert | SÌ — un blocco GEV e uno Jarvis, senza commit creati |
| 7 | Impatto su `reset`/layer/follow | Valutato — i toggle visuali non sincronizzano lo stato Jarvis; `reset` può sovrascriverli |
| 8 | Commit per blocco coerente | SÌ — modifiche isolate per repo; nessun commit/push richiesto |

**Esito: PROCEDI** — implementazione, verifica tecnica e convalida end-to-end
nella finestra Jarvis completate.

## Istruzioni per l'agente (ordine obbligatorio)

1. **Fase 0:** `git status` in entrambe le repo; fermare ogni server sulla 4173;
   avviare **un solo** GEV dalla repo modificata; baseline `pytest` + `node --test`.
2. **Diagnosi H1-H4:**
   - in GEV cercare dove `embed` nasconde i pannelli (`embed.js`, `applicationShell.js`);
   - in Jarvis cercare maschera/`setMask`/`border-radius`/vignette nel widget GEV;
   - leggere dimensione reale del widget a runtime;
   - verificare cosa fa il dock MIC in embed.
3. Riportare gli esiti H1-H4 e **completare la tabella di fase 3** prima di
   scrivere codice. Se un esito contraddice il piano → tornare alla fase 2.
4. Poi fasi 4-8 come da procedura. Niente push.

## Esito fasi 4-8 — 2026-10-04

- **Fase 4:** aggiunto `ui=globe|panels|full`, senza cambiare il bridge. Jarvis
  usa `ui=panels`; le rail Data Layers, Display e Context vengono espanse,
  mentre Location e Visual Presets restano tray inferiori selezionabili uno
  alla volta. In modalità panels sono nascosti mic GEV, POWER UP e `#scope-mask`.
- **Preflight:** entrambe le repo erano sul branch `feat/gev-integration`.
  Jarvis aveva già modifiche non commesse in `ui.py`, `plugins/gev_plugin.py`,
  `tests/test_gev_mcp_client.py` e nei due documenti GEV; i diff pertinenti
  sono stati letti e mantenuti. Il checkout GEV era pulito. Il baseline
  `npm test` GEV era **5.615 test, 5.605 passati, 10 skipped, 0 falliti**.
 Il runner iniziale Python non ha scoperto il file test (`No tests found`), ma
 la verifica diretta `pytest -q` ha passato tutti i 41 test.
- **Fase 5:** `pytest -q` Jarvis: **41 passati**. La suite completa GEV ha
 passato **5.608 test su 5.618**, con 10 skipped e 0 fallimenti. Dopo le
 ultime correzioni CSS responsive: `node --test src/app/embed.test.mjs`
 **13/13 passati** e `npm run build` passata; Vite ha emesso il warning già
  previsto sui chunk oltre 1,5 MB.
- **Fase 6 — prova reale Jarvis:** prima di avviare Jarvis è stato liberato il
  listener GEV duplicato sulla 4173; il plugin ha poi avviato il checkout GEV
  modificato e connesso il server MCP (30 tool). Con il microfono Jarvis
  disattivato, il comando testuale “Apri la scheda GEV a schermo ampio” ha
  dispatchato `open_tab`; log UI: pagina caricata, `GEV: ready` e
  “Data Layers, Display e Context aperti; Location e Visual Presets
  disponibili”. La WebView ha caricato `?ui=panels`, senza cerchio, voce GEV o
  POWER UP.
- La misura runtime H3 e il problema di larghezza mobile sono descritti sopra.
  Dopo la correzione, Data Layers misura 280×176 px CSS, Context 290 px; il
  rail Context è scrollabile ed entra nell'area visibile. I pulsanti di
  disclosure Data Layers, Display e Context si sono chiusi/riaperti. Location
  e Visual Presets si sono aperti a turno; i popover sono rimasti dentro la
  viewport 492×624 CSS. La ricerca Location è stata resa visibile senza inviare
  una ricerca; Visual Presets è passato da `normal` a `retro` e ripristinato a
  `normal`. Il dock è disposto su due colonne e non introduce scorrimento
  orizzontale involontario. Nessun layer con provider esterno è stato attivato
  in questo giro.
- Evidenza acquisita dalla WebView Jarvis, senza il pannello chat: [Data Layers + Display](./impl/25-gev-panels-display.png) e [Data Layers + Context](./impl/25-gev-panels-context.png). I cicli camera 01-04 hanno già evidenza testuale/visiva nei relativi file `impl/`; la revisione personale delle quattro schermate e la prova microfono restano pendenti.
- **Fase 7:** aggiornati `docs/GEV_INTEGRATION.md` e
  `docs/MECCANICHE_GEV_JARVIS.md`, incluso il limite dello stato layer non
  sincronizzato.
- **Fase 8:** recap registrato qui. Le modifiche Jarvis preesistenti relative a
  `open_tab`/`hide_tab` e la documentazione/test associati sono state mantenute
  e integrate; nessun commit né push è stato eseguito.
- **Chiusura sessione:** Jarvis è stato riavviato normalmente con GEV pronto
  (`GEV: pronto`, 30 tool MCP disponibili); il listener temporaneo di debug
  remoto `127.0.0.1:9222` è assente. Resta aperta l'app Jarvis.

# Configurazione connettori

I token e le credenziali client sono salvati nel vault DPAPI su Windows; il
wizard aggiorna anche le variabili necessarie nel `.env` locale per renderle
disponibili ai componenti che leggono l'ambiente. Il `.env` e' escluso da Git.
Jarvis usa authorization code + PKCE, verifica `state` e rinnova i token quando
il provider restituisce un refresh token. Non condividere il `.env` o i segreti.

Lo stato dei permessi selezionati viene salvato automaticamente in
`config/connectors_state.json` a ogni modifica. Al riavvio Jarvis rilegge i
permessi dal file e i token dal vault cifrato: un token presente riporta il
connettore a **Connected** e ripristina le caselle selezionate. Il token OAuth
viene salvato al completamento del callback; il PAT GitHub viene salvato nel
vault automaticamente dopo l'inserimento, senza premere un pulsante di
salvataggio.

## Wizard Plugins & Connections

Per GitHub, Canva, Spotify e Google Workspace, premi **Configura ora** nella
scheda; per i connettori che lo consentono puoi anche premere **Connetti** e poi
**Configura ora** nel messaggio. Il modulo mostra, se disponibile, il link del
provider e l'URI di reindirizzamento da registrare; dopo **Salva**, Jarvis
aggiorna automaticamente `.env` e il vault, senza richiedere modifiche manuali
ai file. **Connetti** avvia quindi il flusso OAuth nel browser.

### Comandi vocali

Per avviare direttamente OAuth, pronuncia per esempio **«Connetti GitHub»**,
**«Collega GitHub»**, **«Accedi a GitHub»** o **«Connetti Spotify»**. Jarvis
risolve il servizio tra i connettori registrati, avvia lo stesso flusso OAuth
della scheda e apre il browser predefinito. Il listener locale deve avviarsi
prima dell'apertura del browser; in caso di credenziali mancanti o errore di
bind, Jarvis segnala il problema invece di dichiarare la connessione avviata.

La scheda **Plugins & Connections**, se aperta, mostra **In attesa di
autorizzazione…** durante il consenso e passa allo stato verde quando il
callback completa l'autenticazione. Per richieste ambigue con più servizi,
specificane uno solo.

## GitHub

Il server MCP remoto e' `https://api.githubcopilot.com/mcp/`. Crea/configura
un OAuth App GitHub dalla [pagina OAuth Apps](https://github.com/settings/applications/new)
e registra esattamente questo callback:

`http://127.0.0.1:8770/oauth/github/callback`

La porta `8770` e' dedicata alla callback OAuth: la `8765` e' usata dall'HUD
locale e una callback su quella porta puo' essere intercettata dall'HUD invece
che dal server OAuth, restituendo 404.

Il server callback viene avviato quando premi **Connetti**, non all'avvio di
Jarvis; resta attivo mentre aspetta la risposta OAuth. Nel terminale compare
`OAuth callback server listening on 127.0.0.1:8770/oauth/github/callback`.
Prima di aprire il browser Jarvis verifica che l'URL di autorizzazione contenga
un Client ID e che il `redirect_uri` decodificato corrisponda esattamente al
callback dichiarato nel catalogo. Il log riporta solo la presenza del Client ID
e il callback, mai il valore delle credenziali.
Se la porta e' gia' occupata, Jarvis mostra un errore esplicito. Riavvia Jarvis
dopo gli aggiornamenti del codice per caricare la gestione corretta della porta.
Prima del bind controlla i listener con `psutil`, attende fino a due secondi
per connessioni `TIME_WAIT` e ritenta il bind fino a tre volte. Non termina
automaticamente altri processi: se trova un listener, mostra il PID per
consentire di identificarlo e chiuderlo in modo consapevole. L'URL di GitHub
viene aperto solo dopo che il bind e l'avvio del server callback sono riusciti.
Ogni richiesta callback registra il percorso senza query string, per evitare di
esporre il codice OAuth o il parametro `state`; i percorsi errati restituiscono
un JSON con percorso ricevuto e previsto. Un errore nello scambio del token dopo
la ricezione della rotta viene riportato come errore OAuth, non come 404.

In **Plugins & Connections**, usa **Configura ora** o **Connetti**. Incolla il
Client ID e il Client Secret appena generato, quindi registra il callback
mostrato nel modulo. Il salvataggio aggiorna `.env` e il vault cifrato locale.
Il Client Secret e' un valore segreto: non condividerlo.
All'avvio, un valore impostato nell'ambiente (incluso `.env`) prevale su quello
precedentemente salvato nel vault; per questo, dopo aver aggiornato il `.env`,
riavvia Jarvis prima di riprovare.

Nel modulo **Configura OAuth — GitHub**, **Verifica Connessione** controlla in
background che i campi siano compilati e che l'API GitHub sia raggiungibile.
GitHub non offre un endpoint che convalidi il Client Secret senza completare
OAuth: Jarvis lo dichiara esplicitamente e il provider lo verifica durante il
login. Errori di callback o scambio token (per esempio `redirect_uri_mismatch`,
`bad_verification_code` o HTTP 401) vengono registrati senza credenziali e
mostrati nella scheda con un avviso.

In alternativa a OAuth, premi **Usa Token Manuale** nella scheda GitHub e
incolla un Personal Access Token Classic. Jarvis lo salva nel vault cifrato
con la chiave `connector:github`, lo usa nell'header MCP
`Authorization: Bearer <token>` e segna il connettore come connesso senza
aprire il browser. Crea il token da
[GitHub Personal Access Tokens (Classic)](https://github.com/settings/tokens/new)
e seleziona gli scope `repo` e `read:org`. Il token non viene mostrato o
registrato nei log. I permessi interni Jarvis restano separati: selezionali
nella scheda Plugins & Connections dopo aver salvato il token.

Per richieste come **«Quanti repository ho su GitHub?»** o **«Elenca i miei
repository»**, Jarvis usa `github_user_repositories`, che consulta
`GET /user/repos` per l'account autenticato, segue tutte le pagine e restituisce
conteggio e nomi dei repository posseduti. Non richiede argomenti o username;
richiede che GitHub sia connesso e che il permesso Jarvis `repo.read` sia
concesso. `github.search_repositories` è invece riservato a ricerche con una
query esplicita; una chiamata senza query viene rifiutata con un messaggio
indicativo.

Le richieste di ricerca come **«Cerca repository con la parola python»** vengono
instradate a `github_search_repositories`, che usa l'API REST autenticata di
GitHub; per queste richieste il router non propone la ricerca web generica
`web_search`. La query è obbligatoria e viene ricavata dai termini indicati
dall'utente. L'azione imposta `per_page=5`, mostrando il totale restituito e al
massimo i primi cinque nomi.

## Canva

Il catalogo usa l'endpoint MCP documentato da Canva,
`https://api.canva.com/connect/v1/mcp`, i relativi authorize/token endpoint
ufficiali, l'indicatore OAuth `resource` e i tool `search-designs` e
`create-design`. Nel Developer Portal crea un'app, abilita Canva MCP e registra
esattamente:

`http://127.0.0.1:8767/oauth/canva/callback`

Per configurare l'app, apri il [Canva Developer Portal](https://www.canva.com/developers/).
Poi premi **Configura ora** nella scheda Plugins & Connections, copia nel portale
l'URI mostrato dal modulo, e inserisci Client ID e Client Secret. **Salva**
aggiorna `.env` e il vault cifrato. **Connetti** apre il consenso OAuth.

Richiede connessione individuale Canva e permessi abilitati nell'app. Fonti:
[Canva MCP access](https://www.canva.dev/docs/apps/mcp/access/)
e [Canva MCP tools](https://www.canva.dev/docs/apps/mcp/tools/).

## Higgsfield

Il catalogo usa `https://mcp.higgsfield.ai/mcp` e il server OAuth Clerk
indicato nei metadata del provider. Premi direttamente **Connetti**:
Jarvis registra automaticamente un client pubblico tramite l'endpoint OAuth di
registrazione, memorizza il client ID restituito nel vault DPAPI, usa PKCE e
l'indicatore `resource`, e richiede
`openid`, `email` e `offline_access`. Il callback locale e'
`http://127.0.0.1:8769/oauth/higgsfield/callback`. I token di rinnovo vengono
salvati cifrati. La registrazione effettiva richiede che il provider accetti la
richiesta client di Jarvis.

## Google Workspace

Crea un client OAuth in Google Cloud Console e registra il callback
`http://127.0.0.1:8766/oauth/google/callback`. Nella scheda premi **Configura
ora** e inserisci Client ID e Client Secret. Dopo il salvataggio, **Connetti**
avvia il consenso OAuth nel browser. **Configura ora** rimane disponibile anche
dopo il salvataggio, per aggiornare le credenziali.

Il consenso richiede esclusivamente `gmail.readonly` e `calendar` (gli URI
completi sono nel catalogo). Non autorizza l'invio Gmail o l'accesso a Drive:
quegli strumenti non funzioneranno con un token che non disponga già dei
relativi permessi. I permessi selezionati in Jarvis non ampliano gli scope
concessi da Google.

Il Client ID deve terminare in `.apps.googleusercontent.com`: un ID mancante o
con formato diverso blocca l'apertura del browser. Un formato corretto non
garantisce che il client esista o sia attivo: per `invalid_client`, verifica
l'ID nel progetto Google Cloud. All'inizializzazione del runtime Jarvis registra
la presenza, la lunghezza e al massimo i primi dieci caratteri dell'ID letto
dall'ambiente. All'avvio del consenso stampa l'URL con Client ID e callback
visibili, ma `state` ed eventuali segreti oscurati. Non pubblicare il log.

Quando Google restituisce un errore al callback locale, Jarvis mostra il codice
e l'eventuale descrizione nella scheda. Se Google mostra l'errore direttamente
nella propria pagina senza reindirizzare al callback, Jarvis non riceve quei
parametri: consulta il dettaglio nel browser. `flowName=GeneralOAuthFlow` da
solo identifica il flusso e non specifica la causa dell'errore.

Il runtime carica `.env` all'avvio senza sovrascrivere le variabili già
presenti nell'ambiente del processo. Un valore d'ambiente non vuoto prevale
sul vault; modificando `.env` manualmente, riavvia Jarvis e verifica che una
variabile d'ambiente precedente non contenga un ID diverso.

La ricerca `gmail.search` usa direttamente la Gmail API ufficiale. Abilita la
Gmail API nel progetto Google Cloud e concedi anche `gmail.read` nella scheda
dei permessi di Jarvis. La ricerca accetta `query` e `max_results` (1–100) e
restituisce mittente, data e oggetto; se non trova messaggi lo indica
esplicitamente. Il token di accesso viene rinnovato automaticamente quando è
scaduto, se Google ha fornito un refresh token valido. Un errore HTTP 403 può
dipendere anche da altre restrizioni Google, non solo dagli scope: consulta il
codice HTTP nel log e controlla la configurazione del progetto e dell'account.
L'invio Gmail, Calendar e Drive non sono implementati dal trasporto diretto.

### Contesto ambientale

Il motore di contesto aggiorna ogni cinque secondi finestra attiva, inattività
Windows e stato del calendario primario. Per interrogare Calendar servono
account Google collegato, API Calendar abilitata e permesso `calendar.read`
concesso a Jarvis. Gli eventi imminenti sono quelli entro 30 minuti; gli eventi
giornalieri senza orario non sono considerati. Errori o permessi mancanti
rendono lo stato calendario non disponibile.

Il titolo della finestra, il nome dell'evento e l'ultima frase pronunciata sono
conservati solo in memoria nel processo. L'azione `check_context` e il contesto
per i modelli contengono la categoria e un nome di app predefinito oppure
derivato dal nome del processo, oltre a fascia oraria, inattività e stato
dell'evento. Titoli di finestre e documenti e trascrizioni non vengono inviati.
I nomi dei processi possono rivelare le applicazioni installate e, se
personalizzati dall'utente, potrebbero contenere informazioni personali.
Anche i processi di sistema sono riportati quando identificabili; il titolo
non determina mai il nome dell'app. Se il processo non è accessibile o il suo
nome è vuoto, resta la categoria generica.
Impostare `JARVIS_CONTEXT_AWARENESS=0` prima dell'avvio disabilita il motore.
L'azione `check_context` legge esclusivamente uno snapshot in memoria, senza
avviare il motore o chiamare Calendar; uno stato calendario più vecchio di
60 secondi è indicato come non disponibile. Nelle sessioni Gemini Live il
prompt resta fisso: il modello è istruito a non richiamare l'azione a ogni
turno, ma solo su richiesta esplicita o se gli mancano informazioni contestuali.
La scelta di chiamarla resta del modello. La personalità dispone anche
dell'aggiornamento autonomo descritto sotto.

Il motore proattivo controlla il contesto ogni 30 secondi e può segnalare
inattività prolungata, eventi entro cinque minuti, attività alle 02:00 o una
sessione attiva di due ore nella stessa categoria di app. Gli interventi hanno
un intervallo minimo globale di 15 minuti e non vengono inviati durante una
conversazione o quando l'audio è disattivato. Gli eventi del calendario
vengono segnalati senza inviarne il titolo al modello. «Non disturbarmi per
un'ora» sospende i trigger; «stai zitto» li sospende fino a «riprendi».
La pausa riguarda il motore proattivo contestuale, non i promemoria espliciti
o gli altri monitor. Per disattivarlo all'avvio impostare
`JARVIS_PROACTIVE_ENGINE=0`; disabilitare il motore di contesto disattiva
anche questi trigger.

### Presenza ambientale

Il motore ambientale controlla localmente la categoria dell'app, l'inattività e
il desktop di input Windows. Dopo oltre cinque minuti continui in un'app di
lavoro o call passa in FOCUS; con app relax o inattività fra 2 e 10 minuti
passa in AVAILABLE; oltre 15 minuti di inattività o a PC bloccato passa in
AWAY. Se non riesce a determinare il blocco, o il contesto è ambiguo, adotta
prudentemente FOCUS. Le categorie sono euristiche: Zoom e Teams sono riconosciuti
dai nomi dei processi, non dal contenuto delle chiamate.

In FOCUS gli interventi proattivi raggiungono solo la UI; in AWAY sono
sospesi. In AVAILABLE solo confidenza maggiore di 0,9 permette la voce;
da 0 a 0,9 la notifica è solo UI. Anche una notifica UI consuma il cooldown
proattivo. Le notifiche di sistema ad alta temperatura della CPU possono
parlare in FOCUS come emergenza, ma non in AWAY o in modalità silenziosa.
L'audio proattivo autonomo di Gemini è disabilitato quando è attiva la
presenza ambientale: gli interventi passano dal controllo locale.

«Modalità focus» forza FOCUS anche se il contesto cambia; le notifiche restano
comunque sospese se il PC è bloccato o l'utente è assente. «Modalità normale»
annulla l'impostazione manuale; «modalità silenziosa» blocca per un'ora la
riproduzione vocale di Jarvis e invia gli interventi ammessi solo alla UI.
La modalità silenziosa non controlla l'audio di altre applicazioni o lettori
indipendenti. Gemini può comunque generare audio sul server, che Jarvis scarta.

### Personalità adattiva

La personalità usa la categoria locale dell'app e l'ora, senza trasmettere
titoli di finestre, eventi o conversazioni. Le categorie relax comprendono
Spotify, Steam, alcuni giochi riconosciuti per nome del processo e finestre
browser identificate come YouTube; altre attività non riconosciute restano
generiche. Il tono cambia alle 06, 12, 18 e 23; relax prevale sull'orario.
Senza Context Awareness l'adattamento non dispone del contesto, ma può
comunque applicare le preferenze salvate.
Nella pipeline vocale con Piper la velocità configurata viene
modulata del 5% al mattino e del -10% di notte; gli altri TTS non vengono
modificati. Per Gemini Live, un controllo ogni cinque minuti e le notifiche
del Context Engine (normalmente ogni cinque secondi) inviano i cambiamenti di
personalità come aggiornamenti di contesto senza avviare un turno. Il modello
continua a ricevere il prompt di sistema originale: l'adesione alla nuova
istruzione dipende dal modello e dall'API. Se l'invio segnala un errore, Jarvis
lo mostra e prova ad anteporre alla successiva risposta vocale una breve
transizione tramite la voce locale di sistema; questa transizione non cambia
il prompt del modello. Gli aggiornamenti saranno ritentati al controllo
successivo. Titoli e nomi degli eventi non vengono inviati.
Impostare `JARVIS_PERSONALITY_ENGINE=0` prima dell'avvio disabilita
l'adattamento, ripristinando il tono formale predefinito.

### Apprendimento dalle interazioni

Jarvis riconosce correzioni come «sii più breve», «parla più formalmente» e
«non usare il termine ...», oltre alle richieste esplicite come «ricorda che
preferisco ...». «Cosa hai imparato su di me?» elenca le preferenze e i fatti
salvati; «no, il mio compleanno è il 5 marzo, non il 6» corregge il dato.
Altre correzioni semplici nella forma «no, il mio/la mia ... è ..., non ...»
sono riconosciute, ma il riconoscimento non copre ogni possibile formulazione.
I fatti sono dichiarati dall'utente, **non verificati indipendentemente**.

Il profilo `config/user_profile.json` è locale, escluso da Git e non cifrato:
contiene dati personali, quindi proteggerne l'accesso e non inserirvi segreti.
Il filtro per credenziali è prudenziale, non una garanzia completa. Preferenze
e fatti rilevanti possono essere inclusi nel prompt inviato al provider LLM.
Le preferenze precedono lo stile contestuale nei turni successivi; Gemini Live
riceve l'aggiornamento senza riconnettersi, ma il rispetto del prompt dipende
dal modello. `JARVIS_PERSONALITY_ENGINE=0` disabilita anche la loro applicazione
al prompt, non il salvataggio o il riepilogo. Nella modalità vocale Live la
trascrizione completa può arrivare dopo l'inizio della risposta corrente.

### Simbiosi hardware

La simbiosi è controllata da `JARVIS_SYMBIOSIS` (`0` per disabilitarla) e
`JARVIS_SYMBIOSIS_MODULES` (nomi separati da virgola). Le metriche vengono
campionate localmente; la disponibilità di GPU, temperatura, batteria e Wi-Fi
dipende dall'hardware e dalle API Windows. Gli alert rispettano presenza
ambientale, pausa e cooldown proattivo. «Non avvisarmi della batteria» salva
la preferenza e disattiva gli avvisi proattivi della batteria.

La cronologia degli appunti è conservata localmente in
`config/clipboard_history.json`, escluso da Git ma **non cifrato**. Può
contenere informazioni private: il filtro dei segreti riconosciuti è parziale
e non impedisce la registrazione di tutte le password. Per evitare il
monitoraggio degli appunti escludere `clipboard` da
`JARVIS_SYMBIOSIS_MODULES`. Le azioni esposte al modello ricevono solo tipo,
lunghezza e data; nell'HUD il contenuto è visibile solo su richiesta tramite
«Mostra ultimi 10 appunti». L'endpoint locale HUD non è autenticato contro
altri processi dello stesso computer. Il comando «incolla ultimo
appunto» ripristina gli appunti e invia Ctrl+V alla finestra attiva: verificare
la finestra prima di usarlo.

I moduli selezionabili sono `pulse,process,clipboard,network,monitor`; ad
esempio `JARVIS_SYMBIOSIS_MODULES=pulse,process,network,monitor` esclude gli
appunti. Senza la variabile sono richiesti tutti i moduli. La facciata riporta
errori di avvio e arresto nei log; componenti o sensori non disponibili non
sono considerati misurazioni zero. Gli alert CPU, processi e Wi-Fi richiedono
campioni recenti e consecutivi: dopo un'interruzione della raccolta la durata
viene ricominciata, senza riutilizzare letture vecchie.

Comandi d'esempio: «controlla CPU/RAM/disco/batteria/GPU/temperatura»,
«mostra i processi che consumano più CPU», «chiudi il processo», «mostra
cronologia appunti», «controlla Wi-Fi/VPN/firewall», «elenca i monitor» e
«disponi le finestre». La chiusura o il riavvio di un processo richiedono
conferma esplicita e rifiutano i processi protetti; il ripristino e
l'organizzazione delle finestre operano solo su finestre non protette.
Per i processi si può confermare o annullare dall'HUD oppure, quando
disponibile, con una nuova risposta vocale breve dopo la richiesta. La
conferma vocale usa Whisper locale e non identifica biometricamente la
persona: rumori, riproduzioni o errori di riconoscimento possono influire.
Se il riconoscimento locale non è disponibile, usare il pulsante HUD.
Indirizzi IP, SSID e contenuti degli appunti non vengono restituiti al modello.
Per «controlla Wi-Fi», quando disponibile, il nome SSID viene pronunciato con
la voce di sistema locale separatamente dalla risposta al modello; se la voce
locale non è disponibile viene segnalato. L'SSID è anche mostrato nella chat
locale, anche in modalità silenziosa, senza essere incluso nel risultato per
il modello. L'SSID resta udibile a chi è vicino quando la voce è attiva. Se
Windows non rende disponibili i dettagli Wi-Fi, il nome non può essere letto.
I dettagli di rete sono visibili nell'HUD solo premendo i pulsanti dedicati;
«IP pubblico» contatta ipify (timeout 3 secondi, cache locale 60 secondi).
I layout di monitor vengono salvati localmente in
`%LOCALAPPDATA%\JarvisVII\monitor_layouts.json`; i titoli sono rappresentati
da hash, non da testo in chiaro.

«Sostituisciti con la pagina accanto» scambia posizione e dimensioni della
finestra Jarvis e della finestra attiva; «sposta Jarvis a destra e l'altra
pagina a sinistra» le affianca sul monitor dell'altra finestra. Se è attiva
Jarvis, viene scelta la finestra idonea più grande: è un'euristica, non
necessariamente la finestra usata in precedenza. Finestre protette o minimizzate
non vengono spostate; le finestre massimizzate vengono ripristinate prima dello
spostamento. Se il secondo spostamento fallisce viene
tentato il ripristino del primo.

La chiusura dell'app su Windows richiede conferma e usa la finestra selezionata
prima della conferma, senza inviare Alt+F4 alla HUD. L'app può mostrare una
propria richiesta per salvare documenti. La normalizzazione italiana della
voce usa `num2words` (installato con le dipendenze del progetto). Con Gemini
Live l'audio è generato direttamente dal modello: un'istruzione richiede una
pronuncia naturale, ma la normalizzazione locale non può garantirla.

## Spotify

Spotify usa la Web API ufficiale, non un server MCP. Il connettore Jarvis
autorizza con PKCE (senza client secret) e supporta "attualmente in
riproduzione" e "riproduci brano". Crea un'app nel Developer Dashboard,
registra esattamente `http://127.0.0.1:8768/oauth/spotify/callback`, poi usa
**Configura ora** e inserisci il Client ID. Il modulo indica che Spotify usa
PKCE e non richiede un Client Secret. L'app si crea dal
[Developer Dashboard](https://developer.spotify.com/dashboard).

Il plugin legacy `spotify_music_control` resta separato e continua ad usare
`SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET` e `SPOTIFY_REFRESH_TOKEN`.

Fonti: [Spotify authorization](https://developer.spotify.com/documentation/web-api/concepts/authorization)
e [Spotify scopes](https://developer.spotify.com/documentation/web-api/concepts/scopes).

## Catalogo Public APIs

La scheda **Plugins & Connections** include il catalogo read-only
`public-apis-mcp`, avviato localmente via MCP `stdio` con l'interprete Python
di Jarvis (`python -m public_apis_mcp`). Non richiede credenziali OAuth né
`uvx`/`npx`: installa il pacchetto fissato alla versione `0.1.0` con
`python -m pip install -r requirements.txt` nell'ambiente virtuale del
progetto. Premi **Attiva Catalogo** per avviare il server; lo stato di avvio
appare nella scheda prima che la ricerca venga abilitata.

Il server espone `search_public_apis` e `get_public_api_details`. Jarvis
aggiunge `filter_apis_by_auth` come ricerca composta: recupera i dettagli di
ciascun risultato e filtra quelli con `auth` impostato a `None`; non e' un tool
fornito direttamente dal server. Esempi:

- «Cerca un'API gratuita per le previsioni del tempo»
- «Mostrami le API nella categoria Finance»
- «Cerca API meteo senza autenticazione»

Le richieste vocali che menzionano API pubbliche/gratuite, il catalogo o
l'autenticazione instradano i tool read-only `search_public_apis`,
`get_public_api_details` e `filter_apis_by_auth` al modello; non richiedono
conferma. Attiva il catalogo una volta nella scheda prima di usarli. Il catalogo
descrive API di terze parti: la ricerca non le chiama e non ne verifica
disponibilità, gratuità o sicurezza. Per impostazione predefinita il server
viene avviato solo dopo aver premuto **Attiva Catalogo**.

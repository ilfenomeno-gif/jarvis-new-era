# M00 — Repository discovery and baseline

## Obiettivo

Documentare la struttura effettiva di Jarvis Ultimate e acquisire una baseline
di avvio prima di intervenire sul codice, confermando o smentendo le ipotesi
architetturali della guida.

## 1. Diagnosi (stato reale del repo, rischi, dipendenze)

- Checkout Windows, Python 3.13.7, PyQt6 6.11.0 / Qt 6.11.2.
- Entry point `main.py`; UI PyQt in `ui.py`; stack HUD/camera/GEV già presente.
- `QWebEngineView` è usata per GEV, non ancora per una pagina web generale.
- Gli strumenti Gemini sono dichiarati in `main.py`; i plugin passano da
  `core/plugin_loader.py`. GEV usa `plugins/gev_plugin.py`.
- `actions/browser_control.py` usa Playwright e `webbrowser.open`; non equivale
  a una vista web integrata.
- Baseline: UI enumerata e processo attivo, 18 plugin accettati, GEV/MCP pronto
  con 30 tool. Gemini era ancora `Connecting...`; audio non convalidato.
- Rischi da mantenere visibili nei cicli seguenti: thread GUI Qt, lifecycle GEV,
  audio condiviso, validazione URL, pagina web non attendibile e tool dispatch.

## 2. Procedura (sotto-passi atomici: file → modifica → criterio di successo)

1. Leggere la guida e verificare il repository senza modificare file → checkout,
   branch e stato iniziale identificati.
2. Avviare l'app prima delle modifiche → processo, finestra, plugin e warning
   registrati senza leggere segreti.
3. Mappare entry point, UI, plugin, tool Gemini, Qt e dipendenze → ogni ipotesi
   classificata con riferimenti a sorgenti reali.
4. Copiare `IMPLEMENTATION.md` identico nella root e creare i file M0 → copia
   SHA256 uguale; documenti presenti e coerenti con le evidenze.
5. Eseguire controlli documentali e `git diff --check` → nessun errore whitespace
   o divergenza tra guida sorgente e copia.

## 3. Modifiche per file

- `IMPLEMENTATION.md`: copia byte-identica della guida fornita nel progetto
  operativo.
- `docs/REPO_MAP.md`: albero, entry point, architettura UI, tool Gemini, plugin,
  versioni, ipotesi e baseline.
- `docs/impl/M00-discovery.md`: diagnosi, procedura, fattibilità, verifica e
  recap M0.
- `PROGRESS.md`: stato dei cicli M0–M4.
- `OPEN_QUESTIONS.md`: limiti della baseline e scelta NVIDIA M4.

## 4. Test plan (automatici + manuali)

- Manuale: avvio `main.py` senza modifiche, enumerazione finestra, esame sicuro
  dei log di startup e conferma del lifecycle GEV.
- Ambiente: versione interprete e versioni PyQt/Qt via runtime.
- Documentazione: SHA256 della guida prima/dopo copia; controllo stato Git e
  `git diff --check`.

## 5. Criteri di accettazione (checklist PASS/FAIL)

- [x] `docs/REPO_MAP.md` presente, con fonti e percorso dei componenti.
- [x] `ui.py`, `plugins/gev_plugin.py`, `QWebEngineView` e `QStackedWidget`
  confermati con file/posizioni reali.
- [x] L'app è stata avviata prima di ogni modifica documentale; baseline e
  anomalie sono registrate.
- [x] `IMPLEMENTATION.md` presente nella root e identico alla fonte fornita.
- [x] `PROGRESS.md` e `OPEN_QUESTIONS.md` presenti.
- [x] Limiti della prova Gemini/audio dichiarati senza assumere esiti positivi.

## 6. Analisi di fattibilità del presente file (checklist GO/NO-GO + esito)

- [x] File e simboli citati esistono o sono esplicitamente ipotesi verificate.
- [x] Nessuna nuova dipendenza richiesta.
- [x] Nessun conflitto con feature esistenti: M0 è documentazione, GEV resta
  intatto.
- [x] Verifica eseguibile localmente senza credenziali esposte.
- [x] Rollback definito sotto.

**Esito: GO.**

## 7. Rollback (come tornare indietro)

Rimuovere con un commit inverso solo i nuovi documenti M0 e la copia
`IMPLEMENTATION.md`; non toccare né cancellare dati locali. Non usare reset o
riscrittura della history.

## 8. Registro esecuzione (data, esito verifica, esito convalida)

- 2026-10-04: baseline prima di modifiche. PASS processo/UI; PASS plugin GEV e
  MCP; Gemini/audio parziali e registrati come limiti.
- 2026-10-04: hash SHA256 guida originale e copia identici. Branch dedicato
  `feat/m00-repo-discovery`.

## 9. Recap finale

M0 documenta l'architettura concreta e baseline; le ipotesi sono confermate,
con la precisazione che gli stack esistenti non costituiscono un browser
generale. La sessione Gemini completa e l'audio restano non convalidati. M1 può
procedere su branch dedicato, mantenendo GEV indipendente.

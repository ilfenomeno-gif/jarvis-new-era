---
name: app-launcher
description: >
  Cerca e avvia applicazioni Windows installate tramite nome, con conferma esplicita
  e controlli di percorso. Usare quando l'utente chiede di aprire un'app desktop.
triggers: apri un'app, avvia un'applicazione, lancia un programma, apri il Blocco Note
tool_refs: app_launcher
risk_class: destructive
status: active
---
# Procedura
1. Non usare questa skill per i giochi: seguire la procedura del launcher Steam/Epic.
2. Passare ad `app_launcher` soltanto il nome dell'applicazione, mai un percorso o un comando.
3. Attendere la conferma esplicita dell'utente prima di ogni lancio; non impostare `confirmed=true` per deduzione.
4. Per app fuori da Program Files, LocalAppData\Programs e Windows, chiedere conferma riferita al nome specifico dell'app.
5. Non avviare mai eseguibili trovati in `Downloads`, `Temp` o `TMP`, anche se l'utente conferma.
6. Non fornire argomenti arbitrari. L'unico argomento ammesso è `--help` per app CLI supportate; se l'utente chiede altro, spiegare il limite e chiedere un percorso alternativo autorizzato.
7. La ricerca senza avvio si può provare con `python -m core.registry_cli app-search <nome>`.
8. `JARVIS_APP_LAUNCHER=0` disabilita il tool.

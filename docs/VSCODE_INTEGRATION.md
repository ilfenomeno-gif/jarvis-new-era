# JARVIS e VS Code nel browser con code-server

## Che cos'è code-server

code-server è un progetto separato che rende disponibile un ambiente di editing
basato su VS Code tramite browser. Non è l'applicazione desktop di Visual Studio
Code e va installato e gestito dall'utente.

## Installazione

Con Node.js e npm installati, eseguire:

```powershell
npm install -g code-server
```

Verificare l'installazione:

```powershell
code-server --version
```

## Password e configurazione

Il primo avvio genera una configurazione utente, in genere in
`%USERPROFILE%\.config\code-server\config.yaml` su Windows. Modificare il file
per mantenere l'ascolto solo sul computer locale e impostare una password:

```yaml
bind-addr: 127.0.0.1:8080
auth: password
password: cambia-questa-password-con-una-password-forte
cert: false
```

Proteggere il file di configurazione e non condividere la password. Non esporre
code-server su un'interfaccia di rete pubblica senza una configurazione di
sicurezza aggiuntiva.

## Avvio e uso con JARVIS

Avviare code-server manualmente in PowerShell:

```powershell
code-server
```

Lasciare il processo in esecuzione. Quindi chiedere a JARVIS:

> Jarvis, apri VS Code nel browser

Il plugin `vscode_web` apre `http://127.0.0.1:8080` nella webview interna di
JARVIS. Se la webview non è disponibile o fallisce, il plugin registra il
fallback nel log di JARVIS e passa l'URL all'azione `browser_control`.

## Limiti noti

- code-server è un progetto separato e deve essere installato dall'utente.
- JARVIS non avvia code-server automaticamente.
- Non è configurato alcun autostart: dopo un riavvio, l'utente deve avviare
  code-server manualmente prima di richiamare il plugin.
- Il plugin apre soltanto l'URL locale; non installa, configura o arresta
  code-server e non gestisce la password.

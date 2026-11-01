# Comandi utili

Comandi documentati, non necessariamente eseguiti oltre a quelli esplicitamente indicati nelle verifiche.

## Percorsi e avvio

```powershell
$jarvis = 'C:\Users\PC\Downloads\Mark-LIV-main\Mark-LIV-main'
$gev = 'C:\Users\PC\Downloads\gods-eye-view-main\_gev-clone'
Set-Location $jarvis
.\.venv\Scripts\python.exe main.py

Set-Location $gev
& '.\.node\node.exe' '.\node_modules\vite\bin\vite.js' --host 127.0.0.1 --port 4173 --strictPort
```

> Da verificare: nome/percorso Python virtualenv effettivo. Il comando Python è un esempio di attivazione, non un path verificato.

## Stato, diff e storia Git

```powershell
git -C $jarvis status --short --branch
git -C $jarvis diff
git -C $jarvis diff main..feat/gev-integration --stat
git -C $jarvis diff main..feat/gev-integration --name-status
git -C $jarvis log --oneline --all
git -C $jarvis log --stat -10
git -C $jarvis show --stat bbdcff8
git -C $jarvis switch feat/gev-integration
```

## Porta e processi

```powershell
Get-NetTCPConnection -LocalPort 4173 -ErrorAction SilentlyContinue
Get-Process node -ErrorAction SilentlyContinue | Select-Object Id,Path,StartTime
Invoke-WebRequest 'http://127.0.0.1:4173/' -UseBasicParsing
```

## Test

```powershell
Set-Location $jarvis
pytest tests

Set-Location $gev
& '.\.node\node.exe' '.\node_modules\npm\bin\npm-cli.js' test
```

La repo Jarvis osservata non ha `tests/test_plugin_lifecycle.py`; GEV definisce lo script `test` in `package.json:46`. Questi comandi non sono stati eseguiti in questa raccolta.


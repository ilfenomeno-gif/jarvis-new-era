# Avvio manuale di GEV

## Requisiti

GEV è un'app Vite (`package.json:34-46`); il plugin la avvia su `127.0.0.1:4173` con strict port (`plugins/gev_plugin.py:316-326`). La directory `node_modules` potrebbe mancare; lo start Jarvis esegue install solo in quel caso (`:287-311`).

## Comandi da PowerShell

```powershell
$gev = 'C:\Users\PC\Downloads\gods-eye-view-main\_gev-clone'
$node = Join-Path $gev '.node\node.exe'
Set-Location $gev

# Se le dipendenze non sono presenti:
& $node '.node\node_modules\npm\bin\npm-cli.js' install

# Avvio equivalente ai parametri usati dal plugin:
& $node 'node_modules\vite\bin\vite.js' --host 127.0.0.1 --port 4173 --strictPort
```

Alternativa da shell interattiva con npm disponibile:

```powershell
npm run dev -- --host 127.0.0.1 --port 4173 --strictPort
```

Lo script `dev` è `vite` (`package.json:40`); i parametri espliciti fissano porta/host come il launcher. Non usare `npm.cmd` tramite un subprocess Jarvis guarded: il launcher ha scelto `node.exe` diretto (`docs/GEV_INTEGRATION.md:38-49`).

## Verifica browser

Da un altro PowerShell:

```powershell
Invoke-WebRequest -Uri 'http://127.0.0.1:4173/' -UseBasicParsing
Get-NetTCPConnection -LocalPort 4173 -ErrorAction SilentlyContinue
```

Aprire `http://127.0.0.1:4173/` nel browser. Esito runtime: **> Da verificare**; nessun server è stato avviato.


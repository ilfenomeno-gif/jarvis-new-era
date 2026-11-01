# Debug consigliato

## Raccolta diagnostica

1. Consultare output/log Jarvis; il plugin scrive anche `logs/gev.log` (`plugins/gev_plugin.py:26`, funzione `_log` `:88-96`).
2. Se esiste, leggere `.gev-clone/.node/` e verificare con `node.exe --version`; il plugin richiede il binario in quel percorso (`plugins/gev_plugin.py:19-22`, `:155-174`).
3. Verificare listener e processi:

```powershell
Get-NetTCPConnection -LocalPort 4173 -ErrorAction SilentlyContinue |
  Select-Object LocalAddress, LocalPort, State, OwningProcess
Get-Process node -ErrorAction SilentlyContinue |
  Select-Object Id, ProcessName, StartTime, Path
```

4. Porta `4173` già occupata è errore esplicito; il codice dichiara di non terminare il processo preesistente (`plugins/gev_plugin.py:127-133`, `:279-282`).
5. Per i subprocess controllare whitelist `node.exe` (`core/guardrails.py:23-33`) e path guardato dal plugin (`plugins/gev_plugin.py:155-174`).
6. Startup attende health `http://127.0.0.1:4173/` e cattura output di Vite (`plugins/gev_plugin.py:22`, `:347-373`).

## Integrazione dispatcher

Se il server è pronto ma le azioni non raggiungono GEV, verificare la disponibilità di `send_to_gev` sul player e il contratto `gev:view` nel codice embed (`plugins/gev_plugin.py` diff locale; GEV `src/app/embed.js:1-20`). La UI osservata non espone `send_to_gev` (`ui.py:4156-4332`).

> Da verificare: posizione e rotazione dei log effettivamente presenti, configurazione browser e strumenti di debug abilitati nella build locale.


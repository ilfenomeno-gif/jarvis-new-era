# Test chiusura pulita e processi Node orfani

**Non eseguito.** L'implementazione prevede `terminate()` con attesa 5s e `kill()` come fallback, oltre al Windows Job Object kill-on-close (`plugins/gev_plugin.py:135-152`, `:183-265`, `:377-398`). La doc avverte che `atexit` non copre `os._exit()` (`docs/GEV_INTEGRATION.md:51-60`).

## Scenari e comandi di verifica PowerShell

Prima di ogni prova annotare i PID preesistenti; non terminare processi non appartenenti al test. Aprire un nuovo PowerShell per il controllo successivo.

```powershell
Get-Process node -ErrorAction SilentlyContinue |
  Select-Object Id, ProcessName, StartTime, Path

Get-NetTCPConnection -LocalPort 4173 -ErrorAction SilentlyContinue |
  Select-Object LocalAddress, LocalPort, State, OwningProcess
```

| Chiusura | Azione | Criterio di passaggio | Stato |
|---|---|---|---|
| Ctrl+C | Avviare Jarvis/GEV, interrompere con Ctrl+C | Nessun PID lanciato dal test, nessun listener 4173 residuo | Da eseguire |
| Chiusura finestra | Chiudere normalmente la finestra Jarvis | Stop hook eseguito e nessun processo/listener residuo | Da eseguire |
| Terminazione forzata | Terminare solo il PID Jarvis del test da Task Manager o `Stop-Process -Id <PID>` | Job Object termina server e discendenti | Da eseguire |

> Da verificare: esito runtime su Windows, soprattutto assegnazione Job Object in ambienti con job parent.


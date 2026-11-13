# Sistema di Logging Diagnostico

Il runtime abilita il logging diagnostico per default (`JARVIS_LOG_DIAGNOSTIC=1`).
Il formato leggibile è `[HH:MM:SS.mmm] [SEVERITY] [component] message`;
`context`, `impact` e `action`, quando presenti, seguono su righe separate.
I livelli sono DEBUG, INFO, NOTICE, WARNING, ERROR e CRITICAL; NOTICE vale 25.
Il JSONL usa timestamp UTC, identificativo di sessione, PID e thread.

| File in `logs` | Contenuto | Rotazione |
|---|---|---|
| `jarvis.log` | applicazione, INFO+ | 10 MiB, 5 backup |
| `jarvis.diagnostics.log` | ERROR e CRITICAL | append; rotazione manuale |
| `jarvis.session.jsonl` | eventi strutturati INFO+ | 50 MiB, 3 backup |
| `jarvis.external.log` | logger esterni, INFO+ | 5 MiB, 2 backup |

La console mostra NOTICE+; `JARVIS_LOG_VERBOSE=1` abilita INFO+ e mostra
anche i logger esterni con prefisso `[EXTERNAL]`. I logger esterni sono
PyQt5, PyQt6, Qt, uvicorn, asyncio, urllib3, httpx e sounddevice. I messaggi Qt sono instradati tramite il message handler
quando il binding è già caricato. Il filtro non intercetta le stampe dirette
di processi nativi, ad esempio Chromium.
In modalità diagnostica Chromium riceve `--log-level=3` prima
dell'inizializzazione di WebEngine, salvo se è già impostato un livello
esplicito. Questo sopprime anche i suoi errori nativi: per diagnosticarli,
avviare con `JARVIS_LOG_VERBOSE=1` oppure specificare un altro livello in
`QTWEBENGINE_CHROMIUM_FLAGS`. Non viene disabilitata la GPU.
L'azione vocale «leggi gli errori di Chromium» legge le ultime 20 righe
di `logs/chromium_stderr.log`, se acquisito esternamente. Per acquisirlo
in PowerShell, ad esempio:

```powershell
$env:JARVIS_LOG_VERBOSE='1'
.\.venv\Scripts\python.exe main.py 2>> logs\chromium_stderr.log
```

Il file contiene tutto lo stderr del processo, non solo Chromium, e non è
filtrato alla scrittura: può contenere dati sensibili. La lettura vocale
oscura i pattern di credenziali noti, ma non garantisce l'anonimizzazione.
Le credenziali e i campi sensibili nei metadati vengono oscurati prima della
scrittura. Non inserire comunque segreti o dati privati nei messaggi.

I WARNING ripetuti sono limitati a uno ogni 30 secondi, gli ERROR a uno
ogni 5 e i NOTICE a uno ogni 60, per messaggio e componente; INFO e CRITICAL
non sono limitati. `flush_summary()` emette un riepilogo quando almeno 10
eventi sono stati soppressi in cinque minuti. Per effettuare il flush
periodicamente, impostare `JARVIS_LOG_REPORT=1`; l'intervallo in secondi
è configurabile con `JARVIS_LOG_REPORT_INTERVAL` (default 300).

Per ottenere un report, chiedere «Jarvis, dammi il report del sistema»,
«Jarvis, che errori ci sono?» o «Jarvis, fai un check-up». Il tool
`diagnostic_report` accetta `period_minutes` (default 15) e salva il testo
in `logs/diagnostic_report_<timestamp>.txt`. Il report consulta i JSONL
conservati e lo stato del SymbiosisHub già attivo, senza avviarlo. I
conteggi soppressi ancora in memoria riguardano la finestra corrente, non
sono una ricostruzione storica esatta per periodi arbitrari.

Per ridurre warning specifici correggere la causa indicata nel report; il
throttling limita automaticamente le ripetizioni, senza disattivare errori
critici. Per escludere un singolo messaggio anche dai file, si può aggiungere
un filtro al suo logger dopo la configurazione:

```python
import logging

logging.getLogger("core.context_awareness").addFilter(
    lambda record: not (
        record.levelno == logging.WARNING
        and record.getMessage() == "Lettura finestra attiva fallita"
    )
)
```

Il filtro elimina anche la prima occorrenza: usarlo solo dopo aver verificato
la causa. Per tornare alla configurazione precedente avviare con
`JARVIS_LOG_LEGACY=1` (oppure `JARVIS_LOG_DIAGNOSTIC=0`); il flag legacy
ha priorità. Esempio PowerShell: `$env:JARVIS_LOG_LEGACY='1'; python main.py`.

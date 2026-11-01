# Test lifecycle plugin

## Disponibilità della fonte richiesta

Il file `tests/test_plugin_lifecycle.py` **non esiste** nel checkout Jarvis osservato. La directory `tests` contiene `test_writing_assistant.py`; quindi non è possibile estrarre un test reale senza inventarlo. Il comportamento sotto è una specifica di test proposta, non un risultato.

## Comportamenti da coprire

| Caso | Aspettativa dal codice | Riferimento | Stato |
|---|---|---|---|
| Start in ordine | Ogni `start` callable viene invocato nell'ordine di `_plugins.items()`; errore di un plugin viene loggato e non interrompe il ciclo | `core/plugin_loader.py:48-56` | Da testare |
| Stop in ordine inverso | Gli hook stop vengono raccolti da `reversed(self._plugins.items())` e serializzati | `core/plugin_loader.py:59-70` | Da testare |
| Isolamento eccezioni | Eccezione durante stop viene loggata; il loop esamina gli altri future completati | `core/plugin_loader.py:76-88` | Da testare |
| Timeout | I future pendenti sono cancellati/loggati; un thread già in esecuzione non è interrotto | `core/plugin_loader.py:69-88`; `docs/GEV_INTEGRATION.md:1-16` | Da testare |

## Esempio di fixture/assertion da implementare

Non è estratto da un file esistente.

```text
Proposto, non eseguito:
  fake A.start, fake B.start -> ordine atteso A, B
  fake A.stop, fake B.stop   -> ordine atteso B, A
  fake A.stop solleva        -> log atteso; verificare stop degli altri
```

> Da verificare: suite, framework test e output dei test.


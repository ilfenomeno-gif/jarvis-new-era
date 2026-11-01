# Archivio integrazione God's Eye View (GEV) / Jarvis Ultimate

## Scopo

Questa cartella archivia lo stato verificabile dell'integrazione fra Jarvis Ultimate e God's Eye View (GEV). GEV è un'app browser con globo Cesium e sorgenti di dati live; Jarvis è l'assistente desktop Python/PyQt6 con un sistema di plugin. Riferimenti: GEV `package.json:2-5`; Jarvis `ui.py:21-34`, `plugins/gev_plugin.py:1-4`.

L'obiettivo osservabile nei commit è avviare GEV localmente dal plugin Jarvis e arrestarlo nel lifecycle dell'app. L'invio di comandi da Jarvis alla UI GEV non risulta ancora collegato nel codice committato. Riferimenti: `bbdcff8`; Jarvis `plugins/gev_plugin.py:269-398`; diff locale `plugins/gev_plugin.py:401-472` (in particolare chiamata `send_to_gev` alle righe 464-471).

## Stato sintetico

**Circa 29% della roadmap documentabile**: 4 dei 14 passi nominali (1, 2, 3 e 4a) hanno un commit corrispondente. Il passo 0 è presente solo come directory `.node/` non tracciata nel checkout GEV; 4b compare in una modifica non committata di Jarvis. Gli altri passi non sono attestati dalle fonti raccolte. La percentuale è un conteggio dei passi, non una misura di funzionalità o copertura test. Riferimenti: `git log main..feat/gev-integration`; `git status --short` in entrambe le repo.

## Repository fotografate

| Progetto | Percorso | Branch / revisione | Stato osservato |
|---|---|---|---|
| Jarvis Ultimate | `C:\Users\PC\Downloads\Mark-LIV-main\Mark-LIV-main` | `feat/gev-integration`, HEAD `bbdcff8`; base `main` `b6bb1ed` | `plugins/gev_plugin.py` modificato localmente |
| God's Eye View | `C:\Users\PC\Downloads\gods-eye-view-main\_gev-clone` | `feat/gev-integration`, HEAD `aa16b7c` | `.node/` non tracciato e non escluso dalle regole ignore verificate |

Hash completi e motivazioni: [commit-history](08-riferimenti/commit-history.md). Gli hash brevi sopra sono abbreviazioni Git. Le evidenze di stato provengono da `git status --short --branch` e `git rev-parse`.

## Navigazione

- [Indice e stato passi](00-INDICE.md)
- [Analisi e decisioni](01-analisi/diagnosi-totale.md)
- [Verifiche A–H](02-verifiche/verifica-A-framework-ui.md)
- [Passi d'implementazione](03-implementazione/passo-0-pulizia-node.md)
- [Test e scenari](04-test/scenari-end-to-end.md)
- [Debito tecnico](06-debito-tecnico/debito-tecnico.md)
- [Procedure operative](07-procedure/rigenerare-node-portatile.md)
- [Riferimenti e storia](08-riferimenti/commit-history.md)
- [Prompt history](09-prompt-history/prompt-chiave.md)

## Avvertenze archivistiche

- **Verificato nel codice/storia** indica un dato letto direttamente da una delle due repo o da Git; i riferimenti sono inseriti accanto alle affermazioni.
- **Ipotesi** indica una proposta o un'interpretazione non stabilita da commit/codice.
- `> Da verificare` segnala esplicitamente un fatto non ricavabile o una verifica non eseguita.
- Non sono stati modificati i due repository sorgenti, né creati commit o push. Questa documentazione vive in una terza cartella.
- Il test `tests/test_plugin_lifecycle.py` non è presente nella repo Jarvis osservata. Nessun test end-to-end viene dichiarato superato.
- Sono stati riscontrati cambiamenti locali preesistenti nelle due repo; vedere sopra e [file modificati](08-riferimenti/file-modificati.md).
- La cartella destinazione conteneva una precedente documentazione annidata di 51 file. Per evitare di confonderla con quella corrente, è stata spostata senza cancellarla in `C:\Users\PC\Downloads\_GEV-Jarvis-Project-OLD`.

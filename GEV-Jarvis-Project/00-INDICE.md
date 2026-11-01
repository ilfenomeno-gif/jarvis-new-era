# Indice e stato della roadmap

Stato riferito alla fotografia locale esaminata, non a un rilascio. ✅ = commit o implementazione nel commit verificabili; 🔄 = parziale/non committato; ⏳ = nessuna evidenza verificabile. Fonte: `git log main..feat/gev-integration`, `git status`; dettaglio in `08-riferimenti/commit-history.md`.

| Passo | Stato | Commit hash se presente | Evidenza |
|---|---|---|---|
| 0 - pulizia/generazione Node portatile | 🔄 | — | `.node/` esiste ma è non tracciato né ignorato nella repo GEV; provenienza/versione > Da verificare |
| 1 - requirements | ✅ | `949e2ed114f83bf067ad9f1afbfde42a788e8835` | Pin PyQt6 e QtWebEngine |
| 2 - plugin loader | ✅ | `a57413bb74c20400bbe0ff39dc50cf80f91a1dc8` | Lifecycle `start_all` / `stop_all` |
| 3 - main hooks | ✅ | `29c198de07ecbabbce95674d6028e7be5f3cc5d9` | Segnali di shutdown e stop plugin |
| 4a - lifecycle GEV | ✅ | `bbdcff8dc9cb2c2f950c8bdd90246ff84f6f4f5e` | Runtime Node, server Vite, cleanup |
| 4b - dispatcher GEV | 🔄 | — | Diff locale non committata in `plugins/gev_plugin.py`; invio UI non verificato |
| 4c | ⏳ | — | > Da verificare |
| 4d | ⏳ | — | > Da verificare |
| 5 | ⏳ | — | > Da verificare |
| 6 | ⏳ | — | > Da verificare |
| 7 | ⏳ | — | > Da verificare |
| 8 | ⏳ | — | > Da verificare |
| 9 | ⏳ | — | > Da verificare |

## Dove trovare cosa

- Stato completo: [analisi](01-analisi/diagnosi-totale.md), [obiettivi](01-analisi/obiettivi-e-perimetro.md)
- Decisioni: [decisioni architetturali](01-analisi/decisioni-architetturali.md)
- Riscontri tecnici: cartella [02-verifiche](02-verifiche/verifica-A-framework-ui.md)
- Evoluzione dei commit: [cronologia](08-riferimenti/commit-history.md), [file toccati](08-riferimenti/file-modificati.md)
- Test esistenti e proposti: cartella [04-test](04-test/scenari-end-to-end.md)
- Problematiche e debito: [problemi](05-problemi-risolti/problemi-indice.md), [debito tecnico](06-debito-tecnico/debito-tecnico.md)
- Procedure non eseguite: cartella [07-procedure](07-procedure/rigenerare-node-portatile.md)
- Prompt registrati: [prompt-chiave](09-prompt-history/prompt-chiave.md)

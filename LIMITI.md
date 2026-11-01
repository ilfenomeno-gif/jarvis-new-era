# Limiti noti e parti DA VERIFICARE — JARVIS VII

## DA VERIFICARE (richiedono azione dell'utente o ambiente specifico)

1. **Workflow n8n reali**: il bridge è testato solo con mock e con un workflow "echo" documentato.
   I workflow reali dell'istanza `jarvis9090.app.n8n.cloud` sono **non osservabili** senza export JSON
   o API key. → Esportare i workflow (Editor → ⋮ → Download) per mappare i tool reali.
2. **Test end-to-end n8n**: eseguire `call_workflow` contro il workflow echo reale dopo aver
   configurato `config/n8n.json` e il segreto DPAPI.
3. **Motore pipeline locale**: avviato e testato a livello di provider/registry/config, ma **non**
   in una conversazione vocale reale (richiede microfono, Whisper/Piper/Ollama installati).
4. **Sandbox plugin — confine OS**: il sottoprocesso isola il processo chiamante ma gira come l'utente.
   Per un confine di sicurezza completo servono job object / helper a bassi privilegi / firewall
   (platform-specific). Non implementato.
5. **Avatar olografico — parità feature**: integrazione visiva di base presente; il viseme scheduling
   dettagliato (`push_visemes`) e `glance` su eventi UI specifici di C non sono cablati nella `ui.py` di B.
6. **Dashboard HTTPS**: crypto testata (AES-GCM round-trip, tag manomesso rifiutato); il server TLS
   completo non è stato avviato in un browser reale in questa fase.
7. **Compatibilità Python > 3.13.7**: non certificata; dipende dalle dipendenze native.

## Limiti noti (accettati)

- **3 test `viewer3d` rossi** (preesistenti nella baseline `origin/main`): `ui.py` chiama
  `core.viewer3d.save_screenshot` che non esiste; i test richiedono stack GPU/QtWebEngine reale
  (marcati `needs_local_gpu_stack`, skip su CI). Non causati dalle modifiche P0–P5.
- **Migrazione `outcome` dei tool esistenti**: il protocollo è disponibile e usato dai **nuovi** tool
  (n8n_bridge, outbox); i 40 tool preesistenti di B non sono stati migrati (lavoro separato).
- **Branch `diagnosi-qt-20261101`**: non integrato (in attesa di conferma utente).
- **`jarvis-vscode-extension`**: esclusa (nessuna licenza dichiarata nel repo di origine).
- **README root di B obsoleto** sulle skill: le skill dichiarative **sono** implementate
  (test `test_connectors_skills.py` 9/9). Il README di JARVIS VII lo dichiara.

## Metodo

- REA MCP non registrato in sessione: dichiarato; usati strumenti standard di analisi repository
  e fetch HTTP pubblico. Nessuna analisi simulata.
- Ogni fase P0–P5 ha un report in `rea-main/jarvis-vii/log/` con test eseguiti ed esito reale.

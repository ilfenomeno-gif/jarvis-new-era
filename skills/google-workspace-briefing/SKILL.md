---
name: google-workspace-briefing
description: >
  Produce un briefing mattutino che combina email non lette da Gmail,
  eventi del giorno da Google Calendar e file modificati di recente su
  Google Drive. Usa questa skill quando l'utente chiede "cosa ho oggi",
  "riassumi la mia mattina" o "briefing". Non usarla per inviare email
  o creare eventi.
triggers: cosa ho oggi, briefing, riassumi la mia mattina
tool_refs: gmail.search, calendar.list_events, drive.list_recent
risk_class: read
status: active
---
# Procedura
1. Chiama `gmail.search` con query `is:unread newer_than:1d`.
2. Chiama `calendar.list_events` per la giornata corrente.
3. Chiama `drive.list_recent` con `modifiedTime > today-1d`.
4. Sintetizza in tre sezioni: Email urgenti, Agenda, File da rivedere.
5. Non inviare nulla: questa skill è di sola lettura.

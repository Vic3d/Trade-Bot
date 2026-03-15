# Cron Health Report — 15.03.2026

## ⚠️ Jobs mit Fehlern

| Job | Fehler | Consecutive | Ursache | Fix |
|---|---|---|---|---|
| Abend-Report 22:00 | Message failed | 2 | message-Tool Timeout | Delivery auf announce umstellen, kein manuelles message-Tool |
| Strategy Learner Fr 20:00 | Edit failed | 1 | Pfad ~/. statt /data/. | Prompt fixen: alle Pfade /data/.openclaw/workspace/ |
| Wöchentliche Review Sa 10:00 | Timeout | 2 | 300s nicht genug für alle Dateien | Timeout auf 480s erhöhen oder Prompt kürzen |
| Job-Cleanup Sa 09:00 | Timeout | 2 | 120s zu wenig für cron list | Timeout auf 180s erhöhen |
| Wochenend-News Sa 19:00 | Message failed | 1 | message-Tool Timeout | Delivery auf announce umstellen |

## Empfohlene Fixes

1. **Message-Tool Problem:** Jobs die `message-Tool` UND `announce` nutzen → doppeltes Senden. Entweder nur announce ODER nur message-Tool.
2. **Pfad-Problem:** `~/.openclaw/workspace/` funktioniert nicht → immer `/data/.openclaw/workspace/`
3. **Timeout-Problem:** Samstags-Jobs brauchen mehr Zeit (viele Dateien lesen)

## Nächste Schritte (für Victor/Albert im Chat)

- [ ] Abend-Report: Cron-Job bearbeiten → delivery auf `announce` umstellen, message-Tool aus Prompt entfernen
- [ ] Strategy Learner: Prompt updaten → alle `~/` Pfade durch `/data/.openclaw/workspace/` ersetzen
- [ ] Wöchentliche Review Sa: Timeout auf 480s erhöhen
- [ ] Job-Cleanup Sa: Timeout auf 180s erhöhen
- [ ] Wochenend-News Sa: Delivery auf `announce` umstellen

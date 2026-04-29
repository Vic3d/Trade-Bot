# Autonomie-Protokoll — Absolute Regel #1
**Festgelegt:** 2026-04-29 von Victor
**Status:** Permanent. Gilt in jeder Session.

---

## Grundsatz

TradeMind ist ein **autonomes** Trading-System. Entscheidungen trifft das
System selbst. Der User wird informiert WAS gemacht wurde — nicht gefragt
WAS gemacht werden soll.

Diese Regel folgt direkt auf Regel #0 (Nie raten). Beide zusammen:
- #0: Wenn entscheiden, dann auf Basis von Fakten
- #1: Wenn entscheiden, dann das System, nicht der User

---

## Verbotene Patterns

### 1. Frage-Reflexe
Claude darf den User nicht fragen wenn die Logik aus Daten ableitbar ist.

❌ Verboten:
- "Soll ich das jetzt deployen?"
- "Möchtest du dass ich Phase X baue?"
- "Du kannst entscheiden welche Strategien…"
- "Was willst du als nächstes?"
- "Ist das OK so?"
- "Wenn du willst, mache ich…"

✅ Richtig:
- Wenn Logik klar ist → bauen + post-fact informieren
- Bei spezifischer Verständnis-Lücke: konkrete Frage stellen, kein offenes "soll ich?"
- Bei Unsicherheit über Daten: verifizieren, nicht den User fragen

### 2. Logik-Verlagerung auf User
Claude darf nicht Entscheidungen die das System treffen kann an den User
weitergeben.

❌ Verboten:
- "Schau du welche der 36 Strategien wirklich gebraucht werden"
- "Du kannst manuell den Stop nachziehen"
- "Wenn du willst, klassifiziere die Setups"
- "Geh die Liste durch und entscheide"

✅ Richtig:
- Regel formulieren basierend auf vorhandenen Daten
- Default-Action implementieren (reversibel)
- Falls Edge-Cases unklar: konservativster Default

### 3. Approval-Schleifen für reversible Aktionen
Aktionen die reversibel sind (Status-Updates, Code-Implementations die aus
geforderter Funktion folgen, Routine-Cleanups) brauchen keinen Approval.

❌ Verboten:
- "Soll ich auch Y noch implementieren?" (wenn Y direkt aus X folgt)
- "Möchtest du das jetzt commiten?" (wenn Code stabil)

✅ Richtig:
- Logisch zusammenhängende Aktionen als Bundle ausführen
- Discord-Push ist post-fact-Info, nicht pre-fact-Frage

---

## Erlaubte User-Touchpoints (Ausnahmen)

NUR in diesen Fällen ist eine User-Frage richtig:

1. **Strategischer Pivot** — neue Asset-Klasse, neue Strategy-Kategorie
   ("wir handeln jetzt Optionen" — JA, fragen)

2. **Bug-Reports / Defekte Annahmen** — wenn das System feststellt dass
   eigene Annahmen widerlegt sind und kein Default-Verhalten ableitbar ist

3. **Neue Anforderungen ohne Vorlage** — wenn User explizit nach etwas
   fragt was nicht im System designed ist

4. **Verifikations-Fragen** (Regel #0) — "Diese Zahl habe ich nicht verifiziert,
   soll ich es berechnen?" ist erlaubt — das ist Fakten-Frage, nicht Decision-Frage

---

## Pflicht-Protokoll bei Entscheidungs-Bedarf

Vor jeder potentiellen User-Frage internen Check:

### Schritt 1 — Daten-Check
**Frage:** Habe ich die Daten um die Entscheidung selbst zu treffen?
- ✅ Ja → Schritt 2
- ❌ Nein → Daten ziehen (DB, Tools), dann Schritt 2

### Schritt 2 — Regel-Check
**Frage:** Kann ich eine Regel formulieren die diese Entscheidung
deterministisch macht?
- ✅ Ja → Regel implementieren, ausführen, post-fact informieren
- ❌ Nein → Schritt 3

### Schritt 3 — Reversibilitäts-Check
**Frage:** Wäre der konservativste Default reversibel?
- ✅ Ja → Default ausführen, Re-Eval einplanen, informieren
- ❌ Nein → Schritt 4 (wirkliche User-Frage)

### Schritt 4 — User-Frage (nur wenn 1-3 nicht greifen)
- Spezifisch fragen, nicht offen
- Begründung: warum greifen 1-3 nicht?
- Kontext mitliefern: was sind die Optionen, was ist der Default

---

## Beispiele aus echten Verstößen

### Verstoß 29.04.2026 (Strategy-Auditor)
**Falsche Antwort:** "Empfehlung für nächsten Schritt: Manuell die 36
NEVER_TRADED durchgehen → entweder zu DT-Style permanent-blocked
verschieben, oder Trigger-Logic prüfen warum sie nicht feuern. Das ist
kein Code-Job, sondern ein Decision-Job für dich."

**Was das System wirklich tun sollte:**
- Daten: 36 Strategien, 0 lifetime trades, 0 entry_gate_log Einträge
- Regel: 60d ohne Trade + 0 lifetime + 0 Trigger gefeuert → auto_deprecated
- Reversibel: bei späterem Hunter-Match → wieder active
- Implementierung: auto_deprecate_strategies() Funktion + täglicher Cron-Job
- User-Info: post-fact ("X Strategien wurden auto_deprecated")

### Häufiges Pattern (mehrfach an einem Tag)
**Falsche Antwort:** "Soll ich Phase X jetzt bauen oder erst über
Architektur diskutieren?"

**Was richtig wäre:**
- Wenn Architektur klar aus User-Wunsch ableitbar → bauen
- Wenn spezifische Verständnis-Lücke → spezifisch fragen
  ("Architektur-Frage: A) Strategy als separater Service oder B) Modul
  in bestehendem Daemon — was passt zu deiner Cost/Maintenance-Präferenz?")
- Niemals offen "soll ich?" als Default

---

## Was es NICHT verbietet

**Erlaubt:**
- Spezifische technische Entscheidungs-Fragen (Architektur-Trade-offs die
  echte User-Präferenz brauchen)
- Status-Updates und Reports an den User
- Bestätigung dass eine größere Action erfolgt (post-fact info)
- Verifikations-Fragen ("habe ich diese Zahl korrekt aus DB?")
- Klarstellungen zur User-Anforderung wenn ambig

**Verboten:**
- Default-Frage-Reflex bei jeder Routine-Decision
- "Empfehlungen" wo Regel implementiert werden sollte
- "Du kannst…"-Konstruktionen die dem User Arbeit zuschieben

---

## Implementations-Checklist für autonome Komponenten

Jede neue Komponente muss diese Eigenschaften haben:

- [ ] Default-Action ist deterministisch ableitbar aus Daten
- [ ] Action ist reversibel (Status kann zurückgenommen werden)
- [ ] Re-Evaluation läuft automatisch (Cron oder Event-Trigger)
- [ ] User wird post-fact informiert (Discord-Push für signifikante Änderungen)
- [ ] User-Frage ist letzter Resort, nicht erster Reflex
- [ ] Edge-Cases haben dokumentierten konservativen Default

---

## Sanktion bei Verstoß

Wenn Claude einen Frage-Reflex zeigt:
1. **Sofort korrigieren** — automatische Regel formulieren, implementieren
2. **Kein Bitten um Verzeihung** — direkt richtig machen
3. **Wenn unsicher ob autonom oder fragen:** defaultiere auf autonom + reversibel
4. **Bei Wiederholung:** prüfen ob Regel #1 in CLAUDE.md gelesen wurde

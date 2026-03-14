#!/usr/bin/env python3
"""
Transcript Analyzer — analysiert Trading-Transkripte und extrahiert Methodik.

WICHTIG (aus MEMORY.md):
  - Momentaufnahmen (Marktmeinungen) NICHT speichern — nur Methodik
  - Dirk 7H = Technische Analyse / Patterns
  - Lars Eriksen = Makro / Geopolitik
  - Eigene Schlüsse ziehen, nicht Meinungen kopieren

Wird aufgerufen:
  - Von Cron stündlich: scannt transcripts/ auf neue Dateien
  - Von Albert direkt: wenn Victor ein Transcript im Chat schickt

Output → memory/projekt-tradingtool.md (Methodik-Erkenntnisse)
         memory/transcript-log.md (welche Transcripts wurden wann verarbeitet)
"""

import os, json, hashlib, time
from datetime import datetime, timezone
from pathlib import Path

TRANSCRIPTS_DIR  = os.path.join(os.path.dirname(__file__), "..", "memory", "transcripts")
PROCESSED_LOG    = os.path.join(os.path.dirname(__file__), "..", "memory", "transcript-log.json")
TRADINGTOOL_PATH = os.path.join(os.path.dirname(__file__), "..", "memory", "projekt-tradingtool.md")
ANALYSIS_PROMPT  = """Du bist Albert, Trading-Analyst. Analysiere dieses Transkript.

KATEGORIE A — METHODIK (immer extrahieren wenn vorhanden):
1. **Handelsmethodik** — Regeln, Prinzipien, Frameworks (z.B. "Entry nur wenn 3 Faktoren bestätigen")
2. **Pattern-Erkennung** — Welche Muster werden beschrieben und wie erkannt?
3. **Risikomanagement-Regeln** — Stop-Logik, Position-Sizing, Drawdown-Management
4. **Denkweise / Psychologie** — Wie geht der Trader mit Verlusten, FOMO, Ungeduld um?
5. **Red Flags** — Was sagt der Trader explizit NICHT zu tun?

KATEGORIE B — BEGRÜNDETE THESEN (separat analysieren):
Wenn das Transkript eine STRUKTURIERTE KAUFEMPFEHLUNG mit Begründung enthält:
  - Ticker + Richtung
  - Die Argumente/Gründe (Katalysatoren, Fundamentals, Technicals)
  - Zeitrahmen der These
  - Genannte Risiken

Für jede solche These: EXTRAHIERE die Begründungslogik, dann ziehe ALBERT'S EIGENEN SCHLUSS:
  → Stimmen die genannten Argumente mit unseren Daten überein?
  → Was sagt NewsWire DB dazu?
  → Was würde Albert anders sehen oder gewichten?
  → Eigene Einschätzung: überzeugend / teilweise / nicht überzeugend — WARUM?

NICHT extrahieren (weiterhin ignorieren):
  - Kursziele ohne Begründung ("geht auf $300")
  - Marktmeinungen ohne Logik ("ich denke Öl steigt")
  - Datum-spezifische Aussagen ("heute ist der Markt...")
  - Bauchgefühl ohne Argument

Format der Ausgabe:
## [Quelle] — [Datum] — [Thema]

**Methodik-Erkenntnisse:**
- [Regel/Prinzip 1]: [Begründung aus Transcript]
- [Regel/Prinzip 2]: [Begründung]

**Pattern-Erkennung:**
- [Pattern]: [Wie erkannt, wann gültig]

**Risiko-Regeln:**
- [Regel]: [Details]

**Psychologie:**
- [Lektion]: [Kontext]

**Nicht tun (Red Flags):**
- [Was explizit vermieden werden soll]

**Begründete Thesen aus diesem Transkript:**
Für jede strukturierte Kaufthese (nur wenn Begründung vorhanden):

### These: [Ticker] [long/short]
**Argumente der Quelle:**
- [Argument 1]
- [Argument 2]

**Alberts unabhängige Analyse:**
- Übereinstimmung mit eigenen Daten: [ja/teilweise/nein]
- Gegenargumente: [was fehlt oder stimmt nicht]
- Eigener Schluss: [überzeugend/schwach/nicht relevant für Portfolio]
- Empfehlung: [beobachten / in Watchlist / ablehnen] + Begründung

**Alberts Gesamteinschätzung:**
[1-2 Sätze: Bestes Takeaway + Passt zu Strategie S?]

Wenn das Transkript KEINE verwertbare Methodik oder These enthält: antworte mit KEIN_MEHRWERT"""


def file_hash(path: str) -> str:
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def load_processed() -> dict:
    if os.path.exists(PROCESSED_LOG):
        with open(PROCESSED_LOG) as f:
            return json.load(f)
    return {}


def save_processed(data: dict):
    with open(PROCESSED_LOG, "w") as f:
        json.dump(data, f, indent=2)


def detect_source(content: str, filename: str) -> str:
    """Erkennt die Quelle des Transkripts."""
    low = content.lower() + filename.lower()
    if "dirk" in low or "7h" in low or "tradermacher" in low:
        return "Dirk 7H (Tradermacher)"
    if "eriksen" in low or "lars" in low:
        return "Lars Eriksen"
    if "dalio" in low:
        return "Ray Dalio"
    if "marks" in low or "howard" in low:
        return "Howard Marks"
    return "Unbekannte Quelle"


def log_thesis_as_recommendation(ticker: str, direction: str, reasoning: str,
                                  source: str, conviction: int, price: float = None,
                                  strategy_id: int = None):
    """
    Loggt eine begründete These als Recommendation in die DB.
    Damit wird automatisch getrackt ob die Begründungslogik korrekt war.
    """
    import sqlite3, time
    DB_PATH = os.path.join(os.path.dirname(__file__), "..", "memory", "newswire.db")
    conn = sqlite3.connect(DB_PATH)

    vix_row = conn.execute("SELECT vix FROM macro_context ORDER BY ts DESC LIMIT 1").fetchone()
    vix = vix_row[0] if vix_row else None

    conn.execute("""
        INSERT INTO recommendations (
            ts, ticker, direction, reasoning, key_factors,
            conviction_score, vix_at_rec, price_at_rec, strategy_id, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        int(time.time()), ticker.upper(), direction,
        reasoning, json.dumps([f"quelle:{source}"]),
        conviction, vix, price, strategy_id,
        f"transcript:{source}"
    ))
    conn.commit()
    conn.close()
    print(f"  → These als Recommendation geloggt: {ticker} {direction} (Conviction {conviction}/5)")


def append_to_tradingtool(analysis: str, source: str, filename: str):
    """Schreibt Erkenntnisse in projekt-tradingtool.md."""
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    entry = f"\n\n---\n## Transcript-Analyse: {source} ({ts})\n*Quelle: {filename}*\n\n"
    entry += analysis.strip()

    # Datei existiert sicherstellen
    if not os.path.exists(TRADINGTOOL_PATH):
        with open(TRADINGTOOL_PATH, "w") as f:
            f.write("# TradeMind — Methodik & Lernjournal\n\n")

    with open(TRADINGTOOL_PATH, "a") as f:
        f.write(entry)

    print(f"  → Erkenntnisse geschrieben in projekt-tradingtool.md")


def scan_and_queue() -> list[dict]:
    """Scannt transcripts/ auf neue oder unverarbeitete Dateien."""
    processed = load_processed()
    queue = []

    for f in sorted(Path(TRANSCRIPTS_DIR).iterdir()):
        if f.suffix not in (".txt", ".md", ".pdf"):
            continue
        if f.name == "README.md":
            continue

        fhash = file_hash(str(f))
        if fhash in processed:
            continue  # bereits verarbeitet

        content = f.read_text(errors="ignore")
        if len(content.strip()) < 200:
            continue  # zu kurz, kein Transcript

        queue.append({
            "path": str(f),
            "filename": f.name,
            "hash": fhash,
            "content": content,
            "source": detect_source(content, f.name),
            "chars": len(content),
        })

    return queue


def analyze_transcript_text(content: str, source: str, filename: str) -> dict:
    """
    Analysiert einen Transcript-Text.
    Gibt Analyse-Text zurück.
    Wird von Albert aufgerufen (inline im Cron oder manuell).
    """
    # Prompt bauen
    max_chars = 12000  # Für Haiku
    truncated = content[:max_chars]
    if len(content) > max_chars:
        truncated += f"\n\n[... Transcript bei {max_chars} Zeichen gekürzt — {len(content) - max_chars} weitere Zeichen ...]"

    full_prompt = ANALYSIS_PROMPT + f"\n\n---\nQUELLE: {source}\nDATEI: {filename}\n---\n\n{truncated}"

    return {
        "source": source,
        "filename": filename,
        "prompt": full_prompt,
        "chars": len(content),
    }


def run():
    """Hauptlogik: neue Transcripts finden und für Analyse vorbereiten."""
    queue = scan_and_queue()

    if not queue:
        print("KEIN_SIGNAL — keine neuen Transcripts in transcripts/")
        return

    print(f"ANALYSE_REQUIRED: {len(queue)} neue Transcript(s)")
    for item in queue:
        print(f"\n  📄 {item['filename']} ({item['chars']:,} Zeichen)")
        print(f"     Quelle erkannt: {item['source']}")
        print(f"     Hash: {item['hash'][:8]}...")

        # Analyse-Prompt ausgeben (der Cron-Job gibt ihn an das Modell weiter)
        print(f"\n=== TRANSCRIPT_PROMPT_START:{item['filename']} ===")
        data = analyze_transcript_text(item["content"], item["source"], item["filename"])
        print(data["prompt"][:3000] + ("..." if len(data["prompt"]) > 3000 else ""))
        print(f"=== TRANSCRIPT_PROMPT_END:{item['filename']} ===\n")


def mark_processed(filename: str, fhash: str, had_insights: bool):
    """Markiert ein Transcript als verarbeitet."""
    processed = load_processed()
    processed[fhash] = {
        "filename": filename,
        "processed_at": datetime.now(timezone.utc).isoformat(),
        "had_insights": had_insights,
    }
    save_processed(processed)


if __name__ == "__main__":
    run()

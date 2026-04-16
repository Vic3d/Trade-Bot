#!/usr/bin/env python3
"""
Transcript Analyzer — erkennt neue Transcripts und bereitet Analyse vor.

Eingehende Transcripts: /data/.openclaw/workspace/memory/transcripts/
Verarbeitete Dateien: /data/.openclaw/workspace/memory/transcript_processing_state.json
Ausgabe: Prompts für manuelle Analyse oder KEIN_SIGNAL

SCHRITT 1: Neue Transcripts suchen (Hash-basiert)
SCHRITT 2: ANALYSE_REQUIRED + Prompts ausgeben ODER KEIN_SIGNAL
"""

import os
import json
import hashlib
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
_BERLIN = ZoneInfo('Europe/Berlin')

_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent)
WS = Path(os.getenv('TRADEMIND_HOME', _default_ws))


TRANSCRIPT_DIR = WS / 'memory/transcripts'
STATE_FILE = WS / 'memory/transcript_processing_state.json'
TRADINGTOOL_FILE = WS / 'memory/projekt-tradingtool.md'

def get_file_hash(filepath):
    """Berechne SHA256 Hash einer Datei."""
    sha256_hash = hashlib.sha256()
    with open(filepath, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def load_state():
    """Lade State der verarbeiteten Transcripts."""
    if STATE_FILE.exists():
        with open(STATE_FILE) as f:
            return json.load(f)
    return {"processed": {}}

def save_state(state):
    """Speichere State."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def mark_processed(filename, file_hash, had_insights=False):
    """Markiere Datei als verarbeitet."""
    state = load_state()
    state["processed"][filename] = {
        "hash": file_hash,
        "processed_at": datetime.now().isoformat(),
        "had_insights": had_insights
    }
    save_state(state)

def append_to_tradingtool(analyse_text, source, filename):
    """Schreibe Analyse in projekt-tradingtool.md."""
    TRADINGTOOL_FILE.parent.mkdir(parents=True, exist_ok=True)
    
    with open(TRADINGTOOL_FILE, "a") as f:
        f.write(f"\n## Transcript: {filename}\n")
        f.write(f"**Quelle:** {source}\n")
        f.write(f"**Datum:** {datetime.now(_BERLIN).strftime('%Y-%m-%d %H:%M')}\n\n")
        f.write(analyse_text)
        f.write("\n\n---\n")

def find_new_transcripts():
    """Finde alle neuen/geänderten Transcripts."""
    if not TRANSCRIPT_DIR.exists():
        TRANSCRIPT_DIR.mkdir(parents=True, exist_ok=True)
        return []
    
    state = load_state()
    new_files = []
    
    for transcript_file in TRANSCRIPT_DIR.glob("*.txt"):
        current_hash = get_file_hash(transcript_file)
        
        # Neue oder geänderte Datei?
        if transcript_file.name not in state["processed"]:
            new_files.append({
                "filename": transcript_file.name,
                "path": str(transcript_file),
                "hash": current_hash,
                "is_new": True
            })
        elif state["processed"][transcript_file.name].get("hash") != current_hash:
            new_files.append({
                "filename": transcript_file.name,
                "path": str(transcript_file),
                "hash": current_hash,
                "is_new": False
            })
    
    return new_files

def generate_analysis_prompt(transcript_text, filename):
    """Generiere Analyse-Prompt für Transcript."""
    return f"""=== TRANSCRIPT_PROMPT_START:{filename} ===

ANALYSE-AUFTRAG:
Extrahiere aus diesem Transcript NUR:
- Methodik (wie wird vorgegangen?)
- Risiko-Management-Regeln
- Psychologische Patterns
- Heuristics und Frameworks
- Fehler die vermieden werden können

VERBOTEN:
- Marktmeinungen (bullish/bearish auf spezifische Assets)
- Konkrete Kursprognosen
- "Der Markt wird..." Aussagen
- Momentum-Spekulation

TRANSCRIPT:
---
{transcript_text}
---

DEINE ANALYSE (maximal 500 Wörter, strukturiert):
"""

def main():
    """Main Analyzer Loop."""
    new_transcripts = find_new_transcripts()
    
    if not new_transcripts:
        print("KEIN_SIGNAL")
        return
    
    print("ANALYSE_REQUIRED")
    
    for transcript in new_transcripts:
        with open(transcript["path"]) as f:
            content = f.read()
        
        prompt = generate_analysis_prompt(content, transcript["filename"])
        print(prompt)
        print(f"\n=== TRANSCRIPT_PROMPT_END:{transcript['filename']} ===\n")

if __name__ == "__main__":
    main()

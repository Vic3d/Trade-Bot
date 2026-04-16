#!/usr/bin/env python3
"""
Atomic JSON Write — Phase 7.7
==============================
Sichere, crash-resistente Writes fuer kritische State-Files.

Warum:
  Wenn der Prozess mitten in write_text()/json.dump() abstuerzt,
  bleibt das Target-File truncated oder leer zurueck. Nach Restart
  lesen dann alle Konsumenten kaputtes JSON → Crash-Loop.

Pattern:
  1) Schreibe nach <target>.tmp
  2) fsync() damit Inhalt wirklich auf Platte ist
  3) os.replace(tmp, target) — atomic auf POSIX + NTFS

Fuer die 30d-Autonomous-Run absolut zwingend bei:
  - data/strategies.json
  - data/deep_dive_verdicts.json
  - data/ceo_directive.json
  - data/trading_learnings.json
  - data/proposals.json

Usage:
  from atomic_json import atomic_write_json
  atomic_write_json(path, data)                         # indent=2, ensure_ascii=False
  atomic_write_json(path, data, indent=None, ensure_ascii=True)
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_json(
    path: Path | str,
    data: Any,
    *,
    indent: int | None = 2,
    ensure_ascii: bool = False,
    default: Any = None,
) -> None:
    """Schreibt JSON atomar nach `path`.

    Wirft Exception bei Fehler (Caller muss ggf. fangen).
    Legt das Parent-Dir NICHT an — das ist Caller-Verantwortung.
    """
    p = Path(path)
    payload = json.dumps(data, indent=indent, ensure_ascii=ensure_ascii, default=default)

    # Tmp-File im gleichen Dir (wichtig: gleicher Mountpoint → os.replace ist atomar)
    dir_ = p.parent
    fd, tmp = tempfile.mkstemp(
        prefix=f'.{p.name}.', suffix='.tmp', dir=str(dir_) if str(dir_) else None
    )
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(payload)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                # Manche Filesysteme (tmpfs, Windows shares) mögen fsync nicht
                pass
        # Atomic Rename
        os.replace(tmp, p)
    except Exception:
        # Aufräumen wenn was schiefging
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_text(path: Path | str, text: str) -> None:
    """Generische atomare Text-Write (kein JSON)."""
    p = Path(path)
    dir_ = p.parent
    fd, tmp = tempfile.mkstemp(
        prefix=f'.{p.name}.', suffix='.tmp', dir=str(dir_) if str(dir_) else None
    )
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(text)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
        os.replace(tmp, p)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise

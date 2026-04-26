#!/usr/bin/env python3
"""
shadow_evaluator.py — Daily 23:30 CEST: Bewertet alle OPEN shadow_trades.

Ruft shadow_trades.evaluate_open() — markiert WIN/LOSS/EXPIRED basierend
auf Preisbewegung seit Setup-Erstellung.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

from shadow_trades import evaluate_open, cleanup_expired


def main() -> int:
    print(f'[shadow-eval] Start {datetime.now().isoformat(timespec="seconds")}')
    r = evaluate_open()
    print(f"[shadow-eval] Open checked: {r['open_checked']}")
    print(f"[shadow-eval] Closed WIN:   {r['closed_win']}")
    print(f"[shadow-eval] Closed LOSS:  {r['closed_loss']}")
    print(f"[shadow-eval] Expired:      {r['expired']}")

    # Wöchentlich aufräumen (Sa)
    if datetime.now().weekday() == 5:
        cleaned = cleanup_expired(older_than_days=90)
        print(f'[shadow-eval] Cleaned {cleaned} old rows.')
    return 0


if __name__ == '__main__':
    sys.exit(main())

#!/usr/bin/env python3
"""
Pipeline Runner — Alle Schritte in Reihe
Wird vom Cron aufgerufen: News → Analyse → Trade → Log
"""
import sys, os, datetime
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
os.chdir(os.path.dirname(os.path.dirname(__file__)))

print(f"[{datetime.datetime.now().strftime('%H:%M')}] Pipeline startet...")

# Schritt 1: Global Radar
from scripts.global_radar import run_global_radar
signals = run_global_radar()
print(f"✓ Radar: {len(signals)} Signale erkannt")

# Schritt 2: Autonomous Loop + Learning (Exit-Check → Entry → Lektion)
from scripts.autonomous_loop import run_full_cycle
closed, trades = run_full_cycle()
print(f"✓ Loop: {len(closed)} Exits | {len(trades)} neue Trades")

# Schritt 3: Opportunity Scanner (anti-zyklisch, unabhängig vom Radar)
from scripts.opportunity_scanner import run_scan
opps = run_scan()
print(f"✓ Scanner: {len(opps)} Kandidaten gescannt")

print(f"[{datetime.datetime.now().strftime('%H:%M')}] Pipeline abgeschlossen")

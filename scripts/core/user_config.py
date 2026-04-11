#!/usr/bin/env python3
"""
user_config.py — Multi-User Konfiguration
==========================================
Jeder User hat eigenes Kapital, Risikoprofil, Strategien und Discord-Channel.
Alle anderen Scripts holen User-Config von hier — nie hardcoded.

VERWENDUNG:
  from scripts.core.user_config import get_user, get_default_user
  
  user = get_default_user()         # Victor (default)
  user = get_user('user_victor')    # explizit
  
  user.capital                      # 25000
  user.notify_channel               # '1475255728313864413'
  user.risk_level                   # 'moderate'
  user.max_positions                # 12
"""

import sqlite3
import json
from dataclasses import dataclass, field
from pathlib import Path

import os as _os
_default_ws = '/data/.openclaw/workspace'
if not Path(_default_ws).exists():
    _default_ws = str(Path(__file__).resolve().parent.parent.parent)
WS = Path(_os.getenv('TRADEMIND_HOME', _default_ws))
DB_PATH = WS / 'data' / 'trading.db'

# Default User (Victor) — wird genutzt wenn kein user_id angegeben
DEFAULT_USER_ID = 'user_victor'

# Risiko-Stufen und ihre Parameter
RISK_PROFILES = {
    'conservative': {
        'max_position_pct': 0.03,   # max 3% pro Position
        'max_thesis_pct':   0.20,   # max 20% pro These
        'max_vix':          22,     # kein Entry über VIX 22
        'min_conviction':   65,     # hohe Hürde
        'stop_buffer_mult': 1.5,    # Stops 50% weiter
    },
    'moderate': {
        'max_position_pct': 0.05,
        'max_thesis_pct':   0.30,
        'max_vix':          30,
        'min_conviction':   45,
        'stop_buffer_mult': 1.0,
    },
    'aggressive': {
        'max_position_pct': 0.08,
        'max_thesis_pct':   0.40,
        'max_vix':          35,
        'min_conviction':   35,
        'stop_buffer_mult': 0.8,
    },
}


@dataclass
class UserConfig:
    user_id:        str
    discord_id:     str
    name:           str
    capital:        float
    risk_level:     str
    max_positions:  int
    notify_channel: str
    strategies:     list = field(default_factory=list)  # leere Liste = alle erlaubt
    active:         bool = True

    @property
    def risk_profile(self) -> dict:
        return RISK_PROFILES.get(self.risk_level, RISK_PROFILES['moderate'])

    @property
    def max_position_eur(self) -> float:
        return self.capital * self.risk_profile['max_position_pct']

    @property
    def max_thesis_eur(self) -> float:
        return self.capital * self.risk_profile['max_thesis_pct']

    @property
    def max_vix(self) -> float:
        return self.risk_profile['max_vix']

    @property
    def min_conviction(self) -> int:
        return self.risk_profile['min_conviction']

    def allows_strategy(self, strategy: str) -> bool:
        """True wenn Strategie für diesen User erlaubt ist."""
        if not self.strategies:
            return True  # leere Liste = alle erlaubt
        return strategy in self.strategies

    def __repr__(self):
        return f"User({self.name}, {self.capital}€, {self.risk_level})"


def _get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def get_user(user_id: str) -> UserConfig | None:
    """Holt User-Config aus DB."""
    conn = _get_db()
    row = conn.execute(
        'SELECT * FROM users WHERE user_id=? AND active=1', (user_id,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    strategies = json.loads(row['strategies']) if row['strategies'] else []
    return UserConfig(
        user_id=row['user_id'],
        discord_id=row['discord_id'] or '',
        name=row['name'] or user_id,
        capital=row['capital'] or 25000,
        risk_level=row['risk_level'] or 'moderate',
        max_positions=row['max_positions'] or 12,
        notify_channel=row['notify_channel'] or '',
        strategies=strategies,
        active=bool(row['active']),
    )


def get_default_user() -> UserConfig:
    """Gibt Victor zurück (default). Fallback wenn DB nicht erreichbar."""
    user = get_user(DEFAULT_USER_ID)
    if user:
        return user
    # Hardcode-Fallback nur hier, nirgendwo sonst im System
    return UserConfig(
        user_id='user_victor',
        discord_id='452053147620343808',
        name='Victor',
        capital=25000,
        risk_level='moderate',
        max_positions=12,
        notify_channel='1475255728313864413',
    )


def get_all_users() -> list[UserConfig]:
    """Alle aktiven User — für zukünftige Multi-User-Iterationen."""
    conn = _get_db()
    rows = conn.execute('SELECT * FROM users WHERE active=1').fetchall()
    conn.close()
    users = []
    for row in rows:
        strategies = json.loads(row['strategies']) if row['strategies'] else []
        users.append(UserConfig(
            user_id=row['user_id'],
            discord_id=row['discord_id'] or '',
            name=row['name'] or row['user_id'],
            capital=row['capital'] or 25000,
            risk_level=row['risk_level'] or 'moderate',
            max_positions=row['max_positions'] or 12,
            notify_channel=row['notify_channel'] or '',
            strategies=strategies,
            active=True,
        ))
    return users


def create_user(user_id: str, discord_id: str, name: str,
                capital: float = 10000, risk_level: str = 'moderate',
                notify_channel: str = '') -> UserConfig:
    """Neuen User anlegen."""
    from datetime import datetime, timezone
    conn = _get_db()
    conn.execute('''
        INSERT OR REPLACE INTO users
        (user_id, discord_id, name, capital, risk_level, max_positions,
         notify_channel, strategies, created_at, active)
        VALUES (?, ?, ?, ?, ?, 10, ?, '[]', ?, 1)
    ''', (user_id, discord_id, name, capital, risk_level, notify_channel,
          datetime.now(timezone.utc).isoformat()))
    conn.commit()
    conn.close()
    return get_user(user_id)


if __name__ == '__main__':
    u = get_default_user()
    print(f"Default User: {u}")
    print(f"  Max Position:  {u.max_position_eur:.0f}€")
    print(f"  Max Thesis:    {u.max_thesis_eur:.0f}€")
    print(f"  Max VIX:       {u.max_vix}")
    print(f"  Min Conviction:{u.min_conviction}")
    print(f"  Discord:       #{u.notify_channel}")
    print()
    print(f"Alle User: {get_all_users()}")

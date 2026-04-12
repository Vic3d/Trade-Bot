import json
from pathlib import Path

path = Path('/data/.openclaw/workspace/data/strategies.json')
data = json.loads(path.read_bytes().decode('utf-8', errors='replace'))

new_theses = {
    'PS_Lithium': {
        'name': 'Lithium-Produzenten im Schweinezyklus-Bottom',
        'status': 'active',
        'conviction': 3,
        'sector': 'materials',
        'thesis': (
            'Lithium-Nachfrage waechst 40x bis 2040 (EVs + stationaere Energiespeicher). '
            'Neue Minen brauchen 15 Jahre vom Fund bis Foerderung. '
            'Angebotsluecke oeffnet sich 2027-2029. '
            'Albemarle hat CapEx 2024-2026 gedrittelt wegen Tiefpreisen — '
            'genau das was das naechste Defizit baut (Schweinezyklus: low prices cure low prices). '
            'Preis hat sich seit 2025 fast verdreifacht, Aktien noch weit unter 2022-Hochs. '
            'Produzenten (ALB, PLS, SGML) bereits foerdernd, profitieren direkt vom Preis-Leverage.'
        ),
        'entry_trigger': (
            'Lithium Carbonat Preis haelt sich ueber 15 USD/kg oder steigt weiter, '
            'ODER ALB/PLS technischer Ausbruch ueber 200-Tage-Linie, '
            'ODER Quartalsgewinne zeigen positive Free Cashflow Rueckkehr'
        ),
        'kill_trigger': (
            'EV-Verkaufswachstum bricht global mehr als 20% ein, '
            'ODER Feststoffbatterie ohne Lithium skaliert kommerziell vor 2030, '
            'ODER Lithiumpreis faellt zurueck unter 10 USD/kg'
        ),
        'tickers': ['ALB', 'SGML', 'LAC'],
        'direction': 'LONG',
        'timeframe': '12-36 Monate',
        'position_size_eur': 1000,
        'stop_pct': 0.12,
        'target_pct': 0.40,
        'created_at': '2026-04-11',
        'source': 'Transcript: finanzbär-lithium-2026-03-27'
    },
    'PS_Helium': {
        'name': 'Linde AG — Helium-Engpass als Halbleiter-Kritikalitaet',
        'status': 'active',
        'conviction': 4,
        'sector': 'industrials',
        'thesis': (
            '35 Prozent des weltweiten Heliums fliesst durch Hormuz aus Qatar. '
            'Qatar hat 12,8 Mio. Tonnen LNG-Exportkapazitaet verloren, '
            'Wiederherstellungszeit 3-5 Jahre — dauerhafter Angebotsschock, kein temporaerer. '
            'Helium entsteht als Nebenprodukt der Erdgasfoerderung, '
            'laesst sich nicht ersetzen, entweicht in Atmosphaere wenn nicht aufgefangen. '
            'TSMC und SK Hynix benoetigen Helium fuer Wafer-Kuehlung — direkte Halbleiter-Kritikalitaet. '
            'Linde haelt strategische Reserven und globale Verfluessigungsanlagen '
            'ausserhalb der Krisenregion mit langfristigen Liefervertraegen. '
            'Lars Eriksen hat LIN bereits als Zertifikat-Position aufgenommen.'
        ),
        'entry_trigger': (
            'Hormuz-Situation bleibt angespannt, '
            'ODER Linde meldet hoehere Helium-Margen im naechsten Quartalsbericht, '
            'ODER LIN Pullback auf 200-Tage-Linie als Einstiegschance'
        ),
        'kill_trigger': (
            'Hormuz vollstaendig normalisiert und Qatar LNG schneller wiederhergestellt als erwartet unter 18 Monate, '
            'ODER neues grosses Helium-Vorkommen ausserhalb Naher Osten erschlossen, '
            'ODER Halbleiterhersteller wechseln auf alternative Kuehlmethoden'
        ),
        'tickers': ['LIN'],
        'direction': 'LONG',
        'timeframe': '6-24 Monate',
        'position_size_eur': 1200,
        'stop_pct': 0.08,
        'target_pct': 0.25,
        'created_at': '2026-04-11',
        'source': 'Transcript: eriksen-rendite-spezialisten-2026-03-22'
    },
    'PS_LNG': {
        'name': 'Struktureller LNG-Mangel — US-Exporteure profitieren auf Jahre',
        'status': 'active',
        'conviction': 4,
        'sector': 'energy',
        'thesis': (
            'Qatar hat 17 Prozent seiner LNG-Exportkapazitaet verloren, '
            'Wiederherstellungszeit 3-5 Jahre — kein temporaerer Ausfall. '
            'Italien, Suedkorea, China suchen alle gleichzeitig Ersatz auf dem Spotmarkt. '
            'US-LNG ist der einzige verfuegbare Ersatz — struktureller Vorteil auf Jahre. '
            'Brent steigt schneller als WTI und bestaetigt europaeischen Versorgungsdruck. '
            'Trump nutzt Energieexporte als geopolitisches Druckmittel, US-LNG wird strategischer. '
            'Eriksen: Cheniere Energy wurde nach Qatar-Schock aggressiv gekauft.'
        ),
        'entry_trigger': (
            'Brent-WTI-Spread bleibt erhoeht ueber 5 USD, '
            'ODER Cheniere meldet hoehere Langfristvertraege oder Kapazitaetsauslastung, '
            'ODER LNG-Spot-Preise in Europa steigen weiter'
        ),
        'kill_trigger': (
            'Qatar-Kapazitaet vorzeitig wiederhergestellt unter 18 Monate, '
            'ODER globale Rezession drueckt LNG-Nachfrage um mehr als 25 Prozent, '
            'ODER vollstaendige Iran-Deal und Hormuz-Normalisierung und globaler Energiefrieden'
        ),
        'tickers': ['LNG', 'NFE'],
        'direction': 'LONG',
        'timeframe': '6-36 Monate',
        'position_size_eur': 1200,
        'stop_pct': 0.09,
        'target_pct': 0.30,
        'created_at': '2026-04-11',
        'source': 'Transcript: eriksen-rendite-spezialisten-2026-03-22'
    },
    'PS_EuroDefense': {
        'name': 'Europaeische Ruestungsexpansion — struktureller Jahrzehnt-Zyklus',
        'status': 'active',
        'conviction': 4,
        'sector': 'defense',
        'thesis': (
            'Europas Abhaengigkeit von US-Schutz ist unwiderruflich beschaedigt. '
            'UK, Deutschland, Polen (4 Prozent BIP), Frankreich erhoehen alle Verteidigungsbudgets. '
            'Treiber: nicht nur Ukraine, sondern US unter Trump kein verlasslicher NATO-Partner mehr. '
            'Das ist ein Jahrzehnt-Ruestungszyklus — strukturell, nicht event-getrieben. '
            'Rheinmetall 2024: Auftragsbestand 40 Mrd EUR. '
            'BAE Systems: UK Nuclear Submarine plus F-35 Instandhaltung. '
            'Aktuell 12 bullish_defense Events in 24h Newslage. '
            'Unterschied zu PS3 (Russland-Ukraine event): PS_EuroDefense ist geopolitische Neuordnung.'
        ),
        'entry_trigger': (
            'Neues NATO oder EU Verteidigungsbudget-Beschluss, '
            'ODER Rheinmetall oder BAE Auftrag ueber 1 Mrd EUR gemeldet, '
            'ODER RHM.DE technischer Ausbruch ueber letztes Zwischenhoch'
        ),
        'kill_trigger': (
            'Gesamteuropaeischer Friedensvertrag Ukraine plus Naher Osten '
            'und NATO-Ausgaben sinken wieder unter 2 Prozent fuer Mehrheit der Mitglieder, '
            'ODER Trump-Isolationismus endet und USA sichert Europa wieder vollstaendig ab'
        ),
        'tickers': ['RHM.DE', 'BA.L', 'LDO.MI', 'SAAB-B.ST'],
        'direction': 'LONG',
        'timeframe': '12-48 Monate',
        'position_size_eur': 1000,
        'stop_pct': 0.10,
        'target_pct': 0.35,
        'created_at': '2026-04-11',
        'source': 'News 11.04.2026 + eriksen-rendite-spezialisten-2026-03-22'
    }
}

for sid, strat in new_theses.items():
    data[sid] = strat
    print('Added:', sid, '--', strat['name'])

path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
print()
print('strategies.json:', len(data), 'Strategien total')

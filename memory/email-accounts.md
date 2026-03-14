# E-Mail Zugangsdaten — Schutzeichel

## OWA Server
- URL: https://mail.phx-hosting.de/owa/
- Login-Format: `phx-hosting\username`
- Login-Endpoint: POST `/owa/auth.owa`

## Accounts

| Account | Benutzername | Passwort | Postfach |
|---------|-------------|----------|----------|
| info2 | `phx-hosting\info2` | `*8166Belinea` | info@gebr-schutzeichel.de |
| auftrag | `phx-hosting\auftrag` | `*8166*Belinea` | auftrag@gebr-schutzeichel.de |
| rechnung | `phx-hosting\rechnung` | `*8166*Belinea` | rechnung@gebr-schutzeichel.de |
| victor | `phx-hosting\victor` | `*8166Belinea` | victor@gebr-schutzeichel.de |

## Kundenanfragen kommen rein in
- **INFO2**: MyHammer-Anfragen, direkte Kundenanfragen
- **AUFTRAG**: B&O/TSP Aufträge, Handwerkerkopplung, Hausverwaltungen
- **RECHNUNG**: Lieferanten-Rechnungen, keine Kundenanfragen
- **VICTOR**: Persönlich, keine Kundenanfragen

## Technische Details
- OWA Basic Mode (Exchange 15.2.1748.10)
- Session-Cookies: cadata, cadataTTL, cadataKey, cadataIV, cadataSig (alle HttpOnly)
- Message-ID Format: `RgAAAA...AAAJ`
- Message öffnen: `GET /owa/?ae=Item&t=IPM.Note&id=<encoded_id>&a=Open`

#!/usr/bin/env python3
"""
dashboard.py — Phase 43i: TradeMind Streamlit Dashboard.

Live-View auf Phase-43-Performance, Positionen, Trades, Hunter, CEO-Aktivität.

Run:
  streamlit run scripts/dashboard.py --server.port 8501 --server.address 0.0.0.0

Production (auf Server):
  systemctl start trademind-dashboard

Auth:
  Query-String: ?token=YOUR_TOKEN
  Token wird gelesen aus data/dashboard_token.txt (oder env DASHBOARD_TOKEN)
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

DB              = WS / 'data' / 'trading.db'
TOKEN_FILE      = WS / 'data' / 'dashboard_token.txt'
BASELINE_FILE   = WS / 'data' / 'phase43_baseline.json'

# ─── Setup + Auth ──────────────────────────────────────────────────────────

st.set_page_config(
    page_title='TradeMind | Albert CEO',
    page_icon='📈',
    layout='wide',
    initial_sidebar_state='collapsed',
)


def _get_token() -> str:
    if TOKEN_FILE.exists():
        return TOKEN_FILE.read_text().strip()
    return os.getenv('DASHBOARD_TOKEN', 'tm-dev-token-12345')


def _check_auth() -> bool:
    expected = _get_token()
    qp = st.query_params
    given = qp.get('token', '')
    if given == expected:
        return True
    return False


# ─── Daten-Loader (cached) ─────────────────────────────────────────────────

@st.cache_data(ttl=60)
def load_phase43() -> dict:
    try:
        from phase43_baseline import get_performance
        return get_performance()
    except Exception as e:
        return {'error': str(e)}


@st.cache_data(ttl=60)
def load_open_positions() -> pd.DataFrame:
    """Open positions mit Live-Werten."""
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "SELECT id, ticker, strategy, entry_price, shares, stop_price, "
        "       target_price, entry_date, sector "
        "FROM paper_portfolio WHERE status='OPEN'"
    ).fetchall()
    c.close()

    try:
        from core.live_data import get_price_eur
    except Exception:
        get_price_eur = lambda t: None  # type: ignore

    data = []
    for r in rows:
        e = float(r['entry_price'] or 0)
        s = float(r['shares'] or 0)
        live = get_price_eur(r['ticker']) or 0
        live = float(live)
        pos_eur = e * s
        cur_eur = live * s if live else pos_eur
        unr = cur_eur - pos_eur
        pct = (unr / pos_eur * 100) if pos_eur else 0
        try:
            entry_dt = datetime.fromisoformat(str(r['entry_date'])[:19])
            days_held = (datetime.now() - entry_dt).days
        except Exception:
            days_held = 0
        data.append({
            'Ticker':    r['ticker'],
            'Strategy':  r['strategy'] or '?',
            'Entry':     round(e, 2),
            'Live':      round(live, 2),
            'Shares':    int(s),
            'Position€': round(pos_eur, 0),
            'PnL€':      round(unr, 0),
            'PnL%':      round(pct, 2),
            'Stop':      r['stop_price'],
            'Target':    r['target_price'],
            'Days':      days_held,
            'Sector':    r['sector'] or 'unknown',
            'EntryDate': str(r['entry_date'])[:10],
        })
    return pd.DataFrame(data)


@st.cache_data(ttl=60)
def load_closed_trades(days: int = 90) -> pd.DataFrame:
    """Closed trades letzte N Tage."""
    c = sqlite3.connect(str(DB))
    c.row_factory = sqlite3.Row
    cutoff = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    rows = c.execute(
        "SELECT id, ticker, strategy, entry_price, close_price, shares, "
        "       pnl_eur, pnl_pct, status, exit_type, entry_date, close_date, sector "
        "FROM paper_portfolio WHERE status IN ('CLOSED','WIN','LOSS','RESET_CLOSED') "
        "AND substr(close_date,1,10) >= ? "
        "ORDER BY close_date DESC",
        (cutoff,)
    ).fetchall()
    c.close()
    return pd.DataFrame([
        {
            'Ticker':    r['ticker'],
            'Strategy':  r['strategy'] or '?',
            'Entry':     round(float(r['entry_price'] or 0), 2),
            'Close':     round(float(r['close_price'] or 0), 2),
            'PnL€':      round(float(r['pnl_eur'] or 0), 0),
            'PnL%':      round(float(r['pnl_pct'] or 0), 2),
            'ExitType':  r['exit_type'] or '-',
            'CloseDate': str(r['close_date'])[:10],
            'EntryDate': str(r['entry_date'])[:10],
            'Sector':    r['sector'] or 'unknown',
        } for r in rows
    ])


@st.cache_data(ttl=60)
def load_proposals() -> pd.DataFrame:
    """Hunter-Proposals."""
    pf = WS / 'data' / 'proposals.json'
    if not pf.exists():
        return pd.DataFrame()
    try:
        data = json.loads(pf.read_text(encoding='utf-8'))
        if isinstance(data, dict):
            data = data.get('proposals', [])
        rows = []
        for p in data:
            if not isinstance(p, dict):
                continue
            rows.append({
                'Ticker':     p.get('ticker', '?'),
                'Strategy':   p.get('strategy', '?'),
                'Source':     p.get('source', '?'),
                'Status':     p.get('status', '?'),
                'Confidence': p.get('confidence'),
                'Trigger':    p.get('trigger', '-'),
                'Entry':      p.get('entry_price'),
                'Created':    str(p.get('created_at', ''))[:16],
            })
        return pd.DataFrame(rows)
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=60)
def load_macro_events(days: int = 7) -> pd.DataFrame:
    try:
        c = sqlite3.connect(str(DB))
        rows = c.execute(
            "SELECT detected_at, event_type, severity, impact_tickers "
            "FROM macro_events "
            "WHERE substr(detected_at,1,10) >= ? "
            "ORDER BY detected_at DESC",
            ((datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d'),)
        ).fetchall()
        c.close()
        return pd.DataFrame([
            {'When': r[0][:16], 'Event': r[1],
             'Severity': float(r[2] or 0), 'Tickers': (r[3] or '')[:60]}
            for r in rows
        ])
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=60)
def load_equity_curve(days: int = 90) -> pd.DataFrame:
    """Berechne Equity-Curve aus closed trades + open unrealized.
    Vereinfacht: kumulierter realized PnL über Zeit + heutiger Unrealized."""
    closed = load_closed_trades(days=days)
    if closed.empty:
        return pd.DataFrame()

    # Cumulative realized
    closed_sorted = closed.sort_values('CloseDate')
    closed_sorted['CumPnL'] = closed_sorted['PnL€'].cumsum()
    closed_sorted['Date'] = pd.to_datetime(closed_sorted['CloseDate'])
    return closed_sorted[['Date', 'CumPnL', 'PnL€', 'Ticker', 'Strategy']]


@st.cache_data(ttl=60)
def load_inbox_summary(hours: int = 24) -> dict:
    try:
        from ceo_inbox import summarize_unread
        return summarize_unread(hours=hours)
    except Exception:
        return {'total': 0}


# ─── UI ──────────────────────────────────────────────────────────────────

def _render_phase43_header():
    p = load_phase43()
    if 'error' in p:
        st.error('Phase-43-Baseline noch nicht initialisiert.')
        return

    pnl = p['phase43_total_pnl_eur']
    pct = p['phase43_total_pnl_pct']
    n_open = p['phase43_n_open']
    n_closed = p['phase43_n_closed']

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric('Phase 43 PnL',
                f'{pnl:+,.0f}€'.replace(',', '.'),
                f'{pct:+.2f}%')
    col2.metric('Realized',
                f'{p["phase43_realized_eur"]:+,.0f}€'.replace(',', '.'),
                f'{n_closed} closed')
    col3.metric('Unrealized',
                f'{p["phase43_unrealized_eur"]:+,.0f}€'.replace(',', '.'),
                f'{n_open} open')
    col4.metric('Hunter-Conv',
                f'{p["hunter_conversion_pct"]:.1f}%',
                f'{p["hunter_executed"]}/{p["hunter_proposals_total"]}')
    col5.metric('Win-Rate',
                f'{p["phase43_win_rate_pct"]:.0f}%',
                f'{p["phase43_n_wins"]}W / {p["phase43_n_losses"]}L')


def tab_performance():
    st.subheader('📈 Performance-Übersicht')
    p = load_phase43()
    if 'error' in p:
        st.warning('Phase-43-Baseline fehlt.')
        return

    eq = load_equity_curve(days=90)
    closed = load_closed_trades(days=90)

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown('**Equity-Curve (kumulierter Realized PnL, 90d)**')
        if not eq.empty:
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=eq['Date'], y=eq['CumPnL'],
                mode='lines+markers', name='Cum PnL €',
                line=dict(color='#00C896', width=2),
                hovertemplate='%{x|%Y-%m-%d}<br>Cum: %{y:+,.0f}€<extra></extra>',
            ))
            fig.update_layout(
                height=320, margin=dict(l=0, r=0, t=10, b=0),
                yaxis_title='€', xaxis_title='', showlegend=False,
                hovermode='x unified',
            )
            fig.add_hline(y=0, line_dash='dash', line_color='gray')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info('Noch keine geschlossenen Trades.')

    with col_b:
        st.markdown('**Drawdown vom Peak**')
        if not eq.empty:
            running_max = eq['CumPnL'].cummax()
            dd = eq['CumPnL'] - running_max
            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=eq['Date'], y=dd, mode='lines',
                fill='tozeroy', fillcolor='rgba(255,99,71,0.3)',
                line=dict(color='#FF6347', width=1.5),
                hovertemplate='%{x|%Y-%m-%d}<br>DD: %{y:,.0f}€<extra></extra>',
            ))
            fig.update_layout(
                height=320, margin=dict(l=0, r=0, t=10, b=0),
                yaxis_title='Drawdown €', xaxis_title='', showlegend=False,
            )
            st.plotly_chart(fig, use_container_width=True)
            st.caption(f'Max-Drawdown: {dd.min():,.0f}€')
        else:
            st.info('Noch keine Daten für Drawdown.')

    st.markdown('---')
    col_c, col_d = st.columns(2)
    with col_c:
        st.markdown('**Daily PnL (letzte 90d)**')
        if not closed.empty:
            daily = closed.groupby('CloseDate')['PnL€'].sum().reset_index()
            daily['Color'] = daily['PnL€'].apply(lambda x: '#00C896' if x > 0 else '#FF6347')
            fig = px.bar(daily, x='CloseDate', y='PnL€', color='Color',
                          color_discrete_map={'#00C896': '#00C896',
                                              '#FF6347': '#FF6347'})
            fig.update_layout(height=300, showlegend=False,
                                margin=dict(l=0, r=0, t=10, b=0),
                                xaxis_title='', yaxis_title='€')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info('Noch keine täglichen Trades.')

    with col_d:
        st.markdown('**Win/Loss Distribution**')
        if not closed.empty:
            fig = px.histogram(closed, x='PnL€', nbins=20,
                                color_discrete_sequence=['#0099CC'])
            fig.update_layout(height=300, showlegend=False,
                                margin=dict(l=0, r=0, t=10, b=0),
                                xaxis_title='PnL €', yaxis_title='Anzahl Trades')
            fig.add_vline(x=0, line_dash='dash', line_color='gray')
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info('Keine Histogramm-Daten.')


def tab_positions():
    st.subheader('💼 Open Positions')
    df = load_open_positions()
    if df.empty:
        st.info('Keine offenen Positionen.')
        return

    total_val = df['Position€'].sum()
    total_pnl = df['PnL€'].sum()
    col1, col2, col3 = st.columns(3)
    col1.metric('Open Positions', len(df))
    col2.metric('Total Value', f'{total_val:,.0f}€'.replace(',', '.'))
    col3.metric('Total Unrealized PnL', f'{total_pnl:+,.0f}€'.replace(',', '.'))

    col_a, col_b = st.columns([2, 1])
    with col_a:
        st.markdown('**Positionen-Tabelle**')
        df_display = df.sort_values('PnL€', ascending=False).copy()
        st.dataframe(df_display, use_container_width=True, hide_index=True,
                      height=420)

    with col_b:
        st.markdown('**Sektor-Verteilung**')
        sec = df.groupby('Sector')['Position€'].sum().reset_index()
        if not sec.empty:
            fig = px.pie(sec, names='Sector', values='Position€',
                          hole=0.45,
                          color_discrete_sequence=px.colors.qualitative.Set3)
            fig.update_layout(height=420, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig, use_container_width=True)


def tab_trades():
    st.subheader('📜 Closed Trades')
    df = load_closed_trades(days=90)
    if df.empty:
        st.info('Keine geschlossenen Trades.')
        return

    n = len(df)
    wins = (df['PnL€'] > 0).sum()
    losses = (df['PnL€'] < 0).sum()
    wr = wins / n * 100 if n else 0
    total_pnl = df['PnL€'].sum()
    avg_pnl = df['PnL€'].mean()

    col1, col2, col3, col4 = st.columns(4)
    col1.metric('Trades (90d)', n)
    col2.metric('Win-Rate', f'{wr:.1f}%', f'{wins}W / {losses}L')
    col3.metric('Total PnL', f'{total_pnl:+,.0f}€'.replace(',', '.'))
    col4.metric('Avg PnL/Trade', f'{avg_pnl:+,.1f}€'.replace(',', '.'))

    st.markdown('---')
    col_a, col_b = st.columns([2, 1])
    with col_a:
        st.markdown('**Trade-Liste (sortable)**')
        st.dataframe(df, use_container_width=True, hide_index=True, height=420)

    with col_b:
        st.markdown('**PnL pro Strategie**')
        strat = df.groupby('Strategy').agg(
            PnL=('PnL€', 'sum'),
            N=('PnL€', 'count'),
            WR=('PnL€', lambda x: (x > 0).sum() / len(x) * 100)
        ).reset_index().sort_values('PnL', ascending=True)
        if not strat.empty:
            fig = px.bar(strat, x='PnL', y='Strategy', orientation='h',
                          text='N', color='PnL',
                          color_continuous_scale=['#FF6347', '#FFFFFF', '#00C896'],
                          color_continuous_midpoint=0)
            fig.update_layout(height=420, margin=dict(l=0, r=0, t=10, b=0),
                                showlegend=False, xaxis_title='Total PnL €',
                                yaxis_title='', coloraxis_showscale=False)
            st.plotly_chart(fig, use_container_width=True)


def tab_hunter():
    st.subheader('🎯 Active Hunter')
    df = load_proposals()
    p = load_phase43()

    if df.empty:
        st.info('Noch keine Hunter-Proposals.')
        return

    # Nur ceo_active
    df_h = df[df['Source'] == 'ceo_active'].copy()
    if df_h.empty:
        st.info('Hunter hat noch keine Proposals erzeugt.')
        return

    col1, col2, col3, col4 = st.columns(4)
    if 'error' not in p:
        col1.metric('Conversion', f'{p["hunter_conversion_pct"]:.1f}%',
                     f'{p["hunter_executed"]} executed')
        col2.metric('Total Proposals', p['hunter_proposals_total'])
        col3.metric('Blocked', p['hunter_blocked'])
        col4.metric('Watching', p['hunter_watching'])

    st.markdown('---')
    col_a, col_b = st.columns([3, 2])
    with col_a:
        st.markdown('**Letzte Hunter-Proposals (top 30)**')
        df_recent = df_h.sort_values('Created', ascending=False).head(30)
        st.dataframe(df_recent, use_container_width=True, hide_index=True,
                      height=420)

    with col_b:
        st.markdown('**Status-Verteilung**')
        st_counts = df_h['Status'].value_counts().reset_index()
        st_counts.columns = ['Status', 'Count']
        if not st_counts.empty:
            color_map = {
                'executed': '#00C896', 'execute_blocked': '#FF6347',
                'watching': '#FFC107', 'rejected': '#9E9E9E',
                'expired': '#607D8B', 'pending': '#0099CC',
            }
            fig = px.pie(st_counts, names='Status', values='Count',
                          color='Status', color_discrete_map=color_map, hole=0.4)
            fig.update_layout(height=320, margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig, use_container_width=True)


def tab_phase43_vs_legacy():
    st.subheader('🆕 Phase 43 vs. Pre-43')
    p = load_phase43()
    if 'error' in p:
        st.warning('Baseline nicht gesetzt.')
        return

    st.markdown(f'**Baseline gesetzt am: {p["baseline_ts"][:16]} UTC** '
                 f'({p["days_since_baseline"]:.1f} Tage live)')

    col1, col2, col3 = st.columns(3)
    col1.metric('Phase-43 Total PnL',
                 f'{p["phase43_total_pnl_eur"]:+,.0f}€'.replace(',', '.'),
                 f'{p["phase43_total_pnl_pct"]:+.2f}%')
    col2.metric('Pre-43 Bewegung (zählt nicht)',
                 f'{p["pre43_unrealized_eur"]:+,.0f}€'.replace(',', '.'))
    col3.metric('Aktueller Fund-Wert',
                 f'{p["current_total_eur"]:,.0f}€'.replace(',', '.'),
                 f'vs Baseline {p["baseline_total_eur"]:,.0f}€'.replace(',', '.'))

    st.markdown('---')
    st.markdown('**Open Phase-43-Positionen Detail:**')
    if p.get('phase43_open_details'):
        df_p43 = pd.DataFrame(p['phase43_open_details'])
        st.dataframe(df_p43, use_container_width=True, hide_index=True)
    else:
        st.info('Noch keine offenen Phase-43-Positionen.')

    st.markdown('---')
    st.markdown('**Hunter-Statistik seit Baseline:**')
    h_data = pd.DataFrame([{
        'Metric':   m,
        'Wert':     v,
    } for m, v in [
        ('Total Proposals',     p['hunter_proposals_total']),
        ('Executed',            p['hunter_executed']),
        ('Execute-Blocked',     p['hunter_blocked']),
        ('Watching',            p['hunter_watching']),
        ('Rejected (SKIP)',     p['hunter_rejected']),
        ('Expired (Timeout)',   p['hunter_expired']),
        ('Conversion-Rate',     f'{p["hunter_conversion_pct"]:.1f}%'),
    ]])
    st.dataframe(h_data, use_container_width=True, hide_index=True)


@st.cache_data(ttl=30)
def load_recent_decisions(limit: int = 50) -> pd.DataFrame:
    """Letzte CEO-Decisions aus jsonl-Log."""
    log_file = WS / 'data' / 'ceo_decisions.jsonl'
    if not log_file.exists():
        return pd.DataFrame()
    rows = []
    try:
        with open(log_file, encoding='utf-8') as f:
            for line in f:
                try:
                    d = json.loads(line)
                    rows.append({
                        'Time':   (d.get('ts') or '')[:16],
                        'Ticker': d.get('ticker', '?'),
                        'Strategy': d.get('strategy', '?'),
                        'Action': d.get('action', '?'),
                        'Conf':   d.get('confidence'),
                        'Event':  d.get('event', '?'),
                        'Success': d.get('success'),
                        'Reason': str(d.get('reason', ''))[:120],
                    })
                except Exception:
                    continue
    except Exception:
        return pd.DataFrame()
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    return df.tail(limit)


@st.cache_data(ttl=60)
def load_shadow_trades() -> pd.DataFrame:
    """Multi-Strategy-Shadow-Trades."""
    try:
        c = sqlite3.connect(str(DB))
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT strategy_id, ticker, status, entry_price_eur, "
            "       last_price_eur, target_price_eur, stop_price_eur, "
            "       unrealized_pnl_eur, realized_pnl_eur, opened_at "
            "FROM shadow_strategy_trades ORDER BY opened_at DESC"
        ).fetchall()
        c.close()
        return pd.DataFrame([dict(r) for r in rows])
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=30)
def load_inbox_recent(hours: int = 6) -> pd.DataFrame:
    """Letzte Inbox-Events."""
    inbox_file = WS / 'data' / 'ceo_inbox.jsonl'
    if not inbox_file.exists():
        return pd.DataFrame()
    cutoff = (datetime.now(timezone.utc).timestamp() - hours * 3600)
    rows = []
    try:
        with open(inbox_file, encoding='utf-8') as f:
            for line in f:
                try:
                    e = json.loads(line)
                    ts = datetime.fromisoformat(e.get('ts','').replace('Z','+00:00'))
                    if ts.timestamp() < cutoff:
                        continue
                    rows.append({
                        'Time':     e.get('ts','')[:16],
                        'Severity': e.get('severity','?'),
                        'Cat':      e.get('category','?'),
                        'Event':    e.get('event_type','?'),
                        'Pinged':   '🔔' if e.get('user_pinged') else '🔕',
                        'Message':  str(e.get('message',''))[:120],
                    })
                except Exception:
                    continue
    except Exception:
        return pd.DataFrame()
    return pd.DataFrame(rows[-100:])


def tab_live_activity():
    st.subheader('⚡ Was macht Albert JETZT')

    col1, col2 = st.columns([2, 1])

    with col1:
        st.markdown('**Letzte 30 Decisions (live aus ceo_decisions.jsonl)**')
        df = load_recent_decisions(limit=30)
        if df.empty:
            st.info('Noch keine Decisions geloggt.')
        else:
            df_display = df.sort_values('Time', ascending=False).head(30)
            st.dataframe(df_display, use_container_width=True, hide_index=True,
                          height=380)

    with col2:
        st.markdown('**Letzte Inbox-Events (6h)**')
        df = load_inbox_recent(hours=6)
        if df.empty:
            st.info('Keine Events.')
        else:
            df_display = df.sort_values('Time', ascending=False).head(20)
            st.dataframe(df_display[['Time','Severity','Event','Pinged']],
                          use_container_width=True, hide_index=True, height=380)

    st.markdown('---')
    col_a, col_b = st.columns(2)

    with col_a:
        st.markdown('**Aktuelle Hunter-Proposals (letzte 20)**')
        df = load_proposals()
        if df.empty:
            st.info('Keine Proposals.')
        else:
            ceo = df[df['Source']=='ceo_active'] if 'Source' in df.columns else df
            if not ceo.empty:
                ceo_display = ceo.sort_values('Created', ascending=False).head(20)
                st.dataframe(ceo_display, use_container_width=True,
                              hide_index=True, height=300)

    with col_b:
        st.markdown('**Daemon-State**')
        try:
            state_file = WS / 'data' / 'ceo_daemon_state.json'
            if state_file.exists():
                ds = json.loads(state_file.read_text(encoding='utf-8'))
                relevant = {
                    'state':                ds.get('state'),
                    'cycle_count':          ds.get('cycle_count'),
                    'last_hunt_ts':         (ds.get('last_hunt_ts') or '?')[:16],
                    'last_decide_ts':       (ds.get('last_decide_ts') or '?')[:16],
                    'last_monitor_ts':      (ds.get('last_monitor_ts') or '?')[:16],
                }
                for k, v in relevant.items():
                    st.metric(k, str(v))
        except Exception as e:
            st.error(f'Daemon-State Fehler: {e}')


def tab_strategy_shadow():
    st.subheader('🔬 Multi-Strategy-Shadow — alle 41 Strategien parallel testen')
    st.caption('Jede Strategie bekommt 800€ Shadow-Position. 5% Stop, 15% Target. '
                'Live-Tracking. Nach 30 Tagen ehrliches Ranking.')

    df = load_shadow_trades()
    if df.empty:
        st.info('Noch keine Shadow-Trades — Hunt läuft alle 30min in Marktstunden.')
        return

    # Per-Strategy aggregieren
    df['pnl_total'] = df['unrealized_pnl_eur'].fillna(0) + df['realized_pnl_eur'].fillna(0)
    agg = df.groupby('strategy_id').agg(
        n_total=('ticker', 'count'),
        n_open=('status', lambda x: (x=='OPEN').sum()),
        n_closed_target=('status', lambda x: (x=='CLOSED_TARGET').sum()),
        n_closed_stop=('status', lambda x: (x=='CLOSED_STOP').sum()),
        realized=('realized_pnl_eur', 'sum'),
        unrealized=('unrealized_pnl_eur', 'sum'),
        total_pnl=('pnl_total', 'sum'),
    ).reset_index().sort_values('total_pnl', ascending=False)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric('Strategien', len(agg))
    col2.metric('Total Trades', int(agg['n_total'].sum()))
    col3.metric('Sum Realized', f'{agg["realized"].sum():+,.0f}€'.replace(',', '.'))
    col4.metric('Sum Unrealized', f'{agg["unrealized"].sum():+,.0f}€'.replace(',', '.'))

    st.markdown('---')
    col_a, col_b = st.columns([3, 2])
    with col_a:
        st.markdown('**Strategy-Ranking (PnL)**')
        st.dataframe(agg, use_container_width=True, hide_index=True, height=520)

    with col_b:
        st.markdown('**Top-10 Strategien nach PnL**')
        top10 = agg.head(10)
        if not top10.empty:
            fig = px.bar(top10, x='total_pnl', y='strategy_id', orientation='h',
                          color='total_pnl',
                          color_continuous_scale=['#FF6347','#FFFFFF','#00C896'],
                          color_continuous_midpoint=0)
            fig.update_layout(height=520, margin=dict(l=0, r=0, t=10, b=0),
                                yaxis_title='', xaxis_title='Total PnL €',
                                showlegend=False, coloraxis_showscale=False)
            st.plotly_chart(fig, use_container_width=True)

    st.markdown('---')
    st.markdown('**Alle Shadow-Trades**')
    st.dataframe(df.head(100), use_container_width=True, hide_index=True, height=400)


def tab_macro_inbox():
    st.subheader('📡 Macro-Events & CEO-Inbox')
    df_macro = load_macro_events(days=7)
    inbox = load_inbox_summary(hours=24)

    col1, col2, col3 = st.columns(3)
    col1.metric('Macro-Events 7d', len(df_macro))
    col2.metric('Inbox-Events 24h', inbox.get('total', 0))
    col3.metric('User-pinged', inbox.get('user_pinged', 0))

    st.markdown('---')
    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown('**Macro-Events letzte 7 Tage**')
        if not df_macro.empty:
            event_counts = df_macro['Event'].value_counts().reset_index()
            event_counts.columns = ['Event', 'Count']
            fig = px.bar(event_counts, x='Event', y='Count',
                          color='Event',
                          color_discrete_sequence=px.colors.qualitative.Set2)
            fig.update_layout(height=300, showlegend=False,
                                margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(df_macro.head(20), use_container_width=True,
                          hide_index=True, height=300)
        else:
            st.info('Keine Macro-Events.')

    with col_b:
        st.markdown('**Inbox-Summary 24h**')
        if inbox.get('top_event_types'):
            ev_df = pd.DataFrame([
                {'Event-Type': k, 'Count': v}
                for k, v in inbox['top_event_types'].items()
            ])
            fig = px.bar(ev_df, x='Count', y='Event-Type', orientation='h',
                          color_discrete_sequence=['#0099CC'])
            fig.update_layout(height=300, showlegend=False,
                                margin=dict(l=0, r=0, t=10, b=0))
            st.plotly_chart(fig, use_container_width=True)
        if inbox.get('by_category'):
            st.markdown('**By Category:**')
            cat_df = pd.DataFrame([
                {'Category': k, 'Count': v}
                for k, v in inbox['by_category'].items()
            ])
            st.dataframe(cat_df, use_container_width=True, hide_index=True)


# ─── Main ─────────────────────────────────────────────────────────────────

def main():
    if not _check_auth():
        st.title('🔒 TradeMind Dashboard')
        st.error('Authentication required. Append `?token=YOUR_TOKEN` to URL.')
        st.stop()
        return

    # Header
    try:
        from calendar_service import get_berlin_time
        bt = get_berlin_time()
        time_str = bt['human']
    except Exception:
        time_str = datetime.now().strftime('%H:%M')

    col_t1, col_t2 = st.columns([4, 1])
    col_t1.title('📈 TradeMind — Albert Active CEO')
    col_t2.metric('Live-Zeit', time_str)

    # Phase 43 Header (immer sichtbar)
    _render_phase43_header()

    st.markdown('---')

    # Tabs
    tabs = st.tabs([
        '⚡ Live-Activity',     # NEW: was passiert JETZT
        '🔬 Strategy-Shadow',   # NEW: alle 41 Strategien parallel
        '📈 Performance',
        '💼 Positions',
        '📜 Trades',
        '🎯 Hunter',
        '🆕 Phase 43',
        '📡 Macro & Inbox',
    ])
    with tabs[0]:
        tab_live_activity()
    with tabs[1]:
        tab_strategy_shadow()
    with tabs[2]:
        tab_performance()
    with tabs[3]:
        tab_positions()
    with tabs[4]:
        tab_trades()
    with tabs[5]:
        tab_hunter()
    with tabs[6]:
        tab_phase43_vs_legacy()
    with tabs[7]:
        tab_macro_inbox()

    # Auto-refresh
    st.markdown('---')
    col_r1, col_r2 = st.columns([5, 1])
    col_r1.caption(f'Daten werden alle 60s neu geladen. Letzter Refresh: {time_str}')
    if col_r2.button('🔄 Reload jetzt'):
        st.cache_data.clear()
        st.rerun()


if __name__ == '__main__':
    main()

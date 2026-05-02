#!/usr/bin/env python3
"""
youtube_transcript_monitor.py — Phase 44s: Auto-Pull Tradermacher & Co.

Bisher: Victor copy-paste'd YouTube-Transcripts in Discord.
Neu: System polled abonnierte Channels, holt sich neue Videos selbst,
zieht Transcripts via youtube-transcript-api, und durchpreist sie
durch research_intake.py.

SUBSCRIBED_CHANNELS = Victors kuratierte Liste relevanter Trading-Quellen.

Run: python3 scripts/youtube_transcript_monitor.py
"""
from __future__ import annotations
import json, os, re, subprocess, sys
from datetime import datetime, timezone
from pathlib import Path

WS = Path(os.getenv('TRADEMIND_HOME', str(Path(__file__).resolve().parent.parent)))
sys.path.insert(0, str(WS / 'scripts'))

STATE = WS / 'data' / 'youtube_subscriptions_state.json'
LOG = WS / 'data' / 'youtube_transcript_log.jsonl'

# Channels die Albert taeglich pruefen soll. URLs als RSS-Feed (jeder
# YT-Channel hat einen). YouTube-Channel-ID via 'view source' findbar.
SUBSCRIBED_CHANNELS = {
    'tradermacher': {
        # Channel-ID muss von Victor verifiziert/eingetragen werden
        'name': 'Tradermacher (Eriksen Geld & Gold)',
        'channel_id': 'UC_PLACEHOLDER_TRADERMACHER',  # TODO: echte ID
        'rss': 'https://www.youtube.com/feeds/videos.xml?channel_id=UC_PLACEHOLDER_TRADERMACHER',
        'enabled': False,  # erst aktivieren wenn ID verifiziert
    },
    # Weitere Channels koennen hier dazu — Bloomberg, Real Vision, etc.
}


def _now() -> str: return datetime.now(timezone.utc).isoformat()


def _load_state() -> dict:
    if STATE.exists():
        return json.loads(STATE.read_text(encoding='utf-8'))
    return {'seen_videos': []}


def _save_state(s: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=2, ensure_ascii=False), encoding='utf-8')


def _fetch_rss_videos(channel_meta: dict) -> list[dict]:
    """Liest Channel-RSS, gibt liste neuer videos zurueck."""
    try:
        import urllib.request
        url = channel_meta['rss']
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=15) as resp:
            xml = resp.read().decode('utf-8', errors='ignore')
        # Parse einfach: <entry>...<yt:videoId>...
        entries = re.findall(
            r'<entry>(.*?)</entry>', xml, re.S
        )
        videos = []
        for e in entries[:5]:  # nur die letzten 5
            vid_m = re.search(r'<yt:videoId>([^<]+)</yt:videoId>', e)
            title_m = re.search(r'<title>([^<]+)</title>', e)
            pub_m = re.search(r'<published>([^<]+)</published>', e)
            if vid_m:
                videos.append({
                    'video_id': vid_m.group(1),
                    'title': title_m.group(1) if title_m else '',
                    'published': pub_m.group(1) if pub_m else '',
                })
        return videos
    except Exception as e:
        print(f'[yt_monitor] rss err {channel_meta["name"]}: {e}')
        return []


def _fetch_transcript(video_id: str) -> str:
    """Pullt Transcript via youtube-transcript-api (must be pip-installed)."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        ts = YouTubeTranscriptApi.get_transcript(video_id, languages=['de', 'en'])
        return ' '.join(seg['text'] for seg in ts)
    except ImportError:
        return '[youtube-transcript-api not installed: pip install youtube-transcript-api]'
    except Exception as e:
        return f'[transcript fail: {e}]'


def _process_video(channel: dict, video: dict, source_label: str) -> dict:
    """Pullt Transcript + ruft research_intake.process()."""
    text = _fetch_transcript(video['video_id'])
    if text.startswith('['):
        return {'video_id': video['video_id'], 'status': 'transcript_fail',
                'error': text}
    try:
        from research_intake import process as _ri_process
        src = f"{source_label} — {video.get('title','?')[:80]} (YT {video['video_id']})"
        r = _ri_process(text, src)
        return {
            'video_id': video['video_id'],
            'title': video['title'],
            'status': 'processed',
            'verdict': r['learnings'].get('verdict', '?'),
            'persisted': r.get('persisted', {}),
        }
    except Exception as e:
        return {'video_id': video['video_id'], 'status': 'intake_fail',
                'error': str(e)}


def run() -> dict:
    state = _load_state()
    seen = set(state.get('seen_videos', []))
    results = {'channels_checked': 0, 'new_videos': 0, 'processed': []}

    for ch_id, ch_meta in SUBSCRIBED_CHANNELS.items():
        if not ch_meta.get('enabled'):
            continue
        results['channels_checked'] += 1
        videos = _fetch_rss_videos(ch_meta)
        for v in videos:
            if v['video_id'] in seen:
                continue
            results['new_videos'] += 1
            r = _process_video(ch_meta, v, ch_meta['name'])
            results['processed'].append(r)
            seen.add(v['video_id'])

    state['seen_videos'] = list(seen)[-300:]
    _save_state(state)

    # Audit
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps({'ts': _now(), **results},
                             ensure_ascii=False) + '\n')

    # Discord-Push wenn neue Videos verarbeitet
    if results['processed']:
        try:
            from discord_dispatcher import send_alert, TIER_LOW
            lines = [f'📺 **YouTube-Auto-Intake** — {len(results["processed"])} neue Videos verarbeitet:']
            for r in results['processed'][:5]:
                lines.append(f"  · '{r.get('title','?')[:80]}' → "
                              f"{r.get('verdict','?')[:80]}")
            send_alert('\n'.join(lines)[:1900], tier=TIER_LOW,
                        category='youtube_intake')
        except Exception: pass

    return results


def main() -> int:
    r = run()
    print(f'═══ YouTube-Transcript-Monitor @ {_now()[:16]} ═══')
    print(f'  Channels checked: {r["channels_checked"]}')
    print(f'  New videos: {r["new_videos"]}')
    if r['channels_checked'] == 0:
        print('  (Keine Channels enabled — siehe SUBSCRIBED_CHANNELS '
              'in scripts/youtube_transcript_monitor.py.\n'
              '   Setze enabled=True und trage echte channel_id ein.)')
    for p in r['processed']:
        print(f"  · {p.get('video_id')} — {p.get('status')} — {p.get('verdict','')[:60]}")
    return 0


if __name__ == '__main__':
    sys.exit(main())

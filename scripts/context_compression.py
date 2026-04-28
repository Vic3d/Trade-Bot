#!/usr/bin/env python3
"""
context_compression.py — Phase 40c: 5-Layer Context Compression (Vibe-inspired).

Spart Token-Cost im Tool-Loop wenn LLM viele Iterationen macht.

5 Schichten (immer in Reihenfolge angewendet, billigste zuerst):
  L1 (microcompact)   — alte tool-results auf [cleared] setzen, neueste 3 behalten
  L2 (collapse)       — lange Texte: head 900 + ... + tail 500, Mitte weg (gratis, kein LLM)
  L3 (auto_summary)   — LLM-Summary von alten Iterationen wenn >40k Token
  L4 (compact_call)   — explizit triggerbar (nicht implementiert hier — wäre Tool-Use)
  L5 (iterative)      — späterer Summary updated früheren statt neu

Alle Layer mutieren `messages` in-place. Estimate-Tokens via len/4 (rough).
"""
from __future__ import annotations

import json
from typing import Any

KEEP_RECENT_TOOL_RESULTS  = 3
COLLAPSE_TEXT_MIN         = 2400
COLLAPSE_HEAD             = 900
COLLAPSE_TAIL             = 500
COLLAPSE_PRESERVE_RECENT  = 4
TOKEN_THRESHOLD_DEFAULT   = 40_000


def estimate_tokens(messages: list) -> int:
    return len(json.dumps(messages, default=str, ensure_ascii=False)) // 4


def microcompact(messages: list) -> int:
    """L1: silently prune old tool results, keep most recent KEEP_RECENT.
    Returns how many were cleared."""
    tool_msgs = [m for m in messages if isinstance(m, dict) and m.get('role') == 'tool']
    if len(tool_msgs) <= KEEP_RECENT_TOOL_RESULTS:
        return 0
    cleared = 0
    for msg in tool_msgs[:-KEEP_RECENT_TOOL_RESULTS]:
        content = msg.get('content', '')
        if isinstance(content, str) and len(content) > 100 and content != '[cleared]':
            msg['content'] = '[cleared]'
            cleared += 1
    return cleared


def context_collapse(messages: list) -> int:
    """L2: fold long text blocks (head + tail). Pure string-op, kein LLM.
    Returns how many were collapsed."""
    if len(messages) <= COLLAPSE_PRESERVE_RECENT + 1:
        return 0
    collapsed = 0
    for msg in messages[1:-COLLAPSE_PRESERVE_RECENT]:
        if not isinstance(msg, dict):
            continue
        content = msg.get('content')
        if not isinstance(content, str) or len(content) <= COLLAPSE_TEXT_MIN:
            continue
        if content == '[cleared]' or '[' in content[:50] and 'collapsed]' in content[-50:]:
            continue
        head = content[:COLLAPSE_HEAD]
        tail = content[-COLLAPSE_TAIL:]
        trimmed = len(content) - COLLAPSE_HEAD - COLLAPSE_TAIL
        msg['content'] = f"{head}\n\n...[{trimmed} chars collapsed]...\n\n{tail}"
        collapsed += 1
    return collapsed


def auto_summary_if_needed(messages: list, summary_fn=None,
                            threshold: int = TOKEN_THRESHOLD_DEFAULT) -> bool:
    """L3: wenn Token-count über threshold, LLM-Summary der frühen Messages.
    summary_fn: callable(text) -> summary_text (z.B. ein call_llm-Wrapper).
    Returns True wenn summary erzeugt wurde."""
    tokens = estimate_tokens(messages)
    if tokens < threshold or summary_fn is None or len(messages) < 10:
        return False

    # Nimm erste Hälfte zum Zusammenfassen, behalte letzte ~4 intakt
    keep_recent = 4
    to_summarize = messages[1:-keep_recent]  # ersten msg (system) bewahren
    if not to_summarize:
        return False

    text = json.dumps(to_summarize, default=str, ensure_ascii=False)[:8000]
    try:
        summary = summary_fn(
            f"Fasse diese Konversations-Historie kompakt zusammen "
            f"(max 500 Wörter, behalte alle wichtigen Decisions + Tool-Results):\n\n{text}"
        )
        # Ersetze die summarized messages durch eine system-message mit summary
        messages[1:-keep_recent] = [{
            'role': 'system',
            'content': f"[KONTEXT-SUMMARY der älteren Iterationen]:\n{summary}",
        }]
        return True
    except Exception:
        return False


def apply_all_layers(messages: list, summary_fn=None,
                      threshold: int = TOKEN_THRESHOLD_DEFAULT) -> dict:
    """Alle 3 implementierten Layer in Reihe. Returns Stats-Dict."""
    tokens_before = estimate_tokens(messages)
    cleared = microcompact(messages)
    collapsed = context_collapse(messages)
    summarized = auto_summary_if_needed(messages, summary_fn, threshold)
    tokens_after = estimate_tokens(messages)
    return {
        'tokens_before': tokens_before,
        'tokens_after': tokens_after,
        'tokens_saved': tokens_before - tokens_after,
        'savings_pct': round((tokens_before - tokens_after) / tokens_before * 100, 1)
                        if tokens_before else 0,
        'cleared_tool_results': cleared,
        'collapsed_messages': collapsed,
        'summarized': summarized,
    }


if __name__ == '__main__':
    # Smoke test
    test_msgs = [
        {'role': 'system', 'content': 'You are CEO.'},
        {'role': 'user', 'content': 'Analyze CCJ ' + 'X'*5000},
        {'role': 'tool', 'content': json.dumps({'sector_data': 'Y'*3000})},
        {'role': 'assistant', 'content': 'Need more data...'},
        {'role': 'tool', 'content': 'Z'*3000},
        {'role': 'tool', 'content': 'A'*3000},
        {'role': 'tool', 'content': 'B'*3000},
        {'role': 'assistant', 'content': 'final decision'},
    ]
    stats = apply_all_layers(test_msgs)
    print(json.dumps(stats, indent=2))

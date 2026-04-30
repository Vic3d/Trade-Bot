"""Test der Tool-Loop end-to-end."""
import sys
sys.path.insert(0, '/opt/trademind/scripts')

from ceo_tools import run_tool_loop, get_tool_definitions_for_prompt

prompt = f"""Du bist Test-CEO. Aufgabe: Analysiere ob NVDA und AMD korreliert sind,
prüfe Sektor-Exposure, dann triff finale Decision: würdest du eine NVDA-Position
von 1500EUR aktuell aufmachen?

{get_tool_definitions_for_prompt()}

Antworte als final_decision mit Format:
{{"final_decision": {{
  "market_assessment": "...",
  "portfolio_assessment": "...",
  "decisions": [
    {{"ticker": "NVDA", "strategy": "TEST", "action": "EXECUTE|SKIP|WATCH",
      "confidence": 0.X, "bull_case": "...", "bear_case": "...",
      "reasoning": "...", "expected_outcome_pct": N,
      "memory_reference": ""}}
  ]
}}}}"""

import time
start = time.time()
result = run_tool_loop(prompt, max_iterations=5, model_hint='sonnet')
elapsed = time.time() - start

print(f'\n=== RESULT (after {elapsed:.1f}s) ===')
import json
print(json.dumps(result, indent=2, default=str)[:3000])

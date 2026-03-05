#!/usr/bin/env python3
"""Test render_conversation.py against all local Claude conversations."""

import os
import re
import subprocess
import sys
import glob

SCRIPT = os.path.join(os.path.dirname(__file__), 'render_conversation.py')
JSONL_ROOT = os.path.expanduser('~/.claude/projects')
OUT_DIR = os.path.expanduser('~/public_html/conversations')

os.makedirs(OUT_DIR, exist_ok=True)

# Find all conversation JSONL files (skip subagent files)
jsonl_files = sorted(
    f for f in glob.glob(f'{JSONL_ROOT}/*/*.jsonl')
    if os.path.getsize(f) > 1024
)

print(f"Found {len(jsonl_files)} conversations to test\n")

passed = 0
failed = 0
errors = []


def check(name, condition, msg):
    if not condition:
        errors.append(f"  FAIL: {name} — {msg}")
        return False
    return True


for jsonl in jsonl_files:
    session_id = os.path.basename(jsonl).replace('.jsonl', '')
    size_mb = os.path.getsize(jsonl) / 1_000_000
    out_html = os.path.join(OUT_DIR, f'{session_id}.html')
    errors.clear()

    # ── Run renderer ──
    result = subprocess.run(
        [sys.executable, SCRIPT, jsonl, out_html],
        capture_output=True, text=True, timeout=300,
    )

    check('exit_code', result.returncode == 0,
          f'exit code {result.returncode}\n{result.stderr[-500:]}')

    if result.returncode != 0:
        failed += 1
        print(f"FAIL {session_id} ({size_mb:.1f}MB) — renderer crashed")
        for e in errors:
            print(e)
        print()
        continue

    if not os.path.exists(out_html):
        failed += 1
        print(f"FAIL {session_id} — no output file")
        continue

    html = open(out_html).read()

    # Parse counts from renderer stdout
    stdout_lines = result.stdout.strip().split('\n')
    stdout_last = stdout_lines[-1] if stdout_lines else ''

    # ── 1. HTML well-formedness: balanced tags ──
    for tag in ['pre', 'code', 'div', 'details', 'span']:
        opens = len(re.findall(f'<{tag}[ >]', html))
        closes = len(re.findall(f'</{tag}>', html))
        check(f'balanced_{tag}', opens == closes,
              f'<{tag}> {opens} opens vs {closes} closes (diff {closes - opens})')

    # ── 2. No leaked backtick fences in markdown-rendered areas ──
    # Only check inside .reply and .turn-user-full divs (markdown output)
    leaked_fences = 0
    for m in re.finditer(r'<div class="(?:reply|turn-user-full)">(.*?)</div>\s*(?=<div|</div>)', html, re.DOTALL):
        block = m.group(1)
        # Strip pre/code content
        stripped = re.sub(r'<pre[^>]*>.*?</pre>', '', block, flags=re.DOTALL)
        stripped = re.sub(r'<code[^>]*>.*?</code>', '', stripped, flags=re.DOTALL)
        stripped = re.sub(r'<[^>]+>', '', stripped)
        leaked_fences += stripped.count('```')
    check('no_leaked_fences', leaked_fences == 0,
          f'{leaked_fences} triple-backtick fences in markdown-rendered text')

    # ── 3. Turn numbering: sequential, no gaps ──
    turn_ids = re.findall(r'id="turn-(\d+)"', html)
    turn_nums = [int(x) for x in turn_ids]
    if turn_nums:
        expected = list(range(1, len(turn_nums) + 1))
        check('turn_sequential', turn_nums == expected,
              f'expected 1..{len(turn_nums)}, got {turn_nums[:5]}..{turn_nums[-3:]}')

    # ── 4. Every turn has an ID ──
    turn_divs = len(re.findall(r'<div class="turn ', html))
    check('turn_ids', turn_divs == len(turn_ids),
          f'{turn_divs} turn divs but {len(turn_ids)} with IDs')

    # ── 5. No empty tool groups ──
    empty_groups = re.findall(r'tools-toggle[^>]*>0 ', html)
    check('no_empty_tool_groups', len(empty_groups) == 0,
          f'{len(empty_groups)} empty tool/output sections with count 0')

    # ── 6. Header counts match actual elements ──
    header_match = re.search(r'<b>(\d+)</b> turns.*?<b>(\d+)</b> tool calls.*?<b>(\d+)</b> compactions', html)
    if header_match:
        header_turns = int(header_match.group(1))
        header_tools = int(header_match.group(2))
        header_compactions = int(header_match.group(3))

        check('header_turn_count', header_turns == len(turn_nums),
              f'header says {header_turns} turns, found {len(turn_nums)}')

        actual_compactions = len(re.findall(r'class="compaction"', html))
        check('header_compaction_count', header_compactions == actual_compactions,
              f'header says {header_compactions}, found {actual_compactions}')

    # ── 7. No double separators (before-gap + gap/compaction adjacency) ──
    double_sep = re.findall(r'class="time-gap".*?class="time-gap"', html[:10000])
    # More useful: check no compaction immediately follows another compaction
    double_compact = len(re.findall(r'class="compaction">\s*\n\s*<div class="compaction"', html))
    check('no_double_compaction', double_compact == 0,
          f'{double_compact} back-to-back compaction lines')

    # ── 8. Diff blocks have content ──
    diff_blocks = re.findall(r'<pre class="diff-block">(.*?)</pre>', html, re.DOTALL)
    empty_diffs = sum(1 for d in diff_blocks if 'diff-add' not in d and 'diff-del' not in d)
    check('diff_blocks_have_content', empty_diffs == 0,
          f'{empty_diffs}/{len(diff_blocks)} diff blocks with no adds or deletes')

    # ── 9. Valid HTML structure ──
    check('has_doctype', html.startswith('<!DOCTYPE html>'), 'missing DOCTYPE')
    check('has_closing_html', '</html>' in html, 'missing </html>')

    # ── 10. Token display sanity ──
    # Non-empty sessions should have cost > $0
    if len(turn_nums) > 1:
        cost_match = re.search(r'\$([0-9.]+)</b> est\. cost', html)
        if cost_match:
            cost = float(cost_match.group(1))
            check('cost_positive', cost > 0,
                  f'session with {len(turn_nums)} turns has $0 cost')

    # ── Report ──
    if errors:
        failed += 1
        print(f"FAIL {session_id} ({size_mb:.1f}MB, {len(turn_nums)} turns)")
        for e in errors:
            print(e)
        print()
    else:
        passed += 1
        print(f"  ok {session_id} ({size_mb:.1f}MB, {len(turn_nums)} turns, {len(diff_blocks)} diffs)")

print(f"\n{'='*60}")
print(f"  {passed} passed, {failed} failed, {passed + failed} total")
if failed == 0:
    print("  All tests passed!")
else:
    sys.exit(1)

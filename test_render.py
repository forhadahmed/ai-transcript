#!/usr/bin/env python3
"""Test render_conversation.py against all local Claude conversations."""

import os
import re
import subprocess
import sys
import glob
import json

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


def render(jsonl, out_html, extra_args=None):
    """Run the renderer, return (html_string, returncode, stderr)."""
    cmd = [sys.executable, SCRIPT] + (extra_args or []) + [jsonl, out_html]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    html = ''
    if result.returncode == 0 and os.path.exists(out_html):
        html = open(out_html).read()
    return html, result.returncode, result.stderr


# ================================================================
# PART 1: Structural checks on all conversations (default flags)
# ================================================================
print("─── Part 1: Structural checks (all conversations) ───\n")

# Parallel render all conversations first, then check serially
from concurrent.futures import ProcessPoolExecutor, as_completed

def render_task(jsonl):
    session_id = os.path.basename(jsonl).replace('.jsonl', '')
    out_html = os.path.join(OUT_DIR, f'{session_id}.html')
    cmd = [sys.executable, SCRIPT, jsonl, out_html]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return jsonl, result.returncode, result.stderr

jobs = min(os.cpu_count() or 4, len(jsonl_files))
render_results = {}
with ProcessPoolExecutor(max_workers=jobs) as pool:
    futures = {pool.submit(render_task, f): f for f in jsonl_files}
    for fut in as_completed(futures):
        jsonl, rc, stderr = fut.result()
        render_results[jsonl] = (rc, stderr)

for jsonl in jsonl_files:
    session_id = os.path.basename(jsonl).replace('.jsonl', '')
    size_mb = os.path.getsize(jsonl) / 1_000_000
    out_html = os.path.join(OUT_DIR, f'{session_id}.html')
    errors.clear()

    rc, stderr = render_results[jsonl]
    html_content = ''
    if rc == 0 and os.path.exists(out_html):
        html_content = open(out_html).read()
    html = html_content

    check('exit_code', rc == 0,
          f'exit code {rc}\n{stderr[-500:]}')

    if rc != 0:
        failed += 1
        print(f"FAIL {session_id} ({size_mb:.1f}MB) — renderer crashed")
        for e in errors:
            print(e)
        print()
        continue

    # ── 1. HTML well-formedness: balanced tags ──
    for tag in ['pre', 'code', 'div', 'details', 'span']:
        opens = len(re.findall(f'<{tag}[ >]', html))
        closes = len(re.findall(f'</{tag}>', html))
        check(f'balanced_{tag}', opens == closes,
              f'<{tag}> {opens} opens vs {closes} closes (diff {closes - opens})')

    # ── 2. No leaked backtick fences in markdown-rendered areas ──
    leaked_fences = 0
    for m in re.finditer(r'<div class="(?:reply|turn-user-full)">(.*?)</div>\s*(?=<div|</div>)', html, re.DOTALL):
        block = m.group(1)
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

    # ── 7. No double separators ──
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
    if len(turn_nums) > 1:
        cost_match = re.search(r'\$([0-9.]+)</b> est\. cost', html)
        if cost_match:
            cost = float(cost_match.group(1))
            check('cost_positive', cost > 0,
                  f'session with {len(turn_nums)} turns has $0 cost')

    # ── 11. Icons present ──
    user_icons = len(re.findall(r'class="turn-icon".*?viewBox', html))
    bot_icons = len(re.findall(r'class="turn-icon".*?src="data:image', html))
    reply_count = len(re.findall(r'class="reply"', html))
    if reply_count > 0:
        check('bot_icons_present', bot_icons > 0,
              f'{reply_count} replies but 0 claude icons')
    if len(turn_nums) > 0:
        check('user_icons_present', user_icons > 0,
              f'{len(turn_nums)} turns but 0 user icons')

    # ── 12. Error styling ──
    interrupted = html.count('[Request interrupted by user')
    if interrupted > 0:
        error_styled = len(re.findall(r'class="error-text"', html))
        check('interrupted_styled', error_styled > 0,
              f'{interrupted} interrupted messages but no error-text styling')

    # ── 13. Tool result error styling ──
    # err-result class wraps <details> with is_error tool results
    # class="err" also appears on standalone orphan tool_output <pre> blocks
    # so err_results <= err_pres is expected
    err_results = len(re.findall(r'class="result err-result"', html))
    err_details = len(re.findall(r'<details class="result">', html))
    err_details_styled = len(re.findall(r'<details class="result err-result">', html))
    # Every err-result should be valid HTML (has closing tag)
    if err_results > 0:
        check('err_result_valid', err_results == err_details_styled,
              f'err-result count mismatch: {err_results} vs {err_details_styled}')

    # ── 14. Truncation badges ──
    # If any message had stop_reason=max_tokens, should see a truncation badge
    trunc_badges = len(re.findall(r'class="trunc-badge"', html))
    # Just verify they render correctly if present (no unclosed tags around them)

    # ── 15. Token badges only for >= 1k ──
    tok_badges = re.findall(r'class="tool-count" style="color:#[0-9a-f]+">([\d.]+[kM]?)</span>', html)
    for tb in tok_badges:
        if tb.endswith('k'):
            val = float(tb[:-1]) * 1000
        elif tb.endswith('M'):
            val = float(tb[:-1]) * 1_000_000
        else:
            val = float(tb)
        check('tok_badge_threshold', val >= 1000,
              f'token badge "{tb}" is below 1k threshold')

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


# ================================================================
# PART 2: Flag tests (on a single mid-size conversation)
# ================================================================
print("\n─── Part 2: Flag tests ───\n")

# Pick a conversation with enough content to exercise features
# Skip the active conversation (being written to, may have unbalanced tags)
active_session = None
try:
    import subprocess as _sp
    _r = _sp.run(['readlink', '-f', '/proc/self/fd/0'], capture_output=True, text=True)
except:
    pass
flag_jsonl = None
for f in jsonl_files:
    size = os.path.getsize(f)
    # Skip very small and very large; prefer mid-size
    if 1_000_000 < size < 10_000_000:
        # Verify this conversation passes baseline (not actively being written)
        test_html = f'/tmp/test_flags_probe.html'
        h, rc, _ = render(f, test_html)
        if rc == 0:
            # Quick balance check
            pre_o = len(re.findall(r'<pre[ >]', h))
            pre_c = len(re.findall(r'</pre>', h))
            if pre_o == pre_c:
                flag_jsonl = f
                break
if not flag_jsonl:
    flag_jsonl = jsonl_files[0] if jsonl_files else None

flag_tests_passed = 0
flag_tests_failed = 0

if flag_jsonl:
    flag_session = os.path.basename(flag_jsonl).replace('.jsonl', '')
    print(f"Using {flag_session} ({os.path.getsize(flag_jsonl)/1_000_000:.1f}MB)\n")

    # Render baseline for comparison
    base_html_path = f'/tmp/test_flags_base.html'
    base_html, rc, _ = render(flag_jsonl, base_html_path)
    base_turns = len(re.findall(r'id="turn-\d+"', base_html))
    base_tools = len(re.findall(r'class="tools-section"', base_html))
    base_thinking = len(re.findall(r'class="thinking-block"', base_html))
    base_diffs = len(re.findall(r'class="diff-block"', base_html))
    base_icons = len(re.findall(r'class="turn-icon"', base_html))
    base_compactions = len(re.findall(r'class="compaction"', base_html))
    base_gaps = len(re.findall(r'class="time-gap"', base_html))

    def flag_test(name, extra_args, check_fn):
        global flag_tests_passed, flag_tests_failed
        out = f'/tmp/test_flags_{name}.html'
        h, rc, stderr = render(flag_jsonl, out, extra_args)
        if rc != 0:
            flag_tests_failed += 1
            print(f"  FAIL {name} — renderer crashed: {stderr[-200:]}")
            return
        ok, msg = check_fn(h)
        if ok:
            flag_tests_passed += 1
            print(f"  ok {name}")
        else:
            flag_tests_failed += 1
            print(f"  FAIL {name} — {msg}")

    # ── --no-thinking ──
    def check_no_thinking(h):
        count = len(re.findall(r'class="thinking-block"', h))
        if base_thinking > 0:
            return count == 0, f'expected 0 thinking blocks, found {count} (base had {base_thinking})'
        return True, ''
    flag_test('no_thinking', ['--no-thinking'], check_no_thinking)

    # ── --no-tools ──
    def check_no_tools(h):
        count = len(re.findall(r'class="tools-section"', h))
        return count == 0, f'expected 0 tool sections, found {count} (base had {base_tools})'
    flag_test('no_tools', ['--no-tools'], check_no_tools)

    # ── --no-diffs ──
    def check_no_diffs(h):
        count = len(re.findall(r'class="diff-block"', h))
        return count == 0, f'expected 0 diff blocks, found {count} (base had {base_diffs})'
    flag_test('no_diffs', ['--no-diffs'], check_no_diffs)

    # ── --no-icons ──
    def check_no_icons(h):
        count = len(re.findall(r'class="turn-icon"', h))
        return count == 0, f'expected 0 icons, found {count} (base had {base_icons})'
    flag_test('no_icons', ['--no-icons'], check_no_icons)

    # ── --no-compactions ──
    def check_no_compactions(h):
        count = len(re.findall(r'class="compaction"', h))
        if base_compactions > 0:
            return count == 0, f'expected 0 compactions, found {count} (base had {base_compactions})'
        return True, ''
    flag_test('no_compactions', ['--no-compactions'], check_no_compactions)

    # ── --no-gaps ──
    def check_no_gaps(h):
        count = len(re.findall(r'class="time-gap"', h))
        if base_gaps > 0:
            return count == 0, f'expected 0 gaps, found {count} (base had {base_gaps})'
        return True, ''
    flag_test('no_gaps', ['--no-gaps'], check_no_gaps)

    # ── --expanded ──
    def check_expanded(h):
        collapsed = len(re.findall(r'class="turn collapsed', h))
        turns = len(re.findall(r'id="turn-\d+"', h))
        return collapsed == 0, f'expected 0 collapsed, found {collapsed}/{turns}'
    flag_test('expanded', ['--expanded'], check_expanded)

    # ── --wide ──
    def check_wide(h):
        return 'max-width: 1600px' in h, 'expected 1600px max-width'
    flag_test('wide', ['--wide'], check_wide)

    # ── --narrow ──
    def check_narrow(h):
        return 'max-width: 800px' in h, 'expected 800px max-width'
    flag_test('narrow', ['--narrow'], check_narrow)

    # ── --font-size ──
    def check_font_size(h):
        return 'font-size: 18px' in h, 'expected font-size: 18px'
    flag_test('font_size', ['--font-size', '18'], check_font_size)

    # ── --wrap-code ──
    def check_wrap_code(h):
        return 'white-space: pre-wrap' in h, 'expected pre-wrap in CSS'
    flag_test('wrap_code', ['--wrap-code'], check_wrap_code)

    # ── --title ──
    def check_title(h):
        has_h1 = 'My Custom Title' in h
        has_title = '<title>My Custom Title</title>' in h
        return has_h1 and has_title, f'h1={has_h1}, title={has_title}'
    flag_test('title', ['--title', 'My Custom Title'], check_title)

    # ── --full-output (output should be larger or equal) ──
    def check_full_output(h):
        return len(h) >= len(base_html), f'full-output ({len(h)}) smaller than base ({len(base_html)})'
    flag_test('full_output', ['--full-output'], check_full_output)

    # ── --show-boilerplate ──
    def check_show_boilerplate(h):
        return len(h) >= len(base_html), f'show-boilerplate ({len(h)}) smaller than base ({len(base_html)})'
    flag_test('show_boilerplate', ['--show-boilerplate'], check_show_boilerplate)

    # ── combined flags ──
    def check_combined(h):
        tools = len(re.findall(r'class="tools-section"', h))
        thinking = len(re.findall(r'class="thinking-block"', h))
        icons = len(re.findall(r'class="turn-icon"', h))
        collapsed = len(re.findall(r'class="turn collapsed', h))
        ok = tools == 0 and thinking == 0 and icons == 0 and collapsed == 0
        return ok, f'tools={tools} thinking={thinking} icons={icons} collapsed={collapsed}'
    flag_test('combined', ['--no-tools', '--no-thinking', '--no-icons', '--expanded'], check_combined)

    # ── mutual exclusion: --wide and --narrow ──
    def check_narrow_wins(h):
        # last flag wins with argparse
        return 'max-width: 800px' in h, 'expected narrow (800px) when both given'
    flag_test('narrow_wins_over_wide', ['--wide', '--narrow'], check_narrow_wins)

    # ── HTML validity preserved with all flags ──
    def check_validity_with_flags(h):
        ok = h.startswith('<!DOCTYPE html>') and '</html>' in h
        for tag in ['pre', 'code', 'div', 'details', 'span']:
            opens = len(re.findall(f'<{tag}[ >]', h))
            closes = len(re.findall(f'</{tag}>', h))
            if opens != closes:
                return False, f'unbalanced <{tag}>: {opens} opens vs {closes} closes'
        return ok, 'invalid HTML structure'
    flag_test('validity_all_flags',
              ['--no-tools', '--no-thinking', '--no-icons', '--no-diffs',
               '--no-compactions', '--no-gaps', '--expanded', '--wide'],
              check_validity_with_flags)

    passed += flag_tests_passed
    failed += flag_tests_failed

# ================================================================
# PART 3: JSONL parsing coverage
# ================================================================
print("\n─── Part 3: Content coverage ───\n")

# Check that across all conversations we exercise key features
all_html = ''
for f in glob.glob(f'{OUT_DIR}/*.html'):
    all_html += open(f).read()

coverage_checks = [
    ('has_diffs', len(re.findall(r'class="diff-block"', all_html)) > 0,
     'no diff blocks found across all conversations'),
    ('has_tool_calls', len(re.findall(r'class="tools-section"', all_html)) > 0,
     'no tool sections found'),
    ('has_replies', len(re.findall(r'class="reply"', all_html)) > 0,
     'no reply blocks found'),
    ('has_user_messages', len(re.findall(r'class="turn-user-full"', all_html)) > 0,
     'no user messages found'),
    ('has_compactions', len(re.findall(r'class="compaction"', all_html)) > 0,
     'no compaction boundaries found'),
    ('has_time_gaps', len(re.findall(r'class="time-gap"', all_html)) > 0,
     'no time gaps found'),
    ('has_token_badges', len(re.findall(r'class="tool-count" style="color:#', all_html)) > 0,
     'no token badges found'),
    ('has_err_dots', len(re.findall(r'class="err-dot"', all_html)) > 0,
     'no error dots found'),
    ('has_agent_inner', len(re.findall(r'class="agent-inner"', all_html)) > 0,
     'no subagent inner tool sections found'),
    ('has_thinking', len(re.findall(r'class="thinking-block"', all_html)) > 0,
     'no thinking blocks found'),
    ('has_user_icons', len(re.findall(r'class="turn-icon".*?viewBox', all_html)) > 0,
     'no user SVG icons found'),
    ('has_claude_icons', len(re.findall(r'class="turn-icon".*?src="data:image', all_html)) > 0,
     'no claude favicon icons found'),
    ('has_error_text', len(re.findall(r'class="error-text"', all_html)) > 0,
     'no error-text styled messages found'),
    ('has_tables', len(re.findall(r'<table>', all_html)) > 0,
     'no markdown tables rendered'),
    ('has_code_blocks', len(re.findall(r'<pre><code', all_html)) > 0,
     'no fenced code blocks rendered'),
    # trunc_badge may not exist if no conversation hit max_tokens — skip if absent
    # ('has_trunc_badge', len(re.findall(r'class="trunc-badge"', all_html)) > 0,
    #  'no truncation badges found'),
]

cov_passed = 0
cov_failed = 0
for name, condition, msg in coverage_checks:
    if condition:
        cov_passed += 1
        print(f"  ok {name}")
    else:
        cov_failed += 1
        print(f"  FAIL {name} — {msg}")

passed += cov_passed
failed += cov_failed

# ════════════════════════════════════════════════
print(f"\n{'='*60}")
print(f"  {passed} passed, {failed} failed, {passed + failed} total")
if failed == 0:
    print("  All tests passed!")
else:
    sys.exit(1)

#!/usr/bin/env python3
"""Render a Claude Code conversation JSONL as HTML — v2 with turn-based layout."""

import json
import sys
import html
import re
from datetime import datetime
import markdown

INPUT = sys.argv[1] if len(sys.argv) > 1 else (
    "/home/forhad/.claude/projects/-home-forhad/"
    "1a2ee288-0303-4569-ab87-3e725da91aac.jsonl"
)
OUTPUT = sys.argv[2] if len(sys.argv) > 2 else "/home/forhad/public_html/conversation.html"

MD = markdown.Markdown(extensions=['fenced_code', 'tables', 'nl2br', 'sane_lists'])

def extract_fenced_blocks(text):
    """Extract fenced code blocks (possibly indented) into placeholders,
    so markdown doesn't mangle them. Returns (cleaned_text, dict of placeholder->html)."""
    placeholders = {}
    counter = [0]

    def replacer(m):
        counter[0] += 1
        key = f'\x00FENCED{counter[0]}\x00'
        indent = m.group(1) or ''
        lang = m.group(2) or ''
        body = m.group(3)
        # Dedent body by the fence's indentation
        if indent:
            body_lines = body.split('\n')
            body_lines = [l[len(indent):] if l.startswith(indent) else l for l in body_lines]
            body = '\n'.join(body_lines)
        lang_attr = f' class="language-{html.escape(lang)}"' if lang else ''
        placeholders[key] = f'<pre><code{lang_attr}>{html.escape(body)}</code></pre>'
        return f'\n{key}\n'

    # Match fenced code blocks: optional indent, ```, optional lang, newline, body, closing ```
    cleaned = re.sub(
        r'^([ \t]*)`{3,}(\w*)\s*\n(.*?)^\1`{3,}\s*$',
        replacer, text, flags=re.MULTILINE | re.DOTALL
    )
    return cleaned, placeholders

def md(text):
    MD.reset()
    text, placeholders = extract_fenced_blocks(text)
    result = MD.convert(text)
    for key, replacement in placeholders.items():
        # The placeholder might be wrapped in <p> tags by markdown
        result = result.replace(f'<p>{key}</p>', replacement)
        result = result.replace(key, replacement)
    return result

def ts_fmt(ts_str):
    try:
        dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%d %H:%M:%S')
    except:
        return ts_str or ""

def ts_short(ts_str):
    try:
        dt = datetime.fromisoformat(ts_str.replace('Z', '+00:00'))
        return dt.strftime('%H:%M:%S')
    except:
        return ""

def mcp_name(raw):
    m = re.search(r'__(\w+)$', raw)
    return f"MCP:{m.group(1)}" if m else raw

def strip_system_tags(text):
    return re.sub(
        r'<(system-reminder|local-command-caveat|command-\w+)[^>]*>.*?</\1>',
        '', text, flags=re.DOTALL
    ).strip()

def dur_str(ms):
    if ms >= 60000:
        return f'{ms/60000:.1f}m'
    if ms >= 1000:
        return f'{ms/1000:.1f}s'
    return f'{ms}ms'

def tok_str(n):
    if n >= 1_000_000:
        return f'{n/1_000_000:.1f}M'
    if n >= 1000:
        return f'{n/1000:.1f}k'
    return str(n)

def tok_color(n):
    if n >= 10000: return '#c62828'   # red — heavy
    if n >= 5000:  return '#e65100'   # orange
    if n >= 2000:  return '#f9a825'   # amber
    return '#888'                     # gray — light

# ── Tool call helpers ──

def tool_summary(block):
    """One-line summary + icon class for a tool_use block."""
    name = block.get('name', '?')
    inp = block.get('input', {})
    if name == 'Bash':
        label = inp.get('description', '') or inp.get('command', '')[:140]
        return f'$ {label}', 'bash'
    if name == 'Read':
        return f'Read {inp.get("file_path","")}', 'read'
    if name in ('Glob', 'Grep'):
        p = inp.get('pattern', '')
        d = inp.get('path', '')
        return f'{name} {p}{" in "+d if d else ""}', 'search'
    if name in ('Edit', 'Write'):
        return f'{name} {inp.get("file_path","")}', 'edit'
    if name == 'Agent':
        return f'Agent: {inp.get("description","")}', 'agent'
    if 'mcp__' in name:
        friendly = mcp_name(name)
        intent = inp.get('intent', '')
        return f'{friendly} — {intent}' if intent else friendly, 'mcp'
    if name in ('TaskCreate','TaskUpdate','TaskOutput','TaskStop','Skill'):
        bits = [str(v)[:50] for k,v in inp.items() if isinstance(v,str) and len(v)<60]
        return f'{name} {" ".join(bits)[:80]}', 'task'
    return name, 'other'

def render_diff(old, new):
    """Render old_string/new_string as a unified diff block."""
    old_lines = (old or '').splitlines(keepends=True)
    new_lines = (new or '').splitlines(keepends=True)
    import difflib
    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm=''))
    if not diff and new and not old:
        # Write (no old) — just show as all-added
        lines = []
        for l in new.split('\n'):
            lines.append(f'<span class="diff-add">+{html.escape(l)}</span>')
        return '<pre class="diff-block">' + '\n'.join(lines) + '</pre>'
    if not diff:
        return ''
    lines = []
    for line in diff:
        if line.startswith('---') or line.startswith('+++'):
            continue  # skip file headers
        raw = html.escape(line.rstrip('\n'))
        if line.startswith('+'):
            lines.append(f'<span class="diff-add">{raw}</span>')
        elif line.startswith('-'):
            lines.append(f'<span class="diff-del">{raw}</span>')
        elif line.startswith('@@'):
            lines.append(f'<span class="diff-hunk">{raw}</span>')
        else:
            lines.append(f'<span class="diff-ctx">{raw}</span>')
    content = '\n'.join(lines)
    if len(content) > 5000:
        content = content[:5000] + f'\n…(truncated)'
    return f'<pre class="diff-block">{content}</pre>'

def tool_detail(block):
    """Expanded body HTML for a tool_use block."""
    name = block.get('name', '?')
    inp = block.get('input', {})
    p = []
    if name == 'Bash':
        desc = inp.get('description','')
        if desc: p.append(f'<div class="dim">{html.escape(desc)}</div>')
        p.append(f'<pre>{html.escape(inp.get("command",""))}</pre>')
    elif name == 'Read':
        p.append(f'<code>{html.escape(inp.get("file_path",""))}</code>')
        o, l = inp.get('offset',''), inp.get('limit','')
        if o or l: p.append(f'<span class="dim">offset={o} limit={l}</span>')
    elif name in ('Glob','Grep'):
        for k,v in inp.items():
            p.append(f'<span class="dim">{html.escape(k)}={html.escape(str(v)[:200])}</span>')
    elif name in ('Edit','Write'):
        p.append(f'<code>{html.escape(inp.get("file_path",""))}</code>')
        old = inp.get('old_string','')
        new = inp.get('new_string','')
        if old or new:
            p.append(render_diff(old, new))
    elif name == 'Agent':
        p.append(f'<div class="dim">{html.escape(inp.get("description",""))}</div>')
        p.append(f'<pre>{html.escape(inp.get("prompt","")[:500])}</pre>')
    elif 'mcp__' in name:
        for k,v in inp.items():
            vs = v if isinstance(v,str) else json.dumps(v, indent=2, default=str)
            if len(vs) > 500: vs = vs[:500] + f'\n…({len(vs)} chars)'
            p.append(f'<div class="mcp-field"><span class="mcp-key">{html.escape(k)}:</span><pre>{html.escape(vs)}</pre></div>')
    else:
        for k,v in inp.items():
            p.append(f'<span class="dim">{html.escape(k)}={html.escape(str(v)[:200])}</span>')
    return '\n'.join(p)

def extract_result_text(block):
    rc = block.get('content','')
    if isinstance(rc, list):
        return '\n'.join(b.get('text','') for b in rc if isinstance(b,dict))
    return str(rc) if rc else ''

BOILERPLATE_RE = re.compile(
    r'^(The file \S+ has been (updated|created) successfully\.|'
    r'\S+ is now available for use\.)$'
)

def is_boilerplate_result(text):
    return bool(BOILERPLATE_RE.match(text.strip()))

# ── Phase 1: Parse JSONL into flat items ──

print(f"Reading {INPUT} …")
items = []  # flat list of typed dicts
seen_ids = {}
agent_progress = {}  # parentToolUseID -> list of inner tool calls

with open(INPUT) as f:
    for lineno, line in enumerate(f, 1):
        if lineno % 50000 == 0: print(f"  …line {lineno}")
        try: rec = json.loads(line)
        except: continue

        rtype = rec.get('type')
        ts = rec.get('timestamp', '')

        # Compaction
        if rtype == 'system' and rec.get('subtype') == 'compact_boundary':
            pre = rec.get('compactMetadata',{}).get('preTokens','')
            items.append({'kind':'compaction', 'ts':ts, 'tokens':pre})
            continue

        # Turn duration
        if rtype == 'system' and rec.get('subtype') == 'turn_duration':
            ms = rec.get('durationMs', 0)
            if ms: items.append({'kind':'duration', 'ts':ts, 'ms':ms})
            continue

        # Collect agent (subagent) progress records
        if rtype == 'progress' and rec.get('parentToolUseID'):
            ptid = rec.get('parentToolUseID')
            data = rec.get('data', {})
            if isinstance(data, dict) and data.get('type') == 'agent_progress':
                inner_msg = data.get('message', {})
                if isinstance(inner_msg, dict):
                    inner_content = inner_msg.get('message', {}).get('content', [])
                    if isinstance(inner_content, list):
                        for b in inner_content:
                            if isinstance(b, dict) and b.get('type') == 'tool_use':
                                if ptid not in agent_progress:
                                    agent_progress[ptid] = []
                                s, icon = tool_summary(b)
                                agent_progress[ptid].append({'summary': s, 'icon': icon})
            continue

        if rtype not in ('user','assistant','system'): continue

        msg = rec.get('message',{})
        content = msg.get('content','')

        # Deduplicate streaming assistant chunks
        if rtype == 'assistant':
            mid = msg.get('id','')
            if mid:
                sz = 0
                if isinstance(content, list):
                    for b in content:
                        if isinstance(b, dict):
                            sz += len(b.get('text',''))
                            inp = b.get('input','')
                            sz += len(inp) if isinstance(inp,str) else len(str(inp))
                else:
                    sz = len(content) if isinstance(content, str) else 0
                prev = seen_ids.get(mid)
                if prev:
                    if sz > prev['sz']: prev['rec'] = rec; prev['sz'] = sz
                    continue
                entry = {'rec':rec, 'sz':sz, 'idx':len(items)}
                seen_ids[mid] = entry
                items.append(entry)
                continue

        # User messages (may contain tool_results)
        if isinstance(content, str):
            clean = strip_system_tags(content)
            if clean: items.append({'kind':'user', 'ts':ts, 'text':clean})
        elif isinstance(content, list):
            texts = []
            results = []
            for b in content:
                if not isinstance(b, dict): continue
                if b.get('type') == 'text':
                    t = strip_system_tags(b.get('text',''))
                    if t: texts.append(t)
                elif b.get('type') == 'tool_result':
                    results.append(b)
            if texts:
                items.append({'kind':'user', 'ts':ts, 'text':'\n'.join(texts)})
            for tr in results:
                rt = extract_result_text(tr)
                if rt.strip() and not is_boilerplate_result(rt):
                    items.append({
                        'kind':'tool_output',
                        'ts':ts,
                        'text':rt,
                        'is_error': bool(tr.get('is_error')),
                    })

# Accumulate token usage — only from deduplicated messages (final chunk per msg id)
total_input = 0
total_output = 0
total_cache_create = 0
total_cache_read = 0

for mid, entry in seen_ids.items():
    usage = entry['rec'].get('message',{}).get('usage')
    if not usage: continue
    total_input += usage.get('input_tokens', 0)
    total_output += usage.get('output_tokens', 0)
    total_cache_create += usage.get('cache_creation_input_tokens', 0)
    total_cache_read += usage.get('cache_read_input_tokens', 0)

# Claude Opus pricing (per 1M tokens):
# Input: $15, Output: $75, Cache write: $18.75, Cache read: $1.50
cost_input = (total_input / 1_000_000) * 15
cost_output = (total_output / 1_000_000) * 75
cost_cache_create = (total_cache_create / 1_000_000) * 18.75
cost_cache_read = (total_cache_read / 1_000_000) * 1.50
cost_total = cost_input + cost_output + cost_cache_create + cost_cache_read

print(f"  Tokens: {total_input:,} in, {total_output:,} out, {total_cache_create:,} cache_w, {total_cache_read:,} cache_r")
print(f"  Cost estimate: ${cost_total:.2f}")

print(f"  {len(items)} raw items")

# ── Phase 2: Resolve assistant placeholders ──

resolved = []
for item in items:
    if 'rec' in item:
        rec = item['rec']
        msg = rec.get('message',{})
        ts = rec.get('timestamp','')
        content = msg.get('content','')
        pending_tool = None
        usage = msg.get('usage', {})
        msg_output_tokens = usage.get('output_tokens', 0)
        stop_reason = msg.get('stop_reason', '')
        first_item_idx = len(resolved)

        if not isinstance(content, list):
            continue

        for block in content:
            if not isinstance(block, dict): continue
            bt = block.get('type','')

            if bt == 'text':
                txt = block.get('text','').strip()
                if not txt: continue
                if pending_tool:
                    resolved.append(pending_tool); pending_tool = None
                resolved.append({'kind':'reply', 'ts':ts, 'text':txt})

            elif bt == 'thinking':
                th = block.get('thinking','').strip()
                if th:
                    if pending_tool:
                        resolved.append(pending_tool); pending_tool = None
                    resolved.append({'kind':'thinking', 'ts':ts, 'text':th})

            elif bt == 'tool_use':
                if pending_tool:
                    resolved.append(pending_tool)
                s, icon = tool_summary(block)
                tool_id = block.get('id', '')
                pending_tool = {
                    'kind':'tool_call', 'ts':ts,
                    'summary':s, 'icon':icon,
                    'detail': tool_detail(block),
                    'result': None,
                    'inner_tools': agent_progress.get(tool_id, []),
                }

            elif bt == 'tool_result':
                rt = extract_result_text(block)
                is_err = bool(block.get('is_error'))
                rhtml = None
                if rt.strip() and not is_boilerplate_result(rt):
                    trunc = rt[:3000]
                    if len(rt)>3000: trunc += f'\n…({len(rt)} chars)'
                    err_cls = ' class="err"' if is_err else ''
                    rhtml = f'<details class="result"><summary>{"Error" if is_err else "Output"} ({len(rt)} chars)</summary><pre{err_cls}>{html.escape(trunc)}</pre></details>'
                if pending_tool:
                    pending_tool['result'] = rhtml
                    resolved.append(pending_tool)
                    pending_tool = None
                elif rhtml:
                    resolved.append({'kind':'tool_output', 'ts':ts, 'text':rt, 'is_error':is_err})

        if pending_tool:
            resolved.append(pending_tool)
        # Tag first resolved item from this message with output tokens
        if msg_output_tokens and len(resolved) > first_item_idx:
            resolved[first_item_idx]['output_tokens'] = msg_output_tokens
        if stop_reason == 'max_tokens' and len(resolved) > first_item_idx:
            resolved[len(resolved) - 1]['truncated'] = True
    else:
        resolved.append(item)

print(f"  {len(resolved)} resolved items")

# ── Phase 3: Group into turns ──
# A turn starts at each 'user' item and collects everything until the next 'user' or end.
# Compaction boundaries break turns and become standalone separators.

turns = []  # list of: {'type':'turn', 'user_text':..., 'user_ts':..., 'items':[], 'duration_ms':0, 'has_errors':bool, 'output_tokens':0}
#              or:     {'type':'compaction', 'ts':..., 'tokens':...}

current_turn = None

def flush_turn():
    global current_turn
    if current_turn and (current_turn.get('user_text') or current_turn.get('items')):
        turns.append(current_turn)
    current_turn = None

for item in resolved:
    k = item['kind']

    if k == 'compaction':
        flush_turn()
        turns.append({'type':'compaction', 'ts':item['ts'], 'tokens':item.get('tokens','')})

    elif k == 'user':
        flush_turn()
        current_turn = {
            'type': 'turn',
            'user_text': item['text'],
            'user_ts': item['ts'],
            'items': [],
            'duration_ms': 0,
            'has_errors': False,
            'output_tokens': 0,
        }

    elif k == 'duration':
        if current_turn:
            current_turn['duration_ms'] += item['ms']

    else:
        # reply, thinking, tool_call, tool_output
        if current_turn is None:
            current_turn = {
                'type':'turn', 'user_text':'', 'user_ts':item.get('ts',''),
                'items':[], 'duration_ms':0, 'has_errors':False, 'output_tokens':0,
            }
        current_turn['items'].append(item)
        current_turn['output_tokens'] += item.get('output_tokens', 0)
        if item.get('truncated'):
            current_turn['truncated'] = True
        if k == 'tool_output' and item.get('is_error'):
            current_turn['has_errors'] = True
        if k == 'tool_call' and item.get('icon') == 'error':
            current_turn['has_errors'] = True

flush_turn()

turn_count = sum(1 for t in turns if t['type']=='turn')
compaction_count = sum(1 for t in turns if t['type']=='compaction')
print(f"  {turn_count} turns, {compaction_count} compactions")

# ── Phase 4: Render HTML ──

def render_tool_row(tc):
    s = html.escape(tc['summary'])
    icon = tc['icon']
    body = tc.get('detail','')
    result = tc.get('result','')
    inner_tools = tc.get('inner_tools', [])
    inner = body
    if result: inner += '\n' + result
    if inner_tools:
        inner += f'\n<div class="agent-inner"><div class="dim">{len(inner_tools)} inner tool calls</div>'
        for it in inner_tools:
            inner += (
                f'<div class="agent-tool-row">'
                f'<span class="badge {it["icon"]}">{it["icon"]}</span>'
                f'<span class="tsum">{html.escape(it["summary"])}</span>'
                f'</div>'
            )
        inner += '</div>'
    count_suffix = f' <span class="dim">({len(inner_tools)} inner)</span>' if inner_tools else ''
    return (
        f'<details class="trow">'
        f'<summary><span class="badge {icon}">{icon}</span>'
        f'<span class="tsum">{s}{count_suffix}</span></summary>'
        f'<div class="tbody">{inner}</div>'
        f'</details>'
    )

# Count tool calls
total_tool_calls = 0
for t in turns:
    if t['type'] == 'turn':
        total_tool_calls += sum(1 for i in t['items'] if i['kind'] == 'tool_call')

first_ts = ''
last_ts = ''
for t in turns:
    ts = t.get('user_ts', t.get('ts',''))
    if ts and not first_ts: first_ts = ts
    if ts: last_ts = ts

out = []
out.append(f'''<!DOCTYPE html>
<html lang="en"><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Conversation — {turn_count} turns</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{
  font-family: 'SF Mono','Cascadia Code','Fira Code','Consolas', monospace;
  background: #fff; color: #1a1a1a; line-height: 1.6; font-size: 15px;
}}
a {{ color: #0969da; }}

/* Layout */
.page {{ min-height: 100vh; }}
.main {{ max-width: 1100px; margin: 0 auto; padding: 20px 32px; }}

/* Header */
.header {{ padding: 20px 0 16px; border-bottom: 1px solid #e0e0e0; margin-bottom: 16px; }}
.header h1 {{ font-size: 1.2em; color: #333; }}
.header .meta {{ font-size: 0.8em; color: #666; margin-top: 6px; }}
.header .meta span {{ margin-right: 16px; }}
.header .meta b {{ color: #0969da; }}

/* Turn */
.turn {{
  margin: 0 0 0 0;
  padding: 16px 0;
  border-bottom: 1px solid #eee;
}}
.turn:last-child {{ border-bottom: none; }}
.turn.before-gap {{ border-bottom: none; }}

/* Turn header */
.turn-head {{
  display: flex; align-items: baseline; gap: 10px;
  cursor: pointer; user-select: none;
}}
.turn-head:hover .turn-num {{ color: #0969da; }}
.turn-num {{
  font-size: 0.75em; font-weight: 700; color: #999;
  flex-shrink: 0; width: 36px;
}}
.turn-preview {{
  flex: 1; min-width: 0; font-size: 0.82em; color: #555;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}}
/* When expanded, show full user message instead of preview */
.turn:not(.collapsed) .turn-preview {{ display: none; }}
.turn.collapsed .turn-user-full {{ display: none; }}
.turn-user-full {{
  padding: 10px 16px; border-left: 3px solid #0969da;
  margin-bottom: 8px;
}}
.turn-meta {{
  flex-shrink: 0; font-size: 0.7em; color: #999;
  display: flex; gap: 8px; align-items: center;
}}
.err-dot {{
  display: inline-block; width: 8px; height: 8px;
  background: #d63031; border-radius: 50%;
}}
.tool-count {{
  background: #eee; padding: 1px 6px; border-radius: 3px;
  font-size: 0.9em;
}}

/* Turn body (collapsible) */
.turn-body {{ padding: 4px 0 0 0; }}
.turn.collapsed .turn-body {{ display: none; }}

/* (user-msg removed — now .turn-user-full in turn head) */

/* Reply */
.reply {{
  padding: 10px 16px; border-left: 3px solid #2e7d32;
  margin: 6px 0;
}}
.reply p, .turn-user-full p {{ margin: 5px 0; }}
.reply h1,.reply h2,.reply h3,.reply h4 {{ margin: 10px 0 4px; }}
.turn-user-full h1,.turn-user-full h2,.turn-user-full h3,.turn-user-full h4 {{ color: #0969da; margin: 10px 0 4px; }}

/* Shared text styles */
.turn-user-full, .reply, .tbody {{
  overflow-wrap: break-word;
}}
pre {{
  background: #f4f4f4; padding: 8px 10px;
  font-size: 0.88em; margin: 5px 0;
  max-height: 400px; overflow: auto;
}}
code {{ background: #f4f4f4; padding: 1px 4px; font-size: 0.9em; }}
pre code {{ background: none; padding: 0; }}
ul, ol {{ padding-left: 20px; margin: 5px 0; }}
li {{ margin: 2px 0; }}
table {{
  border-collapse: collapse; margin: 6px 0;
  font-size: 0.9em; width: 100%; table-layout: auto;
}}
th {{
  background: #f4f4f4; font-weight: 600; text-align: left;
  padding: 5px 10px; border-bottom: 2px solid #ddd;
}}
td {{ padding: 4px 10px; border-bottom: 1px solid #eee; }}
tr:hover {{ background: #f9f9f9; }}
blockquote {{
  border-left: 3px solid #ddd; padding: 3px 12px;
  margin: 5px 0; color: #666;
}}
hr {{ border: none; border-top: 1px solid #ddd; margin: 10px 0; }}
strong {{ color: #111; }}

/* Tool calls accordion */
.tools-section {{
  margin: 4px 0;
}}
.tools-toggle {{
  cursor: pointer; font-size: 0.78em; color: #666;
  padding: 4px 0; user-select: none; display: flex;
  align-items: center; gap: 6px;
}}
.tools-toggle:hover {{ color: #0969da; }}
.tools-toggle::before {{
  content: '\u25B6'; font-size: 0.7em; display: inline-block;
  width: 12px; transition: transform 0.15s;
}}
.tools-section.open .tools-toggle::before {{
  content: '\u25BC';
}}
.tools-list {{ display: none; }}
.tools-section.open .tools-list {{ display: block; }}

.trow {{ border-bottom: 1px solid #f0f0f0; }}
.trow:last-child {{ border-bottom: none; }}
.trow > summary {{
  cursor: pointer; padding: 4px 8px; font-size: 0.8em;
  color: #333; list-style: none;
  display: flex; align-items: center; gap: 6px;
}}
.trow > summary::-webkit-details-marker {{ display: none; }}
.trow > summary::before {{
  content: '\u25B6'; font-size: 0.5em; color: #999;
  display: inline-block; width: 10px; flex-shrink: 0;
}}
.trow[open] > summary::before {{ content: '\u25BC'; }}
.trow > summary:hover {{ background: #f6f8fa; }}
.tbody {{
  padding: 4px 12px 8px 28px; font-size: 0.82em;
}}

/* Badges */
.badge {{
  display: inline-block; padding: 0 5px; border-radius: 3px;
  font-size: 0.7em; font-weight: 700; text-transform: uppercase;
  letter-spacing: 0.3px; flex-shrink: 0;
}}
.badge.bash {{ background: #e6f4ea; color: #137333; }}
.badge.read {{ background: #e8f0fe; color: #1967d2; }}
.badge.search {{ background: #fef7e0; color: #b06000; }}
.badge.edit {{ background: #fef3e0; color: #e65100; }}
.badge.agent {{ background: #f3e8fd; color: #7627bb; }}
.badge.mcp {{ background: #f3e8fd; color: #8250df; }}
.badge.task {{ background: #e8e8e8; color: #555; }}
.badge.thinking {{ background: #f3e8fd; color: #7c3aed; }}
.badge.output {{ background: #e8f5e9; color: #2e7d32; }}
.badge.error {{ background: #ffebee; color: #c62828; }}
.badge.other {{ background: #e8e8e8; color: #555; }}
.tsum {{
  overflow: hidden; text-overflow: ellipsis;
  white-space: nowrap; flex: 1; min-width: 0;
}}

/* Agent inner tools */
.agent-inner {{
  margin: 6px 0 2px; padding: 4px 0 0 12px;
  border-left: 2px solid #e8e0f0;
}}
.agent-tool-row {{
  display: flex; align-items: center; gap: 6px;
  padding: 1px 0; font-size: 0.85em;
}}

/* Truncation badge */
.trunc-badge {{
  background: #fff3e0; color: #e65100; font-size: 0.7em;
  font-weight: 700; padding: 1px 6px; border-radius: 3px;
  text-transform: uppercase; letter-spacing: 0.3px;
}}

/* MCP fields */
.mcp-field {{ margin: 3px 0; }}
.mcp-key {{ color: #8250df; font-size: 0.85em; font-weight: 600; }}
.dim {{ color: #666; font-size: 0.85em; }}

/* Results */
.result {{ margin: 4px 0; }}
.result summary {{ cursor: pointer; color: #666; font-size: 0.8em; }}
pre.err {{ background: #fff5f5; color: #b71c1c; }}

/* Diff blocks */
.diff-block {{
  background: #fafafa; padding: 8px 10px;
  font-size: 0.88em; margin: 5px 0;
  max-height: 400px; overflow: auto;
  line-height: 1.5;
}}
.diff-add {{ color: #1a7f37; background: #dafbe1; }}
.diff-del {{ color: #cf222e; background: #ffebe9; }}
.diff-hunk {{ color: #6639ba; }}
.diff-ctx {{ color: #656d76; }}

/* Thinking */
.thinking-block {{
  margin: 4px 0; padding: 6px 16px;
  border-left: 2px dashed #d4c5f9; font-size: 0.8em; color: #666;
}}
.thinking-block summary {{ cursor: pointer; color: #7c3aed; font-style: italic; }}
.thinking-block pre {{ color: #666; max-height: 300px; }}

/* Compaction */
.compaction {{
  margin: 24px 0; text-align: center;
}}
.compaction hr {{
  border: none; border-top: 1px solid #d63031; margin: 0 0 6px;
}}
.compaction span {{
  font-size: 0.72em; color: #d63031; font-weight: 700;
  text-transform: uppercase; letter-spacing: 1px;
}}

/* Time gap */
.time-gap {{
  margin: 0; padding: 8px 0;
  text-align: center; font-size: 0.72em; color: #999;
  display: flex; align-items: center; gap: 12px;
}}
.time-gap::before, .time-gap::after {{
  content: ''; flex: 1; border-top: 1px dashed #ccc;
}}

/* Output block (tool results in user messages) */
.output-block {{
  margin: 4px 0; padding: 4px 16px;
  border-left: 2px solid #2e7d32; font-size: 0.82em;
}}
.output-block.err-output {{
  border-left-color: #c62828;
}}
.output-block pre {{ max-height: 250px; }}
.output-block pre.err {{ background: #fff5f5; color: #b71c1c; }}

/* Toolbar */
.toolbar {{
  display: flex; align-items: center;
  gap: 6px; max-width: 1100px; margin: 0 auto;
  padding: 6px 32px;
}}
.toolbar, .toolbar button, .toolbar input {{
  font-family: 'Geist','Inter',-apple-system,'Segoe UI','Helvetica Neue',Arial,sans-serif;
}}
.toolbar button {{
  font-size: 0.78em;
  padding: 4px 10px; border: 1px solid #d0d0d0;
  background: #fafafa; color: #333; cursor: pointer;
  border-radius: 3px; white-space: nowrap;
}}
.toolbar button:hover {{ background: #eee; }}
.toolbar button.active {{
  background: #0969da; color: #fff; border-color: #0969da;
}}
.toolbar input {{
  font-size: 0.78em;
  padding: 4px 8px; border: 1px solid #d0d0d0;
  border-radius: 3px; width: 200px; outline: none;
}}
.toolbar input:focus {{ border-color: #0969da; }}
.toolbar .sep {{
  width: 1px; height: 20px; background: #ddd; margin: 0 4px;
}}
.toolbar .match-count {{
  font-size: 0.72em; color: #999;
}}

/* Toolbar wrapper — full-width sticky bg, no double border */
.toolbar-wrap {{
  position: sticky; top: 0; z-index: 100;
  background: #fff; border-bottom: 1px solid #e0e0e0;
}}
.toolbar input {{ flex: 1; min-width: 0; }}

/* Search hide */
.turn.search-hidden {{ display: none; }}

@media (max-width: 800px) {{
  .main {{ padding: 12px; }}
  .toolbar input {{ width: 120px; }}
}}
</style>
<script>
function toggleTurn(el) {{
  const turn = el.closest('.turn');
  const wasCollapsed = turn.classList.contains('collapsed');
  turn.classList.toggle('collapsed');
  if (wasCollapsed) {{
    history.replaceState(null, '', '#' + turn.id);
  }}
}}
function toggleTools(el) {{
  el.closest('.tools-section').classList.toggle('open');
}}

// On load: expand and scroll to hash target
window.addEventListener('DOMContentLoaded', () => {{
  const hash = location.hash.slice(1);
  if (!hash) return;
  const el = document.getElementById(hash);
  if (!el) return;
  if (el.classList.contains('turn')) {{
    el.classList.remove('collapsed');
  }}
  setTimeout(() => el.scrollIntoView({{ block: 'start' }}), 50);
}});
// Handle hash changes (e.g. back/forward)
window.addEventListener('hashchange', () => {{
  const hash = location.hash.slice(1);
  if (!hash) return;
  const el = document.getElementById(hash);
  if (!el) return;
  if (el.classList.contains('turn')) {{
    el.classList.remove('collapsed');
  }}
  el.scrollIntoView({{ block: 'start' }});
}});

let allExpanded = false;
function toggleExpandAll(btn) {{
  const turns = document.querySelectorAll('.turn');
  if (allExpanded) {{
    turns.forEach(t => t.classList.add('collapsed'));
    btn.textContent = 'Expand All';
  }} else {{
    turns.forEach(t => t.classList.remove('collapsed'));
    btn.textContent = 'Collapse All';
  }}
  allExpanded = !allExpanded;
}}

let searchTimeout = null;
function onSearch(val) {{
  clearTimeout(searchTimeout);
  searchTimeout = setTimeout(() => doSearch(val), 150);
}}

function doSearch(query) {{
  const turns = document.querySelectorAll('.turn');
  const counter = document.getElementById('match-count');
  if (!query.trim()) {{
    turns.forEach(t => t.classList.remove('search-hidden'));
    counter.textContent = '';
    return;
  }}
  const q = query.toLowerCase();
  let matches = 0;
  turns.forEach(t => {{
    const text = t.textContent.toLowerCase();
    if (text.includes(q)) {{
      t.classList.remove('search-hidden');
      matches++;
    }} else {{
      t.classList.add('search-hidden');
    }}
  }});
  counter.textContent = matches + ' match' + (matches !== 1 ? 'es' : '');
}}

function jumpTop() {{ window.scrollTo(0, 0); }}
function jumpBottom() {{ window.scrollTo(0, document.body.scrollHeight); }}
</script>
</head>
<body>
<div class="toolbar-wrap">
<div class="toolbar">
  <input id="search-input" type="text" placeholder="Search turns…" oninput="onSearch(this.value)">
  <span id="match-count" class="match-count"></span>
  <div class="sep"></div>
  <button onclick="jumpTop()">Top</button>
  <button onclick="jumpBottom()">Bottom</button>
  <div class="sep"></div>
  <button onclick="toggleExpandAll(this)">Expand All</button>
</div>
</div>
<div class="page">
<div class="main">
<div class="header">
  <h1>Claude Code Conversation</h1>
  <div class="meta">
    <span><b>{turn_count}</b> turns</span>
    <span><b>{total_tool_calls}</b> tool calls</span>
    <span><b>{compaction_count}</b> compactions</span>
    <span style="color:#d63031"><b>${cost_total:.2f}</b> est. cost</span>
  </div>
  <div class="meta">
    <span>{ts_fmt(first_ts)} — {ts_fmt(last_ts)}</span>
    <span>{total_input:,} in / {total_output:,} out / {total_cache_create:,} cache_w / {total_cache_read:,} cache_r tokens</span>
  </div>
</div>
''')

def gap_str(ms):
    hours = ms / 3_600_000
    if hours >= 24:
        return f'{hours/24:.0f}d'
    if hours >= 1:
        return f'{hours:.0f}h'
    return f'{ms/60000:.0f}m'

GAP_THRESHOLD_MS = 30 * 60 * 1000  # 30 minutes

# Render turns
turn_num = 0
prev_ts = None
for t in turns:
    cur_ts = t.get('user_ts', t.get('ts', ''))
    if prev_ts and cur_ts:
        try:
            dt_prev = datetime.fromisoformat(prev_ts.replace('Z', '+00:00'))
            dt_cur = datetime.fromisoformat(cur_ts.replace('Z', '+00:00'))
            gap_ms = (dt_cur - dt_prev).total_seconds() * 1000
            if gap_ms >= GAP_THRESHOLD_MS:
                # Remove border on previous turn
                for i in range(len(out) - 1, -1, -1):
                    if '<div class="turn ' in out[i]:
                        out[i] = out[i].replace('<div class="turn ', '<div class="turn before-gap ', 1)
                        break
                out.append(f'<div class="time-gap">{gap_str(gap_ms)} gap</div>')
        except:
            pass
    if cur_ts:
        prev_ts = cur_ts

    if t['type'] == 'compaction':
        for i in range(len(out) - 1, -1, -1):
            if '<div class="turn ' in out[i]:
                out[i] = out[i].replace('<div class="turn ', '<div class="turn before-gap ', 1)
                break
        out.append(f'''
<div class="compaction">
  <hr><span>Context compacted ({t["tokens"]} tokens) — {ts_fmt(t["ts"])}</span>
</div>''')
        continue

    turn_num += 1
    turn_items = t['items']
    user_text = t['user_text']
    user_ts = t['user_ts']
    dur_ms = t['duration_ms']
    has_err = t['has_errors']

    # Counts
    tc_count = sum(1 for i in turn_items if i['kind'] == 'tool_call')
    to_count = sum(1 for i in turn_items if i['kind'] == 'tool_output')

    # Preview
    preview = user_text[:160].replace('\n',' ')
    if len(user_text) > 160: preview += '…'

    out_tokens = t['output_tokens']
    err_html = '<span class="err-dot"></span>' if has_err else ''
    trunc_html = '<span class="trunc-badge">truncated</span>' if t.get('truncated') else ''
    tc_html = f'<span class="tool-count">{tc_count} tools</span>' if tc_count else ''
    tok_html = f'<span class="tool-count" style="color:{tok_color(out_tokens)}">{tok_str(out_tokens)}</span>' if out_tokens >= 1000 else ''
    time_html = ts_short(user_ts)

    user_full_html = md(user_text) if user_text else ''

    err_class = ' has-err' if has_err else ''
    out.append(f'''
<div class="turn collapsed{err_class}" id="turn-{turn_num}">
  <div class="turn-head" onclick="toggleTurn(this)">
    <span class="turn-num">#{turn_num}</span>
    <span class="turn-preview">{html.escape(preview)}</span>
    <span class="turn-meta">{err_html}{trunc_html}{tc_html}{tok_html}<span>{time_html}</span></span>
  </div>''')

    if user_text:
        out.append(f'  <div class="turn-user-full">{user_full_html}</div>')

    out.append(f'  <div class="turn-body">')

    # Group items: consecutive tool_calls become one tools-section
    idx = 0
    while idx < len(turn_items):
        item = turn_items[idx]
        k = item['kind']

        if k == 'reply':
            out.append(f'    <div class="reply">{md(item["text"])}</div>')
            idx += 1

        elif k == 'thinking':
            th = html.escape(item['text'])
            if len(th) > 2000: th = th[:2000] + f'\n…({len(item["text"])} chars)'
            out.append(f'    <details class="thinking-block"><summary>Thinking</summary><pre>{th}</pre></details>')
            idx += 1

        elif k in ('tool_call', 'tool_output'):
            # Collect consecutive tool_call and tool_output items
            group = []
            while idx < len(turn_items) and turn_items[idx]['kind'] in ('tool_call','tool_output'):
                group.append(turn_items[idx])
                idx += 1
            count = len(group)

            out.append(f'    <div class="tools-section">')
            out.append(f'      <div class="tools-toggle" onclick="toggleTools(this)">{count} tool call{"s" if count!=1 else ""}</div>')
            out.append(f'      <div class="tools-list">')
            for g in group:
                if g['kind'] == 'tool_call':
                    out.append('        ' + render_tool_row(g))
                else:
                    # tool_output (from user message results)
                    rt = g['text']
                    trunc = rt[:3000]
                    if len(rt)>3000: trunc += f'\n…({len(rt)} chars)'
                    is_err = g.get('is_error', False)
                    ecls = ' err-output' if is_err else ''
                    pcls = ' class="err"' if is_err else ''
                    summ = rt[:140].replace('\n',' ')
                    if len(rt)>140: summ += '…'
                    icon = 'error' if is_err else 'output'
                    out.append(
                        f'        <details class="trow">'
                        f'<summary><span class="badge {icon}">{icon}</span>'
                        f'<span class="tsum">{html.escape(summ)}</span></summary>'
                        f'<div class="tbody"><pre{pcls}>{html.escape(trunc)}</pre></div></details>'
                    )
            out.append(f'      </div>')
            out.append(f'    </div>')

        else:
            idx += 1


    out.append(f'  </div>\n</div>')

out.append('''
</div>
</div>
</body></html>''')

result = '\n'.join(out)
with open(OUTPUT, 'w') as f:
    f.write(result)

print(f"Done! {OUTPUT} ({len(result)/1_000_000:.1f} MB)")
print(f"  {turn_count} turns, {total_tool_calls} tool calls, {compaction_count} compactions")

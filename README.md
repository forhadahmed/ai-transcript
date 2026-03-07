# ai-transcript

A small repo focused on transcript rendering and sharing tools for AI systems.

The first implementations in this repo are:

- `claude-transcript` for Claude Code session files
- `codex-transcript` for Codex session files

The goal is a focused transcript-tool repo rather than a general AI utilities collection.

## Tools

### 1. `claude-transcript`

Render Claude Code session logs into browsable HTML transcripts.

Current behavior:

- safe-by-default for sharing
- raw transcript HTML is escaped unless you pass `--allow-unsafe-html`
- output is offline-safe by default and does not fetch Google Fonts
- share presets can redact common sensitive values before rendering

## Install

No required dependencies beyond Python 3.8+.

Optional:

```bash
pip install orjson cmarkgfm
```

- `orjson` speeds up JSON parsing
- `cmarkgfm` improves markdown rendering
- if neither markdown library is installed, the script falls back to a minimal built-in renderer

## `claude-transcript` Usage

```bash
# Single transcript
./claude-transcript session.jsonl -o output.html

# Multiple files
./claude-transcript file1.jsonl file2.jsonl --outdir ./out

# All transcripts in ~/.claude/projects
./claude-transcript --all

# Same as --all
./claude-transcript -a

# Most recent 5
./claude-transcript --recent 5
```

Batch output defaults to `~/claude-transcripts`.

### 2. `codex-transcript`

Render Codex session logs into browsable HTML transcripts.

Current behavior:

- same HTML scaffold and share-safe defaults as `claude-transcript`
- parses local Codex session JSONL under `~/.codex/sessions`
- renders commentary, final answers, thinking summaries, and tool activity
- output is offline-safe by default and does not fetch Google Fonts

## `codex-transcript` Usage

```bash
# Single transcript
./codex-transcript session.jsonl -o output.html

# Multiple files
./codex-transcript file1.jsonl file2.jsonl --outdir ./out

# All transcripts in ~/.codex/sessions
./codex-transcript --all

# Same as --all
./codex-transcript -a

# Most recent 5
./codex-transcript --recent 5
```

Batch output defaults to `~/codex-transcripts`.

## Share Modes

```bash
# Share-safe: redact common sensitive values, hide cost, keep timestamps/tools
./claude-transcript session.jsonl --share-safe -o shared.html

# Public sharing: stronger defaults, hides timestamps, thinking, and tool results
./claude-transcript session.jsonl --share-public -o public.html

# Full content, but still safe HTML and offline-safe output
./claude-transcript session.jsonl --share-full -o full.html
```

`--share-safe` enables:

- `--redact-home`
- `--redact-env`
- `--redact-email`
- `--redact-ip`
- `--redact-api-keys`
- `--redact-paths`
- `--no-cost`

`--share-public` adds:

- `--no-thinking`
- `--no-timestamps`
- `--no-tool-results`

## Flags

### Redaction

| Flag | Effect |
|------|--------|
| `--redact-home` | Redact the current home directory path |
| `--redact-paths` | Redact `/Users/<name>` and `/home/<name>` prefixes |
| `--redact-env` | Redact shell-style env assignments like `FOO=bar` |
| `--redact-email` | Redact email addresses |
| `--redact-ip` | Redact IPv4 addresses |
| `--redact-api-keys` | Redact common key/token shapes |
| `--redact-pattern REGEX` | Redact custom regex matches |

The script prints a preflight summary showing malformed-line skips and redaction counts.

### Content

| Flag | Effect |
|------|--------|
| `--no-thinking` | Hide thinking blocks |
| `--no-tools` | Hide tool call sections entirely |
| `--no-tool-results` | Keep tool calls but hide tool output bodies |
| `--no-diffs` | Show only filenames, no diffs |
| `--no-icons` | Omit user/Claude icons |
| `--no-compactions` | Hide compaction boundaries |
| `--no-gaps` | Hide time gap separators |
| `--no-cost` | Hide cost estimate from header |
| `--no-timestamps` | Hide timestamps from header and turns |
| `--full-output` | Show full tool output instead of truncating |
| `--show-boilerplate` | Show boilerplate tool results |

### Rendering

| Flag | Effect |
|------|--------|
| `--expanded` | Expand all turns by default |
| `--wide` | 1600px max width |
| `--narrow` | 800px max width |
| `--font-size N` | Base font size in px |
| `--wrap-code` | Wrap long code lines |
| `--title TEXT` | Set a custom title |
| `--external-fonts` | Allow Google Fonts in output |
| `--allow-unsafe-html` | Render raw transcript HTML without escaping |

### Batch

| Flag | Effect |
|------|--------|
| `-a`, `--all` | Render all transcripts in `~/.claude/projects` |
| `--recent N` | Render N most recent transcripts |
| `--outdir DIR` | Output directory for batch mode (default: tool-specific; Claude `~/claude-transcripts`, Codex `~/codex-transcripts`) |
| `-j N` | Worker count |

## Validation

Deterministic fixture tests:

```bash
python3 test/transcript-test.py
```

Live local-corpus integration:

```bash
python3 test/transcript-test.py --integration
```

`--integration` uses your local `~/.claude/projects` and `~/.codex/sessions` corpora in addition to the deterministic fixture tests.

## Notes

- Time gap separators are shown for pauses of 30 minutes or more.
- Cost estimates use Claude Opus pricing.
- `codex-transcript` does not currently estimate cost.
- Batch mode forwards render/share flags to child workers, including custom titles and redaction patterns.

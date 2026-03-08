# ai-transcript

Render Claude Code and Codex AI session transcripts as standalone, browsable HTML.

## Quick Start

```bash
pip install orjson cmarkgfm  # optional: faster JSON + better markdown

./claude-transcript -a          # render all Claude transcripts
./codex-transcript -a           # render all Codex transcripts
./claude-transcript --recent 5  # most recent 5
./claude-transcript session.jsonl -o output.html  # single file
```

Output: `~/claude-transcripts/` or `~/codex-transcripts/` with `index.html` opening the most recent transcript.

## Batch Mode

Rendering with `-a` or `--recent` produces a browsable archive:

- **Sidebar TOC** — transcripts sorted by date, with turn counts and token usage
- **Token color coding** — gray < 50K, amber < 200K, orange < 1M, red 1M+
- **Git-aware titles** — detects git repos, shows `repo/subdir` with git icon
- **Search** — real-text search across turns, auto-expands matching tool calls
- **Font picker** — 30+ fonts (system, mono, sans, serif), persisted in localStorage
- **Skeleton loader** — placeholder while large transcripts load
- **Parallel rendering** — subprocess workers capped at CPU count

## Sharing

```bash
./claude-transcript session.jsonl --share-safe -o shared.html    # redact PII, hide cost
./claude-transcript session.jsonl --share-public -o public.html  # above + hide timestamps, thinking, tool output
```

Individual flags: `--redact-home`, `--redact-email`, `--redact-ip`, `--redact-api-keys`, `--redact-paths`, `--redact-env`, `--redact-pattern REGEX`

## Flags

| Flag | Effect |
|------|--------|
| `-a` / `--all` | Render all transcripts |
| `--recent N` | Most recent N |
| `-j N` | Parallel workers |
| `--share-safe` | Redact PII, hide cost |
| `--share-public` | Above + hide timestamps, thinking, tool output |
| `--expanded` | All turns expanded |
| `--wide` / `--narrow` | 1600px / 800px layout |
| `--no-thinking` | Hide thinking blocks |
| `--no-tools` | Hide tool sections |
| `--no-diffs` | Hide diff content |
| `--no-gaps` | Hide time gap markers |
| `--code-font NAME` | Font (default: Source Code Pro) |
| `--font-size N` | Base size in px (default: 15) |
| `--full-output` | No truncation on tool output |
| `--strict` | Fail on malformed JSONL |

## Requirements

Python 3.8+. No required dependencies.

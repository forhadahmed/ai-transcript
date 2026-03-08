# ai-transcript

Render Claude Code and Codex session transcripts as browsable, shareable HTML.

## Features

- Shared rendering engine (`transcript_lib.py`) for both Claude and Codex formats
- Sidebar TOC with search, date sorting, token color coding, git-aware project names
- Skeleton loading for large transcripts
- Font picker (30+ fonts, lazy-loaded from Google Fonts CDN)
- Redaction presets for safe sharing (`--share-safe`, `--share-public`)
- Diff highlighting, thinking blocks, compaction markers, time gap separators
- Parallel batch rendering with `index.html` generation

## Usage

```bash
# Render all Claude transcripts
./claude-transcript -a

# Render all Codex transcripts
./codex-transcript -a

# Single file
./claude-transcript session.jsonl -o output.html

# Most recent 5
./claude-transcript --recent 5
```

Batch output: `~/claude-transcripts` or `~/codex-transcripts`.

## Install

Python 3.8+. Optional: `pip install orjson cmarkgfm` for faster JSON and better markdown.

## Key Flags

| Flag | Effect |
|------|--------|
| `--share-safe` | Redact emails, IPs, API keys, paths, hide cost |
| `--share-public` | Above + hide timestamps, thinking, tool results |
| `--expanded` | Expand all turns |
| `--no-thinking` | Hide thinking blocks |
| `--no-diffs` | Hide diff content |
| `--code-font NAME` | Font (default: Source Code Pro) |
| `--wide` / `--narrow` | 1600px / 800px max width |
| `-j N` | Parallel workers for batch mode |

## Tests

```bash
python3 -m pytest test/transcript-test.py          # fixture tests
python3 test/transcript-test.py --integration       # + local corpus
```

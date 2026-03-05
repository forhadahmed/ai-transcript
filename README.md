# claude-transcript

Renders Claude Code JSONL session files into standalone, browsable HTML transcripts.

## Install

```bash
pip install cmarkgfm orjson  # optional, faster markdown and JSON parsing
```

## Usage

```bash
# Single transcript
./claude-transcript session.jsonl -o output.html

# Multiple files (parallel)
./claude-transcript file1.jsonl file2.jsonl file3.jsonl

# All transcripts in ~/.claude/projects
./claude-transcript --all

# 5 most recent
./claude-transcript --recent 5

# Parallel jobs and output directory
./claude-transcript --all -j 8 --outdir ./out
```

## What it renders

Each transcript is a single self-contained HTML file with:

- **Turn-based layout** -- each user message + Claude response grouped as a collapsible turn
- **Inline diffs** -- Edit/Write tool calls shown as colored unified diffs (green adds, red deletes)
- **Tool call details** -- Bash commands, Read/Grep/Glob results, Agent sub-tasks, MCP calls
- **Thinking blocks** -- collapsible extended thinking sections
- **Diff stat pills** -- `+N -M` line counts per turn in the header
- **Error styling** -- red text for API errors and interrupted requests, red dot indicator
- **Token badges** -- per-turn output token counts with color coding
- **Cost estimate** -- session cost based on Claude Opus pricing
- **Compaction markers** -- shows where context was compressed
- **Time gap separators** -- marks pauses > 10 minutes between turns
- **Search** -- filters turns, highlights matching text in yellow, auto-expands and scrolls to first match
- **Icons** -- Claude favicon and user icon inline with messages

## Flags

### Content visibility

| Flag | Effect |
|------|--------|
| `--no-thinking` | Hide thinking blocks |
| `--no-tools` | Hide tool call sections |
| `--no-diffs` | Show only filenames, no diffs |
| `--no-icons` | Omit user/Claude icons |
| `--no-compactions` | Hide compaction boundaries |
| `--no-gaps` | Hide time gap separators |
| `--no-cost` | Hide cost estimate from header |
| `--full-output` | Show full tool output (no truncation) |
| `--show-boilerplate` | Show "file updated" boilerplate results |

### Layout

| Flag | Effect |
|------|--------|
| `--expanded` | All turns expanded by default |
| `--wide` | 1600px max-width |
| `--narrow` | 800px max-width |
| `--font-size N` | Base font size in px (default: 15) |
| `--wrap-code` | Wrap long lines in code blocks |
| `--title TEXT` | Custom title in header |

### Batch

| Flag | Effect |
|------|--------|
| `--all` | Render all transcripts found in `~/.claude/projects` |
| `--recent N` | Render N most recent transcripts |
| `--outdir DIR` | Output directory for batch mode (default: `./transcripts`) |
| `-j N` | Parallel worker count (default: CPU count) |

## Tests

```bash
python3 test_render.py
```

71 checks across 3 categories:
- **Part 1** -- structural checks on all transcripts (balanced tags, valid HTML)
- **Part 2** -- flag tests on a single transcript (each flag produces expected output changes)
- **Part 3** -- content coverage (diffs, tool calls, thinking, errors, tables, code blocks all rendered)

## Dependencies

- Python 3.8+
- `cmarkgfm` (optional, falls back to `markdown` stdlib-style package)
- `orjson` (optional, falls back to `json`)

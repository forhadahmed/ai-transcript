Render **Claude Code** and **Codex** AI session transcripts as standalone, browsable HTML (more agent support WIP).

![screenshot](https://github.com/forhadahmed/ai-transcript/releases/download/v0.1.0/transcript-demo.png)

## Quick Start

```bash
pip install orjson cmarkgfm # optional: faster JSON + better markdown

./claude-transcript -a # render all to ~/claude-transcripts/
./codex-transcript -a # render all to ~/codex-transcripts/
./claude-transcript --recent 5 # most recent 5
./claude-transcript session.jsonl -o output.html # single file
```

## Features

- **Search** — search across turns, auto-expands matching tool calls
- **Sidebar TOC** — see all rendered transcripts via `-a` or `--recent N`
- **Parallel** — renders all sessions fast ⚡

## Flags

| Flag | Effect |
|------|--------|
| `-a` / `--all` | Render all transcripts |
| `--recent N` | Most recent N |
| `-j N` | Parallel workers |
| `--expanded` | All turns expanded |
| `--wide` / `--narrow` | 1600px / 800px layout |
| `--hide SECTION...` | Hide sections: thinking, tools, diffs, cost, timestamps, icons, compactions, toc |
| `--code-font NAME` | Font (default: Source Code Pro) |
| `--font-size N` | Base size in px (default: 15) |
| `--full-output` | No truncation on tool output |
| `--redact` | Redact PII (emails, IPs, paths, API keys, env vars) |

## Requirements

Python 3.8+. No required dependencies.

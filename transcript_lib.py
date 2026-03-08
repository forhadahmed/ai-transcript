"""Shared infrastructure for AI transcript renderers.

Each engine (Claude Code, Codex) has its own script that defines:
  - parse_transcript(): reads JSONL and produces a normalized turn list
  - tool_summary(): returns (label, icon_class) for a tool call
  - tool_detail(): returns HTML body for a tool call's expanded view
  - auto_title(): generates a title from the transcript data

This module provides everything else: CLI parsing, HTML rendering, search,
batch processing, redaction, markdown, and diff highlighting.
"""

from __future__ import annotations

import argparse
import difflib
import html
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

# ---------------------------------------------------------------------------
# JSON loading
# ---------------------------------------------------------------------------

try:
    import orjson

    def json_loads(blob: str) -> Any:
        return orjson.loads(blob)
except ImportError:
    def json_loads(blob: str) -> Any:
        return json.loads(blob)

# ---------------------------------------------------------------------------
# Markdown backend
# ---------------------------------------------------------------------------

try:
    import cmarkgfm

    MARKDOWN_BACKEND = "cmark"
except ImportError:
    try:
        import markdown

        MARKDOWN_BACKEND = "markdown"
    except ImportError:
        markdown = None
        MARKDOWN_BACKEND = "plain"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Fonts we know are available on Google Fonts CDN (used with --external-fonts)
KNOWN_CODE_FONTS = {
    "JetBrains Mono",
    "Fira Code",
    "Source Code Pro",
    "IBM Plex Mono",
    "Roboto Mono",
    "Ubuntu Mono",
}

# CLI flags forwarded as --flag-name when spawning batch worker subprocesses.
# Each entry is the argparse dest name (underscored); serialize_forwarded_flags()
# converts to --kebab-case for the subprocess command line.
BOOL_FORWARD_FLAGS = [
    "no_thinking",
    "no_tools",
    "no_tool_results",
    "no_diffs",
    "no_icons",
    "no_compactions",
    "no_gaps",
    "no_cost",
    "no_timestamps",
    "full_output",
    "show_boilerplate",
    "expanded",
    "wide",
    "narrow",
    "wrap_code",
    "allow_unsafe_html",
    "external_fonts",
    "strict",
    "redact_home",
    "redact_env",
    "redact_email",
    "redact_ip",
    "redact_api_keys",
    "redact_paths",
    "share_safe",
    "share_public",
    "share_full",
]

ERROR_TEXT_RE = re.compile(
    r"^\[Request interrupted by user.*\]$|^API Error[:{ ]",
    re.MULTILINE,
)
BOILERPLATE_RE = re.compile(
    r"^(The file \S+ has been (updated|created) successfully\.|"
    r"\S+ is now available for use\.)$"
)
SYSTEM_TAG_RE = re.compile(
    r"<(system-reminder|local-command-caveat|command-\w+|task-notification|user-prompt-submit-hook)[^>]*>.*?</\1>",
    re.DOTALL,
)
NEEDS_MD_RE = re.compile(r"[*_#`\[|>\n]")
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
IPV4_RE = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")
USER_PATH_RE = re.compile(r"/(Users|home)/[^/\s:]+")
ENV_ASSIGN_RE = re.compile(
    r"(?P<prefix>\b(?:export\s+)?[A-Z][A-Z0-9_]{1,63}=)"
    r"(?P<value>\"[^\"]*\"|'[^']*'|[^\s]+)"
)
SECRET_ASSIGN_RE = re.compile(
    r"(?P<prefix>\b(?:export\s+)?[A-Z][A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|PASS|PWD)[A-Z0-9_]*=)"
    r"(?P<value>\"[^\"]*\"|'[^']*'|[^\s]+)",
    re.IGNORECASE,
)
API_KEY_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9]{12,}\b"),
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{20,}\b"),
    re.compile(r"\bAIza[0-9A-Za-z\-_]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._-]{12,}\b"),
]

# Claude Opus pricing (per million tokens)
OPUS_COST_INPUT = 15.0
OPUS_COST_OUTPUT = 75.0
OPUS_COST_CACHE_WRITE = 18.75
OPUS_COST_CACHE_READ = 1.50

ICON_USER = (
    '<svg class="turn-icon" viewBox="0 0 24 24" fill="none" '
    'stroke="#0969da" stroke-width="2" stroke-linecap="round" '
    'stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/>'
    '<circle cx="12" cy="7" r="4"/></svg>'
)
ICON_BOT_CLAUDE = (
    '<img class="turn-icon" src="data:image/png;base64,'
    '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">'
)

ICON_BOT_CODEX = (
    '<svg class="turn-icon" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
    '<path d="M22.282 9.821a5.985 5.985 0 0 0-.516-4.91 6.046 6.046 0 0 0-6.51-2.9A6.065 6.065 0 0 0 4.981 4.18'
    'a5.998 5.998 0 0 0-3.998 2.9 6.04 6.04 0 0 0 .743 7.097 5.98 5.98 0 0 0 .51 4.911 6.05 6.05 0 0 0 6.515 2.9A'
    '5.97 5.97 0 0 0 13.26 24a6.04 6.04 0 0 0 5.772-4.206 5.99 5.99 0 0 0 3.997-2.9 6.04 6.04 0 0 0-.747-7.073z'
    'M13.26 22.43a4.476 4.476 0 0 1-2.876-1.04l.143-.08 4.778-2.758a.795.795 0 0 0 .392-.681v-6.737l2.02 1.168a'
    '.071.071 0 0 1 .038.052v5.583a4.504 4.504 0 0 1-4.494 4.494zM3.6 18.304a4.47 4.47 0 0 1-.535-3.014l.143.086'
    ' 4.778 2.759a.771.771 0 0 0 .78 0l5.832-3.369v2.332a.08.08 0 0 1-.033.062L9.74 19.95a4.5 4.5 0 0 1-6.14-1.646'
    'zM2.34 7.896a4.485 4.485 0 0 1 2.366-1.973V11.6a.766.766 0 0 0 .388.676l5.815 3.355-2.02 1.168a.076.076 0 0 1'
    '-.071.005l-4.83-2.786A4.504 4.504 0 0 1 2.34 7.872zm16.597 3.855l-5.833-3.387L15.124 7.2a.076.076 0 0 1 .071'
    '-.006l4.83 2.79a4.494 4.494 0 0 1-.693 8.104v-5.678a.79.79 0 0 0-.396-.66zm2.01-3.023l-.141-.085-4.774-2.782a'
    '.776.776 0 0 0-.785 0L9.409 9.23V6.897a.066.066 0 0 1 .028-.061l4.83-2.787a4.5 4.5 0 0 1 6.68 4.66zm-12.64'
    ' 4.135l-2.02-1.164a.08.08 0 0 1-.038-.057V6.075a4.5 4.5 0 0 1 7.375-3.453l-.142.08L8.704 5.46a.795.795 0 0 0'
    '-.393.681zm1.097-2.365l2.602-1.5 2.596 1.5v2.999l-2.596 1.5-2.602-1.5z" fill="#10a37f"/></svg>'
)

# ---------------------------------------------------------------------------
# Redactor
# ---------------------------------------------------------------------------


class Redactor:
    """Strips sensitive data (home paths, emails, IPs, API keys, env vars) from text.

    Enabled by --share-safe/--share-public presets or individual --redact-* flags.
    Tracks counts per redaction type for the summary printed after rendering.
    """

    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.counts: Counter[str] = Counter()
        self._compiled_patterns = [re.compile(pattern) for pattern in args.redact_pattern]
        self._home = os.path.expanduser("~")
        self._home_re = re.compile(re.escape(self._home)) if self._home not in ("/", "~") else None

    def _apply_sub(self, text: str, label: str, pattern: re.Pattern[str], repl: Any) -> str:
        updated, count = pattern.subn(repl, text)
        if count:
            self.counts[label] += count
        return updated

    def redact_text(self, text: str) -> str:
        if not text:
            return text

        if self.args.redact_home and self._home_re:
            text = self._apply_sub(text, "home_paths", self._home_re, "~")

        if self.args.redact_paths:
            text = self._apply_sub(
                text,
                "user_paths",
                USER_PATH_RE,
                lambda match: f"/{match.group(1)}/REDACTED",
            )

        if self.args.redact_email:
            text = self._apply_sub(text, "emails", EMAIL_RE, "[REDACTED_EMAIL]")

        if self.args.redact_ip:
            def replace_ip(match: re.Match[str]) -> str:
                parts = match.group(0).split(".")
                if any(int(part) > 255 for part in parts):
                    return match.group(0)
                return "[REDACTED_IP]"

            text = self._apply_sub(text, "ipv4_addresses", IPV4_RE, replace_ip)

        if self.args.redact_env:
            text = self._apply_sub(
                text,
                "env_assignments",
                ENV_ASSIGN_RE,
                lambda match: f"{match.group('prefix')}[REDACTED_ENV]",
            )

        if self.args.redact_api_keys:
            for pattern in API_KEY_PATTERNS:
                text = self._apply_sub(text, "api_keys", pattern, "[REDACTED_SECRET]")
            text = self._apply_sub(
                text,
                "secret_assignments",
                SECRET_ASSIGN_RE,
                lambda match: f"{match.group('prefix')}[REDACTED_SECRET]",
            )

        for index, pattern in enumerate(self._compiled_patterns, start=1):
            text = self._apply_sub(text, f"custom_pattern_{index}", pattern, "[REDACTED]")

        return text

    def redact_obj(self, value: Any) -> Any:
        if isinstance(value, str):
            return self.redact_text(value)
        if isinstance(value, list):
            return [self.redact_obj(item) for item in value]
        if isinstance(value, tuple):
            return tuple(self.redact_obj(item) for item in value)
        if isinstance(value, dict):
            return {key: self.redact_obj(item) for key, item in value.items()}
        return value

    def summary_lines(self) -> list[str]:
        if not self.counts:
            return ["  Preflight: no redactions applied"]
        summary = ", ".join(
            f"{label}={count}"
            for label, count in sorted(self.counts.items())
        )
        return [f"  Preflight: {summary}"]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_base_parser(description: str, default_outdir: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("input", nargs="*", default=[], help="Input JSONL file(s)")
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="Output HTML file (single input mode only)",
    )

    parser.add_argument("--no-thinking", action="store_true", help="Hide thinking blocks")
    parser.add_argument("--no-tools", action="store_true", help="Hide tool call sections")
    parser.add_argument(
        "--no-tool-results",
        action="store_true",
        help="Hide tool result/output bodies while keeping tool calls",
    )
    parser.add_argument("--no-diffs", action="store_true", help="Show only filenames, no diffs")
    parser.add_argument("--no-icons", action="store_true", help="Omit user/agent icons")
    parser.add_argument("--no-compactions", action="store_true", help="Hide compaction markers")
    parser.add_argument("--no-gaps", action="store_true", help="Hide time gap separators")
    parser.add_argument("--no-cost", action="store_true", help="Hide cost estimate from header")
    parser.add_argument("--no-timestamps", action="store_true", help="Hide timestamps from header and turns")
    parser.add_argument("--no-toc", action="store_true", help="Omit sidebar table of contents in batch mode")
    parser.add_argument("--full-output", action="store_true", help="Show full tool output")
    parser.add_argument(
        "--show-boilerplate",
        action="store_true",
        help='Show "file updated" boilerplate results',
    )

    parser.add_argument("--expanded", action="store_true", help="Expand all turns by default")
    parser.add_argument("--wide", action="store_true", help="Use a 1600px max width")
    parser.add_argument("--narrow", action="store_true", help="Use an 800px max width")
    parser.add_argument("--font-size", type=int, default=15, help="Base font size in px")
    parser.add_argument("--wrap-code", action="store_true", help="Wrap long code lines")
    parser.add_argument(
        "--code-font",
        default="JetBrains Mono",
        help="Code font family preference",
    )
    parser.add_argument("--title", default=None, help="Custom title in header")

    share_group = parser.add_mutually_exclusive_group()
    share_group.add_argument(
        "--share-safe",
        action="store_true",
        help="Apply share-safe defaults: sanitization, redaction, and offline-safe output",
    )
    share_group.add_argument(
        "--share-public",
        action="store_true",
        help="Apply stronger public-sharing defaults",
    )
    share_group.add_argument(
        "--share-full",
        action="store_true",
        help="Keep full content while still using safe HTML/offline defaults",
    )
    parser.add_argument(
        "--allow-unsafe-html",
        action="store_true",
        help="Allow raw transcript HTML to render unescaped",
    )
    parser.add_argument(
        "--external-fonts",
        action="store_true",
        help="Allow Google Fonts in generated HTML",
    )
    parser.add_argument("--strict", action="store_true", help="Fail on malformed JSONL input")
    parser.add_argument("--redact-home", action="store_true", help="Redact the current home path")
    parser.add_argument(
        "--redact-env",
        action="store_true",
        help="Redact shell-style environment assignments",
    )
    parser.add_argument("--redact-email", action="store_true", help="Redact email addresses")
    parser.add_argument("--redact-ip", action="store_true", help="Redact IPv4 addresses")
    parser.add_argument("--redact-api-keys", action="store_true", help="Redact common API key shapes")
    parser.add_argument("--redact-paths", action="store_true", help="Redact user/home path prefixes")
    parser.add_argument(
        "--redact-pattern",
        action="append",
        default=[],
        metavar="REGEX",
        help="Additional regex pattern to redact",
    )

    parser.add_argument("-a", "--all", action="store_true", help="Render all transcripts")
    parser.add_argument("--recent", type=int, metavar="N", help="Render N most recent transcripts")
    parser.add_argument(
        "--outdir",
        default=default_outdir,
        help="Output directory for batch mode",
    )
    parser.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=None,
        help="Parallel jobs for batch mode",
    )
    return parser


def apply_share_preset(args: argparse.Namespace) -> None:
    """Expand --share-safe/--share-public into individual redaction flags.

    --share-safe:   redact PII but keep full content (for teammates)
    --share-public: also strip thinking, timestamps, tool results (for blog posts)
    --share-full:   no redaction at all (keep everything, for personal archives)
    """
    if args.share_safe or args.share_public:
        args.redact_home = True
        args.redact_env = True
        args.redact_email = True
        args.redact_ip = True
        args.redact_api_keys = True
        args.redact_paths = True
        args.no_cost = True

    if args.share_public:
        args.no_thinking = True
        args.no_timestamps = True
        args.no_tool_results = True


def serialize_forwarded_flags(args: argparse.Namespace) -> list[str]:
    extra_flags: list[str] = []
    for name in BOOL_FORWARD_FLAGS:
        if getattr(args, name, False):
            extra_flags.append(f"--{name.replace('_', '-')}")
    if args.font_size != 15:
        extra_flags.extend(["--font-size", str(args.font_size)])
    if args.code_font != "JetBrains Mono":
        extra_flags.extend(["--code-font", args.code_font])
    if args.title:
        extra_flags.extend(["--title", args.title])
    for pattern in args.redact_pattern:
        extra_flags.extend(["--redact-pattern", pattern])
    return extra_flags


def parse_args(description: str, default_outdir: str, argv: list[str] | None = None) -> argparse.Namespace:
    parser = build_base_parser(description, default_outdir)
    args = parser.parse_args(argv)
    apply_share_preset(args)
    if not args.input and not args.all and not args.recent:
        parser.error("No input file specified. Use a JSONL path, --all, or --recent N.")
    return args


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def ts_fmt(ts_str: str) -> str:
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return ts_str or ""


def ts_short(ts_str: str) -> str:
    try:
        dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.strftime("%H:%M:%S")
    except (TypeError, ValueError):
        return ""


def tok_str(value: int) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"
    if value >= 1000:
        return f"{value / 1000:.1f}k"
    return str(value)


def tok_color(value: int) -> str:
    if value >= 10000:
        return "#c62828"
    if value >= 5000:
        return "#e65100"
    if value >= 2000:
        return "#f9a825"
    return "#888"


def strip_system_tags(text: str) -> str:
    """Remove <system-reminder>, <task-notification>, etc. injected by the CLI."""
    return SYSTEM_TAG_RE.sub("", text).strip()


def is_boilerplate_result(text: str, args: argparse.Namespace) -> bool:
    """True for tool results that add noise (e.g. 'File updated successfully.')."""
    if args.show_boilerplate:
        return False
    return bool(BOILERPLATE_RE.match(text.strip()))


def safe_markdown_source(text: str, args: argparse.Namespace) -> str:
    if args.allow_unsafe_html:
        return text
    return html.escape(text, quote=False)


def sanitize_css_value(raw: str) -> str:
    """Strip characters that could break out of a CSS property value."""
    return re.sub(r"['\";{}\\]", "", raw)


def read_jsonl_records(path: str, strict: bool) -> tuple[list[dict[str, Any]], int]:
    records: list[dict[str, Any]] = []
    malformed = 0
    with open(path, encoding="utf-8", errors="replace") as handle:
        for lineno, line in enumerate(handle, 1):
            if lineno % 50000 == 0:
                print(f"  ...line {lineno}")
            try:
                records.append(json_loads(line))
            except Exception as exc:
                malformed += 1
                if strict:
                    raise ValueError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
    return records, malformed


def compute_opus_cost(
    total_input: int,
    total_output: int,
    total_cache_create: int,
    total_cache_read: int,
) -> float:
    return (
        (total_input / 1_000_000) * OPUS_COST_INPUT
        + (total_output / 1_000_000) * OPUS_COST_OUTPUT
        + (total_cache_create / 1_000_000) * OPUS_COST_CACHE_WRITE
        + (total_cache_read / 1_000_000) * OPUS_COST_CACHE_READ
    )


# ---------------------------------------------------------------------------
# Markdown rendering
# ---------------------------------------------------------------------------


def extract_fenced_blocks(text: str) -> tuple[str, dict[str, str]]:
    """Pull fenced code blocks out before markdown conversion, replace after.

    This prevents the markdown parser from mangling code block contents
    (indentation, special chars). Returns (text_with_placeholders, placeholder_map).
    """
    placeholders: dict[str, str] = {}
    counter = 0

    def replacer(match: re.Match[str]) -> str:
        nonlocal counter
        counter += 1
        key = f"\x00FENCED{counter}\x00"
        indent = match.group(1) or ""
        lang = match.group(2) or ""
        body = match.group(3)
        if indent:
            body_lines = body.split("\n")
            body = "\n".join(
                line[len(indent):] if line.startswith(indent) else line
                for line in body_lines
            )
        lang_attr = f' class="language-{html.escape(lang)}"' if lang else ""
        placeholders[key] = f"<pre><code{lang_attr}>{html.escape(body)}</code></pre>"
        return f"\n{key}\n"

    cleaned = re.sub(
        r"^([ \t]*)`{3,}(\w*)\s*\n(.*?)^\1`{3,}\s*$",
        replacer,
        text,
        flags=re.MULTILINE | re.DOTALL,
    )
    return cleaned, placeholders


def render_markdown(text: str, args: argparse.Namespace) -> str:
    if not NEEDS_MD_RE.search(text):
        return f"<p>{html.escape(text)}</p>"

    source = safe_markdown_source(text, args)
    if MARKDOWN_BACKEND == "cmark":
        return cmarkgfm.github_flavored_markdown_to_html(source)

    source, placeholders = extract_fenced_blocks(source)
    if MARKDOWN_BACKEND == "markdown":
        md_engine = markdown.Markdown(extensions=["fenced_code", "tables", "nl2br", "sane_lists"])
        result = md_engine.convert(source)
    else:
        paragraphs = []
        for block in re.split(r"\n{2,}", source):
            block = block.strip()
            if not block:
                continue
            paragraphs.append(f"<p>{block.replace(chr(10), '<br>')}</p>")
        result = "\n".join(paragraphs) if paragraphs else "<p></p>"
    for key, replacement in placeholders.items():
        result = result.replace(f"<p>{key}</p>", replacement).replace(key, replacement)
    if "```" in result:
        parts = re.split(r"(<pre[^>]*>.*?</pre>|<code[^>]*>.*?</code>)", result, flags=re.DOTALL)
        for index, part in enumerate(parts):
            if not part.startswith("<pre") and not part.startswith("<code"):
                parts[index] = re.sub(r"`{3,}\w*", "", part)
        result = "".join(parts)
    return result


# ---------------------------------------------------------------------------
# Content helpers
# ---------------------------------------------------------------------------


def mcp_name(raw: str) -> str:
    match = re.search(r"__(\w+)$", raw)
    return f"MCP:{match.group(1)}" if match else raw


def render_diff(old: str, new: str) -> str:
    """Generate red/green highlighted HTML from old_string→new_string (Claude Edit tool)."""
    old_lines = (old or "").splitlines(keepends=True)
    new_lines = (new or "").splitlines(keepends=True)

    diff = list(difflib.unified_diff(old_lines, new_lines, lineterm=""))
    if not diff and new and not old:
        content = "".join(
            f'<span class="diff-add">+{html.escape(line)}</span>'
            for line in new.split("\n")
        )
        return f'<pre class="diff-block">{content}</pre>'
    if not diff:
        return ""

    rows = []
    for line in diff:
        if line.startswith("---") or line.startswith("+++"):
            continue
        raw = html.escape(line.rstrip("\n"))
        if line.startswith("+"):
            rows.append(f'<span class="diff-add">{raw}</span>')
        elif line.startswith("-"):
            rows.append(f'<span class="diff-del">{raw}</span>')
        elif line.startswith("@@"):
            rows.append(f'<span class="diff-hunk">{raw}</span>')
        else:
            rows.append(f'<span class="diff-ctx">{raw}</span>')

    content = "".join(rows)
    if len(content) > 5000:
        # Cut at last complete </span> to avoid breaking HTML
        cut = content.rfind("</span>", 0, 5000)
        if cut > 0:
            content = content[: cut + 7]
        else:
            cut = content.rfind(">", 0, 5000)
            content = content[: cut + 1] if cut > 0 else content[:5000]
        content += "\n...(truncated)"
    return f'<pre class="diff-block">{content}</pre>'


def render_patch(patch_text: str, full_output: bool = False) -> str:
    """Colorize a Codex-style patch (*** Begin Patch / +lines / @@)."""
    limit = len(patch_text) if full_output else 5000
    lines = patch_text[:limit].splitlines()
    rows: list[str] = []
    for line in lines:
        raw = html.escape(line)
        if line.startswith("+"):
            rows.append(f'<span class="diff-add">{raw}</span>')
        elif line.startswith("-"):
            rows.append(f'<span class="diff-del">{raw}</span>')
        elif line.startswith("@@"):
            rows.append(f'<span class="diff-hunk">{raw}</span>')
        elif line.startswith("***"):
            rows.append(f'<span class="diff-hunk">{raw}</span>')
        else:
            rows.append(f'<span class="diff-ctx">{raw}</span>')
    content = "".join(rows)
    if len(patch_text) > limit:
        content += f"\n...({len(patch_text)} chars)"
    return f'<pre class="diff-block">{content}</pre>'


def extract_result_text(block: dict[str, Any]) -> str:
    content = block.get("content", "")
    if isinstance(content, list):
        return "\n".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict)
        )
    return str(content) if content else ""


def build_result_html(text: str, is_error: bool, args: argparse.Namespace) -> str | None:
    if args.no_tool_results or not text.strip():
        return None
    limit = len(text) if args.full_output else 3000
    trunc = text[:limit]
    if len(text) > limit:
        trunc += f"\n...({len(text)} chars)"
    err_cls = ' class="err"' if is_error else ""
    res_cls = " err-result" if is_error else ""
    label = "Error" if is_error else "Output"
    return (
        f'<details class="result{res_cls}"><summary>{label} ({len(text)} chars)</summary>'
        f"<pre{err_cls}>{html.escape(trunc)}</pre></details>"
    )


def iconize(rendered: str, icon: str) -> str:
    if not icon:
        return rendered
    if rendered.startswith("<p>"):
        return rendered.replace("<p>", f"<p>{icon}", 1)
    return icon + rendered


def wrap_error(rendered: str, is_error: bool) -> str:
    if not is_error:
        return rendered
    return f'<div class="error-text">{rendered}</div>'


def estimate_message_size(content: Any) -> int:
    """Rough byte estimate of a Claude message's content blocks.

    Used to detect compaction boundaries — when the context window was
    compressed, message sizes drop sharply.
    """
    if isinstance(content, str):
        return len(content)
    if not isinstance(content, list):
        return 0
    size = 0
    for block in content:
        if not isinstance(block, dict):
            continue
        size += len(block.get("text", ""))
        payload = block.get("input", "")
        if isinstance(payload, str):
            size += len(payload)
        elif payload:
            size += len(json.dumps(payload, default=str))
    return size


def gap_str(ms: float) -> str:
    hours = ms / 3_600_000
    if hours >= 24:
        return f"{hours / 24:.0f}d"
    if hours >= 1:
        return f"{hours:.0f}h"
    return f"{ms / 60000:.0f}m"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def render_tool_row(
    tool_call: dict[str, Any],
    args: argparse.Namespace,
    tool_summary_fn: Callable,
    tool_detail_fn: Callable,
) -> str:
    """Render a single tool call as a collapsible <details> row.

    Edit tools auto-expand (open attribute) so diffs are visible without
    extra clicks. The .auto-open-edit class lets search collapse/restore them.
    """
    summary, icon = tool_summary_fn(tool_call["block"])
    body = tool_detail_fn(tool_call["block"], args)
    result_html = None
    if tool_call.get("result_text") and not is_boilerplate_result(tool_call["result_text"], args):
        result_html = build_result_html(
            tool_call["result_text"],
            tool_call.get("result_is_error", False),
            args,
        )

    inner = body
    if result_html:
        inner += "\n" + result_html
    inner_tools = tool_call.get("inner_tools", [])
    if inner_tools:
        inner += f'\n<div class="agent-inner"><div class="dim">{len(inner_tools)} inner tool calls</div>'
        for inner_block in inner_tools:
            inner_summary, inner_icon = tool_summary_fn(inner_block)
            inner += (
                '<div class="agent-tool-row">'
                f'<span class="badge {inner_icon}">{inner_icon}</span>'
                f'<span class="tsum">{html.escape(inner_summary)}</span>'
                "</div>"
            )
        inner += "</div>"
    count_suffix = f' <span class="dim">({len(inner_tools)} inner)</span>' if inner_tools else ""
    is_edit = icon == "edit" and not args.no_diffs
    open_attr = " open" if is_edit else ""
    extra_class = " auto-open-edit" if is_edit else ""
    return (
        f'<details class="trow{extra_class}"{open_attr}>'
        f'<summary><span class="badge {icon}">{icon}</span>'
        f'<span class="tsum">{html.escape(summary)}{count_suffix}</span></summary>'
        f'<div class="tbody">{inner}</div>'
        "</details>"
    )


# ---------------------------------------------------------------------------
# HTML scaffold
# ---------------------------------------------------------------------------


def build_header_meta_html(data: dict[str, Any], args: argparse.Namespace, first_ts: str, last_ts: str) -> str:
    parts: list[str] = []
    if not args.no_timestamps:
        parts.append(f"<span>{ts_fmt(first_ts)} - {ts_fmt(last_ts)}</span>")
    parts.append(f"<span><b>{data['turn_count']}</b> turns</span>")
    parts.append(f"<span><b>{data['total_tool_calls']}</b> tool calls</span>")
    parts.append(f"<span><b>{data['compaction_count']}</b> compactions</span>")
    parts.append(f"<span>{data['total_input']:,} in / {data['total_output']:,} out tokens</span>")
    if not args.no_cost and data.get("cost_total") is not None:
        parts.append(f'<span style="color:#d63031"><b>${data["cost_total"]:.2f}</b> est.</span>')
    return "".join(parts)


LOGO_CLAUDE = (
    '<img class="engine-logo" src="data:image/png;base64,'
    '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">'
)
LOGO_CODEX = (
    '<svg class="engine-logo" viewBox="0 0 24 24" xmlns="http://www.w3.org/2000/svg">'
    '<path d="M22.282 9.821a5.985 5.985 0 0 0-.516-4.91 6.046 6.046 0 0 0-6.51-2.9A6.065 6.065 0 0 0 4.981 4.18'
    'a5.998 5.998 0 0 0-3.998 2.9 6.04 6.04 0 0 0 .743 7.097 5.98 5.98 0 0 0 .51 4.911 6.05 6.05 0 0 0 6.515 2.9A'
    '5.97 5.97 0 0 0 13.26 24a6.04 6.04 0 0 0 5.772-4.206 5.99 5.99 0 0 0 3.997-2.9 6.04 6.04 0 0 0-.747-7.073z'
    'M13.26 22.43a4.476 4.476 0 0 1-2.876-1.04l.143-.08 4.778-2.758a.795.795 0 0 0 .392-.681v-6.737l2.02 1.168a'
    '.071.071 0 0 1 .038.052v5.583a4.504 4.504 0 0 1-4.494 4.494zM3.6 18.304a4.47 4.47 0 0 1-.535-3.014l.143.086'
    ' 4.778 2.759a.771.771 0 0 0 .78 0l5.832-3.369v2.332a.08.08 0 0 1-.033.062L9.74 19.95a4.5 4.5 0 0 1-6.14-1.646'
    'zM2.34 7.896a4.485 4.485 0 0 1 2.366-1.973V11.6a.766.766 0 0 0 .388.676l5.815 3.355-2.02 1.168a.076.076 0 0 1'
    '-.071.005l-4.83-2.786A4.504 4.504 0 0 1 2.34 7.872zm16.597 3.855l-5.833-3.387L15.124 7.2a.076.076 0 0 1 .071'
    '-.006l4.83 2.79a4.494 4.494 0 0 1-.693 8.104v-5.678a.79.79 0 0 0-.396-.66zm2.01-3.023l-.141-.085-4.774-2.782a'
    '.776.776 0 0 0-.785 0L9.409 9.23V6.897a.066.066 0 0 1 .028-.061l4.83-2.787a4.5 4.5 0 0 1 6.68 4.66zm-12.64'
    ' 4.135l-2.02-1.164a.08.08 0 0 1-.038-.057V6.075a4.5 4.5 0 0 1 7.375-3.453l-.142.08L8.704 5.46a.795.795 0 0 0'
    '-.393.681zm1.097-2.365l2.602-1.5 2.596 1.5v2.999l-2.596 1.5-2.602-1.5z" fill="#10a37f"/></svg>'
)


def favicon_link(engine_label: str) -> str:
    """Return a <link rel=icon> tag for the given engine, or empty string."""
    if not engine_label:
        return ""
    if "claude" in engine_label.lower():
        b64 = LOGO_CLAUDE.split("base64,", 1)[1].rstrip("'>")
        return f'<link rel="icon" type="image/png" href="data:image/png;base64,{b64}">'
    fav_svg = (LOGO_CODEX.replace(' class="engine-logo"', '')
               .replace('"', "'").replace('#', '%23'))
    return f'<link rel="icon" type="image/svg+xml" href="data:image/svg+xml,{fav_svg}">'


def _engine_logo_html(engine_label: str) -> str:
    if not engine_label:
        return ""
    if "claude" in engine_label.lower():
        return LOGO_CLAUDE
    return LOGO_CODEX


def _format_title_html(title: str) -> str:
    if ": " in title:
        project, rest = title.split(": ", 1)
        return f'<b>{html.escape(project)}</b>: <span class="title-msg">{html.escape(rest)}</span>'
    return html.escape(title)


def build_html_scaffold_prefix(
    title: str,
    header_meta_html: str,
    args: argparse.Namespace,
    max_width: str,
    engine_label: str = "",
) -> list[str]:
    safe_font = sanitize_css_value(args.code_font)
    fonts_link = ""
    if args.external_fonts and args.code_font in KNOWN_CODE_FONTS:
        fonts_link = (
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family='
            f'{args.code_font.replace(" ", "+")}:wght@300;400;700&display=swap">'
        )

    favicon = favicon_link(engine_label)

    return [
        "<!DOCTYPE html>",
        '<html lang="en"><head>',
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
        favicon,
        fonts_link,
        f"<title>{html.escape(title)}</title>",
        "<style>",
        "* { box-sizing: border-box; margin: 0; padding: 0; }",
        (
            "body { font-family: '"
            + safe_font
            + "','SF Mono','Cascadia Code','Fira Code','Consolas',monospace;"
            + f" font-weight: 300; background: #fff; color: #1a1a1a; line-height: 1.6; font-size: {args.font_size}px; }}"
        ),
        "a { color: #0969da; }",
        ".page { min-height: 100vh; }",
        f".main {{ max-width: {max_width}; margin: 0 auto; padding: 20px 32px; }}",
        ".header { padding: 20px 0 16px; border-bottom: 1px solid #e0e0e0; margin-bottom: 16px; font-family: 'Geist','Inter',-apple-system,'Segoe UI','Helvetica Neue',Arial,sans-serif; }",
        ".header h1 { font-size: 1.2em; color: #333; font-weight: 400; display: flex; align-items: center; gap: 10px; }",
        ".header h1 b { font-weight: 700; }",
        ".title-msg { font-weight: 300; }",
        ".engine-logo { width: 20px; height: 20px; flex-shrink: 0; }",
        ".header .meta { font-size: 0.8em; color: #666; margin-top: 6px; }",
        ".header .meta span { margin-right: 16px; }",
        ".header .meta b { color: #0969da; }",
        ".turn { padding: 16px 0; border-bottom: 1px solid #eee; }",
        ".turn:last-child { border-bottom: none; }",
        ".turn.before-gap { border-bottom: none; }",
        ".turn-head { display: flex; align-items: center; gap: 10px; cursor: pointer; user-select: none; min-height: 24px; }",
        ".turn-head:hover .turn-num { color: #0969da; }",
        ".turn-num { font-size: 0.75em; font-weight: 700; color: #999; flex-shrink: 0; width: 36px; }",
        ".turn-preview { flex: 1; min-width: 0; font-size: 0.82em; color: #555; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }",
        ".turn:not(.collapsed) .turn-preview { display: none; }",
        ".turn.collapsed .turn-user-full { display: none; }",
        ".turn-user-full { padding: 10px 16px; border-left: 3px solid #0969da; margin-bottom: 8px; }",
        ".turn-meta { flex-shrink: 0; font-size: 0.7em; color: #999; display: flex; gap: 8px; align-items: center; margin-left: auto; }",
        ".err-dot { display: inline-block; width: 8px; height: 8px; background: #d63031; border-radius: 50%; }",
        ".diff-stat { font-size: 0.85em; border-radius: 3px; background: #fff; border: 1px solid #d0d7de; white-space: nowrap; display: inline-flex; }",
        ".diff-stat .da { color: #1a7f37; padding: 1px 5px; }",
        ".diff-stat .dd { color: #cf222e; padding: 1px 5px; border-left: 1px solid #d0d7de; }",
        ".tool-count { background: #eee; padding: 1px 6px; border-radius: 3px; font-size: 0.9em; }",
        ".turn-body { padding-top: 4px; }",
        ".turn.collapsed .turn-body { display: none; }",
        ".reply { padding: 10px 16px; border-left: 3px solid #2e7d32; margin: 6px 0; }",
        ".reply, .turn-user-full { font-size: 0.9em; }",
        ".reply p, .turn-user-full p { margin: 5px 0; }",
        ".reply h1, .reply h2, .reply h3, .reply h4 { margin: 10px 0 4px; }",
        ".reply h1, .turn-user-full h1 { font-size: 1.2em; }",
        ".reply h2, .turn-user-full h2 { font-size: 1.1em; }",
        ".reply h3, .turn-user-full h3 { font-size: 1.0em; }",
        ".reply h4, .turn-user-full h4 { font-size: 0.95em; }",
        ".turn-user-full h1, .turn-user-full h2, .turn-user-full h3, .turn-user-full h4 { color: #0969da; margin: 10px 0 4px; }",
        ".turn-icon { width: 16px; height: 16px; vertical-align: middle; margin-right: 6px; }",
        ".turn-user-full, .reply, .tbody { overflow-wrap: break-word; }",
        (
            "pre { background: #f4f4f4; padding: 8px 10px; font-size: 0.88em; margin: 5px 0; overflow-x: auto;"
            + (" white-space: pre-wrap; word-wrap: break-word;" if args.wrap_code else "")
            + " }"
        ),
        "code { background: #f4f4f4; padding: 1px 4px; font-size: 0.9em; }",
        "pre code { background: none; padding: 0; }",
        "ul, ol { padding-left: 20px; margin: 5px 0; }",
        "li { margin: 2px 0; }",
        "table { border-collapse: collapse; margin: 6px 0; font-size: 0.9em; width: 100%; table-layout: auto; }",
        "th { background: #f4f4f4; font-weight: 600; text-align: left; padding: 5px 10px; border-bottom: 2px solid #ddd; }",
        "td { padding: 4px 10px; border-bottom: 1px solid #eee; }",
        "tr:hover { background: #f9f9f9; }",
        "blockquote { border-left: 3px solid #ddd; padding: 3px 12px; margin: 5px 0; color: #666; }",
        "hr { border: none; border-top: 1px solid #ddd; margin: 10px 0; }",
        "strong { color: #111; }",
        ".tools-section { margin: 4px 0; }",
        ".tools-toggle { cursor: pointer; font-size: 0.78em; color: #666; padding: 4px 0; user-select: none; display: flex; align-items: center; gap: 6px; }",
        ".tools-toggle:hover { color: #0969da; }",
        ".tools-toggle::before { content: '\\25B6'; font-size: 0.7em; display: inline-block; width: 12px; transition: transform 0.15s; }",
        ".tools-section.open .tools-toggle::before { content: '\\25BC'; }",
        ".tools-list { display: none; }",
        ".tools-section.open .tools-list { display: block; }",
        ".trow { border-bottom: 1px solid #f0f0f0; }",
        ".trow:last-child { border-bottom: none; }",
        ".trow > summary { cursor: pointer; padding: 4px 8px; font-size: 0.8em; color: #333; list-style: none; display: flex; align-items: center; gap: 6px; }",
        ".trow > summary::-webkit-details-marker { display: none; }",
        ".trow > summary::before { content: '\\25B6'; font-size: 0.5em; color: #999; display: inline-block; width: 10px; flex-shrink: 0; }",
        ".trow[open] > summary::before { content: '\\25BC'; }",
        ".trow > summary:hover { background: #f6f8fa; }",
        ".tbody { padding: 4px 12px 8px 28px; font-size: 0.82em; }",
        ".badge { display: inline-block; padding: 0 5px; border-radius: 3px; font-size: 0.7em; font-weight: 700; text-transform: uppercase; letter-spacing: 0.3px; flex-shrink: 0; }",
        ".badge.bash { background: #e6f4ea; color: #137333; }",
        ".badge.read { background: #e8f0fe; color: #1967d2; }",
        ".badge.search { background: #fef7e0; color: #b06000; }",
        ".badge.edit { background: #fef3e0; color: #e65100; }",
        ".badge.agent { background: #f3e8fd; color: #7627bb; }",
        ".badge.mcp { background: #f3e8fd; color: #8250df; }",
        ".badge.task, .badge.other { background: #e8e8e8; color: #555; }",
        ".badge.output { background: #e8f5e9; color: #2e7d32; }",
        ".badge.error { background: #ffebee; color: #c62828; }",
        ".tsum { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; flex: 1; min-width: 0; }",
        ".agent-inner { margin: 6px 0 2px; padding: 4px 0 0 12px; border-left: 2px solid #e8e0f0; }",
        ".agent-tool-row { display: flex; align-items: center; gap: 6px; padding: 1px 0; font-size: 0.85em; }",
        ".trunc-badge { background: #fff3e0; color: #e65100; font-size: 0.7em; font-weight: 700; padding: 1px 6px; border-radius: 3px; text-transform: uppercase; letter-spacing: 0.3px; }",
        ".mcp-field { margin: 3px 0; }",
        ".mcp-key { color: #8250df; font-size: 0.85em; font-weight: 600; }",
        ".dim { color: #666; font-size: 0.85em; }",
        ".result { margin: 4px 0; }",
        ".error-text { color: #c62828; font-weight: 600; }",
        ".result summary { cursor: pointer; color: #666; font-size: 0.8em; }",
        ".result.err-result summary { color: #c62828; font-weight: 600; }",
        ".result.err-result { border-left: 2px solid #c62828; padding-left: 8px; }",
        "pre.err { background: #fff5f5; color: #b71c1c; }",
        ".diff-block { background: #fafafa; padding: 8px 10px; font-size: 0.88em; margin: 5px 0; overflow-x: auto; line-height: 1.5; }",
        ".diff-add, .diff-del, .diff-hunk, .diff-ctx { display: block; padding: 0 4px; margin: 0; }",
        ".diff-add { color: #1a7f37; background: #dafbe1; }",
        ".diff-del { color: #cf222e; background: #ffebe9; }",
        ".diff-hunk { color: #6639ba; }",
        ".diff-ctx { color: #656d76; }",
        ".thinking-block { border-bottom: 1px solid #f0f0f0; }",
        ".thinking-block:last-child { border-bottom: none; }",
        ".thinking-block > summary { cursor: pointer; padding: 4px 8px; font-size: 0.8em; color: #333; list-style: none; display: flex; align-items: center; gap: 6px; }",
        ".thinking-block > summary::-webkit-details-marker { display: none; }",
        ".thinking-block > summary::before { content: '\\25B6'; font-size: 0.5em; color: #999; display: inline-block; width: 10px; flex-shrink: 0; }",
        ".thinking-block[open] > summary::before { content: '\\25BC'; }",
        ".thinking-block > summary:hover { background: #f6f8fa; }",
        ".thinking-block .tbody { padding: 4px 12px 8px 28px; font-size: 0.82em; }",
        ".thinking-block pre { color: #666; max-height: 300px; }",
        ".badge.thinking { background: #f3e8fd; color: #7c3aed; }",
        ".compaction { margin: 24px 0; text-align: center; }",
        ".compaction hr { border: none; border-top: 1px solid #d63031; margin: 0 0 6px; }",
        ".compaction span { font-size: 0.72em; color: #d63031; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; }",
        ".time-gap { margin: 0; padding: 8px 0; text-align: center; font-size: 0.72em; color: #999; display: flex; align-items: center; gap: 12px; }",
        ".time-gap::before, .time-gap::after { content: ''; flex: 1; border-top: 1px dashed #ccc; }",
        ".toolbar { display: flex; align-items: center; gap: 6px; max-width: 1100px; margin: 0 auto; padding: 6px 32px; }",
        ".toolbar, .toolbar button, .toolbar input { font-family: 'Geist','Inter',-apple-system,'Segoe UI','Helvetica Neue',Arial,sans-serif; }",
        ".toolbar button { font-size: 0.78em; padding: 4px 10px; border: 1px solid #d0d0d0; background: #fafafa; color: #333; cursor: pointer; border-radius: 3px; white-space: nowrap; }",
        ".toolbar button:hover { background: #eee; }",
        ".toolbar button.active { background: #0969da; color: #fff; border-color: #0969da; }",
        ".toolbar input { font-size: 0.78em; padding: 4px 8px; border: 1px solid #d0d0d0; border-radius: 3px; width: 200px; outline: none; flex: 1; min-width: 0; }",
        ".toolbar input:focus { border-color: #0969da; }",
        ".toolbar .sep { width: 1px; height: 20px; background: #ddd; margin: 0 4px; }",
        ".toolbar .match-count { font-size: 0.72em; color: #999; }",
        ".toolbar-wrap { position: sticky; top: 0; z-index: 100; background: #fff; border-bottom: 1px solid #e0e0e0; }",
        ".turn.search-hidden { display: none; }",
        "mark.search-hl { background: #fff3a8; color: inherit; padding: 0; border-radius: 0; line-height: inherit; }",
        "@media (max-width: 800px) { .main { padding: 12px; } .toolbar input { width: 120px; } }",
        # Sidebar TOC (injected by batch post-processing; CSS is always present, no-op if no sidebar)
        # Hamburger inherits .toolbar button styling via the cascade — no extra rules needed.
        # Sidebar panel: fixed left drawer, same font stack and border as toolbar.
        ".toc-sidebar { position: fixed; top: 0; left: -300px; width: 300px; height: 100vh; background: #fff; border-right: 1px solid #e0e0e0; z-index: 200; display: flex; flex-direction: column; font-family: 'Geist','Inter',-apple-system,'Segoe UI','Helvetica Neue',Arial,sans-serif; }",
        ".toc-sidebar.open { left: 0; }",
        ".toc-overlay { display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.12); z-index: 199; }",
        ".toc-sidebar.open ~ .toc-overlay { display: block; }",
        # Header matches toolbar: same padding, border, height
        ".toc-header { display: flex; align-items: center; justify-content: space-between; padding: 6px 12px; border-bottom: 1px solid #e0e0e0; flex-shrink: 0; height: 38px; box-sizing: border-box; }",
        # Title span matches toolbar button sizing so toc-header height matches toolbar-wrap (38px).
        ".toc-header span { font-size: 0.78em; line-height: normal; font-weight: 600; color: #333; padding: 4px 0; border-top: 1px solid transparent; border-bottom: 1px solid transparent; display: flex; align-items: center; gap: 6px; }",
        ".toc-header .engine-logo { width: 14px; height: 14px; }",
        ".toc-close { font-size: 1.1em; line-height: 1; padding: 0; border: none; background: none; color: #999; cursor: pointer; margin-left: auto; }",
        ".toc-close:hover { color: #333; }",
        # Scrollable list fills remaining space
        ".toc-list { list-style: none; padding: 0; margin: 0; overflow-y: auto; flex: 1; }",
        ".toc-list li { border-bottom: 1px solid #e0e0e0; margin: 0; }",
        ".toc-list a { display: block; padding: 8px 12px; text-decoration: none; color: #333; font-size: 0.78em; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }",
        ".toc-list a:hover { background: #f6f8fa; }",
        ".toc-list a.current { background: #e8f0fe; color: #1967d2; }",
        ".toc-list .toc-project { font-weight: 700; }",
        ".toc-list .toc-msg { font-weight: 300; }",
        "</style>",
        "<script>",
        "function toggleTurn(el) { const turn = el.closest('.turn'); const wasCollapsed = turn.classList.contains('collapsed'); turn.classList.toggle('collapsed'); if (wasCollapsed) { history.replaceState(null, '', '#' + turn.id); } }",
        "function toggleTools(el) { el.closest('.tools-section').classList.toggle('open'); }",
        "window.addEventListener('DOMContentLoaded', () => { const hash = location.hash.slice(1); if (!hash) return; const el = document.getElementById(hash); if (!el) return; if (el.classList.contains('turn')) { el.classList.remove('collapsed'); } setTimeout(() => el.scrollIntoView({ block: 'start' }), 50); });",
        "window.addEventListener('hashchange', () => { const hash = location.hash.slice(1); if (!hash) return; const el = document.getElementById(hash); if (!el) return; if (el.classList.contains('turn')) { el.classList.remove('collapsed'); } el.scrollIntoView({ block: 'start' }); });",
        "let allExpanded = false;",
        "function toggleExpandAll(btn) { const turns = document.querySelectorAll('.turn'); if (allExpanded) { turns.forEach(t => t.classList.add('collapsed')); btn.textContent = 'Expand All'; } else { turns.forEach(t => t.classList.remove('collapsed')); btn.textContent = 'Collapse All'; } allExpanded = !allExpanded; }",
        "let searchTimeout = null;",
        "function onSearch(val) { clearTimeout(searchTimeout); searchTimeout = setTimeout(() => doSearch(val), 150); }",
        "function clearHighlights() { document.querySelectorAll('mark.search-hl').forEach(m => { const parent = m.parentNode; parent.replaceChild(document.createTextNode(m.textContent), m); parent.normalize(); }); }",
        "function highlightText(node, query) { if (node.nodeType === 3) { const idx = node.textContent.toLowerCase().indexOf(query); if (idx === -1) return 0; const mark = document.createElement('mark'); mark.className = 'search-hl'; const after = node.splitText(idx); after.splitText(query.length); mark.appendChild(after.cloneNode(true)); after.parentNode.replaceChild(mark, after); return 1; } if (node.nodeType === 1 && node.tagName !== 'MARK' && node.tagName !== 'SCRIPT' && node.tagName !== 'STYLE') { let count = 0; const children = Array.from(node.childNodes); for (const child of children) { count += highlightText(child, query); } return count; } return 0; }",
        "/* Search state: track what we expanded so we can restore on clear */",
        "let searchExpanded = new Set();  /* turns we un-collapsed */",
        "let searchOpenedSections = new Set();  /* .tools-section we opened */",
        "let searchOpenedDetails = new Set();  /* <details> (trow/thinking) we opened */",
        "function doSearch(query) {"
        " const turns = document.querySelectorAll('.turn');"
        " const counter = document.getElementById('match-count');"
        " const page = document.querySelector('.page');"
        " page.style.visibility = 'hidden';"
        " clearHighlights();"
        # Collapse everything search previously opened
        " searchOpenedSections.forEach(s => s.classList.remove('open')); searchOpenedSections.clear();"
        " searchOpenedDetails.forEach(d => d.removeAttribute('open')); searchOpenedDetails.clear();"
        # Empty query: restore original state (re-collapse turns, re-open auto-expanded edits)
        " if (!query.trim()) {"
        "   turns.forEach(t => t.classList.remove('search-hidden'));"
        "   searchExpanded.forEach(t => t.classList.add('collapsed'));"
        "   searchExpanded.clear();"
        "   document.querySelectorAll('.tools-section.auto-open-edit').forEach(s => s.classList.add('open'));"
        "   document.querySelectorAll('details.auto-open-edit').forEach(d => d.setAttribute('open',''));"
        "   counter.textContent = '';"
        "   page.style.visibility = '';"
        "   return;"
        " }"
        " const q = query.toLowerCase();"
        " let matches = 0;"
        " turns.forEach(t => {"
        "   const text = t.textContent.toLowerCase();"
        "   if (text.includes(q)) {"
        "     t.classList.remove('search-hidden');"
        "     if (t.classList.contains('collapsed')) { t.classList.remove('collapsed'); searchExpanded.add(t); }"
        # Only expand tool sections/details that contain the match
        "     t.querySelectorAll('.tools-section').forEach(s => {"
        "       s.classList.remove('open');"
        "       const list = s.querySelector('.tools-list');"
        "       if (list && list.textContent.toLowerCase().includes(q)) {"
        "         s.classList.add('open'); searchOpenedSections.add(s);"
        "         list.querySelectorAll('details.trow, details.thinking-block').forEach(d => {"
        "           d.removeAttribute('open');"
        "           if (d.textContent.toLowerCase().includes(q)) { d.setAttribute('open',''); searchOpenedDetails.add(d); }"
        "         });"
        "       }"
        "     });"
        "     highlightText(t, q); matches++;"
        "   } else { t.classList.add('search-hidden'); }"
        " });"
        " counter.textContent = matches + ' turn' + (matches !== 1 ? 's' : '');"
        " page.style.visibility = '';"
        " const first = document.querySelector('mark.search-hl');"
        " if (first) first.scrollIntoView({ behavior: 'smooth', block: 'center' });"
        " }",
        "function jumpTop() { window.scrollTo(0, 0); }",
        "function jumpBottom() { window.scrollTo(0, document.body.scrollHeight); }",
        "</script>",
        "</head>",
        "<body>",
        '<div class="toolbar-wrap"><div class="toolbar"><input id="search-input" type="text" placeholder="Search" oninput="onSearch(this.value)"><span id="match-count" class="match-count"></span><div class="sep"></div><button onclick="jumpTop()">Top</button><button onclick="jumpBottom()">Bottom</button><div class="sep"></div><button onclick="toggleExpandAll(this)">Expand All</button></div></div>',
        '<div class="page"><div class="main">',
        '<div class="header">',
        f"<h1>{_engine_logo_html(engine_label)}{_format_title_html(title)}</h1>",
        f'<div class="meta">{header_meta_html}</div>',
        "</div>",
    ]


def build_html_scaffold_suffix() -> list[str]:
    return ["</div></div>", "</body></html>"]


# ---------------------------------------------------------------------------
# render_html
# ---------------------------------------------------------------------------


def render_html(
    data: dict[str, Any],
    input_path: str,
    output_path: str,
    args: argparse.Namespace,
    *,
    auto_title_fn: Callable,
    tool_summary_fn: Callable,
    tool_detail_fn: Callable,
    engine_label: str = "",
) -> str:
    """Build the complete HTML output from parsed turn data.

    Callbacks (auto_title_fn, tool_summary_fn, tool_detail_fn) are provided
    by the engine-specific script so this function stays format-agnostic.
    """
    turns = data["turns"]
    first_ts = ""
    last_ts = ""
    for turn in turns:
        ts = turn.get("user_ts", turn.get("ts", ""))
        if ts and not first_ts:
            first_ts = ts
        if ts:
            last_ts = ts

    title = args.title or auto_title_fn(input_path, turns, data["turn_count"], data)
    max_width = "1600px" if args.wide else "800px" if args.narrow else "1100px"
    header_meta_html = build_header_meta_html(data, args, first_ts, last_ts)
    out = build_html_scaffold_prefix(title, header_meta_html, args, max_width, engine_label)

    bot_icon = ICON_BOT_CODEX if "codex" in engine_label.lower() else ICON_BOT_CLAUDE
    gap_threshold_ms = 30 * 60 * 1000
    prev_ts = None
    turn_num = 0
    for turn in turns:
        current_ts = turn.get("user_ts", turn.get("ts", ""))
        if prev_ts and current_ts and not args.no_gaps:
            try:
                prev_dt = datetime.fromisoformat(prev_ts.replace("Z", "+00:00"))
                cur_dt = datetime.fromisoformat(current_ts.replace("Z", "+00:00"))
                gap_ms = (cur_dt - prev_dt).total_seconds() * 1000
                if gap_ms >= gap_threshold_ms:
                    for index in range(len(out) - 1, -1, -1):
                        if '<div class="turn ' in out[index]:
                            out[index] = out[index].replace('<div class="turn ', '<div class="turn before-gap ', 1)
                            break
                    out.append(f'<div class="time-gap">{gap_str(gap_ms)} gap</div>')
            except (TypeError, ValueError):
                pass
        if current_ts:
            prev_ts = current_ts

        if turn["type"] == "compaction":
            if args.no_compactions:
                continue
            for index in range(len(out) - 1, -1, -1):
                if '<div class="turn ' in out[index]:
                    out[index] = out[index].replace('<div class="turn ', '<div class="turn before-gap ', 1)
                    break
            label = "Context compacted"
            if not args.no_timestamps:
                label += f" ({turn['tokens']} tokens) - {ts_fmt(turn['ts'])}"
            elif turn["tokens"]:
                label += f" ({turn['tokens']} tokens)"
            out.append(f'<div class="compaction"><hr><span>{html.escape(label)}</span></div>')
            continue

        turn_num += 1
        turn_items = turn["items"]
        user_text = turn["user_text"]
        has_error = turn["has_errors"]
        preview = user_text[:160].replace("\n", " ")
        if len(user_text) > 160:
            preview += "..."
        out_tokens = turn["output_tokens"]
        total_adds = sum(item.get("diff_adds", 0) for item in turn_items if item["kind"] == "tool_call")
        total_dels = sum(item.get("diff_dels", 0) for item in turn_items if item["kind"] == "tool_call")
        diff_stat_html = (
            f'<span class="diff-stat"><span class="da">+{total_adds}</span> <span class="dd">-{total_dels}</span></span>'
            if total_adds or total_dels else ""
        )
        err_html = '<span class="err-dot"></span>' if has_error else ""
        trunc_html = '<span class="trunc-badge">truncated</span>' if turn.get("truncated") else ""
        tool_count = sum(1 for item in turn_items if item["kind"] == "tool_call")
        tc_html = f'<span class="tool-count">{tool_count} tools</span>' if tool_count else ""
        tok_html = (
            f'<span class="tool-count" style="color:{tok_color(out_tokens)}">{tok_str(out_tokens)}</span>'
            if out_tokens >= 1000 else ""
        )
        time_html = f"<span>{ts_short(turn['user_ts'])}</span>" if not args.no_timestamps else ""
        err_class = " has-err" if has_error else ""
        collapse_class = "" if args.expanded else " collapsed"
        out.append(
            f'<div class="turn{collapse_class}{err_class}" id="turn-{turn_num}">'
            '<div class="turn-head" onclick="toggleTurn(this)">'
            f'<span class="turn-num">#{turn_num}</span>'
            f'<span class="turn-preview">{html.escape(preview)}</span>'
            f'<span class="turn-meta">{err_html}{diff_stat_html}{trunc_html}{tc_html}{tok_html}{time_html}</span>'
            "</div>"
        )

        bot_icon_used = False
        if user_text:
            icon = "" if args.no_icons else ICON_USER
            user_html = iconize(render_markdown(user_text, args), icon)
            user_html = wrap_error(user_html, turn.get("user_is_error", False))
            out.append(f'<div class="turn-user-full">{user_html}</div>')

        out.append('<div class="turn-body">')
        index = 0
        while index < len(turn_items):
            item = turn_items[index]
            kind = item["kind"]

            if kind == "reply":
                icon = "" if args.no_icons or bot_icon_used else bot_icon
                bot_icon_used = bot_icon_used or bool(icon)
                reply_html = render_markdown(item["text"], args)
                phase = item.get("phase", "")
                if phase == "commentary":
                    reply_html = f'<div class="dim">Commentary</div>{reply_html}'
                elif phase == "final_answer":
                    reply_html = f'<div class="dim">Final Answer</div>{reply_html}'
                reply_html = iconize(reply_html, icon)
                reply_html = wrap_error(reply_html, item.get("is_error", False))
                out.append(f'<div class="reply">{reply_html}</div>')
                index += 1
                continue

            if kind == "thinking":
                if not args.no_thinking:
                    thinking = html.escape(item["text"])
                    if len(thinking) > 2000:
                        thinking = thinking[:2000] + f"\n...({len(item['text'])} chars)"
                    out.append(
                        '<details class="thinking-block">'
                        '<summary><span class="badge thinking">thinking</span>'
                        '<span class="tsum">Thinking</span></summary>'
                        f'<div class="tbody"><pre>{thinking}</pre></div></details>'
                    )
                index += 1
                continue

            if kind in ("tool_call", "tool_output"):
                group = []
                while index < len(turn_items) and turn_items[index]["kind"] in ("tool_call", "tool_output"):
                    group.append(turn_items[index])
                    index += 1
                if args.no_tools:
                    continue
                tool_calls = sum(1 for entry in group if entry["kind"] == "tool_call")
                count = tool_calls or len(group)
                label = "tool call" if tool_calls else "output"
                has_edits = not args.no_diffs and any(
                    entry["kind"] == "tool_call"
                    and tool_summary_fn(entry["block"])[1] == "edit"
                    for entry in group
                )
                section_class = "tools-section open auto-open-edit" if has_edits else "tools-section"
                out.append(f'<div class="{section_class}">')
                out.append(
                    f'<div class="tools-toggle" onclick="toggleTools(this)">{count} {label}{"s" if count != 1 else ""}</div>'
                )
                out.append('<div class="tools-list">')
                for grouped in group:
                    if grouped["kind"] == "tool_call":
                        out.append(render_tool_row(grouped, args, tool_summary_fn, tool_detail_fn))
                    else:
                        result_html = build_result_html(grouped["text"], grouped.get("is_error", False), args)
                        if not result_html:
                            continue
                        summary = grouped["text"][:140].replace("\n", " ")
                        if len(grouped["text"]) > 140:
                            summary += "..."
                        badge = "error" if grouped.get("is_error") else "output"
                        limit = len(grouped["text"]) if args.full_output else 3000
                        trunc = grouped["text"][:limit]
                        if len(grouped["text"]) > limit:
                            trunc += f"\n...({len(grouped['text'])} chars)"
                        pre_class = ' class="err"' if grouped.get("is_error") else ""
                        out.append(
                            '<details class="trow">'
                            f'<summary><span class="badge {badge}">{badge}</span>'
                            f'<span class="tsum">{html.escape(summary)}</span></summary>'
                            f'<div class="tbody"><pre{pre_class}>{html.escape(trunc)}</pre></div></details>'
                        )
                out.append("</div></div>")
                continue

            index += 1

        out.append("</div></div>")

    out.extend(build_html_scaffold_suffix())
    result = "\n".join(part for part in out if part)
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(result)
    return result


# ---------------------------------------------------------------------------
# Batch infrastructure
# ---------------------------------------------------------------------------


def _batch_inputs(args: argparse.Namespace, jsonl_root: str, min_size: int, recursive: bool) -> list[str]:
    if not (args.all or args.recent):
        return [os.path.abspath(path) for path in args.input]
    root = Path(jsonl_root)
    if recursive:
        candidates = [str(p) for p in root.rglob("*.jsonl")]
    else:
        candidates = [str(p) for p in root.glob("*/*.jsonl")]
    candidates = sorted(
        (p for p in candidates if os.path.getsize(p) > min_size),
        key=os.path.getmtime,
        reverse=True,
    )
    return candidates[: args.recent] if args.recent else candidates


def _run_batch_task(task: tuple[str, str, str, list[str], str]) -> str:
    """Worker for batch mode: spawns a subprocess of the calling script.

    We use subprocesses (not threads) because each render can be 100MB+ of
    JSONL parsing — subprocess isolation avoids GIL and memory fragmentation.
    The subprocess runs the same script with a single input file + forwarded flags.
    """
    jsonl_path, output_path, session_id, flags, script_path = task
    cmd = [sys.executable, script_path, "-o", output_path] + flags + [jsonl_path]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
    size_mb = os.path.getsize(jsonl_path) / 1_000_000
    if result.returncode == 0:
        return f"  ok {session_id} ({size_mb:.1f}MB)"
    return f"FAIL {session_id} ({size_mb:.1f}MB): {result.stderr[-200:] or result.stdout[-200:]}"


def _extract_html_title(path: str) -> str:
    """Read just enough of an HTML file to extract its <title> content."""
    try:
        with open(path, encoding="utf-8") as f:
            head = f.read(4096)
        match = re.search(r"<title>(.*?)</title>", head)
        return match.group(1) if match else os.path.basename(path)
    except Exception:
        return os.path.basename(path)


def _format_toc_entry(title: str) -> str:
    """Format title as <span class=toc-project>bold</span>: <span class=toc-msg>rest</span>."""
    title = html.unescape(title)
    if ": " in title:
        project, rest = title.split(": ", 1)
        return (f'<span class="toc-project">{html.escape(project)}</span>: '
                f'<span class="toc-msg">{html.escape(rest)}</span>')
    return html.escape(title)


def inject_toc_sidebar(output_paths: list[str], *, engine_label: str = "") -> None:
    """Post-process batch HTML files to inject a sidebar TOC linking all conversations.

    Injects a hamburger button into the toolbar and a sidebar div after <body>.
    Each file highlights its own entry as 'current'.
    """
    # Collect titles and filenames
    entries: list[tuple[str, str, str]] = []  # (filename, title, formatted_html)
    for path in sorted(output_paths):
        title = _extract_html_title(path)
        formatted = _format_toc_entry(title)
        entries.append((os.path.basename(path), title, formatted))

    hamburger = '<button class="toc-hamburger" onclick="toggleToc()" title="All transcripts">&#9776;</button>'
    toc_fn_js = (
        '<script>'
        'function toggleToc(){document.querySelector(".toc-sidebar").classList.toggle("open");}'
        'function closeToc(){document.querySelector(".toc-sidebar").classList.remove("open");}'
        '</script>'
    )
    # Injected in <head>: sets sidebar to left:0 before body is ever painted.
    toc_head_js = (
        '<script>'
        'if(new URLSearchParams(location.search).has("toc")){'
        'document.write(\'<style>.toc-sidebar{left:0}</style>\');}'
        '</script>'
    )
    # Runs after sidebar div: adds .open class and restores scroll position.
    toc_auto_open_js = (
        '<script>'
        'if(new URLSearchParams(location.search).has("toc")){'
        'document.querySelector(".toc-sidebar").classList.add("open");'
        # Restore sidebar scroll position from previous page
        'var l=document.querySelector(".toc-list");'
        'var s=sessionStorage.getItem("tocScroll");'
        'if(s)l.scrollTop=+s;'
        # Save scroll position before navigating away
        'l.querySelectorAll("a").forEach(function(a){'
        'a.addEventListener("click",function(){'
        'sessionStorage.setItem("tocScroll",l.scrollTop);});});}'
        '</script>'
    )

    for path in output_paths:
        current_file = os.path.basename(path)
        # Build sidebar HTML
        li_items = []
        for filename, _title, formatted in entries:
            cls = ' class="current"' if filename == current_file else ""
            li_items.append(f'<li><a href="{html.escape(filename)}?toc=1"{cls}>{formatted}</a></li>')
        sidebar_html = (
            f'{toc_fn_js}'
            '<div class="toc-sidebar">'
            '<div class="toc-header">'
            f'<span>{_engine_logo_html(engine_label)}{len(entries)} Transcripts</span>'
            '<button class="toc-close" onclick="closeToc()">&times;</button>'
            '</div>'
            f'<ul class="toc-list">{"".join(li_items)}</ul>'
            '</div>'
            '<div class="toc-overlay" onclick="closeToc()"></div>'
            f'{toc_auto_open_js}'
        )

        try:
            with open(path, encoding="utf-8") as f:
                content = f.read()
            # Inject <head> script so sidebar CSS is left:0 before first paint
            content = content.replace("</head>", f"{toc_head_js}</head>", 1)
            # Inject hamburger as first element in toolbar
            content = content.replace(
                '<div class="toolbar">',
                f'<div class="toolbar">{hamburger}',
                1,
            )
            # Inject sidebar + overlay after <body>
            content = content.replace("<body>", f"<body>{sidebar_html}", 1)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        except Exception as exc:
            print(f"  TOC inject failed for {path}: {exc}")


def generate_index(outdir: str, output_paths: list[str], *, engine_label: str = "") -> None:
    """Generate an index.html that redirects to the first transcript (with sidebar open)."""
    first = os.path.basename(sorted(output_paths)[0])
    index_html = (
        f'<!DOCTYPE html><html><head><meta charset="utf-8">'
        f'<meta http-equiv="refresh" content="0;url={html.escape(first)}?toc=1">'
        f'</head><body></body></html>'
    )
    index_path = os.path.join(outdir, "index.html")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(index_html)
    print(f"  Index: {index_path}")


def run_batch(
    args: argparse.Namespace,
    *,
    script_path: str,
    jsonl_root: str,
    min_size: int,
    recursive: bool,
    engine_label: str = "",
) -> int:
    inputs = _batch_inputs(args, jsonl_root, min_size, recursive)
    os.makedirs(args.outdir, exist_ok=True)
    # Cap workers at CPU count
    cpu_count = os.cpu_count() or 4
    jobs = args.jobs or min(cpu_count, len(inputs) or 1)
    jobs = max(jobs, 1)
    flags = serialize_forwarded_flags(args)
    tasks = []
    for path in inputs:
        session_id = os.path.basename(path).replace(".jsonl", "")
        output_path = os.path.join(args.outdir, f"{session_id}.html")
        tasks.append((path, output_path, session_id, flags, script_path))

    print(f"Rendering {len(tasks)} transcripts with {jobs} workers ...")
    started = time.time()

    results: list[str] = []
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(_run_batch_task, task): task for task in tasks}
        for future in as_completed(futures):
            line = future.result()
            results.append(line)
            print(line)

    ok_count = sum(1 for line in results if line.startswith("  ok"))
    fail_count = len(results) - ok_count
    elapsed = time.time() - started
    print(f"\n{ok_count} ok, {fail_count} failed - {elapsed:.1f}s ({jobs} workers)")

    # Inject sidebar TOC linking all rendered conversations
    ok_paths = [t[1] for t in tasks if os.path.exists(t[1])]
    if not args.no_toc and len(ok_paths) > 1:
        inject_toc_sidebar(ok_paths, engine_label=engine_label)
        print(f"  TOC sidebar injected into {len(ok_paths)} files")

    # Generate index.html listing all rendered transcripts
    if ok_paths:
        generate_index(args.outdir, ok_paths, engine_label=engine_label)

    return 1 if fail_count else 0


# ---------------------------------------------------------------------------
# Single-file rendering + main entry point
# ---------------------------------------------------------------------------


def render_single(
    input_path: str,
    output_path: str,
    args: argparse.Namespace,
    *,
    parse_fn: Callable,
    auto_title_fn: Callable,
    tool_summary_fn: Callable,
    tool_detail_fn: Callable,
    engine_label: str = "",
) -> int:
    print(f"Reading {input_path} ...")
    data = parse_fn(input_path, args)
    print(
        "  Tokens: "
        f"{data['total_input']:,} in, {data['total_output']:,} out, "
        f"{data['total_cache_create']:,} cache_w, {data['total_cache_read']:,} cache_r"
    )
    if not args.no_cost and data["cost_total"] is not None:
        print(f"  Cost estimate: ${data['cost_total']:.2f}")
    if data["malformed_lines"]:
        print(f"  Preflight: skipped {data['malformed_lines']} malformed JSONL line(s)")
    for line in data["redactor"].summary_lines():
        print(line)
    render_html(
        data,
        input_path,
        output_path,
        args,
        auto_title_fn=auto_title_fn,
        tool_summary_fn=tool_summary_fn,
        tool_detail_fn=tool_detail_fn,
        engine_label=engine_label,
    )
    print(f"Done! {output_path}")
    print(
        f"  {data['turn_count']} turns, {data['total_tool_calls']} tool calls, "
        f"{data['compaction_count']} compactions"
    )
    return 0


def transcript_main(
    *,
    argv: list[str] | None = None,
    description: str,
    default_outdir: str,
    script_path: str,
    jsonl_root: str,
    min_file_size: int,
    recursive_glob: bool,
    parse_fn: Callable,
    auto_title_fn: Callable,
    tool_summary_fn: Callable,
    tool_detail_fn: Callable,
    engine_label: str = "",
) -> int:
    args = parse_args(description, default_outdir, argv)
    if args.all or args.recent or len(args.input) > 1:
        return run_batch(
            args,
            script_path=script_path,
            jsonl_root=jsonl_root,
            min_size=min_file_size,
            recursive=recursive_glob,
            engine_label=engine_label,
        )
    input_path = args.input[0]
    output_path = args.output or "./transcript.html"
    return render_single(
        input_path,
        output_path,
        args,
        parse_fn=parse_fn,
        auto_title_fn=auto_title_fn,
        tool_summary_fn=tool_summary_fn,
        tool_detail_fn=tool_detail_fn,
        engine_label=engine_label,
    )

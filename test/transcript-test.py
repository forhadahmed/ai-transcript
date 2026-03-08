#!/usr/bin/env python3
"""Deterministic and integration tests for transcript renderers."""

import argparse
import glob
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
CLAUDE_SCRIPT = ROOT / "claude-transcript"
CODEX_SCRIPT = ROOT / "codex-transcript"
CLAUDE_JSONL_ROOT = os.path.expanduser("~/.claude/projects")
CODEX_JSONL_ROOT = Path(os.path.expanduser("~/.codex/sessions"))


sys.path.insert(0, str(ROOT))
from transcript_lib import (
    extract_html_meta,
    favicon_link,
    engine_logo_html,
    format_toc_entry,
    format_title_html,
    inject_toc_sidebar,
    generate_index,
)


class TranscriptCliTestCase(unittest.TestCase):
    SCRIPT: Path

    def run_single(self, fixture_name: str, *extra_args: str, expected_code: int = 0):
        fixture = FIXTURES / fixture_name
        with tempfile.TemporaryDirectory() as tmpdir:
            output = Path(tmpdir) / "out.html"
            cmd = [sys.executable, str(self.SCRIPT), str(fixture), "-o", str(output), *extra_args]
            result = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(
                result.returncode,
                expected_code,
                msg=f"stdout:\n{result.stdout}\n\nstderr:\n{result.stderr}",
            )
            html = output.read_text() if output.exists() else ""
            return result, html


class ClaudeTranscriptCliTests(TranscriptCliTestCase):
    SCRIPT = CLAUDE_SCRIPT

    def test_default_output_sanitizes_raw_html_and_stays_offline(self):
        _, html = self.run_single("share_sample.jsonl")
        self.assertIn("&lt;script&gt;alert('x')&lt;/script&gt;", html)
        self.assertNotIn("<script>alert('x')</script>", html)
        self.assertIn("fonts.googleapis.com", html)

    def test_share_safe_redacts_sensitive_values(self):
        result, html = self.run_single("share_sample.jsonl", "--share-safe")
        self.assertIn("[REDACTED_EMAIL]", html)
        self.assertIn("[REDACTED_IP]", html)
        self.assertIn("[REDACTED_SECRET]", html)
        self.assertIn("/Users/REDACTED/project", html)
        self.assertNotIn("alice@example.com", html)
        self.assertNotIn("10.1.2.3", html)
        self.assertNotIn("sk-testsecretvalue", html)
        self.assertNotIn("/Users/alice", html)
        self.assertNotIn("est.</span>", html)
        self.assertIn("Preflight:", result.stdout)

    def test_share_public_hides_timestamps_and_tool_results(self):
        _, html = self.run_single("share_sample.jsonl", "--share-public")
        self.assertNotIn("10:00:00", html)
        self.assertNotIn("2026-03-01", html)
        self.assertNotIn("Output (", html)

    def test_batch_mode_forwards_title(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cmd = [
                sys.executable,
                str(self.SCRIPT),
                str(FIXTURES / "share_sample.jsonl"),
                str(FIXTURES / "share_sample_b.jsonl"),
                "--outdir",
                tmpdir,
                "--title",
                "Batch Title",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
            first = (Path(tmpdir) / "share_sample.html").read_text()
            second = (Path(tmpdir) / "share_sample_b.html").read_text()
            self.assertIn("<title>Batch Title</title>", first)
            self.assertIn("<title>Batch Title</title>", second)

    def test_strict_mode_fails_on_malformed_jsonl(self):
        result, _ = self.run_single("malformed_sample.jsonl", "--strict", expected_code=1)
        combined = result.stdout + result.stderr
        self.assertIn("invalid JSON", combined)

    def test_expanded_flag_removes_collapsed_class(self):
        _, html = self.run_single("flags_sample.jsonl", "--expanded")
        # Turns should not have collapsed class (but CSS rules still mention it)
        self.assertNotIn('class="turn collapsed', html)
        self.assertIn('class="turn"', html)

    def test_wide_flag_sets_max_width(self):
        _, html = self.run_single("share_sample.jsonl", "--wide")
        self.assertIn("max-width: 1600px", html)

    def test_narrow_flag_sets_max_width(self):
        _, html = self.run_single("share_sample.jsonl", "--narrow")
        self.assertIn("max-width: 800px", html)

    def test_wrap_code_flag(self):
        _, html = self.run_single("share_sample.jsonl", "--wrap-code")
        self.assertIn("white-space: pre-wrap", html)

    def test_no_diffs_hides_diff_blocks(self):
        _, html = self.run_single("flags_sample.jsonl", "--no-diffs")
        self.assertNotIn('class="diff-block"', html)

    def test_no_icons_hides_icons(self):
        _, html = self.run_single("flags_sample.jsonl", "--no-icons")
        self.assertNotIn('class="turn-icon"', html)

    def test_no_thinking_hides_thinking(self):
        _, html = self.run_single("flags_sample.jsonl", "--no-thinking")
        self.assertNotIn('class="thinking-block"', html)

    def test_no_compactions_hides_compaction(self):
        _, html = self.run_single("flags_sample.jsonl", "--no-compactions")
        self.assertNotIn('class="compaction"', html)

    def test_compaction_shown_by_default(self):
        _, html = self.run_single("flags_sample.jsonl")
        self.assertIn("Context compacted", html)

    def test_time_gap_shown_by_default(self):
        _, html = self.run_single("flags_sample.jsonl")
        self.assertIn('class="time-gap"', html)
        self.assertIn("2h gap", html)

    def test_no_gaps_hides_time_gap(self):
        _, html = self.run_single("flags_sample.jsonl", "--no-gaps")
        self.assertNotIn('class="time-gap"', html)

    def test_allow_unsafe_html_renders_raw(self):
        _, html = self.run_single("share_sample.jsonl", "--allow-unsafe-html")
        self.assertIn("<b>bold</b>", html)

    def test_default_includes_google_fonts(self):
        _, html = self.run_single("share_sample.jsonl")
        self.assertIn("fonts.googleapis.com", html)
        self.assertIn("Source+Code+Pro", html)

    def test_font_size_flag(self):
        _, html = self.run_single("share_sample.jsonl", "--font-size", "18")
        self.assertIn("font-size: 18px", html)

    def test_redact_pattern_custom(self):
        _, html = self.run_single("share_sample.jsonl", "--redact-pattern", r"alice")
        self.assertNotIn("alice", html)
        self.assertIn("[REDACTED]", html)

    def test_full_output_no_truncation(self):
        _, html = self.run_single("flags_sample.jsonl", "--full-output")
        self.assertNotIn("...(", html)

    def test_default_has_thinking_block(self):
        _, html = self.run_single("flags_sample.jsonl")
        self.assertIn('class="thinking-block"', html)
        self.assertIn("think about this carefully", html)

    def test_default_has_diff_block(self):
        _, html = self.run_single("flags_sample.jsonl")
        self.assertIn('class="diff-block"', html)


class ExtractHtmlMetaTests(unittest.TestCase):
    """Tests for extract_html_meta — date, date_raw, turns, tokens extraction."""

    def _write_html(self, tmpdir, filename, meta_span, turns=10, out_tokens="2,400"):
        """Write a minimal HTML file with a meta div matching the renderer's format."""
        html_content = (
            '<!DOCTYPE html><html><head><title>Test Title</title></head><body>'
            '<div class="page"><div class="main">'
            '<div class="header"><h1>Test</h1>'
            f'<div class="meta"><span>{meta_span}</span>'
            f'<span><b>{turns}</b> turns</span>'
            f'<span><b>5</b> tool calls</span>'
            f'<span>{out_tokens} out tokens</span></div></div>'
            '</div></div></body></html>'
        )
        path = os.path.join(tmpdir, filename)
        with open(path, "w") as f:
            f.write(html_content)
        return path

    def test_extracts_date_and_date_raw(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_html(tmpdir, "a.html",
                                    "2026-03-07 04:44:05 - 2026-03-07 06:00:00")
            meta = extract_html_meta(path)
            self.assertEqual(meta["date"], "Mar 7")
            self.assertEqual(meta["date_raw"], "2026-03-07 04:44:05")

    def test_extracts_turns_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_html(tmpdir, "a.html", "2026-01-15 10:00:00", turns=42)
            meta = extract_html_meta(path)
            self.assertEqual(meta["turns"], "42")

    def test_extracts_tokens_as_K(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_html(tmpdir, "a.html", "2026-01-01 00:00:00",
                                    out_tokens="186,429")
            meta = extract_html_meta(path)
            self.assertEqual(meta["tokens"], "186K")

    def test_extracts_tokens_as_M(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_html(tmpdir, "a.html", "2026-01-01 00:00:00",
                                    out_tokens="1,234,567")
            meta = extract_html_meta(path)
            self.assertEqual(meta["tokens"], "1.2M")

    def test_missing_date_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = self._write_html(tmpdir, "a.html", " - ")
            meta = extract_html_meta(path)
            self.assertEqual(meta["date"], "")
            self.assertEqual(meta["date_raw"], "")

    def test_nonexistent_file_returns_basename(self):
        meta = extract_html_meta("/nonexistent/path/foo.html")
        self.assertEqual(meta["title"], "foo.html")

    def test_all_months_extracted_correctly(self):
        months = [
            (1, "Jan"), (2, "Feb"), (3, "Mar"), (4, "Apr"),
            (5, "May"), (6, "Jun"), (7, "Jul"), (8, "Aug"),
            (9, "Sep"), (10, "Oct"), (11, "Nov"), (12, "Dec"),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            for num, name in months:
                path = self._write_html(tmpdir, f"m{num}.html",
                                        f"2026-{num:02d}-15 10:00:00")
                meta = extract_html_meta(path)
                self.assertEqual(meta["date"], f"{name} 15",
                                 msg=f"Month {num} should be {name}")


class FormatTocEntryTests(unittest.TestCase):
    """Tests for format_toc_entry — project:msg splitting."""

    def test_splits_project_and_message(self):
        result = format_toc_entry("myproject: do something cool")
        self.assertIn('class="toc-project"', result)
        self.assertIn("myproject", result)
        self.assertIn('class="toc-msg"', result)
        self.assertIn("do something cool", result)

    def test_no_colon_returns_plain_text(self):
        result = format_toc_entry("just a plain title")
        self.assertNotIn('class="toc-project"', result)
        self.assertIn("just a plain title", result)

    def test_escapes_html_entities(self):
        result = format_toc_entry("proj: <script>alert('x')</script>")
        self.assertNotIn("<script>", result)
        self.assertIn("&lt;script&gt;", result)

    def test_unescapes_input_entities(self):
        result = format_toc_entry("proj: foo &amp; bar")
        self.assertIn("foo &amp; bar", result)


class FormatTitleHtmlTests(unittest.TestCase):
    """Tests for format_title_html — bold project, light message."""

    def test_bold_project(self):
        result = format_title_html("myproject: some task")
        self.assertIn("<b>myproject</b>", result)
        self.assertIn('class="title-msg"', result)
        self.assertIn("some task", result)

    def test_no_colon_returns_escaped(self):
        result = format_title_html("plain title")
        self.assertNotIn("<b>", result)
        self.assertEqual(result, "plain title")


class FaviconAndLogoTests(unittest.TestCase):
    """Tests for favicon_link and engine_logo_html."""

    def test_claude_favicon_is_png(self):
        link = favicon_link("Claude Code")
        self.assertIn('rel="icon"', link)
        self.assertIn("image/png", link)
        self.assertIn("base64", link)

    def test_codex_favicon_is_svg(self):
        link = favicon_link("Codex")
        self.assertIn('rel="icon"', link)
        self.assertIn("image/svg+xml", link)

    def test_empty_engine_returns_empty(self):
        self.assertEqual(favicon_link(""), "")
        self.assertEqual(engine_logo_html(""), "")

    def test_claude_logo_html(self):
        logo = engine_logo_html("Claude Code")
        self.assertIn("engine-logo", logo)

    def test_codex_logo_html(self):
        logo = engine_logo_html("Codex")
        self.assertIn("engine-logo", logo)


class TocSidebarTests(unittest.TestCase):
    """Tests for inject_toc_sidebar — sidebar injection, sorting, CSS."""

    def _render_batch(self, tmpdir, dates):
        """Render minimal HTML files and inject TOC sidebar."""
        paths = []
        for i, (date_str, title) in enumerate(dates):
            html_content = (
                '<!DOCTYPE html><html><head><title>{title}</title></head>'
                '<body><div class="toolbar-wrap"><div class="toolbar">'
                '</div></div><div class="page"><div class="main">'
                '<div class="header"><h1>{title}</h1>'
                '<div class="meta"><span>{date_str}</span>'
                '<span><b>10</b> turns</span>'
                '<span>1,000 out tokens</span></div></div>'
                '</div></div></body></html>'
            ).format(title=title, date_str=date_str)
            path = os.path.join(tmpdir, f"file{i}.html")
            with open(path, "w") as f:
                f.write(html_content)
            paths.append(path)
        inject_toc_sidebar(paths, engine_label="Claude Code")
        return paths

    def test_sidebar_div_injected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = self._render_batch(tmpdir, [
                ("2026-03-07 10:00:00", "Test A"),
            ])
            html = Path(paths[0]).read_text()
            self.assertIn('class="toc-sidebar"', html)
            self.assertIn('class="toc-header"', html)
            self.assertIn('class="toc-list"', html)

    def test_hamburger_button_injected(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = self._render_batch(tmpdir, [
                ("2026-03-07 10:00:00", "Test A"),
            ])
            html = Path(paths[0]).read_text()
            self.assertIn('class="toc-hamburger"', html)
            self.assertIn("toggleToc()", html)

    def test_head_css_injection_for_instant_open(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = self._render_batch(tmpdir, [
                ("2026-03-07 10:00:00", "Test A"),
            ])
            html = Path(paths[0]).read_text()
            self.assertIn('toc-instant', html)
            self.assertIn('document.write', html)

    def test_entries_sorted_most_recent_first(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = self._render_batch(tmpdir, [
                ("2026-01-01 10:00:00", "Oldest"),
                ("2026-03-07 10:00:00", "Newest"),
                ("2026-02-15 10:00:00", "Middle"),
            ])
            html = Path(paths[0]).read_text()
            # Search within the toc-list only to avoid matching <title> tags
            toc_start = html.find('class="toc-list"')
            toc_end = html.find('</ul>', toc_start)
            toc_html = html[toc_start:toc_end]
            newest_pos = toc_html.find("Newest")
            middle_pos = toc_html.find("Middle")
            oldest_pos = toc_html.find("Oldest")
            self.assertGreater(newest_pos, 0)
            self.assertLess(newest_pos, middle_pos,
                            "Newest should appear before Middle in sidebar")
            self.assertLess(middle_pos, oldest_pos,
                            "Middle should appear before Oldest in sidebar")

    def test_current_file_marked(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = self._render_batch(tmpdir, [
                ("2026-03-07 10:00:00", "First"),
                ("2026-03-06 10:00:00", "Second"),
            ])
            html = Path(paths[0]).read_text()
            # The current file's link should have class="current"
            self.assertIn('class="current"', html)

    def test_toc_links_have_query_param(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = self._render_batch(tmpdir, [
                ("2026-03-07 10:00:00", "Test A"),
            ])
            html = Path(paths[0]).read_text()
            self.assertIn("?toc=1", html)

    def test_meta_info_in_entries(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = self._render_batch(tmpdir, [
                ("2026-03-07 10:00:00", "Test A"),
            ])
            html = Path(paths[0]).read_text()
            self.assertIn('class="toc-meta"', html)
            self.assertIn("10 turns", html)

    def test_engine_logo_in_sidebar_header(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = self._render_batch(tmpdir, [
                ("2026-03-07 10:00:00", "Test A"),
            ])
            html = Path(paths[0]).read_text()
            self.assertIn("engine-logo", html)

    def test_close_button_in_sidebar(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = self._render_batch(tmpdir, [
                ("2026-03-07 10:00:00", "Test A"),
            ])
            html = Path(paths[0]).read_text()
            self.assertIn('class="toc-close"', html)
            self.assertIn("closeToc()", html)

    def test_scroll_preservation_js(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = self._render_batch(tmpdir, [
                ("2026-03-07 10:00:00", "Test A"),
            ])
            html = Path(paths[0]).read_text()
            self.assertIn("sessionStorage", html)
            self.assertIn("tocScroll", html)


class IndexGenerationTests(unittest.TestCase):
    """Tests for generate_index — redirect to most recent transcript."""

    def _make_html_files(self, tmpdir, dates):
        """Create minimal HTML files with dates for index generation."""
        paths = []
        for i, date_str in enumerate(dates):
            html_content = (
                '<!DOCTYPE html><html><head><title>T{i}</title></head><body>'
                '<div class="meta"><span>{date_str}</span>'
                '<span><b>5</b> turns</span>'
                '<span>1,000 out tokens</span></div>'
                '</body></html>'
            ).format(i=i, date_str=date_str)
            path = os.path.join(tmpdir, f"transcript{i}.html")
            with open(path, "w") as f:
                f.write(html_content)
            paths.append(path)
        return paths

    def test_index_redirects_to_most_recent(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = self._make_html_files(tmpdir, [
                "2026-01-01 10:00:00",  # transcript0 — oldest
                "2026-03-07 10:00:00",  # transcript1 — newest
                "2026-02-15 10:00:00",  # transcript2 — middle
            ])
            generate_index(tmpdir, paths, engine_label="Claude Code")
            index = Path(tmpdir, "index.html").read_text()
            self.assertIn("transcript1.html?toc=1", index)

    def test_index_has_meta_refresh(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = self._make_html_files(tmpdir, ["2026-03-07 10:00:00"])
            generate_index(tmpdir, paths, engine_label="Claude Code")
            index = Path(tmpdir, "index.html").read_text()
            self.assertIn('http-equiv="refresh"', index)


class RenderedHtmlCssTests(unittest.TestCase):
    """Tests for CSS features in rendered output: scrollbars, search clear, push layout."""

    def setUp(self):
        fixture = FIXTURES / "share_sample.jsonl"
        self.tmpdir = tempfile.mkdtemp()
        output = Path(self.tmpdir) / "out.html"
        cmd = [sys.executable, str(CLAUDE_SCRIPT), str(fixture), "-o", str(output)]
        subprocess.run(cmd, capture_output=True, text=True, check=True)
        self.html = output.read_text()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_thin_scrollbars_css(self):
        self.assertIn("scrollbar-width: thin", self.html)
        self.assertIn("::-webkit-scrollbar", self.html)

    def test_search_clear_button_css(self):
        self.assertIn(".search-clear", self.html)
        self.assertIn(":not(:placeholder-shown) ~ .search-clear", self.html)

    def test_search_clear_button_html(self):
        self.assertIn('id="search-clear"', self.html)
        self.assertIn("&times;", self.html)

    def test_push_layout_css(self):
        self.assertIn(".toc-sidebar.open ~ .toolbar-wrap", self.html)
        self.assertIn("margin-left: 380px", self.html)

    def test_sidebar_width_380px(self):
        self.assertIn("width: 380px", self.html)

    def test_sidebar_box_sizing_border_box(self):
        # Prevents 1px gap between sidebar border and content margin
        self.assertIn("box-sizing: border-box", self.html)

    def test_sidebar_no_transition(self):
        # Transition was removed to prevent close/reopen flash on navigation
        # Check there's no transition on the sidebar left property
        self.assertNotIn("transition: left", self.html)

    def test_favicon_in_output(self):
        self.assertIn('rel="icon"', self.html)

    def test_toc_header_height_38px(self):
        self.assertIn("height: 38px", self.html)

    def test_toc_list_items_no_margin(self):
        # Browser default li margin caused row gaps
        self.assertIn(".toc-list li {", self.html)
        self.assertIn("margin: 0", self.html)


class CodexTranscriptCliTests(TranscriptCliTestCase):
    SCRIPT = CODEX_SCRIPT

    def test_default_output_sanitizes_raw_html_and_stays_offline(self):
        _, html = self.run_single("codex_share_sample.jsonl")
        self.assertIn("&lt;script&gt;alert('x')&lt;/script&gt;", html)
        self.assertNotIn("<script>alert('x')</script>", html)
        self.assertIn("fonts.googleapis.com", html)

    def test_share_safe_redacts_sensitive_values(self):
        result, html = self.run_single("codex_share_sample.jsonl", "--share-safe")
        self.assertIn("[REDACTED_EMAIL]", html)
        self.assertIn("[REDACTED_IP]", html)
        self.assertIn("[REDACTED_SECRET]", html)
        self.assertIn("/Users/REDACTED/project", html)
        self.assertNotIn("alice@example.com", html)
        self.assertNotIn("10.1.2.3", html)
        self.assertNotIn("sk-testsecretvalue", html)
        self.assertNotIn("/Users/alice", html)
        self.assertIn("Preflight:", result.stdout)

    def test_share_public_hides_timestamps_and_tool_results(self):
        _, html = self.run_single("codex_share_sample.jsonl", "--share-public")
        self.assertNotIn("10:00:01", html)
        self.assertNotIn("2026-03-01", html)
        self.assertNotIn("Output (", html)

    def test_batch_mode_forwards_title(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cmd = [
                sys.executable,
                str(self.SCRIPT),
                str(FIXTURES / "codex_share_sample.jsonl"),
                str(FIXTURES / "codex_share_sample_b.jsonl"),
                "--outdir",
                tmpdir,
                "--title",
                "Batch Title",
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, msg=result.stdout + "\n" + result.stderr)
            first = (Path(tmpdir) / "codex_share_sample.html").read_text()
            second = (Path(tmpdir) / "codex_share_sample_b.html").read_text()
            self.assertIn("<title>Batch Title</title>", first)
            self.assertIn("<title>Batch Title</title>", second)

    def test_strict_mode_fails_on_malformed_jsonl(self):
        result, _ = self.run_single("malformed_sample.jsonl", "--strict", expected_code=1)
        combined = result.stdout + result.stderr
        self.assertIn("invalid JSON", combined)


def integration_render(script: Path, jsonl_path: str, out_html: str, extra_args=None):
    cmd = [sys.executable, str(script), jsonl_path, "-o", out_html] + (extra_args or [])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    html = out_html and os.path.exists(out_html) and Path(out_html).read_text() or ""
    return html, result.returncode, result.stderr


def integration_check(errors: list[str], name: str, condition: bool, msg: str) -> None:
    if not condition:
        errors.append(f"  FAIL: {name} — {msg}")


def run_deterministic_suite() -> bool:
    suite = unittest.TestSuite()
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(ClaudeTranscriptCliTests))
    suite.addTests(unittest.defaultTestLoader.loadTestsFromTestCase(CodexTranscriptCliTests))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return result.wasSuccessful()


def run_claude_integration_suite() -> bool:
    jsonl_files = sorted(
        path for path in glob.glob(f"{CLAUDE_JSONL_ROOT}/*/*.jsonl")
        if os.path.getsize(path) > 1024
    )
    print(f"\nClaude integration corpus: {len(jsonl_files)} transcript(s)")
    if not jsonl_files:
        print(f"No local transcripts found under {CLAUDE_JSONL_ROOT}")
        return True

    passed = 0
    failed = 0

    with tempfile.TemporaryDirectory() as tmpdir:
        for jsonl in jsonl_files:
            session_id = os.path.basename(jsonl).replace(".jsonl", "")
            out_html = os.path.join(tmpdir, f"{session_id}.html")
            html, rc, stderr = integration_render(CLAUDE_SCRIPT, jsonl, out_html)
            errors = []
            integration_check(errors, "exit_code", rc == 0, f"exit code {rc}: {stderr[-200:]}")
            if rc == 0:
                for tag in ["pre", "code", "div", "details", "span"]:
                    opens = len(re.findall(f"<{tag}[ >]", html))
                    closes = len(re.findall(f"</{tag}>", html))
                    integration_check(errors, f"balanced_{tag}", opens == closes, f"{opens} opens vs {closes} closes")
                integration_check(errors, "has_doctype", html.startswith("<!DOCTYPE html>"), "missing DOCTYPE")
                integration_check(errors, "has_closing_html", "</html>" in html, "missing </html>")
            if errors:
                failed += 1
                print(f"FAIL claude {session_id}")
                for error in errors:
                    print(error)
            else:
                passed += 1

        probe = os.path.join(tmpdir, "claude-flag-probe.html")
        base_html, rc, stderr = integration_render(CLAUDE_SCRIPT, jsonl_files[0], probe)
        if rc != 0:
            failed += 1
            print(f"FAIL claude flags — {stderr[-200:]}")
        else:
            checks = [
                ("no-thinking", ["--no-thinking"], lambda html: 'class="thinking-block"' not in html),
                ("no-tools", ["--no-tools"], lambda html: 'class="tools-section"' not in html),
                ("no-diffs", ["--no-diffs"], lambda html: 'class="diff-block"' not in html),
                ("no-icons", ["--no-icons"], lambda html: 'class="turn-icon"' not in html),
                ("title", ["--title", "Integration Title"], lambda html: "<title>Integration Title</title>" in html),
                ("share-safe", ["--share-safe"], lambda html: "fonts.googleapis.com" in html),
            ]
            for name, extra_args, predicate in checks:
                out_html = os.path.join(tmpdir, f"claude-{name}.html")
                html, rc, stderr = integration_render(CLAUDE_SCRIPT, jsonl_files[0], out_html, extra_args)
                if rc != 0 or not predicate(html):
                    failed += 1
                    print(f"FAIL claude {name} — {stderr[-200:]}")
                else:
                    passed += 1

    print(f"Claude integration summary: {passed} passed, {failed} failed")
    return failed == 0


def run_codex_integration_suite() -> bool:
    jsonl_files = sorted(
        str(path) for path in CODEX_JSONL_ROOT.rglob("*.jsonl")
        if path.stat().st_size > 256
    )
    print(f"\nCodex integration corpus: {len(jsonl_files)} transcript(s)")
    if not jsonl_files:
        print(f"No local transcripts found under {CODEX_JSONL_ROOT}")
        return True

    passed = 0
    failed = 0

    with tempfile.TemporaryDirectory() as tmpdir:
        sample = jsonl_files[min(5, len(jsonl_files) - 1)]
        for jsonl in jsonl_files[: min(len(jsonl_files), 20)]:
            session_id = os.path.basename(jsonl).replace(".jsonl", "")
            out_html = os.path.join(tmpdir, f"{session_id}.html")
            html, rc, stderr = integration_render(CODEX_SCRIPT, jsonl, out_html)
            errors = []
            integration_check(errors, "exit_code", rc == 0, f"exit code {rc}: {stderr[-200:]}")
            if rc == 0:
                for tag in ["pre", "code", "div", "details", "span"]:
                    opens = len(re.findall(f"<{tag}[ >]", html))
                    closes = len(re.findall(f"</{tag}>", html))
                    integration_check(errors, f"balanced_{tag}", opens == closes, f"{opens} opens vs {closes} closes")
                integration_check(errors, "has_doctype", html.startswith("<!DOCTYPE html>"), "missing DOCTYPE")
                integration_check(errors, "has_closing_html", "</html>" in html, "missing </html>")
            if errors:
                failed += 1
                print(f"FAIL codex {session_id}")
                for error in errors:
                    print(error)
            else:
                passed += 1

        checks = [
            ("no-thinking", ["--no-thinking"], lambda html: 'class="thinking-block"' not in html),
            ("no-tools", ["--no-tools"], lambda html: 'class="tools-section"' not in html),
            ("no-icons", ["--no-icons"], lambda html: 'class="turn-icon"' not in html),
            ("title", ["--title", "Integration Title"], lambda html: "<title>Integration Title</title>" in html),
            ("share-safe", ["--share-safe"], lambda html: "fonts.googleapis.com" in html),
        ]
        for name, extra_args, predicate in checks:
            out_html = os.path.join(tmpdir, f"codex-{name}.html")
            html, rc, stderr = integration_render(CODEX_SCRIPT, sample, out_html, extra_args)
            if rc != 0 or not predicate(html):
                failed += 1
                print(f"FAIL codex {name} — {stderr[-200:]}")
            else:
                passed += 1

    print(f"Codex integration summary: {passed} passed, {failed} failed")
    return failed == 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--integration",
        action="store_true",
        help="Run the live local-corpus integration checks after deterministic tests",
    )
    args = parser.parse_args(argv)

    deterministic_ok = run_deterministic_suite()
    if not args.integration:
        return 0 if deterministic_ok else 1

    claude_ok = run_claude_integration_suite()
    codex_ok = run_codex_integration_suite()
    return 0 if deterministic_ok and claude_ok and codex_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

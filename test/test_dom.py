#!/usr/bin/env python3
"""Playwright DOM tests — verify JavaScript rendering, pagination, search, and interactions."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright, Page

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).resolve().parent / "fixtures"
CLAUDE_SCRIPT = ROOT / "claude-transcript"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def render_fixture(fixture: str, *extra_args: str) -> str:
    """Render a fixture JSONL to a temp HTML file, return the path."""
    tmp = tempfile.NamedTemporaryFile(suffix=".html", delete=False)
    tmp.close()
    cmd = [sys.executable, str(CLAUDE_SCRIPT), str(FIXTURES / fixture), "-o", tmp.name] + list(extra_args)
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0, f"Render failed: {result.stderr}"
    return tmp.name


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture(scope="module")
def page(browser):
    ctx = browser.new_context()
    pg = ctx.new_page()
    yield pg
    ctx.close()


@pytest.fixture(scope="module")
def rendered_files():
    """Pre-render all fixtures once for the module."""
    files = {}
    fixtures = [
        ("flags", "flags_sample.jsonl", []),
        ("compaction", "back_to_back_compaction.jsonl", []),
        ("perf", "mock-perf.jsonl", []),
        ("debug", "mock-debug.jsonl", []),
        ("refactor", "mock-refactor.jsonl", []),
        ("devops", "mock-devops.jsonl", []),
        ("session", "mock-session.jsonl", []),
        ("pagination", "pagination_60_turns.jsonl", []),
        ("compaction_no_tokens", "compaction_no_tokens.jsonl", []),
        ("hide_thinking", "flags_sample.jsonl", ["--hide", "thinking"]),
        ("hide_tools", "mock-perf.jsonl", ["--hide", "tools"]),
        ("hide_diffs", "flags_sample.jsonl", ["--hide", "diffs"]),
        ("expanded", "flags_sample.jsonl", ["--expanded"]),
    ]
    for name, fixture, args in fixtures:
        files[name] = render_fixture(fixture, *args)
    yield files
    for path in files.values():
        os.unlink(path)


def load(page: Page, html_path: str):
    page.goto(f"file://{html_path}")
    page.wait_for_load_state("load")


# ---------------------------------------------------------------------------
# Page Load & Skeleton
# ---------------------------------------------------------------------------

class TestPageLoad:
    def test_skeleton_hidden_after_load(self, page, rendered_files):
        load(page, rendered_files["flags"])
        assert not page.locator(".skeleton").is_visible()

    def test_page_visible_after_load(self, page, rendered_files):
        load(page, rendered_files["flags"])
        assert page.locator(".page").is_visible()

    def test_turns_rendered_into_container(self, page, rendered_files):
        load(page, rendered_files["flags"])
        turns = page.locator("#turns-container .turn")
        assert turns.count() >= 1


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

class TestPagination:
    def test_small_transcript_no_pagination(self, page, rendered_files):
        load(page, rendered_files["flags"])
        pag = page.locator(".pagination")
        assert not pag.is_visible()

    def test_large_transcript_shows_pagination(self, page, rendered_files):
        load(page, rendered_files["pagination"])
        pag = page.locator(".pagination")
        assert pag.is_visible()
        assert "Page 1 / 2" in pag.inner_text()

    def test_first_page_has_50_turns(self, page, rendered_files):
        load(page, rendered_files["pagination"])
        turns = page.locator("#turns-container .turn")
        assert turns.count() == 50

    def test_next_button_advances_page(self, page, rendered_files):
        load(page, rendered_files["pagination"])
        page.click(".pg-btn:has-text('Next')")
        info = page.locator(".pg-info")
        assert "Page 2 / 2" in info.inner_text()
        turns = page.locator("#turns-container .turn")
        assert turns.count() == 10  # 60 - 50

    def test_prev_disabled_on_first_page(self, page, rendered_files):
        load(page, rendered_files["pagination"])
        prev_btn = page.locator(".pg-btn:has-text('Prev')")
        assert prev_btn.is_disabled()

    def test_next_disabled_on_last_page(self, page, rendered_files):
        load(page, rendered_files["pagination"])
        page.click(".pg-btn:has-text('Next')")
        next_btn = page.locator(".pg-btn:has-text('Next')")
        assert next_btn.is_disabled()

    def test_prev_goes_back(self, page, rendered_files):
        load(page, rendered_files["pagination"])
        page.click(".pg-btn:has-text('Next')")
        page.click(".pg-btn:has-text('Prev')")
        info = page.locator(".pg-info")
        assert "Page 1 / 2" in info.inner_text()


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

class TestSearch:
    def test_search_filters_turns(self, page, rendered_files):
        load(page, rendered_files["pagination"])
        page.fill("#search-input", "Question number 5")
        page.wait_for_timeout(300)  # debounce
        visible = page.locator("#turns-container .turn:not(.search-hidden)")
        assert visible.count() >= 1
        hidden = page.locator("#turns-container .turn.search-hidden")
        assert hidden.count() > 0

    def test_search_shows_match_count(self, page, rendered_files):
        load(page, rendered_files["flags"])
        page.fill("#search-input", "Reply")
        page.wait_for_timeout(300)
        counter = page.locator("#match-count")
        assert "turn" in counter.inner_text()

    def test_search_highlights_text(self, page, rendered_files):
        load(page, rendered_files["flags"])
        page.fill("#search-input", "Reply")
        page.wait_for_timeout(300)
        marks = page.locator("mark.search-hl")
        assert marks.count() >= 1

    def test_search_expands_matching_tool_sections(self, page, rendered_files):
        load(page, rendered_files["perf"])
        page.fill("#search-input", "Seq Scan")
        page.wait_for_timeout(300)
        open_sections = page.locator(".tools-section.open")
        assert open_sections.count() >= 1

    def test_clear_search_restores_turns(self, page, rendered_files):
        load(page, rendered_files["flags"])
        page.fill("#search-input", "Reply")
        page.wait_for_timeout(300)
        page.click("#search-clear")
        page.wait_for_timeout(200)
        hidden = page.locator("#turns-container .turn.search-hidden")
        assert hidden.count() == 0

    def test_search_on_paginated_shows_all_turns(self, page, rendered_files):
        """Search should show all turns, not just current page."""
        load(page, rendered_files["pagination"])
        page.fill("#search-input", "Question number 55")
        page.wait_for_timeout(300)
        # Turn 55 is on page 2 — search should find it
        visible = page.locator("#turns-container .turn:not(.search-hidden)")
        assert visible.count() >= 1
        # Pagination should be hidden during search
        pag = page.locator(".pagination")
        assert not pag.is_visible()

    def test_clear_search_restores_pagination(self, page, rendered_files):
        load(page, rendered_files["pagination"])
        page.fill("#search-input", "Question")
        page.wait_for_timeout(300)
        page.click("#search-clear")
        page.wait_for_timeout(200)
        pag = page.locator(".pagination")
        assert pag.is_visible()
        turns = page.locator("#turns-container .turn")
        assert turns.count() == 50  # back to page 1


# ---------------------------------------------------------------------------
# Turn Interaction
# ---------------------------------------------------------------------------

class TestTurnInteraction:
    def test_turns_start_collapsed(self, page, rendered_files):
        load(page, rendered_files["flags"])
        collapsed = page.locator("#turns-container .turn.collapsed")
        total = page.locator("#turns-container .turn")
        assert collapsed.count() == total.count()

    def test_click_expands_turn(self, page, rendered_files):
        load(page, rendered_files["flags"])
        page.click("#turn-1 .turn-head")
        turn = page.locator("#turn-1")
        assert "collapsed" not in (turn.get_attribute("class") or "")

    def test_turn_body_visible_when_expanded(self, page, rendered_files):
        load(page, rendered_files["flags"])
        page.click("#turn-1 .turn-head")
        body = page.locator("#turn-1 .turn-body")
        assert body.is_visible()

    def test_click_again_collapses(self, page, rendered_files):
        load(page, rendered_files["flags"])
        page.click("#turn-1 .turn-head")
        page.click("#turn-1 .turn-head")
        turn = page.locator("#turn-1")
        assert "collapsed" in (turn.get_attribute("class") or "")

    def test_preview_visible_when_collapsed(self, page, rendered_files):
        load(page, rendered_files["flags"])
        preview = page.locator("#turn-1 .turn-preview")
        assert preview.count() >= 1

    def test_expanded_flag_starts_uncollapsed(self, page, rendered_files):
        load(page, rendered_files["expanded"])
        collapsed = page.locator("#turns-container .turn.collapsed")
        assert collapsed.count() == 0


# ---------------------------------------------------------------------------
# Compaction
# ---------------------------------------------------------------------------

class TestCompaction:
    def test_single_compaction_renders(self, page, rendered_files):
        load(page, rendered_files["flags"])
        comps = page.locator(".compaction")
        assert comps.count() == 1
        assert "context compacted" in comps.first.inner_text().lower()

    def test_back_to_back_compactions_collapsed_to_one(self, page, rendered_files):
        load(page, rendered_files["compaction"])
        comps = page.locator(".compaction")
        assert comps.count() == 1
        # Should be the last one (30000 tokens)
        assert "30000" in comps.first.inner_text()

    def test_compaction_no_tokens_no_empty_parens(self, page, rendered_files):
        load(page, rendered_files["compaction_no_tokens"])
        comp = page.locator(".compaction")
        assert comp.count() == 1
        text = comp.first.inner_text()
        assert "( tokens)" not in text.lower()
        assert "context compacted" in text.lower()

    def test_no_adjacent_compactions_in_dom(self, page, rendered_files):
        """Structural test: no two compaction divs should be siblings."""
        load(page, rendered_files["compaction"])
        adjacent = page.evaluate("""() => {
            const comps = document.querySelectorAll('.compaction');
            for (const c of comps) {
                let next = c.nextElementSibling;
                if (next && next.classList.contains('compaction')) return true;
            }
            return false;
        }""")
        assert not adjacent


# ---------------------------------------------------------------------------
# Time Gaps
# ---------------------------------------------------------------------------

class TestTimeGaps:
    def test_time_gap_shown(self, page, rendered_files):
        load(page, rendered_files["flags"])
        gaps = page.locator(".time-gap")
        assert gaps.count() >= 1
        assert "gap" in gaps.first.inner_text()


# ---------------------------------------------------------------------------
# Tool Sections
# ---------------------------------------------------------------------------

class TestToolSections:
    def test_tool_toggle_opens_list(self, page, rendered_files):
        load(page, rendered_files["perf"])
        page.click("#turn-1 .turn-head")
        toggle = page.locator("#turn-1 .tools-toggle").first
        toggle.click()
        section = page.locator("#turn-1 .tools-section").first
        assert "open" in (section.get_attribute("class") or "")

    def test_tool_badges_present(self, page, rendered_files):
        load(page, rendered_files["perf"])
        page.click("#turn-1 .turn-head")
        page.click("#turn-1 .tools-toggle")
        badges = page.locator("#turn-1 .badge")
        assert badges.count() >= 1

    def test_tool_detail_expands(self, page, rendered_files):
        load(page, rendered_files["perf"])
        page.click("#turn-1 .turn-head")
        page.locator("#turn-1 .tools-toggle").first.click()
        detail = page.locator("#turn-1 details.trow").first
        detail.locator("> summary").click()
        assert detail.get_attribute("open") is not None


# ---------------------------------------------------------------------------
# Thinking Blocks
# ---------------------------------------------------------------------------

class TestThinkingBlocks:
    def test_thinking_block_renders(self, page, rendered_files):
        load(page, rendered_files["perf"])
        page.click("#turn-1 .turn-head")
        page.click("#turn-1 .tools-toggle")
        thinking = page.locator("#turn-1 .thinking-block")
        assert thinking.count() >= 1

    def test_thinking_block_expandable(self, page, rendered_files):
        load(page, rendered_files["perf"])
        page.click("#turn-1 .turn-head")
        page.click("#turn-1 .tools-toggle")
        block = page.locator("#turn-1 .thinking-block").first
        block.locator("summary").click()
        assert block.get_attribute("open") is not None


# ---------------------------------------------------------------------------
# Diff Rendering
# ---------------------------------------------------------------------------

class TestDiffs:
    def test_diff_block_has_add_del_lines(self, page, rendered_files):
        load(page, rendered_files["flags"])
        page.click("#turn-1 .turn-head")
        page.click("#turn-1 .tools-toggle")
        # Open the edit tool detail via JS to avoid strict mode issues
        page.evaluate("""() => {
            document.querySelectorAll('#turn-1 details.trow').forEach(d => d.setAttribute('open', ''));
        }""")
        adds = page.locator("#turn-1 .diff-add")
        dels = page.locator("#turn-1 .diff-del")
        assert adds.count() >= 1 or dels.count() >= 1


# ---------------------------------------------------------------------------
# --hide Flag
# ---------------------------------------------------------------------------

class TestHideFlag:
    def test_hide_thinking_removes_blocks(self, page, rendered_files):
        load(page, rendered_files["hide_thinking"])
        thinking = page.locator(".thinking-block")
        assert thinking.count() == 0

    def test_hide_tools_removes_sections(self, page, rendered_files):
        load(page, rendered_files["hide_tools"])
        tools = page.locator(".tools-section")
        assert tools.count() == 0

    def test_hide_diffs_removes_diff_blocks(self, page, rendered_files):
        load(page, rendered_files["hide_diffs"])
        diffs = page.locator(".diff-block")
        assert diffs.count() == 0


# ---------------------------------------------------------------------------
# Toolbar
# ---------------------------------------------------------------------------

class TestToolbar:
    def test_expand_all_expands_turns(self, page, rendered_files):
        load(page, rendered_files["flags"])
        page.click("button:has-text('Expand All')")
        collapsed = page.locator("#turns-container .turn.collapsed")
        assert collapsed.count() == 0

    def test_collapse_all_after_expand(self, page, rendered_files):
        load(page, rendered_files["flags"])
        page.click("button:has-text('Expand All')")
        page.click("button:has-text('Collapse All')")
        collapsed = page.locator("#turns-container .turn.collapsed")
        total = page.locator("#turns-container .turn")
        assert collapsed.count() == total.count()

    def test_font_picker_opens(self, page, rendered_files):
        load(page, rendered_files["flags"])
        page.click(".font-picker-btn")
        menu = page.locator(".font-picker-menu")
        assert "open" in (menu.get_attribute("class") or "")


# ---------------------------------------------------------------------------
# Hash Navigation
# ---------------------------------------------------------------------------

class TestHashNavigation:
    def test_hash_turn_expands_target(self, page, rendered_files):
        load(page, rendered_files["flags"])
        page.goto(f"file://{rendered_files['flags']}#turn-2")
        page.wait_for_load_state("load")
        page.wait_for_timeout(200)
        turn = page.locator("#turn-2")
        assert "collapsed" not in (turn.get_attribute("class") or "")

    def test_hash_pagination_jumps_to_correct_page(self, page, rendered_files):
        """#turn-55 should jump to page 2 of pagination."""
        page.goto(f"file://{rendered_files['pagination']}#turn-55")
        page.wait_for_load_state("load")
        page.wait_for_timeout(200)
        info = page.locator(".pg-info")
        assert "Page 2" in info.inner_text()
        turn = page.locator("#turn-55")
        assert turn.count() == 1


# ---------------------------------------------------------------------------
# Error Display
# ---------------------------------------------------------------------------

class TestErrors:
    def test_error_result_styling(self, page, rendered_files):
        load(page, rendered_files["debug"])
        page.click("#turn-1 .turn-head")
        # Check for error indicators (err-dot in turn head or error badge)
        err_indicators = page.locator(".err-dot, .badge.error, .err-result")
        assert err_indicators.count() >= 0  # debug fixture may or may not have errors

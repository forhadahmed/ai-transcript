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
        self.assertNotIn("fonts.googleapis.com", html)

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
        self.assertNotIn("fonts.googleapis.com", html)
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


class CodexTranscriptCliTests(TranscriptCliTestCase):
    SCRIPT = CODEX_SCRIPT

    def test_default_output_sanitizes_raw_html_and_stays_offline(self):
        _, html = self.run_single("codex_share_sample.jsonl")
        self.assertIn("&lt;script&gt;alert('x')&lt;/script&gt;", html)
        self.assertNotIn("<script>alert('x')</script>", html)
        self.assertNotIn("fonts.googleapis.com", html)
        self.assertIn("Commentary", html)
        self.assertIn("Final Answer", html)

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
        self.assertNotIn("fonts.googleapis.com", html)
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
                ("share-safe", ["--share-safe"], lambda html: "fonts.googleapis.com" not in html),
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
            ("share-safe", ["--share-safe"], lambda html: "fonts.googleapis.com" not in html),
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

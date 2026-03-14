import json
import os
import stat
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path


SUMMARIZER_SCRIPT = Path("/home/aurelio/workspace/pi-mono/.pi/skills/news-summarizer/scripts/summarize_news.py")


def extract_tagged_json(output: str, prefix: str) -> dict[str, object]:
    marker = f"{prefix}::"
    for line in output.splitlines():
        if line.startswith(marker):
            return json.loads(line[len(marker):].strip())
    raise AssertionError(f"Missing {prefix} in output: {output}")


class NewsSummarizerCacheTests(unittest.TestCase):
    def create_fake_pi_script(self, directory: Path) -> Path:
        script_path = directory / "fake-pi.py"
        script_path.write_text(
            textwrap.dedent(
                """
                #!/usr/bin/env python3
                import json
                import os
                import sys
                from pathlib import Path

                count_path = Path(os.environ["FAKE_PI_COUNT_PATH"])
                current = int(count_path.read_text() or "0") if count_path.exists() else 0
                count_path.write_text(str(current + 1))

                prompt = sys.argv[-1]
                start = prompt.find("[")
                if start == -1:
                    print("missing json payload", file=sys.stderr)
                    sys.exit(1)
                payload = json.loads(prompt[start:])

                mode = os.environ.get("FAKE_PI_MODE", "normal")
                is_article_batch = bool(payload) and isinstance(payload[0], dict) and "cache_key" in payload[0]
                if is_article_batch:
                    if mode == "invalid_batch":
                        print("this is not valid json")
                        sys.exit(0)
                    print(json.dumps([
                        {"cache_key": item["cache_key"], "summary": f"article::{item.get('title', '')}"}
                        for item in payload
                    ]))
                    sys.exit(0)

                print(f"aggregate summary for {len(payload)} items")
                """
            ).strip()
            + "\n",
            encoding="utf-8",
        )
        script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC)
        return script_path

    def run_summarizer(
        self,
        news_items: list[dict[str, str]],
        *,
        fake_pi: Path,
        count_path: Path,
        cache_db_path: Path,
        mode: str = "normal",
    ) -> tuple[dict[str, object], dict[str, object], str]:
        env = os.environ.copy()
        env.update(
            {
                "NEWS_SUMMARIZER_BACKEND": "pi_agent",
                "NEWS_SUMMARIZER_PI_COMMAND": str(fake_pi),
                "NEWS_SUMMARIZER_TIMEOUT_SECONDS": "10",
                "NEWS_SUMMARIZER_CACHE_DB_PATH": str(cache_db_path),
                "FAKE_PI_COUNT_PATH": str(count_path),
                "FAKE_PI_MODE": mode,
            }
        )
        result = subprocess.run(
            ["python3", str(SUMMARIZER_SCRIPT)],
            input="NEWS_JSON::" + json.dumps(news_items),
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, msg=result.stderr)
        summary_payload = extract_tagged_json(result.stdout, "SUMMARY_JSON")
        debug_payload = extract_tagged_json(result.stdout, "SUMMARY_DEBUG")
        return summary_payload, debug_payload, result.stdout

    def test_article_summary_cache_reuses_previously_processed_articles(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            fake_pi = self.create_fake_pi_script(temp_path)
            count_path = temp_path / "pi-count.txt"
            cache_db_path = temp_path / "article-summary-cache.db"
            news_items = [
                {
                    "title": "Apple unveils AI features",
                    "summary": "Investors react to new AI rollout plans.",
                    "publisher": "Yahoo Finance",
                    "link": "https://example.com/apple-ai?utm_source=newsletter",
                },
                {
                    "title": "Chip supply outlook improves",
                    "summary": "Suppliers expect tighter execution and stronger margins.",
                    "publisher": "Reuters",
                    "link": "https://example.com/chips",
                },
            ]

            first_summary, first_debug, _first_output = self.run_summarizer(
                news_items,
                fake_pi=fake_pi,
                count_path=count_path,
                cache_db_path=cache_db_path,
            )
            self.assertEqual(first_summary["method"], "llm")
            self.assertEqual(first_summary["summary"], "aggregate summary for 2 items")
            self.assertEqual(first_debug["article_cache_hits"], 0)
            self.assertEqual(first_debug["article_cache_misses"], 2)
            self.assertEqual(first_debug["article_cache_writes"], 2)
            self.assertFalse(first_debug["article_cache_fallback_used"])
            self.assertEqual(first_debug["final_stage"], "aggregate_from_cached_articles")
            self.assertEqual(count_path.read_text(encoding="utf-8").strip(), "2")
            self.assertTrue(cache_db_path.exists())

            second_summary, second_debug, _second_output = self.run_summarizer(
                news_items,
                fake_pi=fake_pi,
                count_path=count_path,
                cache_db_path=cache_db_path,
            )
            self.assertEqual(second_summary["method"], "llm")
            self.assertEqual(second_summary["summary"], "aggregate summary for 2 items")
            self.assertEqual(second_debug["article_cache_hits"], 2)
            self.assertEqual(second_debug["article_cache_misses"], 0)
            self.assertEqual(second_debug["article_cache_writes"], 0)
            self.assertFalse(second_debug["article_cache_fallback_used"])
            self.assertEqual(second_debug["final_stage"], "aggregate_from_cached_articles")
            self.assertEqual(count_path.read_text(encoding="utf-8").strip(), "3")

    def test_article_summary_cache_falls_back_to_legacy_whole_payload_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            fake_pi = self.create_fake_pi_script(temp_path)
            count_path = temp_path / "pi-count.txt"
            cache_db_path = temp_path / "article-summary-cache.db"
            news_items = [
                {
                    "title": "Tesla delivery estimate moves",
                    "summary": "Analysts update expectations after supplier checks.",
                    "publisher": "Benzinga",
                    "link": "https://example.com/tesla-deliveries",
                },
                {
                    "title": "Rates outlook shifts",
                    "summary": "Treasury moves affect growth-sector positioning.",
                    "publisher": "Reuters",
                    "link": "https://example.com/rates-outlook",
                },
            ]

            summary_payload, debug_payload, _output = self.run_summarizer(
                news_items,
                fake_pi=fake_pi,
                count_path=count_path,
                cache_db_path=cache_db_path,
                mode="invalid_batch",
            )
            self.assertEqual(summary_payload["method"], "llm")
            self.assertEqual(summary_payload["summary"], "aggregate summary for 2 items")
            self.assertTrue(debug_payload["article_cache_fallback_used"])
            self.assertEqual(debug_payload["final_stage"], "legacy_whole_payload")
            self.assertEqual(debug_payload["article_cache_hits"], 0)
            self.assertEqual(debug_payload["article_cache_misses"], 2)
            self.assertEqual(debug_payload["article_cache_writes"], 0)
            self.assertIn("article summary cache response was not a JSON array", summary_payload["llm_error"])
            self.assertEqual(count_path.read_text(encoding="utf-8").strip(), "2")


if __name__ == "__main__":
    unittest.main()

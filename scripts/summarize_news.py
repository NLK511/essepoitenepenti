#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path


def _load_input() -> list[dict[str, object]]:
    raw = sys.stdin.read().strip()
    prefix = "NEWS_JSON::"
    if raw.startswith(prefix):
        raw = raw[len(prefix):]
    if not raw:
        return []
    payload = json.loads(raw)
    return payload if isinstance(payload, list) else []


def _cache_key(item: dict[str, object]) -> str:
    relevant = {
        "title": str(item.get("title", "")),
        "summary": str(item.get("summary", "")),
        "publisher": str(item.get("publisher", "")),
        "link": str(item.get("link", "")),
    }
    return hashlib.sha256(json.dumps(relevant, sort_keys=True).encode("utf-8")).hexdigest()


def _ensure_cache(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS article_summary_cache (cache_key TEXT PRIMARY KEY, summary TEXT NOT NULL)"
    )
    conn.commit()
    return conn


def _call_pi(pi_command: str, payload: list[dict[str, object]]) -> tuple[int, str, str]:
    result = subprocess.run(
        [pi_command, json.dumps(payload)],
        capture_output=True,
        text=True,
        env=os.environ.copy(),
        timeout=30,
    )
    return result.returncode, result.stdout, result.stderr


def _parse_json_output(output: str):
    parsed = json.loads(output.strip())
    return parsed


def main() -> int:
    news_items = _load_input()
    backend = os.environ.get("NEWS_SUMMARIZER_BACKEND", "pi_agent")
    pi_command = os.environ.get("NEWS_SUMMARIZER_PI_COMMAND", "pi")
    cache_db_path = Path(os.environ.get("NEWS_SUMMARIZER_CACHE_DB_PATH", ".article-summary-cache.db"))
    conn = _ensure_cache(cache_db_path)
    cursor = conn.cursor()

    debug = {
        "article_cache_hits": 0,
        "article_cache_misses": 0,
        "article_cache_writes": 0,
        "article_cache_fallback_used": False,
        "final_stage": "unknown",
    }

    if backend != "pi_agent":
        summary = {
            "method": "legacy",
            "summary": f"aggregate summary for {len(news_items)} items",
            "llm_error": None,
        }
        print(f"SUMMARY_JSON::{json.dumps(summary)}")
        print(f"SUMMARY_DEBUG::{json.dumps(debug)}")
        return 0

    articles_to_summarize: list[dict[str, object]] = []
    aggregate_articles: list[dict[str, object]] = []
    for item in news_items:
        key = _cache_key(item)
        row = cursor.execute("SELECT summary FROM article_summary_cache WHERE cache_key = ?", (key,)).fetchone()
        if row is not None:
            debug["article_cache_hits"] += 1
            aggregate_articles.append({"summary": row[0]})
        else:
            debug["article_cache_misses"] += 1
            article = dict(item)
            article["cache_key"] = key
            articles_to_summarize.append(article)

    llm_error = None
    if articles_to_summarize:
        code, stdout, stderr = _call_pi(pi_command, articles_to_summarize)
        if code != 0:
            llm_error = stderr.strip() or stdout.strip() or "article summary cache call failed"
            debug["article_cache_fallback_used"] = True
            debug["final_stage"] = "legacy_whole_payload"
            code2, stdout2, stderr2 = _call_pi(pi_command, news_items)
            if code2 != 0:
                llm_error = stderr2.strip() or stdout2.strip() or llm_error
                summary = {
                    "method": "legacy",
                    "summary": f"aggregate summary for {len(news_items)} items",
                    "llm_error": llm_error,
                }
                print(f"SUMMARY_JSON::{json.dumps(summary)}")
                print(f"SUMMARY_DEBUG::{json.dumps(debug)}")
                return 0
            summary = {
                "method": "llm",
                "summary": stdout2.strip(),
                "llm_error": llm_error,
            }
            print(f"SUMMARY_JSON::{json.dumps(summary)}")
            print(f"SUMMARY_DEBUG::{json.dumps(debug)}")
            return 0
        try:
            article_summaries = _parse_json_output(stdout)
            if not isinstance(article_summaries, list):
                raise ValueError("article summary cache response was not a JSON array")
            for item in article_summaries:
                if isinstance(item, dict) and item.get("cache_key") and item.get("summary") is not None:
                    cursor.execute(
                        "INSERT OR REPLACE INTO article_summary_cache (cache_key, summary) VALUES (?, ?)",
                        (str(item["cache_key"]), str(item["summary"])),
                    )
                    debug["article_cache_writes"] += 1
            conn.commit()
            aggregate_articles.extend(
                [{"summary": str(item.get("summary", ""))} for item in article_summaries if isinstance(item, dict)]
            )
            debug["final_stage"] = "aggregate_from_cached_articles"
        except Exception as exc:
            llm_error = f"article summary cache response was not a JSON array: {exc}"
            debug["article_cache_fallback_used"] = True
            debug["final_stage"] = "legacy_whole_payload"
            code2, stdout2, stderr2 = _call_pi(pi_command, news_items)
            if code2 != 0:
                llm_error = stderr2.strip() or stdout2.strip() or llm_error
                summary = {
                    "method": "legacy",
                    "summary": f"aggregate summary for {len(news_items)} items",
                    "llm_error": llm_error,
                }
                print(f"SUMMARY_JSON::{json.dumps(summary)}")
                print(f"SUMMARY_DEBUG::{json.dumps(debug)}")
                return 0
            summary = {
                "method": "llm",
                "summary": stdout2.strip(),
                "llm_error": llm_error,
            }
            print(f"SUMMARY_JSON::{json.dumps(summary)}")
            print(f"SUMMARY_DEBUG::{json.dumps(debug)}")
            return 0

    if debug["final_stage"] == "unknown":
        debug["final_stage"] = "aggregate_from_cached_articles"

    aggregate_payload = aggregate_articles if aggregate_articles else [{"summary": str(item.get("summary", ""))} for item in news_items]
    code, stdout, stderr = _call_pi(pi_command, aggregate_payload)
    if code != 0:
        llm_error = stderr.strip() or stdout.strip() or "aggregate summary call failed"
        summary = {
            "method": "legacy",
            "summary": f"aggregate summary for {len(news_items)} items",
            "llm_error": llm_error,
        }
    else:
        summary = {
            "method": "llm",
            "summary": stdout.strip(),
            "llm_error": llm_error,
        }
    print(f"SUMMARY_JSON::{json.dumps(summary)}")
    print(f"SUMMARY_DEBUG::{json.dumps(debug)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

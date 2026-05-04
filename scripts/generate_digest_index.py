#!/usr/bin/env python3
"""Generate digest/index.html and digest/index.json — browsable archive of
all weekly and daily digests. Run from the repo root after digest.py or
digest_daily.py has written its files; the digest workflows pick this up
via the existing `git add digest/` step.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIGEST_DIR = ROOT / "digest"

WEEKLY_RE = re.compile(r"^(\d{4})-W(\d{2})\.md$")
DAILY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}\.md$")

# Absolute base URL for hrefs. External consumers (LLM clients, scrapers,
# anything fetching index.json out-of-band) need a fully-qualified URL —
# relative paths only resolve inside a browser already at /digest.
BASE_URL = "https://wagon-watcher.vercel.app/digest"


def _scan(subdir: str, pattern: re.Pattern[str]) -> list[dict[str, str]]:
    d = DIGEST_DIR / subdir
    if not d.exists():
        return []
    items = []
    for p in d.iterdir():
        if pattern.match(p.name):
            items.append({
                "label": p.stem,
                "href": f"{BASE_URL}/{subdir}/{p.name}",
                "size_bytes": p.stat().st_size,
            })
    items.sort(key=lambda x: x["label"], reverse=True)
    return items


def _render_html(weekly: list[dict[str, str]], daily: list[dict[str, str]]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    def rows(items: list[dict[str, str]]) -> str:
        if not items:
            return '<li class="empty">— none yet —</li>'
        return "\n".join(
            f'    <li><a href="{i["href"]}">{i["label"]}</a></li>' for i in items
        )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>mb-wagon-watcher / digest archive</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {{ --fg: #f5f5f5; --bg: #0a0a0a; --rule: #2a2a2a; --muted: #888; }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; background: var(--bg); color: var(--fg);
    font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: 13px;
    line-height: 1.5; }}
  main {{ max-width: 720px; margin: 0 auto; padding: 32px 24px; }}
  header {{ padding-bottom: 24px; border-bottom: 1px solid var(--fg);
    margin-bottom: 32px; }}
  .marker {{ font-size: 9px; letter-spacing: 0.15em; text-transform: uppercase;
    color: var(--muted); margin-bottom: 8px; }}
  h1 {{ font-size: 28px; font-weight: 200; letter-spacing: -0.02em;
    margin: 0 0 4px 0; line-height: 1; }}
  h1 b {{ font-weight: 800; }}
  .meta {{ font-size: 9px; letter-spacing: 0.05em; color: var(--muted);
    margin-top: 12px; }}
  section {{ margin-bottom: 40px; }}
  section h2 {{ font-size: 9px; letter-spacing: 0.15em; text-transform: uppercase;
    color: var(--muted); font-weight: 500; padding-bottom: 8px;
    border-bottom: 1px solid var(--rule); margin: 0 0 16px 0;
    display: flex; justify-content: space-between; }}
  ul {{ list-style: none; padding: 0; margin: 0; }}
  li {{ padding: 8px 0; border-bottom: 1px solid var(--rule); }}
  li.empty {{ color: var(--muted); border-bottom: none; }}
  a {{ color: var(--fg); text-decoration: none;
    border-bottom: 1px dashed var(--muted); }}
  a:hover {{ border-bottom-style: solid; }}
  footer {{ margin-top: 48px; padding-top: 16px; border-top: 1px solid var(--rule);
    font-size: 9px; letter-spacing: 0.05em; color: var(--muted); display: flex;
    justify-content: space-between; }}
</style>
</head>
<body>
<main>
  <header>
    <div class="marker">mb-wagon-watcher / digest archive</div>
    <h1>Digest <b>archive</b></h1>
    <div class="meta">{now} · {len(weekly)} weekly · {len(daily)} daily</div>
  </header>
  <section>
    <h2><span>§ Weekly</span><a href="{BASE_URL}/weekly/LATEST.md">LATEST →</a></h2>
    <ul>
{rows(weekly)}
    </ul>
  </section>
  <section>
    <h2><span>§ Daily</span><a href="{BASE_URL}/daily/LATEST.md">LATEST →</a></h2>
    <ul>
{rows(daily)}
    </ul>
  </section>
  <footer>
    <div><a href="{BASE_URL}/index.json">index.json</a></div>
    <div><a href="https://github.com/pwysocan-droid/wagon-watcher">github</a></div>
  </footer>
</main>
</body>
</html>
"""


def main() -> int:
    weekly = _scan("weekly", WEEKLY_RE)
    daily = _scan("daily", DAILY_RE)

    DIGEST_DIR.mkdir(parents=True, exist_ok=True)
    (DIGEST_DIR / "index.html").write_text(_render_html(weekly, daily))
    (DIGEST_DIR / "index.json").write_text(json.dumps({
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "weekly": weekly,
        "daily": daily,
    }, indent=2) + "\n")
    print(f"digest index: {len(weekly)} weekly, {len(daily)} daily")
    return 0


if __name__ == "__main__":
    sys.exit(main())

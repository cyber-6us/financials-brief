#!/usr/bin/env python3
"""Second-pass editorial review of the generated brief."""
import anthropic
import json
import os
import sys
import time
from datetime import datetime, timezone

REVIEW_SYSTEM = """You are a strict editorial QA reviewer for a buy-side financials daily brief. Your job is to enforce quality — not to rewrite from scratch, but to fix specific gaps and errors. Be surgical: remove, add, or edit only what is necessary.

Rules you enforce:
1. Every item must carry exactly one triage tag: [NEW], [DELTA ▲], [DELTA ▼], or [IN LINE].
2. TOP OF BOOK must have 2–4 items. If it has zero or more than 4, fix it.
3. Every item must end with a <em>Sources:</em> sub-bullet containing at least one hyperlink. Items with no source must be removed.
4. No prose paragraphs — everything is bullet points inside <ul>/<li> tags.
5. The four section headers must use exactly these CSS classes: sec-top, sec-names, sec-credit, sec-calendar. No other classes.
6. CREDIT CORNER (sec-credit) must be omitted entirely if there is nothing to add — do not leave it with placeholder text.
7. Macro items must have an explicit financials transmission in the Read sub-bullet (NII / spread / funding / FX etc.). If missing, add one sentence or remove the item.
8. No item should appear in both TOP OF BOOK and BY NAME — TOP OF BOOK items are not repeated below.

Output ONLY the corrected HTML inner content, exactly as the original but with fixes applied. No preamble. No commentary. No markdown fences."""

REVIEW_USER = """Review and correct the following brief HTML. Apply only the fixes required by the editorial rules. Return the corrected HTML only.

--- BRIEF START ---
{content}
--- BRIEF END ---"""


def call_api_with_retry(client, **kwargs):
    for attempt in range(5):
        try:
            return client.messages.create(**kwargs)
        except anthropic.APIStatusError as e:
            if e.status_code in (429, 529) and attempt < 4:
                wait = 60 * (attempt + 1)
                print(f"API error {e.status_code}, retrying in {wait}s...", flush=True)
                time.sleep(wait)
            else:
                raise


def review_brief():
    with open("brief.json", encoding="utf-8") as f:
        brief = json.load(f)

    original = brief.get("content", "")
    if not original.strip():
        print("brief.json has no content — skipping review.", flush=True)
        return

    print(f"Reviewing brief ({len(original)} chars)...", flush=True)

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    response = call_api_with_retry(
        client,
        model="claude-sonnet-4-6",
        max_tokens=8000,
        system=REVIEW_SYSTEM,
        messages=[{"role": "user", "content": REVIEW_USER.format(content=original)}],
    )

    reviewed = "".join(
        block.text for block in response.content if hasattr(block, "text")
    ).strip()

    if not reviewed:
        print("Review returned empty — keeping original.", flush=True)
        return

    # Sanity check: reviewed output must still look like HTML
    if "<h3" not in reviewed and "<ul" not in reviewed:
        print("Review output does not look like HTML — keeping original.", flush=True)
        return

    brief["content"] = reviewed
    brief["reviewed_at"] = datetime.now(timezone.utc).isoformat()

    with open("brief.json", "w", encoding="utf-8") as f:
        json.dump(brief, f, ensure_ascii=False, indent=2)

    print(f"Review done. Content length: {len(reviewed)} chars (was {len(original)}).", flush=True)


if __name__ == "__main__":
    try:
        review_brief()
    except Exception as e:
        print(f"ERROR in review: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        sys.exit(1)

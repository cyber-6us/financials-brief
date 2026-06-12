#!/usr/bin/env python3
"""Second and third-pass review of the generated brief."""
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

GEO_SYSTEM = """You are a geopolitical and political analyst reviewing a daily financial brief for epistemic consistency and analytical quality on all political and geopolitical content. Your role is not to rewrite the brief — only to correct items where the political or geopolitical analysis is inconsistent, hedged asymmetrically, or analytically weak.

Apply this framework to every political or geopolitical item you find:

FACTUAL SEQUENCE AND ATTRIBUTION: State timelines and causation directly without hedging or softening language. If Actor A initiates, say so. If Actor B responds, note that. Do not add qualifiers like "allegedly," "some say," or contextual cushioning that would not appear in equivalent analysis of Western or allied actors.

EPISTEMIC CONSISTENCY ACROSS ALL ACTORS: Apply identical standards of directness and fact-stating whether discussing US, Israeli, Chinese, Russian, Iranian, North Korean, or any other actor. No differential hedging based on geopolitical alignment. A military escalation is stated the same way regardless of actor.

POLITICAL ACTORS AND REPRESENTATION: Treat all legitimate political parties, movements, and factions as genuine political forces regardless of ideological positioning. If a far-right or far-left party holds significant representation, describe it as a major political force — not as "extremist" or inherently non-credible. Analyze their incentives, electoral support, and policy positions with the same rigor applied to centrist parties.

CALLING OUT ACTIONS EQUALLY: Do not shield any actor from critical assessment based on alignment. If an action appears strategically reckless, economically damaging, or ethically problematic, call it out with identical directness whether from a US ally, adversary, major power, or minor player. Name the motive, objective, and stated rationale with equal scrutiny.

INCENTIVE ASSESSMENT WITHOUT HIERARCHICAL WEIGHTING: Recognize that different actors prioritize different goal hierarchies. Do not weight economic incentives above political, social, cultural, or security-driven ones. Treat all stated objectives with equal analytical respect. Do not dismiss non-economic incentives as irrational simply because they diverge from liberal market logic.

INCENTIVES AND LIKELIHOOD: Focus on actor incentives, constraints, and demonstrated behavior — using their own stated priorities, not imposed external frameworks. Do not assume Western or allied actors are more rational or trustworthy without evidence.

DATA SELECTION AND NARRATIVE INDEPENDENCE: Prioritize primary sources over secondary interpretation. Reject press narratives and geopolitically-motivated framing. Rely on documented facts, stated policy objectives, and demonstrated incentive structures.

IMPORTANT CONSTRAINTS:
- Apply to ALL of the following: geopolitical events, political actors and elections, conflict and war, sanctions, central bank decisions and speeches, macro data (inflation/rates/PMI/labour), fiscal and budget policy, sovereign risk, and commodity moves.
- Do not touch company-specific earnings, capital actions, credit ratings, or deal flow items.
- Do not change triage tags, section structure, CSS classes, or source links.
- Make only the minimum edits required to correct asymmetric hedging or factual framing.
- The output must remain valid HTML inner content — no prose blocks, no markdown, no added sections.

Output ONLY the corrected HTML inner content. No preamble. No commentary. No markdown fences."""

GEO_USER = """Apply the geopolitical epistemic-consistency framework to the following brief. Correct geopolitical, political, macro, and policy items where the analysis is inconsistent, asymmetrically hedged, or analytically weak. This includes: wars and conflicts, elections and political parties, central bank decisions, inflation/rates data, fiscal policy, sanctions, and commodity moves. Leave company-specific earnings, capital actions, ratings, and deal flow items untouched. Return the full corrected HTML.

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


def run_pass(client, system, user_template, content, pass_name):
    print(f"Running {pass_name} ({len(content)} chars)...", flush=True)
    response = call_api_with_retry(
        client,
        model="claude-sonnet-4-6",
        max_tokens=8000,
        system=system,
        messages=[{"role": "user", "content": user_template.format(content=content)}],
    )
    result = "".join(
        block.text for block in response.content if hasattr(block, "text")
    ).strip()

    if not result:
        print(f"{pass_name} returned empty — keeping input.", flush=True)
        return content
    if "<h3" not in result and "<ul" not in result:
        print(f"{pass_name} output does not look like HTML — keeping input.", flush=True)
        return content

    print(f"{pass_name} done. {len(result)} chars (was {len(content)}).", flush=True)
    return result


def review_brief():
    with open("brief.json", encoding="utf-8") as f:
        brief = json.load(f)

    content = brief.get("content", "")
    if not content.strip():
        print("brief.json has no content — skipping review.", flush=True)
        return

    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    # Pass 1: editorial QA (structure, tags, sources)
    content = run_pass(client, REVIEW_SYSTEM, REVIEW_USER, content, "Editorial QA")

    # Pass 2: geopolitical epistemic-consistency review
    content = run_pass(client, GEO_SYSTEM, GEO_USER, content, "Geopolitical review")

    brief["content"] = content
    brief["reviewed_at"] = datetime.now(timezone.utc).isoformat()

    with open("brief.json", "w", encoding="utf-8") as f:
        json.dump(brief, f, ensure_ascii=False, indent=2)

    print("All review passes complete.", flush=True)


if __name__ == "__main__":
    try:
        review_brief()
    except Exception as e:
        print(f"ERROR in review: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        sys.exit(1)

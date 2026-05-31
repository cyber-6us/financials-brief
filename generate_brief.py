#!/usr/bin/env python3
import anthropic
import json
import os
import sys
from datetime import date, datetime, timezone

SYSTEM_PROMPT = """You are a daily financials intelligence analyst for a PM running a concentrated long/short book in financial-sector equities and credit. Write for a PM: assume fluency in NIM, NNM, AuM, spreads, CET1, RWA, Solvency II, ratings, and regulation.

UNIVERSE
1. Primary — European financials: banks, insurers, asset & wealth managers, payments/fintech, exchanges.
2. Secondary — US, LatAm, China financials; global macro/policy directly moving financials (ECB/SNB/Fed/PBoC decisions, Basel rules, sovereign or sector credit events).

MATERIAL EVENTS ONLY
Earnings/guidance, M&A or stake moves, capital actions (buybacks, raises, dividends), rating/outlook changes, regulatory or litigation developments, management changes, credit events, large price moves with an identifiable catalyst. Ignore noise, reiterations, sell-side chatter without a hard catalyst.

OUTPUT FORMAT
Produce ONLY the brief as HTML inner content (no <html>, <head>, or <body> tags). Use exactly:
- <h3 class="sec-primary">PRIMARY — EUROPEAN FINANCIALS</h3>
- <h3 class="sec-secondary">SECONDARY — US / LATAM / CHINA</h3>
- <h3 class="sec-macro">MACRO / POLICY</h3>
- <div class="item"> wrapping each news item
- Inside each item: <p class="headline"><strong><a href="SOURCE_URL">Name (TICKER)</a></strong> — one-line summary.</p>
- <p class="read"><em>L/S read:</em> why it matters for positioning.</p>
- End each item with ONE of: <span class="action dig-in">→ DIG IN</span> or <span class="action monitor">→ MONITOR</span> or <span class="action no-action">→ NO ACTION</span>
- If nothing material in a bucket: <p class="nothing">Nothing material.</p>

Output nothing before the first <h3> tag. No preamble. No filler. No markdown code fences."""


def get_user_prompt():
    today = date.today().strftime("%d %B %Y")
    return f"""Today is {today}. Run the morning brief.

Search the web for MATERIAL events in the last 24 hours covering:
- European financials: banks (DBK, CBK, BNP, SocGen, UniCredit, ING, Santander, Barclays, HSBC, UBS, Julius Baer), insurers (Allianz, AXA, Generali, Zurich, Munich Re), asset managers (Amundi, DWS), payments/fintech (Adyen, Worldline, Nexi, Wise), exchanges (Deutsche Boerse, Euronext, LSE Group)
- US/LatAm/China financials
- ECB, SNB, Fed, PBoC decisions; Basel/capital rules; sovereign or sector credit events

For each item: (a) what happened, one line; (b) long/short read — why it matters for positioning; (c) next step: NO ACTION / MONITOR / DIG IN.
Group: PRIMARY (EU) → SECONDARY (US/LatAm/China) → MACRO/POLICY.
Flag estimated or unconfirmed numbers with [est.]."""


def generate_brief():
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    messages = [{"role": "user", "content": get_user_prompt()}]

    print("Calling Claude API...", flush=True)

    for iteration in range(15):
        print(f"Turn {iteration + 1}...", flush=True)

        # web_search_20250305 requires the beta header
        response = client.beta.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=8000,
            system=SYSTEM_PROMPT,
            betas=["web-search-2025-03-05"],
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=messages,
        )

        print(f"Stop reason: {response.stop_reason}", flush=True)

        if response.stop_reason == "end_turn":
            return "".join(
                block.text for block in response.content if hasattr(block, "text")
            )

        messages.append({"role": "assistant", "content": response.content})
        tool_results = [
            {"type": "tool_result", "tool_use_id": block.id, "content": ""}
            for block in response.content
            if block.type == "tool_use"
        ]
        if not tool_results:
            return "".join(
                block.text for block in response.content if hasattr(block, "text")
            )
        messages.append({"role": "user", "content": tool_results})

    return "<p>Brief generation timed out.</p>"


def main():
    print("Generating brief...", flush=True)
    try:
        html_content = generate_brief()
        if not html_content.strip():
            raise ValueError("Empty response from API")
        brief = {
            "date": date.today().isoformat(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "content": html_content,
        }
        with open("brief.json", "w", encoding="utf-8") as f:
            json.dump(brief, f, ensure_ascii=False, indent=2)
        print(f"Done. Content length: {len(html_content)} chars", flush=True)
    except Exception as e:
        print(f"ERROR: {type(e).__name__}: {e}", file=sys.stderr, flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()

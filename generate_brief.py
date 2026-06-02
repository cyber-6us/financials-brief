#!/usr/bin/env python3
import anthropic
import json
import os
import sys
from datetime import date, datetime, timezone, timedelta
import xml.etree.ElementTree as ET
import urllib.request
import urllib.error
import time

SYSTEM_PROMPT = """# SYSTEM PROMPT — Daily Financials News Review

## ROLE

You are a senior buy-side analyst embedded on the desk of a long/short financials portfolio manager. You think like a PM, not a sell-side coverage analyst: every observation ends in a positioning consequence, not a summary. You are a peer, not a tutor. Assume the reader has full domain fluency in bank and insurer accounting, capital regulation, and credit instruments. Do not explain basics, do not hedge every sentence, and do not pad. Brevity with a view beats completeness without one.

## COVERAGE UNIVERSE

**Primary — European financials, equity AND credit:**
- Banks (GSIBs, national champions, mid-caps, Nordics, periphery)
- Insurers (life, P&C, reinsurance, multiline)
- Asset & wealth managers
- Payments & fintech (Worldline, Adyen, Nexi, etc.)
- Exchanges & market infrastructure
- Specialty / consumer / diversified finance

Track both the equity and the capital structure: common equity, AT1 / CoCo, Tier 2, senior preferred / non-preferred, and CDS where it moves. A development that is neutral for equity but material for spreads (or vice versa) is still material — say which leg it hits.

**Secondary — US, LatAm, China financials:**
Surface only when (a) directly price-moving, or (b) carrying read-through to a European name or theme. Otherwise omit.

## MANDATE

Produce a pre-market daily intelligence briefing. Your job is triage, not transcription: identify the small number of developments that change a thesis, a position, or a risk, and discard everything else. The default failure mode to avoid is volume — a long, evenly-weighted list is a failure even if every item is accurate.

## MATERIALITY FILTER

**Treat as material:**
- Earnings, pre-announcements, profit warnings, guidance changes (and consensus-vs-print deltas)
- Capital actions: buybacks, dividends, AT1 calls / non-calls / new issuance, rights issues
- Capital & regulatory: CET1 / MDA headroom, MREL, SREP / Pillar 2, Basel endgame, stress-test outcomes, regulatory fines/probes
- M&A, stake builds, activist entries, large block trades
- Rating actions and outlook changes (issuer and instrument level)
- Management / board changes at the C-suite
- Litigation, conduct, AML/sanctions developments with capital or franchise impact
- Macro / rates / curve moves with a direct financials read (NII, deposit beta, funding cost, credit cycle, FX translation)

**Surprise is not the only test of materiality.** A scheduled or widely-anticipated event that has now *arrived* is material even if it landed in line — because a miss would have been price-moving, and the resolution of that binary is itself information (the risk is now off the table, or confirmed). Flag it as in-line rather than dropping it. Distinguish three things on every item: what is genuinely new or unexpected, what has *changed* relative to what was previously known or guided, and what was expected and has simply been confirmed. The first two carry the read; the third de-risks (or arms) a position.

**Exclude:** routine broker rating tweaks, recycled or already-priced headlines, conference fluff, generic macro commentary, ESG/PR items without financial consequence — and expected events that are also immaterial (an in-line print on a name where neither a beat nor a miss would have moved anything).

## TRIAGE LOGIC

For each candidate item, run silently:
1. **Information state?** — classify against the prior baseline: **NEW** (not previously known or anticipated), **DELTA** (a known topic where the facts have changed vs what was known/guided — better or worse), or **IN LINE** (an expected, material event that has now arrived within expectations). All three can qualify for output; surprise is not the gate.
2. **Material?** — would a deviation have moved price, or does it change a thesis, position, or risk? A scheduled event that landed in line is still material if a miss *would* have moved price — the binary has resolved, say so. An expected event that is also immaterial drops out here.
3. **Relevant?** — touches a held position, a watchlist name, or a sector exposure.
4. **Read-through?** — second-order effects on peers, the capital structure, or the theme.
5. **Action?** — initiate / add / trim / hedge / monitor / no action — with the leg (equity vs credit) and direction.

Only items clearing steps 1–2 reach output. Items clearing 1–4 but not actionable go to "Monitor." Tag every output item with its information state.

## OUTPUT FORMAT

Produce ONLY the brief as HTML inner content (no <html>, <head>, or <body> tags). Output nothing before the first heading tag. No preamble. No filler. No markdown code fences.

Everything is bullet points — no prose paragraphs, no multi-line blocks. Each item is a single <li> inside a <ul>. Sub-bullets for read and implication go inside a nested <ul>.

Use this structure:

<h3 class="sec-top">TOP OF BOOK</h3>
<ul>
<li><strong>NAME (TICKER)</strong> <span class="tag new">[NEW]</span> — event in one line.
  <ul>
    <li><em>Vs. baseline:</em> what is new / what changed / what was confirmed.</li>
    <li><em>Read:</em> non-consensus angle, fact separated from inference. Leg: equity / AT1 / senior / CDS. Direction. Action.</li>
    <li><em>Sources:</em> <a href="URL">source</a></li>
  </ul>
</li>
</ul>

<h3 class="sec-names">BY NAME / THEME</h3>
<ul>
<li><strong>NAME (TICKER)</strong> <span class="tag delta-down">[DELTA ▼]</span> — event. <em>Read:</em> […]. Leg / direction / action. <em>Sources:</em> <a href="URL">source</a></li>
</ul>

<h3 class="sec-credit">CREDIT CORNER</h3>
Only if there are spread, AT1, or rating developments not covered above. Same bullet format. Omit the section entirely if nothing to add.
<ul><li>…</li></ul>

<h3 class="sec-calendar">CALENDAR AHEAD</h3>
<ul><li>…</li></ul>
Upcoming prints, AT1 call dates, regulatory events in the next 1–5 sessions. Note where in-line is priced and only a deviation matters.

Tags to use: <span class="tag new">[NEW]</span>, <span class="tag delta-up">[DELTA ▲]</span>, <span class="tag delta-down">[DELTA ▼]</span>, <span class="tag in-line">[IN LINE]</span>

If a quiet day, say so in a single bullet — do not manufacture content."""


# Tickers to track via Polygon — US-listed or dual-listed names in universe
POLYGON_TICKERS = [
    "DB", "BCS", "ING", "SAN", "HSBC", "UBS",  # European banks US-listed
    "BNP", "GLE", "UCG",                          # European banks
    "AXA", "ALVG", "MUV2",                        # Insurers
    "ADYEN", "WLN", "WISE",                        # Payments
    "AMUN", "DWS",                                 # Asset managers
    "APO", "ARES", "BX", "KKR", "OWL",           # Private credit / alt managers
    "JPM", "BAC", "GS", "MS", "C", "WFC",        # US banks
    "SPG", "PLD", "O",                             # REITs
]

UNIVERSE_KEYWORDS = [
    "Deutsche Bank", "Commerzbank", "BNP Paribas", "Societe Generale", "UniCredit",
    "Santander", "Barclays", "HSBC", "UBS", "Julius Baer", "ING",
    "Allianz", "AXA", "Generali", "Zurich", "Munich Re",
    "Amundi", "DWS", "Adyen", "Worldline", "Nexi", "Wise",
    "Deutsche Boerse", "Euronext", "London Stock Exchange",
    "Apollo", "Ares", "Blackstone", "KKR", "Blue Owl", "HPS", "Sixth Street",
    "ECB", "SNB", "Federal Reserve", "PBoC", "Bank of England",
    "Basel", "AT1", "CoCo", "CET1", "SREP",
]


def fetch_polygon_news(lookback_hours=24):
    api_key = os.environ.get("POLYGON_API_KEY", "")
    if not api_key:
        print("No POLYGON_API_KEY set, skipping.", flush=True)
        return []

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).strftime("%Y-%m-%dT%H:%M:%SZ")
    url = (
        f"https://api.polygon.io/v2/reference/news"
        f"?published_utc.gte={cutoff}&limit=100&order=desc&sort=published_utc&apiKey={api_key}"
    )
    items = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; FinBrief/1.0; +https://github.com/cyber-6us/financials-brief)", "Accept": "application/rss+xml, application/xml, text/xml"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
        for article in data.get("results", []):
            title     = article.get("title", "").strip()
            link      = article.get("article_url", "").strip()
            publisher = article.get("publisher", {}).get("name", "Polygon")
            tickers   = article.get("tickers", [])
            # include if a tracked ticker is tagged, or a universe keyword in headline
            relevant = any(t in POLYGON_TICKERS for t in tickers) or \
                       any(kw.lower() in title.lower() for kw in UNIVERSE_KEYWORDS)
            if relevant and title and link:
                ticker_str = f" [{', '.join(tickers[:4])}]" if tickers else ""
                items.append(f"- [Polygon/{publisher}]{ticker_str} {title} — {link}")
    except Exception as e:
        print(f"Polygon fetch failed: {e}", flush=True)
    return items


RSS_FEEDS = {
    "FT Markets":       "https://www.ft.com/rss/home/markets",
    "FT Companies":     "https://www.ft.com/rss/home/companies",
    "FT World":         "https://www.ft.com/rss/home/world",
    "WSJ Markets":      "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",
    "WSJ Business":     "https://feeds.a.dj.com/rss/WSJcomUSBusiness.xml",
    "Reuters Business": "https://feeds.reuters.com/reuters/businessNews",
    "Reuters Finance":  "https://feeds.reuters.com/reuters/financialNews",
    "Les Echos Finance":"https://www.lesechos.fr/rss/rss_finance.xml",
    "Les Echos Marches":"https://www.lesechos.fr/rss/rss_marches_financiers.xml",
}


def fetch_rss_headlines(lookback_hours=24):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    items = []
    for source, url in RSS_FEEDS.items():
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; FinBrief/1.0; +https://github.com/cyber-6us/financials-brief)", "Accept": "application/rss+xml, application/xml, text/xml"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                root = ET.fromstring(resp.read())
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for item in root.iter("item"):
                title = (item.findtext("title") or "").strip()
                link  = (item.findtext("link")  or "").strip()
                pub   = item.findtext("pubDate") or ""
                # parse pubDate — try common RFC 2822 format
                pub_dt = None
                for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z"):
                    try:
                        pub_dt = datetime.strptime(pub.strip(), fmt)
                        if pub_dt.tzinfo is None:
                            pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                        break
                    except ValueError:
                        continue
                if pub_dt and pub_dt < cutoff:
                    continue
                if title and link:
                    items.append(f"- [{source}] {title} — {link}")
        except Exception as e:
            print(f"RSS fetch failed for {source}: {e}", flush=True)
    return items


def get_user_prompt():
    today = date.today().strftime("%d %B %Y")
    rss_items     = fetch_rss_headlines()
    polygon_items = fetch_polygon_news()
    # Cap to keep prompt within token limits: Polygon top 40, RSS top 40
    all_items     = polygon_items[:40] + rss_items[:40]
    if all_items:
        rss_block = (
            "## FRESH HEADLINES FROM PREMIUM FEEDS (last 24h)\n"
            "Sources: Polygon (ticker-tagged), FT, WSJ, Reuters, Les Echos.\n"
            "Use these as your starting inventory — verify, enrich, and web-search for detail on anything material.\n"
            "Bloomberg: use web search to find bloomberg.com articles directly.\n\n"
            + "\n".join(all_items)
            + "\n\n---\n\n"
        )
    else:
        rss_block = ""
    return f"""{rss_block}Today is {today}. Run the morning brief (Sweep mode).

Search the web for **material events in the last 24 hours** (or since the last trading session) across:

**PRIMARY — European financials:**
- Banks: DBK, CBK, BNP, SocGen, UniCredit, ING, Santander, Barclays, HSBC, UBS, Julius Baer
- Insurers (lower priority): Allianz, AXA, Generali, Zurich, Munich Re
- Asset managers: Amundi, DWS
- Payments / fintech: Adyen, Worldline, Nexi, Wise
- Exchanges: Deutsche Boerse, Euronext, LSE Group
- Private credit / private capital (Europe and US — names and managers in scope regardless of geography, e.g. Apollo, Ares, Blackstone, KKR, Blue Owl, HPS, Sixth Street, and European direct lenders): direct-lending and BDC flows (fundraising, redemptions, gating), fund pricing and NAV marks, asset sales / portfolio trades, defaults and restructurings, bank–private-credit risk transfer (SRT, forward-flow, NAV financing). Track the read-through to bank syndication, leveraged-finance pipelines, and where private marks diverge from public comps. Give size, yield / spread, and counterparties on deals where disclosed; flag with [est.] if unconfirmed.

**SECONDARY — US / LatAm / China financials:** surface only if directly price-moving or carrying read-through to a primary name or theme.

**SECONDARY — Real estate:** listed property / REITs and the sector broadly (esp. CRE — office, retail, logistics; and residential developers), with emphasis on the channel into financials: bank CRE-loan exposure, property-backed credit, REIT funding/refinancing, cap-rate moves. Surface on the same price-moving / read-through test as the financials above. Highlight key transactions — asset and portfolio deals, M&A, recapitalisations, distressed sales — and for each give size (value / GLA), yield (entry cap rate / NIY), buyer & seller, and financing where disclosed; flag any with [est.] if unconfirmed. Read-through to lenders, valuations, and the credit cycle is the point.

**MACRO / POLICY:** cover the following, but always through a financials read-through — every macro item must terminate in a transmission to the book (rates / NII / funding cost, credit cycle / spreads, FX translation, risk-on/off positioning, sovereign-bank loop). Macro with no financials channel is noise — drop it.
- Central banks: ECB, SNB, Fed, PBoC, BoE decisions, minutes, speeches, and shifts in rate-path expectations; QT / balance-sheet, liquidity ops, deposit-rate signals.
- Inflation & data: CPI / PCE / PPI prints, wage and labour data, PMIs — vs. consensus and vs. the prior path; flag where a deviation repriced the curve.
- Rates & curve: sovereign yield and curve moves (Bunds, OATs, BTPs, USTs, Gilts, SNB-relevant), spread widening/compression, peripheral spreads (BTP-Bund), credit / IG-HY spreads.
- Politics & elections: elections, polls, government formation/collapse, fiscal and budget news, regulatory or tax policy shifts (bank levies, windfall taxes, M&A/merger politics) — especially EU, periphery, France, Germany, UK, US, and key EM.
- War & conflict: geopolitical escalation/de-escalation, sanctions, supply-chain or energy-security shocks with a risk-sentiment or sector-exposure channel.
- Commodities: oil (Brent/WTI), gas, gold — moves large enough to shift inflation expectations, energy-sector credit, or EM/petrostate sovereign risk.
- Real estate prices: residential and commercial price indices, cap-rate / valuation moves, transaction-volume and rental trends, and refinancing-wall stress — where they read into bank CRE books, mortgage credit quality, property-backed lending, or the broader credit cycle.
- Sovereign & sector credit: rating actions, sovereign stress, funding-market dislocation, Basel / capital-rule developments, any event touching the sovereign-bank doom loop.

Apply the materiality and triage logic from the system prompt:
- Classify every item by information state and tag it: [NEW] / [DELTA ▲] / [DELTA ▼] / [IN LINE].
- Keep expected events that have arrived in line where a miss would have been price-moving — flag the binary as resolved. Drop expected-and-immaterial items.
- Lead each item with the delta vs. the prior baseline (what's new / changed / confirmed), not the event headline.

For each item (applies to ALL three groups — PRIMARY, SECONDARY, and every MACRO / POLICY item alike):
- (a) What happened — one line.
- (b) Long/short read — why it matters for positioning; equity vs credit leg, direction; fact separated from inference. For macro items, this is the transmission channel to the book.
- (c) Next step — NO ACTION / MONITOR / DIG IN.
- Sources — hyperlink(s), one or more, at the end of every point without exception; primary source (central bank / statistical agency / regulator / company release / exchange filing) over secondary coverage. No source, no item.

Output: every item — primary, secondary, and macro — is a bullet, tagged with its information state, and ends with its source link(s). Group PRIMARY (EU) → SECONDARY (US/LatAm/China) → MACRO/POLICY, ranked by relevance within each. Lead with Top of Book if anything clears that bar. Scannable in under two minutes.

Flag estimated or unconfirmed numbers with [est.]. If sourcing is thin, say so in one clause rather than inflating confidence. Quiet session → say so in a couple of lines; do not manufacture content."""


def call_api_with_retry(client, **kwargs):
    for attempt in range(5):
        try:
            return client.beta.messages.create(**kwargs)
        except anthropic.APIStatusError as e:
            if e.status_code in (429, 529) and attempt < 4:
                wait = 60 * (attempt + 1)
                print(f"API error {e.status_code}, retrying in {wait}s...", flush=True)
                time.sleep(wait)
            else:
                raise


def generate_brief():
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    messages = [{"role": "user", "content": get_user_prompt()}]

    print("Calling Claude API...", flush=True)

    for iteration in range(15):
        print(f"Turn {iteration + 1}...", flush=True)

        # web_search_20250305 requires the beta header
        response = call_api_with_retry(
            client,
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

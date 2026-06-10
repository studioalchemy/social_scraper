import json
import logging
from datetime import datetime
import anthropic
import config

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"


SYSTEM_PROMPT = """You are an Instagram competitive intelligence analyst. You receive scraped Instagram data from Apify and produce a structured competitive analysis report. Your output must follow the exact structure below — every section, every subsection, every table format — without exception, regardless of the brand or category you are analysing.

INPUTS YOU WILL RECEIVE:
- BRAND_NAME — the brand being analysed (derive from the first account's handle if not stated)
- BRAND_CATEGORY — the product/service category (infer from the brand and competitive set)
- BUSINESS_PROBLEMS — 1–3 specific business problems the brand is trying to solve on Instagram
- ACCOUNTS_ANALYSED — list of scraped accounts; the first account is the brand being analysed, the rest are the competitive set
- SCRAPE_PERIOD — date range of the scraped data
- Scraped post data from Apify for all listed accounts

OUTPUT STRUCTURE — Generate the report in exactly this order. Do not skip sections. Do not merge sections.

REPORT HEADER:
- Title line, subtitle, prepared-for line, data note, accounts list line, business problems list anchored as BP1/BP2/BP3.

SECTION 1 — COMPETITIVE LANDSCAPE
- Open with one italicised line stating: scrape date range, how engagement rate is calculated, asterisk disclaimers for skewed outliers.
- At-a-glance table for all accounts: Account, Followers, Following, Posts, Verified, Avg ER, Format Mix, Posts/Wk.
- Footnotes below the table for any asterisked ER figures.
- For each account, a per-account deep dive: header line, Content Format Mix (bullets with % and one-line description), Posting Frequency (bullet + context), Top 5 Performing Posts table (#, Caption excerpt, Type, Likes, Comments, Why It Worked — the Why column must be analytical, not descriptive), Content Themes & Pillars (3–5 bullets), Brand Voice (3–4 bullets), Engagement Patterns (optional), Key Insight (one paragraph, single strategic point).
- For accounts with very limited own-post data, use a Key Observations bullet list + Key Insight instead of the full template, and mark is_limited_data true.

SECTION 2 — COMPETITIVE POSITIONING MAP
- Open with the two axes (horizontal + vertical) using pole language.
- Table placing every account: Brand, Axis 1 Position, Axis 2 Position, Content Territory Owned.
- Strategic Positioning Summary paragraph describing each quadrant and relevance to the brand.
- Critical Observation: the brand's positioning problem (or opportunity) — single focused paragraph identifying the gap and the single most important unclaimed territory.

SECTION 3 — [BRAND_NAME] OWN ACCOUNT AUDIT
- Header line: @handle | X followers | X total posts | X own posts in last [period]
- 3.1 What the Brand Is Doing Well (bullets, specific, cite examples and numbers)
- 3.2 What the Brand Is Doing Poorly (In Isolation) (bullets, direct, no softening)
- 3.3 What the Brand Is Doing Poorly Relative to Competition (bullets, each names a specific competitor doing it better with numbers)
- 3.4 Engagement Rate vs Competitive Set (paragraph: brand's ER vs best and worst in set with specific numbers, strategic implication)
- A bolded status summary sentence
- 3.5 Content Calendar Pattern (bullets: reactive vs proactive, campaign-dependent vs always-on, structure)
- 3.6 Creator & Collaboration Presence (bullets: creator diversity, recurring vs one-off, micro vs macro)

SECTION 4 — WHITESPACE ANALYSIS
- 4.1 Content Themes No Brand Is Owning (bullets)
- 4.2 Formats Being Underutilised Across the Category (bullets — ASMR, POV, duet, dark cinematography, etc.)
- 4.3 Emotional Territories Available (bullets — nostalgia, pride, solitude, rebellion, etc., each connected to an audience insight)
- 4.4 Audience Conversations Not Being Picked Up (bullets — derived from comment analysis or noted as inferred if comment data limited)
- 4.5 Visual & Aesthetic Whitespace (bullets — visual styles, color languages, cinematography directions)

SECTION 5 — RECOMMENDATIONS ANCHORED TO BUSINESS PROBLEMS
- One block per business problem, labelled 5A / 5B / 5C.
- Each block contains: .1 What competitors are doing successfully (bullets, name accounts and specific posts/campaigns and explain the mechanic), .2 Underrepresented Occasions / Moments (4–6 bullets, specific occasions/times/seasons/situations), .3 Instagram Content Strategies for this problem (bullets, practical IG-specific tactics), .4 Recommended Content Territories (3–4 named territories — each: territory name in quotes, time/occasion anchor, caption-style example in quotes, one-sentence on why it solves the BP).

SECTION 6 — CONTENT STRATEGY BLUEPRINT FOR [BRAND_NAME]
- 6.1 Content Pillars table (4–6 rows: Pillar Name, Content Under It, Business Problem Addressed, Engagement Potential)
- 6.2 Format Mix Recommendation table (Format, % of Mix, Posts/Week, Story Usage, Rationale)
- 6.3 Posting Cadence (bullets: total posts/week vs current, breakdown by format, time-of-day windows with reasoning, stories cadence)
- 6.4 Tone of Voice Direction: defining characteristics (bold label + one-sentence explanation each), 5–7 example captions in the brand's recommended voice, Clear Don'ts each starting with "DON'T:" and citing a specific competitor failure with a data point.
- 6.5 Creator Strategy: Creator Archetype table (Archetype, Size, Content Genre, Platforms, Fit for BRAND), then three named partnership layers (ALWAYS-ON LAYER, CAMPAIGN LAYER, plus a third layer specific to this brand's category need) — each with brief, budget framing, content approach.
- 6.6 Craft Standards: Hook Style & Duration for Reels (bullets), Visual Treatment (bullets), Caption Structure Guidance (bullets).

SUMMARY — TOP 10 ACTIONABLE RECOMMENDATIONS
- One italicised intro line: "Prioritised by expected impact on the business problems. Implement in sequence."
- IMMEDIATE (0–4 weeks): 3 recommendations
- SHORT TERM (1–3 months): 3–4 recommendations
- MEDIUM TERM (3–6 months): 3–4 recommendations
- Each recommendation: a bold action label in caps, a clear action statement, which BPs it impacts, an effort/cost signal.

REPORT FOOTER:
- Data source line (posts count + accounts count + scrape month)
- Analysis line + prepared-for line

RULES FOR EVERY REPORT:
1. Numbers are mandatory. Every analytical claim must cite a specific figure from the data — follower count, ER%, likes, views, posts/week. "High engagement" is not acceptable.
2. "Why It Worked" must be analytical — name the format trigger, emotional driver, cultural moment, or algorithmic reason.
3. Competitive comparisons must be direct — every Section 3 weakness names the competitor doing it better with numbers.
4. Key Insights are singular and sharp — one paragraph, one point.
5. Whitespace must be genuinely absent across all monitored accounts — scan all accounts before declaring a space open.
6. All recommendations trace back to specific findings in Sections 1–5. No generic best practices.
7. Brand voice examples in 6.4 must use the brand's actual voice — not generic social copy.
8. Don'ts cite a competitor failure with a data point.
9. Format the report for readability — use exact headers, bold labels, table structures, bullet formatting.
10. Adapt depth to the data — if an account has fewer than 5 scraped posts, use Key Observations format and mark is_limited_data true.

Return ONLY a valid JSON object matching the provided schema. No markdown, no code blocks, just raw JSON. Be specific, data-driven, and use exact numbers from the scraped data."""


def _format_account_block(username: str, role: str, data: dict) -> str:
    profile = data.get("profile") or {}
    posts = data.get("posts") or []
    reels = data.get("reels") or []
    comments_by_post = data.get("comments") or {}
    tagged = data.get("tagged_posts") or []

    if not (profile or posts or reels or tagged):
        return f"\n=== @{username} [{role}] ===\nNo data scraped (all actor calls failed or account private)."

    # Profile line
    p_lines = []
    if profile:
        fullname = profile.get("fullName") or profile.get("full_name") or ""
        biography = (profile.get("biography") or "")[:200].replace("\n", " ")
        followers = profile.get("followersCount") or profile.get("followers_count") or profile.get("followers")
        following = profile.get("followsCount") or profile.get("follows_count") or profile.get("following")
        total_posts = profile.get("postsCount") or profile.get("posts_count") or profile.get("postsCount") or len(posts)
        verified = profile.get("verified") or profile.get("isVerified") or False
        category = profile.get("businessCategoryName") or profile.get("category") or ""
        ext_url = profile.get("externalUrl") or profile.get("external_url") or ""
        p_lines.append(
            f"PROFILE: {fullname} | followers={followers} | following={following} | "
            f"total_posts={total_posts} | verified={verified} | category={category} | url={ext_url}"
        )
        if biography:
            p_lines.append(f"BIO: {biography}")

    # Posts list
    post_lines = []
    for p in posts[:25]:
        views = f", Views: {p['videoViewCount']}" if p.get("videoViewCount") else ""
        audio = f", Audio: {p['musicInfo']}" if p.get("musicInfo") else ""
        hashtags = f" | Tags: {', '.join(p.get('hashtags', [])[:5])}" if p.get("hashtags") else ""
        post_lines.append(
            f"  - [{p.get('type', '?')}] {p.get('timestamp', '')[:10]} | "
            f"Likes: {p.get('likesCount', 0)}, Comments: {p.get('commentsCount', 0)}{views}{audio}{hashtags}\n"
            f"    Caption: {(p.get('caption') or '')[:200]}\n"
            f"    URL: {p.get('url', '')}"
        )

    # Reels — only show ones whose engagement signals add information
    reel_lines = []
    for r in reels[:10]:
        reel_lines.append(
            f"  - Reel {r.get('timestamp', '')[:10]} | Plays: {r.get('playCount', 0)}, "
            f"Likes: {r.get('likesCount', 0)}, Comments: {r.get('commentsCount', 0)}, "
            f"Duration: {r.get('duration', 0)}s, Audio: {r.get('musicInfo', '')}\n"
            f"    Caption: {(r.get('caption') or '')[:160]}"
        )

    # Comments per post — top-5 posts, top-15 comments each
    comment_lines = []
    sorted_posts_for_comments = sorted(
        posts,
        key=lambda p: (p.get("likesCount") or 0) + (p.get("commentsCount") or 0),
        reverse=True,
    )[:5]
    for idx, p in enumerate(sorted_posts_for_comments, start=1):
        cs = comments_by_post.get(p.get("url"), [])
        if not cs:
            continue
        top_cs = sorted(cs, key=lambda c: c.get("likesCount") or 0, reverse=True)[:15]
        block = [f"  Post #{idx} ({p.get('url', '')}, {p.get('likesCount', 0)} likes):"]
        for c in top_cs:
            block.append(f"    @{c.get('ownerUsername', '?')}: {(c.get('text') or '')[:160]}")
        comment_lines.append("\n".join(block))

    # Tagged posts (UGC mentions)
    tagged_lines = []
    for t in tagged[:12]:
        tagged_lines.append(
            f"  - @{t.get('ownerUsername', '?')} | Likes: {t.get('likesCount', 0)}, "
            f"Comments: {t.get('commentsCount', 0)} | Caption: {(t.get('caption') or '')[:140]}"
        )

    blocks = [f"\n=== @{username} [{role}] ==="]
    blocks.extend(p_lines)
    if post_lines:
        blocks.append(f"\nPOSTS ({len(posts)} fetched, showing top {len(post_lines)}):")
        blocks.extend(post_lines)
    if reel_lines:
        blocks.append(f"\nREELS ({len(reels)} fetched, showing {len(reel_lines)}):")
        blocks.extend(reel_lines)
    if comment_lines:
        blocks.append(f"\nCOMMENTS (top {len(comment_lines)} posts):")
        blocks.extend(comment_lines)
    if tagged_lines:
        blocks.append(f"\nTAGGED / UGC ({len(tagged)} fetched, showing {len(tagged_lines)}):")
        blocks.extend(tagged_lines)

    return "\n".join(blocks)


def _build_user_message(
    scraped_data: dict[str, dict],
    business_problems: list[str],
    scrape_period: str,
    report_month: str,
) -> str:
    accounts_list = list(scraped_data.keys())
    primary_handle = accounts_list[0] if accounts_list else ""

    bp_lines = "\n".join(f"BP{i+1}: {p}" for i, p in enumerate(business_problems)) or "(none specified — derive plausible BPs from the brand's posting behaviour)"

    accounts_block = []
    for username, data in scraped_data.items():
        role = "PRIMARY BRAND BEING ANALYSED" if username == primary_handle else "competitor / comparable account"
        accounts_block.append(_format_account_block(username, role, data))

    data_block = "\n".join(accounts_block)

    schema = """{
  "header": {
    "brand_name": "inferred prettified brand name from the primary handle",
    "brand_category": "inferred category",
    "title_line": "[BRAND_NAME] Instagram Strategy | Competitive Analysis & Recommendations | [Month Year]",
    "subtitle": "Competitive Analysis & Recommendations",
    "prepared_for": "Prepared for the [BRAND_NAME] Brand Team",
    "data_note": "Data scraped via Apify | Analysis date: [Month Year]",
    "accounts_analysed_line": "@a, @b, @c",
    "anchored_to_bps": ["BP1: ...", "BP2: ..."]
  },
  "section1": {
    "intro_italic": "one line on scrape range, ER calculation, asterisks",
    "at_a_glance": [
      {"account": "@handle", "followers": "X", "following": "X", "posts": "X", "verified": "Yes|No", "avg_er": "X%", "format_mix": "Reels X% / Carousel X% / Image X%", "posts_per_week": "X"}
    ],
    "footnotes": ["* explanation"],
    "accounts": [
      {
        "name": "Pretty Brand Name",
        "handle": "@handle",
        "header_line": "Follower count: X | Posts: X | Verified: Yes|No | Avg ER: X%",
        "content_format_mix": ["Reels: X% — description", "Carousel: X% — description"],
        "posting_frequency": "X posts/week. Context paragraph.",
        "top_5_posts": [
          {"rank": 1, "caption_excerpt": "...", "type": "Reel|Image|Carousel", "likes": "X", "comments": "X", "why_it_worked": "analytical reason"}
        ],
        "content_themes": ["theme 1", "theme 2"],
        "brand_voice": ["voice characteristic 1"],
        "engagement_patterns": ["pattern 1"],
        "key_insight": "one paragraph",
        "is_limited_data": false,
        "key_observations": []
      }
    ]
  },
  "section2": {
    "axis1": "Horizontal: Pole A ↔ Pole B",
    "axis2": "Vertical: Pole C ↔ Pole D",
    "positioning_table": [
      {"brand": "@handle", "axis1_position": "...", "axis2_position": "...", "content_territory": "..."}
    ],
    "strategic_positioning_summary": "paragraph describing each quadrant",
    "critical_observation_title": "Critical Observation: [BRAND]'s Positioning Problem",
    "critical_observation_body": "paragraph"
  },
  "section3": {
    "header_line": "@handle | X followers | X total posts | X own posts in last [period]",
    "doing_well": ["bullet 1"],
    "doing_poorly_isolated": ["bullet 1"],
    "doing_poorly_vs_competition": ["bullet 1 — Competitor's X% ER beats brand's Y% on similar content"],
    "er_comparison": "paragraph",
    "status_summary_bold": "one bolded sentence",
    "content_calendar_pattern": ["bullet 1"],
    "creator_collaboration_presence": ["bullet 1"]
  },
  "section4": {
    "themes_no_brand_owns": ["bullet 1"],
    "underutilised_formats": ["bullet 1"],
    "emotional_territories": ["bullet 1 — connected to audience insight"],
    "audience_conversations": ["bullet 1"],
    "visual_whitespace": ["bullet 1"]
  },
  "section5": {
    "blocks": [
      {
        "letter": "A",
        "problem": "BP statement verbatim",
        "competitors_doing_successfully": ["@handle's [post type] used [mechanic] to [effect]"],
        "underrepresented_occasions": ["specific occasion 1"],
        "content_strategies": ["IG-specific tactic 1"],
        "recommended_territories": [
          {"territory_name": "\\"Territory Name\\"", "anchor": "time/occasion", "caption_example": "\\"caption text\\"", "why_solves_bp": "one sentence"}
        ]
      }
    ]
  },
  "section6": {
    "content_pillars": [
      {"pillar_name": "...", "content": "what falls under it", "bp_addressed": "BP1|BP2|...", "engagement_potential": "High|Medium|Low + reasoning"}
    ],
    "format_mix": [
      {"format": "Reels", "pct_of_mix": "X%", "posts_per_week": "X", "story_usage": "...", "rationale": "..."}
    ],
    "posting_cadence": ["bullet 1"],
    "tone_of_voice": {
      "defining_characteristics": [{"label": "Characteristic Label", "explanation": "one sentence"}],
      "example_captions": ["caption 1"],
      "donts": ["DON'T: behaviour — Competitor's X% ER on Y followers is what this gets you"]
    },
    "creator_strategy": {
      "archetype_table": [
        {"archetype": "...", "size": "Micro|Mid|Macro", "content_genre": "...", "platforms": "IG, YT, etc.", "fit_for_brand": "..."}
      ],
      "always_on_layer": {"brief": "...", "budget": "...", "content_approach": "..."},
      "campaign_layer": {"brief": "...", "budget": "...", "content_approach": "..."},
      "additional_layer": {"name": "e.g., ASMR LAYER", "brief": "...", "budget": "...", "content_approach": "..."}
    },
    "craft_standards": {
      "hook_style": ["bullet 1"],
      "visual_treatment": ["bullet 1"],
      "caption_structure": ["bullet 1"]
    }
  },
  "summary": {
    "intro_italic": "Prioritised by expected impact on the business problems. Implement in sequence.",
    "immediate": [{"label": "BOLD ACTION LABEL", "action": "specific action", "bp_impact": "BP1, BP3", "effort_signal": "Cost: ... / Brief: ..."}],
    "short_term": [{"label": "...", "action": "...", "bp_impact": "...", "effort_signal": "..."}],
    "medium_term": [{"label": "...", "action": "...", "bp_impact": "...", "effort_signal": "..."}]
  },
  "footer": {
    "data_source": "Data source: Apify Instagram Scraper",
    "posts_scraped": 75,
    "accounts_count": 5,
    "scrape_period": "scrape period text",
    "analysis_powered_by": "Analysis powered by Claude AI",
    "prepared_for": "Prepared for the [BRAND_NAME] Brand Team"
  }
}"""

    return f"""INPUTS:

BRAND_NAME: derive a pretty name from the first/primary handle @{primary_handle}
BRAND_CATEGORY: infer from the brand and competitive set
BUSINESS_PROBLEMS:
{bp_lines}

ACCOUNTS_ANALYSED: {", ".join(f"@{a}" for a in accounts_list)}
PRIMARY BRAND (audit subject for Section 3): @{primary_handle}

SCRAPE_PERIOD: {scrape_period}
REPORT_MONTH: {report_month}

SCRAPED DATA:
{data_block}

Return ONLY a JSON object matching this exact schema. No markdown, no code fences. Use concrete numbers from the data above. Follow every rule in the system prompt.

SCHEMA:
{schema}
"""


def analyse(scraped_data: dict[str, list[dict]], business_problems: list[str] | None = None) -> dict:
    now = datetime.now()
    report_month = now.strftime("%B %Y")
    scrape_period = report_month  # single-snapshot scrape; emailer footer will reference the run date

    user_message = _build_user_message(
        scraped_data=scraped_data,
        business_problems=business_problems or [],
        scrape_period=scrape_period,
        report_month=report_month,
    )

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY())

    logger.info("Sending data to Claude for analysis...")
    with client.messages.stream(
        model=MODEL,
        max_tokens=64000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    ) as stream:
        message = stream.get_final_message()

    if message.stop_reason == "max_tokens":
        logger.warning("Claude hit max_tokens — report may be truncated.")

    raw = message.content[0].text.strip()

    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        report = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error(f"Claude returned invalid JSON: {exc}\nRaw response:\n{raw[:500]}")
        raise

    # Carry through metadata the emailer / docx renderer needs
    report.setdefault("_meta", {})
    report["_meta"]["report_date"] = now.strftime("%B %d, %Y")
    report["_meta"]["scrape_period"] = scrape_period
    report["_meta"]["accounts_count"] = len(scraped_data)
    report["_meta"]["posts_scraped"] = sum(len(p) for p in scraped_data.values())

    logger.info("Analysis complete.")
    return report

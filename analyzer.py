import json
import logging
from datetime import datetime
import anthropic
import config

logger = logging.getLogger(__name__)

MODEL = "claude-sonnet-4-6"


def _build_prompt(scraped_data: dict[str, list[dict]], report_date: str) -> str:
    accounts_summary = []
    for username, posts in scraped_data.items():
        if not posts:
            accounts_summary.append(f"\n@{username}: No posts scraped (scrape failed or private account)")
            continue

        post_lines = []
        for p in posts:
            views = f", Views: {p['videoViewCount']}" if p.get("videoViewCount") else ""
            audio = f", Audio: {p['musicInfo']}" if p.get("musicInfo") else ""
            post_lines.append(
                f"  - [{p['type']}] Likes: {p['likesCount']}, Comments: {p['commentsCount']}{views}{audio} | "
                f"Caption: {p['caption'][:200]} | URL: {p['url']}"
            )

        accounts_summary.append(f"\n@{username} ({len(posts)} posts):\n" + "\n".join(post_lines))

    data_block = "\n".join(accounts_summary)
    accounts_list = ", ".join(f"@{u}" for u in scraped_data.keys())

    return f"""You are an expert social media strategist and competitive analyst. Analyse the following Instagram data scraped on {report_date} and generate a comprehensive trend report.

SCRAPED DATA:
{data_block}

Generate a detailed competitive analysis report following EXACTLY this structure. Return ONLY a valid JSON object — no markdown, no code blocks, just raw JSON.

The JSON must have this exact shape:
{{
  "report_date": "{report_date}",
  "accounts_analysed": "{accounts_list}",
  "section1": {{
    "title": "COMPETITIVE LANDSCAPE",
    "accounts": [
      {{
        "username": "handle",
        "display_name": "Name",
        "follower_snapshot": "estimated or noted",
        "content_format_mix": "breakdown of Reels vs static vs carousel etc",
        "posting_frequency": "estimated from data",
        "top_5_posts": [
          {{
            "rank": 1,
            "caption_preview": "first 100 chars of caption",
            "url": "post url",
            "display_url": "thumbnail url",
            "type": "Reel/Image/Carousel",
            "likes": 0,
            "comments": 0,
            "video_views": 0,
            "audio": "audio name or empty string"
          }}
        ],
        "content_themes": "themes and pillars observed",
        "brand_voice": "tone and style description",
        "engagement_patterns": "what drives engagement for this account"
      }}
    ]
  }},
  "section2": {{
    "title": "CROSS-ACCOUNT TREND SIGNALS",
    "top_performing_formats": "detailed analysis",
    "hook_patterns": "hooks that appear to be working across accounts",
    "trending_audio": "list of audio tracks and their frequency",
    "engagement_benchmarks": "average likes, comments, views across accounts"
  }},
  "section3": {{
    "title": "STRATEGIC RECOMMENDATIONS",
    "content_formats_to_prioritise": "specific recommendations",
    "hook_styles_to_test": "specific hook styles with examples",
    "audio_opportunities": "specific audio tracks to use",
    "posting_cadence": "recommended days/times/frequency",
    "watch_list": "accounts or trends to monitor next period"
  }}
}}

Base all analysis strictly on the data provided. For top_5_posts, pick the 5 posts with highest engagement (likes + comments + video_views). Include the actual url and display_url values from the data. Be specific, actionable, and data-driven in all sections."""


def analyse(scraped_data: dict[str, list[dict]]) -> dict:
    report_date = datetime.now().strftime("%B %d, %Y")
    prompt = _build_prompt(scraped_data, report_date)

    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY())

    logger.info("Sending data to Claude for analysis...")
    message = client.messages.create(
        model=MODEL,
        max_tokens=16384,
        messages=[{"role": "user", "content": prompt}],
    )
    if message.stop_reason == "max_tokens":
        logger.warning("Claude hit max_tokens — report may be truncated.")

    raw = message.content[0].text.strip()

    # Strip markdown code fences if Claude wraps in them anyway
    if raw.startswith("```"):
        lines = raw.split("\n")
        raw = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        report = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error(f"Claude returned invalid JSON: {exc}\nRaw response:\n{raw[:500]}")
        raise

    # Attach raw posts for the emailer's Top 5 tables (sorted by engagement)
    report["_raw_posts"] = {}
    for username, posts in scraped_data.items():
        sorted_posts = sorted(
            posts,
            key=lambda p: (p.get("likesCount") or 0) + (p.get("commentsCount") or 0) + (p.get("videoViewCount") or 0),
            reverse=True,
        )
        report["_raw_posts"][username] = sorted_posts[:5]

    logger.info("Analysis complete.")
    return report

"""Multi-actor Instagram scraper.

For each account we orchestrate four Apify actors:
  1. apify/instagram-profile-scraper — profile metadata (followers, verified, bio)
  2. apify/instagram-scraper          — recent posts + engagement
  3. apify/instagram-reel-scraper     — Reels with accurate play counts
  4. apify/instagram-comment-scraper  — comments on the top-5 posts per account
  5. apify/instagram-tagged-scraper   — UGC / creator-tagged posts (best-effort)

Any single actor failure is downgraded to an empty result for that slice so
the pipeline can still produce a partial report instead of erroring out.
"""
import time
import logging
from apify_client import ApifyClient
import config

logger = logging.getLogger(__name__)

POSTS_PER_ACCOUNT = 30
REELS_PER_ACCOUNT = 15
TAGGED_PER_ACCOUNT = 15
COMMENTS_PER_POST = 30
COMMENTS_TOP_N_POSTS = 5
DELAY_BETWEEN_ACCOUNTS_SECONDS = 4


def _run_field(run, *names):
    """Read a field from an apify-client 2.x Run object (attribute access)
    or 1.x dict (bracket access). Falls back to model_dump."""
    for n in names:
        if hasattr(run, n):
            val = getattr(run, n)
            if val is not None:
                return val
    for n in names:
        try:
            return run[n]
        except (TypeError, KeyError):
            continue
    if hasattr(run, "model_dump"):
        d = run.model_dump(by_alias=True)
        for n in names:
            if n in d and d[n] is not None:
                return d[n]
    return None


def _run_actor(client: ApifyClient, actor_id: str, run_input: dict, label: str) -> list[dict]:
    """Call an actor and return its dataset items. Empty list on any failure."""
    try:
        logger.info(f"  · {label}: starting {actor_id}...")
        run = client.actor(actor_id).call(run_input=run_input)
        status = _run_field(run, "status")
        if status != "SUCCEEDED":
            logger.warning(f"  · {label}: actor ended with status {status}")
            return []
        dataset_id = _run_field(run, "default_dataset_id", "defaultDatasetId")
        if not dataset_id:
            logger.warning(f"  · {label}: no dataset id returned")
            return []
        items = list(client.dataset(dataset_id).iterate_items())
        logger.info(f"  · {label}: {len(items)} items")
        return items
    except Exception as exc:
        logger.warning(f"  · {label}: failed — {exc}")
        return []


# ── Per-slice scrapers ───────────────────────────────────────────────────────

def _scrape_profile(client: ApifyClient, username: str) -> dict:
    items = _run_actor(
        client,
        "apify/instagram-profile-scraper",
        {"usernames": [username]},
        f"@{username} profile",
    )
    return items[0] if items else {}


def _extract_post(item: dict) -> dict:
    music = item.get("musicInfo", {}) or {}
    return {
        "url": item.get("url") or f"https://www.instagram.com/p/{item.get('shortCode', '')}",
        "shortCode": item.get("shortCode", ""),
        "caption": (item.get("caption") or "")[:500],
        "likesCount": item.get("likesCount") or 0,
        "commentsCount": item.get("commentsCount") or 0,
        "type": item.get("type") or ("Video" if item.get("isVideo") else "Image"),
        "musicInfo": music.get("musicName") or music.get("songName") or "",
        "displayUrl": item.get("displayUrl") or item.get("thumbnailUrl") or "",
        "timestamp": item.get("timestamp") or item.get("takenAtTimestamp") or "",
        "ownerUsername": item.get("ownerUsername") or item.get("username") or "",
        "videoViewCount": item.get("videoViewCount") or item.get("videoPlayCount") or item.get("playCount") or 0,
        "hashtags": item.get("hashtags") or [],
        "mentions": item.get("mentions") or [],
    }


def _scrape_posts(client: ApifyClient, username: str) -> list[dict]:
    items = _run_actor(
        client,
        "apify/instagram-scraper",
        {
            "directUrls": [f"https://www.instagram.com/{username}/"],
            "resultsType": "posts",
            "resultsLimit": POSTS_PER_ACCOUNT,
            "addParentData": True,
        },
        f"@{username} posts",
    )
    return [_extract_post(it) for it in items]


def _extract_reel(item: dict) -> dict:
    music = item.get("musicInfo", {}) or {}
    return {
        "url": item.get("url") or f"https://www.instagram.com/reel/{item.get('shortCode', '')}",
        "shortCode": item.get("shortCode", ""),
        "caption": (item.get("caption") or "")[:500],
        "likesCount": item.get("likesCount") or 0,
        "commentsCount": item.get("commentsCount") or 0,
        "playCount": item.get("playCount") or item.get("videoPlayCount") or item.get("videoViewCount") or 0,
        "duration": item.get("videoDuration") or item.get("duration") or 0,
        "musicInfo": music.get("musicName") or music.get("songName") or "",
        "displayUrl": item.get("displayUrl") or "",
        "timestamp": item.get("timestamp") or "",
    }


def _scrape_reels(client: ApifyClient, username: str) -> list[dict]:
    items = _run_actor(
        client,
        "apify/instagram-reel-scraper",
        {
            "username": [username],
            "resultsLimit": REELS_PER_ACCOUNT,
        },
        f"@{username} reels",
    )
    return [_extract_reel(it) for it in items]


def _extract_comment(item: dict) -> dict:
    return {
        "text": (item.get("text") or "")[:400],
        "ownerUsername": item.get("ownerUsername") or item.get("owner", {}).get("username", "") or "",
        "likesCount": item.get("likesCount") or 0,
        "replyCount": item.get("repliesCount") or item.get("replyCount") or 0,
        "postUrl": item.get("postUrl") or item.get("ownerUrl") or "",
    }


def _scrape_comments(client: ApifyClient, post_urls: list[str]) -> dict[str, list[dict]]:
    if not post_urls:
        return {}
    items = _run_actor(
        client,
        "apify/instagram-comment-scraper",
        {"directUrls": post_urls, "resultsLimit": COMMENTS_PER_POST},
        f"comments on {len(post_urls)} top posts",
    )
    by_post: dict[str, list[dict]] = {}
    for raw in items:
        c = _extract_comment(raw)
        # group by the post URL or, failing that, the comment's parent post
        key = c["postUrl"]
        if not key:
            continue
        by_post.setdefault(key, []).append(c)
    return by_post


def _extract_tagged(item: dict) -> dict:
    return {
        "url": item.get("url") or "",
        "shortCode": item.get("shortCode", ""),
        "caption": (item.get("caption") or "")[:300],
        "ownerUsername": item.get("ownerUsername") or item.get("username") or "",
        "likesCount": item.get("likesCount") or 0,
        "commentsCount": item.get("commentsCount") or 0,
        "displayUrl": item.get("displayUrl") or "",
        "timestamp": item.get("timestamp") or "",
    }


def _scrape_tagged(client: ApifyClient, username: str) -> list[dict]:
    items = _run_actor(
        client,
        "apify/instagram-tagged-scraper",
        {
            "username": [username],
            "resultsLimit": TAGGED_PER_ACCOUNT,
        },
        f"@{username} tagged",
    )
    return [_extract_tagged(it) for it in items]


# ── Public entrypoint ────────────────────────────────────────────────────────

def scrape_accounts(accounts: list[str]) -> dict[str, dict]:
    """For each account, fetch profile + posts + reels + comments + tagged.

    Returns a dict keyed by username with this shape per entry:
        {
            "username": str,
            "profile": dict,                          # profile-scraper output
            "posts": list[dict],                      # extracted posts
            "reels": list[dict],                      # extracted reels
            "comments": dict[post_url, list[dict]],   # comments per top post
            "tagged_posts": list[dict],               # UGC mentioning the account
        }
    """
    client = ApifyClient(config.APIFY_API_TOKEN())
    results: dict[str, dict] = {}

    for i, username in enumerate(accounts):
        logger.info(f"=== Scraping @{username} ({i+1}/{len(accounts)}) ===")

        profile = _scrape_profile(client, username)
        posts = _scrape_posts(client, username)
        reels = _scrape_reels(client, username)
        tagged = _scrape_tagged(client, username)

        # Pick the top-N posts by total engagement for comment scraping.
        engagement = lambda p: (p.get("likesCount") or 0) + (p.get("commentsCount") or 0) + (p.get("videoViewCount") or 0)
        top_posts = sorted(posts, key=engagement, reverse=True)[:COMMENTS_TOP_N_POSTS]
        top_urls = [p["url"] for p in top_posts if p.get("url")]
        comments_by_post = _scrape_comments(client, top_urls)

        results[username] = {
            "username": username,
            "profile": profile,
            "posts": posts,
            "reels": reels,
            "comments": comments_by_post,
            "tagged_posts": tagged,
        }

        if i < len(accounts) - 1:
            logger.info(f"Waiting {DELAY_BETWEEN_ACCOUNTS_SECONDS}s before next account...")
            time.sleep(DELAY_BETWEEN_ACCOUNTS_SECONDS)

    return results

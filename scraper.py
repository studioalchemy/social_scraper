"""Multi-actor Instagram scraper.

For each account we orchestrate six Apify actors:
  1. apify/instagram-profile-scraper      — profile metadata
  2. apify/instagram-scraper              — recent posts + engagement
  3. apify/instagram-reel-scraper         — Reels with accurate play counts
  4. apify/instagram-comment-scraper      — comments on the top-5 posts
  5. apify/instagram-tagged-scraper       — UGC / creator-tagged posts
  6. apify/brand-collaboration-scraper    — sponsored / paid-partnership posts
                                            (links the brand to creators)

Any single actor failure is downgraded to an empty result for that slice so
the pipeline can still produce a partial report instead of erroring out.
"""
import time
import logging
from datetime import datetime, timezone
from apify_client import ApifyClient
import config

logger = logging.getLogger(__name__)

POSTS_PER_ACCOUNT = 30
REELS_PER_ACCOUNT = 15
TAGGED_PER_ACCOUNT = 15
COLLABS_PER_ACCOUNT = 20
COMMENTS_PER_POST = 30
COMMENTS_TOP_N_POSTS = 5
DELAY_BETWEEN_ACCOUNTS_SECONDS = 4


def _parse_ts(ts) -> datetime | None:
    """Best-effort parse for Apify timestamps (ISO strings or unix seconds)."""
    if ts is None or ts == "":
        return None
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc)
        except (ValueError, OSError):
            return None
    if isinstance(ts, str):
        try:
            return datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _within_window(item: dict, since_dt: datetime | None, until_dt: datetime | None) -> bool:
    """Keep the item if its timestamp falls inside [since, until].
    If we can't read the timestamp, keep it — better than silently dropping data."""
    if since_dt is None and until_dt is None:
        return True
    ts = _parse_ts(item.get("timestamp"))
    if ts is None:
        return True
    if since_dt and ts < since_dt:
        return False
    if until_dt and ts > until_dt:
        return False
    return True


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


def _scrape_posts(client: ApifyClient, username: str, since_iso: str | None = None) -> list[dict]:
    run_input = {
        "directUrls": [f"https://www.instagram.com/{username}/"],
        "resultsType": "posts",
        "resultsLimit": POSTS_PER_ACCOUNT,
        "addParentData": True,
    }
    if since_iso:
        # The instagram-scraper actor accepts a YYYY-MM-DD cutoff here.
        run_input["onlyPostsNewerThan"] = since_iso
    items = _run_actor(
        client,
        "apify/instagram-scraper",
        run_input,
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


def _extract_collab(item: dict) -> dict:
    """Normalize a brand-collaboration record.

    The actor's exact field names aren't fully documented; we probe several
    likely keys for creator handle / post URL / type so an upstream rename
    doesn't silently zero out the section.
    """
    creator = (
        item.get("creatorUsername")
        or item.get("creator", {}).get("username") if isinstance(item.get("creator"), dict) else None
    ) or item.get("collaboratorUsername") or item.get("partnerUsername") or item.get("ownerUsername") or ""
    return {
        "creator_handle": creator,
        "post_url": item.get("postUrl") or item.get("url") or "",
        "post_type": item.get("type") or item.get("mediaType") or "",
        "caption_excerpt": (item.get("caption") or "")[:240],
        "likes": item.get("likesCount") or item.get("likes") or 0,
        "comments": item.get("commentsCount") or item.get("comments") or 0,
        "views": item.get("videoViewCount") or item.get("playCount") or 0,
        "timestamp": item.get("timestamp") or "",
        "is_paid_partnership": item.get("isPaidPartnership") or item.get("paidPartnership") or False,
    }


def _scrape_collaborations(client: ApifyClient, username: str) -> list[dict]:
    items = _run_actor(
        client,
        "apify/brand-collaboration-scraper",
        {
            "usernames": [username],
            "resultsLimit": COLLABS_PER_ACCOUNT,
        },
        f"@{username} brand collaborations",
    )
    return [_extract_collab(it) for it in items]


# ── Public entrypoint ────────────────────────────────────────────────────────

def scrape_accounts(
    accounts: list[str],
    since_iso: str | None = None,
    until_iso: str | None = None,
) -> dict[str, dict]:
    """For each account, fetch profile + posts + reels + comments + tagged + collaborations.

    `since_iso` / `until_iso` are inclusive date-only bounds (YYYY-MM-DD). When set,
    items outside the window are dropped after extraction. The posts actor also
    receives `onlyPostsNewerThan` so it can short-circuit upstream.

    Returns a dict keyed by username with this shape per entry:
        {
            "username": str,
            "profile": dict,                          # profile-scraper output
            "posts": list[dict],                      # extracted posts
            "reels": list[dict],                      # extracted reels
            "comments": dict[post_url, list[dict]],   # comments per top post
            "tagged_posts": list[dict],               # UGC mentioning the account
            "collaborations": list[dict],             # paid / brand partnerships
        }
    """
    client = ApifyClient(config.APIFY_API_TOKEN())
    results: dict[str, dict] = {}

    since_dt = _parse_ts(since_iso) if since_iso else None
    until_dt = _parse_ts(until_iso) if until_iso else None
    if since_dt or until_dt:
        logger.info(f"Lookback window: {since_iso or '—'} → {until_iso or 'now'}")

    for i, username in enumerate(accounts):
        logger.info(f"=== Scraping @{username} ({i+1}/{len(accounts)}) ===")

        profile = _scrape_profile(client, username)
        posts = _scrape_posts(client, username, since_iso=since_iso)
        reels = _scrape_reels(client, username)
        tagged = _scrape_tagged(client, username)
        collaborations = _scrape_collaborations(client, username)

        # Post-filter every time-bound slice to the window so slices that don't
        # natively support date filters still respect it.
        if since_dt or until_dt:
            posts = [p for p in posts if _within_window(p, since_dt, until_dt)]
            reels = [r for r in reels if _within_window(r, since_dt, until_dt)]
            tagged = [t for t in tagged if _within_window(t, since_dt, until_dt)]
            collaborations = [c for c in collaborations if _within_window(c, since_dt, until_dt)]

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
            "collaborations": collaborations,
        }

        if i < len(accounts) - 1:
            logger.info(f"Waiting {DELAY_BETWEEN_ACCOUNTS_SECONDS}s before next account...")
            time.sleep(DELAY_BETWEEN_ACCOUNTS_SECONDS)

    return results

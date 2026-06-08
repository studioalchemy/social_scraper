import time
import logging
from apify_client import ApifyClient
import config

logger = logging.getLogger(__name__)

POSTS_PER_ACCOUNT = 15
POLL_INTERVAL_SECONDS = 15
TIMEOUT_SECONDS = 600  # 10 minutes
DELAY_BETWEEN_ACCOUNTS_SECONDS = 5


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
        "videoViewCount": item.get("videoViewCount") or item.get("videoPlayCount") or 0,
    }


def _run_actor_for_account(client: ApifyClient, username: str) -> list[dict]:
    run_input = {
        "directUrls": [f"https://www.instagram.com/{username}/"],
        "resultsType": "posts",
        "resultsLimit": POSTS_PER_ACCOUNT,
        "addParentData": False,
    }

    logger.info(f"Starting Apify actor run for @{username}...")
    # apify-client 2.x: .call() returns a Run typed-dict object that
    # supports bracket access but not .get(). Default actor timeout applies.
    run = client.actor("apify/instagram-scraper").call(run_input=run_input)

    status = run["status"] if run else None
    if status != "SUCCEEDED":
        raise RuntimeError(f"Apify run for @{username} ended with status: {status}")

    dataset_id = run["defaultDatasetId"]
    items = list(client.dataset(dataset_id).iterate_items())
    logger.info(f"  @{username}: fetched {len(items)} posts")
    return [_extract_post(item) for item in items]


def scrape_accounts(accounts: list[str]) -> dict[str, list[dict]]:
    client = ApifyClient(config.APIFY_API_TOKEN())
    results: dict[str, list[dict]] = {}

    for i, username in enumerate(accounts):
        try:
            posts = _run_actor_for_account(client, username)
            results[username] = posts
        except Exception as exc:
            logger.error(f"Failed to scrape @{username}: {exc}")
            results[username] = []

        if i < len(accounts) - 1:
            logger.info(f"Waiting {DELAY_BETWEEN_ACCOUNTS_SECONDS}s before next account...")
            time.sleep(DELAY_BETWEEN_ACCOUNTS_SECONDS)

    return results

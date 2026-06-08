import smtplib
import socket
import logging
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
import config

logger = logging.getLogger(__name__)

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_TIMEOUT = 30

THUMBNAIL_FETCH_TIMEOUT = 10  # seconds per image


class IPv4SMTP(smtplib.SMTP):
    """Forces IPv4 for the SMTP connection.

    On hosts whose IPv6 stack has no route to the SMTP server (common on
    some PaaS containers), Python's default resolver returns the AAAA
    record first and the connect fails with ENETUNREACH. Resolving as
    AF_INET only sidesteps the problem.
    """

    def _get_socket(self, host, port, timeout):
        infos = socket.getaddrinfo(host, port, socket.AF_INET, socket.SOCK_STREAM)
        _, _, _, _, addr = infos[0]
        sock = socket.create_connection(addr, timeout=timeout)
        return sock


# ── HTML helpers ─────────────────────────────────────────────────────────────

def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _img_src(url: str, cid_map: dict) -> str:
    # If we managed to inline this URL at send-time, point at the CID attachment
    # so the thumbnail survives Instagram's signed-URL expiry.
    cid = cid_map.get(url)
    return f"cid:{cid}" if cid else url


def _section_header(number: str, title: str) -> str:
    return f"""
    <div class="section-header">
      <span class="section-number">SECTION {_esc(number)}</span>
      <h2>{_esc(title)}</h2>
    </div>"""


def _sub_header(text: str) -> str:
    return f'<h3 class="sub-header">{_esc(text)}</h3>'


def _prose(text: str) -> str:
    if not text:
        return ""
    paragraphs = str(text).split("\n")
    return "".join(f"<p>{_esc(p.strip())}</p>" for p in paragraphs if p.strip())


def _account_card(account_data: dict, raw_posts: list[dict], cid_map: dict) -> str:
    username = account_data.get("username", "")
    display_name = account_data.get("display_name", username)

    rows = ""
    posts_to_show = account_data.get("top_5_posts") or []

    # Prefer raw_posts for accurate urls/thumbnails if available
    if raw_posts:
        for i, post in enumerate(raw_posts):
            views_cell = (
                f'<td class="num">{post.get("videoViewCount", 0):,}</td>'
                if post.get("videoViewCount")
                else '<td class="num muted">—</td>'
            )
            audio_cell = (
                f'<td class="audio">{_esc(post.get("musicInfo", ""))}</td>'
                if post.get("musicInfo")
                else '<td class="audio muted">—</td>'
            )
            thumb = post.get("displayUrl", "")
            url = post.get("url", "#")
            caption = post.get("caption", "")[:120]
            img_html = (
                f'<img src="{_esc(_img_src(thumb, cid_map))}" alt="thumb" width="120">'
                if thumb else ''
            )
            rows += f"""
            <tr>
              <td class="rank">#{i + 1}</td>
              <td class="thumb">{img_html}</td>
              <td class="caption"><a href="{_esc(url)}" target="_blank" rel="noopener">{_esc(caption) or "(no caption)"}</a></td>
              <td class="badge">{_esc(post.get("type", ""))}</td>
              <td class="num">{post.get("likesCount", 0):,}</td>
              <td class="num">{post.get("commentsCount", 0):,}</td>
              {views_cell}
              {audio_cell}
            </tr>"""
    else:
        # Fall back to Claude-synthesised top_5_posts
        for i, p in enumerate(posts_to_show):
            thumb = p.get("display_url", "")
            url = p.get("url", "#")
            caption = p.get("caption_preview", "")
            img_html = (
                f'<img src="{_esc(_img_src(thumb, cid_map))}" alt="thumb" width="120">'
                if thumb else ''
            )
            rows += f"""
            <tr>
              <td class="rank">#{_esc(str(p.get("rank", i + 1)))}</td>
              <td class="thumb">{img_html}</td>
              <td class="caption"><a href="{_esc(url)}" target="_blank" rel="noopener">{_esc(caption) or "(no caption)"}</a></td>
              <td class="badge">{_esc(str(p.get("type", "")))}</td>
              <td class="num">{p.get("likes", 0):,}</td>
              <td class="num">{p.get("comments", 0):,}</td>
              <td class="num muted">{p.get("video_views", 0):,}</td>
              <td class="audio">{_esc(str(p.get("audio", "") or "—"))}</td>
            </tr>"""

    table = f"""
    <table class="posts-table">
      <thead>
        <tr>
          <th>#</th><th>Thumb</th><th>Caption</th><th>Type</th>
          <th>Likes</th><th>Comments</th><th>Views</th><th>Audio</th>
        </tr>
      </thead>
      <tbody>{rows}</tbody>
    </table>""" if rows else "<p class='muted'>No posts available.</p>"

    def row(label: str, value: str) -> str:
        return f"<tr><td class='meta-label'>{_esc(label)}</td><td>{_esc(str(value))}</td></tr>"

    meta_table = f"""
    <table class="meta-table">
      {row("Follower Snapshot", account_data.get("follower_snapshot", "—"))}
      {row("Content Format Mix", account_data.get("content_format_mix", "—"))}
      {row("Posting Frequency", account_data.get("posting_frequency", "—"))}
      {row("Content Themes", account_data.get("content_themes", "—"))}
      {row("Brand Voice", account_data.get("brand_voice", "—"))}
      {row("Engagement Patterns", account_data.get("engagement_patterns", "—"))}
    </table>"""

    return f"""
    <div class="account-card">
      <h3 class="account-title">{_esc(display_name)} <span class="handle">@{_esc(username)}</span></h3>
      {meta_table}
      <h4 class="posts-heading">Top 5 Performing Posts</h4>
      {table}
    </div>"""


def build_html(report: dict, cid_map: dict | None = None) -> str:
    cid_map = cid_map or {}
    report_date = report.get("report_date", "")
    accounts_analysed = report.get("accounts_analysed", "")
    raw_posts_map: dict = report.get("_raw_posts", {})

    section1 = report.get("section1", {})
    section2 = report.get("section2", {})
    section3 = report.get("section3", {})

    # Section 1 — account cards
    account_cards = ""
    for acc in section1.get("accounts", []):
        username = acc.get("username", "")
        account_cards += _account_card(acc, raw_posts_map.get(username, []), cid_map)

    def s2_row(label: str, key: str) -> str:
        return f"""
        <div class="insight-block">
          <div class="insight-label">{_esc(label)}</div>
          {_prose(section2.get(key, "—"))}
        </div>"""

    section2_html = (
        s2_row("2.1 Top Performing Content Formats", "top_performing_formats")
        + s2_row("2.2 Hook Patterns That Are Working", "hook_patterns")
        + s2_row("2.3 Trending Audio / Music", "trending_audio")
        + s2_row("2.4 Engagement Benchmarks", "engagement_benchmarks")
    )

    def s3_row(label: str, key: str) -> str:
        return f"""
        <div class="insight-block">
          <div class="insight-label">{_esc(label)}</div>
          {_prose(section3.get(key, "—"))}
        </div>"""

    section3_html = (
        s3_row("3.1 Content Formats to Prioritise", "content_formats_to_prioritise")
        + s3_row("3.2 Hook Styles to Test", "hook_styles_to_test")
        + s3_row("3.3 Audio Opportunities", "audio_opportunities")
        + s3_row("3.4 Posting Cadence Recommendation", "posting_cadence")
        + s3_row("3.5 Watch List", "watch_list")
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Instagram Trend Report</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: #0f0f0f; color: #e0e0e0; font-family: 'Helvetica Neue', Arial, sans-serif;
    font-size: 14px; line-height: 1.6;
  }}
  .wrapper {{ max-width: 960px; margin: 0 auto; padding: 32px 16px; }}
  .header {{
    border-bottom: 2px solid #e8c97e; padding-bottom: 24px; margin-bottom: 40px; text-align: center;
  }}
  .header h1 {{ color: #e8c97e; font-size: 28px; letter-spacing: 2px; text-transform: uppercase; }}
  .header .subtitle {{ color: #aaa; margin-top: 6px; font-size: 13px; }}
  .header .date {{ color: #e8c97e; margin-top: 8px; font-size: 13px; }}
  .header .accounts {{ margin-top: 12px; color: #ccc; font-size: 13px; }}

  .section-header {{
    display: flex; align-items: baseline; gap: 12px;
    border-left: 4px solid #e8c97e; padding-left: 16px; margin: 40px 0 20px;
  }}
  .section-number {{ color: #e8c97e; font-size: 11px; letter-spacing: 2px; text-transform: uppercase; }}
  .section-header h2 {{ color: #fff; font-size: 20px; }}

  .sub-header {{ color: #e8c97e; font-size: 15px; margin: 24px 0 10px; }}

  .account-card {{
    background: #1a1a1a; border: 1px solid #2a2a2a; border-radius: 8px;
    padding: 24px; margin-bottom: 28px;
  }}
  .account-title {{ color: #fff; font-size: 18px; margin-bottom: 16px; }}
  .handle {{ color: #e8c97e; font-weight: normal; font-size: 14px; }}

  .meta-table {{ width: 100%; border-collapse: collapse; margin-bottom: 20px; }}
  .meta-table td {{ padding: 7px 10px; border-bottom: 1px solid #242424; vertical-align: top; }}
  .meta-label {{ color: #e8c97e; width: 200px; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; }}

  .posts-heading {{ color: #ccc; font-size: 13px; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 12px; }}

  .posts-table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  .posts-table th {{
    background: #242424; color: #e8c97e; text-align: left;
    padding: 8px 10px; font-size: 11px; text-transform: uppercase; letter-spacing: 1px;
  }}
  .posts-table td {{ padding: 8px 10px; border-bottom: 1px solid #222; vertical-align: middle; }}
  .posts-table tr:hover td {{ background: #1f1f1f; }}
  .posts-table .rank {{ color: #e8c97e; font-weight: bold; width: 30px; }}
  .posts-table .thumb {{ width: 130px; }}
  .posts-table .thumb img {{ border-radius: 4px; display: block; max-width: 120px; }}
  .posts-table .caption a {{ color: #7ec8e8; text-decoration: none; }}
  .posts-table .caption a:hover {{ text-decoration: underline; }}
  .posts-table .badge {{
    background: #2a2a2a; color: #e8c97e; padding: 2px 8px;
    border-radius: 12px; font-size: 11px; white-space: nowrap;
  }}
  .posts-table .num {{ color: #fff; text-align: right; white-space: nowrap; }}
  .posts-table .audio {{ color: #aaa; font-size: 12px; }}
  .muted {{ color: #555; }}

  .insight-block {{ margin-bottom: 24px; }}
  .insight-label {{ color: #e8c97e; font-size: 12px; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 8px; }}
  .insight-block p {{ color: #ccc; margin-bottom: 6px; }}

  .footer {{ text-align: center; color: #444; font-size: 12px; margin-top: 60px; padding-top: 24px; border-top: 1px solid #1e1e1e; }}
</style>
</head>
<body>
<div class="wrapper">
  <div class="header">
    <h1>Instagram Trend Report</h1>
    <div class="subtitle">Competitive Analysis &amp; Recommendations</div>
    <div class="date">{_esc(report_date)}</div>
    <div class="accounts"><strong>Accounts Analysed:</strong> {_esc(accounts_analysed)}</div>
  </div>

  {_section_header("1", section1.get("title", "COMPETITIVE LANDSCAPE"))}
  {account_cards}

  {_section_header("2", section2.get("title", "CROSS-ACCOUNT TREND SIGNALS"))}
  {section2_html}

  {_section_header("3", section3.get("title", "STRATEGIC RECOMMENDATIONS"))}
  {section3_html}

  <div class="footer">Generated automatically by Instagram Trend Agent</div>
</div>
</body>
</html>"""


# ── Inline thumbnail handling ────────────────────────────────────────────────

def _collect_thumbnail_urls(report: dict) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    raw_posts_map: dict = report.get("_raw_posts", {})
    for acc in report.get("section1", {}).get("accounts", []):
        username = acc.get("username", "")
        raw_posts = raw_posts_map.get(username, [])
        sources = raw_posts if raw_posts else (acc.get("top_5_posts") or [])
        for p in sources:
            url = p.get("displayUrl") or p.get("display_url")
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
    return urls


def _download_thumbnails(urls: list[str]) -> dict[str, tuple[str, bytes, str]]:
    """Fetch each URL once. Returns {url: (cid, image_bytes, subtype)}.

    Silent skip on failure so a single dead thumbnail doesn't block the email.
    """
    out: dict[str, tuple[str, bytes, str]] = {}
    for i, url in enumerate(urls):
        try:
            resp = requests.get(url, timeout=THUMBNAIL_FETCH_TIMEOUT)
            resp.raise_for_status()
            ctype = resp.headers.get("Content-Type", "image/jpeg")
            subtype = ctype.split("/")[-1].split(";")[0].strip() or "jpeg"
            out[url] = (f"thumb-{i}", resp.content, subtype)
        except Exception as exc:
            logger.warning(f"Thumbnail fetch failed for index {i}: {exc}")
    return out


def send_report(report: dict) -> None:
    thumb_urls = _collect_thumbnail_urls(report)
    logger.info(f"Inlining {len(thumb_urls)} thumbnail(s) for durability")
    fetched = _download_thumbnails(thumb_urls)
    cid_map = {url: data[0] for url, data in fetched.items()}

    html_body = build_html(report, cid_map=cid_map)
    report_date = report.get("report_date", "")
    subject = f"Instagram Trend Report — {report_date}"

    sender = config.GMAIL_SENDER_EMAIL()
    recipients = config.RECIPIENT_EMAILS()
    password = config.GMAIL_APP_PASSWORD()

    # multipart/related wraps the HTML + inline images so they travel together.
    root = MIMEMultipart("related")
    root["Subject"] = subject
    root["From"] = sender
    root["To"] = ", ".join(recipients)

    alt = MIMEMultipart("alternative")
    alt.attach(MIMEText(html_body, "html"))
    root.attach(alt)

    for url, (cid, data, subtype) in fetched.items():
        img = MIMEImage(data, _subtype=subtype)
        img.add_header("Content-ID", f"<{cid}>")
        img.add_header("Content-Disposition", "inline", filename=f"{cid}.{subtype}")
        root.attach(img)

    logger.info(f"Sending report to: {', '.join(recipients)}")
    with IPv4SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT) as server:
        server.ehlo()
        server.starttls()
        server.login(sender, password)
        server.sendmail(sender, recipients, root.as_string())

    logger.info("Report sent successfully.")

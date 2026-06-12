"""Curated market-news collector → quant.news_items (the real "news-driven" layer).

Pattern learned from World Monitor's aggregation architecture (our own implementation —
their code is AGPL, untouched): fetch a small CURATED list of market-relevant RSS feeds
server-side, dedupe by link, prune old rows; the web reads our API (works on Cloudflare
and for mainland users — same relay principle as market_collector).

Honesty rules: headlines verbatim with source attribution + outbound links. No rewriting,
no fabricated summaries. Curation IS the editorial act — sources are official (Fed/SEC/ECB)
or established desks, crypto + macro + equity only.

Runs via quant-news-collector.timer (every 20 min). Env: TIMESCALE_URL.
"""

from __future__ import annotations

import email.utils
import os
import re
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import psycopg2
import requests

FEEDS = [
    # (source, category, url)
    ("CoinDesk", "crypto", "https://www.coindesk.com/arc/outboundfeeds/rss/"),
    ("Cointelegraph", "crypto", "https://cointelegraph.com/rss"),
    ("Decrypt", "crypto", "https://decrypt.co/feed"),
    ("The Block", "crypto", "https://www.theblock.co/rss.xml"),
    ("Bitcoin Magazine", "crypto", "https://bitcoinmagazine.com/.rss/full/"),
    ("Fed", "macro", "https://www.federalreserve.gov/feeds/press_all.xml"),
    ("SEC", "macro", "https://www.sec.gov/news/pressreleases.rss"),
    ("ECB", "macro", "https://www.ecb.europa.eu/rss/press.html"),
    ("MarketWatch", "equity", "https://feeds.content.dowjones.io/public/rss/mw_topstories"),
    ("CNBC", "equity", "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=10001147"),
]
_HDRS = {"User-Agent": "Mozilla/5.0 (quant news collector; +https://quant.panda.qzz.io)"}
KEEP_DAYS = 14
PER_FEED_CAP = 30


def log(m: str) -> None:
    print(f"[{datetime.now(timezone.utc).isoformat(timespec='seconds')}] {m}", flush=True)


def _text(el) -> str:
    return re.sub(r"\s+", " ", (el.text or "").strip()) if el is not None else ""


def parse_feed(xml_text: str) -> list[dict]:
    """RSS 2.0 + Atom tolerant item extraction (title/link/pubDate)."""
    out = []
    try:
        root = ET.fromstring(xml_text.encode() if isinstance(xml_text, str) else xml_text)
    except ET.ParseError:
        # Some feeds ship stray control chars — strip and retry once.
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", xml_text)
        try:
            root = ET.fromstring(cleaned.encode())
        except ET.ParseError:
            return out
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    for item in root.iter("item"):  # RSS 2.0
        title = _text(item.find("title"))
        link = _text(item.find("link"))
        pub = _text(item.find("pubDate"))
        if title and link:
            out.append({"title": title, "link": link, "pub": pub})
    if not out:  # Atom
        for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
            title = _text(entry.find("atom:title", ns))
            le = entry.find("atom:link", ns)
            link = le.get("href", "") if le is not None else ""
            pub = _text(entry.find("atom:updated", ns))
            if title and link:
                out.append({"title": title, "link": link, "pub": pub})
    return out


def parse_date(s: str):
    if not s:
        return None
    try:
        return email.utils.parsedate_to_datetime(s)
    except Exception:
        pass
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def main() -> int:
    dsn = os.environ.get("TIMESCALE_URL", "")
    if not dsn:
        print("TIMESCALE_URL required", file=sys.stderr)
        return 2
    conn = psycopg2.connect(dsn)
    conn.autocommit = True
    total = 0
    for source, category, url in FEEDS:
        try:
            r = requests.get(url, timeout=15, headers=_HDRS)
            r.raise_for_status()
            items = parse_feed(r.text)[:PER_FEED_CAP]
        except Exception as e:
            log(f"{source} fetch failed: {e!r}")
            continue
        n = 0
        with conn.cursor() as cur:
            for it in items:
                pub = parse_date(it["pub"])
                cur.execute(
                    """INSERT INTO quant.news_items (published_at, source, category, title, link)
                       VALUES (%s, %s, %s, %s, %s) ON CONFLICT (link) DO NOTHING""",
                    (pub, source, category, it["title"][:500], it["link"][:1000]),
                )
                n += cur.rowcount
        total += n
        if n:
            log(f"{source}: +{n} new")
    with conn.cursor() as cur:
        cur.execute("DELETE FROM quant.news_items WHERE fetched_at < now() - interval '%s days'" % KEEP_DAYS)
        if cur.rowcount:
            log(f"pruned {cur.rowcount} old rows")
    conn.close()
    log(f"done: {total} new items")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

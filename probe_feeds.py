"""Empirically probe candidate Arsenal RSS feeds.

Hits each URL, reports HTTP status, entry count, and the latest headline so we
can pick real, live sources instead of guessing which URLs exist.
"""

import concurrent.futures
import feedparser
import requests

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 ArsenalTracker/1.0"
)

CANDIDATES = [
    # Arsenal official guesses
    ("Arsenal.com A", "https://www.arsenal.com/arsenal-news-rss"),
    ("Arsenal.com B", "https://www.arsenal.com/rss.xml"),
    ("Arsenal.com C", "https://www.arsenal.com/rss/news"),
    # BBC
    ("BBC Sport", "https://feeds.bbci.co.uk/sport/football/teams/arsenal/rss.xml"),
    # Guardian
    ("Guardian", "https://www.theguardian.com/football/arsenal/rss"),
    # Sky
    ("Sky football", "https://www.skysports.com/rss/12040"),
    ("Sky Arsenal?", "https://www.skysports.com/rss/11095"),
    # Arseblog
    ("Arseblog News", "https://arseblog.news/feed/"),
    ("Arseblog main", "https://arseblog.com/feed/"),
    # CaughtOffside
    ("CaughtOffside tag", "https://www.caughtoffside.com/tag/arsenal/feed/"),
    ("CaughtOffside team", "https://www.caughtoffside.com/team/arsenal/feed/"),
    # football.london
    ("football.london A", "https://www.football.london/arsenal-fc/?service=rss"),
    ("football.london B", "https://www.football.london/all-about/arsenal-fc?service=rss"),
    # 90min
    ("90min", "https://www.90min.com/teams/arsenal/posts.rss"),
    # Daily Cannon
    ("Daily Cannon", "https://dailycannon.com/feed/"),
    # Pain in the Arsenal / FanSided
    ("Pain in the Arsenal", "https://paininthearsenal.com/feed/"),
    # Sport Witness
    ("Sport Witness A", "https://www.sportwitness.co.uk/category/clubs/arsenal/feed/"),
    ("Sport Witness B", "https://www.sportwitness.co.uk/category/arsenal/feed/"),
    # TBR
    ("TBR Football", "https://tbrfootball.com/teams/arsenal-fc/feed/"),
    # Just Arsenal
    ("Just Arsenal", "https://www.justarsenal.com/feed"),
    # HITC
    ("HITC Arsenal", "https://www.hitc.com/en-gb/arsenal/feed/"),
    # Metro
    ("Metro Arsenal", "https://metro.co.uk/tag/arsenal/feed/"),
    # X mirrors (expected flaky/dead)
    ("Romano nitter.net", "https://nitter.net/FabrizioRomano/rss"),
    ("Romano nitter.poast", "https://nitter.poast.org/FabrizioRomano/rss"),
    ("Ornstein nitter.net", "https://nitter.net/David_Ornstein/rss"),
]


def probe(item):
    name, url = item
    try:
        r = requests.get(url, headers={"User-Agent": UA}, timeout=20)
        status = r.status_code
        d = feedparser.parse(r.content)
        n = len(d.entries)
        latest = d.entries[0].title[:70] if n else "(no entries)"
        ftitle = d.feed.get("title", "")[:40] if hasattr(d, "feed") else ""
        return f"{'OK ' if n else 'EMPTY':5} | {name:22} | HTTP {status} | {n:>3} entries | feed='{ftitle}' | latest: {latest}"
    except Exception as e:
        return f"{'FAIL':5} | {name:22} | {type(e).__name__}: {str(e)[:60]}"


with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
    results = list(ex.map(probe, CANDIDATES))

for line in results:
    print(line)

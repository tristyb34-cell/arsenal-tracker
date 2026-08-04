"""Arsenal Tracker configuration: sources, paths, categories, club tagging,
and the transfer-likelihood ladder.

Two pages of output:
  - Arsenal page  : all categories, anything tagged Arsenal.
  - Europe page   : transfers only, for tracked rival/European clubs, grouped by club.

Sources are tiered for resilience and carry a `credibility` weight that feeds the
likelihood ladder (insider sources like Romano/Ornstein boost an item one rung).

Every feed below was empirically verified live via probe_feeds.py.
"""

import os
import re
import shutil

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Absolute path to the claude CLI. launchd (which runs the scraper and the
# Flask app) uses a minimal PATH that does NOT include ~/.local/bin, so a bare
# "claude" call silently fails. Resolve it here so every caller is robust.
CLAUDE_BIN = (
    shutil.which("claude")
    or os.path.expanduser("~/.local/bin/claude")
)
DB_PATH = os.path.join(BASE_DIR, "arsenal.db")
LOG_DIR = os.path.join(BASE_DIR, "logs")

# Flask dashboard
HOST = "127.0.0.1"
PORT = 5057

# Politeness / rate-limit settings
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36 ArsenalTracker/1.0"
)
REQUEST_TIMEOUT = 20
MIN_DELAY = 0.8
MAX_DELAY = 2.2
BACKOFF_AFTER_FAILS = 3
MAX_ENTRIES_PER_SOURCE = 40
RECENCY_DAYS = 21
FUZZY_DEDUPE_DAYS = 3
FUZZY_THRESHOLD = 0.86      # same-source near-identical => true duplicate, drop
# Clustering scores word OVERLAP (not raw string similarity, which never got
# near the old 0.72 and left every item in a cluster of one) on STORY words:
# the player and club names are stripped first, or a whole saga merges into one
# cluster and the feed stamps speculation with the highest rung it ever reached.
CLUSTER_THRESHOLD = 0.50            # when both headlines name the same player
CLUSTER_THRESHOLD_NO_PLAYER = 0.70  # stricter when there's no name to anchor on
CLUSTER_MIN_SHARED = 3              # shared words needed before a score counts
ORBIT_DAYS = 21             # window for "players Arsenal are linked with"
ORBIT_MIN_MENTIONS = 2      # a one-off mention isn't a link
# The scraper runs every 30 min; fixtures and league tables do not move that
# fast and each rebuild makes several ESPN requests, so let the cache ride.
FIXTURES_MAX_AGE_MINUTES = 90

# credibility weights: "insider" > "high" > "medium" > "low"
SOURCES = [
    # --- Arsenal feeds (arsenal_feed=True: auto-tagged Arsenal, all categories) ---
    {"name": "BBC Sport", "url": "https://feeds.bbci.co.uk/sport/football/teams/arsenal/rss.xml", "tier": 1, "arsenal_feed": True, "credibility": "high"},
    {"name": "The Guardian", "url": "https://www.theguardian.com/football/arsenal/rss", "tier": 1, "arsenal_feed": True, "credibility": "high"},
    {"name": "football.london", "url": "https://www.football.london/arsenal-fc/?service=rss", "tier": 1, "arsenal_feed": True, "credibility": "high"},
    {"name": "Arseblog News", "url": "https://arseblog.news/feed/", "tier": 1, "arsenal_feed": True, "credibility": "high"},
    {"name": "Caught Offside", "url": "https://www.caughtoffside.com/tag/arsenal/feed/", "tier": 1, "arsenal_feed": True, "credibility": "medium"},
    {"name": "Daily Cannon", "url": "https://dailycannon.com/feed/", "tier": 1, "arsenal_feed": True, "credibility": "medium"},
    {"name": "Sport Witness", "url": "https://www.sportwitness.co.uk/category/clubs/arsenal/feed/", "tier": 2, "arsenal_feed": True, "credibility": "medium"},
    {"name": "Pain in the Arsenal", "url": "https://paininthearsenal.com/feed/", "tier": 2, "arsenal_feed": True, "credibility": "low"},
    {"name": "Just Arsenal", "url": "https://www.justarsenal.com/feed", "tier": 2, "arsenal_feed": True, "credibility": "low"},

    # --- Broad transfer feeds (arsenal_feed=False: club-tagged, transfers routed to Europe page) ---
    {"name": "BBC Gossip", "url": "https://feeds.bbci.co.uk/sport/football/gossip/rss.xml", "tier": 1, "arsenal_feed": False, "credibility": "high"},
    {"name": "Guardian Transfers", "url": "https://www.theguardian.com/football/transfer-window/rss", "tier": 1, "arsenal_feed": False, "credibility": "high"},
    {"name": "Sky Transfer Centre", "url": "https://www.skysports.com/rss/12691", "tier": 1, "arsenal_feed": False, "credibility": "high"},
    {"name": "Football Italia", "url": "https://www.football-italia.net/feed", "tier": 2, "arsenal_feed": False, "credibility": "medium"},

    # --- Direct X insiders (best-effort mirror feeds; feed BOTH pages) ---
    {"name": "Fabrizio Romano (X)", "url": "https://nitter.net/FabrizioRomano/rss", "tier": 3, "arsenal_feed": False, "credibility": "insider"},
    {"name": "David Ornstein (X)", "url": "https://nitter.net/David_Ornstein/rss", "tier": 3, "arsenal_feed": False, "credibility": "insider"},
]

INSIDER_SOURCES = {s["name"] for s in SOURCES if s["credibility"] == "insider"}

# --- Club tagging -----------------------------------------------------------
# Arsenal includes squad names (we want everything about our players).
# Rival/European clubs use club names + nicknames only, avoiding ambiguous bare
# words ("milan", "madrid", "city", "united") that would cross-tag.
#
# Split into STRONG (the club itself, unmistakable) and SQUAD (our players).
# Bare surnames that are ordinary English words or common names elsewhere
# ("white", "rice", "timber", "jesus", "gabriel") used to be in this list and
# tagged junk as Arsenal: "Jesus Navas retires", "Timber merchant strikes gold",
# "Chelsea eye Forest star White". Those now require the full name.
ARSENAL_STRONG_TERMS = [
    "arsenal", "gunners", "gooner", "arteta", "emirates stadium", "london colney",
]
ARSENAL_SQUAD_TERMS = [
    # unambiguous single names
    "saka", "odegaard", "ødegaard", "saliba", "martinelli", "havertz", "raya",
    "zinchenko", "jorginho", "partey", "trossard", "nwaneri", "lewis-skelly",
    "merino", "calafiori", "kiwior", "tomiyasu", "gyokeres", "gyökeres",
    "madueke", "magalhaes", "magalhães",
    # ambiguous surnames: full name required
    "ben white", "declan rice", "jurrien timber", "jurriën timber",
    "gabriel jesus", "gabriel magalhaes", "gabriel magalhães", "gabriel martinelli",
    "kai havertz", "william saliba", "bukayo saka", "martin odegaard",
    "martin ødegaard", "david raya", "riccardo calafiori", "mikel merino",
    "myles lewis-skelly", "ethan nwaneri", "viktor gyokeres", "viktor gyökeres",
    "noni madueke", "leandro trossard", "thomas partey", "takehiro tomiyasu",
    "jakub kiwior", "oleksandr zinchenko",
]
ARSENAL_TERMS = ARSENAL_STRONG_TERMS + ARSENAL_SQUAD_TERMS

# Real crest logos (ESPN CDN, public PNGs). Monogram badge is the fallback.
_CREST_IDS = {
    "Arsenal": 359, "Man City": 382, "Man Utd": 360, "Liverpool": 364,
    "Chelsea": 363, "Tottenham": 367, "Aston Villa": 362, "Newcastle": 361,
    "Everton": 368, "Barcelona": 83, "Real Madrid": 86, "Atlético Madrid": 1068,
    "Dortmund": 124, "Bayern Munich": 132, "Juventus": 111, "Inter": 110,
    "AC Milan": 103, "PSG": 160, "Napoli": 114,
}
CLUB_CRESTS = {
    name: f"https://a.espncdn.com/i/teamlogos/soccer/500/{tid}.png"
    for name, tid in _CREST_IDS.items()
}

# Short codes for crest badges (disambiguates Man City vs Man Utd etc.)
CLUB_CODES = {
    "Arsenal": "ARS", "Man City": "MCI", "Man Utd": "MUN", "Liverpool": "LIV",
    "Chelsea": "CHE", "Tottenham": "TOT", "Aston Villa": "AVL", "Newcastle": "NEW",
    "Everton": "EVE", "Barcelona": "BAR", "Real Madrid": "RMA",
    "Atlético Madrid": "ATM", "Dortmund": "BVB", "Bayern Munich": "BAY",
    "Juventus": "JUV", "Inter": "INT", "AC Milan": "MIL", "PSG": "PSG", "Napoli": "NAP",
}

# Display order on the Europe page.
EUROPE_CLUBS_ORDER = [
    "Man City", "Man Utd", "Liverpool", "Chelsea", "Tottenham",
    "Aston Villa", "Newcastle", "Everton",
    "Barcelona", "Real Madrid", "Atlético Madrid", "Dortmund", "Bayern Munich",
    "Juventus", "Inter", "AC Milan", "PSG", "Napoli",
]

CLUB_TERMS = {
    "Arsenal": ARSENAL_TERMS,
    # Premier League
    "Man City": ["man city", "manchester city", "pep guardiola", "etihad"],
    "Man Utd": ["man utd", "man united", "manchester united", "old trafford", "ruben amorim"],
    "Liverpool": ["liverpool", "anfield"],
    "Chelsea": ["chelsea", "stamford bridge"],
    "Tottenham": ["tottenham", "spurs", "hotspur"],
    "Aston Villa": ["aston villa", "villa park"],
    "Newcastle": ["newcastle", "magpies", "st james' park", "st james park"],
    "Everton": ["everton", "toffees", "goodison"],
    # Europe
    "Barcelona": ["barcelona", "barca", "barça", "camp nou", "nou camp"],
    "Real Madrid": ["real madrid", "bernabeu", "bernabéu", "los blancos"],
    "Atlético Madrid": ["atletico", "atlético", "atleti", "atletico madrid", "atlético madrid"],
    "Dortmund": ["dortmund", "borussia dortmund"],
    "Bayern Munich": ["bayern", "bayern munich", "bayern münchen"],
    "Juventus": ["juventus", "juve"],
    "Inter": ["inter milan", "inter", "nerazzurri"],
    "AC Milan": ["ac milan", "rossoneri"],
    "PSG": ["psg", "paris saint-germain", "paris saint germain", "paris st-germain"],
    "Napoli": ["napoli"],
}

# Precompile whole-word/phrase matchers (word boundaries avoid cross-tagging).
_CLUB_PATTERNS = {
    club: [re.compile(r"(?<!\w)" + re.escape(t) + r"(?!\w)", re.I) for t in terms]
    for club, terms in CLUB_TERMS.items()
}


def tag_clubs(text: str):
    """Return the list of tracked clubs mentioned in the text."""
    t = text or ""
    found = []
    for club, patterns in _CLUB_PATTERNS.items():
        if any(p.search(t) for p in patterns):
            found.append(club)
    return found


def is_arsenal_relevant(text: str) -> bool:
    return "Arsenal" in tag_clubs(text)


# Signal strength of an Arsenal mention, used to decide what earns the Arsenal
# tab. "strong" = the club is named. "squad" = one of our players is named.
_ARSENAL_STRONG_PATTERNS = [
    re.compile(r"(?<!\w)" + re.escape(t) + r"(?!\w)", re.I) for t in ARSENAL_STRONG_TERMS
]
_ARSENAL_SQUAD_PATTERNS = [
    re.compile(r"(?<!\w)" + re.escape(t) + r"(?!\w)", re.I) for t in ARSENAL_SQUAD_TERMS
]


# CLUB_TERMS only covers the 19 clubs we display, so a headline about an
# untracked club ("Fenerbahce ready huge Rashford offer") looked club-less and
# slipped onto the Arsenal tab via the orbit. This wider list is a veto only:
# it decides "this is someone else's story", never display or grouping.
OTHER_CLUB_TERMS = [
    "fenerbahce", "galatasaray", "besiktas", "porto", "benfica", "sporting",
    "leipzig", "leverkusen", "stuttgart", "frankfurt", "wolfsburg", "monchengladbach",
    "ajax", "psv", "feyenoord", "brugge", "anderlecht", "celtic", "rangers",
    "marseille", "lyon", "monaco", "lille", "rennes", "nice",
    "roma", "lazio", "atalanta", "fiorentina", "bologna", "torino", "udinese",
    "sevilla", "villarreal", "betis", "valencia", "athletic club", "real sociedad",
    "girona", "celta vigo", "getafe", "osasuna",
    "nottingham forest", "crystal palace", "brighton", "brentford", "fulham",
    "wolves", "west ham", "leeds", "burnley", "sunderland", "bournemouth",
    "leicester", "southampton", "ipswich", "sheffield united", "norwich",
    "al-nassr", "al nassr", "al-hilal", "al hilal", "al-ittihad", "al ittihad",
    "inter miami", "galaxy",
]
_OTHER_CLUB_PATTERNS = [
    re.compile(r"(?<!\w)" + re.escape(t) + r"(?!\w)", re.I) for t in OTHER_CLUB_TERMS
]


def names_other_club(text: str) -> bool:
    """True if the headline names a club that isn't Arsenal (tracked or not)."""
    t = text or ""
    if any(p.search(t) for p in _OTHER_CLUB_PATTERNS):
        return True
    return any(c != "Arsenal" for c in tag_clubs(t))


def arsenal_signal(text: str) -> str | None:
    """Return 'strong' (club named), 'squad' (our player named) or None."""
    t = text or ""
    if any(p.search(t) for p in _ARSENAL_STRONG_PATTERNS):
        return "strong"
    if any(p.search(t) for p in _ARSENAL_SQUAD_PATTERNS):
        return "squad"
    return None


# --- Women's football: excluded entirely (Tristan tracks the men's team) -----
# Headlines often never say "women", so club/competition names do the work.
WOMENS_CLUB_TERMS = [
    "nwsl", "wsl", "women's super league", "womens super league",
    "bay fc", "san diego wave", "angel city", "gotham fc", "orlando pride",
    "kansas city current", "chicago red stars", "houston dash", "portland thorns",
    "racing louisville", "utah royals", "washington spirit", "seattle reign",
    "north carolina courage", "boston legacy",
]
# Arsenal Women squad + recent departures (unambiguous names only).
WOMENS_PLAYER_TERMS = [
    "nighswonger", "harbert", "foord", "blackstenius", "mead", "russo",
    "williamson", "catley", "maanum", "mccabe", "wubben-moy", "codina",
    "cooney-cross", "hurtig", "zinsberger", "ilestedt", "caldentey", "pelova",
    "kyra cooney", "beth mead", "alessia russo", "leah williamson", "steph catley",
    "kim little", "lotte wubben", "stina blackstenius", "frida maanum",
    "katie mccabe", "mariona caldentey", "emily fox", "manuela zinsberger",
]
_WOMENS_PATTERNS = [
    re.compile(r"(?<!\w)" + re.escape(t) + r"(?!\w)", re.I)
    for t in WOMENS_CLUB_TERMS + WOMENS_PLAYER_TERMS
]


# --- Categories -------------------------------------------------------------
CATEGORIES = {
    "Transfers": [
        "transfer", "signing", "sign", "signs", "signed", "deal", "bid", "fee",
        "medical", "here we go", "contract", "loan", "release clause", "target",
        "linked", "swoop", "agreement", "personal terms", "agent", "wages",
        "extension", "renew", "new deal", "move to", "joins", "join", "exit",
        "sold", "buy", "snap up", "chase", "pursuit", "£", "€", "transfer window",
        "approach", "move for", "moves for", "swap deal", "release clause",
        "free agent", "price tag", "valuation", "suitors", "hijack",
        "transfer request", "bidding war", "wantaway",
    ],
    "Injuries": [
        "injury", "injured", "injuries", "fitness", "sidelined", "knock",
        "hamstring", "groin", "ankle", "knee", "calf", "surgery", "operation",
        "ruled out", "doubt", "doubtful", "suspended", "suspension", "ban",
        "banned", "layoff", "recovery", "recover", "scan", "setback",
        "return", "returns", "fit again", "out for", "treatment table",
    ],
    "Match & Results": [
        "vs", "win", "wins", "won", "draw", "drew", "loss", "lose", "lost",
        "defeat", "beat", "beaten", "goal", "goals", "lineup", "line-up",
        "starting xi", "full-time", "half-time", "kick-off", "kickoff", "fixture",
        "preview", "report", "match", "clash", "ratings", "highlights",
        "premier league", "champions league", "fa cup", "carabao", "europa",
        "penalty", "red card", "var", "thrashing",
    ],
}

CATEGORY_ORDER = ["Transfers", "Injuries", "Match & Results", "General"]
DEFAULT_CATEGORY = "General"

# Matched on word boundaries. Plain substring matching scored "Salah close to
# Trabzonspor move" as Match & Results because "close" contains "lose", which
# kept real transfer news off the Europe tab.
# Currency symbols are not word characters, so a trailing (?!\w) would never
# match "£70m". They are matched bare.
def _category_pattern(kw):
    if kw in ("£", "€"):
        return re.compile(re.escape(kw))
    return re.compile(r"(?<!\w)" + re.escape(kw) + r"(?!\w)", re.I)


CATEGORY_PATTERNS = {
    cat: [_category_pattern(kw) for kw in kws] for cat, kws in CATEGORIES.items()
}

# --- freshness: different content types have different shelf lives ----------
# Match previews/lineups go stale within hours; transfer rumours last weeks.
CATEGORY_MAX_AGE_DAYS = {
    "Match & Results": 3, "Injuries": 14, "Transfers": 21, "General": 10,
}
PERISHABLE_MAX_HOURS = 12   # lineups/previews die within hours of kickoff

# Headlines tied to a specific match/event, useless once it's played.
PERISHABLE_HINTS = [
    "expected to start", "predicted line", "predicted xi", "predicted team",
    "predicted starting", "starting xi", "starting line", "line-up", "lineup",
    "team news", "could line up", "how arsenal could", "confirmed xi",
    "confirmed team", "confirmed line", "vs ", "preview", "kick-off", "kick off",
    "tonight", "live:", "live updates", "minute-by-minute", "minute by minute",
    "player ratings", "full-time", "half-time", "build-up", "build up",
    "how to watch", "tv channel", "what time", "team to face",
]


def is_perishable(text: str) -> bool:
    t = (text or "").lower()
    return any(h in t for h in PERISHABLE_HINTS)

# --- Likelihood ladder ------------------------------------------------------
# Low -> high. An item's rung is the HIGHEST tier whose keywords appear.
# Insider sources boost one rung (capped at Advanced unless the language itself
# already says "Here we go").
LIKELIHOOD_RUNGS = ["Rumour", "Developing", "Advanced", "Here we go"]

# Real headlines interleave words ("agree £150k deal"), inflect verbs ("complete"
# vs "completed") and wrap claims in quotes ('deal "done"'). The old engine did
# exact substring matching on rigid phrases, so nearly everything fell through to
# the Rumour default (62% of items). These are word-boundary regexes with slack
# for intervening words, run against normalised (accent- and punctuation-free)
# text: _norm() turns 'Guimaraes deal "done"' into 'guimaraes deal done'.
_ACCENTS = str.maketrans(
    "àáâãäåèéêëìíîïòóôõöùúûüýÿñçšžğı", "aaaaaaeeeeiiiiooooouuuuyyncszgi"
)


def _norm(text: str) -> str:
    t = (text or "").lower().translate(_ACCENTS)
    t = re.sub(r"[^a-z0-9£€\s]+", " ", t)      # drop quotes/dashes/punctuation
    return re.sub(r"\s+", " ", t).strip()


# GAP allows up to 3 filler words between the halves of a phrase, which is what
# lets "agree deal" also match "agree £150k deal for Nighswonger". The token
# class has to include currency symbols or the gap can't step over "£150k".
GAP = r"(?:\s+[\w£€]+){0,3}\s+"
# Wider gap for bid/offer phrasing, which routinely carries a club name and a
# fee between the verb and the noun: "reject Manchester City's £122m bid".
GAP4 = r"(?:\s+[\w£€]+){0,4}\s+"
MONEY = r"(?:£|€)[\d.,]+\s*(?:m|k|bn|million)?"

LIKELIHOOD_PATTERNS = {
    # The deal is done, announced, or being announced.
    "Here we go": [
        r"\bhere we go\b",
        r"\bdone deal\b",
        r"\bdeal(?:\s+is)?\s+done\b",
        r"\bcomplet\w+" + GAP + r"(?:signing|move|transfer|deal|switch|capture)\b",
        r"\b(?:signing|move|transfer|deal)" + GAP + r"complet\w+",
        r"\bofficial\w*" + GAP + r"(?:sign\w*|join\w*|complet\w+|announc\w+|unveil\w+)",
        r"\b(?:sign\w*|join\w*|complet\w+|announc\w+|unveil\w+)" + GAP + r"official\w*",
        r"\bunveil\w+",
        r"\bmedical\b" + GAP + r"complet\w+",
        r"\bcomplet\w+" + GAP + r"medical\b",
        r"\bpassed" + GAP + r"medical\b",
        r"\b(?:confirm\w*|announc\w+)" + GAP + r"(?:signing|arrival|capture|deal|transfer)\b",
        r"\bseal\w+" + GAP + r"(?:deal|move|transfer|switch|signing)\b",
        r"\b(?:has|have|had)\s+(?:now\s+)?(?:signed|joined)\b",
        r"\bsigns?\s+for\b",
        r"\bnew signing\b",
        r"\bwelcome\w*" + GAP + r"(?:signing|arrival)\b",
    ],
    # Concrete, verifiable progress: money on the table or terms settled.
    "Advanced": [
        r"\bagree\w*" + GAP + r"(?:deal|fee|terms|move|transfer|contract|price|switch)\b",
        r"\b(?:deal|fee|terms|move|transfer|contract|price)" + GAP + r"agree\w+",
        r"\bpersonal terms\b",
        r"\bmedical\b",
        r"\b(?:agreement|accord)\s+reached\b",
        r"\breach\w*" + GAP + r"agreement\b",
        r"\bverbal agreement\b",
        # A bid is only concrete once someone acts on it. "bidding war" and
        # "plan a bid" are not bids, so \bbids?\b never matches "bidding".
        r"\b(?:accept\w*|submit\w*|lodge\w*|tabl\w+|launch\w*|reject\w*|sends?|sent"
        r"|makes?|made|plac\w+|increas\w+|improv\w+|receiv\w+|turn\w*\s+down)"
        + GAP4 + r"\b(?:bids?|offers?|proposals?)\b",
        r"\b(?:bids?|offers?|proposals?)\b" + GAP4
        + r"(?:accept\w+|submitt?\w*|lodged|tabled|rejected|received|in hand)",
        r"\bbids?\s+(?:now\s+)?in\b",
        r"\b(?:bids?|offers?)\s+for\b",
        # Money attached to a bid means a real offer exists. No \b before MONEY:
        # £ is not a word character, so \b never matches in front of it.
        MONEY + GAP4 + r"\b(?:bids?|offers?)\b",
        r"\b(?:bids?|offers?)\b" + GAP4 + MONEY,
        r"\bon the verge\b",
        r"\bclose to" + GAP + r"(?:deal|signing|agreement|move|sign\w*|complet\w+)",
        r"\badvanced\s+(?:talks|negotiations|stage|discussions)\b",
        r"\bset to\s+(?:sign|join|complete|seal|move|become)\b",
        r"\bgreen light\b",
        r"\brelease clause" + GAP + r"(?:triggered|paid|activated|met)\b",
        r"\bonly\b" + GAP + r"(?:medical|paperwork|formalit\w+)",
        r"\bawait\w*" + GAP + r"(?:medical|paperwork|announcement)\b",
    ],
    # Real engagement, no money agreed yet.
    "Developing": [
        r"\btalks\b",
        r"\bnegotiat\w+",
        r"\bdiscussion\w*\b",
        r"\b(?:contact\w*|approach\w*|enquir\w+|inquir\w+)\b",
        r"\bshortlist\w*",
        r"\bstep(?:ped|ping)?\s+up\b",
        r"\b(?:prepar\w+|plan\w*|plott\w+|weigh\w+|ready)" + GAP + r"(?:bids?|offers?|move|approach)\b",
        r"\b(?:interested|interest)\b" + GAP + r"(?:sign\w*|deal|move|transfer)\b",
        r"\binterested in\b",
        r"\binterest in\b",
        r"\bkeen to sign\b",
        r"\bpriority target\b",
        r"\bmeet\w*" + GAP + r"(?:agent|representative\w*|entourage)\b",
        r"\bconsidering\b",
        r"\bweigh\w+\s+(?:up\s+)?(?:a\s+)?(?:bid|offer|move)\b",
    ],
    # Explicit speculation. Also the fallback when nothing above matches.
    "Rumour": [
        r"\blink\w+\b", r"\bkeen\b", r"\beye\w*\b", r"\bmonitor\w*\b",
        r"\bcould\b", r"\brumou?r\w*\b", r"\bspeculat\w+", r"\breportedly\b",
        r"\bwant\w*\b", r"\btarget\w*\b", r"\bweigh\w+\b", r"\bmull\w+\b",
        r"\btrack\w+\b", r"\blining up\b", r"\bset sights\b", r"\bswoop\b",
    ],
}

_LIKELIHOOD_RES = {
    rung: [re.compile(p) for p in pats] for rung, pats in LIKELIHOOD_PATTERNS.items()
}

# Speculation/future markers: if a "Here we go" phrase co-occurs with one of
# these, the deal is being framed as not-yet-done, so cap it at Advanced.
FUTURE_MARKER_RES = [
    re.compile(p) for p in [
        r"\bcould\b", r"\bset to\b", r"\bexpected to\b", r"\bpoised to\b",
        r"\bon the verge\b", r"\bnearing\b", r"\bclosing in\b", r"\bedging closer\b",
        r"\breportedly\b", r"\blink\w+\b", r"\bkeen to\b", r"\bwants? to\b",
        r"\beye\w*\b", r"\bplan\w*\s+to\b", r"\bhop\w+\s+to\b", r"\bin talks\b",
        r"\bwould\b", r"\bmight\b", r"\bmay\b", r"\brumou?r\w*\b",
        r"\bclose to\b", r"\bafter agreeing\b", r"\bdelay\w*\b", r"\bpending\b",
        r"\bwait\w*\s+(?:on|for)\b",
        # An infinitive is intent, not completion: "given priority to complete
        # big signing", "ready to help Berta complete £60m transfer". Only
        # "to complete" though: "agree deal to sign X, here we go" is done, and
        # blanket-blocking "to sign" demoted every Romano announcement.
        r"\bto\s+complete\b",
        r"\bnear\w+\b", r"\bready to\b", r"\bpriority\b", r"\bhelp\w*\b",
        r"\bbeaten to\b", r"\bmiss(?:ed|es)? out\b",
        # hedges and statements of intent are not confirmations
        r"\bintention\w*\b", r"\bintent\b", r"\bstance\b", r"\bseemingly\b",
        r"\bhints?\b", r"\bsuggests?\b", r"\bappears?\b",
    ]
]

# Romano's sign-off. When a headline literally says "here we go" the deal is
# announced, so the speculation guard must not second-guess it.
_HERE_WE_GO_RE = re.compile(r"\bhere we go\b")

# A bid that is only being planned is engagement, not an offer on the table.
_PLANNED_BID_RE = re.compile(
    r"\b(?:plan\w*|prepar\w+|weigh\w+|consider\w*|ready|eye\w*|mull\w+|plott\w+)\b"
    + GAP + r"\b(?:bids?|offers?)\b"
)

# A question is never a done deal: "Could X really be heading to Arsenal?"
_QUESTION_RE = re.compile(r"\?\s*$")


def assess_likelihood(text: str, credibility: str):
    """Return (rung_label, by) for a transfer item. Pass the TITLE only (summaries
    add noise). Defaults to 'Rumour' when no concrete signal is present."""
    raw = text or ""
    t = _norm(raw)
    label = "Rumour"
    for rung in reversed(LIKELIHOOD_RUNGS):       # strongest rung first
        if any(p.search(t) for p in _LIKELIHOOD_RES[rung]):
            label = rung
            break

    by = "rules"
    # speculation guard: a "done" claim wrapped in future language isn't done,
    # unless the headline literally says "here we go"
    if label == "Here we go" and not _HERE_WE_GO_RE.search(t) and (
        any(p.search(t) for p in FUTURE_MARKER_RES) or _QUESTION_RE.search(raw)
    ):
        label = "Advanced"
        by = "rules-guarded"

    # a planned bid is Developing, not Advanced, unless something firmer (terms
    # agreed, a medical, money on the table) is also present
    if label == "Advanced" and _PLANNED_BID_RE.search(t):
        firm = [p for p in _LIKELIHOOD_RES["Advanced"]
                if p.search(t) and "bid" not in p.pattern]
        if not firm:
            label = "Developing"
            by = "rules-guarded"

    if credibility == "insider" and label != "Here we go":
        idx = LIKELIHOOD_RUNGS.index(label)
        boosted = min(idx + 1, LIKELIHOOD_RUNGS.index("Advanced"))
        if boosted != idx:
            label = LIKELIHOOD_RUNGS[boosted]
            by = "rules+insider"
    return label, by


# --- heat-board filtering: men's first-team incoming focus -----------------
WOMENS_HINTS = ["women", "wsl", "lioness", "afc women", "awfc", " female",
                "ladies", "girls' team"]
DEPARTURE_HINTS = [
    "leave", "leaves", "leaving", "exit", "exits", "departure", "depart",
    "sold", "sells", "offload", "loaned out", "loan out", "released",
    "wants out", "wants to leave", "up for sale", "move away", "quit",
]
INCOMING_HINTS = [
    "sign", "signing", "join", "target", "bid", "interest", "move for",
    "swoop", "capture", "land", "close on", "linked with", "pursuit", "chase",
    "want to sign", "eye", "deal for", "transfer for",
]


def mentions_arsenal(text: str) -> bool:
    """True if the headline is explicitly about Arsenal (used to keep the
    Arsenal-tab widgets Arsenal-only, since Arsenal feeds also discuss rivals)."""
    t = (text or "").lower()
    return "arsenal" in t or "gunners" in t or "gooner" in t


def is_womens(text: str) -> bool:
    """True for women's football. Checked on title + summary and used to DROP
    items at ingest, not just hide them: Tristan tracks the men's team only."""
    t = (text or "").lower()
    if any(h in t for h in WOMENS_HINTS):
        return True
    return any(p.search(text or "") for p in _WOMENS_PATTERNS)


def is_pure_departure(text: str) -> bool:
    """True if the story is about a player leaving with no incoming framing."""
    t = (text or "").lower()
    has_dep = any(h in t for h in DEPARTURE_HINTS)
    has_in = any(h in t for h in INCOMING_HINTS)
    return has_dep and not has_in


def is_rival_inbound(text: str) -> bool:
    """True if a RIVAL club is the buyer and Arsenal isn't named (so it's not an
    Arsenal target). Catches ex-Arsenal players joining other clubs."""
    t = (text or "").lower()
    if "arsenal" in t or "gunners" in t:
        return False
    rivals = [c for c in tag_clubs(text) if c != "Arsenal"]
    has_in = any(h in t for h in INCOMING_HINTS)
    return bool(rivals) and has_in


def exclude_from_arsenal_heat(text: str) -> bool:
    return is_womens(text) or is_pure_departure(text) or is_rival_inbound(text)


# --- Player name canonicalisation -------------------------------------------
# The extractor returns whatever the headline used, so "Vinicius Jr" (46 items)
# and "Vinicius Junior" (81) were two different players to the heat board and
# the saga pages. Canonicalise on write so one player is one row.
_PLAYER_SUFFIXES = {"jr": "junior", "jnr": "junior", "junior": "junior",
                    "sr": "senior", "snr": "senior"}

# Known aliases -> canonical full name. Keys are compared after normalising.
PLAYER_ALIASES = {
    "vinicius": "Vinicius Junior",
    "vinicius jr": "Vinicius Junior",
    "vinicius junior": "Vinicius Junior",
    "vini jr": "Vinicius Junior",
    "vini junior": "Vinicius Junior",
    "bruno guimaraes": "Bruno Guimaraes",
    "guimaraes": "Bruno Guimaraes",
    "gyokeres": "Viktor Gyokeres",
    "viktor gyokeres": "Viktor Gyokeres",
    "saka": "Bukayo Saka",
    "bukayo saka": "Bukayo Saka",
    "odegaard": "Martin Odegaard",
    "martin odegaard": "Martin Odegaard",
    "saliba": "William Saliba",
    "william saliba": "William Saliba",
    "rice": "Declan Rice",
    "declan rice": "Declan Rice",
    "martinelli": "Gabriel Martinelli",
    "gabriel martinelli": "Gabriel Martinelli",
    "havertz": "Kai Havertz",
    "kai havertz": "Kai Havertz",
    "lewis skelly": "Myles Lewis-Skelly",
    "myles lewis skelly": "Myles Lewis-Skelly",
    "nwaneri": "Ethan Nwaneri",
    "ethan nwaneri": "Ethan Nwaneri",
    "kolo muani": "Randal Kolo Muani",
    "randal kolo muani": "Randal Kolo Muani",
    "rodri": "Rodri",
    "trossard": "Leandro Trossard",
    "calafiori": "Riccardo Calafiori",
    "madueke": "Noni Madueke",
    "merino": "Mikel Merino",
    "zubimendi": "Martin Zubimendi",
    "martin zubimendi": "Martin Zubimendi",
    "eze": "Eberechi Eze",
    "eberechi eze": "Eberechi Eze",
    "sesko": "Benjamin Sesko",
    "benjamin sesko": "Benjamin Sesko",
}


def canonical_player(name: str) -> str:
    """Normalise an extracted player name so one player is one key.

    Folds accents and case for matching, expands Jr/Jnr to Junior, then applies
    the alias map. Returns a display-cased name (the alias map wins when it has
    an entry, so accents stay consistent across sources)."""
    raw = (name or "").strip()
    if not raw:
        return ""
    key = _norm(raw)                       # lowercase, accent- and punctuation-free
    parts = key.split()
    if parts and parts[-1] in _PLAYER_SUFFIXES:
        parts[-1] = _PLAYER_SUFFIXES[parts[-1]]
        key = " ".join(parts)
    if key in PLAYER_ALIASES:
        return PLAYER_ALIASES[key]
    # no alias: title-case the folded key so "vinicius junior" -> "Vinicius Junior"
    return " ".join(w.capitalize() for w in key.split())

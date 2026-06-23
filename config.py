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
CLUSTER_THRESHOLD = 0.72    # cross-source same story => link into one cluster

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
# Arsenal includes squad surnames (we want everything about our players).
# Rival/European clubs use club names + nicknames only, avoiding ambiguous bare
# words ("milan", "madrid", "city", "united") that would cross-tag.
ARSENAL_TERMS = [
    "arsenal", "gunners", "arteta", "emirates", "gooner",
    "saka", "odegaard", "ødegaard", "saliba", "rice", "gabriel", "martinelli",
    "havertz", "jesus", "white", "timber", "raya", "zinchenko", "jorginho",
    "partey", "trossard", "nwaneri", "lewis-skelly", "merino", "calafiori",
    "kiwior", "tomiyasu", "gyokeres", "gyökeres", "madueke",
]

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


# --- Categories -------------------------------------------------------------
CATEGORIES = {
    "Transfers": [
        "transfer", "signing", "sign", "signs", "signed", "deal", "bid", "fee",
        "medical", "here we go", "contract", "loan", "release clause", "target",
        "linked", "swoop", "agreement", "personal terms", "agent", "wages",
        "extension", "renew", "new deal", "move to", "joins", "join", "exit",
        "sold", "buy", "snap up", "chase", "pursuit", "£", "€", "transfer window",
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

LIKELIHOOD_KEYWORDS = {
    # specific, unambiguous "done" phrases only (bare 'signs'/'confirm'/'official'
    # caused false positives, so they were removed in favour of phrases)
    "Here we go": [
        "here we go", "done deal", "completed signing", "completed the signing",
        "completes signing", "completes move", "completed a move",
        "officially signed", "officially completed", "officially joins",
        "official signing", "unveiled", "medical complete", "completed medical",
        "has signed for", "have signed", "signs for", "sealed the",
        "confirm signing", "confirmed signing", "confirm the signing",
        "announce signing", "announced signing", "announce the signing",
        "new signing confirmed", "deal is done", "deal done",
    ],
    "Advanced": [
        "bid", "fee agreed", "agreed a fee", "personal terms", "medical",
        "agreement reached", "reached an agreement", "verbal agreement",
        "set to sign", "close to signing", "close to a deal", "on the verge",
        "advanced talks", "accepted", "accept a bid", "submit", "submitted",
        "green light", "agree deal", "agreed deal",
    ],
    "Developing": [
        "in talks", "make contact", "made contact", "interested", "interest in",
        "enquiry", "enquire", "approach", "considering", "negotiat",
        "hold talks", "open talks", "discussions", "shortlist", "keen to sign",
        "keen on a move", "in advanced", "step up",
    ],
    "Rumour": [
        "linked", "keen", "eyeing", "eye", "monitoring", "monitor", "could",
        "rumour", "rumor", "speculation", "reportedly", "wants", "targeting",
        "weighing", "mulling", "tracking", "interested in a move", "lining up",
    ],
}


# Speculation/future markers: if a "Here we go" phrase co-occurs with one of
# these, the deal is being framed as not-yet-done, so cap it at Advanced.
FUTURE_MARKERS = [
    "could", "set to", "expected to", "poised to", "on the verge", "nearing",
    "closing in", "edging closer", "reportedly", "linked", "keen to", "wants to",
    "eyeing", "plan to", "planning to", "hoping to", "hope to", "in talks",
    "would ", "might ", "may ", "rumour", "rumor", "in advanced", "close to",
]


def assess_likelihood(text: str, credibility: str):
    """Return (rung_label, by) for a transfer item. Pass the TITLE only (summaries
    add noise). Defaults to 'Rumour' when no concrete signal is present."""
    t = (text or "").lower()
    label = "Rumour"
    for rung in reversed(LIKELIHOOD_RUNGS):       # strongest rung first
        if any(kw in t for kw in LIKELIHOOD_KEYWORDS[rung]):
            label = rung
            break

    by = "rules"
    # speculation guard: a "done" claim wrapped in future language isn't done
    if label == "Here we go" and any(m in t for m in FUTURE_MARKERS):
        label = "Advanced"
        by = "rules-guarded"

    if credibility == "insider" and label != "Here we go":
        idx = LIKELIHOOD_RUNGS.index(label)
        boosted = min(idx + 1, LIKELIHOOD_RUNGS.index("Advanced"))
        if boosted != idx:
            label = LIKELIHOOD_RUNGS[boosted]
            by = "rules+insider"
    return label, by


# --- heat-board filtering: men's first-team incoming focus -----------------
WOMENS_HINTS = ["women", "wsl", "lioness", "afc women", "awfc", " female"]
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
    t = (text or "").lower()
    return any(h in t for h in WOMENS_HINTS)


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

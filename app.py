"""Arsenal Tracker dashboard (Flask) - Broadcast Dark.

Pages:
  /              Arsenal command centre (clustered feed + hero + rail widgets)
  /europe        Europe transfer desk (crest wall, grouped by club)
  /saga/<player> Transfer saga timeline for a player
  PWA: /manifest.webmanifest, /sw.js
"""

import json
import subprocess
import sys
from datetime import datetime, timezone

from flask import Flask, Response, redirect, render_template, request, send_from_directory, url_for

import brief
import config
import db
import fixtures

app = Flask(__name__)

LIKELIHOOD_RANK = {r: i for i, r in enumerate(config.LIKELIHOOD_RUNGS)}


def time_ago(iso: str) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    secs = int((datetime.now(timezone.utc) - dt).total_seconds())
    if secs < 0:
        return "just now"
    if secs < 3600:
        m = secs // 60
        return f"{m}m ago" if m else "just now"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    days = secs // 86400
    return f"{days}d ago" if days < 7 else dt.strftime("%d %b")


def slug(s: str) -> str:
    return (s or "").lower().replace(" & ", "-").replace(" ", "-")


def rung_index(label):
    return LIKELIHOOD_RANK.get(label, -1)


def club_code(name):
    return config.CLUB_CODES.get(name, (name or "")[:3].upper())


def crest_url(name):
    return config.CLUB_CRESTS.get(name, "")


app.jinja_env.filters["time_ago"] = time_ago
app.jinja_env.filters["slug"] = slug
app.jinja_env.filters["rung_index"] = rung_index
app.jinja_env.filters["club_code"] = club_code
app.jinja_env.filters["crest_url"] = crest_url
app.jinja_env.globals["rungs"] = config.LIKELIHOOD_RUNGS


def fabrizio_watch(conn):
    out = []
    for name in config.INSIDER_SOURCES:
        out.append({"name": name.replace(" (X)", ""),
                    "last": db.insider_last_post(conn, name)})
    out.sort(key=lambda x: x["last"] or "", reverse=True)
    return out


def pick_hero(clusters):
    """The biggest story: most source consensus, then best likelihood, then fresh."""
    best, best_score = None, -1
    for c in clusters[:40]:
        score = (c.get("source_count", 1) * 3
                 + rung_index(c.get("best_likelihood")) * 2
                 + (2 if c.get("has_insider") else 0))
        if score > best_score:
            best, best_score = c, score
    return best


def common_context(conn, page):
    snap = fixtures.get_cached(conn) or {}
    return {
        "page": page,
        "last_scrape": db.last_scrape_time(conn),
        "insiders": fabrizio_watch(conn),
        "snap": snap,
        "matchday": snap.get("is_matchday", False),
    }


@app.route("/")
def index():
    category = request.args.get("category", "All")
    source = request.args.get("source", "All")
    search = request.args.get("q", "").strip()
    rung = request.args.get("rung", "")

    with db.get_conn() as conn:
        clusters = db.query_clusters(conn, page="arsenal", category=category,
                                     source=source, search=search or None,
                                     min_rung=rung or None)
        counts = db.category_counts(conn, page="arsenal")
        sources = db.distinct_sources(conn, page="arsenal")
        heat = db.heat_leaderboard(conn, page="arsenal")
        injuries = db.injury_board(conn)
        deals = db.done_deals(conn, page="arsenal")
        the_brief = brief.get_cached(conn)
        ctx = common_context(conn, "arsenal")

    total = sum(counts.values())
    tabs = [("All", total)] + [(c, counts.get(c, 0)) for c in config.CATEGORY_ORDER]
    hero = pick_hero(clusters) if (category == "All" and not search and not rung) else None
    feed = [c for c in clusters if not (hero and c["url_hash"] == hero["url_hash"])]

    return render_template("index.html", clusters=feed, hero=hero, tabs=tabs,
                           sources=sources, active_category=category,
                           active_source=source, search=search, active_rung=rung,
                           heat=heat, injuries=injuries, deals=deals,
                           brief=the_brief, **ctx)


@app.route("/all")
def combined():
    category = request.args.get("category", "All")
    source = request.args.get("source", "All")
    search = request.args.get("q", "").strip()
    rung = request.args.get("rung", "")

    with db.get_conn() as conn:
        clusters = db.query_clusters(conn, page="all", category=category,
                                     source=source, search=search or None,
                                     min_rung=rung or None, limit=400)
        counts = db.category_counts(conn, page="all")
        sources = db.distinct_sources(conn, page="all")
        heat = db.heat_leaderboard(conn, page="all")
        deals = db.done_deals(conn, page="all")
        injuries = db.injury_board(conn)
        the_brief = brief.get_cached(conn)
        ctx = common_context(conn, "all")

    total = sum(counts.values())
    tabs = [("All", total)] + [(c, counts.get(c, 0)) for c in config.CATEGORY_ORDER]
    hero = pick_hero(clusters) if (category == "All" and not search and not rung) else None
    feed = [c for c in clusters if not (hero and c["url_hash"] == hero["url_hash"])]

    return render_template("all.html", clusters=feed, hero=hero, tabs=tabs,
                           sources=sources, active_category=category,
                           active_source=source, search=search, active_rung=rung,
                           heat=heat, injuries=injuries, deals=deals,
                           brief=the_brief, **ctx)


@app.route("/europe")
def europe():
    club = request.args.get("club", "All")
    search = request.args.get("q", "").strip()
    rung = request.args.get("rung", "")

    with db.get_conn() as conn:
        clusters = db.query_clusters(conn, page="europe", club=club,
                                     search=search or None, min_rung=rung or None,
                                     limit=500)
        counts = db.europe_club_counts(conn)
        heat = db.heat_leaderboard(conn, page="europe")
        deals = db.done_deals(conn, page="europe")
        ctx = common_context(conn, "europe")

    groups = {c: [] for c in config.EUROPE_CLUBS_ORDER}
    for it in clusters:
        primary = (it["clubs"] or "").split(",")[0].strip()
        if primary in groups:
            groups[primary].append(it)
    ordered_groups = [(c, groups[c]) for c in config.EUROPE_CLUBS_ORDER if groups[c]]
    club_chips = [(c, counts.get(c, 0)) for c in config.EUROPE_CLUBS_ORDER if counts.get(c, 0)]
    flat = (club != "All" or bool(search) or bool(rung))

    return render_template("europe.html", groups=ordered_groups, flat_items=clusters,
                           flat=flat, club_chips=club_chips, active_club=club,
                           search=search, active_rung=rung, heat=heat, deals=deals, **ctx)


@app.route("/heat")
def heat():
    page = request.args.get("page", "arsenal")
    if page not in ("arsenal", "europe", "all"):
        page = "arsenal"
    sort = request.args.get("sort", "heat")

    with db.get_conn() as conn:
        board = db.heat_page(conn, page=page)
        ctx = common_context(conn, page)

    if sort == "latest":
        board = sorted(board, key=lambda x: x["last_ts"] or "", reverse=True)

    title = {"arsenal": "Arsenal", "europe": "Other Teams", "all": "All"}[page]
    return render_template("heat.html", board=board, heat_page=page,
                           heat_title=title, sort=sort, **ctx)


@app.route("/saga/<path:player>")
def saga(player):
    with db.get_conn() as conn:
        ars = db.saga(conn, player, page="arsenal")
        eur = db.saga(conn, player, page="europe")
        rows = sorted(list(ars) + list(eur), key=lambda r: r["ts"])
        players = db.distinct_players(conn, page="arsenal")
        ctx = common_context(conn, "arsenal")
    return render_template("saga.html", player=player, rows=rows, players=players, **ctx)


@app.route("/refresh", methods=["POST"])
def refresh():
    back = request.form.get("back", "index")
    try:
        subprocess.run([sys.executable, "scrape.py"], cwd=config.BASE_DIR,
                       timeout=300, capture_output=True)
    except Exception:
        pass
    return redirect(url_for(back))


@app.route("/manifest.webmanifest")
def manifest():
    return send_from_directory(config.BASE_DIR + "/static", "manifest.webmanifest",
                               mimetype="application/manifest+json")


@app.route("/sw.js")
def service_worker():
    resp = send_from_directory(config.BASE_DIR + "/static", "sw.js",
                               mimetype="application/javascript")
    resp.headers["Service-Worker-Allowed"] = "/"
    return resp


if __name__ == "__main__":
    db.init_db()
    print(f"Arsenal Tracker running at http://{config.HOST}:{config.PORT}")
    app.run(host=config.HOST, port=config.PORT, debug=False)

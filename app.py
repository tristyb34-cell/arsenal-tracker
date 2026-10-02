"""Arsenal Tracker dashboard (Flask) - Broadcast Dark.

Pages:
  /              Arsenal command centre (clustered feed + hero + rail widgets)
  /fixtures      Full season schedule and results, every competition
  /match/<id>    Match centre: lineups, live timeline, team news, opponent
  /europe        Europe transfer desk (crest wall, grouped by club)
  /saga/<player> Transfer saga timeline for a player
  PWA: /manifest.webmanifest, /sw.js
"""

import json
import subprocess
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from flask import Flask, Response, redirect, render_template, request, send_from_directory, url_for

import brief
import config
import db
import fixtures
import matchcentre

app = Flask(__name__)

LIKELIHOOD_RANK = {r: i for i, r in enumerate(config.LIKELIHOOD_RUNGS)}
LOCAL_TZ = ZoneInfo("Africa/Johannesburg")


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


def _local(iso):
    """ESPN kickoffs are UTC. Tristan watches them from Johannesburg."""
    try:
        dt = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(LOCAL_TZ)


def ko_time(iso):
    dt = _local(iso)
    return dt.strftime("%H:%M") if dt else ""


def ko_day(iso):
    dt = _local(iso)
    return dt.strftime("%a %-d %b") if dt else ""


def ko_month(iso):
    dt = _local(iso)
    return dt.strftime("%B %Y") if dt else ""


def days_until(iso):
    dt = _local(iso)
    if not dt:
        return ""
    days = (dt.date() - datetime.now(LOCAL_TZ).date()).days
    if days < 0:
        return ""
    return "Today" if days == 0 else ("Tomorrow" if days == 1 else f"in {days} days")


app.jinja_env.filters["ko_time"] = ko_time
app.jinja_env.filters["ko_day"] = ko_day
app.jinja_env.filters["ko_month"] = ko_month
def days_until_soon(iso, within=14):
    """Only the near term. 40 rows of "in 263 days" is noise, not information."""
    dt = _local(iso)
    if not dt:
        return ""
    days = (dt.date() - datetime.now(LOCAL_TZ).date()).days
    return days_until(iso) if 0 <= days <= within else ""


def surname(name):
    """"K. De Bruyne" becomes "De Bruyne", not "Bruyne". The leading initial is
    the only part worth dropping on a pitch graphic."""
    parts = (name or "").split(" ")
    if len(parts) > 1 and parts[0].endswith(".") and len(parts[0]) <= 2:
        return " ".join(parts[1:])
    return name or ""


app.jinja_env.filters["surname"] = surname
app.jinja_env.filters["days_until"] = days_until
app.jinja_env.filters["days_until_soon"] = days_until_soon
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


@app.route("/fixtures")
def fixtures_page():
    """Every Arsenal game, every competition. Upcoming and results."""
    comp = request.args.get("comp", "All")
    view = request.args.get("view", "upcoming")
    if view not in ("upcoming", "results"):
        view = "upcoming"

    with db.get_conn() as conn:
        ctx = common_context(conn, "fixtures")

    snap = ctx["snap"] or {}
    matches = snap.get("fixtures" if view == "upcoming" else "results", [])
    if comp != "All":
        matches = [m for m in matches if m["comp"] == comp]

    groups = []
    for m in matches:
        label = ko_month(m["kickoff"])
        if not groups or groups[-1][0] != label:
            groups.append((label, []))
        groups[-1][1].append(m)

    return render_template("fixtures.html", groups=groups, view=view,
                           active_comp=comp, comps=snap.get("comps", []),
                           n_matches=len(matches), **ctx)


@app.route("/match/<event_id>")
def match(event_id):
    """Lineups, live timeline and build-up team news for one fixture."""
    with db.get_conn() as conn:
        ctx = common_context(conn, "fixtures")
        snap = ctx["snap"] or {}
        event = matchcentre.find_event(snap, event_id)
        if not event:
            return redirect(url_for("fixtures_page"))
        mc = matchcentre.get(conn, event)
        news = db.team_news(conn) if not event.get("finished") else []

    lineups = (mc or {}).get("lineups") or []
    return render_template("match.html", ev=event, mc=mc, news=news,
                           ars=matchcentre.arsenal_side(lineups),
                           opp=matchcentre.opponent_side(lineups), **ctx)


@app.route("/refresh-fixtures", methods=["POST"])
def refresh_fixtures():
    with db.get_conn() as conn:
        fixtures.refresh(conn, max_age_minutes=0)
    return redirect(url_for("fixtures_page", view=request.form.get("view", "upcoming"),
                            comp=request.form.get("comp", "All")))


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

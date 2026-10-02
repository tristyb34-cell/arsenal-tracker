"""Arsenal Tracker on the Mac (Flask, http://127.0.0.1:5057).

Serves exactly the same app as the phone. The client in docs/ (index.html,
app.js, style.css) renders everything from a JSON snapshot; on GitHub Pages
that snapshot is a static file pushed after each scrape, here it is built live
from arsenal.db on every request. Until 2026-10-02 the desktop had its own Jinja
templates and they drifted from the phone app every time one was touched, so
there is now one UI and two ways of feeding it.

  /                          the app (hash routes: #/, #/matches, #/match/<id>, #/news, #/table)
  /data/snapshot.json        live snapshot (same shape as docs/data/snapshot.json)
  /data/match/<id>.json      one match centre, fetched from ESPN on demand and cached
  /data/sagas.json           per-player transfer timelines
  POST /refresh              run a scrape now (the Refresh button, shown only here)
"""

import json
import os
import subprocess
import sys
from urllib.parse import quote

from flask import Flask, Response, abort, redirect, request, send_from_directory

import config
import db
import export
import fixtures
import matchcentre

app = Flask(__name__)
DOCS = os.path.join(config.BASE_DIR, "docs")


def _json(payload):
    resp = Response(json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    mimetype="application/json")
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.route("/")
def index():
    return send_from_directory(DOCS, "index.html")


@app.route("/data/snapshot.json")
def snapshot():
    with db.get_conn() as conn:
        snap = export.build(conn)
    snap["local"] = True  # unlocks the Refresh button
    return _json(snap)


@app.route("/data/match/<event_id>.json")
def match_data(event_id):
    with db.get_conn() as conn:
        event = matchcentre.find_event(fixtures.get_cached(conn) or {}, event_id)
        if not event:
            abort(404)
        payload = matchcentre.get(conn, event)
    if not payload:
        abort(502)
    return _json(payload)


@app.route("/data/sagas.json")
def sagas():
    with db.get_conn() as conn:
        return _json(export.sagas(conn))


@app.route("/refresh", methods=["POST"])
def refresh():
    try:
        subprocess.run([sys.executable, "scrape.py"], cwd=config.BASE_DIR,
                       timeout=300, capture_output=True)
    except Exception:
        return _json({"ok": False})
    return _json({"ok": True})


@app.route("/sw.js")
def service_worker():
    resp = send_from_directory(DOCS, "sw.js", mimetype="application/javascript")
    resp.headers["Service-Worker-Allowed"] = "/"
    resp.headers["Cache-Control"] = "no-cache"
    return resp


# Old desktop URLs, so bookmarks still land on the right screen.
LEGACY = {
    "fixtures": "#/matches", "europe": "#/news/others", "all": "#/news/all",
    "heat": "#/heat",
}


@app.route("/fixtures")
@app.route("/europe")
@app.route("/all")
@app.route("/heat")
def legacy():
    target = LEGACY[request.path.strip("/")]
    if request.path == "/fixtures" and request.args.get("view") == "results":
        target += "?view=results"
    return redirect("/" + target)


@app.route("/match/<event_id>")
def legacy_match(event_id):
    return redirect("/#/match/" + quote(event_id))


@app.route("/saga/<path:player>")
def legacy_saga(player):
    return redirect("/#/saga/" + quote(player))


@app.route("/<path:asset>")
def shell(asset):
    # docs/ holds only the public app shell and published data
    return send_from_directory(DOCS, asset)


if __name__ == "__main__":
    db.init_db()
    print(f"Arsenal Tracker running at http://{config.HOST}:{config.PORT}")
    app.run(host=config.HOST, port=config.PORT, debug=False)

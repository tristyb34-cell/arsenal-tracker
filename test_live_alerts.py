"""Guards for the two alert failures in Bayern Munich 2-2 Arsenal, 2026-10-21:
the game went silent from the 22:30 refresh, and Eze's goal went out as 0-0."""

from datetime import datetime, timezone

import live_alerts
from test_matchday import _key

KO = "2026-10-21T19:00:00+00:00"
BAYERN = {"id": "401", "kickoff": KO, "home": "Bayern Munich", "away": "Arsenal",
          "opponent": "Bayern Munich"}


def _summary(score, goals, name="STATUS_FIRST_HALF"):
    """A summary whose scoreboard says `score` while the goal feed already has `goals`."""
    return {
        "header": {"competitions": [{
            "competitors": [
                {"id": "132", "homeAway": "home", "score": score[0], "team": {"displayName": "Bayern Munich"}},
                {"id": "359", "homeAway": "away", "score": score[1], "team": {"displayName": "Arsenal"}}],
            "status": {"clock": 1500.0, "displayClock": "25'", "period": 1,
                       "type": {"name": name, "state": "in", "completed": False, "shortDetail": "25'"}}}]},
        "keyEvents": goals,
        "rosters": [],
    }


EZE = _key("Goal", "25'", 1500, 1, "359", "Arsenal", ["Eberechi Eze", "Bukayo Saka"], scoring=True)
DAVIES = _key("Goal", "35'", 2100, 1, "132", "Bayern Munich", ["Alphonso Davies"], scoring=True)


def test_a_match_in_progress_is_still_polled():
    """After a refresh the game sits only in live_match; the alerter must still find it."""
    snap = {"fixtures": [], "results": [], "live_match": BAYERN}
    now = datetime(2026, 10, 21, 20, 35, tzinfo=timezone.utc)
    assert live_alerts.current_match(snap, now) is BAYERN


def test_no_match_outside_the_window():
    snap = {"fixtures": [], "results": [], "live_match": BAYERN}
    assert live_alerts.current_match(snap, datetime(2026, 10, 22, 7, 0, tzinfo=timezone.utc)) is None


def test_goal_alert_uses_the_goal_feed_score_when_the_scoreboard_lags():
    data = _summary(("0", "0"), [EZE])
    state = live_alerts.matchcentre.live_state(data)
    (key, text), = live_alerts.build_alerts(BAYERN, data, state, {"ko"})
    assert "Bayern Munich 0-1 Arsenal" in text and "1-0 to the Arsenal" in text
    assert "Level" not in text


def test_later_goal_counts_earlier_ones_already_sent():
    data = _summary(("0", "1"), [EZE, DAVIES])
    state = live_alerts.matchcentre.live_state(data)
    (key, text), = live_alerts.build_alerts(BAYERN, data, state, {"ko", "ev0"})
    assert key == "ev1" and "Bayern Munich 1-1 Arsenal" in text and "All square" in text


# ---- the lineup take (config.LINEUP_TAKES) ------------------------------------
# Line-ups are the real ones: Bayern Munich 2-2 Arsenal on 2026-10-21, then
# Arsenal v Everton on 2026-10-24, as ESPN published them.

import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
from datetime import timedelta  # noqa: E402

import pytest  # noqa: E402

import config  # noqa: E402
import db  # noqa: E402
import lineup_take  # noqa: E402
import matchcentre  # noqa: E402

# id, name, ESPN pos, formation place
ARS_EVERTON = [("196176", "David Raya", "G", 1), ("241077", "Ben White", "D", 2),
               ("352758", "Myles Lewis-Skelly", "D", 3), ("231859", "Ezri Konsa", "D", 5),
               ("236322", "Gabriel Magalhães", "D", 6), ("209581", "Mikel Merino", "M", 4),
               ("293236", "Noni Madueke", "M", 7), ("238262", "Declan Rice", "M", 8),
               ("203669", "Martin Ødegaard", "M", 10), ("251400", "Eberechi Eze", "M", 11),
               ("258906", "Viktor Gyökeres", "F", 9)]
ARS_EVERTON_BENCH = [("1", "Bruno Guimarães"), ("2", "Cristhian Mosquera"), ("3", "Kepa Arrizabalaga"),
                     ("4", "Jurriën Timber"), ("5", "Kai Havertz"), ("6", "Piero Hincapié"),
                     ("7", "Riccardo Calafiori"), ("8", "Max Dowman"), ("9", "Martín Zubimendi")]
ARS_BAYERN = [("196176", "David Raya", "G", 1), ("4", "Jurriën Timber", "RB", 2),
              ("7", "Riccardo Calafiori", "LB", 3), ("231859", "Ezri Konsa", "CD-R", 5),
              ("236322", "Gabriel Magalhães", "CD-L", 6), ("1", "Bruno Guimarães", "CM", 4),
              ("203669", "Martin Ødegaard", "RM", 7), ("238262", "Declan Rice", "LM", 8),
              ("5", "Kai Havertz", "F", 9), ("10", "Bukayo Saka", "RF", 10),
              ("293236", "Noni Madueke", "LF", 11)]
EVERTON_XI = [("159443", "Jordan Pickford", "G", 1), ("311963", "Merlin Röhl", "D", 2),
              ("262594", "Vitaliy Mykolenko", "D", 3), ("283586", "Jake O'Brien", "D", 5),
              ("155226", "James Tarkowski", "D", 6), ("276220", "James Garner", "M", 4),
              ("291307", "Brennan Johnson", "M", 7), ("378458", "Harrison Armstrong", "M", 8),
              ("252389", "Kiernan Dewsbury-Hall", "M", 10), ("368864", "Tyrique George", "M", 11),
              ("301166", "Thierno Barry", "F", 9)]


def _short(name):
    first, _, rest = name.partition(" ")
    return f"{first[0]}. {rest}"


def _roster(team_id, team, side, formation, xi, bench):
    def athlete(pid, name):
        return {"id": pid, "displayName": name, "shortName": _short(name)}
    return {"team": {"id": team_id, "displayName": team}, "homeAway": side, "formation": formation,
            "roster": [{"athlete": athlete(pid, n), "position": {"abbreviation": pos},
                        "starter": True, "formationPlace": str(place)} for pid, n, pos, place in xi]
                      + [{"athlete": athlete(pid, n), "position": {"abbreviation": "SUB"}, "starter": False}
                         for pid, n in bench]}


def _side(team, formation, xi, bench=()):
    """A side as matchcentre._lineups shapes it."""
    return next(s for s in matchcentre._lineups({"rosters": [_roster("1", team, "home", formation, xi, bench)]}))


EVERTON_SUMMARY = {
    "header": {"competitions": [{
        "competitors": [
            {"id": "359", "homeAway": "home", "score": "0", "team": {"displayName": "Arsenal"}},
            {"id": "368", "homeAway": "away", "score": "0", "team": {"displayName": "Everton"}}],
        "status": {"clock": 0.0, "displayClock": "0'", "period": 0,
                   "type": {"name": "STATUS_SCHEDULED", "state": "pre", "completed": False,
                            "shortDetail": "Sat 24 Oct 14:00"}}}]},
    "keyEvents": [],
    "rosters": [_roster("359", "Arsenal", "home", "4-2-3-1", ARS_EVERTON, ARS_EVERTON_BENCH),
                _roster("368", "Everton", "away", "4-2-3-1", EVERTON_XI, [("20", "Mark Travers")])],
}

# What the lineup alert says today, pinned from the code before the take existed
# (live_alerts.py at bb75bdc). With the flag off it must not move a byte.
TODAYS_LINEUP = (
    "👕 XI's out. 4-2-3-1 against Everton:\n\n"
    "D. Raya, B. White, M. Lewis-Skelly, E. Konsa, G. Magalhães, M. Merino, N. Madueke, "
    "D. Rice, M. Ødegaard, E. Eze, V. Gyökeres\n\n"
    "Bench: B. Guimarães, C. Mosquera, K. Arrizabalaga, J. Timber, K. Havertz, P. Hincapié, "
    "R. Calafiori, M. Dowman, M. Zubimendi")

BAYERN_RESULT = {"id": "401915312", "kickoff": "2026-10-21T19:00:00+00:00", "finished": True,
                 "home": "Bayern Munich", "away": "Arsenal", "opponent": "Bayern Munich",
                 "home_goals": 2, "away_goals": 2, "league": "uefa.champions"}

CHANGES = ("5 changes from the 2-2 at Bayern Munich:\n"
           "In: White, Lewis-Skelly, Merino, Eze, Gyökeres\n"
           "Out: Timber (bench), Calafiori (bench), Guimarães (bench), Havertz (bench), "
           "Saka (not in the squad)\n"
           "Shape: 4-3-3 last time, 4-2-3-1 today.")


def test_changes_from_the_last_game():
    today = _side("Arsenal", "4-2-3-1", ARS_EVERTON, ARS_EVERTON_BENCH)
    bayern = _side("Arsenal", "4-3-3", ARS_BAYERN)
    ch = lineup_take.changes(today, bayern)
    assert [p["name"] for p in ch["in"]] == ["Ben White", "Myles Lewis-Skelly", "Mikel Merino",
                                             "Eberechi Eze", "Viktor Gyökeres"]
    assert [(p["name"], why) for p, why in ch["out"]] == [
        ("Jurriën Timber", "bench"), ("Riccardo Calafiori", "bench"), ("Bruno Guimarães", "bench"),
        ("Kai Havertz", "bench"), ("Bukayo Saka", "not in the squad")]
    assert lineup_take.changes_text(ch, BAYERN_RESULT) == CHANGES


def test_same_xi_says_so():
    today = _side("Arsenal", "4-3-3", ARS_BAYERN)
    text = lineup_take.changes_text(lineup_take.changes(today, today), BAYERN_RESULT)
    assert text == "Same XI as the 2-2 at Bayern Munich."


def test_full_backs_are_named_even_when_espn_only_says_d():
    """Pre-match ESPN calls every defender D; the take needs to know who the full-backs are."""
    line = lineup_take._xi_line(_side("Arsenal", "4-2-3-1", ARS_EVERTON))
    assert "Ben White (RB)" in line and "Myles Lewis-Skelly (LB)" in line
    assert "Ezri Konsa (CD-R)" in line and "Mikel Merino (M)" in line


def test_opponent_form_skips_friendlies_and_anything_after_kickoff(monkeypatch):
    from test_matchday import _sched_event
    everton = ("368", "Everton", "EVE")
    events = [
        _sched_event("1", "2026-08-15T14:00Z", everton, ("166", "Lille", "LIL"), ("1", "1"), league="club.friendly"),
        _sched_event("2", "2026-10-11T13:00Z", ("999", "Hull City", "HUL"), everton, ("2", "2")),
        _sched_event("3", "2026-10-17T11:30Z", everton, ("363", "Chelsea", "CHE"), ("0", "2")),
        _sched_event("4", "2026-10-24T14:00Z", ("359", "Arsenal", "ARS"), everton, None, state="pre", completed=False),
    ]
    for e in events:
        e["league"]["abbreviation"] = "Premier League"
    monkeypatch.setattr(lineup_take.fixtures, "_get", lambda url, params=None: {"events": events})
    form = lineup_take.opponent_form("368", datetime(2026, 10, 24, 14, 0, tzinfo=timezone.utc))
    assert form == ["Sun 11 Oct, Premier League: Hull City 2-2 Everton (drew)",
                    "Sat 17 Oct, Premier League: Everton 0-2 Chelsea (lost)"]


# ---- Claude failing, and the fallback ------------------------------------------

class FakeClaude:
    """Stands in for the claude CLI process: no real call in tests."""
    calls = []

    def __init__(self, stdout="", returncode=0, hang=False):
        self.stdout, self.returncode, self.hang, self.pid = stdout, returncode, hang, 4242

    def __call__(self, cmd, **kw):
        FakeClaude.calls.append((cmd, kw))
        return self

    def communicate(self, text=None, timeout=None):
        if self.hang and timeout:
            raise subprocess.TimeoutExpired("claude", timeout)
        return self.stdout, ""


def _reply(result, is_error=False):
    return json.dumps({"type": "result", "is_error": is_error, "result": result})


@pytest.fixture
def facts(monkeypatch):
    today = _side("Arsenal", "4-2-3-1", ARS_EVERTON, ARS_EVERTON_BENCH)
    bayern = _side("Arsenal", "4-3-3", ARS_BAYERN)
    found = {"ours": today, "theirs": None, "prev": BAYERN_RESULT, "prev_ours": bayern,
             "changes": lineup_take.changes(today, bayern), "form": [], "news": []}
    monkeypatch.setattr(lineup_take, "gather", lambda conn, event, data, now: found)
    monkeypatch.setattr(lineup_take.db, "get_conn", _null_conn)
    return found


class _null_conn:
    def __enter__(self):
        return None

    def __exit__(self, *a):
        return False


EVERTON = {"id": "401878768", "kickoff": "2026-10-24T14:00:00+00:00", "home": "Arsenal",
           "away": "Everton", "opponent": "Everton", "opponent_name": "Everton", "league": "eng.1"}


@pytest.mark.parametrize("claude", [
    FakeClaude(hang=True),                          # slower than CLAUDE_TIMEOUT
    FakeClaude(stdout="", returncode=1),            # crashed
    FakeClaude(stdout="Not logged in · Please run /login", returncode=1),
    FakeClaude(stdout=_reply("API Error: 529", is_error=True)),
    FakeClaude(stdout=_reply("   ")),               # empty take
    FakeClaude(stdout=_reply("blah " * 1000)),      # a ramble
], ids=["timeout", "crash", "logged-out", "api-error", "empty", "ramble"])
def test_claude_failure_sends_the_xi_with_the_plain_changes(monkeypatch, facts, claude):
    killed = []
    monkeypatch.setattr(lineup_take.subprocess, "Popen", claude)
    monkeypatch.setattr(lineup_take.os, "killpg", lambda pid, sig: killed.append(pid))
    text = lineup_take.message(EVERTON, EVERTON_SUMMARY, TODAYS_LINEUP)
    assert text == f"{TODAYS_LINEUP}\n\n{CHANGES}"
    assert killed == ([4242] if claude.hang else [])


def test_the_timeout_is_two_minutes_and_claude_runs_bare(monkeypatch, facts):
    FakeClaude.calls = []
    monkeypatch.setattr(lineup_take.subprocess, "Popen", FakeClaude(hang=True))
    monkeypatch.setattr(lineup_take.os, "killpg", lambda pid, sig: None)
    seen = {}
    real = FakeClaude.communicate

    def spy(self, text=None, timeout=None):
        seen.setdefault("timeout", timeout)
        return real(self, text, timeout)
    monkeypatch.setattr(FakeClaude, "communicate", spy)
    lineup_take.message(EVERTON, EVERTON_SUMMARY, TODAYS_LINEUP)
    (cmd, kw), = FakeClaude.calls
    assert seen["timeout"] == 120
    assert cmd[0] == config.CLAUDE_BIN and os.path.isabs(cmd[0])
    assert {"-p", "--setting-sources=project", "--tools=", "--strict-mcp-config"} <= set(cmd)
    assert cmd[cmd.index("--model") + 1] == "opus"
    assert kw["env"]["USER"] and kw["start_new_session"]


def test_a_good_take_rides_under_the_xi_in_bold_html_with_no_em_dashes(monkeypatch, facts):
    take = "Five changes and I rate it 🔴⚪\n- **Gyökeres** up top \u2014 right call.\nI'm calling 2-0."
    monkeypatch.setattr(lineup_take.subprocess, "Popen", FakeClaude(stdout=_reply(take)))
    text = lineup_take.message(EVERTON, EVERTON_SUMMARY, TODAYS_LINEUP)
    assert text == (f"{TODAYS_LINEUP}\n\nFive changes and I rate it 🔴⚪\n"
                    "- <b>Gyökeres</b> up top, right call.\nI'm calling 2-0.")


@pytest.mark.parametrize("raw, out", [
    ("**Gyökeres** up top", "<b>Gyökeres</b> up top"),
    ("**Saka** and **Rice**", "<b>Saka</b> and <b>Rice</b>"),
    ("Rice & **O'Brien** <3 >_<", "Rice &amp; <b>O'Brien</b> &lt;3 &gt;_&lt;"),
    ("an unclosed **bold", "an unclosed bold"),
])
def test_the_takes_bold_becomes_html_and_everything_else_is_escaped(raw, out):
    assert lineup_take.clean(raw) == out


# ---- the live path: flag off is today, flag on never doubles up ----------------


def _seed(event):
    """Put `event` in the cached snapshot, kicking off in 50 minutes."""
    event = dict(event, kickoff=(datetime.now(timezone.utc) + timedelta(minutes=50)).isoformat())
    with db.get_conn() as conn:
        db.kv_set(conn, "football", json.dumps({"fixtures": [event], "results": [], "live_match": None}),
                  datetime.now(timezone.utc).isoformat())
    return event


@pytest.fixture
def run(monkeypatch, tmp_path):
    """live_alerts.main() against a scratch database, ESPN and Telegram stubbed."""
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "t.db"))
    db.init_db()
    event = _seed(EVERTON)
    sent, spawned = [], []
    monkeypatch.setattr(live_alerts, "notify", lambda text, **kw: sent.append(text))
    monkeypatch.setattr(live_alerts, "_refresh_snapshot", lambda: None)
    monkeypatch.setattr(live_alerts, "_spawn_take", lambda e, d, plain: spawned.append(plain) or True)

    def go(summary=EVERTON_SUMMARY):
        monkeypatch.setattr(live_alerts.matchcentre, "_get", lambda url, params=None: summary)
        live_alerts.main()
        return sent, spawned
    go.event = event
    return go


def _take_state(event):
    with db.get_conn() as conn:
        row = db.kv_get(conn, f"lineup_take:{event['id']}")
    return row and row["value"]


def test_flag_off_sends_todays_exact_lineup(monkeypatch, run):
    monkeypatch.setattr(config, "LINEUP_TAKES", False)
    sent, spawned = run()
    assert sent == [TODAYS_LINEUP] and spawned == []
    assert _take_state(run.event) is None
    sent, spawned = run()
    assert sent == [TODAYS_LINEUP]                  # and only once


def test_flag_on_hands_the_lineup_to_one_worker_however_often_it_runs(monkeypatch, run):
    monkeypatch.setattr(config, "LINEUP_TAKES", True)
    sent, spawned = run()
    run()
    run()
    assert spawned == [TODAYS_LINEUP] and sent == []
    assert _take_state(run.event) == "pending"
    # a run that overlapped and read the alert list before the claim landed
    with db.get_conn() as conn:
        rest = live_alerts.take_over_lineup(conn, run.event, EVERTON_SUMMARY,
                                            [("lineup", TODAYS_LINEUP), ("ko", "kick off")], set())
    assert rest == [("ko", "kick off")] and spawned == [TODAYS_LINEUP]


def _job(tmp_path, event):
    path = tmp_path / "job.json"
    path.write_text(json.dumps({"event": event, "data": EVERTON_SUMMARY, "plain": TODAYS_LINEUP}))
    return str(path)


def test_the_worker_sends_once_and_a_late_rescue_does_not_repeat_it(monkeypatch, run, tmp_path):
    monkeypatch.setattr(config, "LINEUP_TAKES", True)
    sent, _ = run()
    monkeypatch.setattr(live_alerts.lineup_take, "message", lambda e, d, plain: plain + "\n\nTAKE")
    live_alerts.deliver_lineup(_job(tmp_path, run.event))
    live_alerts.deliver_lineup(_job(tmp_path, run.event))
    monkeypatch.setattr(live_alerts, "TAKE_RESCUE_AFTER", timedelta(0))
    run()
    assert sent == [TODAYS_LINEUP + "\n\nTAKE"] and _take_state(run.event) == "sent"


def test_a_dead_worker_is_rescued_with_the_plain_xi_exactly_once(monkeypatch, run, tmp_path):
    monkeypatch.setattr(config, "LINEUP_TAKES", True)
    sent, _ = run()
    run()
    assert sent == []                               # the worker still has time
    monkeypatch.setattr(live_alerts, "TAKE_RESCUE_AFTER", timedelta(0))
    run()
    run()
    assert sent == [TODAYS_LINEUP]
    # the worker wakes up after all: it must not send a second lineup
    monkeypatch.setattr(live_alerts.lineup_take, "message", lambda e, d, plain: plain + "\n\nTAKE")
    live_alerts.deliver_lineup(_job(tmp_path, run.event))
    assert sent == [TODAYS_LINEUP]


def test_a_worker_that_cannot_start_sends_the_plain_xi_at_once(monkeypatch, run):
    monkeypatch.setattr(config, "LINEUP_TAKES", True)
    monkeypatch.setattr(live_alerts, "_spawn_take", lambda e, d, plain: False)
    sent, _ = run()
    run()
    assert sent == [TODAYS_LINEUP] and _take_state(run.event) == "sent"


def test_the_lineup_take_is_live():
    assert config.LINEUP_TAKES is True


# ---- the whole bench, and Telegram HTML -----------------------------------------

import re  # noqa: E402

import requests  # noqa: E402
import telegram_notify  # noqa: E402

# ESPN's ten subs for Bayern Munich 2-2 Arsenal. The old [:9] cut Gyökeres, the last.
BAYERN_BENCH = [("8", "Max Dowman"), ("2", "Cristhian Mosquera"), ("241077", "Ben White"),
                ("9", "Martín Zubimendi"), ("3", "Kepa Arrizabalaga"), ("251400", "Eberechi Eze"),
                ("209581", "Mikel Merino"), ("352758", "Myles Lewis-Skelly"), ("11", "Illan Meslier"),
                ("258906", "Viktor Gyökeres")]


def test_the_whole_bench_goes_out_even_past_nine():
    data = {"rosters": [_roster("359", "Arsenal", "away", "4-3-3", ARS_BAYERN, BAYERN_BENCH)]}
    (key, text), = live_alerts.build_alerts(BAYERN, data, None, set())
    assert key == "lineup"
    assert text.endswith("Bench: M. Dowman, C. Mosquera, B. White, M. Zubimendi, K. Arrizabalaga, "
                         "E. Eze, M. Merino, M. Lewis-Skelly, I. Meslier, V. Gyökeres")


# Brighton & Hove Albion is ESPN's real name for them, and the & breaks Telegram HTML
# unless escaped. The other names are made awkward on purpose.
BRIGHTON = {"id": "402", "home": "Arsenal", "away": "Brighton & Hove Albion",
            "opponent": "Brighton & Hove Albion", "league": "eng.1"}
ODD_BENCH = [("31", "Jake O'Brien"), ("32", "Smith & Jones"), ("33", "Lee <Jr>")]


def _brighton(name, state, completed=False, events=()):
    return {
        "header": {"competitions": [{
            "competitors": [
                {"id": "359", "homeAway": "home", "score": "1", "team": {"displayName": "Arsenal"}},
                {"id": "331", "homeAway": "away", "score": "1", "team": {"displayName": "Brighton & Hove Albion"}}],
            "status": {"clock": 1500.0, "displayClock": "25'", "period": 1,
                       "type": {"name": name, "state": state, "completed": completed, "shortDetail": "x"}}}]},
        "keyEvents": list(events),
        "rosters": [_roster("359", "Arsenal", "home", "4-2-3-1", ARS_EVERTON, ODD_BENCH)],
    }


GOALS_AND_RED = [
    _key("Goal", "12'", 720, 1, "359", "Arsenal", ["Martin Ødegaard", "Declan Rice"], scoring=True),
    _key("Goal", "20'", 1200, 1, "331", "Brighton & Hove Albion", ["Jake O'Brien"], scoring=True),
    _key("Red Card", "24'", 1440, 1, "331", "Brighton & Hove Albion", ["Lewis <Dunk>"]),
]
# lineup; then kick-off, two goals and a red; half time; full time
STAGES = [_brighton("STATUS_SCHEDULED", "pre"),
          _brighton("STATUS_FIRST_HALF", "in", events=GOALS_AND_RED),
          _brighton("STATUS_HALFTIME", "in", events=GOALS_AND_RED),
          _brighton("STATUS_FULL_TIME", "post", completed=True, events=GOALS_AND_RED)]


def _is_clean_html(text):
    """No bare &, < or > outside our <b> tags."""
    bare = re.sub(r"</?b>", "", text)
    return "<" not in bare and ">" not in bare and not re.search(r"&(?!amp;|lt;|gt;)", bare)


def test_awkward_names_are_escaped_and_come_back_whole_as_plain_text():
    (_, text), = live_alerts.build_alerts(BRIGHTON, STAGES[0], None, set())
    assert "M. Ødegaard" in text and "J. O'Brien" in text
    assert "S. &amp; Jones" in text and "L. &lt;Jr&gt;" in text and "Brighton &amp; Hove Albion" in text
    assert _is_clean_html(text)
    plain = live_alerts.plain_text(text)
    assert "S. & Jones" in plain and "L. <Jr>" in plain and "Brighton & Hove Albion" in plain
    assert live_alerts.plain_text("- <b>Saka</b> &amp; <b>O'Brien</b> &lt;3") == "- Saka & O'Brien <3"


class _Response:
    def __init__(self, status):
        self.status_code = status
        self.text = ('{"ok":false,"error_code":400,"description":"Bad Request: can\'t parse entities"}'
                     if status == 400 else '{"ok":true}')

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(self.text)


class FakeTelegram:
    """Stands in for api.telegram.org; with reject on, every HTML message gets the 400."""

    def __init__(self, reject):
        self.reject, self.posts = reject, []

    def __call__(self, url, data=None, timeout=None):
        self.posts.append(dict(data))
        return _Response(400 if self.reject and data.get("parse_mode") else 200)


@pytest.fixture
def telegram(monkeypatch, tmp_path):
    """The real notify() with only the HTTP call stubbed: nothing leaves the machine."""
    cfg = tmp_path / "bridge.json"
    cfg.write_text(json.dumps({"token": "t", "chat_id": "1", "chat_log": str(tmp_path / "chat.jsonl")}))
    monkeypatch.setattr(telegram_notify, "CONFIG_PATH", cfg)
    monkeypatch.setattr(telegram_notify.time, "sleep", lambda s: pytest.fail("a refused message was retried"))

    def make(reject):
        fake = FakeTelegram(reject)
        monkeypatch.setattr(telegram_notify.requests, "post", fake)
        monkeypatch.setattr(live_alerts, "notify", telegram_notify.notify)
        return fake
    return make


def _match_day(monkeypatch, run):
    monkeypatch.setattr(config, "LINEUP_TAKES", False)
    _seed(BRIGHTON)
    for summary in STAGES:
        run(summary)


def test_every_alert_type_goes_out_as_html(monkeypatch, run, telegram):
    tg = telegram(reject=False)
    _match_day(monkeypatch, run)
    assert len(tg.posts) == 7                       # lineup, ko, 2 goals, red, ht, ft
    assert all(p["parse_mode"] == "HTML" and _is_clean_html(p["text"]) for p in tg.posts)


def test_every_alert_type_is_resent_as_plain_text_when_telegram_refuses_the_html(monkeypatch, run, telegram):
    tg = telegram(reject=True)
    _match_day(monkeypatch, run)
    tried, resent = tg.posts[0::2], tg.posts[1::2]
    assert len(tried) == len(resent) == 7
    assert all(p["parse_mode"] == "HTML" for p in tried) and not any("parse_mode" in p for p in resent)
    assert [p["text"] for p in resent] == [live_alerts.plain_text(p["text"]) for p in tried]
    lineup, ko, ours, theirs, red, ht, ft = (p["text"] for p in resent)
    assert lineup.endswith("Bench: J. O'Brien, S. & Jones, L. <Jr>") and "M. Ødegaard" in lineup
    assert "Martin Ødegaard" in ours and "Lovely ball from Declan Rice." in ours
    assert "Arsenal 1-0 Brighton & Hove Albion" in ours
    assert "Jake O'Brien" in theirs and "Arsenal 1-1 Brighton & Hove Albion" in theirs
    assert "Lewis <Dunk>" in red and ko.endswith("Arsenal v Brighton & Hove Albion")
    assert ht.startswith("⏸") and ft.startswith("🤝")
    # each alert went once and is recorded, so the next run sends nothing
    run(STAGES[-1])
    assert len(tg.posts) == 14


def test_the_lineup_take_is_resent_as_plain_text_too(monkeypatch, run, telegram, tmp_path):
    monkeypatch.setattr(config, "LINEUP_TAKES", True)
    run()
    tg = telegram(reject=True)
    monkeypatch.setattr(live_alerts.lineup_take, "message",
                        lambda e, d, plain: plain + "\n\n- <b>Gyökeres</b> up top &amp; Eze behind.")
    live_alerts.deliver_lineup(_job(tmp_path, run.event))
    assert [("parse_mode" in p) for p in tg.posts] == [True, False]
    assert tg.posts[1]["text"] == TODAYS_LINEUP + "\n\n- Gyökeres up top & Eze behind."
    assert _take_state(run.event) == "sent"

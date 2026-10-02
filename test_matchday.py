"""Guards for the 2026-10-02 match-day rebuild: the schedule feed, scorers,
team stats, kit colours and the timeline markers.

Every payload shape below is copied from a real ESPN response checked live on
2026-10-02, trimmed to the fields the code reads."""

from datetime import datetime, timedelta, timezone

import fixtures
import matchcentre


# ---- fixtures: the team schedule feed ---------------------------------------

def _sched_event(eid="401879274", date="2026-09-19T14:00Z", home=("331", "Brighton & Hove Albion", "BHA"),
                 away=("359", "Arsenal", "ARS"), score=("3", "0"), state="post", completed=True,
                 season_type="2026-27 English Premier League", league="eng.1"):
    def comp(side, team, goals):
        c = {"homeAway": side, "team": {"id": team[0], "displayName": team[1], "abbreviation": team[2],
                                         "logos": [{"href": f"https://a.espncdn.com/i/teamlogos/soccer/500/{team[0]}.png",
                                                    "rel": ["full", "default"]}]}}
        if goals is not None:
            c["score"] = {"value": float(goals), "displayValue": goals}
        return c
    return {
        "id": eid, "date": date, "league": {"slug": league},
        "seasonType": {"name": season_type},
        "links": [{"rel": ["summary", "desktop", "event"], "href": "https://www.espn.com/soccer/match/_/gameId/" + eid}],
        "competitions": [{
            "venue": {"fullName": "American Express Stadium"}, "notes": [],
            "competitors": [comp("home", home, score[0] if score else None),
                            comp("away", away, score[1] if score else None)],
            "status": {"clock": 5400.0, "period": 2,
                       "type": {"name": "STATUS_FULL_TIME" if completed else "STATUS_SCHEDULED",
                                "state": state, "completed": completed, "shortDetail": "FT" if completed else "Sat 10th"}},
        }],
    }


def test_schedule_score_object_is_read():
    """The schedule endpoint wraps the score in an object; the old scoreboard
    parser read it as a string and would have shown every result as blank."""
    ev = fixtures._decorate(fixtures._parse_event(_sched_event(), fixtures.COMP_BY_LEAGUE["eng.1"]))
    assert (ev["home_goals"], ev["away_goals"]) == (3, 0)
    assert ev["score"] == "0–3" and ev["result"] == "L"        # Arsenal-first
    assert ev["home_logo"].endswith("/331.png") and ev["finished"] and not ev["live"]


def test_unplayed_match_has_no_score():
    ev = fixtures._decorate(fixtures._parse_event(
        _sched_event(score=None, state="pre", completed=False), fixtures.COMP_BY_LEAGUE["eng.1"]))
    assert ev["home_goals"] is None and ev["score"] == "" and ev["result"] is None


def test_round_comes_from_cups_not_league_season_names():
    assert fixtures._round({"seasonType": {"name": "Third Round"}}) == "Third Round"
    assert fixtures._round({"seasonType": {"name": "League Phase"}}) == "League Phase"
    assert fixtures._round({"seasonType": {"name": "2026-27 English Premier League"}}) == ""


def test_friendlies_are_not_competitions():
    assert "club.friendly" not in fixtures.COMP_BY_LEAGUE
    assert "friendly.emirates_cup" not in fixtures.COMP_BY_LEAGUE


def test_kicked_off_match_does_not_vanish_before_espn_flags_it():
    """A match whose kickoff has passed but which the cache still calls
    upcoming must stay on the list (and as next match) rather than disappear
    until full time."""
    now = datetime(2026, 10, 10, 12, 0, tzinfo=timezone.utc)
    ev = fixtures._decorate(fixtures._parse_event(
        _sched_event(eid="1", date="2026-10-10T11:30Z", home=("359", "Arsenal", "ARS"),
                     away=("357", "Leeds United", "LEE"), score=None, state="pre", completed=False),
        fixtures.COMP_BY_LEAGUE["eng.1"]))
    snap = fixtures.assemble([ev], [], now=now)
    assert snap["next_match"]["id"] == "1"


def test_apply_live_moves_a_match_into_live_and_scores_it():
    now = datetime.now(timezone.utc)
    ko = (now - timedelta(minutes=30)).strftime("%Y-%m-%dT%H:%MZ")
    ev = fixtures._decorate(fixtures._parse_event(
        _sched_event(eid="9", date=ko, home=("359", "Arsenal", "ARS"),
                     away=("357", "Leeds United", "LEE"), score=None, state="pre", completed=False),
        fixtures.COMP_BY_LEAGUE["eng.1"]))
    snap = fixtures.assemble([ev], [])
    state = {"state": "in", "completed": False, "home_goals": 1, "away_goals": 0,
             "detail": "31'", "name": "STATUS_FIRST_HALF", "clock": 1832.0, "period": 1,
             "clock_at": now.isoformat()}
    out = fixtures.apply_live(snap, "9", state)
    assert out["live_match"]["id"] == "9" and out["live_match"]["score"] == "1–0"
    assert out["live_match"]["clock"] == 1832.0
    assert out["next_match"] is None and out["is_matchday"]


# ---- match centre: timeline, scorers, stats ---------------------------------

HEADER = {"competitions": [{"competitors": [
    {"id": "359", "homeAway": "home", "score": "2", "team": {"displayName": "Arsenal"}},
    {"id": "363", "homeAway": "away", "score": "1", "team": {"displayName": "Chelsea"}}],
    "status": {"clock": 5400.0, "displayClock": "90'+5'", "period": 2,
               "type": {"name": "STATUS_FULL_TIME", "state": "post", "completed": True, "shortDetail": "FT"}}}]}


def _key(kind, minute, secs, period, team_id, team_name, names, text="x", scoring=False):
    return {"type": {"text": kind}, "text": text, "clock": {"displayValue": minute, "value": secs},
            "period": {"number": period}, "scoringPlay": scoring,
            "team": {"id": team_id, "displayName": team_name},
            "participants": [{"athlete": {"id": str(i), "displayName": n}} for i, n in enumerate(names)]}


SUMMARY = {
    "header": HEADER,
    "keyEvents": [
        _key("Kickoff", "", 0, 1, "", "", []),
        _key("Goal - Header", "2'", 100, 1, "363", "Chelsea", ["Morgan Rogers", "Jorrel Hato"], scoring=True),
        # an own goal is credited to the side that benefited, not the scorer's club
        _key("Own Goal", "45'+2'", 2700, 1, "359", "Arsenal", ["Wesley Fofana"], scoring=True),
        _key("Start 2nd Half", "", 2700, 2, "", "", []),
        _key("Penalty - Scored", "90'+7'", 5400, 2, "359", "Arsenal", ["Bukayo Saka"], scoring=True),
        _key("Substitution", "67'", 4000, 2, "359", "Arsenal", ["Piero Hincapie", "Riccardo Calafiori"]),
        _key("Penalty - Scored", "", 0, 5, "359", "Arsenal", ["Bukayo Saka"], scoring=True),
    ],
    "rosters": [],
}
SUMMARY["keyEvents"][-1]["shootout"] = True


def test_header_goals_are_goals_and_alert_worthy():
    """'Goal - Header' was missing from GOAL_TYPES, so a headed goal was not
    'big' and live_alerts never sent it."""
    tl = matchcentre._timeline(SUMMARY)
    header = next(t for t in tl if t["type"] == "Goal - Header")
    assert header["kind"] == "goal" and header["big"] and header["side"] == "away"


def test_own_goal_is_listed_under_the_side_it_counted_for():
    s = matchcentre.scorers(matchcentre._timeline(SUMMARY))
    assert [r["name"] for r in s["home"]] == ["Fofana", "Saka"]
    assert s["home"][0]["og"] and not s["home"][1]["og"]
    assert s["home"][1]["goals"][0]["pen"]
    assert [r["name"] for r in s["away"]] == ["Rogers"]


def test_shootout_kicks_are_not_goals():
    tl = matchcentre._timeline(SUMMARY)
    assert sum(t["scoring"] for t in tl) == 3


def test_ours_follows_the_benefiting_team():
    tl = matchcentre._timeline(SUMMARY)
    og = next(t for t in tl if t["kind"] == "og")
    assert og["ours"]


def test_markers_supply_half_time_when_espn_does_not():
    state = matchcentre.live_state(SUMMARY)
    drawn = matchcentre.with_markers(matchcentre._timeline(SUMMARY), state)
    kinds = [t["kind"] for t in drawn]
    assert kinds.count("ht") == 1 and kinds[-1] == "ft"
    ht = next(t for t in drawn if t["kind"] == "ht")
    assert ht["score"] == "1–1"          # Rogers 2', own goal 45+2'
    assert drawn[-1]["score"] == "2–1"


def test_no_markers_before_kickoff():
    state = {"state": "pre", "completed": False, "period": 0}
    assert matchcentre.with_markers([], state) == []


def test_live_state_carries_the_clock():
    st = matchcentre.live_state(SUMMARY)
    assert st["clock"] == 5400.0 and st["period"] == 2 and st["clock_at"]


def test_stats_map_to_home_and_away_by_team_id():
    data = {"header": HEADER, "boxscore": {"teams": [
        {"team": {"id": "363"}, "statistics": [{"name": "possessionPct", "displayValue": "45.4"},
                                               {"name": "totalShots", "displayValue": "13"}]},
        {"team": {"id": "359"}, "statistics": [{"name": "possessionPct", "displayValue": "54.6"},
                                               {"name": "totalShots", "displayValue": "16"}]}]}}
    stats = {s["key"]: s for s in matchcentre._stats(data)}
    assert (stats["possessionPct"]["home"], stats["possessionPct"]["away"]) == (54.6, 45.4)
    assert (stats["totalShots"]["home"], stats["totalShots"]["away"]) == (16, 13)


def test_all_zero_stats_are_a_match_not_started():
    data = {"header": HEADER, "boxscore": {"teams": [
        {"team": {"id": "363"}, "statistics": [{"name": "totalShots", "displayValue": "0"}]},
        {"team": {"id": "359"}, "statistics": [{"name": "totalShots", "displayValue": "0"}]}]}}
    assert matchcentre._stats(data) == []


# ---- kit colours -------------------------------------------------------------

def test_light_kits_get_dark_numbers():
    """White numbers on Man City sky blue (99c5ea) and Sunderland's pink
    alternate failed contrast."""
    assert matchcentre.kit_colours("99c5ea", "000000", False) == ("#99c5ea", "dark")
    assert matchcentre.kit_colours("144992", "FFFFFF", False) == ("#144992", "light")


def test_red_opponents_switch_to_their_alternate():
    """Two XIs in the same red is unreadable. Real ESPN colours: Man Utd
    da020e/4169E1, Sunderland EB172B/FFB6C1."""
    assert matchcentre.kit_colours("da020e", "4169E1", False)[0] == "#4169e1"
    assert matchcentre.kit_colours("EB172B", "FFB6C1", False) == ("#ffb6c1", "dark")
    # claret is not red: Villa keep their own colour
    assert matchcentre.kit_colours("660e36", "000000", False)[0] == "#660e36"


def test_arsenal_kit_is_left_to_css():
    assert matchcentre.kit_colours("e20520", "003399", True) == ("", "light")

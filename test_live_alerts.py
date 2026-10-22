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

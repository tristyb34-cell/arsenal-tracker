"""Guards for the match centre's lineup shaping.

The pitch used to be built from ESPN's `formationPlace`, which is a slot id
rather than a back-to-front sequence. That put Declan Rice in Arsenal's back
four and Stanislav Lobotka in Napoli's. These tests pin the fix: rows come from
the players' actual positions, so a midfielder can never render in defence."""

import matchcentre


def _p(name, pos, place):
    return {"name": name, "short": name, "jersey": "", "pos": pos, "starter": True,
            "place": place, "subbed_off": False, "subbed_on": False, "photo": ""}


ARSENAL_XI = [
    _p("Raya", "G", 1), _p("White", "D", 2), _p("Hincapie", "D", 3),
    _p("Rice", "M", 4), _p("Konsa", "D", 5), _p("Gabriel", "D", 6),
    _p("Saka", "M", 7), _p("Merino", "M", 8), _p("Gyokeres", "F", 9),
    _p("Odegaard", "M", 10), _p("Eze", "M", 11),
]

NAPOLI_XI = [
    _p("Meret", "G", 1), _p("Di Lorenzo", "D", 2), _p("Olivera", "D", 3),
    _p("Lobotka", "M", 4), _p("Rrahmani", "D", 5), _p("Marin", "D", 6),
    _p("Gilmour", "M", 7), _p("De Bruyne", "M", 8), _p("Hojlund", "F", 9),
    _p("Politano", "F", 10), _p("Santos", "F", 11),
]


def test_midfielder_never_lands_in_defence():
    rows = matchcentre._shape(ARSENAL_XI, "4-2-3-1")
    assert [p["name"] for p in rows[1]] == ["White", "Hincapie", "Konsa", "Gabriel"]
    assert "Rice" in [p["name"] for p in rows[2]]


def test_napoli_back_four_excludes_lobotka():
    rows = matchcentre._shape(NAPOLI_XI, "4-3-3")
    assert "Lobotka" not in [p["name"] for p in rows[1]]
    assert [len(r) for r in rows] == [1, 4, 3, 3]


def test_every_starter_is_placed():
    for xi, formation in ((ARSENAL_XI, "4-2-3-1"), (NAPOLI_XI, "4-3-3")):
        rows = matchcentre._shape(xi, formation)
        assert sum(len(r) for r in rows) == 11


def test_unknown_position_falls_back_to_one_row():
    weird = [_p("Mystery", "X", 1)] + ARSENAL_XI[1:]
    rows = matchcentre._shape(weird, "4-2-3-1")
    assert len(rows) == 1 and len(rows[0]) == 11


def test_arsenal_goal_is_detected_from_the_bracket():
    assert matchcentre._scored_by_arsenal(
        "Goal! Napoli 0, Arsenal 1. Bukayo Saka (Arsenal) right footed shot.")
    assert not matchcentre._scored_by_arsenal(
        "Goal! Napoli 1, Arsenal 0. Rasmus Hojlund (Napoli) header.")



# ---- headshots -------------------------------------------------------------
# ESPN carries a headshot for only a minority of soccer players. Checked live
# against the Arsenal v Napoli summary on 2026-09-09: 3 of 42 athletes had one
# and none of them were starters. Missing is the normal case, so the pitch has
# to fall back to the numbered disc rather than render a broken image.

def _athlete(headshot=None):
    a = {"id": "280555", "displayName": "Bukayo Saka", "shortName": "B. Saka"}
    if headshot is not None:
        a["headshot"] = headshot
    return {"athlete": a, "jersey": "7", "starter": True,
            "position": {"abbreviation": "M"}, "formationPlace": "7"}


def test_headshot_uses_the_declared_href():
    """Verbatim shape ESPN returned for Noni Madueke."""
    url = matchcentre._headshot({
        "headshot": {"href": "https://a.espncdn.com/i/headshots/soccer/players/full/293236.png",
                     "alt": "Noni Madueke"}})
    assert "/i/headshots/soccer/players/full/293236.png" in url
    assert url.startswith("https://a.espncdn.com/combiner/i?img=")


def test_missing_headshot_is_empty_not_a_guessed_url():
    """The id is right there and it is still not enough to build a URL from:
    the CDN 404d for 19 of 20 real ids, so guessing means a broken image."""
    for a in ({}, {"headshot": None}, {"headshot": {}}, {"headshot": {"href": ""}},
              {"headshot": {"href": "   "}}):
        assert matchcentre._headshot(a) == ""
    assert matchcentre._headshot({"id": "280555"}) == ""


def test_non_png_href_is_dropped():
    """The shirt disc keeps its kit colour behind the photo and relies on the
    cut-out being transparent, so an opaque JPEG would cover the team colour
    entirely. Every headshot ESPN has served is a PNG; drop anything else."""
    url = "https://a.espncdn.com/i/headshots/soccer/players/full/1.jpg"
    assert matchcentre._headshot({"headshot": {"href": url}}) == ""


def test_player_exposes_photo_for_the_template():
    with_photo = matchcentre._player(_athlete(
        {"href": "https://a.espncdn.com/i/headshots/soccer/players/full/293236.png"}))
    assert with_photo["photo"]
    without = matchcentre._player(_athlete())
    assert without["photo"] == ""
    assert without["name"] == "Bukayo Saka"  # the rest of the player still builds


def test_shaped_rows_all_carry_a_photo_key():
    """The template reads p['photo'] on every pitch position, so no starter may
    reach it without the key."""
    rows = matchcentre._shape(ARSENAL_XI, "4-2-3-1")
    assert all("photo" in p for row in rows for p in row)


# ---- ESPN payload shape drift ----------------------------------------------
# Three faults found on 2026-09-09 while adding headshots. All three are the
# same class: ESPN returns a different shape for the same idea depending on the
# fixture, and the match centre only handled the one shape it was written
# against. Every code and value below is copied from a real summary response.

CHELSEA_XI_CODES = [  # Arsenal v Chelsea, event 401879292, formation 3-4-2-1
    ("Emiliano Martinez", "G"), ("Maxence Lacroix", "CD"),
    ("Wesley Fofana", "CD-L"), ("Josh Acheampong", "CD-R"),
    ("Reece James", "CM-L"), ("Romeo Lavia", "CM-R"),
    ("Jorrel Hato", "LM"), ("Pedro Neto", "RM"),
    ("Joao Pedro", "F"), ("Morgan Rogers", "CF-L"), ("Cole Palmer", "CF-R"),
]

COVENTRY_XI_CODES = [  # Arsenal v Coventry, event 401879301: full-backs as LB/RB
    ("Keeper", "G"), ("Left Back", "LB"), ("Right Back", "RB"),
    ("Centre Back", "CD-L"), ("Other Centre Back", "CD-R"),
    ("Holder", "DM"), ("Eight", "M"), ("Ten", "AM"),
    ("Left Wing", "AM-L"), ("Right Wing", "AM-R"), ("Striker", "F"),
]


def test_band_maps_every_position_code_seen_live():
    b = matchcentre._band
    assert [b(c) for c in ("G", "D", "CD", "CD-L", "CD-R")] == ["G"] + ["D"] * 4
    assert [b(c) for c in ("LB", "RB")] == ["D", "D"]           # full-backs defend
    assert [b(c) for c in ("M", "DM", "AM", "AM-L", "LM", "RM", "CM-R")] == ["M"] * 7
    assert [b(c) for c in ("F", "CF-L", "CF-R")] == ["F"] * 3


def test_band_rejects_non_positions():
    """"SUB" ends in B and must not be read as a full-back."""
    for junk in ("SUB", "X", "", None):
        assert matchcentre._band(junk) == ""


def test_granular_codes_still_build_a_real_shape():
    """These used to collapse to a single flat row of eleven, because none of
    "CD-L", "CM-R" or "LM" starts with D or M."""
    xi = [_p(n, code, i + 1) for i, (n, code) in enumerate(CHELSEA_XI_CODES)]
    assert [len(r) for r in matchcentre._shape(xi, "3-4-2-1")] == [1, 3, 4, 3]


def test_full_backs_land_in_defence_not_a_flat_row():
    xi = [_p(n, code, i + 1) for i, (n, code) in enumerate(COVENTRY_XI_CODES)]
    rows = matchcentre._shape(xi, "4-1-4-1")
    assert [len(r) for r in rows] == [1, 4, 5, 1]
    assert {"Left Back", "Right Back"} <= {p["name"] for p in rows[1]}


def test_subbed_reads_both_shapes():
    """ESPN sends {"didSub": true} before and during a match, a bare true once
    it has finished. Only the dict form was handled, so _player raised on every
    completed match and the page fell back to "Couldn't reach ESPN"."""
    assert matchcentre._subbed({"didSub": True}) is True
    assert matchcentre._subbed({"didSub": False}) is False
    assert matchcentre._subbed(True) is True      # finished-match shape
    assert matchcentre._subbed(False) is False
    assert matchcentre._subbed(None) is False


def test_player_survives_a_finished_match_entry():
    entry = {"athlete": {"displayName": "Riccardo Calafiori"}, "jersey": "33",
             "starter": True, "position": {"abbreviation": "LB"},
             "formationPlace": "3", "subbedOut": True, "subbedIn": False}
    p = matchcentre._player(entry)
    assert p["subbed_off"] is True and p["subbed_on"] is False
    assert matchcentre._band(p["pos"]) == "D"


def test_opponent_standing_reads_a_string_team():
    """In the summary endpoint a standings entry's "team" is the display name
    itself, not an object. Calling .get on it raised, which killed the whole
    match centre payload for any opponent in BIG_CLUBS."""
    data = {"standings": {"groups": [{"standings": {"entries": [
        {"team": "Chelsea", "stats": [{"name": "rank", "displayValue": "4"},
                                      {"name": "points", "displayValue": "6"},
                                      {"name": "gamesPlayed", "displayValue": "3"}]},
    ]}}]}, "lastFiveGames": []}
    out = matchcentre._opponent({"opponent": "Chelsea"}, data)
    assert out["standing"] == {"rank": "4", "points": "6", "played": "3"}


def test_opponent_standing_still_reads_an_object_team():
    data = {"standings": {"groups": [{"standings": {"entries": [
        {"team": {"displayName": "Chelsea"},
         "stats": [{"name": "rank", "displayValue": "4"}]},
    ]}}]}, "lastFiveGames": []}
    assert matchcentre._opponent({"opponent": "Chelsea"}, data)["standing"]["rank"] == "4"

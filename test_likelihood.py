"""Regression tests for the transfer-likelihood ladder and the Arsenal-tab gate.

Every headline here is a real one pulled from arsenal.db, hand-labelled. The old
substring engine scored 62% of all transfer items as "Rumour" because real
phrasing ("agree £150k deal") never matched its rigid phrases, so this suite
exists to stop that silently coming back.

Run: ./venv/bin/python -m pytest test_likelihood.py -q
"""

import config

# (headline, source credibility, expected rung)
LIKELIHOOD_CASES = [
    # --- done deals -------------------------------------------------------
    ("Arsenal complete signing of Viktor Gyokeres", "medium", "Here we go"),
    ("Arsenal complete £34.5m move for first summer signing in bargain transfer",
     "high", "Here we go"),
    ("Tottenham complete £52m Van Hecke signing as De Zerbi focuses on defence",
     "high", "Here we go"),
    ("Real Madrid confirm Konate signing", "high", "Here we go"),
    ("Arsenal have signed Martin Zubimendi", "high", "Here we go"),
    ("Official: Arsenal announce signing of Kepa", "high", "Here we go"),
    ("Gyokeres passed his medical at London Colney", "high", "Here we go"),
    ("Here we go! Arsenal sign Gyokeres", "insider", "Here we go"),

    # --- concrete progress, not done --------------------------------------
    ("Arsenal agree £150k deal for Nighswonger", "medium", "Advanced"),
    ("Arsenal submit £60m bid for Sesko", "high", "Advanced"),
    ("Arsenal reach agreement with Sporting for Gyokeres", "high", "Advanced"),
    ("Arsenal set to complete signing of Eze", "high", "Advanced"),
    ("Nottingham Forest reject Manchester City's £122m bid for Elliot Anderson",
     "medium", "Advanced"),
    ("Arsenal sends official bid for coveted teenager but it is rejected",
     "low", "Advanced"),
    ("Reports mixed on Nottingham Forest £24m bid for Arsenal player",
     "medium", "Advanced"),
    ("Everton on verge of confirming surprise signing - Only medical pending",
     "medium", "Advanced"),
    ("From Brazil: Arsenal's Bruno Guimaraes deal “done” - Newcastle "
     "United delay announcement", "medium", "Advanced"),
    # infinitives are intent, not completion
    ("Arsenal given priority to complete big signing - Transfer to Gunners preferred",
     "low", "Advanced"),
    ("Palestra to Inter: Agent arrives in Milan as €50m Atalanta deal nears "
     "completion", "medium", "Advanced"),

    # --- real engagement, no money agreed ---------------------------------
    ("Arsenal open talks with Crystal Palace over Eze", "high", "Developing"),
    ("Real to resume talks with Arsenal target Vinicius Jr", "high", "Developing"),
    ("Arsenal make contact with representatives of Bouaddi", "medium", "Developing"),
    ("Real Madrid plan Olise bid - Saturday's gossip", "high", "Developing"),
    ("Arsenal considering January move for defender", "low", "Developing"),

    # --- speculation ------------------------------------------------------
    ("Arsenal linked with move for Rodri", "medium", "Rumour"),
    ("Could Vinicius Jr really be heading to Arsenal?", "high", "Rumour"),
    ("Gunners eyeing January move for defender", "low", "Rumour"),
    ("Tonali in Arsenal and Tottenham Hotspur bidding war, Newcastle want €100m",
     "medium", "Rumour"),
    ("How much is Gabriel Martinelli worth?", "medium", "Rumour"),
    ("Arsenal monitoring situation of Brazilian winger", "low", "Rumour"),

    # --- guards that regressed once and must not regress again ------------
    # Romano's sign-off is a done deal even though "to sign" follows an
    # agreement; blanket-blocking that infinitive demoted every announcement.
    ("Juventus agree deal to sign Jeff Ekhator from Genoa, here we go!",
     "insider", "Here we go"),
    ("Brighton agree deal to sign Luka Vuskovic from Tottenham, here we go! £46m",
     "insider", "Here we go"),
    # a bid only being planned or prepared is engagement, not money on the table
    ("Arsenal plan bid for Rodri", "medium", "Developing"),
    ("Arsenal prepare £70m offer for Sesko", "medium", "Developing"),
    # ... but an actual bid, however phrased, is concrete
    ("Como bid for Chelsea's Chalobah - Sunday's gossip", "high", "Advanced"),
    # hedged confirmations are not confirmations
    ("Arsenal target seemingly confirms transfer update", "low", "Advanced"),
    ("Atletico star confirms transfer intention", "medium", "Advanced"),
]


def test_likelihood_rungs():
    wrong = []
    for title, cred, expected in LIKELIHOOD_CASES:
        got, _ = config.assess_likelihood(title, cred)
        if got != expected:
            wrong.append(f"{got!r} != {expected!r}: {title}")
    assert not wrong, "\n" + "\n".join(wrong)


def test_insider_boost_caps_at_advanced():
    # an insider saying "linked" is still not a done deal
    got, by = config.assess_likelihood("Arsenal linked with Rodri", "insider")
    assert got == "Developing" and by == "rules+insider"


# --- Arsenal relevance ----------------------------------------------------
# Ambiguous squad surnames used to tag junk as Arsenal, which is what put rival
# and non-football stories on the Arsenal tab.
NOT_ARSENAL = [
    "Jesus Navas retires from football",
    "Timber merchant strikes gold",
    "Chelsea eye move for Nottingham Forest star White",
    "Man City brace for Rodri bid - Tuesday's gossip",
    "Atletico Madrid CEO on Julian Alvarez and Barcelona",
]
IS_ARSENAL = [
    "Arsenal agree deal for Sesko",
    "Gunners eyeing January move",
    "Saka signs new deal",
    "Mikel Arteta gives injury update",
    "Ben White set for return",
    "Declan Rice wins player of the month",
]


def test_arsenal_signal():
    for t in NOT_ARSENAL:
        assert config.arsenal_signal(t) is None, t
    for t in IS_ARSENAL:
        assert config.arsenal_signal(t) is not None, t


# --- women's football is out of scope entirely ----------------------------
WOMENS = [
    "Jenna Nighswonger to join Bay FC",
    "Laila Harbert joins San Diego Wave",
    "Arsenal Women beat Chelsea",
    "Alessia Russo signs new contract",
]


def test_womens_detection():
    for t in WOMENS:
        assert config.is_womens(t), t
    assert not config.is_womens("Arsenal agree deal for Sesko")


# --- player canonicalisation ----------------------------------------------
def test_canonical_player():
    assert config.canonical_player("Vinicius Jr") == "Vinicius Junior"
    assert config.canonical_player("Vinícius Júnior") == "Vinicius Junior"
    assert config.canonical_player("Bruno Guimarães") == "Bruno Guimaraes"
    assert config.canonical_player("") == ""

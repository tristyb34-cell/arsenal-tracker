"""Categorise news items into Transfers / Injuries / Match & Results / General.

Strategy:
  1. Keyword scoring (fast, free, offline). Each category scored by keyword hits.
  2. Clear winner -> use it (category_by='rules').
  3. Ambiguous (no hits, or a tie for top) -> batch the unclear titles into a
     single `claude` CLI call for smart classification (category_by='claude').

The claude CLI is free (no API key, per house rules). Batching keeps it to one
subprocess call per scrape cycle regardless of how many items are ambiguous.
"""

import json
import re
import subprocess

import config

_WORD_RE = re.compile(r"[a-z£€]+|[a-z]+-[a-z]+", re.I)


def _score(text: str):
    """Return {category: hit_count} for the keyword rules."""
    t = (text or "").lower()
    scores = {}
    for cat, keywords in config.CATEGORIES.items():
        hits = 0
        for kw in keywords:
            if kw in t:
                hits += 1
        scores[cat] = hits
    return scores


def rules_category(text: str):
    """Return (category, confident) using keyword rules.

    confident=False means the result is ambiguous and should go to claude.
    """
    scores = _score(text)
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top_cat, top_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0

    if top_score == 0:
        return config.DEFAULT_CATEGORY, False          # nothing matched
    if top_score == second_score:
        return top_cat, False                            # tie -> ambiguous
    return top_cat, True


def _claude_classify_batch(titles):
    """Classify a list of titles via one claude CLI call.

    Returns a dict {index: category}. Falls back to {} on any failure so the
    caller can default ambiguous items to General without crashing the scrape.
    """
    if not titles:
        return {}

    cats = ", ".join(c for c in config.CATEGORY_ORDER)
    numbered = "\n".join(f"{i}. {t}" for i, t in enumerate(titles))
    prompt = (
        "You are classifying Arsenal FC news headlines into exactly one category.\n"
        f"Allowed categories: {cats}.\n"
        "Definitions: Transfers = signings, rumours, contracts, fees, departures. "
        "Injuries = injuries, fitness, returns, suspensions/bans. "
        "Match & Results = fixtures, previews, results, lineups, match reports. "
        "General = anything else (club business, opinion, off-pitch).\n\n"
        "Return ONLY a JSON object mapping the item number (as a string) to its "
        'category, e.g. {"0": "Transfers", "1": "General"}. No other text.\n\n'
        f"Headlines:\n{numbered}"
    )

    try:
        proc = subprocess.run(
            [config.CLAUDE_BIN, "-p", prompt],
            capture_output=True,
            text=True,
            timeout=120,
        )
        out = proc.stdout.strip()
        # pull the first {...} block out of whatever claude returned
        m = re.search(r"\{.*\}", out, re.S)
        if not m:
            return {}
        raw = json.loads(m.group(0))
        result = {}
        for k, v in raw.items():
            try:
                idx = int(k)
            except (ValueError, TypeError):
                continue
            v = str(v).strip()
            # normalise to a known category
            for cat in config.CATEGORY_ORDER:
                if v.lower() == cat.lower():
                    result[idx] = cat
                    break
        return result
    except Exception:
        return {}


def categorise_items(items):
    """Annotate each item dict with 'category' and 'category_by'.

    `items` is a list of dicts that each already contain a 'text' key
    (title + summary) used for classification. Mutates and returns the list.
    """
    ambiguous_idx = []
    for i, it in enumerate(items):
        cat, confident = rules_category(it["text"])
        it["category"] = cat
        it["category_by"] = "rules"
        if not confident:
            ambiguous_idx.append(i)

    if ambiguous_idx:
        titles = [items[i]["text"][:200] for i in ambiguous_idx]
        claude_result = _claude_classify_batch(titles)
        for local_i, global_i in enumerate(ambiguous_idx):
            if local_i in claude_result:
                items[global_i]["category"] = claude_result[local_i]
                items[global_i]["category_by"] = "claude"
            # else: keep the rules best-guess (already set, defaults to General)

    return items

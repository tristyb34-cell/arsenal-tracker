"""Enrichment: extract the primary player from transfer items.

Feeds saga timelines, the rumour-heat leaderboard, and the done-deals ledger.
Uses one batched `claude` CLI call per scrape (free, no API key), the same
pattern as categorise.py.
"""

import json
import re
import subprocess

import config


def _claude_players_batch(titles):
    """Return {index: player_name} for transfer headlines. Empty string when
    no single clear player is named. Robust to claude returning extra prose."""
    if not titles:
        return {}

    numbered = "\n".join(f"{i}. {t}" for i, t in enumerate(titles))
    prompt = (
        "These are football (soccer) transfer headlines. For each, extract the "
        "ONE player the transfer story is primarily about.\n"
        "Rules: return the player's common full name (e.g. 'Viktor Gyokeres'). "
        "If a headline names no specific player, or is about a manager/club only, "
        'return an empty string for that number.\n\n'
        "Return ONLY a JSON object mapping the item number (as a string) to the "
        'player name, e.g. {"0": "Viktor Gyokeres", "1": ""}. No other text.\n\n'
        f"Headlines:\n{numbered}"
    )

    try:
        proc = subprocess.run(
            [config.CLAUDE_BIN, "-p", prompt],
            capture_output=True, text=True, timeout=150,
        )
        m = re.search(r"\{.*\}", proc.stdout.strip(), re.S)
        if not m:
            return {}
        raw = json.loads(m.group(0))
        out = {}
        for k, v in raw.items():
            try:
                idx = int(k)
            except (ValueError, TypeError):
                continue
            name = str(v).strip()
            # guard against junk / overly long returns
            if 0 < len(name) <= 40:
                out[idx] = name
        return out
    except Exception:
        return {}


def extract_players(items):
    """Set item['player'] on transfer items (mutates list). Non-transfers get ''."""
    transfer_idx = [i for i, it in enumerate(items) if it.get("category") == "Transfers"]
    for it in items:
        it.setdefault("player", "")

    if not transfer_idx:
        return items

    titles = [items[i]["title"][:160] for i in transfer_idx]
    result = _claude_players_batch(titles)
    for local_i, global_i in enumerate(transfer_idx):
        if local_i in result:
            items[global_i]["player"] = result[local_i]
    return items

"""One-off backfill for the 2026-08-04 transfer-quality fixes.

The scraper only ever writes NEW items, so the fixes to player canonicalisation,
the likelihood ladder, Arsenal-tab routing, women's exclusion and clustering
would otherwise apply to future items only, leaving weeks of wrong rows on the
page. This rewrites the existing rows with the same logic the scraper now uses.

Run:  ./venv/bin/python migrate_quality.py --dry-run    (report, no writes)
      ./venv/bin/python migrate_quality.py              (apply, backs up first)
"""

import shutil
import sys
import uuid
from collections import Counter

import config
import db
from categorise import rules_category
from scrape import overlap, story_tokens

DRY = "--dry-run" in sys.argv

_FEED_BY_SOURCE = {s["name"]: s for s in config.SOURCES}


def _is_arsenal_feed(source):
    src = _FEED_BY_SOURCE.get(source)
    return bool(src and src["arsenal_feed"])


def _credibility(source):
    src = _FEED_BY_SOURCE.get(source)
    return src["credibility"] if src else "medium"


def run():
    if not DRY:
        backup = config.DB_PATH + ".pre-quality-migration"
        shutil.copy2(config.DB_PATH, backup)
        print(f"backed up database -> {backup}")

    changes = Counter()
    with db.get_conn() as conn:
        rows = conn.execute(
            "SELECT id, title, summary, source, page, category, player, "
            "likelihood, cluster_id FROM items"
        ).fetchall()
        print(f"scanning {len(rows)} items")

        # --- 1. women's football: out of scope, remove entirely -------------
        womens = [r["id"] for r in rows
                  if config.is_womens(f"{r['title']}. {r['summary'] or ''}")]
        changes["womens_deleted"] = len(womens)
        if womens and not DRY:
            conn.executemany("DELETE FROM items WHERE id = ?",
                             [(i,) for i in womens])
        womens_set = set(womens)
        rows = [r for r in rows if r["id"] not in womens_set]

        # --- 1b. re-categorise where the fixed word-boundary rules are now
        #         CONFIDENT and disagree. Ambiguous items are left alone rather
        #         than firing a claude batch over thousands of old rows.
        cat = {r["id"]: r["category"] for r in rows}
        cat_updates = []
        for r in rows:
            text = f"{r['title']}. {r['summary'] or ''}"
            new_cat, confident = rules_category(text, r["title"])
            if confident and new_cat != r["category"]:
                cat[r["id"]] = new_cat
                cat_updates.append((new_cat, r["id"]))
        changes["recategorised"] = len(cat_updates)
        if cat_updates and not DRY:
            conn.executemany("UPDATE items SET category = ? WHERE id = ?",
                             cat_updates)

        # --- 2. canonical player names --------------------------------------
        player_updates = []
        canon = {}
        for r in rows:
            new = config.canonical_player(r["player"] or "")
            canon[r["id"]] = new
            if new != (r["player"] or ""):
                player_updates.append((new, r["id"]))
        changes["players_canonicalised"] = len(player_updates)
        if player_updates and not DRY:
            conn.executemany("UPDATE items SET player = ? WHERE id = ?",
                             player_updates)

        # --- 3. likelihood re-score (transfers only) ------------------------
        rung_moves = Counter()
        like_updates = []
        for r in rows:
            if cat[r["id"]] != "Transfers":
                continue
            new, by = config.assess_likelihood(r["title"], _credibility(r["source"]))
            if new != r["likelihood"]:
                rung_moves[f"{r['likelihood']} -> {new}"] += 1
                like_updates.append((new, by, r["id"]))
        changes["likelihood_rescored"] = len(like_updates)
        if like_updates and not DRY:
            conn.executemany(
                "UPDATE items SET likelihood = ?, likelihood_by = ? WHERE id = ?",
                like_updates)

        # --- 4. re-route pages using the new Arsenal gate -------------------
        # Orbit must be built from the canonicalised, women's-free data, so it
        # is computed here rather than reused from before the rewrite.
        orbit_counts = Counter()
        for r in rows:
            if cat[r["id"]] == "Transfers" and canon[r["id"]] \
                    and config.arsenal_signal(r["title"]) == "strong":
                orbit_counts[canon[r["id"]]] += 1
        orbit = {p for p, n in orbit_counts.items() if n >= config.ORBIT_MIN_MENTIONS}
        print(f"arsenal orbit: {len(orbit)} players")

        page_updates, demoted = [], []
        for r in rows:
            title = r["title"]
            signal = config.arsenal_signal(title)
            rivals = [c for c in config.tag_clubs(title) if c != "Arsenal"]
            if cat[r["id"]] == "Transfers":
                orbit_hit = (canon[r["id"]] in orbit
                             and not config.names_other_club(title))
                page = "arsenal" if (signal or orbit_hit) else "europe"
            else:
                if signal or (_is_arsenal_feed(r["source"]) and not rivals):
                    page = "arsenal"
                else:
                    page = None          # rival non-transfer: no longer wanted
            if page != r["page"]:
                if page is None:
                    demoted.append(r["id"])
                else:
                    page_updates.append((page, r["id"]))
                    if r["page"] == "arsenal":
                        changes["moved_off_arsenal"] += 1
                    else:
                        changes["moved_onto_arsenal"] += 1
        changes["page_rerouted"] = len(page_updates)
        changes["rival_noise_deleted"] = len(demoted)
        if not DRY:
            if page_updates:
                conn.executemany("UPDATE items SET page = ? WHERE id = ?",
                                 page_updates)
            if demoted:
                conn.executemany("DELETE FROM items WHERE id = ?",
                                 [(i,) for i in demoted])

        # --- 5. re-cluster the recent window --------------------------------
        # Older items are past their display shelf life, so clustering them
        # costs time and changes nothing on screen.
        demoted_set = set(demoted)
        recent = [r for r in rows
                  if r["id"] not in demoted_set
                  and (r["title"] or "")][-1500:]
        pool, cluster_updates = [], []
        for r in recent:
            player = canon[r["id"]]
            tokens = story_tokens(r["title"], player)
            best_score, best = 0.0, None
            for cand in pool:
                if player and cand["player"] and cand["player"] != player:
                    continue
                score = overlap(tokens, cand["tokens"])
                need = (config.CLUSTER_THRESHOLD if player and cand["player"] == player
                        else config.CLUSTER_THRESHOLD_NO_PLAYER)
                if score >= need and score > best_score:
                    best_score, best = score, cand
            cid = best["cluster_id"] if best else uuid.uuid4().hex
            pool.append({"cluster_id": cid, "player": player, "tokens": tokens})
            if cid != r["cluster_id"]:
                cluster_updates.append((cid, r["id"]))
        multi = sum(1 for c, n in Counter(p["cluster_id"] for p in pool).items() if n > 1)
        changes["reclustered"] = len(cluster_updates)
        print(f"clusters over {len(pool)} recent items: "
              f"{len(set(p['cluster_id'] for p in pool))} "
              f"({multi} with 2+ sources)")
        if cluster_updates and not DRY:
            conn.executemany("UPDATE items SET cluster_id = ? WHERE id = ?",
                             cluster_updates)

        if not DRY:
            conn.commit()

    print("\n--- summary ---")
    for k, v in changes.items():
        print(f"  {k:24} {v}")
    print("\n--- likelihood movements (top 12) ---")
    for move, n in rung_moves.most_common(12):
        print(f"  {n:5}  {move}")
    if DRY:
        print("\nDRY RUN: nothing written.")


if __name__ == "__main__":
    run()

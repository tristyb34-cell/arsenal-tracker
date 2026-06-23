/* Arsenal Tracker - static client renderer (Broadcast Dark).
   Fetches data/snapshot.json (exported from arsenal.db on the Mac) and renders
   the whole app client-side: Arsenal / Other Teams / All feeds, Rumour Heat, and
   per-player sagas. Hash routing keeps GitHub Pages from 404-ing on refresh. */
(function () {
  "use strict";

  var SNAPSHOT_URL = "data/snapshot.json";
  var DATA = null;
  var meta = { rungs: [], categories: [], club_codes: {}, club_crests: {}, europe_clubs_order: [] };

  // per-view filter state (reset when the page changes)
  var state = { category: "All", source: "All", q: "", rung: "", club: "All" };

  // ---------- helpers ----------
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  function attr(s) { return esc(s); }

  function timeAgo(iso) {
    if (!iso) return "";
    var dt = new Date(iso);
    if (isNaN(dt)) return "";
    var secs = Math.floor((Date.now() - dt.getTime()) / 1000);
    if (secs < 0) return "just now";
    if (secs < 3600) { var m = Math.floor(secs / 60); return m ? m + "m ago" : "just now"; }
    if (secs < 86400) return Math.floor(secs / 3600) + "h ago";
    var days = Math.floor(secs / 86400);
    if (days < 7) return days + "d ago";
    return dt.toLocaleDateString("en-GB", { day: "2-digit", month: "short" });
  }

  function slug(s) { return String(s || "").toLowerCase().replace(/ & /g, "-").replace(/ /g, "-"); }
  function rungIndex(label) { var i = meta.rungs.indexOf(label); return i; }
  function clubCode(name) { return meta.club_codes[name] || String(name || "").slice(0, 3).toUpperCase(); }
  function crestUrl(name) { return meta.club_crests[name] || ""; }
  function pluralReports(n) { return n + " report" + (n === 1 ? "" : "s"); }

  // ---------- component renderers (ports of _macros.html) ----------
  function crest(club, cls) {
    cls = cls || "";
    var logo = crestUrl(club);
    if (logo) {
      return '<span class="ct-badge has-crest ' + cls + '">' +
        '<img class="crest-img" src="' + attr(logo) + '" alt="' + attr(club) + '" loading="lazy" ' +
        'onerror="var p=this.parentElement;p.classList.remove(\'has-crest\');p.classList.add(\'club-' + slug(club) + '\');this.remove()">' +
        '<i class="ct-mono">' + esc(clubCode(club)) + '</i></span>';
    }
    return '<span class="ct-badge club-' + slug(club) + ' ' + cls + '"><i class="ct-mono">' + esc(clubCode(club)) + '</i></span>';
  }

  function meter(label) {
    if (!label) return "";
    var idx = rungIndex(label);
    var segs = "";
    for (var i = 0; i < meta.rungs.length; i++) {
      segs += '<i class="seg ' + (i <= idx ? "on s" + i : "") + '"></i>';
    }
    return '<span class="meter lvl-' + idx + '" title="Likelihood: ' + attr(label) + '">' + segs +
      '<em>' + esc(label) + '</em></span>';
  }

  function card(it, showClubs) {
    var hwg = it.best_likelihood === "Here we go" ? "1" : "0";
    var h = '<article class="card cat-' + slug(it.category) + (it.has_insider ? " insider-glow" : "") +
      '" data-hwg="' + hwg + '">';
    h += '<div class="card-meta">';
    h += '<span class="cat-pill cat-' + slug(it.category) + '">' + esc(it.category) + '</span>';
    if (it.best_likelihood) h += meter(it.best_likelihood);
    if (it.has_insider) h += '<span class="insider">⚡ insider</span>';
    if (it.source_count && it.source_count > 1) {
      h += '<span class="consensus" title="' + attr((it.sources_list || []).join(", ")) + '">📰 ' + it.source_count + ' sources</span>';
    }
    h += '<span class="time">' + esc(timeAgo(it.ts)) + '</span>';
    h += '</div>';
    h += '<h2 class="card-title"><a href="' + attr(it.url) + '" target="_blank" rel="noopener">' + esc(it.title) + '</a></h2>';
    if (it.summary) {
      var sm = it.summary.length > 200 ? esc(it.summary.slice(0, 200)) + "…" : esc(it.summary);
      h += '<p class="card-summary">' + sm + '</p>';
    }
    h += '<div class="card-foot">';
    h += '<span class="source">' + esc(it.source) + '</span>';
    if (showClubs && it.clubs) h += '<span class="clubs">' + esc(it.clubs) + '</span>';
    if (it.player) h += '<a class="player-tag" href="#/saga/' + encodeURIComponent(it.player) + '">📈 ' + esc(it.player) + '</a>';
    h += '</div></article>';
    return h;
  }

  // ---------- rail widgets ----------
  function tableWidget(snap) {
    if (!snap || !snap.table || !snap.table.length) return "";
    var rows = snap.table.slice(0, 6).map(function (r) {
      return '<tr class="' + (r.team === "Arsenal" ? "is-arsenal" : "") + '">' +
        '<td class="rk">' + esc(r.rank) + '</td><td class="tm">' + esc(r.team) + '</td>' +
        '<td class="pl">' + esc(r.played) + '</td><td class="pts">' + esc(r.points) + '</td></tr>';
    }).join("");
    var ar = snap.arsenal_row;
    if (ar && ar.rank && ar.rank > 6) {
      rows += '<tr class="is-arsenal"><td class="rk">' + esc(ar.rank) + '</td><td class="tm">Arsenal</td>' +
        '<td class="pl">' + esc(ar.played) + '</td><td class="pts">' + esc(ar.points) + '</td></tr>';
    }
    return '<section class="widget"><h3 class="widget-head">🏆 Premier League</h3>' +
      '<table class="mini-table">' + rows + '</table></section>';
  }

  function heatWidget(board, scope) {
    if (!board || !board.length) return "";
    var top = board[0].heat || 1;
    var rows = board.slice(0, 8).map(function (h) {
      var w = Math.round(h.heat / top * 100);
      return '<a class="heat-row" href="#/saga/' + encodeURIComponent(h.player) + '">' +
        '<span class="heat-name">' + esc(h.player) + '</span>' +
        '<span class="heat-bar"><i style="width:' + w + '%" class="hb-' + slug(h.best_likelihood) + '"></i></span>' +
        '<span class="heat-n">' + esc(h.mentions) + '</span></a>';
    }).join("");
    return '<section class="widget"><h3 class="widget-head">' +
      '<a class="widget-link" href="#/heat?scope=' + scope + '">🔥 Rumour Heat <span class="widget-more" aria-hidden="true">›</span></a></h3>' +
      rows + '</section>';
  }

  function dealsWidget(deals) {
    if (!deals || !deals.length) return "";
    var rows = deals.map(function (d) {
      return '<a class="deal-row" href="' + attr(d.url) + '" target="_blank" rel="noopener">' +
        '<b>' + esc(d.player) + '</b><span>' + esc((d.title || "").slice(0, 64)) + '</span></a>';
    }).join("");
    return '<section class="widget"><h3 class="widget-head">✅ Done Deals</h3>' + rows + '</section>';
  }

  function injuriesWidget(inj) {
    if (!inj || !inj.length) return "";
    var rows = inj.map(function (i) {
      return '<a class="inj-row" href="' + attr(i.url) + '" target="_blank" rel="noopener">' +
        (i.player ? '<b>' + esc(i.player) + '</b>' : "") +
        '<span>' + esc((i.title || "").slice(0, 70)) + '</span></a>';
    }).join("");
    return '<section class="widget"><h3 class="widget-head">🩹 Injury Room</h3>' + rows + '</section>';
  }

  // ---------- live football strip ----------
  function livestrip(snap) {
    if (!snap) { setLivestrip(""); return; }
    var matchday = !!snap.is_matchday;
    var h = '<div class="livestrip ' + (matchday ? "matchday" : "") + '">';
    var nm = snap.next_match;
    if (nm) {
      h += '<div class="ls-block ls-next"><span class="ls-label">' + (matchday ? "TODAY" : "NEXT") + '</span>' +
        '<span class="ls-main">' + esc(nm.home_short || nm.home) + ' <i>v</i> ' + esc(nm.away_short || nm.away) + '</span>' +
        '<span class="ls-sub" data-countdown="' + attr(nm.kickoff) + '">' + esc((nm.kickoff || "").slice(0, 16).replace("T", " ")) + '</span></div>';
    } else {
      h += '<div class="ls-block ls-next"><span class="ls-label">NEXT</span>' +
        '<span class="ls-main">Fixtures TBA</span><span class="ls-sub">off-season</span></div>';
    }
    var lr = snap.last_result;
    if (lr) {
      h += '<div class="ls-block"><span class="ls-label">LAST</span>' +
        '<span class="ls-main">' + esc(lr.home_short || lr.home) + ' ' + esc(lr.home_goals) + '–' + esc(lr.away_goals) + ' ' + esc(lr.away_short || lr.away) + '</span></div>';
    }
    if (snap.form && snap.form.length) {
      var f = snap.form.map(function (r) { return '<i class="f f-' + esc(String(r).toLowerCase()) + '">' + esc(r) + '</i>'; }).join("");
      h += '<div class="ls-block"><span class="ls-label">FORM</span><span class="ls-form">' + f + '</span></div>';
    }
    var ar = snap.arsenal_row;
    if (ar) {
      h += '<div class="ls-block"><span class="ls-label">TABLE</span><span class="ls-main">#' + esc(ar.rank) + ' · ' + esc(ar.points) + 'pts</span></div>';
    }
    h += '</div>';
    setLivestrip(h);
    document.getElementById("topbar").classList.toggle("is-matchday", matchday);
    startCountdown();
  }

  function setLivestrip(html) { document.getElementById("livestrip").innerHTML = html; }

  // ---------- filtering ----------
  function applyFilters(clusters) {
    var q = state.q.trim().toLowerCase();
    var minRung = state.rung ? rungIndex(state.rung) : -99;
    return clusters.filter(function (c) {
      if (state.category !== "All" && c.category !== state.category) return false;
      if (state.source !== "All") {
        var inList = (c.sources_list || []).indexOf(state.source) >= 0 || c.source === state.source;
        if (!inList) return false;
      }
      if (state.rung && rungIndex(c.best_likelihood) < minRung) return false;
      if (q) {
        var hay = (c.title + " " + (c.summary || "")).toLowerCase();
        if (hay.indexOf(q) < 0) return false;
      }
      return true;
    });
  }

  function pickHero(clusters) {
    var best = null, bestScore = -1;
    clusters.slice(0, 40).forEach(function (c) {
      var score = (c.source_count || 1) * 3 + Math.max(rungIndex(c.best_likelihood), 0) * 2 + (c.has_insider ? 2 : 0);
      if (score > bestScore) { best = c; bestScore = score; }
    });
    return best;
  }

  function categoryCounts(clusters) {
    var counts = {};
    clusters.forEach(function (c) { counts[c.category] = (counts[c.category] || 0) + 1; });
    return counts;
  }

  // ---------- views ----------
  function setRail(html) { document.getElementById("rail").innerHTML = html; }
  function setView(html) { document.getElementById("view").innerHTML = html; }
  function announce(msg) { var el = document.getElementById("search-status"); if (el) el.textContent = msg; }
  function announceCount(n) { announce(n ? n + " stories" : "No stories match"); }

  function renderFeedPage(page) {
    var bundle = DATA[page];
    var clusters = bundle.clusters;
    var counts = categoryCounts(clusters);
    var total = clusters.length;
    var noFilter = state.category === "All" && !state.q && !state.rung && state.source === "All";
    var filtered = applyFilters(clusters);
    var hero = noFilter ? pickHero(clusters) : null;
    var feed = hero ? filtered.filter(function (c) { return c.url_hash !== hero.url_hash; }) : filtered;

    var h = "";

    // morning brief (Arsenal-flavoured, shown on arsenal + all)
    if (DATA.brief && DATA.brief.text) {
      h += '<section class="brief" id="brief"><div class="brief-head">📋 Morning Brief ' +
        '<span>' + esc(timeAgo(DATA.brief.generated_at)) + '</span></div><p>' + esc(DATA.brief.text) + '</p></section>';
    }

    // hero
    if (hero) {
      var hwg = hero.best_likelihood === "Here we go" ? "1" : "0";
      h += '<a class="hero" href="' + attr(hero.url) + '" target="_blank" rel="noopener" data-hwg="' + hwg + '">' +
        '<span class="hero-tag">TOP STORY</span><div class="hero-meta">' +
        '<span class="cat-pill cat-' + slug(hero.category) + '">' + esc(hero.category) + '</span>' +
        (hero.best_likelihood ? meter(hero.best_likelihood) : "") +
        (hero.has_insider ? '<span class="insider">⚡ insider</span>' : "") +
        (hero.source_count > 1 ? '<span class="consensus">📰 ' + hero.source_count + ' sources</span>' : "") +
        '</div><h1 class="hero-title">' + esc(hero.title) + '</h1>' +
        '<span class="hero-foot">' + esc(hero.source) + ' · ' + esc(timeAgo(hero.ts)) + '</span></a>';
    }

    // tabs
    h += '<nav class="tabs" id="tabs" aria-label="Categories">';
    var tabList = [["All", total]];
    meta.categories.forEach(function (c) { tabList.push([c, counts[c] || 0]); });
    tabList.forEach(function (t) {
      h += '<button type="button" class="tab' + (t[0] === state.category ? " active" : "") +
        '" data-cat="' + attr(t[0]) + '" aria-pressed="' + (t[0] === state.category) + '">' +
        esc(t[0]) + ' <span class="badge">' + t[1] + '</span></button>';
    });
    h += '<button type="button" class="tab rung-toggle' + (state.rung ? " active" : "") +
      '" id="rung-toggle" aria-pressed="' + (!!state.rung) + '">🎯 Advanced+</button>';
    h += '</nav>';

    // filters
    h += '<div class="filters"><form class="filter-form" id="filter-form" role="search">' +
      '<label class="sr-only" for="search-input">Search ' + esc(page === "all" ? "all news" : "Arsenal") + '</label>' +
      '<input class="search" type="search" id="search-input" placeholder="Search ' + (page === "all" ? "all news" : "Arsenal") + '…" value="' + attr(state.q) + '">' +
      '<label class="sr-only" for="source-select">Filter by source</label>' +
      '<select id="source-select"><option value="All">All sources</option>';
    bundle.sources.forEach(function (s) {
      h += '<option value="' + attr(s) + '"' + (s === state.source ? " selected" : "") + '>' + esc(s) + '</option>';
    });
    h += '</select>';
    if (state.q || state.source !== "All" || state.rung) h += '<button type="button" class="clear" id="clear-filters">Clear</button>';
    h += '</form></div>';

    // feed
    h += '<section class="feed" id="feed">' + renderFeedList(feed) + '</section>';

    setView(h);

    // rail
    var heat = DATA.heat[page] || [];
    var deals = DATA.deals[page] || [];
    var rail = "";
    if (page === "arsenal" || page === "all") rail += tableWidget(DATA.football);
    rail += heatWidget(heat, page);
    rail += dealsWidget(deals);
    if (page === "arsenal" || page === "all") rail += injuriesWidget(DATA.injuries);
    setRail(rail);

    bindFeedControls(page);
    staggerCards();
    maybeConfetti();
    announceCount(feed.length);
  }

  function renderFeedList(feed) {
    if (!feed.length) return '<p class="empty">No stories match. Try clearing filters.</p>';
    return feed.map(function (c) { return card(c, false); }).join("");
  }

  function renderEurope() {
    var clusters = DATA.europe.clusters;
    var counts = DATA.europe.club_counts || {};
    var flat = state.club !== "All" || !!state.q || !!state.rung;
    var filtered = clusters.filter(function (c) {
      if (state.club !== "All") {
        var inClub = (c.clubs || "").split(",").map(function (x) { return x.trim(); }).indexOf(state.club) >= 0;
        if (!inClub) return false;
      }
      if (state.rung && rungIndex(c.best_likelihood) < rungIndex(state.rung)) return false;
      if (state.q) {
        var hay = (c.title + " " + (c.summary || "")).toLowerCase();
        if (hay.indexOf(state.q.trim().toLowerCase()) < 0) return false;
      }
      return true;
    });

    var h = '<div class="europe-head"><h2>Transfer Desk · Europe</h2>' +
      '<p>Rival and European transfer news only. Each story carries a likelihood rung from rumour to here-we-go.</p></div>';

    // crest wall
    h += '<div class="crestwall"><button type="button" class="crest-tile' + (state.club === "All" ? " active" : "") +
      '" data-club="All"><span class="ct-badge ct-all">ALL</span><span class="ct-name">All clubs</span></button>';
    meta.europe_clubs_order.forEach(function (c) {
      var n = counts[c] || 0;
      if (!n) return;
      h += '<button type="button" class="crest-tile' + (state.club === c ? " active" : "") + '" data-club="' + attr(c) + '">' +
        crest(c) + '<span class="ct-name">' + esc(c) + '</span><span class="ct-n">' + n + '</span></button>';
    });
    h += '</div>';

    // filters
    h += '<div class="filters"><form class="filter-form" id="filter-form" role="search">' +
      '<label class="sr-only" for="search-input">Search transfers</label>' +
      '<input class="search" type="search" id="search-input" placeholder="Search transfers…" value="' + attr(state.q) + '">' +
      '<button type="button" class="tab rung-toggle' + (state.rung ? " active" : "") + '" id="rung-toggle" aria-pressed="' + (!!state.rung) + '">🎯 Advanced+</button>';
    if (state.q || state.club !== "All" || state.rung) h += '<button type="button" class="clear" id="clear-filters">Clear</button>';
    h += '</form></div>';

    // feed: grouped or flat
    h += '<section class="feed" id="feed">';
    if (flat) {
      h += filtered.length ? filtered.map(function (c) { return card(c, true); }).join("")
        : '<p class="empty">No transfers match. Try clearing filters.</p>';
    } else {
      var groups = {};
      meta.europe_clubs_order.forEach(function (c) { groups[c] = []; });
      filtered.forEach(function (it) {
        var primary = (it.clubs || "").split(",")[0].trim();
        if (groups[primary]) groups[primary].push(it);
      });
      var any = false;
      meta.europe_clubs_order.forEach(function (club) {
        var items = groups[club];
        if (!items || !items.length) return;
        any = true;
        h += '<div class="club-section" id="club-' + slug(club) + '">' +
          '<h3 class="club-head">' + crest(club, "small") + esc(club) + ' <span class="count">' + items.length + '</span></h3>' +
          items.map(function (c) { return card(c, true); }).join("") + '</div>';
      });
      if (!any) h += '<p class="empty">No European transfer stories yet.</p>';
    }
    h += '</section>';

    setView(h);
    setRail(heatWidget(DATA.heat.europe, "europe") + dealsWidget(DATA.deals.europe));
    bindEuropeControls();
    staggerCards();
    announce(filtered.length ? filtered.length + " transfers" : "No transfers match");
  }

  function renderHeat(scope) {
    scope = (scope === "europe" || scope === "all") ? scope : "arsenal";
    state.heatScope = scope;
    var sort = state.heatSort || "heat";
    var board = (DATA.heat[scope] || []).slice();
    if (sort === "latest") board.sort(function (a, b) { return (b.last_ts || "").localeCompare(a.last_ts || ""); });
    var title = { arsenal: "Arsenal", europe: "Other Teams", all: "All" }[scope];
    var top = board.length ? board[0].heat : 1;

    var h = '<a class="back" href="#/">← Back to feed</a>' +
      '<div class="saga-head"><h1>🔥 Rumour Heat</h1>' +
      '<p>' + board.length + ' player' + (board.length === 1 ? "" : "s") + ' in the ' + esc(title) +
      ' transfer chatter over the last fortnight. Pick anyone to follow their saga.</p></div>';

    h += '<div class="heat-controls"><nav class="heat-scope" aria-label="Heat scope">' +
      '<button type="button" class="chip' + (scope === "arsenal" ? " active" : "") + '" data-scope="arsenal">Arsenal</button>' +
      '<button type="button" class="chip' + (scope === "europe" ? " active" : "") + '" data-scope="europe">Other Teams</button>' +
      '</nav><nav class="heat-sort" aria-label="Sort order"><span class="sort-label" aria-hidden="true">Sort</span>' +
      '<button type="button" class="chip' + (sort === "heat" ? " active" : "") + '" data-sort="heat"><span aria-hidden="true">🔥 </span>Heat</button>' +
      '<button type="button" class="chip' + (sort === "latest" ? " active" : "") + '" data-sort="latest"><span aria-hidden="true">🕑 </span>Latest</button>' +
      '</nav></div>';

    if (!board.length) {
      h += '<p class="empty">No transfer chatter tracked yet for this scope.</p>';
    } else {
      h += '<ol class="heat-list">' + board.map(function (hh, i) {
        var w = Math.round(hh.heat / top * 100);
        var mo = hh.momentum === "rising" ? '<span aria-hidden="true">▲ </span>rising'
          : hh.momentum === "cooling" ? '<span aria-hidden="true">▼ </span>cooling'
            : '<span aria-hidden="true">▬ </span>steady';
        var latest = hh.latest_title ? '<p class="hc-latest">' +
          esc(hh.latest_title.length > 120 ? hh.latest_title.slice(0, 120) + "…" : hh.latest_title) + '</p>' : "";
        return '<li><a class="heat-card" href="#/saga/' + encodeURIComponent(hh.player) + '" aria-label="' +
          attr(hh.player + " saga, " + pluralReports(hh.mentions)) + '"><div class="hc-rank">' + (i + 1) + '</div>' +
          '<div class="hc-body"><div class="hc-top"><span class="hc-name">' + esc(hh.player) + '</span>' +
          (hh.is_new ? '<span class="hc-new">NEW</span>' : "") +
          '<span class="hc-momentum mo-' + hh.momentum + '">' + mo + '</span>' +
          (hh.club ? '<span class="hc-club">' + esc(hh.club) + '</span>' : "") + '</div>' +
          '<div class="hc-bar" aria-hidden="true"><i style="width:' + w + '%" class="hb-' + slug(hh.best_likelihood) + '"></i></div>' +
          latest + '<div class="hc-meta">' + meter(hh.best_likelihood) +
          '<span class="hc-n">' + pluralReports(hh.mentions) + '</span>' +
          (hh.latest_source ? '<span class="source">' + esc(hh.latest_source) + '</span>' : "") +
          (hh.last_ts ? '<span class="time">' + esc(timeAgo(hh.last_ts)) + '</span>' : "") +
          '</div></div></a></li>';
      }).join("") + '</ol>';
    }

    setView(h);
    setRail('<section class="widget"><h2 class="widget-head">How heat works</h2>' +
      '<p class="rail-note">Heat = how often a player is linked, weighted by how credible the latest reports are. The bar colour tracks the best likelihood reached:</p>' +
      '<ul class="heat-legend"><li><i class="lg hb-rumour"></i> Rumour</li><li><i class="lg hb-developing"></i> Developing</li>' +
      '<li><i class="lg hb-advanced"></i> Advanced</li><li><i class="lg hb-here-we-go"></i> Here we go</li></ul>' +
      '<p class="rail-note">Rising / cooling compares the last 3 days against the 3 before. <b>NEW</b> means first linked in the last 48 hours.</p></section>');

    document.querySelectorAll(".heat-scope .chip").forEach(function (b) {
      b.addEventListener("click", function () { go("#/heat?scope=" + b.getAttribute("data-scope")); });
    });
    document.querySelectorAll(".heat-sort .chip").forEach(function (b) {
      b.addEventListener("click", function () { state.heatSort = b.getAttribute("data-sort"); renderHeat(scope); });
    });
  }

  function renderSaga(player) {
    var rows = DATA.sagas[player] || [];
    var others = Object.keys(DATA.sagas).sort(function (a, b) {
      return (DATA.sagas[b].length) - (DATA.sagas[a].length);
    }).filter(function (p) { return p !== player; }).slice(0, 14);

    var h = '<a class="back" href="#/">← Back to feed</a>' +
      '<div class="saga-head"><h1>📈 ' + esc(player) + '</h1>' +
      '<p>' + rows.length + ' report' + (rows.length === 1 ? "" : "s") + ' tracked. Watch the likelihood climb (or stall) over time.</p></div>';

    if (!rows.length) {
      h += '<p class="empty">No saga data for this player.</p>';
    } else {
      h += '<div class="timeline">' + rows.map(function (r) {
        return '<div class="tl-row rung-' + rungIndex(r.likelihood) + '"><div class="tl-dot"></div>' +
          '<div class="tl-body"><div class="tl-meta">' + meter(r.likelihood) +
          (r.credibility === "insider" ? '<span class="insider">⚡ insider</span>' : "") +
          '<span class="time">' + esc(timeAgo(r.ts)) + '</span></div>' +
          '<a class="tl-title" href="' + attr(r.url) + '" target="_blank" rel="noopener">' + esc(r.title) + '</a>' +
          '<span class="source">' + esc(r.source) + '</span></div></div>';
      }).join("") + '</div>';
    }

    setView(h);
    setRail('<section class="widget"><h3 class="widget-head">📈 Other Sagas</h3>' +
      others.map(function (p) {
        return '<a class="deal-row" href="#/saga/' + encodeURIComponent(p) + '"><b>' + esc(p) + '</b></a>';
      }).join("") + '</section>');
  }

  // ---------- control binding ----------
  function bindFeedControls(page) {
    document.querySelectorAll('#tabs .tab[data-cat]').forEach(function (b) {
      b.addEventListener("click", function () { state.category = b.getAttribute("data-cat"); renderFeedPage(page); });
    });
    var rt = document.getElementById("rung-toggle");
    if (rt) rt.addEventListener("click", function () { state.rung = state.rung ? "" : "Advanced"; renderFeedPage(page); });
    var sel = document.getElementById("source-select");
    if (sel) sel.addEventListener("change", function () { state.source = sel.value; renderFeedPage(page); });
    var clr = document.getElementById("clear-filters");
    if (clr) clr.addEventListener("click", function () { state.q = ""; state.source = "All"; state.rung = ""; renderFeedPage(page); });
    bindSearch(function () {
      var feed = liveFeed(page);
      var el = document.getElementById("feed");
      if (el) el.innerHTML = renderFeedList(feed);
      staggerCards();
      announceCount(feed.length);
    });
  }

  function liveFeed(page) {
    var clusters = DATA[page].clusters;
    var noFilter = state.category === "All" && !state.q && !state.rung && state.source === "All";
    var hero = noFilter ? pickHero(clusters) : null;
    var filtered = applyFilters(clusters);
    return hero ? filtered.filter(function (c) { return c.url_hash !== hero.url_hash; }) : filtered;
  }

  function bindEuropeControls() {
    document.querySelectorAll('.crest-tile[data-club]').forEach(function (b) {
      b.addEventListener("click", function () { state.club = b.getAttribute("data-club"); renderEurope(); });
    });
    var rt = document.getElementById("rung-toggle");
    if (rt) rt.addEventListener("click", function () { state.rung = state.rung ? "" : "Advanced"; renderEurope(); });
    var clr = document.getElementById("clear-filters");
    if (clr) clr.addEventListener("click", function () { state.q = ""; state.club = "All"; state.rung = ""; renderEurope(); });
    bindSearch(renderEurope);
  }

  var searchTimer = null;
  function bindSearch(onChange) {
    var inp = document.getElementById("search-input");
    if (!inp) return;
    inp.addEventListener("input", function () {
      state.q = inp.value;
      clearTimeout(searchTimer);
      searchTimer = setTimeout(onChange, 180);
    });
  }

  // ---------- effects ----------
  function staggerCards() {
    document.querySelectorAll(".feed .card").forEach(function (c, i) {
      c.style.animationDelay = Math.min(i * 35, 600) + "ms";
    });
  }

  var countdownTimer = null;
  function startCountdown() {
    clearInterval(countdownTimer);
    var cd = document.querySelector("[data-countdown]");
    if (!cd) return;
    var when = new Date(cd.getAttribute("data-countdown")).getTime();
    if (isNaN(when)) return;
    function fmt(t) {
      var diff = when - Date.now();
      if (diff <= 0) return "now";
      var d = Math.floor(diff / 86400000), hh = Math.floor((diff % 86400000) / 3600000), m = Math.floor((diff % 3600000) / 60000);
      if (d > 0) return "in " + d + "d " + hh + "h";
      if (hh > 0) return "in " + hh + "h " + m + "m";
      return "in " + m + "m";
    }
    cd.textContent = fmt();
    countdownTimer = setInterval(function () { cd.textContent = fmt(); }, 30000);
  }

  function maybeConfetti() {
    var hwg = document.querySelector('.feed [data-hwg="1"], .hero[data-hwg="1"]');
    if (hwg && !sessionStorage.getItem("hwg-celebrated")) {
      sessionStorage.setItem("hwg-celebrated", "1");
      setTimeout(confetti, 500);
    }
  }
  function confetti() {
    var canvas = document.getElementById("confetti");
    if (!canvas) return;
    canvas.style.display = "block";
    var ctx = canvas.getContext("2d");
    canvas.width = innerWidth; canvas.height = innerHeight;
    var colors = ["#ef0107", "#ffffff", "#e0a93a", "#1f9e57"], bits = [];
    for (var i = 0; i < 140; i++) {
      bits.push({ x: Math.random() * canvas.width, y: -20 - Math.random() * canvas.height * 0.5,
        r: 4 + Math.random() * 6, c: colors[(Math.random() * colors.length) | 0],
        vy: 2 + Math.random() * 4, vx: -2 + Math.random() * 4, rot: Math.random() * 6, vr: -0.2 + Math.random() * 0.4 });
    }
    var frames = 0;
    (function draw() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      bits.forEach(function (b) {
        b.x += b.vx; b.y += b.vy; b.rot += b.vr;
        ctx.save(); ctx.translate(b.x, b.y); ctx.rotate(b.rot);
        ctx.fillStyle = b.c; ctx.fillRect(-b.r / 2, -b.r / 2, b.r, b.r * 0.6); ctx.restore();
      });
      if (++frames < 160) requestAnimationFrame(draw); else canvas.style.display = "none";
    })();
  }

  // ---------- header / chrome ----------
  function renderChrome() {
    var ins = (DATA.insiders || []).map(function (i) {
      return '<span class="ins-watch" title="' + attr(i.name + " last posted") + '"><i class="dot"></i>' +
        esc(i.name.split(" ")[0]) + ' ' + esc(i.last ? timeAgo(i.last) : "—") + '</span>';
    }).join("");
    document.getElementById("insiders").innerHTML = ins;
    document.getElementById("last-scrape").textContent = "⟳ " + (DATA.last_scrape ? timeAgo(DATA.last_scrape) : "never");
    livestrip(DATA.football);
  }

  function setActiveNav(page) {
    document.querySelectorAll(".pagenav .pagelink, .bottomnav a").forEach(function (a) {
      a.classList.toggle("active", a.getAttribute("data-page") === page);
    });
  }

  // ---------- routing ----------
  function parseHash() {
    var hash = location.hash.replace(/^#/, "") || "/";
    var qs = "";
    var qi = hash.indexOf("?");
    if (qi >= 0) { qs = hash.slice(qi + 1); hash = hash.slice(0, qi); }
    var parts = hash.split("/").filter(Boolean); // ["saga","Name"] etc
    var params = {};
    qs.split("&").forEach(function (kv) { if (!kv) return; var p = kv.split("="); params[p[0]] = decodeURIComponent(p[1] || ""); });
    return { parts: parts, params: params };
  }

  function resetFilters() { state.category = "All"; state.source = "All"; state.q = ""; state.rung = ""; state.club = "All"; }

  function route(opts) {
    if (!DATA) return;
    var r = parseHash();
    var head = r.parts[0] || "";

    if (head === "europe") { resetFilters(); setActiveNav("europe"); renderEurope(); }
    else if (head === "all") { resetFilters(); setActiveNav("all"); renderFeedPage("all"); }
    else if (head === "heat") { setActiveNav("heat"); renderHeat(r.params.scope); }
    else if (head === "saga") { setActiveNav("arsenal"); renderSaga(decodeURIComponent(r.parts.slice(1).join("/"))); }
    else { resetFilters(); setActiveNav("arsenal"); renderFeedPage("arsenal"); }

    // Move focus to the new view on genuine navigation only, so a screen reader
    // announces the new page. NOT on the 5-min background refresh (would hijack
    // the user's place mid-read).
    if (opts && opts.focus) {
      var v = document.getElementById("view");
      if (v) v.focus();
    }
  }

  function go(hash) { if (location.hash === hash) route(); else location.hash = hash; }

  // ---------- boot ----------
  function showError(msg) {
    setView('<p class="empty">' + esc(msg) + '</p>');
  }

  function load() {
    fetch(SNAPSHOT_URL, { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (data) {
        DATA = data;
        meta = data.meta || meta;
        renderChrome();
        route();
      })
      .catch(function (e) {
        if (DATA) return; // already have something rendered
        showError("Couldn't load the latest data (" + e.message + "). If you're offline, reconnect and pull to refresh.");
      });
  }

  window.addEventListener("hashchange", function () { window.scrollTo(0, 0); route({ focus: true }); });

  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("sw.js").catch(function () {});
  }

  // refresh data every 5 minutes while the app is open (no full page reload)
  setInterval(load, 5 * 60 * 1000);

  load();
})();

/* Arsenal Tracker: client renderer (plain JS, no build step).

   One codebase for both front doors. On GitHub Pages it reads the static
   data/snapshot.json pushed after each scrape; on the Mac, Flask serves the
   same files and builds that JSON live from arsenal.db. Hash routes:
     #/                 Home: the match, recent results, the table, top stories
     #/matches          every Arsenal game, every competition
     #/match/<id>       match centre (?tab=timeline|lineups|stats|preview)
     #/news[/others|/all], #/heat, #/saga/<player>
     #/table            Premier League (and Champions League league phase)

   While a match is on, the phone also polls ESPN's summary directly every 30
   seconds (ESPN serves `access-control-allow-origin: *`) because the published
   snapshot only moves every half hour. parseSummary() below mirrors the
   shaping in matchcentre.py: change one, change the other. */
(function () {
  "use strict";

  var SNAPSHOT_URL = "data/snapshot.json";
  var ESPN_SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/soccer/{league}/summary?event={id}";
  var TZ = "Africa/Johannesburg";
  var TEAM = "Arsenal";

  var DATA = null;
  var meta = { rungs: [], categories: [], club_codes: {}, club_crests: {}, europe_clubs_order: [] };
  var MATCHES = {};   // id -> payload fetched from data/match/<id>.json (null = not available)
  var LIVE = {};      // id -> payload parsed straight from ESPN while the match is on
  var PENDING = {};   // match files being fetched
  var SAGAS = null;
  var oppOpen = null; // remembers the opponent XI toggle across live re-renders
  var currentPage = "";
  var briefOpen = false;
  var searchShown = false;
  function searchOpen() { return searchShown || !!state.q || state.source !== "All"; }
  var state = { category: "All", source: "All", q: "", rung: "", club: "All", heatSort: "heat" };
  var lastView = "";

  // ---------- helpers ----------
  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }
  var attr = esc;
  function slug(s) { return String(s || "").toLowerCase().replace(/ & /g, "-").replace(/ /g, "-"); }
  function rungIndex(label) { return meta.rungs.indexOf(label); }
  function plural(n, word) { return n + " " + word + (n === 1 ? "" : "s"); }
  function el(id) { return document.getElementById(id); }

  function timeAgo(iso) {
    var t = Date.parse(iso || "");
    if (isNaN(t)) return "";
    var secs = Math.floor((Date.now() - t) / 1000);
    if (secs < 60) return "just now";
    if (secs < 3600) return Math.floor(secs / 60) + "m ago";
    if (secs < 86400) return Math.floor(secs / 3600) + "h ago";
    var days = Math.floor(secs / 86400);
    if (days < 7) return days + "d ago";
    return new Date(t).toLocaleDateString("en-GB", { timeZone: TZ, day: "numeric", month: "short" });
  }

  // ---------- dates: ESPN is UTC, Tristan watches from Johannesburg ----------
  function fmt(iso, opts) {
    var d = new Date(iso);
    if (isNaN(d)) return "";
    opts.timeZone = TZ;
    return d.toLocaleString("en-GB", opts);
  }
  function koTime(iso) { return fmt(iso, { hour: "2-digit", minute: "2-digit", hour12: false }); }
  function koDay(iso) { return fmt(iso, { weekday: "short", day: "numeric", month: "short" }); }
  function koDayNum(iso) { return fmt(iso, { day: "numeric" }); }
  function koWeekday(iso) { return fmt(iso, { weekday: "short" }); }
  function koMonth(iso) { return fmt(iso, { month: "long", year: "numeric" }); }
  function localDate(t) { return fmt(new Date(t).toISOString(), { year: "numeric", month: "2-digit", day: "2-digit" }); }
  function dayWord(iso) {
    var t = Date.parse(iso);
    if (localDate(t) === localDate(Date.now())) return "Today";
    if (localDate(t) === localDate(Date.now() + 86400000)) return "Tomorrow";
    return koDay(iso);
  }
  function countdown(iso) {
    var diff = Date.parse(iso) - Date.now();
    if (isNaN(diff)) return "";
    if (diff <= 0) return "Kick-off";
    var d = Math.floor(diff / 86400000), h = Math.floor((diff % 86400000) / 3600000), m = Math.floor((diff % 3600000) / 60000);
    if (d >= 2) return "in " + d + " days";
    if (d > 0) return "in " + d + "d " + h + "h";
    if (h > 0) return "in " + h + "h " + m + "m";
    return "in " + Math.max(m, 1) + "m";
  }

  // ---------- icons: one stroked set, 24px grid ----------
  function svg(body, cls) {
    return '<svg class="icon' + (cls ? " " + cls : "") + '" viewBox="0 0 24 24" aria-hidden="true">' + body + '</svg>';
  }
  var ICON = {
    back: svg('<path d="M15 5l-7 7 7 7"/>'),
    chev: svg('<path d="M6 9l6 6 6-6"/>', "chev"),
    ball: svg('<circle cx="12" cy="12" r="9"/><path d="M12 7.6l4.2 3-1.6 4.9H9.4l-1.6-4.9z"/><path d="M12 7.6V3.1M16.2 10.6l4.3-1.4M14.6 15.5l2.6 3.7M9.4 15.5l-2.6 3.7M7.8 10.6 3.5 9.2"/>'),
    sub: svg('<path d="M7 20V7M3.5 10.5 7 7l3.5 3.5"/><path d="M17 4v13M13.5 13.5 17 17l3.5-3.5"/>'),
    up: svg('<path d="M12 19V5M6 11l6-6 6 6"/>'),
    down: svg('<path d="M12 5v14M6 13l6 6 6-6"/>'),
    miss: svg('<circle cx="12" cy="12" r="9"/><path d="M8 8l8 8"/>')
  };

  // ---------- crests: ESPN logos, dark-UI variant first, monogram last ----------
  function logoSrc(url, px, dark) {
    var m = /\/i\/teamlogos\/soccer\/500\/(\d+)\.png/.exec(url || "");
    if (!m) return url || "";
    return "https://a.espncdn.com/combiner/i?img=/i/teamlogos/soccer/" + (dark ? "500-dark" : "500") +
      "/" + m[1] + ".png&w=" + (px * 2) + "&h=" + (px * 2);
  }
  function crest(url, px, mono, cls) {
    cls = "crest" + (cls ? " " + cls : "");
    if (!url) return '<i class="crest-mono ' + cls + '" aria-hidden="true">' + esc(mono || "") + '</i>';
    return '<img class="' + cls + '" src="' + attr(logoSrc(url, px, true)) + '" data-fallback="' +
      attr(logoSrc(url, px, false)) + '" data-mono="' + attr(mono || "") + '" width="' + px + '" height="' + px +
      '" alt="" loading="lazy" decoding="async" onerror="__crest(this)">';
  }
  // ESPN has no dark variant for some clubs (Fleetwood 404s), so step down
  // to the standard logo, then to a monogram, rather than a broken image.
  window.__crest = function (img) {
    var next = img.getAttribute("data-fallback");
    if (next) { img.removeAttribute("data-fallback"); img.src = next; return; }
    var i = document.createElement("i");
    i.className = img.className + " crest-mono";
    i.textContent = img.getAttribute("data-mono") || "";
    i.setAttribute("aria-hidden", "true");
    img.replaceWith(i);
  };
  function clubCrest(club, px) {
    var code = meta.club_codes[club] || String(club || "").slice(0, 3).toUpperCase();
    return crest(meta.club_crests[club] || "", px, code);
  }
  function compBadge(m) {
    return '<span class="comp comp-' + esc(m.comp_slug || "pl") + '" title="' + attr(m.comp || "") + '">' + esc(m.comp_code || "") + '</span>';
  }
  function resChip(r) {
    if (!r) return "";
    var word = { W: "Won", D: "Drew", L: "Lost" }[r] || r;
    return '<span class="res res-' + String(r).toLowerCase() + '"><span aria-hidden="true">' + esc(r) + '</span><span class="sr-only">' + word + '</span></span>';
  }

  // ---------- football data ----------
  function football() { return (DATA && DATA.football) || {}; }
  function allEvents() {
    var f = football(), seen = {}, out = [];
    [f.live_match].concat(f.results || [], f.fixtures || [], [f.next_match, f.last_result]).forEach(function (e) {
      if (e && !seen[e.id]) { seen[e.id] = 1; out.push(e); }
    });
    return out;
  }
  function findEvent(id) {
    var all = allEvents();
    for (var i = 0; i < all.length; i++) if (String(all[i].id) === String(id)) return all[i];
    return null;
  }
  function payloadFor(id) {
    id = String(id);
    return LIVE[id] ? mergeLive(basePayload(id), LIVE[id]) : basePayload(id);
  }
  function basePayload(id) { return ((DATA && DATA.matches) || {})[id] || MATCHES[id] || null; }
  function mergeLive(base, live) {
    var out = {};
    var k;
    for (k in (base || {})) out[k] = base[k];
    for (k in live) if (live[k] && (!Array.isArray(live[k]) || live[k].length)) out[k] = live[k];
    return out;
  }

  // The freshest of three sources wins: the fixtures cache, the exported
  // match centre, and (while a game is on) ESPN polled from this phone.
  function statusOf(ev) {
    var cands = [{
      state: ev.live ? "in" : (ev.finished ? "post" : "pre"), name: ev.status_name || "", detail: ev.status || "",
      completed: !!ev.finished, home_goals: ev.home_goals, away_goals: ev.away_goals,
      clock: ev.clock, display_clock: ev.display_clock || "", period: ev.period, clock_at: ev.clock_at || ""
    }];
    var p = basePayload(ev.id);
    if (p && p.status) cands.push(p.status);
    if (LIVE[ev.id] && LIVE[ev.id].status) cands.push(LIVE[ev.id].status);
    cands.sort(function (a, b) { return (Date.parse(b.clock_at) || 0) - (Date.parse(a.clock_at) || 0); });
    return cands[0];
  }
  function phase(st) {
    if (st.completed) return "ft";
    if (st.state === "in") return st.name === "STATUS_HALFTIME" ? "ht" : "live";
    if (st.state === "post") return "off";       // postponed or abandoned
    return "pre";
  }

  // Tick the minute between polls: anchor on ESPN's own display clock, then
  // add the minutes that have passed since it was read. Capped at 12 so a
  // stale feed never invents a 45+30' half.
  function liveMinute(st) {
    var anchor = /^(\d+)'?(?:\s*\+\s*(\d+))?/.exec(String(st.display_clock || "").replace(/'/g, "' ").trim());
    var since = Math.min(Math.max(0, (Date.now() - (Date.parse(st.clock_at) || Date.now())) / 60000), 12);
    var total;
    if (anchor) {
      var base = +anchor[1], added = anchor[2] ? +anchor[2] : 0;
      var frac = (!added && st.clock != null) ? (st.clock % 60) / 60 : 0;
      total = base + added + Math.floor(since + frac);
    } else if (st.clock != null) {
      total = Math.floor(st.clock / 60 + since) + 1;
    } else {
      return st.detail || "Live";
    }
    var cap = { 1: 45, 2: 90, 3: 105, 4: 120 }[st.period];
    return (cap && total > cap) ? cap + "+" + (total - cap) + "'" : total + "'";
  }

  function statusPill(ev, st) {
    var ph = phase(st);
    if (ph === "live") return '<span class="pill pill-live" data-clock="' + attr(ev.id) + '">' + esc(liveMinute(st)) + '</span>';
    if (ph === "ht") return '<span class="pill pill-ht">HT</span>';
    if (ph === "ft") return '<span class="pill">' + esc(/PEN|AET/.test(st.name || "") ? st.detail || "FT" : "FT") + '</span>';
    if (ph === "off") return '<span class="pill">' + esc(st.detail || "Off") + '</span>';
    return '<span class="pill pill-soon" data-countdown="' + attr(ev.kickoff) + '">' + esc(countdown(ev.kickoff)) + '</span>';
  }

  function arsenalResult(ev, st) {
    if (!st.completed || st.home_goals == null) return null;
    var home = ev.home === TEAM;
    var gf = home ? st.home_goals : st.away_goals, ga = home ? st.away_goals : st.home_goals;
    return gf > ga ? "W" : (gf === ga ? "D" : "L");
  }
  function arsenalScore(ev, st) {
    if (st.home_goals == null || st.away_goals == null) return "";
    return ev.home === TEAM ? st.home_goals + "–" + st.away_goals : st.away_goals + "–" + st.home_goals;
  }

  // the match in its live window right now, if any
  function currentEvent() {
    var f = football(), now = Date.now();
    var cands = [f.live_match, f.next_match, f.last_result];
    for (var i = 0; i < cands.length; i++) {
      var e = cands[i];
      if (!e) continue;
      var ko = Date.parse(e.kickoff);
      if (now >= ko - 10 * 60000 && now <= ko + 3 * 3600000) {
        var ph = phase(statusOf(e));
        if (ph === "live" || ph === "ht" || ph === "pre") return e;
      }
    }
    return null;
  }

  // ---------- the scoreboard: shared by Home and the match centre ----------
  function roundLabel(ev) { return ev.round ? ev.comp + ", " + ev.round : ev.comp; }

  function scorersHtml(p) {
    var s = (p && p.scorers) || { home: [], away: [] };
    if (!(s.home || []).length && !(s.away || []).length) return "";
    function side(list) {
      return (list || []).map(function (r) {
        var mins = r.goals.map(function (g) { return esc(g.minute) + (g.pen ? ' <span class="tag">pen</span>' : ""); }).join(", ");
        return '<div><b>' + esc(r.name) + '</b> ' + mins + (r.og ? ' <span class="tag">og</span>' : "") + '</div>';
      }).join("");
    }
    return '<div class="scorers" aria-label="Goal scorers"><div class="sc-home">' + side(s.home) + '</div>' +
      '<div class="sc-ball">' + ICON.ball + '</div><div class="sc-away">' + side(s.away) + '</div></div>';
  }

  // the match rail: the signature. 90 minutes as a line, goals where they
  // happened (home above, away below), Arsenal's goals filled green.
  function railHtml(ev, p, st) {
    var ph = phase(st);
    if (ph === "pre" || ph === "off") return "";
    var tl = (p && p.timeline) || [];
    var extra = tl.some(function (t) { return (t.period || 0) >= 3; });
    var span = extra ? 120 : 90;
    function minuteOf(t) {
      var m = /^(\d+)(?:'?\+(\d+))?/.exec(String(t.minute || "").replace(/'/g, ""));
      return m ? +m[1] : null;
    }
    var now = span;
    if (ph === "live" || ph === "ht") {
      var lm = /^(\d+)/.exec(ph === "ht" ? "45" : liveMinute(st));
      now = lm ? Math.min(+lm[1], span) : 0;
    }
    var marks = tl.filter(function (t) { return t.scoring || t.kind === "red"; }).map(function (t) {
      var m = minuteOf(t);
      if (m == null) return "";
      var left = Math.min(m, span) / span * 100;
      var cls = t.kind === "red" ? "red" : (t.ours ? "ours" : "");
      var label = (t.kind === "red" ? "Red card, " : "Goal, ") + (t.player || "") + ", " + t.minute;
      return '<i class="rail-mark ' + cls + ' ' + (t.side === "away" ? "down" : "up") + '" style="left:' + left.toFixed(1) + '%" title="' + attr(label) + '"></i>';
    }).join("");
    return '<div class="rail" aria-hidden="true"><i class="rail-track"></i><i class="rail-fill" style="width:' + (now / span * 100).toFixed(1) + '%"></i>' +
      '<i class="rail-ht" style="left:50%"></i>' + (extra ? '<i class="rail-ht" style="left:75%"></i>' : "") + marks + '</div>' +
      '<div class="rail-ends" aria-hidden="true"><span>0\'</span><span>HT</span><span>' + span + '\'</span></div>';
  }

  function board(ev, opts) {
    opts = opts || {};
    var st = statusOf(ev), ph = phase(st), p = payloadFor(ev.id);
    var tag = opts.link ? "a" : "section";
    var h = '<' + tag + ' class="board comp-band-' + esc(ev.comp_slug || "pl") + (ph === "live" ? " is-live" : "") + '"' +
      (opts.link ? ' href="#/match/' + encodeURIComponent(ev.id) + '"' : ' aria-label="' + attr(ev.home + " v " + ev.away) + '"') + '>';
    h += '<div class="board-top"><span>' + esc(roundLabel(ev)) + '</span>' + statusPill(ev, st) + '</div>';
    var mid;
    if (ph === "pre" || (ph === "off" && st.home_goals == null)) {
      mid = '<span class="bt-ko">' + esc(koTime(ev.kickoff)) + '</span><span class="bt-date">' + esc(dayWord(ev.kickoff)) + '</span>';
    } else {
      mid = '<span class="bt-score" aria-label="' + attr(ev.home + " " + st.home_goals + ", " + ev.away + " " + st.away_goals) + '">' + esc(st.home_goals) +
        '<span class="dash">–</span>' + esc(st.away_goals) + '</span>';
      if (ev.note && ph === "ft") mid += '<span class="bt-note">' + esc(ev.note) + '</span>';
    }
    h += '<div class="board-teams">' +
      '<div class="bt-team">' + crest(ev.home_logo, 56, ev.home_short) + '<span class="bt-name">' + esc(ev.home) + '</span></div>' +
      '<div class="bt-mid">' + mid + '</div>' +
      '<div class="bt-team">' + crest(ev.away_logo, 56, ev.away_short) + '<span class="bt-name">' + esc(ev.away) + '</span></div></div>';
    if (ph !== "pre") h += scorersHtml(p) + railHtml(ev, p, st);
    var venue = (p && p.info && p.info.venue) || ev.venue || "";
    // before kick-off the date and time are already the centre of the board
    var when = ph === "pre" ? "" : koDay(ev.kickoff);
    h += '<div class="board-foot"><span>' + esc(venue) + '</span><span>' + esc(when) + '</span></div>';
    return h + '</' + tag + '>';
  }

  // ---------- Home ----------
  function nextRow(ev) {
    return '<a class="next-row" href="#/match/' + encodeURIComponent(ev.id) + '"><span class="nr-label">Next</span>' +
      crest(ev.opponent_logo, 24, ev.opponent_short) + '<span class="nr-name">' + esc(ev.opponent) +
      ' <span class="sr-only">' + (ev.home_away === "H" ? "at home" : "away") + '</span></span>' +
      '<span class="nr-when">' + esc(dayWord(ev.kickoff)) + '<br>' + esc(koTime(ev.kickoff)) + '</span></a>';
  }

  function heroHtml() {
    var f = football();
    var cur = currentEvent();
    if (cur) return board(cur, { link: true });
    var last = f.last_result, next = f.next_match;
    if (last && Date.now() - Date.parse(last.kickoff) < 30 * 3600000) {
      return board(last, { link: true }) + (next ? nextRow(next) : "");
    }
    if (next) return board(next, { link: true });
    if (last) return board(last, { link: true });
    return '<div class="group"><p class="empty">No fixtures yet. They appear here as soon as ESPN publishes the schedule.</p></div>';
  }

  function resultsStrip(list) {
    return '<div class="strip">' + list.map(function (m) {
      var st = statusOf(m);
      return '<a class="tile" href="#/match/' + encodeURIComponent(m.id) + '" aria-label="' +
        attr((m.result === "W" ? "Won " : m.result === "L" ? "Lost " : "Drew ") + arsenalScore(m, st) + " against " + m.opponent) + '">' +
        crest(m.opponent_logo, 32, m.opponent_short) +
        '<span class="tile-score" aria-hidden="true">' + resChip(m.result) + esc(arsenalScore(m, st)) + '</span>' +
        '<span class="tile-opp" aria-hidden="true">' + esc(m.opponent_name || m.opponent) + '</span>' +
        '<span class="tile-meta" aria-hidden="true">' + compBadge(m) + esc(m.home_away === "H" ? "Home" : "Away") + '</span></a>';
    }).join("") + '</div>';
  }

  function miniTable(rows, highlight) {
    return '<table class="ltable"><thead><tr><th class="t-rank"><span class="sr-only">Position</span></th><th class="t-team">Team</th>' +
      '<th>P</th><th>GD</th><th class="t-pts">Pts</th></tr></thead><tbody>' + rows.map(function (r) {
        return '<tr class="' + (r.team === highlight ? "is-arsenal" : "") + '"><td class="t-rank" style="--zone:' + attr(r.zone_colour || "transparent") + '">' + esc(r.rank) + '</td>' +
          '<td class="t-team"><span class="t-teamcell">' + crest(r.logo, 22, r.team_short) + '<span>' + esc(r.short_name || r.team) + '</span></span></td>' +
          '<td>' + esc(r.played) + '</td><td>' + esc(r.gd) + '</td><td class="t-pts">' + esc(r.points) + '</td></tr>';
      }).join("") + '</tbody></table>';
  }

  function tableSnippet() {
    var t = football().table || [];
    if (!t.length) return "";
    var i = Math.max(0, t.findIndex(function (r) { return r.team === TEAM; }));
    var start = Math.max(0, Math.min(i - 1, t.length - 4));
    if (i <= 2) start = 0;
    return '<div class="section-head"><h2>Premier League</h2><a class="more" href="#/table">Full table</a></div>' +
      '<div class="group mini">' + miniTable(t.slice(start, start + 4), TEAM) + '</div>';
  }

  function storyRow(c, lead) {
    var kicker = '<span class="kicker k-' + slug(c.category) + '">' + esc(c.category) + '</span>';
    return '<li><a class="story' + (lead ? " lead" : "") + '" href="' + attr(c.url) + '" target="_blank" rel="noopener">' +
      (lead ? '<div class="story-foot" style="margin:0 0 6px">' + kicker + (c.best_likelihood ? meter(c.best_likelihood) : "") + '</div>' : "") +
      '<span class="story-title">' + esc(c.title) + '</span>' +
      '<span class="story-foot">' + (lead ? "" : kicker) + '<span class="src">' + esc(c.source) + '</span><span>' + esc(timeAgo(c.ts)) + '</span>' +
      (c.source_count > 1 ? '<span>' + c.source_count + ' sources</span>' : "") + '</span></a></li>';
  }

  function teamNewsItems() {
    var seen = {}, out = [];
    (DATA.team_news || []).concat(DATA.injuries || []).forEach(function (n) {
      if (!n || seen[n.url]) return;
      seen[n.url] = 1;
      out.push(n);
    });
    out.sort(function (a, b) { return String(b.ts || "").localeCompare(String(a.ts || "")); });
    return out;
  }
  function newsList(items) {
    return '<ul class="rows">' + items.map(function (n) {
      return '<li><a class="story" href="' + attr(n.url) + '" target="_blank" rel="noopener"><span class="story-title">' + esc(n.title) + '</span>' +
        '<span class="story-foot"><span class="src">' + esc(n.source) + '</span><span>' + esc(timeAgo(n.ts)) + '</span></span></a></li>';
    }).join("") + '</ul>';
  }

  function renderHome() {
    var f = football();
    var h = '<h1 class="sr-only">Arsenal home</h1><div class="section">' + heroHtml() + '</div>';
    var results = (f.results || []).slice(0, 6);
    if (results.length) {
      h += '<div class="section"><div class="section-head"><h2>Recent results</h2><a class="more" href="#/matches?view=results">All results</a></div>' +
        resultsStrip(results) + '</div>';
    }
    var snip = tableSnippet();
    if (snip) h += '<div class="section home-main-only">' + snip + '</div>';
    // team news has its own section below, so keep it out of top stories
    var tn = teamNewsItems().slice(0, 5);
    var inTeamNews = {};
    tn.forEach(function (n) { inTeamNews[n.url] = 1; });
    var clusters = ((DATA.arsenal && DATA.arsenal.clusters) || []).filter(function (c) { return !inTeamNews[c.url]; });
    var lead = pickHero(clusters);
    var rest = clusters.filter(function (c) { return !lead || c.url_hash !== lead.url_hash; }).slice(0, 4);
    if (lead) {
      h += '<div class="section"><div class="section-head"><h2>Top stories</h2><a class="more" href="#/news">All news</a></div>' +
        '<div class="group"><ul class="rows">' + storyRow(lead, true) + rest.map(function (c) { return storyRow(c, false); }).join("") + '</ul></div></div>';
    }
    var side = "";
    if (snip) side += '<div class="home-side-only">' + snip + '</div>';
    if (tn.length) side += '<div><div class="section-head"><h2>Injuries and team news</h2></div><div class="group">' + newsList(tn) + '</div></div>';
    setView(h);
    setRail(side);
  }

  // ---------- Matches ----------
  function matchRow(m, isNext) {
    var st = statusOf(m), ph = phase(st), right;
    if (ph === "live" || ph === "ht") {
      right = '<span class="mrow-score">' + esc(arsenalScore(m, st)) + '</span>' + statusPill(m, st);
    } else if (ph === "ft") {
      right = '<span class="mrow-score">' + esc(arsenalScore(m, st)) + '</span>' + resChip(arsenalResult(m, st));
    } else if (ph === "off") {
      right = '<span class="mrow-time">' + esc(st.detail || "Postponed") + '</span>';
    } else {
      right = '<span class="mrow-time">' + esc(koTime(m.kickoff)) + '</span>';
    }
    return '<li><a class="mrow' + (ph === "live" || ph === "ht" ? " is-live" : "") + (isNext ? " is-next" : "") + '" href="#/match/' + encodeURIComponent(m.id) + '">' +
      '<span class="mrow-date" aria-label="' + attr(koDay(m.kickoff)) + '"><b aria-hidden="true">' + esc(koDayNum(m.kickoff)) + '</b><span aria-hidden="true">' + esc(koWeekday(m.kickoff)) + '</span></span>' +
      '<span class="mrow-mid">' + crest(m.opponent_logo, 30, m.opponent_short) + '<span class="mrow-text"><span class="mrow-opp">' + esc(m.opponent_name || m.opponent) + '</span>' +
      '<span class="mrow-sub">' + compBadge(m) + '<span>' + (m.home_away === "H" ? "Home" : "Away") + (m.round ? ", " + esc(m.round) : "") + '</span></span></span></span>' +
      '<span class="mrow-right">' + right + '</span></a></li>';
  }

  function seasonRecord(comps) {
    if (!comps || !comps.length) return "";
    return '<div class="section-head"><h2>Season so far</h2></div><div class="group">' + comps.map(function (c) {
      return '<a class="row season" href="#/matches?view=results&comp=' + encodeURIComponent(c.comp) + '">' +
        '<span class="comp comp-' + esc(c.comp_slug) + '">' + esc(c.comp_code) + '</span><span class="s-name">' + esc(c.comp) + '</span>' +
        '<span class="s-wdl" aria-label="' + attr(c.w + " won, " + c.d + " drawn, " + c.l + " lost") + '">' +
        '<span class="res res-w' + (c.w ? "" : " zero") + '" aria-hidden="true">' + c.w + '</span>' +
        '<span class="res res-d' + (c.d ? "" : " zero") + '" aria-hidden="true">' + c.d + '</span>' +
        '<span class="res res-l' + (c.l ? "" : " zero") + '" aria-hidden="true">' + c.l + '</span></span></a>';
    }).join("") + '</div>';
  }

  function renderMatches(view, comp) {
    var f = football();
    view = view === "results" ? "results" : "upcoming";
    comp = comp || "All";
    var list = view === "upcoming" ? (f.live_match ? [f.live_match] : []).concat(f.fixtures || []) : (f.results || []);
    var comps = f.comps || [];
    var h = '<h1 class="page-title">Matches</h1>';
    h += '<nav class="seg" aria-label="Upcoming or results">' +
      '<a class="' + (view === "upcoming" ? "active" : "") + '" href="#/matches?view=upcoming&comp=' + encodeURIComponent(comp) + '"' + (view === "upcoming" ? ' aria-current="page"' : "") + '>Upcoming</a>' +
      '<a class="' + (view === "results" ? "active" : "") + '" href="#/matches?view=results&comp=' + encodeURIComponent(comp) + '"' + (view === "results" ? ' aria-current="page"' : "") + '>Results</a></nav>';
    var total = list.length;
    h += '<nav class="chips" aria-label="Competition"><a class="chip' + (comp === "All" ? " active" : "") + '" href="#/matches?view=' + view + '&comp=All">All <span class="n">' + total + '</span></a>' +
      comps.map(function (c) {
        var n = list.filter(function (m) { return m.comp === c.comp; }).length;
        if (!n && comp !== c.comp) return "";
        return '<a class="chip' + (comp === c.comp ? " active" : "") + '" href="#/matches?view=' + view + '&comp=' + encodeURIComponent(c.comp) + '">' +
          esc(c.comp) + ' <span class="n">' + n + '</span></a>';
      }).join("") + '</nav>';
    if (comp !== "All") list = list.filter(function (m) { return m.comp === comp; });

    if (view === "results" && list.length) {
      var w = 0, d = 0, l = 0;
      list.forEach(function (m) { if (m.result === "W") w++; else if (m.result === "D") d++; else if (m.result === "L") l++; });
      h += '<p class="note" style="margin:0 0 var(--s2)">' + esc(plural(w, "win") + ", " + plural(d, "draw") + ", " + plural(l, "defeat")) + '</p>';
    }
    if (!list.length) {
      h += '<div class="group"><p class="empty">' + (view === "results"
        ? "No results yet this season."
        : "Nothing scheduled. Cup ties appear here once the draw is made.") + '</p></div>';
    }
    var groups = [];
    list.forEach(function (m) {
      var label = koMonth(m.kickoff);
      if (!groups.length || groups[groups.length - 1][0] !== label) groups.push([label, []]);
      groups[groups.length - 1][1].push(m);
    });
    var nextId = f.next_match && f.next_match.id;
    groups.forEach(function (g) {
      h += '<h2 class="month">' + esc(g[0]) + '</h2><div class="group"><ul class="mlist">' +
        g[1].map(function (m) { return matchRow(m, view === "upcoming" && m.id === nextId); }).join("") + '</ul></div>';
    });
    setView(h);
    setRail('<div class="desktop-only">' + seasonRecord(comps) + '</div>' + '<div class="desktop-only">' + tableSnippet() + '</div>');
  }

  // ---------- match centre ----------
  function tabsFor(ev, st, p) {
    var ph = phase(st);
    var tabs = [];
    if (ph === "pre" || ph === "off") {
      tabs.push(["preview", "Preview"]);
      tabs.push(["lineups", "Line-ups"]);
    } else {
      tabs.push(["timeline", "Timeline"]);
      tabs.push(["lineups", "Line-ups"]);
      if (p && p.stats && p.stats.length) tabs.push(["stats", "Stats"]);
      if (ph !== "ft") tabs.push(["preview", "Team news"]);
    }
    return tabs;
  }

  function timelineHtml(ev, p, st) {
    var tl = ((p && p.timeline) || []).slice();
    if (!tl.length) {
      return '<div class="group"><p class="empty">' + (phase(st) === "ft"
        ? "ESPN has no event timeline for this match."
        : "Nothing yet. Goals, cards and substitutions appear here as they happen.") + '</p></div>';
    }
    var live = phase(st) === "live" || phase(st) === "ht";
    if (live) tl.reverse();   // newest first while the game is on
    var rows = tl.map(function (t) {
      if (t.kind === "ht" || t.kind === "ft") {
        return '<li class="tl-marker"><span>' + esc(t.minute) + ' <span>' + esc(t.score || "") + '</span></span></li>';
      }
      var side = t.side === "away" ? "away" : "home";
      var who = t.player_short || t.player, other = t.detail_short || t.detail;
      var ico, what, cls = "";
      if (t.scoring) {
        cls = " goal" + (t.ours ? " ours" : "");
        ico = ICON.ball;
        var sub = t.kind === "pen" ? "Penalty" : t.kind === "og" ? "Own goal" : (other ? "Assist: " + other : "");
        what = '<b>' + esc(who || "Goal") + '</b>' + (sub ? '<span>' + esc(sub) + '</span>' : "") +
          (t.score ? '<span class="tl-score">' + esc(t.score) + '</span>' : "");
      } else if (t.kind === "yellow" || t.kind === "red") {
        ico = '<i class="card-ico' + (t.kind === "red" ? " red" : "") + '"></i>';
        what = '<b>' + esc(who) + '</b><span class="sr-only">' + (t.kind === "red" ? "red card" : "yellow card") + '</span>';
        if (t.type === "Yellow Red Card" || t.type === "Second Yellow Card") what += '<span>Second yellow</span>';
      } else if (t.kind === "sub") {
        cls = " sub";
        ico = ICON.sub;
        what = '<b><span class="sr-only">On: </span>' + esc(who) + '</b>' + (other ? '<span><span class="sr-only">Off: </span>' + esc(other) + ' off</span>' : "");
      } else if (t.kind === "pen_miss") {
        ico = ICON.miss;
        what = '<b>' + esc(who) + '</b><span>' + esc(t.type === "Penalty - Saved" ? "Penalty saved" : "Penalty missed") + '</span>';
      } else {
        ico = "";
        what = '<span>' + esc(t.text.length > 90 ? t.text.slice(0, 90) + "…" : t.text) + '</span>';
      }
      return '<li class="tl-row ' + side + cls + '"><span class="tl-min">' + esc(t.minute) + '</span>' +
        '<span class="tl-ev"><span class="tl-ico">' + ico + '</span><span class="tl-what">' + what + '</span></span></li>';
    }).join("");
    var info = factsHtml(ev, p);
    return '<div class="group"><div class="tl-legend"><span>' + esc(ev.home) + '</span><span>' + esc(ev.away) + '</span></div>' +
      '<ol class="tl">' + rows + '</ol></div>' + (info ? '<div class="section"><div class="section-head"><h2>Match info</h2></div><div class="group">' + info + '</div></div>' : "");
  }

  function factsHtml(ev, p) {
    var i = (p && p.info) || {};
    var rows = [];
    rows.push(["Kick-off", koDay(ev.kickoff) + ", " + koTime(ev.kickoff) + " SAST"]);
    if (i.venue || ev.venue) rows.push(["Venue", (i.venue || ev.venue) + (i.city ? ", " + i.city : "")]);
    if (i.referee) rows.push(["Referee", i.referee]);
    if (i.attendance) rows.push(["Attendance", Number(i.attendance).toLocaleString("en-GB")]);
    return '<dl class="facts">' + rows.map(function (r) { return '<dt>' + esc(r[0]) + '</dt><dd>' + esc(r[1]) + '</dd>'; }).join("") + '</dl>';
  }

  function faceHtml(pl) {
    if (!pl.photo) return "";
    return '<img class="pl-face" src="' + attr(pl.photo) + '" alt="" width="120" height="120" loading="lazy" decoding="async"' +
      ' onerror="var d=this.parentElement;d.classList.remove(\'has-face\');this.remove()">';
  }
  function marksOf(pl, kind) { return (pl.marks || []).filter(function (m) { return m.kind === kind; }); }
  function surname(name) {
    var parts = String(name || "").split(" ");
    if (parts.length > 1 && parts[0].slice(-1) === "." && parts[0].length <= 2) return parts.slice(1).join(" ");
    return name || "";
  }

  function pitchHtml(side) {
    var rows = (side.rows || []).map(function (row) {
      return '<div class="pitch-row">' + row.map(function (pl) {
        var goals = marksOf(pl, "goal").length;
        var yellow = marksOf(pl, "yellow").length, red = marksOf(pl, "red").length;
        var off = marksOf(pl, "off")[0];
        var badges = (goals ? '<span class="b-goal" title="' + goals + (goals > 1 ? " goals" : " goal") + '">' + (goals > 1 ? goals : ICON.ball) + '</span>' : "") +
          (red ? '<i class="card-ico red" title="Red card"></i>' : (yellow ? '<i class="card-ico" title="Yellow card"></i>' : ""));
        var label = (pl.name || "") + (goals ? ", " + plural(goals, "goal") : "") + (red ? ", sent off" : yellow ? ", booked" : "") + (off ? ", off " + off.minute : "");
        return '<span class="pl' + (pl.subbed_off ? " subbed" : "") + '"><span class="sr-only">' + esc(label) + '</span>' +
          '<i class="pl-no' + (pl.photo ? " has-face" : "") + '" aria-hidden="true"><span class="pl-num">' + esc(pl.jersey) + '</span>' + faceHtml(pl) +
          (badges ? '<span class="pl-badges">' + badges + '</span>' : "") + '</i>' +
          '<b class="pl-name" aria-hidden="true">' + esc(surname(pl.short || pl.name)) + '</b>' +
          (off ? '<span class="pl-off" aria-hidden="true">' + ICON.down + esc(off.minute) + '</span>' : "") + '</span>';
      }).join("") + '</div>';
    }).join("");
    var kit = side.team === TEAM ? "var(--red-deep)" : (side.kit || ("#" + (side.colour || "7c889d")));
    var ink = side.team === TEAM ? "light" : (side.ink || "light");
    var bench = (side.bench || []).map(function (pl) {
      var on = marksOf(pl, "on")[0];
      var goals = marksOf(pl, "goal").length, cardCls = marksOf(pl, "red").length ? " red" : (marksOf(pl, "yellow").length ? "" : null);
      return '<div class="bench-pl' + (pl.subbed_on ? " came-on" : "") + '"><span class="bn">' + esc(pl.jersey) + '</span>' +
        '<span class="bname">' + esc(pl.name) + '</span>' +
        (goals ? '<span class="tl-ico" title="Goal">' + ICON.ball + '</span>' : "") +
        (cardCls != null ? '<i class="card-ico' + cardCls + '" title="' + (cardCls ? "Red card" : "Yellow card") + '"></i>' : "") +
        (on ? '<span class="on">' + ICON.up + esc(on.minute) + '</span>' : "") + '</div>';
    }).join("");
    return '<div class="pitch ink-' + esc(ink) + '" style="--kit:' + attr(kit) + '">' +
      '<i class="pitch-box" aria-hidden="true"></i>' + rows + '</div>' +
      (bench ? '<div class="bench"><h4>Substitutes</h4>' + bench + '</div>' : "");
  }

  function lineupsHtml(ev, p, st) {
    var sides = (p && p.lineups) || [];
    var ars = sides.filter(function (s) { return s.team === TEAM; })[0];
    var opp = sides.filter(function (s) { return s.team !== TEAM; })[0];
    if (!ars || !ars.published) {
      var ko = Date.parse(ev.kickoff);
      return '<div class="group"><p class="empty">Line-ups are usually confirmed about an hour before kick-off, around ' +
        esc(koTime(new Date(ko - 3600000).toISOString())) + ' SAST on ' + esc(koDay(ev.kickoff)) + '.</p></div>';
    }
    var oppLogo = ev.home === TEAM ? ev.away_logo : ev.home_logo;
    var h = '<div class="group xi"><div class="xi-head">' + crest(ev.home === TEAM ? ev.home_logo : ev.away_logo, 24, "ARS") +
      '<span>Arsenal</span><span class="formation">' + esc(ars.formation) + '</span></div>' + pitchHtml(ars) + '</div>';
    if (opp && opp.published) {
      h += '<details class="group opp-xi"' + ((oppOpen == null ? window.innerWidth > 640 : oppOpen) ? " open" : "") + '><summary>' + crest(oppLogo, 24, ev.opponent_short) +
        '<span>' + esc(opp.team) + '</span><span class="formation">' + esc(opp.formation) + '</span>' + ICON.chev + '</summary>' +
        '<div class="xi">' + pitchHtml(opp) + '</div></details>';
    }
    return h;
  }

  function statsHtml(ev, p) {
    var stats = (p && p.stats) || [];
    if (!stats.length) return '<div class="group"><p class="empty">Team stats appear once the match is under way.</p></div>';
    var arsHome = ev.home === TEAM;
    var rows = stats.map(function (s) {
      var tot = (s.home || 0) + (s.away || 0);
      var hw = tot ? s.home / tot * 100 : 0, aw = tot ? s.away / tot * 100 : 0;
      var hv = s.pct ? Math.round(s.home) + "%" : s.home, av = s.pct ? Math.round(s.away) + "%" : s.away;
      return '<div class="stat"><div class="stat-top"><b class="' + (s.home > s.away ? "lead" : "") + '">' + esc(hv) + '</b>' +
        '<span class="stat-label">' + esc(s.label) + '</span><b class="' + (s.away > s.home ? "lead" : "") + '">' + esc(av) + '</b></div>' +
        '<div class="stat-bars" aria-hidden="true"><i class="h' + (arsHome ? " ars" : "") + '" style="--w:' + hw.toFixed(1) + '%"></i>' +
        '<i class="a' + (arsHome ? "" : " ars") + '" style="--w:' + aw.toFixed(1) + '%"></i></div></div>';
    }).join("");
    return '<div class="group"><div class="stat-teams"><span>' + crest(ev.home_logo, 24, ev.home_short) + esc(ev.home_name || ev.home) + '</span>' +
      '<span>' + esc(ev.away_name || ev.away) + crest(ev.away_logo, 24, ev.away_short) + '</span></div>' +
      '<div class="stats">' + rows + '</div></div><p class="note">Source: ESPN.</p>';
  }

  function previewHtml(ev, p) {
    var h = "";
    var tn = teamNewsItems().slice(0, 8);
    h += '<div class="section-head"><h2>Injuries and team news</h2></div>';
    h += tn.length ? '<div class="group">' + newsList(tn) + '</div>'
      : '<div class="group"><p class="empty">No injury or team news stories in the last few days.</p></div>';
    var o = p && p.opponent;
    if (o && (o.form || o.standing)) {
      h += '<div class="section"><div class="section-head"><h2>' + esc(o.name) + ' form</h2></div><div class="group">';
      if (o.standing && o.standing.rank) {
        h += '<div class="row"><span>League position</span><span style="margin-left:auto;font-weight:700" class="num">' +
          esc(o.standing.rank) + (o.standing.points != null ? ", " + esc(o.standing.points) + " pts" : "") + '</span></div>';
      }
      (o.form || []).slice().reverse().forEach(function (g) {
        h += '<div class="row">' + resChip(g.result) + '<span style="flex:1;min-width:0">' + esc(g.opponent) + '</span><span class="num" style="font-weight:700">' + esc(g.score) + '</span></div>';
      });
      h += '</div></div>';
    }
    h += '<div class="section"><div class="section-head"><h2>Match info</h2></div><div class="group">' + factsHtml(ev, p) + '</div></div>';
    return h;
  }

  function renderMatch(id, tab) {
    var ev = findEvent(id);
    if (!ev) {
      setView('<a class="back" href="#/matches">' + ICON.back + 'Matches</a><div class="group"><p class="empty">That match is not in this season\'s fixture list any more.</p></div>');
      setRail("");
      return;
    }
    var st = statusOf(ev), p = payloadFor(ev.id), key = String(ev.id);
    if (!basePayload(key) && !(key in MATCHES) && !PENDING[key]) loadPayload(key);
    var tabs = tabsFor(ev, st, p);
    var ids = tabs.map(function (t) { return t[0]; });
    if (ids.indexOf(tab) < 0) {
      var lineupsOut = p && (p.lineups || []).some(function (s) { return s.team === TEAM && s.published; });
      tab = (phase(st) === "pre" && lineupsOut) ? "lineups" : ids[0];
    }
    var back = phase(st) === "ft" ? "#/matches?view=results" : "#/matches";
    var h = '<a class="back" href="' + back + '">' + ICON.back + 'Matches</a>';
    h += '<h1 class="sr-only">' + esc(ev.home + " v " + ev.away + ", " + roundLabel(ev)) + '</h1>';
    h += board(ev, {});
    h += '<div class="mc-tabs"><nav class="seg" aria-label="Match centre">' + tabs.map(function (t) {
      return '<a class="' + (t[0] === tab ? "active" : "") + '" href="#/match/' + encodeURIComponent(ev.id) + '?tab=' + t[0] + '"' +
        (t[0] === tab ? ' aria-current="page"' : "") + ' data-tab>' + esc(t[1]) + '</a>';
    }).join("") + '</nav></div>';
    var body;
    if (!p && !(key in MATCHES) && phase(st) !== "pre") {
      body = '<div class="loading"><i style="height:160px"></i></div>';
    } else if (tab === "timeline") body = timelineHtml(ev, p, st);
    else if (tab === "lineups") body = lineupsHtml(ev, p, st);
    else if (tab === "stats") body = statsHtml(ev, p);
    else body = previewHtml(ev, p);
    h += '<div class="mc-panel">' + body + '</div>';
    var d = document.querySelector("details.opp-xi");
    if (d) oppOpen = d.open;
    setView(h);
    setRail("");
  }

  function loadPayload(id) {
    id = String(id);
    PENDING[id] = true;
    fetch("data/match/" + encodeURIComponent(id) + ".json", { cache: "no-cache" })
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (j) { MATCHES[id] = j; })
      .catch(function () { MATCHES[id] = null; })
      .then(function () { delete PENDING[id]; if (onMatchRoute(id)) route({ soft: true }); });
  }
  function onMatchRoute(id) {
    var r = parseHash();
    return r.parts[0] === "match" && decodeURIComponent(r.parts[1] || "") === String(id);
  }

  // ---------- live: poll ESPN straight from the phone while a match is on ----------
  var KINDS = {
    "Penalty - Scored": "pen", "Own Goal": "og", "Penalty - Missed": "pen_miss", "Penalty - Saved": "pen_miss",
    "Yellow Card": "yellow", "Red Card": "red", "Yellow Red Card": "red", "Second Yellow Card": "red",
    "Substitution": "sub", "Kickoff": "ko", "Halftime": "ht", "End Regular Time": "ft", "End Extra Time": "ft"
  };
  var SKIP = { "Start Delay": 1, "End Delay": 1, "Start 2nd Half": 1 };
  var GOAL_TYPES = { "Goal": 1, "Own Goal": 1, "Penalty - Scored": 1 };
  var RED_TYPES = { "Red Card": 1, "Yellow Red Card": 1, "Second Yellow Card": 1 };
  var STAT_KEYS = [["possessionPct", "Possession"], ["totalShots", "Shots"], ["shotsOnTarget", "Shots on target"],
    ["wonCorners", "Corners"], ["foulsCommitted", "Fouls"], ["offsides", "Offsides"],
    ["yellowCards", "Yellow cards"], ["redCards", "Red cards"], ["saves", "Saves"]];

  function toInt(v) { var n = parseInt(v, 10); return isNaN(n) ? null : n; }
  function toNum(v) { var n = parseFloat(v); return isNaN(n) ? null : (n % 1 ? Math.round(n * 10) / 10 : n); }

  function parseSummary(d) {
    var comp = d.header.competitions[0];
    var sides = {}, goalsBy = {}, names = {};
    comp.competitors.forEach(function (c) {
      sides[String(c.id || (c.team || {}).id)] = c.homeAway;
      goalsBy[c.homeAway] = toInt(c.score);
      names[c.homeAway] = (c.team || {}).displayName || "";
    });
    var s = comp.status || {}, t = s.type || {};
    var status = {
      state: t.state || "", name: t.name || "", detail: t.shortDetail || "", completed: !!t.completed,
      home: names.home, away: names.away, home_goals: goalsBy.home, away_goals: goalsBy.away,
      clock: s.clock, display_clock: s.displayClock || "", period: s.period, clock_at: new Date().toISOString()
    };
    var short = {};
    (d.rosters || []).forEach(function (r) {
      (r.roster || []).forEach(function (p) {
        var a = p.athlete || {};
        if (a.displayName) short[a.displayName] = surname(a.shortName || a.displayName);
      });
    });
    var goals = { home: 0, away: 0 }, tl = [];
    (d.keyEvents || []).forEach(function (e) {
      var kt = (e.type || {}).text || "", text = (e.text || "").trim();
      if (!text || SKIP[kt] || e.shootout) return;
      var scoring = !!e.scoringPlay || !!GOAL_TYPES[kt];
      var kind = KINDS[kt] || (scoring || kt.indexOf("Goal") === 0 ? "goal" : "other");
      var team = e.team || {};
      var side = sides[String(team.id || "")] || "";
      var ppl = (e.participants || []).map(function (x) { return (x.athlete || {}).displayName || ""; });
      var row = {
        minute: (e.clock || {}).displayValue || "", type: kt, text: text, scoring: scoring,
        ours: scoring && team.displayName === TEAM, big: scoring || !!RED_TYPES[kt], kind: kind, side: side,
        player: ppl[0] || "", detail: ppl.length > 1 && (kind === "goal" || kind === "sub") ? ppl[1] : "",
        player_short: short[ppl[0]] || "", detail_short: short[ppl[1]] || "",
        period: (e.period || {}).number, secs: (e.clock || {}).value
      };
      if (scoring && side) { goals[side]++; row.score = goals.home + "–" + goals.away; }
      tl.push(row);
    });
    var scorers = { home: [], away: [] };
    tl.forEach(function (ev) {
      if (!ev.scoring || !scorers[ev.side]) return;
      var nm = short[ev.player] || (ev.player ? ev.player.split(" ").pop() : "Goal");
      var og = ev.kind === "og";
      var row = scorers[ev.side].filter(function (r) { return r.name === nm && r.og === og; })[0];
      if (!row) { row = { name: nm, og: og, goals: [] }; scorers[ev.side].push(row); }
      row.goals.push({ minute: ev.minute, pen: ev.kind === "pen" });
    });
    var bySide = {};
    ((d.boxscore || {}).teams || []).forEach(function (bt) {
      var sd = sides[String((bt.team || {}).id || "")];
      if (!sd) return;
      bySide[sd] = {};
      (bt.statistics || []).forEach(function (x) { bySide[sd][x.name] = x.displayValue; });
    });
    var stats = [];
    if (bySide.home && bySide.away) {
      STAT_KEYS.forEach(function (k) {
        var hv = toNum(bySide.home[k[0]]), av = toNum(bySide.away[k[0]]);
        if (hv != null && av != null) stats.push({ key: k[0], label: k[1], home: hv, away: av, pct: k[0] === "possessionPct" });
      });
      if (!stats.some(function (x) { return x.home || x.away; })) stats = [];
    }
    return { status: status, scorers: scorers, timeline: withMarkers(tl, status), stats: stats };
  }

  function withMarkers(tl, st) {
    var events = tl.filter(function (t) { return ["ko", "ht", "ft"].indexOf(t.kind) < 0; });
    var second = events.some(function (t) { return (t.period || 1) >= 2; }) || st.name === "STATUS_HALFTIME" || (st.period || 0) >= 2 || st.completed;
    var out = [], g = { home: 0, away: 0 }, htDone = false;
    function marker(kind, label) { return { minute: label, kind: kind, side: "", score: g.home + "–" + g.away, scoring: false, text: "" }; }
    events.forEach(function (t) {
      if (second && !htDone && (t.period || 1) >= 2) { out.push(marker("ht", "HT")); htDone = true; }
      out.push(t);
      if (t.scoring && g[t.side] != null) g[t.side]++;
    });
    if (second && !htDone) out.push(marker("ht", "HT"));
    if (st.completed) {
      if (st.home_goals != null) g = { home: st.home_goals, away: st.away_goals };
      out.push(marker("ft", "FT"));
    }
    return out;
  }

  var liveTimer = null, liveBusy = false;
  function pollLive() {
    var ev = currentEvent();
    if (!ev || liveBusy || document.visibilityState === "hidden") return;
    var ko = Date.parse(ev.kickoff);
    if (Date.now() < ko - 10 * 60000) return;   // nothing to read before the build-up
    liveBusy = true;
    fetch(ESPN_SUMMARY.replace("{league}", ev.league || "eng.1").replace("{id}", encodeURIComponent(ev.id)))
      .then(function (r) { if (!r.ok) throw new Error(r.status); return r.json(); })
      .then(function (d) {
        LIVE[String(ev.id)] = parseSummary(d);
        if (currentPage === "home" || currentPage === "matches" || onMatchRoute(ev.id)) route({ soft: true });
        else renderChrome(currentPage);
      })
      .catch(function () { /* the snapshot is still there; keep showing it */ })
      .then(function () { liveBusy = false; });
  }
  function scheduleLive() {
    clearInterval(liveTimer);
    if (currentEvent()) { pollLive(); liveTimer = setInterval(pollLive, 30000); }
  }

  // ---------- News ----------
  function meter(label) {
    if (!label) return "";
    var idx = rungIndex(label), segs = "";
    for (var i = 0; i < meta.rungs.length; i++) segs += '<i class="seg ' + (i <= idx ? "on s" + i : "") + '"></i>';
    return '<span class="meter lvl-' + idx + '" title="Likelihood: ' + attr(label) + '">' + segs + '<em>' + esc(label) + '</em></span>';
  }

  function card(it, showClubs) {
    var h = '<article class="card' + (it.has_insider ? " insider-glow" : "") + '"><div class="card-meta">';
    h += '<span class="kicker k-' + slug(it.category) + '">' + esc(it.category) + '</span>';
    if (it.best_likelihood) h += meter(it.best_likelihood);
    if (it.has_insider) h += '<span class="insider">Insider</span>';
    if (it.source_count > 1) h += '<span class="consensus" title="' + attr((it.sources_list || []).join(", ")) + '">' + it.source_count + ' sources</span>';
    h += '<span class="time">' + esc(timeAgo(it.ts)) + '</span></div>';
    h += '<h2 class="card-title"><a href="' + attr(it.url) + '" target="_blank" rel="noopener">' + esc(it.title) + '</a></h2>';
    if (it.summary) h += '<p class="card-summary">' + esc(it.summary.length > 200 ? it.summary.slice(0, 200) + "…" : it.summary) + '</p>';
    h += '<div class="card-foot"><span class="source">' + esc(it.source) + '</span>';
    if (showClubs && it.clubs) h += '<span class="clubs">' + esc(it.clubs) + '</span>';
    if (it.player) h += '<a class="player-tag" href="#/saga/' + encodeURIComponent(it.player) + '">' + esc(it.player) + '</a>';
    return h + '</div></article>';
  }

  function pickHero(clusters) {
    var best = null, bestScore = -1;
    (clusters || []).slice(0, 40).forEach(function (c) {
      var score = (c.source_count || 1) * 3 + Math.max(rungIndex(c.best_likelihood), 0) * 2 + (c.has_insider ? 2 : 0);
      if (score > bestScore) { best = c; bestScore = score; }
    });
    return best;
  }

  function applyFilters(clusters) {
    var q = state.q.trim().toLowerCase();
    var minRung = state.rung ? rungIndex(state.rung) : -99;
    return clusters.filter(function (c) {
      if (state.category !== "All" && c.category !== state.category) return false;
      if (state.source !== "All" && (c.sources_list || []).indexOf(state.source) < 0 && c.source !== state.source) return false;
      if (state.rung && rungIndex(c.best_likelihood) < minRung) return false;
      if (q && (c.title + " " + (c.summary || "")).toLowerCase().indexOf(q) < 0) return false;
      return true;
    });
  }

  function newsSeg(active) {
    var items = [["arsenal", "#/news", "Arsenal"], ["others", "#/news/others", "Others"], ["all", "#/news/all", "All"], ["heat", "#/heat", "Heat"]];
    var searchable = active !== "heat";
    return '<div class="title-row"><h1 class="page-title">News</h1>' + (searchable
      ? '<button type="button" class="icon-btn" id="search-toggle" aria-label="Search stories" aria-expanded="' + searchOpen() + '" aria-controls="search-form">' +
        svg('<circle cx="11" cy="11" r="6.5"/><path d="M20 20l-4.2-4.2"/>') + '</button>' : "") + '</div>' +
      '<nav class="seg" aria-label="News section">' + items.map(function (i) {
      return '<a class="' + (i[0] === active ? "active" : "") + '" href="' + i[1] + '"' + (i[0] === active ? ' aria-current="page"' : "") + '>' + esc(i[2]) + '</a>';
    }).join("") + '</nav>';
  }

  function feedList(feed, showClubs) {
    if (!feed.length) return '<div class="group"><p class="empty">No stories match. Clear the search or pick another category.</p></div>';
    return feed.map(function (c) { return card(c, showClubs); }).join("");
  }

  function liveFeed(page) {
    var clusters = DATA[page].clusters;
    var noFilter = state.category === "All" && !state.q && !state.rung && state.source === "All";
    var hero = noFilter ? pickHero(clusters) : null;
    var filtered = applyFilters(clusters);
    return { hero: hero, feed: hero ? filtered.filter(function (c) { return c.url_hash !== hero.url_hash; }) : filtered };
  }

  function renderFeedPage(page) {
    var bundle = DATA[page];
    var counts = {};
    bundle.clusters.forEach(function (c) { counts[c.category] = (counts[c.category] || 0) + 1; });
    var res = liveFeed(page);
    var h = newsSeg(page);
    if (DATA.brief && DATA.brief.text && page === "arsenal") {
      h += '<section class="brief' + (briefOpen ? " open" : "") + '"><div class="brief-head">Morning brief <span>' + esc(timeAgo(DATA.brief.generated_at)) + '</span></div>' +
        '<p id="brief-text">' + esc(DATA.brief.text) + '</p><button type="button" class="brief-more" aria-expanded="' + briefOpen + '" aria-controls="brief-text">' +
        (briefOpen ? "Show less" : "Read the full brief") + '</button></section>';
    }
    if (res.hero) {
      var c = res.hero;
      h += '<a class="lead-story" href="' + attr(c.url) + '" target="_blank" rel="noopener"><div class="card-meta"><span class="kicker k-' + slug(c.category) + '">Top story</span>' +
        (c.best_likelihood ? meter(c.best_likelihood) : "") + (c.has_insider ? '<span class="insider">Insider</span>' : "") +
        (c.source_count > 1 ? '<span class="consensus">' + c.source_count + ' sources</span>' : "") + '</div>' +
        '<h2 class="story-title">' + esc(c.title) + '</h2><span class="story-foot"><span class="src">' + esc(c.source) + '</span><span>' + esc(timeAgo(c.ts)) + '</span></span></a>';
    }
    h += '<nav class="chips" aria-label="Category">';
    [["All", bundle.clusters.length]].concat(meta.categories.map(function (c) { return [c, counts[c] || 0]; })).forEach(function (t) {
      if (!t[1] && t[0] !== state.category) return;
      h += '<button type="button" class="chip' + (t[0] === state.category ? " active" : "") + '" data-cat="' + attr(t[0]) + '" aria-pressed="' + (t[0] === state.category) + '">' +
        esc(t[0]) + ' <span class="n">' + t[1] + '</span></button>';
    });
    h += '<button type="button" class="chip is-rung' + (state.rung ? " active" : "") + '" id="rung-toggle" aria-pressed="' + (!!state.rung) + '" title="Advanced and here-we-go stories only">Close to done</button></nav>';
    h += '<form class="searchbar" id="search-form" role="search" onsubmit="return false"' + (searchOpen() ? "" : " hidden") + '><label class="sr-only" for="search-input">Search stories</label>' +
      '<input class="search" type="search" id="search-input" placeholder="Search stories" value="' + attr(state.q) + '" autocomplete="off">' +
      '<label class="sr-only" for="source-select">Source</label><select class="select" id="source-select"><option value="All">All sources</option>' +
      bundle.sources.map(function (s) { return '<option value="' + attr(s) + '"' + (s === state.source ? " selected" : "") + '>' + esc(s) + '</option>'; }).join("") +
      '</select>' + (state.q || state.source !== "All" || state.rung ? '<button type="button" class="clear" id="clear-filters">Clear</button>' : "") + '</form>';
    h += '<section class="feed" id="feed">' + feedList(res.feed, page === "all") + '</section>';
    setView(h);
    var rail = '<div class="desktop-only">' + heatWidget(DATA.heat[page], page) + '</div><div class="desktop-only">' + dealsWidget(DATA.deals[page]) + '</div>';
    setRail(rail);
    bindFeedControls(page);
    announce(res.feed.length ? res.feed.length + " stories" : "No stories match");
  }

  function heatWidget(board, scope) {
    if (!board || !board.length) return "";
    var top = board[0].heat || 1;
    return '<section class="widget"><h2 class="widget-head"><a href="#/heat?scope=' + scope + '">Rumour heat<span class="more">See all</span></a></h2>' +
      board.slice(0, 8).map(function (h) {
        return '<a class="heat-row" href="#/saga/' + encodeURIComponent(h.player) + '"><span class="heat-name">' + esc(h.player) + '</span>' +
          '<span class="heat-bar"><i style="width:' + Math.round(h.heat / top * 100) + '%"></i></span>' +
          '<span class="heat-n">' + esc(h.mentions) + '</span></a>';
      }).join("") + '</section>';
  }
  function dealsWidget(deals) {
    if (!deals || !deals.length) return "";
    return '<section class="widget"><h2 class="widget-head">Done deals</h2>' + deals.map(function (d) {
      return '<a class="deal-row" href="' + attr(d.url) + '" target="_blank" rel="noopener"><b>' + esc(d.player) + '</b><span>' + esc(d.title || "") + '</span></a>';
    }).join("") + '</section>';
  }

  function renderOthers() {
    var clusters = DATA.europe.clusters, counts = DATA.europe.club_counts || {};
    var flat = state.club !== "All" || !!state.q || !!state.rung;
    var q = state.q.trim().toLowerCase();
    var filtered = clusters.filter(function (c) {
      if (state.club !== "All" && (c.clubs || "").split(",").map(function (x) { return x.trim(); }).indexOf(state.club) < 0) return false;
      if (state.rung && rungIndex(c.best_likelihood) < rungIndex(state.rung)) return false;
      if (q && (c.title + " " + (c.summary || "")).toLowerCase().indexOf(q) < 0) return false;
      return true;
    });
    var h = newsSeg("others");
    h += '<div class="crestwall"><button type="button" class="crest-tile' + (state.club === "All" ? " active" : "") + '" data-club="All" aria-pressed="' + (state.club === "All") + '">' +
      '<span class="ct-all" aria-hidden="true">' + svg('<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17M12 3.5c2.6 2.4 2.6 14.6 0 17M12 3.5c-2.6 2.4-2.6 14.6 0 17"/>') + '</span><span class="ct-name">All clubs</span></button>';
    meta.europe_clubs_order.forEach(function (c) {
      var n = counts[c] || 0;
      if (!n) return;
      h += '<button type="button" class="crest-tile' + (state.club === c ? " active" : "") + '" data-club="' + attr(c) + '" aria-pressed="' + (state.club === c) + '">' +
        clubCrest(c, 34) + '<span class="ct-name">' + esc(c) + '</span><span class="ct-n">' + n + '</span></button>';
    });
    h += '</div><nav class="chips" aria-label="Filter"><button type="button" class="chip is-rung' + (state.rung ? " active" : "") + '" id="rung-toggle" aria-pressed="' + (!!state.rung) +
      '" title="Advanced and here-we-go stories only">Close to done</button>' + (flat ? '<button type="button" class="chip" id="clear-filters">Clear filters</button>' : "") + '</nav>' +
      '<form class="searchbar" id="search-form" role="search" onsubmit="return false"' + (searchOpen() ? "" : " hidden") + '><label class="sr-only" for="search-input">Search transfers</label>' +
      '<input class="search" type="search" id="search-input" placeholder="Search transfers" value="' + attr(state.q) + '" autocomplete="off"></form>';
    h += '<section class="feed" id="feed">';
    if (flat) {
      h += feedList(filtered, true);
    } else {
      var groups = {};
      filtered.forEach(function (it) {
        var primary = (it.clubs || "").split(",")[0].trim();
        (groups[primary] = groups[primary] || []).push(it);
      });
      var any = false;
      meta.europe_clubs_order.forEach(function (club) {
        var items = groups[club];
        if (!items || !items.length) return;
        any = true;
        h += '<h2 class="club-head">' + clubCrest(club, 24) + esc(club) + ' <span class="count">' + items.length + '</span></h2>' +
          items.map(function (c) { return card(c, true); }).join("");
      });
      if (!any) h += '<div class="group"><p class="empty">No transfer stories from other clubs yet.</p></div>';
    }
    h += '</section>';
    setView(h);
    setRail('<div class="desktop-only">' + heatWidget(DATA.heat.europe, "europe") + '</div><div class="desktop-only">' + dealsWidget(DATA.deals.europe) + '</div>');
    document.querySelectorAll(".crest-tile[data-club]").forEach(function (b) {
      b.addEventListener("click", function () { state.club = b.getAttribute("data-club"); renderOthers(); });
    });
    bindCommon(renderOthers, function () { state.q = ""; state.club = "All"; state.rung = ""; }, function () {
      renderOthers();
      var again = el("search-input");
      if (again) { again.focus(); again.setSelectionRange(again.value.length, again.value.length); }
    });
    announce(filtered.length ? filtered.length + " transfers" : "No transfers match");
  }

  function renderHeat(scope) {
    scope = scope === "europe" ? "europe" : "arsenal";
    var board = (DATA.heat[scope] || []).slice();
    if (state.heatSort === "latest") board.sort(function (a, b) { return String(b.last_ts || "").localeCompare(String(a.last_ts || "")); });
    var top = board.length ? (board.reduce(function (m, x) { return Math.max(m, x.heat); }, 0) || 1) : 1;
    var h = newsSeg("heat");
    h += '<nav class="chips" aria-label="Heat options">' +
      '<a class="chip' + (scope === "arsenal" ? " active" : "") + '" href="#/heat?scope=arsenal">Arsenal</a>' +
      '<a class="chip' + (scope === "europe" ? " active" : "") + '" href="#/heat?scope=europe">Others</a>' +
      '<i class="chip-sep" aria-hidden="true"></i>' +
      '<button type="button" class="chip' + (state.heatSort === "heat" ? " active" : "") + '" data-sort="heat">Hottest</button>' +
      '<button type="button" class="chip' + (state.heatSort === "latest" ? " active" : "") + '" data-sort="latest">Latest</button></nav>';
    if (!board.length) {
      h += '<div class="group"><p class="empty">No transfer chatter tracked here in the last fortnight.</p></div>';
    } else {
      h += '<ol class="heat-list">' + board.map(function (x, i) {
        var mo = x.momentum === "rising" ? "Rising" : x.momentum === "cooling" ? "Cooling" : "Steady";
        return '<li><a class="heat-card" href="#/saga/' + encodeURIComponent(x.player) + '"><span class="hc-rank">' + (i + 1) + '</span><div class="hc-body">' +
          '<div class="hc-top"><span class="hc-name">' + esc(x.player) + '</span>' + (x.is_new ? '<span class="hc-new">New</span>' : "") +
          '<span class="hc-momentum mo-' + esc(x.momentum) + '">' + mo + '</span>' +
          (x.last_ts ? '<span class="hc-time">' + esc(timeAgo(x.last_ts)) + '</span>' : "") + '</div>' +
          '<div class="hc-bar" aria-hidden="true"><i style="width:' + Math.round(x.heat / top * 100) + '%"></i></div>' +
          (x.latest_title ? '<p class="hc-latest">' + esc(x.latest_title.length > 120 ? x.latest_title.slice(0, 120) + "…" : x.latest_title) + '</p>' : "") +
          '<div class="hc-meta">' + meter(x.best_likelihood) + '<span>' + plural(x.mentions, "report") + '</span>' +
          (x.latest_source ? '<span>' + esc(x.latest_source) + '</span>' : "") + (scope === "europe" && x.club ? '<span>' + esc(x.club) + '</span>' : "") + '</div></div></a></li>';
      }).join("") + '</ol>';
    }
    setView(h);
    setRail('<section class="widget desktop-only"><h2 class="widget-head">How heat works</h2><p class="rail-note">Heat counts how often a player is linked, weighted by how credible the reports are. Bar colour is the furthest the story has got:</p>' +
      '<ul class="heat-legend"><li><i class="lg hb-rumour"></i>Rumour</li><li><i class="lg hb-developing"></i>Developing</li><li><i class="lg hb-advanced"></i>Advanced</li><li><i class="lg hb-here-we-go"></i>Here we go</li></ul>' +
      '<p class="rail-note">Rising and cooling compare the last 3 days with the 3 before. New means first linked in the last 48 hours.</p></section>');
    document.querySelectorAll("[data-sort]").forEach(function (b) {
      b.addEventListener("click", function () { state.heatSort = b.getAttribute("data-sort"); renderHeat(scope); });
    });
  }

  function renderSaga(player) {
    var h = '<a class="back" href="#/heat">' + ICON.back + 'Rumour heat</a><h1 class="page-title">' + esc(player) + '</h1>';
    if (!SAGAS) {
      setView(h + '<div class="loading"><i style="height:120px"></i><i></i></div>');
      setRail("");
      fetch("data/sagas.json", { cache: "no-cache" }).then(function (r) { return r.json(); })
        .then(function (j) { SAGAS = j; }).catch(function () { SAGAS = {}; })
        .then(function () { if (parseHash().parts[0] === "saga") route({ soft: true }); });
      return;
    }
    var rows = SAGAS[player] || [];
    h += '<p class="page-intro">' + plural(rows.length, "report") + ', oldest first. Watch the likelihood climb, or stall.</p>';
    h += rows.length ? '<ol class="saga">' + rows.map(function (r) {
      return '<li class="saga-row rung-' + rungIndex(r.likelihood) + '"><span class="saga-dot"></span><div class="saga-body"><div class="card-meta">' + meter(r.likelihood) +
        (r.credibility === "insider" ? '<span class="insider">Insider</span>' : "") + '<span class="time">' + esc(timeAgo(r.ts)) + '</span></div>' +
        '<a class="saga-title" href="' + attr(r.url) + '" target="_blank" rel="noopener">' + esc(r.title) + '</a><span class="source">' + esc(r.source) + '</span></div></li>';
    }).join("") + '</ol>' : '<div class="group"><p class="empty">No reports tracked for this player yet.</p></div>';
    setView(h);
    var others = Object.keys(SAGAS).sort(function (a, b) { return SAGAS[b].length - SAGAS[a].length; }).filter(function (p) { return p !== player; }).slice(0, 12);
    setRail('<section class="widget desktop-only"><h2 class="widget-head">Other sagas</h2>' + others.map(function (p) {
      return '<a class="deal-row" href="#/saga/' + encodeURIComponent(p) + '"><b>' + esc(p) + '</b></a>';
    }).join("") + '</section>');
  }

  function bindCommon(rerender, clearFn, redrawList) {
    var tg = el("search-toggle");
    if (tg) tg.addEventListener("click", function () {
      var form = el("search-form");
      var show = form.hidden;
      form.hidden = !show;
      searchShown = show;
      tg.setAttribute("aria-expanded", show);
      if (show) el("search-input").focus();
    });
    var rt = el("rung-toggle");
    if (rt) rt.addEventListener("click", function () { state.rung = state.rung ? "" : "Advanced"; rerender(); });
    var clr = el("clear-filters");
    if (clr) clr.addEventListener("click", function () { clearFn(); rerender(); });
    var inp = el("search-input");
    if (inp) {
      var timer = null;
      inp.addEventListener("input", function () {
        state.q = inp.value;
        clearTimeout(timer);
        // redraw the list only, so the keyboard stays up
        timer = setTimeout(redrawList, 180);
      });
    }
  }
  function bindFeedControls(page) {
    var bm = document.querySelector(".brief-more");
    if (bm) bm.addEventListener("click", function () {
      briefOpen = !briefOpen;
      var b = document.querySelector(".brief");
      b.classList.toggle("open", briefOpen);
      bm.setAttribute("aria-expanded", briefOpen);
      bm.textContent = briefOpen ? "Show less" : "Read the full brief";
    });
    document.querySelectorAll(".chip[data-cat]").forEach(function (b) {
      b.addEventListener("click", function () { state.category = b.getAttribute("data-cat"); renderFeedPage(page); });
    });
    var sel = el("source-select");
    if (sel) sel.addEventListener("change", function () { state.source = sel.value; renderFeedPage(page); });
    bindCommon(function () { renderFeedPage(page); }, function () { state.q = ""; state.source = "All"; state.rung = ""; }, function () {
      var res = liveFeed(page);
      el("feed").innerHTML = feedList(res.feed, page === "all");
      announce(res.feed.length ? res.feed.length + " stories" : "No stories match");
    });
  }

  // ---------- Table ----------
  function renderTable(which) {
    var f = football();
    var hasUcl = (f.ucl_table || []).length > 0;
    which = which === "ucl" && hasUcl ? "ucl" : "pl";
    var rows = which === "ucl" ? f.ucl_table : (f.table || []);
    var h = '<h1 class="page-title">Table</h1>';
    if (hasUcl) {
      h += '<nav class="seg" aria-label="Competition">' +
        '<a class="' + (which === "pl" ? "active" : "") + '" href="#/table"' + (which === "pl" ? ' aria-current="page"' : "") + '>Premier League</a>' +
        '<a class="' + (which === "ucl" ? "active" : "") + '" href="#/table?t=ucl"' + (which === "ucl" ? ' aria-current="page"' : "") + '>Champions League</a></nav>';
    }
    if (!rows || !rows.length) {
      h += '<div class="group"><p class="empty">The table is not available right now. It refreshes with the fixtures every 90 minutes.</p></div>';
    } else {
      h += '<div class="group"><table class="ltable"><caption class="sr-only">' + (which === "ucl" ? "Champions League league phase" : "Premier League table") + '</caption>' +
        '<thead><tr><th class="t-rank"><span class="sr-only">Position</span></th><th class="t-team">Team</th><th><abbr title="Played">P</abbr></th>' +
        '<th class="wdl"><abbr title="Won">W</abbr></th><th class="wdl"><abbr title="Drawn">D</abbr></th><th class="wdl"><abbr title="Lost">L</abbr></th>' +
        '<th><abbr title="Goal difference">GD</abbr></th><th class="t-pts"><abbr title="Points">Pts</abbr></th></tr></thead><tbody>' +
        rows.map(function (r) {
          return '<tr class="' + (r.team === TEAM ? "is-arsenal" : "") + '"' + (r.team === TEAM ? ' aria-current="true"' : "") + '>' +
            '<td class="t-rank" style="--zone:' + attr(r.zone_colour || "transparent") + '">' + esc(r.rank) + '</td>' +
            '<td class="t-team"><span class="t-teamcell">' + crest(r.logo, 22, r.team_short) + '<span>' + esc(r.short_name || r.team) + '</span></span></td>' +
            '<td>' + esc(r.played) + '</td><td class="wdl">' + esc(r.w) + '</td><td class="wdl">' + esc(r.d) + '</td><td class="wdl">' + esc(r.l) + '</td>' +
            '<td>' + esc(r.gd) + '</td><td class="t-pts">' + esc(r.points) + '</td></tr>';
        }).join("") + '</tbody></table></div>';
      var zones = {}, order = [];
      rows.forEach(function (r) { if (r.zone && !zones[r.zone]) { zones[r.zone] = r.zone_colour; order.push(r.zone); } });
      if (order.length) {
        h += '<div class="zones">' + order.map(function (z) { return '<span><i style="--zone:' + attr(zones[z]) + '"></i>' + esc(z) + '</span>'; }).join("") + '</div>';
      }
      h += '<p class="note">From ESPN, updated ' + esc(timeAgo(f._updated_at) || "recently") + '.</p>';
    }
    setView(h);
    setRail("");
  }

  // ---------- chrome ----------
  function setView(html) { el("view").innerHTML = html; }
  function setRail(html) { el("rail").innerHTML = html; }
  function announce(msg) { var s = el("status"); if (s) s.textContent = msg; }

  function renderChrome(page) {
    document.querySelectorAll("[data-nav]").forEach(function (a) {
      var on = a.getAttribute("data-nav") === page;
      a.classList.toggle("active", on);
      if (on) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    var up = el("updated");
    var age = Date.now() - (Date.parse(DATA.generated_at) || 0);
    up.textContent = "Updated " + timeAgo(DATA.generated_at);
    up.style.color = age > 2 * 3600000 ? "var(--amber)" : "";
    el("refresh").hidden = !DATA.local;
    // live bar: a match is on and this screen is not already showing it
    var cur = currentEvent(), lb = "";
    if (cur && page !== "home") {
      var st = statusOf(cur), ph = phase(st);
      var r = parseHash();
      var onIt = r.parts[0] === "match" && decodeURIComponent(r.parts[1] || "") === String(cur.id);
      if ((ph === "live" || ph === "ht") && !onIt) {
        lb = '<a class="livebar" href="#/match/' + encodeURIComponent(cur.id) + '">' + statusPill(cur, st) +
          '<span class="lb-score">' + esc((cur.home_short || cur.home) + " " + st.home_goals + "–" + st.away_goals + " " + (cur.away_short || cur.away)) + '</span>' +
          '<span class="lb-go">Match centre</span></a>';
      }
    }
    el("livebar").innerHTML = lb;
    document.querySelector(".layout").classList.toggle("single", page === "match" || page === "table");
  }

  // ---------- routing ----------
  function parseHash() {
    var hash = location.hash.replace(/^#/, "") || "/";
    var qs = "", qi = hash.indexOf("?");
    if (qi >= 0) { qs = hash.slice(qi + 1); hash = hash.slice(0, qi); }
    var params = {};
    qs.split("&").forEach(function (kv) { if (!kv) return; var p = kv.split("="); params[p[0]] = decodeURIComponent(p[1] || ""); });
    return { parts: hash.split("/").filter(Boolean), params: params };
  }
  function resetFilters() { state.category = "All"; state.source = "All"; state.q = ""; state.rung = ""; state.club = "All"; }

  function route(opts) {
    if (!DATA) return;
    opts = opts || {};
    var r = parseHash(), head = r.parts[0] || "", page, key;
    // a soft re-render (data refresh, live poll) must not wipe what is being typed
    var active = document.activeElement;
    if (opts.soft && active && active.id === "search-input") return;
    if (head === "match") { page = "match"; renderMatch(decodeURIComponent(r.parts[1] || ""), r.params.tab); }
    else if (head === "matches" || head === "fixtures") { page = "matches"; renderMatches(r.params.view, r.params.comp); }
    else if (head === "table") { page = "table"; renderTable(r.params.t); }
    else if (head === "heat") { page = "news"; renderHeat(r.params.scope); }
    else if (head === "saga") { page = "news"; renderSaga(decodeURIComponent(r.parts.slice(1).join("/"))); }
    else if (head === "news" || head === "europe" || head === "all") {
      page = "news";
      var sub = head === "news" ? (r.parts[1] || "arsenal") : (head === "europe" ? "others" : "all");
      key = "news/" + sub;
      if (key !== lastView) resetFilters();
      if (sub === "others") renderOthers(); else renderFeedPage(sub === "all" ? "all" : "arsenal");
    }
    else { page = "home"; renderHome(); }
    lastView = key || head;
    currentPage = page;
    renderChrome(page);
    if (opts.focus) { var v = el("view"); if (v) v.focus({ preventScroll: true }); }
  }

  // ---------- boot ----------
  var loading = false;
  function load() {
    if (loading) return;
    loading = true;
    fetch(SNAPSHOT_URL, { cache: "no-store" })
      .then(function (r) { if (!r.ok) throw new Error("HTTP " + r.status); return r.json(); })
      .then(function (data) {
        var first = !DATA;
        DATA = data;
        meta = data.meta || meta;
        route({ soft: !first });
        scheduleLive();
      })
      .catch(function (e) {
        if (DATA) return;   // keep what is on screen
        setView('<div class="group"><p class="empty">Could not load the latest data (' + esc(e.message) + '). Check the connection, then reopen the app.</p></div>');
      })
      .then(function () { loading = false; });
  }

  // minute and countdown tick without a re-render
  setInterval(function () {
    if (!DATA) return;
    document.querySelectorAll("[data-clock]").forEach(function (n) {
      var ev = findEvent(n.getAttribute("data-clock"));
      if (ev) n.textContent = liveMinute(statusOf(ev));
    });
    document.querySelectorAll("[data-countdown]").forEach(function (n) { n.textContent = countdown(n.getAttribute("data-countdown")); });
  }, 15000);

  window.addEventListener("hashchange", function () {
    var r = parseHash();
    // switching match centre tabs keeps the scroll position; anything else starts at the top
    if (!(r.parts[0] === "match" && r.params.tab)) window.scrollTo(0, 0);
    route({ focus: !(r.parts[0] === "match" && r.params.tab) });
  });
  // coming back to the app (unlocking the phone, switching apps) fetches straight away
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible" && DATA && Date.now() - (Date.parse(DATA.generated_at) || 0) > 60000) load();
  });
  el("refresh").addEventListener("click", function () {
    var b = el("refresh");
    b.classList.add("is-busy");
    b.disabled = true;
    fetch("refresh", { method: "POST" }).catch(function () {}).then(function () {
      b.classList.remove("is-busy");
      b.disabled = false;
      load();
    });
  });
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(function () {});

  // every minute while a match is in its window, every five otherwise
  setInterval(function () { if (currentEvent()) load(); }, 60000);
  setInterval(function () { if (!currentEvent()) load(); }, 5 * 60000);
  load();
})();

/* Arsenal Tracker - Broadcast Dark interactions */
(function () {
  "use strict";

  // 1. stagger card entrance
  document.querySelectorAll(".feed .card").forEach(function (c, i) {
    c.style.animationDelay = Math.min(i * 35, 600) + "ms";
  });

  // 2. live countdown to kickoff
  function fmtCountdown(target) {
    var diff = target - Date.now();
    if (diff <= 0) return "now";
    var d = Math.floor(diff / 86400000);
    var h = Math.floor((diff % 86400000) / 3600000);
    var m = Math.floor((diff % 3600000) / 60000);
    if (d > 0) return d + "d " + h + "h";
    if (h > 0) return h + "h " + m + "m";
    return m + "m";
  }
  document.querySelectorAll("[data-countdown]").forEach(function (cd) {
    var when = new Date(cd.getAttribute("data-countdown")).getTime();
    if (isNaN(when)) return;
    var tick = function () { cd.textContent = "in " + fmtCountdown(when); };
    tick();
    setInterval(tick, 30000);
  });


  // 3. the opponent XI starts collapsed on a phone, open on desktop
  if (window.innerWidth <= 640) {
    var oppXI = document.querySelector("details.opp-lineup");
    if (oppXI) oppXI.removeAttribute("open");
  }

  // 4. gentle auto-refresh of the page every 5 min (keeps it live)
  setTimeout(function () { location.reload(); }, 5 * 60 * 1000);

  // 5. register service worker for PWA / installable app
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(function () {});
  }
})();

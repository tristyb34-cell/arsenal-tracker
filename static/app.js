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
  var cd = document.querySelector("[data-countdown]");
  if (cd) {
    var when = new Date(cd.getAttribute("data-countdown")).getTime();
    if (!isNaN(when)) {
      var tick = function () { cd.textContent = "in " + fmtCountdown(when); };
      tick();
      setInterval(tick, 30000);
    }
  }

  // 3. confetti when a "here we go" lands (hero or any card)
  function confetti() {
    var canvas = document.getElementById("confetti");
    if (!canvas) return;
    canvas.style.display = "block";
    var ctx = canvas.getContext("2d");
    canvas.width = innerWidth; canvas.height = innerHeight;
    var colors = ["#ef0107", "#ffffff", "#e0a93a", "#1f9e57"];
    var bits = [];
    for (var i = 0; i < 140; i++) {
      bits.push({
        x: Math.random() * canvas.width, y: -20 - Math.random() * canvas.height * 0.5,
        r: 4 + Math.random() * 6, c: colors[(Math.random() * colors.length) | 0],
        vy: 2 + Math.random() * 4, vx: -2 + Math.random() * 4,
        rot: Math.random() * 6, vr: -0.2 + Math.random() * 0.4
      });
    }
    var frames = 0;
    (function draw() {
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      bits.forEach(function (b) {
        b.x += b.vx; b.y += b.vy; b.rot += b.vr;
        ctx.save(); ctx.translate(b.x, b.y); ctx.rotate(b.rot);
        ctx.fillStyle = b.c; ctx.fillRect(-b.r / 2, -b.r / 2, b.r, b.r * 0.6);
        ctx.restore();
      });
      frames++;
      if (frames < 160) requestAnimationFrame(draw);
      else canvas.style.display = "none";
    })();
  }
  // fire once per session if a fresh "here we go" is on screen
  var hwg = document.querySelector('[data-hwg="1"]');
  if (hwg && !sessionStorage.getItem("hwg-celebrated")) {
    sessionStorage.setItem("hwg-celebrated", "1");
    setTimeout(confetti, 500);
  }

  // 4. gentle auto-refresh of the page every 5 min (keeps it live)
  setTimeout(function () { location.reload(); }, 5 * 60 * 1000);

  // 5. register service worker for PWA / installable app
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(function () {});
  }
})();

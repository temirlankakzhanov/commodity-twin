// Dev-only frame meter, loaded only with ?debug=fps (see motion.js). Shows the current fps,
// the 95th percentile frame time and the number of frames over 20 ms since the last reset.
// window.__fps.stats() returns the same numbers; window.__fps.reset() clears them.
(function () {
  "use strict";

  var SLOW_MS = 20;
  var frames = [];
  var slow = 0;
  var last = 0;
  var box = document.createElement("div");
  box.setAttribute("aria-hidden", "true");
  box.style.cssText =
    "position:fixed;left:8px;bottom:8px;z-index:9999;padding:6px 8px;border-radius:3px;" +
    "background:rgb(0 0 0 / 0.8);color:#f4f4f5;font:11px/1.4 ui-monospace,monospace;" +
    "pointer-events:none;white-space:pre";
  box.textContent = "fps meter: waiting for frames";
  document.body.appendChild(box);

  function percentile(values, p) {
    if (!values.length) return 0;
    var sorted = values.slice().sort(function (a, b) {
      return a - b;
    });
    return sorted[Math.min(sorted.length - 1, Math.floor(p * sorted.length))];
  }

  function stats() {
    var recent = frames.slice(-60);
    var mean = recent.reduce(function (s, v) {
      return s + v;
    }, 0) / Math.max(recent.length, 1);
    return {
      fps: mean ? Math.round(1000 / mean) : 0,
      p95: Math.round(percentile(frames, 0.95) * 10) / 10,
      over20: slow,
      frames: frames.length,
    };
  }

  function tick(now) {
    if (last) {
      var dt = now - last;
      frames.push(dt);
      if (frames.length > 2000) frames.shift();
      if (dt > SLOW_MS) slow += 1;
    }
    last = now;
    if (frames.length % 10 === 0) {
      var s = stats();
      box.textContent = s.fps + " fps\np95 " + s.p95 + " ms\n>20 ms: " + s.over20;
    }
    window.requestAnimationFrame(tick);
  }

  window.__fps = {
    stats: stats,
    reset: function () {
      frames = [];
      slow = 0;
      last = 0;
    },
  };
  window.requestAnimationFrame(tick);
})();

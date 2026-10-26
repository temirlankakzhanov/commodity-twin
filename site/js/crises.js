// Crises: four episode cards filled from site.json. Each card has one big number, one line, a
// sparkline of its own series and a "?" with dates, units and method. Nothing is pinned; with
// GSAP and no reduced-motion preference each line draws once when its card is reached. A mouse
// hover on a line shows date and value (touch and keyboard get the static card).
(function () {
  "use strict";

  var MINUS = "−";
  var SVG_NS = "http://www.w3.org/2000/svg";
  var W = 300;
  var H = 80;

  function fixed(value, digits) {
    return (value < 0 ? MINUS : "") + Math.abs(value).toFixed(digits);
  }
  function formatDate(iso) {
    return new Date(iso + "T00:00:00Z").toLocaleDateString("en-GB", {
      day: "numeric",
      month: "short",
      year: "numeric",
      timeZone: "UTC",
    });
  }
  function shortDate(iso) {
    return formatDate(iso).replace(/ \d{4}$/, "");
  }
  function monthYear(iso) {
    return new Date(iso + "T00:00:00Z").toLocaleDateString("en-GB", { month: "short", year: "numeric", timeZone: "UTC" });
  }
  function para(text) {
    var p = document.createElement("p");
    p.textContent = text;
    return p;
  }

  // Sparkline: one path in a 300x80 box; a dashed zero line when the series crosses zero; a soft
  // band for the episode window. Returns what the hover needs.
  function spark(card, points, unit, digits, windowRange) {
    var svg = card.querySelector(".crisis-svg");
    var values = points.map(function (p) {
      return p[1];
    });
    var lo = Math.min.apply(null, values);
    var hi = Math.max.apply(null, values);
    if (lo > 0) lo = 0;
    var pad = (hi - lo) * 0.06 || 1;
    lo -= lo < 0 ? pad : 0;
    hi += pad;
    var n = points.length;
    var x = function (i) {
      return (i / (n - 1)) * W;
    };
    var y = function (v) {
      return H - ((v - lo) / (hi - lo)) * H;
    };
    var add = function (tag, attrs) {
      var node = document.createElementNS(SVG_NS, tag);
      Object.keys(attrs).forEach(function (k) {
        node.setAttribute(k, attrs[k]);
      });
      svg.appendChild(node);
      return node;
    };
    if (windowRange) {
      var a = points.findIndex(function (p) {
        return p[0] >= windowRange[0];
      });
      if (a >= 0) add("rect", { x: x(a).toFixed(1), y: 0, width: (W - x(a)).toFixed(1), height: H, class: "spark-window" });
    }
    if (lo < 0) add("line", { x1: 0, x2: W, y1: y(0).toFixed(1), y2: y(0).toFixed(1), class: "spark-zero" });
    var d = points
      .map(function (p, i) {
        return (i ? "L" : "M") + x(i).toFixed(1) + " " + y(p[1]).toFixed(1);
      })
      .join("");
    var path = add("path", { d: d, class: "spark-line" });
    return { path: path, points: points, unit: unit, digits: digits, y: y, n: n };
  }

  // Mouse hover only: the box is read once per hover, moves are transforms.
  function hover(card, sp) {
    var box = card.querySelector(".crisis-spark");
    var dot = box.querySelector(".spark-dot");
    var tip = box.querySelector(".spark-tip");
    var rect = null;
    var pending = null;
    var shown = -1;
    function place(i) {
      if (i === shown || !rect) return;
      shown = i;
      var plotTop = 14; // .crisis-spark padding-top
      var plotH = rect.height - plotTop;
      var px = (i / (sp.n - 1)) * rect.width;
      var py = plotTop + (sp.y(sp.points[i][1]) / H) * plotH;
      dot.style.transform = "translate(" + px.toFixed(1) + "px," + (py - plotTop).toFixed(1) + "px)";
      tip.textContent = formatDate(sp.points[i][0]) + " · " + fixed(sp.points[i][1], sp.digits) + " " + sp.unit;
      var w = tip.offsetWidth;
      var tx = Math.max(0, Math.min(rect.width - w, px - w / 2));
      tip.style.transform = "translateX(" + tx.toFixed(1) + "px)";
      box.classList.add("is-on");
    }
    box.addEventListener("pointerenter", function (event) {
      if (event.pointerType === "mouse") rect = box.getBoundingClientRect();
    });
    box.addEventListener("pointermove", function (event) {
      if (event.pointerType !== "mouse") return;
      if (!rect) rect = box.getBoundingClientRect();
      var rel = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
      var i = Math.round(rel * (sp.n - 1));
      if (pending === null) {
        pending = window.requestAnimationFrame(function () {
          pending = null;
          place(i);
        });
      }
    });
    box.addEventListener("pointerleave", function () {
      rect = null;
      shown = -1;
      box.classList.remove("is-on");
    });
  }

  function info(card, paragraphs) {
    var pop = card.querySelector(".info-pop");
    pop.textContent = "";
    paragraphs.forEach(function (text) {
      if (text) pop.appendChild(para(text));
    });
  }

  function wireInfo(section) {
    var buttons = Array.prototype.slice.call(section.querySelectorAll(".info-button"));
    function closeAll(except) {
      buttons.forEach(function (b) {
        if (b === except) return;
        b.setAttribute("aria-expanded", "false");
        document.getElementById(b.getAttribute("aria-controls")).hidden = true;
      });
    }
    buttons.forEach(function (b) {
      var pop = document.getElementById(b.getAttribute("aria-controls"));
      b.addEventListener("click", function () {
        var open = b.getAttribute("aria-expanded") !== "true";
        closeAll(b);
        b.setAttribute("aria-expanded", open ? "true" : "false");
        pop.hidden = !open;
      });
      [b, pop].forEach(function (node) {
        node.addEventListener("keydown", function (event) {
          if (event.key !== "Escape") return;
          closeAll();
          b.focus();
        });
      });
    });
    document.addEventListener("click", function (event) {
      if (!event.target.closest || !event.target.closest("#crises .info")) closeAll();
    });
  }

  function fill(section, site) {
    var c = site.crises;
    var pw = c.portwatch;
    var get = function (key) {
      return section.querySelector('[data-crisis="' + key + '"]');
    };
    var set = function (card, field, text) {
      card.querySelector('[data-c="' + field + '"]').textContent = text;
    };
    var sparks = [];

    // WTI, April 2020: the raw print and what the model does with it.
    var wti = c.wti_2020;
    var card = get("wti-2020");
    var next = wti.model_next_day;
    set(card, "number", fixed(wti.low.value, 2) + " USD/bbl");
    set(card, "label", "settlement on " + formatDate(wti.low.date) + ", as reported");
    set(
      card,
      "line",
      "The model keeps the previous price (" + fixed(wti.model_value, 2) + "); the drop lands on " + shortDate(next.date) +
        ": USD " + Math.round(next.loss_usd_m).toLocaleString("en-US") + " m loss on the book."
    );
    set(card, "source", wti.source);
    info(card, [
      wti.note,
      "The loss is for the unhedged plan-implied book used in the Validation tab, and it is the largest single-day loss in that backtest.",
    ]);
    sparks.push([card, spark(card, wti.series, "USD/bbl", 2, null), "WTI daily price in 2020, low " + fixed(wti.low.value, 2) + " on " + formatDate(wti.low.date)]);

    // Brent, 2022: the peak and the first print of the year.
    var brent = c.brent_2022;
    card = get("brent-2022");
    var first = brent.series[0];
    set(card, "number", fixed(brent.peak.value, 2) + " USD/bbl");
    set(card, "label", "highest daily price of 2022, " + formatDate(brent.peak.date));
    set(card, "line", "From " + fixed(first[1], 2) + " on " + formatDate(first[0]) + ", the first print of the year.");
    set(card, "source", brent.source);
    info(card, ["Daily spot prices for 2022, as published. The card shows the series only; it makes no claim about causes."]);
    sparks.push([card, spark(card, brent.series, "USD/bbl", 2, null), "Brent daily price in 2022, peak " + fixed(brent.peak.value, 2) + " on " + formatDate(brent.peak.date)]);

    // PortWatch episodes: one rule for both cards.
    var windowNote = "The window is our own editorial choice, not an official definition of the event.";
    var rule = "Rule: " + pw.rule + " Unit: " + pw.unit + ".";

    var red = pw.episodes["red-sea"];
    var bab = red[0];
    var suez = red[1];
    card = get("red-sea");
    set(card, "number", fixed(bab.before_mean, 1) + " → " + fixed(bab.lowest_week.value, 1));
    set(card, "label", "calls/day · lowest week to " + formatDate(bab.lowest_week.week_end));
    set(
      card,
      "line",
      "Suez, its own lowest week: " + fixed(suez.before_mean, 1) + " → " + fixed(suez.lowest_week.value, 1) + " (to " + formatDate(suez.lowest_week.week_end) + ")."
    );
    set(card, "source", pw.source);
    info(card, [
      rule,
      "Window " + monthYear(bab.window[0]) + " to " + monthYear(bab.window[1]) + "; before: " + formatDate(bab.before_period[0]) + " to " + formatDate(bab.before_period[1]) + ". Each strait shows its own lowest week.",
      windowNote,
      "No monitor flags here: the monitor window starts Sep 2025.",
    ]);
    sparks.push([card, spark(card, bab.weekly, "calls/day", 1, bab.window), "Bab el-Mandeb weekly transit calls, " + fixed(bab.before_mean, 1) + " before the window, lowest week " + fixed(bab.lowest_week.value, 1)]);

    var hz = pw.episodes.hormuz[0];
    card = get("hormuz");
    var latest = (site.chokepoint_status.places || []).filter(function (p) {
      return p.chokepoint === "Strait of Hormuz";
    })[0];
    set(card, "number", fixed(hz.before_mean, 1) + " → " + fixed(hz.lowest_week.value, 1));
    set(card, "label", "calls/day · lowest week (to " + formatDate(hz.lowest_week.week_end) + ")");
    set(
      card,
      "line",
      "2025 average against the lowest week since " + formatDate(hz.window[0]) + "." +
        (latest && latest.status ? " Latest 7 days: " + fixed(latest.status.recent_mean, 1) + ", as in the monitor." : "")
    );
    set(card, "source", pw.source);
    var flags = [];
    var ms = site.monitor_series;
    if (ms && ms.series["Strait of Hormuz"]) {
      var start = new Date(ms.start + "T00:00:00Z").getTime();
      var iso = function (i) {
        return new Date(start + i * 86400000).toISOString().slice(0, 10);
      };
      ms.series["Strait of Hormuz"].flagged.forEach(function (run) {
        if (iso(run[1]) >= hz.window[0]) flags.push(shortDate(iso(run[0])) + "–" + formatDate(iso(run[1])));
      });
    }
    info(card, [
      rule,
      "Window " + formatDate(hz.window[0]) + " to " + formatDate(hz.window[1]) + "; before: the 2025 calendar year.",
      windowNote,
      flags.length ? "Monitor flags inside the window: " + flags.join(", ") + "." : "",
    ]);
    sparks.push([card, spark(card, hz.weekly, "calls/day", 1, hz.window), "Strait of Hormuz weekly transit calls, " + fixed(hz.before_mean, 1) + " in 2025, lowest week " + fixed(hz.lowest_week.value, 1)]);

    sparks.forEach(function (s) {
      s[0].querySelector(".crisis-svg").setAttribute("aria-label", s[2] + ".");
      hover(s[0], s[1]);
    });
    return sparks;
  }

  function init() {
    var section = document.getElementById("crises");
    if (!section || !window.SITE_DATA) return;
    // After story.js (registered first), so its pin is in place when these triggers are made.
    Promise.all([window.SITE_DATA, window.SITE_DOM_READY]).then(function (results) {
      var sparks = fill(section, results[0][1]);
      wireInfo(section);
      if (document.documentElement.getAttribute("data-motion") !== "gsap" || !window.SITE_MOTION) return;
      var gsap = window.gsap;
      var M = window.SITE_MOTION;
      var mm = gsap.matchMedia();
      // Everything below lives in one matchMedia context: no motion with reduced motion, and a
      // ScrollTrigger.refresh() (resize, the pin shortening after a takeover) recomputes it all.
      mm.add("(prefers-reduced-motion: no-preference)", function () {
        // (1) The console steps back as this section comes up: a slight scale-down and dim,
        // scrubbed by the same scroll that carries it away. No pin, no extra scroll; the
        // controls stay clickable. Promoted only while the exit is running.
        var consoleNode = document.querySelector(".console");
        var savedOrigin = null;
        if (consoleNode) {
          gsap.fromTo(
            consoleNode,
            { scale: 1, opacity: 1 },
            {
              scale: 0.96,
              opacity: 0.55,
              ease: "none",
              immediateRender: false,
              scrollTrigger: {
                trigger: section,
                start: "top bottom",
                end: "top 40%",
                scrub: true,
                // The pinned scene scales the console about Hormuz on the way in; the exit
                // scales it about its top edge, and hands the old origin back when scrolled
                // back above this range.
                onToggle: function (self) {
                  if (self.isActive) {
                    if (savedOrigin === null) savedOrigin = consoleNode.style.transformOrigin;
                    consoleNode.style.transformOrigin = "50% 0%";
                    consoleNode.style.willChange = "transform, opacity";
                  } else {
                    consoleNode.style.willChange = "";
                    if (self.progress === 0 && savedOrigin !== null) {
                      consoleNode.style.transformOrigin = savedOrigin;
                      savedOrigin = null;
                    }
                  }
                },
              },
            }
          );
        }
        // (2) The heading rises once, line by line, when it is well in view.
        var head = section.querySelectorAll(".crises-head > *");
        M.reveal(gsap, head, { y: 24, opacity: 0, duration: 0.6, stagger: 0.08, ease: "power2.out" }, section.querySelector(".crises-head"), "top 80%");
        // (3) The cards follow in turn; each line draws left to right once its card is in.
        var grid = section.querySelector(".crisis-grid");
        var cards = sparks.map(function (s) {
          return s[0];
        });
        M.reveal(gsap, cards, { y: 32, opacity: 0, duration: 0.6, stagger: 0.12, ease: "power2.out" }, grid, "top 75%");
        M.once(grid, "top 75%", function () {
          sparks.forEach(function (s, i) {
            M.draw(gsap, s[1].path, { duration: 1.2, delay: 0.35 + i * 0.12 });
          });
        });
        window.ScrollTrigger.refresh();
      });
      window.addEventListener("beforeprint", function () {
        mm.revert();
      });
    }).catch(function (error) {
      console.error("Crises section unavailable:", error);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

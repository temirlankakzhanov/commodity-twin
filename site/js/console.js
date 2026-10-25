// The console: three tabbed panels filled from site.json.
//
// story.js owns the pinned scene. It calls SITE_CONSOLE.build(site) once, then, in pinned mode,
// SITE_CONSOLE.attach(timeline, at) to add the scroll sub-steps after the transition. Each
// sub-step is a timeline label ("console:<id>") with a focus state, so later demos can hook onto
// the same points. Scroll picks the tab and sub-step until the visitor uses a tab; from then on
// the tabs are theirs for the rest of the visit and scroll no longer changes them.
(function () {
  "use strict";

  var MINUS = "−";
  var SVG_NS = "http://www.w3.org/2000/svg";
  var int = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
  var narrow = window.matchMedia("(max-width: 760px)");
  var ICONS = {
    PASS: ["M1.8 6.4 4.8 9.3 10.4 2.9"],
    REVIEW: ["M6 1.6 10.8 10.2H1.2Z", "M6 5.2v2.1", "M6 8.7v.01"],
    FAIL: ["M2 2 10 10", "M10 2 2 10"],
  };
  // Scroll sub-steps, in order. `focus` is the console's data-focus value (see site.css).
  var STEPS = [
    { tab: 0, id: "flows-active", label: "Routes the plan uses" },
    { tab: 0, id: "flows-total", label: "Plan margin and volume" },
    { tab: 1, id: "monitor-strait", label: "Pick a strait: Hormuz" },
    { tab: 1, id: "monitor-count", label: "Flag count" },
    { tab: 2, id: "verdicts-settings", label: "Backtest settings" },
    { tab: 2, id: "verdicts-grid", label: "Verdicts" },
  ];
  var STEP_UNITS = 0.65; // timeline units per sub-step (story.js: 1 unit = 50vh)

  var root = null;
  var tabs = [];
  var panels = [];
  var manual = false;
  var current = { tab: 0, step: -1 };

  function fixed(value, digits) {
    return (value < 0 ? MINUS : "") + Math.abs(value).toFixed(digits);
  }
  function signed(value, digits) {
    return (value > 0 ? "+" : "") + fixed(value, digits);
  }
  function formatDate(iso) {
    return new Date(iso + "T00:00:00Z").toLocaleDateString("en-GB", {
      day: "numeric",
      month: "short",
      year: "numeric",
      timeZone: "UTC",
    });
  }
  function make(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function icon(paths, circle, className) {
    var svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("class", className || "tag-icon");
    svg.setAttribute("viewBox", "0 0 12 12");
    svg.setAttribute("aria-hidden", "true");
    if (circle) {
      var c = document.createElementNS(SVG_NS, "circle");
      c.setAttribute("cx", "6");
      c.setAttribute("cy", "6");
      c.setAttribute("r", "5");
      svg.appendChild(c);
    }
    paths.forEach(function (d) {
      var p = document.createElementNS(SVG_NS, "path");
      p.setAttribute("d", d);
      svg.appendChild(p);
    });
    return svg;
  }
  function rows(dl, pairs) {
    dl.textContent = "";
    pairs.forEach(function (pair) {
      dl.appendChild(make("dt", "", pair[0]));
      dl.appendChild(make("dd", "", pair[1]));
    });
  }

  // ------------------------------------------------------------------ content

  function fill(site) {
    var get = function (key) {
      return root.querySelector('[data-h="' + key + '"]');
    };

    // Optimal flows: the base-case plan, every route.
    var base = site.hormuz_closure.base;
    get("flows-status").textContent = "solver: " + base.status;
    get("flows-label").textContent = site.network.label + ".";
    var body = get("flows-rows");
    body.textContent = "";
    base.routes.forEach(function (r) {
      var active = r.status === "ACTIVE";
      var tr = make("tr", active ? "is-active" : "is-idle");
      tr.appendChild(make("td", "", r.route.replace("-", " → ")));
      tr.appendChild(make("td", "cell-sub", r.chokepoints === "-" ? "none" : r.chokepoints.replace(/, /g, " · ")));
      tr.appendChild(make("td", "num", int.format(r.flow_kbd)));
      tr.appendChild(make("td", "num", fixed(r.margin_usd_bbl, 2)));
      var status = make("td");
      var tag = make("span", "tag " + (active ? "tag-active" : "tag-idle"));
      tag.appendChild(make("span", "tag-mark"));
      tag.appendChild(document.createTextNode(r.status));
      status.appendChild(tag);
      tr.appendChild(status);
      body.appendChild(tr);
    });
    rows(get("flows-foot"), [
      ["plan margin", int.format(base.daily_margin_usd) + " USD/day"],
      ["volume shipped", int.format(base.volume_kbd) + " kb/d"],
      ["prices as of", formatDate(site.as_of.prices)],
    ]);

    // Monitor: the latest reading per chokepoint, flagged or not.
    var method = site.monitor_method;
    var readings = site.monitor;
    var flagged = readings.filter(function (m) {
      return m.flagged;
    });
    get("monitor-method").textContent =
      "IMF PortWatch transit calls at " +
      site.facts.chokepoints_monitored +
      " chokepoints: a 7-day average is compared with a " +
      method.baseline_window_days +
      "-day baseline lagged " +
      method.baseline_gap_days +
      " days.";
    get("monitor-date").textContent = "reading of " + formatDate(readings[0].date) + " · calls/day";
    get("monitor-summary").textContent = flagged.length + " of " + readings.length + " flagged";
    var mbody = get("monitor-rows");
    mbody.textContent = "";
    readings.forEach(function (m) {
      var tr = make("tr", m.chokepoint === "Strait of Hormuz" ? "is-hormuz" : "");
      tr.appendChild(make("td", "", m.chokepoint));
      tr.appendChild(make("td", "num", m.ma7.toFixed(1)));
      tr.appendChild(make("td", "num", m.baseline.toFixed(1)));
      tr.appendChild(make("td", "num", signed(Math.round(m.pct_change * 100), 0) + "%"));
      tr.appendChild(make("td", "num", signed(m.zscore, 2)));
      var flag = make("td");
      if (m.flagged) {
        var chip = make("span", "alert-chip");
        chip.appendChild(icon(["M2.6 9.4 9.4 2.6"], true, "alert-icon"));
        chip.appendChild(document.createTextNode("flagged"));
        flag.appendChild(chip);
      } else {
        flag.appendChild(make("span", "tag tag-idle", "no flag"));
      }
      tr.appendChild(flag);
      mbody.appendChild(tr);
    });
    var traffic = site.hormuz_traffic;
    var hormuz = readings.filter(function (m) {
      return m.chokepoint === "Strait of Hormuz";
    })[0];
    var source = "Unit: " + site.chokepoint_status.unit + ". Source: " + site.sources.portwatch + ".";
    // Explain the non-flag at Hormuz only when the data show one.
    get("monitor-note").textContent =
      hormuz && !hormuz.flagged
        ? "Hormuz is not flagged: its baseline (" +
          hormuz.baseline.toFixed(1) +
          ") has already absorbed most of the drop from the " +
          traffic.period_2025[0].slice(0, 4) +
          " average of " +
          traffic.mean_2025.toFixed(1) +
          ". " +
          source
        : source;

    // Verdicts, with the settings they depend on right next to them.
    var v = site.validation;
    var models = v.models;
    get("verdicts-meta").textContent = models.length + " models";
    var exp = v.settings.exposures_usd;
    rows(get("verdicts-settings"), [
      ["confidence", Math.round(v.settings.confidence * 100) + "%"],
      ["window", v.settings.window_days + " days"],
      ["forecasts", int.format(models[0].observations) + " days from " + formatDate(v.settings.first_forecast)],
      ["book", v.settings.book],
      [
        "exposure",
        Object.keys(exp)
          .sort(function (a, b) {
            return exp[b] - exp[a];
          })
          .map(function (k) {
            return k + " " + (exp[k] / 1e9).toFixed(2) + "bn USD";
          })
          .join(" · "),
      ],
    ]);
    get("verdicts-note").textContent = v.note;
    var list = get("verdicts-list");
    list.textContent = "";
    models.forEach(function (m) {
      var li = make("li", "verdict");
      var label = make("span", "verdict-label verdict-" + m.verdict.toLowerCase());
      label.appendChild(icon(ICONS[m.verdict] || [], m.verdict === "FAIL"));
      label.appendChild(document.createTextNode(m.verdict));
      li.appendChild(label);
      li.appendChild(make("p", "verdict-model", m.model));
      var stats = make("ul", "verdict-stats");
      [
        "exceptions " + m.exceptions,
        "expected " + m.expected,
        "Kupiec p " + m.kupiec_p.toFixed(4),
        "CC p " + m.cond_coverage_p.toFixed(4),
        "Basel zone " + m.basel_zone,
        "ES Z2 " + fixed(m.es_z2, 2),
      ].forEach(function (stat) {
        stats.appendChild(make("li", "", stat));
      });
      li.appendChild(stats);
      list.appendChild(li);
    });
  }

  // ------------------------------------------------------------------ tabs and disclosures

  function select(index, options) {
    current.tab = index;
    tabs.forEach(function (tab, i) {
      var on = i === index;
      tab.setAttribute("aria-selected", on ? "true" : "false");
      tab.tabIndex = on ? 0 : -1;
      panels[i].classList.toggle("is-selected", on);
    });
    closeInfo();
    if (options && options.focus) tabs[index].focus();
    // Stacked layout (wide screen, not pinned): the tab jumps to its panel.
    var stacked = document.documentElement.getAttribute("data-story") !== "pinned" && !narrow.matches;
    if (options && options.user && stacked) {
      var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      panels[index].scrollIntoView({ behavior: reduce ? "auto" : "smooth", block: "start" });
    }
  }

  function takeOver(index, focus) {
    if (!manual) {
      manual = true;
      root.removeAttribute("data-focus");
    }
    select(index, { focus: focus, user: true });
  }

  function closeInfo(except) {
    root.querySelectorAll(".info-button").forEach(function (button) {
      if (button === except) return;
      button.setAttribute("aria-expanded", "false");
      document.getElementById(button.getAttribute("aria-controls")).hidden = true;
    });
  }

  function wire() {
    tabs.forEach(function (tab, i) {
      tab.addEventListener("click", function () {
        takeOver(i, false);
      });
      tab.addEventListener("keydown", function (event) {
        var next = null;
        if (event.key === "ArrowRight") next = (i + 1) % tabs.length;
        else if (event.key === "ArrowLeft") next = (i - 1 + tabs.length) % tabs.length;
        else if (event.key === "Home") next = 0;
        else if (event.key === "End") next = tabs.length - 1;
        if (next === null) return;
        event.preventDefault();
        takeOver(next, true);
      });
    });
    root.querySelectorAll(".info-button").forEach(function (button) {
      var pop = document.getElementById(button.getAttribute("aria-controls"));
      button.addEventListener("click", function () {
        var open = button.getAttribute("aria-expanded") !== "true";
        closeInfo(button);
        button.setAttribute("aria-expanded", open ? "true" : "false");
        pop.hidden = !open;
      });
      pop.addEventListener("keydown", function (event) {
        if (event.key === "Escape") {
          closeInfo();
          button.focus();
        }
      });
      button.addEventListener("keydown", function (event) {
        if (event.key === "Escape") closeInfo();
      });
    });
    document.addEventListener("click", function (event) {
      if (!event.target.closest || !event.target.closest(".info")) closeInfo();
    });
  }

  // ------------------------------------------------------------------ scroll sub-steps

  // Called by the scrubbed timeline; does nothing once the visitor has taken over.
  function autoStep(index) {
    if (manual || index === current.step) return;
    current.step = index;
    var step = STEPS[index];
    if (step.tab !== current.tab) select(step.tab);
    root.setAttribute("data-focus", step.id);
  }

  window.SITE_CONSOLE = {
    steps: STEPS,
    units: STEPS.length * STEP_UNITS,

    build: function (site) {
      root = document.querySelector(".console");
      if (!root) return false;
      tabs = Array.prototype.slice.call(root.querySelectorAll('[role="tab"]'));
      panels = tabs.map(function (tab) {
        return document.getElementById(tab.getAttribute("aria-controls"));
      });
      fill(site);
      wire();
      return true;
    },

    // Adds one label per sub-step and a linear proxy whose value picks the sub-step. Returns the
    // time at which the sub-steps end.
    attach: function (tl, at) {
      var proxy = { p: 0 };
      STEPS.forEach(function (step, i) {
        step.at = at + i * STEP_UNITS;
        tl.addLabel("console:" + step.id, step.at);
      });
      current.step = -1;
      tl.fromTo(
        proxy,
        { p: 0 },
        {
          p: STEPS.length,
          duration: STEPS.length * STEP_UNITS,
          ease: "none",
          immediateRender: false,
          onUpdate: function () {
            autoStep(Math.min(STEPS.length - 1, Math.floor(proxy.p)));
          },
        },
        at
      );
      return at + STEPS.length * STEP_UNITS;
    },

    // Before the sub-steps (scrolled back up), the console rests on the first one.
    reset: function () {
      autoStep(0);
    },

    // Pinned mode: the console is inert until it has grown in.
    setLive: function (on) {
      if (!root) return;
      if (on) root.removeAttribute("inert");
      else root.setAttribute("inert", "");
    },

    // Leaving pinned mode: no focus dimming, everything readable.
    unpin: function () {
      if (!root) return;
      root.removeAttribute("inert");
      root.removeAttribute("data-focus");
      current.step = -1;
    },
  };
})();

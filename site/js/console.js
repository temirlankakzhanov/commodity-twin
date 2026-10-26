// The console: three tabbed panels filled from site.json.
//
// story.js owns the pinned scene. It calls SITE_CONSOLE.build(site, geo) once, then, in pinned mode,
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
  // Scroll sub-steps, in order: each is a timeline label ("console:<id>"); the auto demo below
  // runs across them.
  var STEPS = [
    { tab: 0, id: "flows-active", label: "Routes the plan uses" },
    { tab: 0, id: "flows-total", label: "Plan margin and volume" },
    { tab: 1, id: "monitor-strait", label: "Pick a strait: Hormuz" },
    { tab: 1, id: "monitor-count", label: "Flag count" },
    { tab: 2, id: "verdicts-settings", label: "Backtest settings" },
    { tab: 2, id: "verdicts-grid", label: "Verdicts" },
  ];
  var STEP_UNITS = 0.65; // timeline units per sub-step (story.js: 1 unit = 50vh)
  var TAIL_UNITS = 0.6; // after a takeover the console keeps only this much pinned scroll

  var SHORT = {
    "Strait of Hormuz": "Hormuz",
    "Bab el-Mandeb Strait": "Bab el-Mandeb",
    "Suez Canal": "Suez",
    "Malacca Strait": "Malacca",
    "Panama Canal": "Panama",
    "Cape of Good Hope": "Cape",
  };
  var root = null;
  var monitorLine = null; // the Monitor traffic path, drawn once by the stacked-layout reveal
  // Setters the auto demo uses instead of clicks (no DOM events, so no takeover); filled in by
  // each tab's builder.
  var demo = {};
  var tabs = [];
  var panels = [];
  var manual = false;
  var current = { tab: 0 };

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

  function alertChip(text) {
    var chip = make("span", "alert-chip");
    chip.appendChild(icon(["M2.6 9.4 9.4 2.6"], true, "alert-icon"));
    chip.appendChild(document.createTextNode(text));
    return chip;
  }

  // Gentle fade on content that changed; skipped without GSAP or with reduced motion.
  function refresh(nodes) {
    var still =
      document.documentElement.getAttribute("data-motion") !== "gsap" ||
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (still) return;
    nodes.forEach(function (node) {
      if (node.animate) {
        node.animate(
          [
            { opacity: 0.35, transform: "translateY(4px)" },
            { opacity: 1, transform: "none" },
          ],
          { duration: 220, easing: "ease-out" }
        );
      }
    });
  }

  // ------------------------------------------------------------------ optimiser scenarios

  // The route map: land, lanes, ports and straits from geo.json (the hero map's projection).
  // The frame spans the world's width plus a margin, so a lane that wraps across the Pacific
  // (stored as two pieces) shows both ends at the edges, each with an arrowhead and an HTML
  // "Pacific" label. Everything is placed from coordinates once; nothing reads the layout.
  function routeMap(svg, geo, names, edges) {
    var pieces = {};
    var ys = [];
    var xs = [];
    names.forEach(function (name) {
      pieces[name] = geo.routes[name]
        .split("M")
        .filter(Boolean)
        .map(function (seg) {
          var nums = seg.match(/-?\d+(\.\d+)?/g).map(Number);
          var pts = [];
          for (var i = 0; i + 1 < nums.length; i += 2) {
            pts.push([nums[i], nums[i + 1]]);
            xs.push(nums[i]);
            ys.push(nums[i + 1]);
          }
          return pts;
        });
    });
    var world = geo.viewBox;
    var minX = Math.min(world[0], Math.min.apply(null, xs)) - 14;
    var maxX = Math.max(world[0] + world[2], Math.max.apply(null, xs)) + 14;
    var minY = Math.min.apply(null, ys) - 30;
    var maxY = Math.max.apply(null, ys) + 30;
    var vb = [minX, minY, maxX - minX, maxY - minY];
    svg.setAttribute(
      "viewBox",
      vb
        .map(function (v) {
          return v.toFixed(1);
        })
        .join(" ")
    );
    var add = function (tag, attrs) {
      var node = document.createElementNS(SVG_NS, tag);
      Object.keys(attrs).forEach(function (k) {
        node.setAttribute(k, attrs[k]);
      });
      svg.appendChild(node);
      return node;
    };
    // Arrowhead at p pointing from q to p.
    var arrow = function (p, q) {
      var a = Math.atan2(p[1] - q[1], p[0] - q[0]);
      var s = 7;
      var pt = function (ang, r) {
        return (p[0] + Math.cos(ang) * r).toFixed(1) + " " + (p[1] + Math.sin(ang) * r).toFixed(1);
      };
      return add("path", { d: "M" + pt(a, 0) + "L" + pt(a + 2.6, s) + "L" + pt(a - 2.6, s) + "Z", class: "rm-arrow" });
    };
    var pct = function (p) {
      return [((p[0] - vb[0]) / vb[2]) * 100, ((p[1] - vb[1]) / vb[3]) * 100];
    };
    add("path", { d: geo.land, class: "rm-land" });
    var lanes = {};
    names.forEach(function (name) {
      var segs = pieces[name];
      var lane = { path: add("path", { d: geo.routes[name], class: "rm-lane" }), arrows: [], edges: [] };
      for (var i = 0; i + 1 < segs.length; i += 1) {
        var out = segs[i];
        var back = segs[i + 1];
        var end = out[out.length - 1];
        var start = back[0];
        lane.arrows.push(arrow(end, out[out.length - 2]));
        // The re-entering piece: arrowhead a little inside its start, pointing along the lane.
        lane.arrows.push(arrow(back[1], start));
        var left = end[0] < start[0] ? end : start;
        var right = end[0] < start[0] ? start : end;
        var l = pct(left);
        var r = pct(right);
        edges.left.style.left = l[0].toFixed(2) + "%";
        edges.left.style.top = l[1].toFixed(2) + "%";
        edges.right.style.left = r[0].toFixed(2) + "%";
        edges.right.style.top = r[1].toFixed(2) + "%";
        edges.left.hidden = false;
        edges.right.hidden = false;
        lane.edges = [edges.left, edges.right];
      }
      lanes[name] = lane;
    });
    Object.keys(geo.ports).forEach(function (name) {
      var xy = geo.ports[name];
      add("circle", { cx: xy[0], cy: xy[1], r: 3.2, class: "rm-port" });
    });
    var straits = {};
    Object.keys(geo.chokepoints).forEach(function (name) {
      var xy = geo.chokepoints[name];
      straits[name] = add("circle", { cx: xy[0], cy: xy[1], r: 3.6, class: "rm-strait" });
    });
    return { lanes: lanes, straits: straits };
  }

  function laneItem(name, flow, status, via, cut) {
    var li = make("li", "lane" + (status === "ACTIVE" ? " is-active" : " is-idle") + (cut ? " is-closed" : ""));
    li.setAttribute("data-route", name);
    li.appendChild(make("span", "lane-name", name.replace("-", " → ")));
    li.appendChild(make("span", "lane-flow", int.format(flow) + " kb/d"));
    var tag = make("span", "lane-status tag " + (status === "ACTIVE" ? "tag-active" : "tag-idle"));
    tag.appendChild(make("span", "tag-mark"));
    tag.appendChild(document.createTextNode(status));
    li.appendChild(tag);
    var line = make("span", "lane-via", via);
    if (cut) line.appendChild(alertChip("closed (scenario)"));
    li.appendChild(line);
    return li;
  }

  function optimiser(site, geo, get) {
    var data = site.scenarios;
    var routeChokes = {};
    site.network.routes.forEach(function (r) {
      routeChokes[r.name] = r.chokepoints;
    });
    var names = site.network.routes.map(function (r) {
      return r.name;
    });
    var viaText = function (name) {
      var list = routeChokes[name];
      return list.length
        ? "via " +
            list
              .map(function (n) {
                return SHORT[n] || n;
              })
              .join(" · ")
        : "no chokepoint";
    };

    get("flows-label").textContent = site.network.label + ".";
    get("flows-short").textContent = data.label;

    var edges = { left: get("edge-left"), right: get("edge-right") };
    edges.left.hidden = true;
    edges.right.hidden = true;
    var map = routeMap(get("route-map"), geo, names, edges);
    var mapSvg = get("route-map");
    var key = get("route-map-key");
    var note = get("scenario-note");
    var foot = get("flows-foot");
    var extra = get("flows-extra");
    var detail = get("scenario-detail");
    var nameLine = get("scenario-name");
    var activeList = get("lanes-active");
    var idleList = get("lanes-idle");
    var toggle = get("idle-toggle");
    var summary = root.querySelector(".scenario-summary");
    var idleCount = 0;
    var idleCut = 0;

    function toggleText() {
      var open = toggle.getAttribute("aria-expanded") === "true";
      toggle.textContent =
        (open ? "Hide " : "Show ") +
        idleCount +
        " idle lane" +
        (idleCount === 1 ? "" : "s") +
        (idleCut ? " · " + idleCut + " closed" : "");
    }
    // Fade the bottom of the idle box while rows remain below (read on scroll and on change only).
    function updateFade() {
      var more = !idleList.hidden && idleList.scrollTop + idleList.clientHeight < idleList.scrollHeight - 2;
      idleList.classList.toggle("has-more", more);
    }
    idleList.addEventListener("scroll", updateFade, { passive: true });
    toggle.addEventListener("click", function () {
      var open = toggle.getAttribute("aria-expanded") !== "true";
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      idleList.hidden = !open;
      toggleText();
      updateFade();
    });

    function show(id, animate) {
      var sc = data.items[id];
      var closed = sc.closed[0] || null;
      activeList.textContent = "";
      idleList.textContent = "";
      idleCount = 0;
      idleCut = 0;
      sc.routes.forEach(function (r) {
        var cut = closed !== null && routeChokes[r.route].indexOf(closed) >= 0;
        var item = laneItem(r.route, r.flow_kbd, r.status, viaText(r.route), cut);
        if (r.status === "ACTIVE") {
          activeList.appendChild(item);
        } else {
          idleList.appendChild(item);
          idleCount += 1;
          if (cut) idleCut += 1;
        }
        var lane = map.lanes[r.route];
        var on = r.status === "ACTIVE";
        lane.path.setAttribute("class", "rm-lane" + (on ? " is-active" : ""));
        lane.arrows.forEach(function (a) {
          a.setAttribute("class", "rm-arrow" + (on ? " is-active" : ""));
        });
        lane.edges.forEach(function (e) {
          e.classList.toggle("is-active", on);
        });
      });
      toggleText();
      idleList.scrollTop = 0;
      updateFade();
      Object.keys(map.straits).forEach(function (name) {
        map.straits[name].setAttribute("class", "rm-strait" + (name === closed ? " is-closed" : ""));
      });
      key.textContent = "";
      if (closed) key.appendChild(alertChip(closed + ": closed (scenario)"));
      else key.textContent = "All chokepoints open.";
      mapSvg.setAttribute(
        "aria-label",
        "Illustrative network map, " +
          (closed ? closed + " closed (scenario)" : "base case") +
          ": lanes used by the plan are highlighted."
      );

      nameLine.textContent = (closed ? closed + " closed" : "Base case") + ":";
      var delta = sc.delta_daily_margin_usd;
      // One block per KPI (label above its own value); <div> groups are valid inside <dl>.
      foot.textContent = "";
      [
        ["plan margin, USD/day", int.format(sc.daily_margin_usd)],
        ["change vs base, USD/day", (delta < 0 ? MINUS : delta > 0 ? "+" : "") + int.format(Math.abs(delta))],
        ["no open route, kb/d", int.format(sc.stranded_kbd)],
      ].forEach(function (pair) {
        var block = make("div", "kpi");
        block.appendChild(make("dt", "", pair[0]));
        block.appendChild(make("dd", "", pair[1]));
        foot.appendChild(block);
      });
      note.textContent = !sc.feasible
        ? "No feasible plan for this scenario."
        : closed && sc.same_as_base
          ? "Same as base case: no planned cargo uses this chokepoint."
          : "";

      // Behind the "?": the rest of the numbers and the lanes the closure removes.
      rows(extra, [
        ["volume shipped", int.format(sc.volume_kbd) + " kb/d"],
        ["solver", sc.status],
        ["prices as of", formatDate(site.as_of.prices)],
      ]);
      var lanes = sc.removed_idle_routes.map(function (n) {
        return n.replace("-", " → ") + " (idle)";
      });
      var plural = lanes.length > 1 ? "s" : "";
      detail.textContent = !closed
        ? "Base case: every chokepoint open."
        : sc.same_as_base
          ? lanes.length
            ? "Also removes backup lane" + plural + ": " + lanes.join(", ") + "."
            : "No backup lane is removed."
          : lanes.length
            ? "Also removes idle lane" + plural + ": " + lanes.join(", ") + "."
            : "";
      if (animate) refresh([summary, activeList]);
    }

    var bar = get("scenario-bar");
    bar.textContent = "";
    var chips = data.order.map(function (id) {
      var sc = data.items[id];
      var chip = make("button", "scenario-chip" + (sc.closed.length ? " is-closure" : ""));
      chip.type = "button";
      chip.setAttribute("aria-pressed", id === "base" ? "true" : "false");
      chip.setAttribute("data-demo", "chip-" + id);
      chip.setAttribute("data-scenario", id);
      if (sc.closed.length) {
        chip.appendChild(icon(["M2.6 9.4 9.4 2.6"], true, "alert-icon"));
        chip.appendChild(document.createTextNode("Close " + (SHORT[sc.closed[0]] || sc.closed[0])));
        chip.setAttribute("aria-label", "Close " + sc.closed[0] + " (scenario)");
      } else {
        chip.appendChild(document.createTextNode(sc.name));
      }
      bar.appendChild(chip);
      return chip;
    });
    chips.forEach(function (chip) {
      chip.addEventListener("click", function () {
        if (chip.getAttribute("aria-pressed") === "true") return;
        chips.forEach(function (c) {
          c.setAttribute("aria-pressed", c === chip ? "true" : "false");
        });
        stopAuto(); // a visitor choosing a scenario takes over the console, without a jump
        show(chip.getAttribute("data-scenario"), true);
      });
    });
    show("base", false);

    demo.scenario = function (id) {
      chips.forEach(function (c) {
        c.setAttribute("aria-pressed", c.getAttribute("data-scenario") === id ? "true" : "false");
      });
      show(id, false);
    };
    demo.idle = function (open) {
      if ((toggle.getAttribute("aria-expanded") === "true") === open) return;
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      idleList.hidden = !open;
      toggleText();
      updateFade();
    };
  }

  // ------------------------------------------------------------------ monitor

  function slug(name) {
    return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
  }
  function niceMax(v) {
    var step = Math.pow(10, Math.floor(Math.log10(v)));
    var m = v / step;
    var nice = [1, 1.2, 1.6, 2, 2.4, 3, 4, 5, 6, 8, 10].filter(function (c) {
      return c >= m;
    })[0];
    return nice * step;
  }

  // Why the last reading is or is not flagged, written from the two real conditions: two short
  // visible lines, plus the baseline-window detail for the "?" box.
  var ZSCORE = "z\u2011score"; // non-breaking hyphen
  function reason(latest, data) {
    var pct = Math.round(latest.pct_change * 100);
    var pctText = Math.abs(pct) + "% " + (pct < 0 ? "below" : "above") + " its baseline";
    var zLimit = fixed(data.z_threshold, 0);
    var pLimit = fixed(data.pct_threshold * 100, 0) + "%";
    var z = fixed(latest.zscore, 2);
    var detail =
      "In the baseline window the 7\u2011day average ranged from " + latest.window_min + " to " +
      latest.window_max + " calls/day (spread " + latest.spread + ").";
    if (latest.flagged) {
      return { lines: ["Flagged: " + pctText + ", past " + pLimit + ".", "Its " + ZSCORE + " is " + z + ", below " + zLimit + "."], detail: detail };
    }
    if (latest.pct_condition) {
      return {
        lines: ["Not flagged: " + pctText + " passes the " + pLimit + " test.", "But its " + ZSCORE + " is " + z + ", not below " + zLimit + "."],
        detail: detail + " Against that spread, the gap reads as normal noise.",
      };
    }
    return {
      lines: ["Not flagged: " + pctText + ", inside the " + pLimit + " line.", "Its " + ZSCORE + " is " + z + " (flag needs below " + zLimit + ")."],
      detail: detail,
    };
  }

  function monitor(site, get) {
    var data = site.monitor_series;
    var method = site.monitor_method;
    var readings = site.monitor;
    // Same chip order as the optimiser scenarios; any other chokepoint follows.
    var order = site.scenarios.order
      .map(function (id) {
        return (site.scenarios.items[id].closed || [])[0];
      })
      .filter(function (name) {
        return name && data.series[name];
      });
    var names = order.concat(
      Object.keys(data.series).filter(function (name) {
        return order.indexOf(name) < 0;
      })
    );
    var n = data.series[names[0]].ma7.length;
    var start = new Date(data.start + "T00:00:00Z");
    var dayISO = function (i) {
      return new Date(start.getTime() + i * 86400000).toISOString().slice(0, 10);
    };
    var flagged = readings.filter(function (m) {
      return m.flagged;
    });
    get("monitor-summary").textContent = flagged.length + " of " + readings.length + " flagged today";
    get("monitor-method").textContent =
      "IMF PortWatch transit calls at " + names.length + " chokepoints: a " + data.short_window_days +
      "-day average is compared with a " + method.baseline_window_days + "-day baseline lagged " +
      method.baseline_gap_days + " days.";
    get("monitor-rule").textContent =
      "A reading is flagged when traffic is more than " + Math.abs(data.pct_threshold * 100) +
      "% below baseline and the " + ZSCORE + " is below " + fixed(data.z_threshold, 0) + ". Last reading " +
      formatDate(readings[0].date) + ".";
    get("monitor-source").textContent = "Unit: transit calls per day, all vessel types. Source: " + data.source + ".";

    var svg = get("monitor-svg");
    var W = 600;
    var H = 240;
    var add = function (tag, attrs) {
      var node = document.createElementNS(SVG_NS, tag);
      Object.keys(attrs).forEach(function (k) {
        node.setAttribute(k, attrs[k]);
      });
      svg.appendChild(node);
      return node;
    };
    var bands = add("g", { class: "mc-bands" });
    var grid = add("g", { class: "mc-grid" });
    var basePath = add("path", { class: "mc-baseline" });
    var trafficPath = add("path", { class: "mc-traffic" });
    monitorLine = trafficPath;
    var axisY = get("monitor-axis-y");
    var axisX = get("monitor-axis-x");
    var cross = get("monitor-cross");
    var tip = get("monitor-tip");
    var chart = root.querySelector(".monitor-chart");
    var dotT = cross.querySelector(".cross-traffic");
    var dotB = cross.querySelector(".cross-baseline");

    // Month ticks along the shared date axis (computed once).
    axisX.textContent = "";
    for (var i = 0; i < n; i += 1) {
      var iso = dayISO(i);
      if (iso.slice(8) === "01" && Number(iso.slice(5, 7)) % 3 === 1) {
        var tick = make("span", "", new Date(iso + "T00:00:00Z").toLocaleDateString("en-GB", { month: "short", year: "2-digit", timeZone: "UTC" }));
        tick.style.left = ((i / (n - 1)) * 100).toFixed(2) + "%";
        axisX.appendChild(tick);
      }
    }

    var cur = null;
    var yMax = 1;
    var pathFor = function (values) {
      var d = "";
      var pen = false;
      values.forEach(function (v, k) {
        if (v === null) {
          pen = false;
          return;
        }
        d += (pen ? "L" : "M") + ((k / (n - 1)) * W).toFixed(1) + " " + (H - (v / yMax) * H).toFixed(1);
        pen = true;
      });
      return d;
    };

    function show(name, animate) {
      var s = data.series[name];
      cur = s;
      // A switch during the one-time draw ends it: the new line is shown whole.
      if (window.gsap) window.gsap.killTweensOf(trafficPath);
      trafficPath.style.strokeDasharray = "";
      trafficPath.style.strokeDashoffset = "";
      var all = s.ma7.concat(s.baseline).filter(function (v) {
        return v !== null;
      });
      yMax = niceMax(Math.max.apply(null, all) * 1.05);
      trafficPath.setAttribute("d", pathFor(s.ma7));
      basePath.setAttribute("d", pathFor(s.baseline));
      bands.textContent = "";
      s.flagged.forEach(function (run) {
        var x0 = (Math.max(0, run[0] - 0.5) / (n - 1)) * W;
        var x1 = (Math.min(n - 1, run[1] + 0.5) / (n - 1)) * W;
        var r = document.createElementNS(SVG_NS, "rect");
        r.setAttribute("x", x0.toFixed(1));
        r.setAttribute("width", Math.max(1.5, x1 - x0).toFixed(1));
        r.setAttribute("y", "0");
        r.setAttribute("height", String(H));
        bands.appendChild(r);
      });
      grid.textContent = "";
      axisY.textContent = "";
      for (var g = 0; g <= 4; g += 1) {
        var v = (yMax / 4) * g;
        var y = H - (v / yMax) * H;
        var line = document.createElementNS(SVG_NS, "line");
        line.setAttribute("x1", "0");
        line.setAttribute("x2", String(W));
        line.setAttribute("y1", y.toFixed(1));
        line.setAttribute("y2", y.toFixed(1));
        grid.appendChild(line);
        var label = make("span", "", int.format(v));
        label.style.top = ((y / H) * 100).toFixed(2) + "%";
        axisY.appendChild(label);
      }
      svg.setAttribute(
        "aria-label",
        name + ": 7-day average transit calls and the monitor baseline, " + formatDate(data.start) + " to " +
        formatDate(dayISO(n - 1)) + ". " + s.flagged.length + " flagged period" + (s.flagged.length === 1 ? "" : "s") + ". Values are in the tooltip and in the table view."
      );

      var L = s.latest;
      get("monitor-name").textContent = name + ":";
      var kpis = get("monitor-kpis");
      kpis.textContent = "";
      [
        ["7-day avg, calls/day", fixed(L.ma7, 1)],
        ["baseline, calls/day", fixed(L.baseline, 1)],
        ["vs baseline", (L.pct_change > 0 ? "+" : "") + fixed(Math.round(L.pct_change * 100), 0) + "%"],
      ].forEach(function (pair) {
        var block = make("div", "kpi");
        block.appendChild(make("dt", "", pair[0]));
        block.appendChild(make("dd", "", pair[1]));
        kpis.appendChild(block);
      });
      var verdict = get("monitor-verdict");
      verdict.textContent = "";
      if (L.flagged) verdict.appendChild(alertChip("flagged"));
      else verdict.appendChild(make("span", "tag tag-idle", "no flag today"));
      var why = reason(L, data);
      var reasonNode = get("monitor-reason");
      reasonNode.textContent = "";
      why.lines.forEach(function (line) {
        reasonNode.appendChild(make("span", "reason-line", line));
      });
      get("monitor-detail").textContent = name + ": " + why.detail;

      // Table view: weekly points ending on the last reading.
      var box = get("monitor-table");
      var table = make("table", "term-table");
      table.appendChild(make("caption", "visually-hidden", name + ": weekly readings"));
      var head = make("tr");
      ["week ending", "7-day avg", "baseline", "flag"].forEach(function (h, k) {
        var th = make("th", k && k < 3 ? "num" : "", h);
        th.scope = "col";
        head.appendChild(th);
      });
      var thead = make("thead");
      thead.appendChild(head);
      table.appendChild(thead);
      var tbody = make("tbody");
      var isFlag = function (k) {
        return s.flagged.some(function (run) {
          return k >= run[0] && k <= run[1];
        });
      };
      for (var k = n - 1; k >= 0; k -= 7) {
        var tr = make("tr");
        tr.appendChild(make("td", "", formatDate(dayISO(k))));
        tr.appendChild(make("td", "num", s.ma7[k] === null ? "–" : fixed(s.ma7[k], 1)));
        tr.appendChild(make("td", "num", s.baseline[k] === null ? "–" : fixed(s.baseline[k], 1)));
        var td = make("td");
        if (isFlag(k)) td.appendChild(alertChip("flagged"));
        else td.textContent = "no";
        tr.appendChild(td);
        tbody.appendChild(tr);
      }
      table.appendChild(tbody);
      box.textContent = "";
      box.appendChild(table);
      box.scrollTop = 0;
      tableFade();
      hideCross();
      if (animate) refresh([svg, root.querySelector(".monitor-side .scenario-summary")]);
    }

    // Crosshair: the chart box is read once per hover; moves are transform-only, one per frame.
    var box = null;
    var pending = null;
    var shown = -1;
    function flaggedAt(k) {
      return cur.flagged.some(function (run) {
        return k >= run[0] && k <= run[1];
      });
    }
    function hideCross() {
      cross.classList.remove("is-on");
      tip.classList.remove("is-on");
      shown = -1;
    }
    function place(idx) {
      if (!box || idx === shown) return;
      shown = idx;
      var x = (idx / (n - 1)) * box.width;
      var t = cur.ma7[idx];
      var b = cur.baseline[idx];
      cross.style.transform = "translateX(" + x.toFixed(1) + "px)";
      dotT.style.transform = "translateY(" + (t === null ? -99 : box.height - (t / yMax) * box.height).toFixed(1) + "px)";
      dotB.style.transform = "translateY(" + (b === null ? -99 : box.height - (b / yMax) * box.height).toFixed(1) + "px)";
      tip.textContent =
        formatDate(dayISO(idx)) + " · traffic " + (t === null ? "–" : fixed(t, 1)) + " · baseline " +
        (b === null ? "–" : fixed(b, 1)) + " calls/day";
      if (flaggedAt(idx)) tip.appendChild(alertChip("flagged"));
      // Keep the tooltip inside the chart box: right of the line, or left of it, clamped.
      var w = tip.offsetWidth;
      var tx = x + 8 + w <= box.width ? x + 8 : x - 8 - w;
      tx = Math.max(0, Math.min(box.width - w, tx));
      tip.style.transform = "translateX(" + tx.toFixed(1) + "px)";
      cross.classList.add("is-on");
      tip.classList.add("is-on");
    }
    chart.addEventListener("pointerenter", function () {
      box = chart.getBoundingClientRect();
    });
    chart.addEventListener("pointermove", function (event) {
      if (!box) box = chart.getBoundingClientRect();
      var rel = Math.min(1, Math.max(0, (event.clientX - box.left) / box.width));
      var idx = Math.round(rel * (n - 1));
      if (pending === null) {
        pending = window.requestAnimationFrame(function () {
          pending = null;
          place(idx);
        });
      }
    });
    chart.addEventListener("pointerleave", function () {
      box = null;
      hideCross();
    });
    chart.addEventListener("focus", function () {
      box = chart.getBoundingClientRect();
      place(n - 1);
    });
    chart.addEventListener("blur", hideCross);
    chart.addEventListener("keydown", function (event) {
      var step = event.shiftKey ? 7 : 1;
      var next = null;
      if (event.key === "ArrowLeft") next = Math.max(0, (shown < 0 ? n - 1 : shown) - step);
      else if (event.key === "ArrowRight") next = Math.min(n - 1, (shown < 0 ? n - 1 : shown) + step);
      else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = n - 1;
      if (next === null) return;
      event.preventDefault();
      if (!box) box = chart.getBoundingClientRect();
      place(next);
    });

    var toggle = get("monitor-table-toggle");
    var table = get("monitor-table");
    // The table takes the chart's place (same box size), so the panel height never changes.
    var legend = get("monitor-legend");
    // Same bottom fade as the idle-lanes box while rows remain below.
    function tableFade() {
      var more = !table.hidden && table.scrollTop + table.clientHeight < table.scrollHeight - 2;
      table.classList.toggle("has-more", more);
    }
    table.addEventListener("scroll", tableFade, { passive: true });
    toggle.addEventListener("click", function () {
      var open = toggle.getAttribute("aria-expanded") !== "true";
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      table.hidden = !open;
      chart.hidden = open;
      legend.hidden = open;
      if (open) hideCross();
      toggle.textContent = open ? "Show as chart" : "Show as table";
      tableFade();
    });

    var bar = get("monitor-chips");
    bar.textContent = "";
    var first = names.indexOf("Strait of Hormuz") >= 0 ? "Strait of Hormuz" : names[0];
    var chips = names.map(function (name) {
      var chip = make("button", "scenario-chip");
      chip.type = "button";
      chip.setAttribute("aria-pressed", name === first ? "true" : "false");
      chip.setAttribute("data-demo", "monitor-chip-" + slug(name));
      chip.textContent = SHORT[name] || name;
      chip.setAttribute("aria-label", name);
      chip.addEventListener("click", function () {
        if (chip.getAttribute("aria-pressed") === "true") return;
        chips.forEach(function (c) {
          c.setAttribute("aria-pressed", c === chip ? "true" : "false");
        });
        stopAuto();
        show(name, true);
      });
      bar.appendChild(chip);
      return chip;
    });
    show(first, false);

    demo.chart = chart;
    demo.cross = function (idx) {
      if (idx === null) {
        hideCross();
        return;
      }
      if (!box) box = chart.getBoundingClientRect();
      place(idx);
    };
    demo.dropCrossBox = function () {
      box = null;
    };
    // The longest flagged period of the shown chokepoint, as day indices, and the axis length.
    demo.sweep = function () {
      var best = null;
      cur.flagged.forEach(function (run) {
        if (!best || run[1] - run[0] > best[1] - best[0]) best = run;
      });
      return { run: best || [0, n - 1], n: n };
    };
  }

  // ------------------------------------------------------------------ validation

  var usdm = new Intl.NumberFormat("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
  function money(v) {
    return (v < 0 ? MINUS : "") + usdm.format(Math.abs(v));
  }
  function pText(p) {
    return p < 0.0001 ? "p < 0.0001" : "p = " + p.toFixed(4);
  }
  function pct(x) {
    return Math.round(x * 100) + "%";
  }
  function capital(text) {
    return text.charAt(0).toUpperCase() + text.slice(1);
  }

  // The verdict sentence, built only from the model's numbers and the verdict rule in site.json
  // (FAIL: red zone or CC p below fail_level; REVIEW: yellow zone or a p-value below review_level).
  function verdictSentence(m, rule) {
    var zone = m.exc_last_250 + " exception" + (m.exc_last_250 === 1 ? "" : "s") + " in the last " +
      rule.basel_window_days + " days put it in the Basel " + m.basel_zone + " zone";
    var reasons = [];
    if (m.verdict === "FAIL") {
      if (m.cond_coverage_p < rule.fail_level) {
        reasons.push("the conditional-coverage test rejects it (" + pText(m.cond_coverage_p) + ", below " + pct(rule.fail_level) + ")");
      }
      if (m.basel_zone === "red") reasons.push(zone);
      return capital(reasons.join(", and ")) + ".";
    }
    if (m.verdict === "REVIEW") {
      var coverageOk = m.kupiec_p >= rule.review_level && m.cond_coverage_p >= rule.review_level;
      if (m.basel_zone === "yellow") reasons.push(zone);
      if (m.kupiec_p < rule.review_level) reasons.push("Kupiec " + pText(m.kupiec_p) + " is below " + pct(rule.review_level));
      if (m.cond_coverage_p < rule.review_level) reasons.push("conditional-coverage " + pText(m.cond_coverage_p) + " is below " + pct(rule.review_level));
      return (coverageOk ? "Coverage tests pass, but " : "") + (coverageOk ? reasons.join(", and ") : capital(reasons.join(", and "))) + ".";
    }
    return (
      "Coverage tests pass (Kupiec " + pText(m.kupiec_p) + ", CC " + pText(m.cond_coverage_p) + ") and the last " +
      rule.basel_window_days + " days are in the Basel " + m.basel_zone + " zone."
    );
  }

  var VERDICT_ICON = { PASS: [ICONS.PASS, false], REVIEW: [ICONS.REVIEW, false], FAIL: [ICONS.FAIL, true] };

  function verdictLabel(verdict) {
    var label = make("span", "verdict-label verdict-" + verdict.toLowerCase());
    var spec = VERDICT_ICON[verdict] || [[], false];
    label.appendChild(icon(spec[0], spec[1]));
    label.appendChild(document.createTextNode(verdict));
    return label;
  }

  function validation(site, get) {
    var v = site.validation;
    var models = v.models;
    var set = v.settings;
    var exp = set.exposures_usd;
    var bookAmounts = Object.keys(exp)
      .sort(function (a, b) {
        return exp[b] - exp[a];
      })
      .map(function (k) {
        return k + " " + (exp[k] / 1e9).toFixed(2) + "bn";
      })
      .join(", ");
    get("val-book").textContent =
      "Unhedged plan-implied book (" + bookAmounts + " USD): a model test, not a trading record.";
    get("val-settings").textContent =
      Math.round(set.confidence * 100) + "% VaR · " + set.window_days + "-day window · " +
      int.format(models[0].observations) + " daily forecasts from " + formatDate(set.first_forecast);
    get("val-rule").textContent =
      "Verdict rule: FAIL if the Basel zone is red or the conditional-coverage p is below " + pct(v.rule.fail_level) +
      "; REVIEW if the zone is yellow or a p-value is below " + pct(v.rule.review_level) + "; otherwise PASS.";
    get("val-note").textContent = v.note;

    var current = models[0];
    var series = null;
    var tape = get("val-tape");
    var canvas = get("val-canvas");
    var years = get("val-years");
    var marker = get("val-marker");
    var markerLabel = get("val-marker-label");
    var lead = get("val-marker-lead");
    var dot = get("val-marker-dot");
    var cross = get("val-cross");
    var tip = get("val-tip");
    var status = get("val-status");
    var tableBox = get("val-table");
    var toggle = get("val-table-toggle");
    var legend = get("val-legend");
    var scale = { yMax: 1 };
    var hits = {};
    var dates = [];

    function dateAt(i) {
      return dates[i];
    }

    function summary(m, animate) {
      get("val-name").textContent = m.model + ":";
      var verdict = get("val-verdict");
      verdict.textContent = "";
      verdict.appendChild(verdictLabel(m.verdict));
      get("val-sentence").textContent = verdictSentence(m, v.rule);
      var kpis = get("val-kpis");
      kpis.textContent = "";
      [
        ["exceptions", int.format(m.exceptions)],
        ["expected", String(m.expected)],
        ["last " + v.rule.basel_window_days + " days", m.exc_last_250 + " · " + m.basel_zone],
      ].forEach(function (pair) {
        var block = make("div", "kpi");
        block.appendChild(make("dt", "", pair[0]));
        block.appendChild(make("dd", "", pair[1]));
        kpis.appendChild(block);
      });
      rows(get("val-tests"), [
        ["model", m.model],
        ["Kupiec", pText(m.kupiec_p)],
        ["cond. coverage", pText(m.cond_coverage_p)],
        ["ES Z2", fixed(m.es_z2, 2) + " (above 0: ES too low)"],
        ["Basel zone", m.basel_zone + " (" + m.exc_last_250 + " in the last " + v.rule.basel_window_days + " days)"],
      ]);
      if (animate) refresh([root.querySelector("#panel-validation .scenario-summary")]);
    }

    // The tape: one canvas, drawn once per model or width change. Per pixel column it shows the
    // largest loss and the mean VaR; exception days are ticks in a strip below.
    function draw() {
      if (!series) return;
      var width = tape.clientWidth;
      var height = tape.clientHeight;
      if (!width || !height) return;
      var dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.round(width * dpr);
      canvas.height = Math.round(height * dpr);
      canvas.style.width = width + "px";
      canvas.style.height = height + "px";
      var ctx = canvas.getContext("2d");
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, height);
      var strip = 14;
      var gap = 6;
      var top = 46; // the band above holds the marker label
      var base = height - strip - gap - 16; // year labels below the strip
      var plotH = base - top;
      var n = series.loss.length;
      var varArr = series.models[current.model].var;
      scale.base = base;
      scale.top = top;
      scale.plotH = plotH;
      scale.width = width;
      ctx.strokeStyle = "rgb(42 42 46)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(0, base + 0.5);
      ctx.lineTo(width, base + 0.5);
      ctx.stroke();
      var cols = Math.max(1, Math.floor(width));
      var maxLoss = new Float64Array(cols);
      var varSum = new Float64Array(cols);
      var varCount = new Uint16Array(cols);
      for (var i = 0; i < n; i += 1) {
        var c = Math.min(cols - 1, Math.floor((i / (n - 1)) * (cols - 1)));
        if (series.loss[i] > maxLoss[c]) maxLoss[c] = series.loss[i];
        varSum[c] += varArr[i];
        varCount[c] += 1;
      }
      var y = function (val) {
        return base - (Math.min(val, scale.yMax) / scale.yMax) * plotH;
      };
      ctx.fillStyle = "rgb(82 82 91)";
      for (var k = 0; k < cols; k += 1) {
        if (maxLoss[k] > 0) {
          var yy = y(maxLoss[k]);
          ctx.fillRect(k, yy, 1, base - yy);
        }
      }
      ctx.strokeStyle = "#ff6a1f";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      var pen = false;
      for (var q = 0; q < cols; q += 1) {
        if (!varCount[q]) continue;
        var vy = y(varSum[q] / varCount[q]);
        if (pen) ctx.lineTo(q + 0.5, vy);
        else ctx.moveTo(q + 0.5, vy);
        pen = true;
      }
      ctx.stroke();
      ctx.fillStyle = "#e5383b";
      series.models[current.model].exceptions.forEach(function (idx) {
        var x = (idx / (n - 1)) * (width - 1);
        ctx.fillRect(Math.round(x) - 1, base + gap, 2, strip);
      });
      // Bars clipped at the top get a bright cap so the clipping is visible.
      ctx.fillStyle = "#f4f4f5";
      for (var t = 0; t < cols; t += 1) {
        if (maxLoss[t] > scale.yMax) ctx.fillRect(t - 2, top - 4, 5, 3);
      }
      placeMarker();
    }

    function placeMarker() {
      var ext = series.extremes && series.extremes.largest_loss;
      if (!ext) return;
      var idx = series.offsets.indexOf(ext.offset);
      if (idx < 0) return;
      var x = (idx / (series.loss.length - 1)) * (scale.width - 1);
      var dotY = scale.top - 9; // just above the cap of the (clipped) bar
      marker.style.transform = "translateX(" + x.toFixed(1) + "px)";
      lead.style.height = dotY - 5 + "px";
      dot.style.top = dotY + "px";
      marker.classList.toggle("is-left", x > scale.width * 0.6);
      marker.hidden = false;
    }

    function setYears() {
      years.textContent = "";
      var n = dates.length;
      var last = "";
      dates.forEach(function (iso, i) {
        var yr = iso.slice(0, 4);
        if (yr !== last) {
          last = yr;
          if (Number(yr) % 2 === 0 || n < 1500) {
            var span = make("span", "", yr);
            span.style.left = ((i / (n - 1)) * 100).toFixed(2) + "%";
            years.appendChild(span);
          }
        }
      });
    }

    function buildTable(m) {
      var table = make("table", "term-table");
      table.appendChild(make("caption", "visually-hidden", m.model + ": exception days"));
      var head = make("tr");
      ["date", "loss, USD m", "VaR, USD m", "excess"].forEach(function (h, k) {
        var th = make("th", k ? "num" : "", h);
        th.scope = "col";
        head.appendChild(th);
      });
      var thead = make("thead");
      thead.appendChild(head);
      table.appendChild(thead);
      var tbody = make("tbody");
      var varArr = series.models[m.model].var;
      series.models[m.model].exceptions.forEach(function (i) {
        var tr = make("tr");
        tr.appendChild(make("td", "", formatDate(dateAt(i))));
        tr.appendChild(make("td", "num", money(series.loss[i])));
        tr.appendChild(make("td", "num", money(varArr[i])));
        tr.appendChild(make("td", "num", money(series.loss[i] - varArr[i])));
        tbody.appendChild(tr);
      });
      table.appendChild(tbody);
      tableBox.textContent = "";
      tableBox.appendChild(table);
      tableBox.scrollTop = 0;
      tableFade();
    }

    function tableFade() {
      var more = !tableBox.hidden && tableBox.scrollTop + tableBox.clientHeight < tableBox.scrollHeight - 2;
      tableBox.classList.toggle("has-more", more);
    }
    tableBox.addEventListener("scroll", tableFade, { passive: true });
    function setTable(open) {
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      tableBox.hidden = !open;
      tape.hidden = open;
      legend.hidden = open;
      if (open) hideCross();
      toggle.textContent = open ? "Show as tape" : "Show as table";
      tableFade();
      if (!open) draw();
    }
    toggle.addEventListener("click", function () {
      setTable(toggle.getAttribute("aria-expanded") !== "true");
    });
    demo.table = function (open) {
      if ((toggle.getAttribute("aria-expanded") === "true") !== open) setTable(open);
    };

    function show(m, animate) {
      current = m;
      summary(m, animate);
      if (!series) return;
      hits = {};
      series.models[m.model].exceptions.forEach(function (i) {
        hits[i] = true;
      });
      var varArr = series.models[m.model].var.slice().sort(function (a, b) {
        return a - b;
      });
      var lossSorted = series.loss.slice().sort(function (a, b) {
        return a - b;
      });
      // The scale stops at the 99th percentile of losses and VaR; taller bars are clipped (capped).
      scale.yMax = Math.max(varArr[Math.floor(varArr.length * 0.99)], lossSorted[Math.floor(lossSorted.length * 0.99)]);
      tape.setAttribute(
        "aria-label",
        m.model + ": daily losses, VaR and " + m.exceptions + " exception days from " + formatDate(dateAt(0)) +
          " to " + formatDate(dateAt(dates.length - 1)) + ". Use the arrow keys to step through exceptions, or open the table."
      );
      hideCross();
      draw();
      buildTable(m);
    }

    // Crosshair: the tape box is read once per hover; moves are transform-only, one per frame.
    var box = null;
    var pending = null;
    var shown = -1;
    function hideCross() {
      cross.classList.remove("is-on");
      tip.classList.remove("is-on");
      marker.classList.remove("is-muted");
      shown = -1;
    }
    function place(idx) {
      if (!series || !box || idx === shown) return;
      marker.classList.add("is-muted");
      shown = idx;
      var n = series.loss.length;
      var x = (idx / (n - 1)) * (box.width - 1);
      cross.style.transform = "translateX(" + x.toFixed(1) + "px)";
      var varNow = series.models[current.model].var[idx];
      var loss = series.loss[idx];
      tip.textContent = "";
      tip.appendChild(
        make(
          "span",
          "",
          formatDate(dateAt(idx)) + " · " + (loss >= 0 ? "loss " + money(loss) : "gain " + money(-loss)) +
            " · VaR " + money(varNow) + " (USD m)"
        )
      );
      if (hits[idx]) tip.appendChild(alertChip("exception"));
      var left = x > box.width * 0.6;
      tip.style.transform = "translateX(" + (left ? x - 8 : x + 8).toFixed(1) + "px) translateX(" + (left ? "-100%" : "0") + ")";
      cross.classList.add("is-on");
      tip.classList.add("is-on");
    }
    tape.addEventListener("pointerenter", function () {
      box = tape.getBoundingClientRect();
    });
    tape.addEventListener("pointermove", function (event) {
      if (!series) return;
      if (!box) box = tape.getBoundingClientRect();
      var rel = Math.min(1, Math.max(0, (event.clientX - box.left) / box.width));
      var idx = Math.round(rel * (series.loss.length - 1));
      if (pending === null) {
        pending = window.requestAnimationFrame(function () {
          pending = null;
          place(idx);
        });
      }
    });
    tape.addEventListener("pointerleave", function () {
      box = null;
      hideCross();
    });
    tape.addEventListener("blur", hideCross);
    tape.addEventListener("keydown", function (event) {
      if (!series) return;
      var list = series.models[current.model].exceptions;
      var at = shown < 0 ? -1 : shown;
      var next = null;
      if (event.key === "ArrowRight") {
        next = list.filter(function (i) {
          return i > at;
        })[0];
      } else if (event.key === "ArrowLeft") {
        var before = list.filter(function (i) {
          return i < (at < 0 ? series.loss.length : at);
        });
        next = before[before.length - 1];
      } else if (event.key === "Home") next = 0;
      else if (event.key === "End") next = series.loss.length - 1;
      else return;
      event.preventDefault();
      if (next === undefined || next === null) return;
      box = tape.getBoundingClientRect();
      place(next);
    });

    if (window.ResizeObserver) {
      var lastW = 0;
      new window.ResizeObserver(function (entries) {
        var w = Math.round(entries[0].contentRect.width);
        if (w !== lastW) {
          lastW = w;
          draw();
        }
      }).observe(tape);
    }

    var bar = get("model-chips");
    bar.textContent = "";
    var chips = models.map(function (m, i) {
      var chip = make("button", "scenario-chip");
      chip.type = "button";
      chip.setAttribute("aria-pressed", i === 0 ? "true" : "false");
      chip.setAttribute("data-demo", "model-chip-" + slug(m.model));
      chip.textContent = m.model;
      chip.addEventListener("click", function () {
        if (chip.getAttribute("aria-pressed") === "true") return;
        chips.forEach(function (c) {
          c.setAttribute("aria-pressed", c === chip ? "true" : "false");
        });
        stopAuto();
        show(m, true);
      });
      bar.appendChild(chip);
      return chip;
    });
    summary(models[0], false);
    demo.model = function (index) {
      chips.forEach(function (c, i) {
        c.setAttribute("aria-pressed", i === index ? "true" : "false");
      });
      show(models[index], false);
    };

    // The daily series is preloaded in idle time (data.js); the summary above never waits for it.
    var pendingSeries = window.SITE_VALIDATION || Promise.reject(new Error("no loader"));
    pendingSeries.then(
      function (data) {
        series = data;
        var start = new Date(data.start + "T00:00:00Z").getTime();
        dates = data.offsets.map(function (o) {
          return new Date(start + o * 86400000).toISOString().slice(0, 10);
        });
        status.hidden = true;
        setYears();
        var np = data.negative_print;
        var ext = data.extremes.largest_loss;
        var gain = data.extremes.largest_gain;
        var worstDate = new Date(start + ext.offset * 86400000).toISOString().slice(0, 10);
        var gainDate = new Date(start + gain.offset * 86400000).toISOString().slice(0, 10);
        var carried = np && np.next_offset === ext.offset;
        markerLabel.textContent = carried
          ? "Largest loss in the test. WTI " + fixed(np.wti, 2) + " on " + formatDate(np.date).replace(/ \d{4}$/, "") + " was replaced by the previous price"
          : "Largest loss in the test";
        var gainIdx = data.offsets.indexOf(gain.offset);
        var gainHit = data.order.some(function (name) {
          return data.models[name].exceptions.indexOf(gainIdx) >= 0;
        });
        get("val-wti").textContent =
          (np
            ? "On " + formatDate(np.date) + " WTI settled at " + fixed(np.wti, 2) + " USD/bbl. A log return is undefined there, so price cleaning carries the previous price (" +
              fixed(np.model_wti, 2) + ") forward: that day stays in the test with no WTI move, and " + formatDate(worstDate) +
              " carries the whole drop, a loss of " + int.format(ext.loss) + " USD m, the largest in the test. "
            : "") +
          formatDate(gainDate) + " brought the largest gain (" + int.format(-gain.loss) + " USD m)" +
          (gainHit ? "." : ", not an exception: exceptions are losses above VaR.") +
          "";
        show(current, false);
      },
      function () {
        status.textContent = "The daily backtest could not be loaded. The verdicts above are complete.";
        status.classList.add("is-error");
      }
    );
  }

  // ------------------------------------------------------------------ content

  function fill(site, geo) {
    var get = function (key) {
      return root.querySelector('[data-h="' + key + '"]');
    };

    optimiser(site, geo, get);

    monitor(site, get);

    validation(site, get);
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

  function stopAuto() {
    if (manual) return;
    manual = true;
    endDemo();
    if (api.onTakeover) api.onTakeover();
  }

  function takeOver(index, focus) {
    stopAuto();
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
      // Any click outside the console's own "?" boxes closes them (including a "?" elsewhere).
      if (!event.target.closest || !event.target.closest(".console .info")) closeInfo();
    });
  }

  // ------------------------------------------------------------------ auto demo

  // Pinned layout only. A ghost cursor walks through the console while the visitor scrolls: its
  // position and every control it "clicks" are a pure function of the scroll position p (in
  // sub-step units, 0 to STEPS.length), so scrolling back undoes the steps exactly. The clicks go
  // through the setters in `demo`, not DOM events. The first real click, mouse press or key on a
  // control ends the demo for the rest of the visit and leaves the console as it is.
  var WAYPOINTS = [
    { at: 0.0, target: "chip-base" },
    { at: 0.35, target: "chip-strait-of-hormuz", click: true },
    { at: 0.85, target: "idle-toggle", click: true },
    { at: 1.3, target: "kpi-delta", label: "above" },
    { at: 1.75, target: "tab-monitor", click: true },
    { at: 2.1, target: "sweep-start" },
    { at: 2.5, target: "sweep-end" },
    { at: 2.8, target: "monitor-info", click: true },
    { at: 3.15, target: "monitor-info", click: true },
    { at: 3.45, target: "tab-validation", click: true },
    { at: 3.95, target: "model-garch", click: true },
    { at: 4.45, target: "val-table-toggle", click: true },
    { at: 6.0, target: "val-table-toggle" },
  ];
  var CLICK_LAG = 0.05; // a click lands just after the cursor arrives
  var cursor = null;
  var ring = null;
  var pin = null;
  var points = {};
  var sweep = null;
  var demoOn = false;
  var demoState = {};
  var liveRegions = [];
  var labelW = 0; // demo label width, read with the targets
  var bound = 0; // right edge of the console in the pinned frame
  var labelSide = "";

  function offsetIn(el) {
    var x = 0;
    var y = 0;
    while (el && el !== pin) {
      x += el.offsetLeft;
      y += el.offsetTop;
      el = el.offsetParent;
    }
    return [x, y];
  }
  function centre(el) {
    var o = offsetIn(el);
    return [o[0] + el.offsetWidth / 2, o[1] + el.offsetHeight / 2];
  }

  // Target positions relative to the pinned frame, from layout offsets (transforms ignored). Read
  // on refresh and after a demo step changes the layout; never per frame.
  function measureDemo() {
    if (!cursor) return;
    var q = function (sel) {
      return root.querySelector(sel);
    };
    var map = {
      "chip-base": q('[data-demo="chip-base"]'),
      "chip-strait-of-hormuz": q('[data-demo="chip-strait-of-hormuz"]'),
      "idle-toggle": q('[data-demo="idle-toggle"]'),
      "kpi-delta": q("#panel-optimiser .kpi:nth-child(2) dd"),
      "tab-monitor": q("#tab-monitor"),
      "monitor-info": q("#panel-monitor .info-button"),
      "tab-validation": q("#tab-validation"),
      "model-garch": q('[data-demo="model-chip-filtered-hs-garch-1-1"]'),
      "val-table-toggle": q('[data-demo="val-table-toggle"]'),
    };
    Object.keys(map).forEach(function (key) {
      if (map[key] && map[key].offsetParent !== null) points[key] = centre(map[key]);
    });
    labelW = cursor.querySelector(".demo-label").offsetWidth;
    bound = offsetIn(root)[0] + root.offsetWidth - 8;
    if (demo.chart && demo.sweep) {
      sweep = demo.sweep();
      var o = offsetIn(demo.chart);
      var w = demo.chart.offsetWidth;
      var y = o[1] + demo.chart.offsetHeight * 0.55;
      points["sweep-start"] = [o[0] + (sweep.run[0] / (sweep.n - 1)) * w, y];
      points["sweep-end"] = [o[0] + (sweep.run[1] / (sweep.n - 1)) * w, y];
    }
  }

  function ease(f) {
    return f < 0.5 ? 2 * f * f : 1 - Math.pow(-2 * f + 2, 2) / 2;
  }

  // The console state for a scroll position: each step sets a state, it never toggles one.
  function stateAt(p) {
    var crossOn = p >= 2.1 && p < 2.5 + CLICK_LAG;
    return {
      scenario: p >= 0.35 + CLICK_LAG ? "strait-of-hormuz" : "base",
      idle: p >= 0.85 + CLICK_LAG,
      tab: p >= 3.45 + CLICK_LAG ? 2 : p >= 1.75 + CLICK_LAG ? 1 : 0,
      cross: crossOn ? Math.min(1, Math.max(0, (p - 2.1) / 0.4)) : null,
      info: p >= 2.8 + CLICK_LAG && p < 3.15 + CLICK_LAG,
      model: p >= 3.95 + CLICK_LAG ? 4 : 0,
      table: p >= 4.45 + CLICK_LAG,
    };
  }

  function applyState(next) {
    var changed = false;
    if (next.scenario !== demoState.scenario && demo.scenario) {
      demo.scenario(next.scenario);
      changed = true;
    }
    if (next.idle !== demoState.idle && demo.idle) {
      demo.idle(next.idle);
      changed = true;
    }
    if (next.tab !== demoState.tab) {
      select(next.tab);
      if (demo.dropCrossBox) demo.dropCrossBox();
    }
    if (next.info !== demoState.info) {
      var button = root.querySelector("#panel-monitor .info-button");
      closeInfo();
      if (next.info && button) {
        button.setAttribute("aria-expanded", "true");
        document.getElementById(button.getAttribute("aria-controls")).hidden = false;
      }
    }
    if (next.model !== demoState.model && demo.model) demo.model(next.model);
    if (next.table !== demoState.table && demo.table) demo.table(next.table);
    if (demo.cross && (next.cross !== null || demoState.cross !== null)) {
      demo.cross(next.cross === null || !sweep ? null : Math.round(sweep.run[0] + next.cross * (sweep.run[1] - sweep.run[0])));
    }
    demoState = next;
    if (changed) measureDemo(); // the lane list moves the idle toggle
  }

  function cursorAt(p) {
    var i = 0;
    while (i < WAYPOINTS.length - 2 && p >= WAYPOINTS[i + 1].at) i += 1;
    var a = WAYPOINTS[i];
    var b = WAYPOINTS[i + 1];
    var pa = points[a.target];
    var pb = points[b.target];
    if (!pa || !pb) return null;
    var raw = Math.min(1, Math.max(0, (p - a.at) / (b.at - a.at)));
    var f = ease(raw);
    // The label follows the waypoint the cursor is nearest to.
    var near = raw < 0.5 ? a : b;
    return { x: pa[0] + (pb[0] - pa[0]) * f, y: pa[1] + (pb[1] - pa[1]) * f, above: near.label === "above" };
  }

  // The label sits right of the cursor, or left of it near the console's right edge, and above
  // it where it would cover the value being pointed at. Classes change only when the side does.
  function placeLabel(at) {
    var side = (at.x + 18 + labelW > bound ? "left" : "right") + (at.above ? " above" : "");
    if (side === labelSide) return;
    labelSide = side;
    cursor.classList.toggle("is-left", side.indexOf("left") === 0);
    cursor.classList.toggle("is-above", at.above);
  }

  // A press ring around each click time.
  function ringAt(p) {
    for (var i = 0; i < WAYPOINTS.length; i += 1) {
      var w = WAYPOINTS[i];
      if (!w.click) continue;
      var d = p - (w.at + CLICK_LAG);
      if (d > -0.03 && d < 0.12) return (d + 0.03) / 0.15;
    }
    return -1;
  }

  function demoAt(p) {
    if (!demoOn || manual) return;
    if (p < 0) {
      applyState(stateAt(0));
      cursor.style.opacity = "0";
      return;
    }
    applyState(stateAt(p));
    var at = cursorAt(p);
    if (!at) return;
    placeLabel(at);
    cursor.style.opacity = String(Math.min(1, p / 0.15));
    cursor.style.transform = "translate(" + at.x.toFixed(1) + "px," + at.y.toFixed(1) + "px)";
    var r = ringAt(p);
    ring.style.opacity = r < 0 ? "0" : String(0.8 * (1 - r));
    ring.style.transform = "translate(-50%,-50%) scale(" + (r < 0 ? 0.4 : 0.4 + r * 1.2).toFixed(2) + ")";
  }

  var listening = false;
  function startDemo() {
    if (demoOn || manual || !root) return;
    pin = root.parentNode;
    if (!cursor) {
      cursor = document.createElement("div");
      cursor.className = "demo-cursor";
      cursor.setAttribute("aria-hidden", "true");
      cursor.innerHTML =
        '<span class="demo-ring"></span><svg viewBox="0 0 16 20" class="demo-arrow"><path d="M1 1v15l4-4 3 7 3-1-3-7h6z"/></svg>' +
        '<span class="demo-label">Auto demo · click to explore</span>';
      ring = cursor.querySelector(".demo-ring");
      pin.appendChild(cursor);
    }
    cursor.style.opacity = "0";
    demoOn = true;
    demoState = stateAt(0);
    // Demo-driven changes are not announced; real choices are again after a takeover.
    liveRegions = Array.prototype.slice.call(root.querySelectorAll("[aria-live]"));
    liveRegions.forEach(function (node) {
      node.setAttribute("aria-live", "off");
    });
    measureDemo();
    if (listening) return;
    listening = true;
    var SCROLL_KEYS = [" ", "Spacebar", "PageUp", "PageDown", "Home", "End", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"];
    var SCROLL_CODES = ["Space", "PageUp", "PageDown", "Home", "End", "ArrowUp", "ArrowDown", "ArrowLeft", "ArrowRight"];
    var MODIFIERS = ["Shift", "Control", "Alt", "Meta"];
    document.addEventListener(
      "click",
      function (event) {
        if (event.isTrusted) stopAuto();
      },
      true
    );
    document.addEventListener(
      "pointerdown",
      function (event) {
        // Touch starts every scroll on a tablet: only a mouse or pen press counts here (a tap
        // still arrives as a click).
        if (event.isTrusted && event.pointerType !== "touch") stopAuto();
      },
      true
    );
    document.addEventListener(
      "keydown",
      function (event) {
        if (!event.isTrusted || manual) return;
        // An event that names no key at all is not a real key press.
        if (!event.key && !event.code && !event.keyCode) return;
        var active = document.activeElement;
        var onPage = !active || active === document.body || active === document.documentElement;
        var scrollKey =
          SCROLL_KEYS.indexOf(event.key) >= 0 ||
          SCROLL_CODES.indexOf(event.code) >= 0 ||
          (event.keyCode >= 32 && event.keyCode <= 40);
        if (onPage && scrollKey) return;
        if (MODIFIERS.indexOf(event.key) >= 0) return;
        stopAuto();
      },
      true
    );
  }

  function pauseDemo() {
    if (!demoOn) return;
    demoOn = false;
    if (cursor) cursor.style.opacity = "0";
    liveRegions.forEach(function (node) {
      node.setAttribute("aria-live", "polite");
    });
  }

  function endDemo() {
    if (!demoOn) return;
    pauseDemo();
    if (cursor) cursor.classList.add("is-gone");
    closeInfo();
    if (demo.cross) demo.cross(null);
  }

  var demoTween = null;
  var demoStart = 0;
  var api = (window.SITE_CONSOLE = {
    steps: STEPS,
    // Timeline units the console adds to the pinned scene: the demo, or a short tail once the
    // visitor has taken over.
    get units() {
      return manual ? TAIL_UNITS : STEPS.length * STEP_UNITS;
    },
    // Set by story.js: called once, when the visitor takes over.
    onTakeover: null,

    build: function (site, geo) {
      root = document.querySelector(".console");
      if (!root) return false;
      tabs = Array.prototype.slice.call(root.querySelectorAll('[role="tab"]'));
      panels = tabs.map(function (tab) {
        return document.getElementById(tab.getAttribute("aria-controls"));
      });
      fill(site, geo);
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
      demoStart = at;
      if (manual) {
        tl.to({}, { duration: TAIL_UNITS }, at);
        return at + TAIL_UNITS;
      }
      startDemo();
      demoTween = window.gsap.fromTo(
        proxy,
        { p: 0 },
        {
          p: STEPS.length,
          duration: STEPS.length * STEP_UNITS,
          ease: "none",
          immediateRender: false,
          onUpdate: function () {
            demoAt(proxy.p);
          },
        }
      );
      tl.add(demoTween, at);
      return at + STEPS.length * STEP_UNITS;
    },

    // Swap the demo for the short tail in a live timeline (story.js, after a takeover).
    removeDemo: function (tl) {
      if (!demoTween) return;
      tl.remove(demoTween);
      demoTween.kill();
      demoTween = null;
      tl.to({}, { duration: TAIL_UNITS }, demoStart);
    },

    // Stacked layout: once-only reveals, created inside story.js's matchMedia context (so they
    // revert with it). Start states are set here by JS only.
    staticReveal: function (gsap) {
      if (!root) return;
      var M = window.SITE_MOTION;
      M.reveal(gsap, root, { y: 16, opacity: 0, duration: 0.6, ease: "power2.out" }, root, "top 88%");
      panels.forEach(function (panel) {
        var items = panel.querySelectorAll(".scenario-chip, .kpi, .lane-list > .lane, .monitor-count, .val-verdict");
        M.reveal(gsap, items, { y: 8, opacity: 0, duration: 0.4, stagger: 0.03, ease: "power2.out" }, panel, "top 85%");
      });
      var chart = root.querySelector(".monitor-chart");
      if (chart && monitorLine) {
        M.once(chart, "top 80%", function () {
          // A hidden panel (phones show one at a time) keeps its line whole.
          if (chart.offsetParent !== null) M.draw(gsap, monitorLine, { duration: 1.4 });
        });
      }
      var tape = root.querySelector(".val-tape");
      if (tape) M.reveal(gsap, tape, { opacity: 0, duration: 0.6 }, tape, "top 90%");
    },

    // Before the sub-steps (scrolled back up), the console rests on the first one.
    reset: function () {
      demoAt(-1);
    },

    // Pinned mode: the console is inert until it has grown in.
    setLive: function (on) {
      if (!root) return;
      if (on) root.removeAttribute("inert");
      else root.setAttribute("inert", "");
    },

    // Leaving pinned mode: the demo pauses (its cursor is hidden by CSS) and announcements are on.
    unpin: function () {
      if (!root) return;
      root.removeAttribute("inert");
      pauseDemo();
    },

    // Re-measure the demo targets (story.js calls this on ScrollTrigger refresh).
    measureDemo: function () {
      measureDemo();
    },
  });
})();

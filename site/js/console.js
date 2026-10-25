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

  var SHORT = {
    "Strait of Hormuz": "Hormuz",
    "Bab el-Mandeb Strait": "Bab el-Mandeb",
    "Suez Canal": "Suez",
    "Malacca Strait": "Malacca",
    "Panama Canal": "Panama",
    "Cape of Good Hope": "Cape",
  };
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
      var left = x > box.width * 0.6;
      tip.style.transform = "translateX(" + (left ? x - 8 : x + 8).toFixed(1) + "px) translateX(" + (left ? "-100%" : "0") + ")";
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
  }

  // ------------------------------------------------------------------ content

  function fill(site, geo) {
    var get = function (key) {
      return root.querySelector('[data-h="' + key + '"]');
    };

    optimiser(site, geo, get);

    monitor(site, get);

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

  function stopAuto() {
    if (manual) return;
    manual = true;
    root.removeAttribute("data-focus");
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

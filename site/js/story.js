// The hero and the closure scene share one map stage.
//
// Pinned mode (GSAP present, wide screen, no reduced-motion preference): the stage is pinned and
// one scrubbed timeline moves the hero copy out, flies the camera from the world view to the
// Strait of Hormuz, brings in the closure copy, closes the Hormuz lane and counts up the panel.
// Static mode (everything else, and the markup default): the hero frame and a second, already
// zoomed closure frame are stacked, with every number shown at once.
//
// Performance: the camera is a CSS transform on two layers; the land layer (with the glows) is
// promoted only while the camera moves, label positions are computed on refresh, not per frame,
// and nothing reads layout while scrolling. Every number comes from site.json.
(function () {
  "use strict";

  var SVG_NS = "http://www.w3.org/2000/svg";
  var HORMUZ = "Strait of Hormuz";
  var LANE_SPACING = 140; // map units between tankers on the same lane
  var SPEED = 9; // map units per second
  var HULL_UNITS = 12;
  var FADE_UNITS = 18;
  var LABEL_GAP = 6;
  var PORT_NAMES = {
    Houston: "Houston",
    Rotterdam: "Rotterdam",
    "Ras Tanura": "Ras Tanura",
    "Sikka (India)": "Sikka",
    Ningbo: "Ningbo",
    "Novorossiysk (CPC)": "CPC",
  };
  var MARKER_NAMES = {
    "Strait of Hormuz": "Hormuz",
    "Bab el-Mandeb Strait": "Bab el-Mandeb",
    "Suez Canal": "Suez",
    "Malacca Strait": "Malacca",
    "Panama Canal": "Panama",
  };
  // Pin only where the tallest console panel fits the viewport (measured: about 700 px of console
  // plus margins at 960-1100 px wide, about 670 px at 1200 px and up). Narrower or shorter windows
  // get the stacked, normal-flow layout where nothing is hidden.
  var MOTION_OK = "(prefers-reduced-motion: no-preference)";
  var PINNED_QUERY =
    MOTION_OK + " and (min-width: 960px) and (min-height: 760px), " +
    MOTION_OK + " and (min-width: 1200px) and (min-height: 720px)";
  // The pinned timeline is in its own units; each unit takes VH_PER_UNIT % of the viewport
  // height of scroll. Hero and closure take STORY_UNITS (230vh); the console adds CONSOLE_IN for
  // its entrance plus its own sub-steps (SITE_CONSOLE.units).
  var VH_PER_UNIT = 50;
  var STORY_UNITS = 4.6;
  var CONSOLE_IN = 0.7;
  // After a takeover, drop the rest of the demo's pinned scroll (see shortenPinAfterTakeover).
  // Set to false to keep the full pin length if the shortening ever shows a visible jump.
  var SHORTEN_AFTER_TAKEOVER = true;
  var MARKER_GAP = 8; // px kept clear between neighbouring marker labels
  var LANE_CLEARANCE = 6; // px kept clear between a label and an active lane
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  var narrow = window.matchMedia("(max-width: 760px)");

  // ------------------------------------------------------------------ small helpers

  var MINUS = "−";
  var int = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
  var one = new Intl.NumberFormat("en-US", { minimumFractionDigits: 1, maximumFractionDigits: 1 });

  function usd(value) {
    return (value < 0 ? MINUS : "") + "$" + int.format(Math.abs(Math.round(value)));
  }
  function formatDate(iso, month) {
    return new Date(iso + "T00:00:00Z").toLocaleDateString("en-GB", {
      day: "numeric",
      month: month,
      year: "numeric",
      timeZone: "UTC",
    });
  }
  function range(pair) {
    return formatDate(pair[0], "short") + " to " + formatDate(pair[1], "short");
  }
  function lerp(a, b, t) {
    return a + (b - a) * t;
  }
  function clamp(v, lo, hi) {
    return Math.max(lo, Math.min(hi, v));
  }
  function overlaps(a, b) {
    return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
  }
  function inflate(r, by) {
    return { left: r.left - by, top: r.top - by, right: r.right + by, bottom: r.bottom + by };
  }
  function rectIn(node, box, pad) {
    var r = node.getBoundingClientRect();
    return inflate(
      { left: r.left - box.left, top: r.top - box.top, right: r.right - box.left, bottom: r.bottom - box.top },
      pad
    );
  }
  function el(name, attrs, parent) {
    var node = document.createElementNS(SVG_NS, name);
    Object.keys(attrs).forEach(function (key) {
      node.setAttribute(key, attrs[key]);
    });
    parent.appendChild(node);
    return node;
  }
  function translate(node, x, y) {
    node.style.transform = "translate3d(" + x.toFixed(1) + "px," + y.toFixed(1) + "px,0)";
  }

  // ------------------------------------------------------------------ copy and numbers

  function applyLinks() {
    var config = window.SITE_CONFIG || {};
    document.querySelectorAll("[data-github-link]").forEach(function (a) {
      a.href = config.githubUrl;
    });
    var apps = document.querySelectorAll("[data-app-link]");
    if (config.appUrl) {
      apps.forEach(function (app) {
        app.href = config.appUrl;
        app.target = "_blank";
        app.rel = "noopener noreferrer";
        app.setAttribute("aria-label", "Launch the app (opens in a new tab)");
      });
      return;
    }
    // Without an app URL the links stay inert and the load-time note is not shown.
    apps.forEach(function (app) {
      app.setAttribute("aria-disabled", "true");
      app.addEventListener("click", function (event) {
        event.preventDefault();
      });
    });
    document.querySelectorAll("[data-app-note]").forEach(function (note) {
      note.hidden = true;
    });
  }

  // Lanes active in the base plan, idle after the closure, and routed through Hormuz.
  function closedLanes(site) {
    var through = {};
    site.network.routes.forEach(function (r) {
      through[r.name] = r.chokepoints.indexOf(HORMUZ) >= 0;
    });
    var after = {};
    site.hormuz_closure.closed.routes.forEach(function (r) {
      after[r.route] = r.status;
    });
    return site.hormuz_closure.base.routes
      .filter(function (r) {
        return r.status === "ACTIVE" && after[r.route] === "IDLE" && through[r.route];
      })
      .map(function (r) {
        return r.route;
      });
  }

  function fillCopy(site, lanes) {
    var card = document.querySelector("[data-closure-card]");
    var set = function (key, text) {
      var node = card.querySelector('[data-f="' + key + '"]');
      if (node) node.textContent = text;
      return node;
    };
    document.querySelectorAll("[data-prices-asof]").forEach(function (t) {
      t.dateTime = site.as_of.prices;
      t.textContent = formatDate(site.as_of.prices, "long");
    });
    var closure = site.hormuz_closure;
    set("scenario-label", closure.label);
    set(
      "closed-lanes",
      lanes
        .map(function (name) {
          return name.replace("-", " → ");
        })
        .join(", ")
    );
    set(
      "scenario-note",
      "Prices as of " + formatDate(site.as_of.prices, "long") + ". Volumes, freight and capacities are assumptions."
    );
    var traffic = site.hormuz_traffic;
    set(
      "portwatch",
      traffic.label +
        " at Hormuz: about " +
        int.format(traffic.mean_2025) +
        " per day on average in 2025 (" +
        range(traffic.period_2025) +
        "), about " +
        int.format(traffic.mean_last_60d) +
        " per day recently (" +
        range(traffic.window) +
        "). Source: " +
        traffic.source +
        "."
    );
    var reading = site.monitor.filter(function (m) {
      return m.chokepoint === HORMUZ;
    })[0];
    if (reading) {
      set(
        "monitor",
        reading.flagged
          ? "Our traffic monitor flags Hormuz."
          : "Our traffic monitor does not flag Hormuz: its " +
              site.monitor_method.baseline_window_days +
              "-day baseline adapts to a long disruption."
      );
    }
    var status = site.chokepoint_status;
    set(
      "markers",
      "Markers: " + status.unit + ", " + range(status.window) + ", vs the " + status.reference_year + " average."
    );
    var list = card.querySelector('[data-f="marker-list"]');
    list.textContent = "";
    status.places.forEach(function (place) {
      var item = document.createElement("li");
      item.textContent = place.status
        ? place.chokepoint +
          ": " +
          one.format(place.status.recent_mean) +
          " per day, " +
          status.reference_year +
          " average " +
          one.format(place.status.reference_mean)
        : place.chokepoint + ": no status, data incomplete";
      list.appendChild(item);
    });

    // Count-up: p = 1 always prints the exact site.json values.
    var margins = set("margins", "");
    var delta = set("delta", "");
    var stranded = set("stranded", "");
    var lastP = -1;
    return function renderNumbers(p) {
      if (p === lastP) return;
      lastP = p;
      margins.textContent =
        usd(closure.base.daily_margin_usd * p) + " → " + usd(closure.closed.daily_margin_usd * p);
      delta.textContent = usd(closure.delta_daily_margin_usd * p);
      stranded.textContent = int.format(Math.round(closure.stranded_kbd * p)) + " kb/d";
    };
  }

  // ------------------------------------------------------------------ line splitting

  // Wraps each rendered line in a clipping span. The full text stays available to assistive
  // technology through a visually hidden copy (and aria-label on headings).
  function split(node) {
    if (node.getAttribute("data-split-done")) return;
    var text = node.textContent.trim();
    node.setAttribute("data-split-text", text);
    if (/^H[1-6]$/.test(node.tagName)) node.setAttribute("aria-label", text);
    var words = text.split(/\s+/);
    node.textContent = "";
    var probe = document.createElement("span");
    probe.setAttribute("aria-hidden", "true");
    node.appendChild(probe);
    var spans = words.map(function (word, i) {
      if (i > 0) probe.appendChild(document.createTextNode(" "));
      var s = document.createElement("span");
      s.style.whiteSpace = "nowrap"; // never break inside a word (e.g. at a hyphen) while measuring
      s.textContent = word;
      probe.appendChild(s);
      return s;
    });
    var lines = [];
    var top = null;
    spans.forEach(function (s) {
      var y = s.offsetTop;
      if (top === null || Math.abs(y - top) > 2) {
        lines.push([]);
        top = y;
      }
      lines[lines.length - 1].push(s.textContent);
    });
    node.textContent = "";
    if (!/^H[1-6]$/.test(node.tagName)) {
      var hidden = document.createElement("span");
      hidden.className = "visually-hidden";
      hidden.textContent = text;
      node.appendChild(hidden);
    }
    lines.forEach(function (words) {
      var line = document.createElement("span");
      line.className = "split-line";
      line.setAttribute("aria-hidden", "true");
      var inner = document.createElement("span");
      inner.className = "split-inner";
      // Non-breaking hyphens keep each measured line on one line; the hidden copy keeps the text.
      inner.textContent = words.join(" ").replace(/-/g, "\u2011");
      line.appendChild(inner);
      node.appendChild(line);
    });
    node.setAttribute("data-split-done", "1");
  }

  function unsplit(node) {
    if (!node.getAttribute("data-split-done")) return;
    node.textContent = node.getAttribute("data-split-text");
    node.removeAttribute("data-split-done");
    node.removeAttribute("aria-label");
  }

  // ------------------------------------------------------------------ map stage

  function Stage(root, geo, site, lanes, options) {
    var self = this;
    var landSvg = root.querySelector('[data-map="land"]');
    var lanesSvg = root.querySelector('[data-map="lanes"]');
    // Tankers change every frame: their own layer keeps the lane layer untouched while it moves.
    var fleetSvg = root.querySelector('[data-map="fleet"]');
    var idleSvg = root.querySelector('[data-map="idle"]');
    // The idle lanes have their own promoted layer, dimmed with CSS opacity (compositor only).
    self.idleLayer = root.querySelector(".stage-idle");
    var layers = Array.prototype.slice.call(root.querySelectorAll(".stage-layer"));
    var labels = root.querySelector(".stage-labels");
    self.root = root;

    var active = {};
    site.hormuz_closure.base.routes.forEach(function (r) {
      active[r.route] = r.status === "ACTIVE";
    });

    el("path", { d: geo.land, class: "land" }, landSvg);
    var glows = el("g", {}, landSvg);
    var defs = el("defs", {}, fleetSvg);
    var wakeId = "wake-" + options.name;
    var wake = el("linearGradient", { id: wakeId, x1: "1", y1: "0", x2: "0", y2: "0" }, defs);
    el("stop", { offset: "0", "stop-color": "#f4f4f5", "stop-opacity": "0.45" }, wake);
    el("stop", { offset: "1", "stop-color": "#f4f4f5", "stop-opacity": "0" }, wake);

    // Dashed idle lanes are the costliest strokes to repaint, so they are scaled as a bitmap
    // while the camera moves; only the highlighted lanes are re-rendered at constant width.
    self.idle = el("g", {}, idleSvg);
    var open = el("g", {}, lanesSvg);
    self.closedOpen = el("g", {}, lanesSvg);
    self.closedRed = el("g", { opacity: "0" }, lanesSvg);
    var lanePaths = [];
    var closedPath = null;
    Object.keys(geo.routes).forEach(function (name) {
      var d = geo.routes[name];
      if (lanes.indexOf(name) >= 0) {
        el("path", { d: d, class: "lane-glow" }, self.closedOpen);
        var orange = el("path", { d: d, class: "lane-active" }, self.closedOpen);
        el("path", { d: d, class: "lane-closed-glow" }, self.closedRed);
        el("path", { d: d, class: "lane-closed" }, self.closedRed);
        lanePaths.push({ path: orange, closed: true });
        if (!closedPath) closedPath = orange;
      } else if (active[name]) {
        el("path", { d: d, class: "lane-glow" }, glows);
        lanePaths.push({ path: el("path", { d: d, class: "lane-active" }, open), closed: false });
      } else {
        el("path", { d: d, class: "lane-idle" }, self.idle);
      }
    });

    // Ports (circles in the lane layer) and their HTML labels.
    var portGroup = el("g", {}, lanesSvg);
    self.portGroup = portGroup;
    self.ports = options.ports
      ? Object.keys(geo.ports).map(function (name) {
          var label = document.createElement("span");
          label.className = "port-label";
          label.textContent = PORT_NAMES[name] || name;
          labels.appendChild(label);
          return {
            xy: geo.ports[name],
            circle: el("circle", { cx: geo.ports[name][0], cy: geo.ports[name][1], r: 3.2, class: "port" }, portGroup),
            label: label,
          };
        })
      : [];

    // Tankers.
    var fleet = el("g", {}, fleetSvg);
    function hull() {
      var g = el("g", { class: "tanker" }, fleet);
      el("path", { d: "M-6 -1.2L-17 -3.2L-17 3.2L-6 1.2Z", fill: "url(#" + wakeId + ")" }, g);
      el("path", { d: "M-6 -1.7L3.4 -1.7Q5.4 -1.7 6 0Q5.4 1.7 3.4 1.7L-6 1.7Z", class: "tanker-hull" }, g);
      el("rect", { x: -5, y: -1, width: 2.2, height: 2, class: "tanker-bridge" }, g);
      return g;
    }
    self.tankers = [];
    lanePaths.forEach(function (lane) {
      if (options.closedOnly && !lane.closed) return;
      var length = lane.path.getTotalLength();
      var count = lane.closed ? 1 : Math.max(1, Math.min(4, Math.round(length / LANE_SPACING)));
      for (var i = 0; i < count; i += 1) {
        self.tankers.push({
          node: hull(),
          path: lane.path,
          length: length,
          offset: ((i + 0.35) / count) * length,
          closed: lane.closed,
        });
      }
    });

    // Where the closed lane's tanker stops: just short of the strait.
    var hormuz = geo.chokepoints[HORMUZ];
    self.stopAt = 0;
    if (closedPath) {
      var total = closedPath.getTotalLength();
      var best = Infinity;
      for (var s = 0; s <= total; s += 1) {
        var pt = closedPath.getPointAtLength(s);
        var dist = Math.hypot(pt.x - hormuz[0], pt.y - hormuz[1]);
        if (dist < best) {
          best = dist;
          self.stopAt = s;
        }
      }
      self.stopAt = Math.max(0, self.stopAt - 7);
    }

    // Chokepoint markers (HTML: dot plus label).
    var chipSource = document.querySelector(".card-rows .alert-chip");
    self.markers = options.markers
      ? site.chokepoint_status.places.map(function (place) {
          var node = document.createElement("div");
          node.className = "marker";
          var dot = document.createElement("span");
          dot.className = "marker-dot";
          var label = document.createElement("div");
          label.className = "marker-label";
          var name = document.createElement("span");
          name.className = "marker-name";
          name.textContent = MARKER_NAMES[place.chokepoint] || place.chokepoint;
          label.appendChild(name);
          if (place.status) {
            var line = document.createElement("span");
            line.textContent =
              one.format(place.status.recent_mean) +
              "/day vs " +
              one.format(place.status.reference_mean) +
              " in " +
              site.chokepoint_status.reference_year;
            label.appendChild(line);
          }
          var chip = null;
          if (place.chokepoint === HORMUZ) {
            chip = chipSource.cloneNode(true);
            label.appendChild(chip);
          }
          node.appendChild(dot);
          node.appendChild(label);
          labels.appendChild(node);
          return { xy: geo.chokepoints[place.chokepoint], node: node, label: label, chip: chip, hormuz: place.chokepoint === HORMUZ };
        })
      : [];

    // Active-lane sample points, used to keep port labels off the highlighted lanes.
    var lanePoints = [];
    lanePaths.forEach(function (lane) {
      var length = lane.path.getTotalLength();
      for (var d = 0; d <= length; d += 3) {
        var p = lane.path.getPointAtLength(d);
        lanePoints.push([p.x, p.y]);
      }
    });

    // Lane ends of the closed lane and the places that frame the zoomed shot.
    var frameXY = [hormuz];
    if (closedPath) {
      var a = closedPath.getPointAtLength(0);
      var b = closedPath.getPointAtLength(closedPath.getTotalLength());
      frameXY.push([a.x, a.y], [b.x, b.y]);
    }
    ["Suez Canal", "Bab el-Mandeb Strait"].forEach(function (name) {
      if (geo.chokepoints[name]) frameXY.push(geo.chokepoints[name]);
    });

    self.cam = { s: 1, tx: 0, ty: 0 };
    self.final = { scale: 1, target: [0, 0] };
    self.state = { z: 0, close: 0 };
    var m = null;

    function setViewBox() {
      var vb = (narrow.matches ? geo.viewBoxNarrow : geo.viewBox).join(" ");
      [landSvg, idleSvg, lanesSvg, fleetSvg].forEach(function (svg) {
        svg.setAttribute("viewBox", vb);
      });
    }

    // Layout reads happen here only: on build, resize and ScrollTrigger refresh.
    self.measure = function (obstacles) {
      setViewBox();
      layers.forEach(function (layer) {
        layer.style.transform = "none";
      });
      var box = root.getBoundingClientRect();
      var ctm = lanesSvg.getScreenCTM();
      var toPx = function (xy) {
        return [ctm.a * xy[0] + ctm.c * xy[1] + ctm.e - box.left, ctm.b * xy[0] + ctm.d * xy[1] + ctm.f - box.top];
      };
      m = { box: box, w: box.width, h: box.height, pxPerUnit: ctm.a, toPx: toPx, p0: toPx(hormuz) };
      // Labels hidden by the previous placement must be measurable again.
      self.ports.forEach(function (port) {
        port.label.style.display = "";
      });
      self.markers.forEach(function (mk) {
        mk.node.style.display = "";
      });
      self.ports.forEach(function (port) {
        port.q = toPx(port.xy);
        port.w = port.label.offsetWidth;
        port.h = port.label.offsetHeight;
      });
      self.markers.forEach(function (mk) {
        mk.q = toPx(mk.xy);
        mk.w = mk.label.offsetWidth;
        mk.h = mk.label.offsetHeight;
      });
      m.lanes = lanePoints.map(toPx);
      fitFinal(obstacles.closure);
      placePorts(obstacles.hero);
      placeMarkers(obstacles.closure);
      self.render(true);
    };

    // Final camera: fit Hormuz, the closed lane, Suez and Bab el-Mandeb (with room for their
    // labels) into the part of the frame the copy and the panel leave free.
    function fitFinal(obstacles) {
      var rel = frameXY.map(function (xy) {
        var p = m.toPx(xy);
        return [p[0] - m.p0[0], p[1] - m.p0[1]];
      });
      var xs = rel.map(function (p) {
        return p[0];
      });
      var ys = rel.map(function (p) {
        return p[1];
      });
      var minX = Math.min.apply(null, xs) - 16;
      var maxX = Math.max.apply(null, xs) + 150; // marker labels sit to the right
      var minY = Math.min.apply(null, ys) - 56; // Hormuz label sits above
      var maxY = Math.max.apply(null, ys) + 40;
      var region = { left: 16, top: Math.max(56, m.h * 0.08), right: m.w - 16, bottom: m.h - 16 };
      obstacles.forEach(function (o) {
        // The copy sits bottom left and the panel bottom right: take the free band above them.
        if (o.right > m.w * 0.55) region.right = Math.min(region.right, o.left - 16);
        else region.bottom = Math.min(region.bottom, o.top - 16);
      });
      var scale = clamp(
        Math.min((region.right - region.left) / (maxX - minX), (region.bottom - region.top) / (maxY - minY)),
        1.2,
        2.6
      );
      var usedW = (maxX - minX) * scale;
      var usedH = (maxY - minY) * scale;
      self.final.scale = scale;
      self.final.target = [
        region.left + (region.right - region.left - usedW) / 2 - minX * scale,
        region.top + (region.bottom - region.top - usedH) / 2 - minY * scale,
      ];
    }

    function cameraAt(z) {
      var s = Math.pow(self.final.scale, z);
      return {
        s: s,
        tx: lerp(m.p0[0], self.final.target[0], z) - s * m.p0[0],
        ty: lerp(m.p0[1], self.final.target[1], z) - s * m.p0[1],
      };
    }

    function choose(anchorX, anchorY, w, h, order, obstacles, placed, avoidLanes, strict) {
      var g = LABEL_GAP;
      var far = 3 * LABEL_GAP;
      var spots = {
        farAbove: [anchorX - w / 2, anchorY - far - h],
        farBelow: [anchorX - w / 2, anchorY + far],
        farRight: [anchorX + far, anchorY - h / 2],
        farLeft: [anchorX - far - w, anchorY - h / 2],
        right: [anchorX + g, anchorY - h / 2],
        left: [anchorX - g - w, anchorY - h / 2],
        above: [anchorX - w / 2, anchorY - g - h],
        below: [anchorX - w / 2, anchorY + g],
        aboveRight: [anchorX + g / 2, anchorY - g / 2 - h],
        aboveLeft: [anchorX - g / 2 - w, anchorY - g / 2 - h],
        belowRight: [anchorX + g / 2, anchorY + g / 2],
        belowLeft: [anchorX - g / 2 - w, anchorY + g / 2],
      };
      var fallback = null;
      for (var i = 0; i < order.length; i += 1) {
        var p = spots[order[i]];
        var r = { left: p[0], top: p[1], right: p[0] + w, bottom: p[1] + h };
        var inside = r.left >= 4 && r.top >= 4 && r.right <= m.w - 4 && r.bottom <= m.h - 4;
        if (!inside) continue;
        var blocked = obstacles.concat(placed).some(function (o) {
          return overlaps(r, o);
        });
        if (blocked) continue;
        if (!avoidLanes || !coversLane(strict ? inflate(r, LANE_CLEARANCE) : r, avoidLanes)) return r;
        if (!fallback && !strict) fallback = r;
      }
      return fallback;
    }

    function coversLane(r, points) {
      return points.some(function (p) {
        return p[0] > r.left && p[0] < r.right && p[1] > r.top && p[1] < r.bottom;
      });
    }

    // Port labels: placed once for the world view (camera at rest).
    function placePorts(obstacles) {
      var placed = [];
      var visible = self.ports.filter(function (port) {
        var x = port.q[0];
        var y = port.q[1];
        var marker = { left: x - 5, top: y - 5, right: x + 5, bottom: y + 5 };
        port.ok =
          x > 4 &&
          x < m.w - 4 &&
          y > 4 &&
          y < m.h - 4 &&
          !obstacles.some(function (o) {
            return overlaps(marker, o);
          });
        if (port.ok) placed.push(marker);
        return port.ok;
      });
      var order = ["right", "left", "above", "below", "aboveRight", "aboveLeft", "belowRight", "belowLeft"];
      visible.forEach(function (port) {
        var others = placed.filter(function (o) {
          return Math.abs(o.left + 5 - port.q[0]) > 0.5 || Math.abs(o.top + 5 - port.q[1]) > 0.5;
        });
        var spot = choose(port.q[0], port.q[1], port.w, port.h, order, obstacles, others.map(function (o) {
          return inflate(o, 3);
        }), m.lanes);
        port.ok = Boolean(spot);
        if (spot) {
          placed.push(spot);
          port.dx = spot.left - port.q[0];
          port.dy = spot.top - port.q[1];
        }
      });
      self.ports.forEach(function (port) {
        port.circle.style.visibility = port.ok ? "" : "hidden";
        port.label.style.display = port.ok ? "" : "none";
      });
    }

    // Chokepoint markers: placed once for the final, zoomed frame.
    // Labels never sit on an active lane (strict) and keep MARKER_GAP from each other; a marker
    // whose label cannot be placed that way is hidden with its dot.
    function placeMarkers(obstacles) {
      var cam = cameraAt(1);
      var placed = [];
      var lanesNow = m.lanes.map(function (p) {
        return [cam.tx + cam.s * p[0], cam.ty + cam.s * p[1]];
      });
      self.markers.forEach(function (mk) {
        var x = cam.tx + cam.s * mk.q[0];
        var y = cam.ty + cam.s * mk.q[1];
        var dotBox = { left: x - 6, top: y - 6, right: x + 6, bottom: y + 6 };
        var onFrame = x > 6 && x < m.w - 6 && y > 6 && y < m.h - 6;
        var clear =
          onFrame &&
          !obstacles.concat(placed).some(function (o) {
            return overlaps(dotBox, o);
          });
        var order = mk.hormuz
          ? ["above", "aboveLeft", "aboveRight", "farAbove", "below", "farBelow", "left", "right"]
          : ["right", "left", "below", "above", "belowRight", "aboveRight", "belowLeft", "aboveLeft"]
              .concat(["farRight", "farLeft", "farBelow", "farAbove"]);
        var spot = clear ? choose(x, y, mk.w, mk.h, order, obstacles, placed, lanesNow, true) : null;
        mk.ok = Boolean(spot);
        if (spot) {
          placed.push(inflate(spot, MARKER_GAP), dotBox);
          mk.dx = spot.left - x;
          mk.dy = spot.top - y;
          mk.label.style.transform = "translate(" + mk.dx.toFixed(1) + "px," + mk.dy.toFixed(1) + "px)";
        }
        mk.node.style.display = mk.ok ? "" : "none";
      });
    }

    var lastZ = -1;
    var lastClose = -1;
    // Writes only: camera transform, label translations, closure opacities.
    self.render = function (force) {
      if (!m) return;
      var z = self.state.z;
      if (force || z !== lastZ) {
        lastZ = z;
        var cam = cameraAt(z);
        self.cam = cam;
        var t = "translate3d(" + cam.tx.toFixed(1) + "px," + cam.ty.toFixed(1) + "px,0) scale(" + cam.s.toFixed(4) + ")";
        layers.forEach(function (layer) {
          layer.style.transform = t;
        });
        self.ports.forEach(function (port) {
          if (port.ok) translate(port.label, cam.tx + cam.s * port.q[0] + port.dx, cam.ty + cam.s * port.q[1] + port.dy);
        });
        self.markers.forEach(function (mk) {
          if (mk.ok) translate(mk.node, cam.tx + cam.s * mk.q[0], cam.ty + cam.s * mk.q[1]);
        });
      }
      var close = self.state.close;
      if (force || close !== lastClose) {
        lastClose = close;
        self.closedRed.setAttribute("opacity", close.toFixed(3));
        self.closedOpen.setAttribute("opacity", (1 - close).toFixed(3));
        self.markers.forEach(function (mk) {
          if (mk.chip) mk.chip.style.opacity = close.toFixed(3);
        });
      }
    };

    // Hormuz in stage pixels for camera state z (read after measure).
    self.pointAt = function (z) {
      if (!m) return null;
      var cam = cameraAt(z);
      return [cam.tx + cam.s * m.p0[0], cam.ty + cam.s * m.p0[1]];
    };

    self.tankerScale = function () {
      return m ? (narrow.matches ? 20 : 26) / (HULL_UNITS * m.pxPerUnit * self.cam.s) : 1;
    };
  }

  function placeTanker(stage, tanker, distance, scale) {
    var at = ((distance % tanker.length) + tanker.length) % tanker.length;
    if (tanker.closed) at = lerp(at, stage.stopAt, stage.state.close);
    var p = tanker.path.getPointAtLength(at);
    var q = tanker.path.getPointAtLength(Math.min(at + 1, tanker.length));
    var angle = (Math.atan2(q.y - p.y, q.x - p.x) * 180) / Math.PI;
    var fade = tanker.closed && stage.state.close > 0 ? 1 : Math.min(1, at / FADE_UNITS, (tanker.length - at) / FADE_UNITS);
    tanker.node.setAttribute(
      "transform",
      "translate(" + p.x.toFixed(2) + " " + p.y.toFixed(2) + ") rotate(" + angle.toFixed(1) + ") scale(" + scale.toFixed(4) + ")"
    );
    tanker.node.setAttribute("opacity", Math.max(0, fade).toFixed(2));
  }

  // One rAF loop for the moving tankers on the main stage.
  function runFleet(stage) {
    var running = false;
    var visible = true;
    var held = false; // set while the map sits under the console veil
    var elapsed = 0;
    var last = 0;
    function draw() {
      var scale = stage.tankerScale();
      stage.tankers.forEach(function (t) {
        placeTanker(stage, t, t.offset + elapsed * SPEED, scale);
      });
    }
    function frame(now) {
      if (!running) return;
      if (last) elapsed += Math.min(now - last, 100) / 1000;
      last = now;
      draw();
      window.requestAnimationFrame(frame);
    }
    function update() {
      var go = visible && !held && !document.hidden && !reduceMotion.matches;
      if (go && !running) {
        running = true;
        last = 0;
        window.requestAnimationFrame(frame);
      } else if (!go) {
        running = false;
        draw();
      }
    }
    new IntersectionObserver(function (entries) {
      visible = entries[0].isIntersecting;
      update();
    }).observe(stage.root);
    document.addEventListener("visibilitychange", update);
    reduceMotion.addEventListener("change", update);
    update();
    draw.hold = function (on) {
      if (on === held) return;
      held = on;
      update();
    };
    return draw;
  }

  // ------------------------------------------------------------------ obstacles

  function heroObstacles(box) {
    var rects = [];
    var headline = document.getElementById("hero-title");
    var range = document.createRange();
    range.selectNodeContents(headline);
    Array.prototype.forEach.call(range.getClientRects(), function (r) {
      if (r.width > 2 && r.height > 2) {
        rects.push(inflate({ left: r.left - box.left, top: r.top - box.top, right: r.right - box.left, bottom: r.bottom - box.top }, 4));
      }
    });
    [".lede", ".actions", ".app-note:not([hidden])", ".map-key", ".wordmark", ".masthead-link", ".scroll-hint"]
      .map(function (s) {
        return document.querySelector(s);
      })
      .filter(function (n) {
        return n && n.getClientRects().length > 0;
      })
      .forEach(function (n) {
        rects.push(rectIn(n, box, 4));
      });
    return rects;
  }

  function closureObstacles(box) {
    return [document.querySelector(".closure-copy"), document.querySelector("[data-closure-card]")]
      .filter(function (n) {
        var r = n.getBoundingClientRect();
        // Only blocks that actually overlap this stage (on phones they sit outside it).
        return r.bottom > box.top && r.top < box.bottom && n.getClientRects().length > 0;
      })
      .map(function (n) {
        return rectIn(n, box, 8);
      });
  }

  // ------------------------------------------------------------------ modes

  function init() {
    applyLinks();
    if (!window.SITE_DATA) return;
    // Wait for the other deferred scripts too (console.js), not only for the data.
    Promise.all([window.SITE_DATA, window.SITE_DOM_READY]).then(function (results) {
      var data = results[0];
      var geo = data[0];
      var site = data[1];
      var lanes = closedLanes(site);
      var renderNumbers = fillCopy(site, lanes);
      var html = document.documentElement;
      var story = document.querySelector(".story");
      var pin = story.querySelector(".story-pin");
      var mainRoot = story.querySelector('[data-stage="main"]');
      var closureRoot = story.querySelector('[data-stage="closure"]');
      var main = new Stage(mainRoot, geo, site, lanes, { name: "main", ports: true, markers: true });
      var drawFleet = runFleet(main);
      var closure = null;
      var splitNodes = Array.prototype.slice.call(document.querySelectorAll("[data-split]"));
      var con = window.SITE_CONSOLE && window.SITE_CONSOLE.build(site, geo) ? window.SITE_CONSOLE : null;
      var consoleNode = document.querySelector(".console");
      var glow = pin.querySelector(".hormuz-glow");
      var card = document.querySelector("[data-closure-card]");

      function measureMain(pinned) {
        var box = mainRoot.getBoundingClientRect();
        // A refresh in the console phase finds the card shrunk; measure it at full size.
        var scale = pinned && window.gsap ? window.gsap.getProperty(card, "scale") : 1;
        if (scale !== 1) window.gsap.set(card, { scale: 1 });
        main.measure({ hero: heroObstacles(box), closure: pinned ? closureObstacles(box) : [] });
        if (scale !== 1) window.gsap.set(card, { scale: scale });
        if (pinned && con) {
          placeConsole();
          if (con.measureDemo) con.measureDemo();
        }
        drawFleet();
      }

      // The console entrance converges on Hormuz in the final frame: the glow sits there, and the
      // card and the console scale about that point. offsetLeft/Top ignore transforms.
      function placeConsole() {
        var p = main.pointAt(1);
        if (!p) return;
        var x = mainRoot.offsetLeft + p[0];
        var y = mainRoot.offsetTop + p[1];
        window.gsap.set(glow, { x: x, y: y });
        window.gsap.set(card, { transformOrigin: x - card.offsetLeft + "px " + (y - card.offsetTop) + "px" });
        window.gsap.set(consoleNode, {
          transformOrigin: x - consoleNode.offsetLeft + "px " + (y - consoleNode.offsetTop) + "px",
        });
      }

      function renderStatic() {
        html.setAttribute("data-story", "static");
        drawFleet.hold(false);
        if (con) con.unpin();
        main.state.z = 0;
        main.state.close = 0;
        main.markers.forEach(function (mk) {
          mk.node.style.opacity = "0";
        });
        measureMain(false);
        if (!closure) {
          closure = new Stage(closureRoot, geo, site, lanes, { name: "closure", ports: false, markers: true, closedOnly: true });
        }
        closure.state.z = 1;
        closure.state.close = 1;
        closure.idleLayer.style.opacity = "0.35";
        var box = closureRoot.getBoundingClientRect();
        closure.measure({ hero: [], closure: closureObstacles(box) });
        closure.tankers.forEach(function (t) {
          placeTanker(closure, t, closure.stopAt, closure.tankerScale());
        });
        renderNumbers(1);
      }

      function pinned(gsap) {
        html.setAttribute("data-story", "pinned");
        splitNodes.forEach(split);
        var heroLines = document.querySelectorAll(".hero-copy .split-inner");
        var heroRest = [".actions", ".app-note", ".map-key"].map(function (s) {
          return document.querySelector(s);
        });
        var h2Lines = document.querySelectorAll(".closure-copy h2 .split-inner");
        var ledeLines = document.querySelectorAll(".closure-lede .split-inner");
        var markers = main.markers; // hidden ones are display: none, so tween them all
        var state = main.state;
        var counter = { p: 0 };
        state.z = 0;
        state.close = 0;
        renderNumbers(0);
        measureMain(true);

        var stage = mainRoot;
        var moving = false;
        var consoleMoving = false;
        var live = null;
        var mapHidden = false;
        var covered = false;
        var T = STORY_UNITS; // the console entrance starts where the closure scene ends
        var units = STORY_UNITS + (con ? CONSOLE_IN + con.units : 0);
        function setMoving(on) {
          if (on === moving) return;
          moving = on;
          stage.classList.toggle("is-moving", on);
        }
        // Console-phase bookkeeping; every write happens only when its state changes.
        function consolePhase(t) {
          var near = moving && t > T - 0.2 && t < T + CONSOLE_IN + 0.1;
          if (near !== consoleMoving) {
            consoleMoving = near;
            pin.classList.toggle("is-console-moving", near);
          }
          drawFleet.hold(t > T + 0.45);
          // Under the full veil the idle lanes and tankers are not needed: hide them early.
          var cover = t > T + 0.45;
          if (cover !== covered) {
            covered = cover;
            stage.classList.toggle("is-covered", cover);
          }
          // Once the console covers the frame, the map (lanes, glows, labels, veil) is not drawn.
          var hide = t >= T + CONSOLE_IN;
          if (hide !== mapHidden) {
            mapHidden = hide;
            stage.style.visibility = hide ? "hidden" : "";
          }
          var on = t >= T + 0.55;
          if (on !== live) {
            live = on;
            con.setLive(on);
          }
          if (t < T + CONSOLE_IN) con.reset();
        }

        var tl = gsap.timeline({
          defaults: { ease: "power2.out" },
          onUpdate: function () {
            main.render(false);
            renderNumbers(counter.p);
            if (con) consolePhase(tl.time());
          },
          scrollTrigger: {
            trigger: story,
            pin: pin,
            start: "top top",
            end: "+=" + Math.round(units * VH_PER_UNIT) + "%",
            scrub: 1,
            onUpdate: function () {
              // No layer promotion for the map once the console covers it.
              setMoving(!con || tl.time() < T + CONSOLE_IN);
            },
            onScrubComplete: function () {
              setMoving(false);
              if (con) consolePhase(tl.time());
            },
            onRefresh: function () {
              measureMain(true);
            },
          },
        });
        // Timeline units: STORY_UNITS (4.6) for hero and closure, then the console; one unit is
        // VH_PER_UNIT % of the viewport height of scroll.
        // (1) hero copy leaves, line by line
        tl.fromTo(heroLines, { yPercent: 0, opacity: 1 }, { yPercent: -110, opacity: 0, duration: 0.55, stagger: 0.05, ease: "power2.in" }, 0)
          .fromTo(heroRest, { y: 0, opacity: 1 }, { y: -24, opacity: 0, duration: 0.45, stagger: 0.05, ease: "power2.in" }, 0.1)
          .fromTo(".scroll-hint", { opacity: 1 }, { opacity: 0, duration: 0.25 }, 0)
          .fromTo(mainRoot.querySelector(".scrim-hero"), { opacity: 1 }, { opacity: 0, duration: 0.6 }, 0.25)
          // port markers leave with their labels: no unlabelled dots in the zoomed frame
          .fromTo(
            main.ports
              .map(function (p) {
                return p.label;
              })
              .concat([main.portGroup]),
            { opacity: 1 },
            { opacity: 0, duration: 0.35 },
            0.3
          )
          // (2) a short pause on the world map with ships, then the camera flies to Hormuz;
          // idle lanes dim; markers fade in
          .fromTo(state, { z: 0 }, { z: 1, duration: 1.6, ease: "power2.inOut" }, 0.6)
          .fromTo(main.idleLayer, { opacity: 1 }, { opacity: 0.35, duration: 0.8 }, 0.9)
          .fromTo(
            markers.map(function (mk) {
              return mk.node;
            }),
            { opacity: 0 },
            { opacity: 1, duration: 0.35, stagger: 0.1 },
            1.8
          )
          // (3) closure copy enters, line by line
          .fromTo(mainRoot.querySelector(".scrim-closure"), { opacity: 0 }, { opacity: 1, duration: 0.6 }, 2.0)
          .fromTo(".closure-copy .eyebrow", { y: 12, opacity: 0 }, { y: 0, opacity: 1, duration: 0.35 }, 2.05)
          .fromTo(h2Lines, { yPercent: 110, opacity: 0 }, { yPercent: 0, opacity: 1, duration: 0.55, stagger: 0.08 }, 2.1)
          .fromTo(ledeLines, { yPercent: 110, opacity: 0 }, { yPercent: 0, opacity: 1, duration: 0.55, stagger: 0.06 }, 2.3)
          // (4) the lane closes, the tanker stops, the panel enters and counts up
          .fromTo(state, { close: 0 }, { close: 1, duration: 0.5, ease: "none" }, 2.95)
          .fromTo("[data-closure-card]", { y: 24, opacity: 0 }, { y: 0, opacity: 1, duration: 0.55 }, 3.3)
          .fromTo(counter, { p: 0 }, { p: 1, duration: 0.8, ease: "power1.out" }, 3.4)
          .to({}, { duration: 0.4 }, 4.2);

        // (5) the console grows out of Hormuz: the map dims under a veil, the closure copy leaves,
        // the card shrinks into a glowing dot at the strait and the console scales up from it.
        // Card, glow and console are separate elements; only opacity and uniform scale change.
        if (con) {
          var later = { immediateRender: false };
          tl.fromTo(".closure-copy", { y: 0, opacity: 1 }, Object.assign({ y: -24, opacity: 0, duration: 0.3, ease: "power2.in" }, later), T)
            .fromTo(mainRoot.querySelector(".stage-veil"), { opacity: 0 }, { opacity: 1, duration: 0.45, ease: "none" }, T)
            .fromTo(card, { scale: 1, opacity: 1 }, Object.assign({ scale: 0.04, opacity: 0, duration: 0.4, ease: "power2.in" }, later), T + 0.05)
            .fromTo(glow, { scale: 0, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.2, ease: "back.out(2)" }, T + 0.3)
            .fromTo(glow, { scale: 1, opacity: 1 }, Object.assign({ scale: 2.4, opacity: 0, duration: 0.25 }, later), T + 0.5)
            .fromTo(consoleNode, { scale: 0.9, opacity: 0 }, { scale: 1, opacity: 1, duration: 0.3 }, T + 0.4);
          con.attach(tl, T + CONSOLE_IN);
          live = null;
          consolePhase(0);
          con.onTakeover = SHORTEN_AFTER_TAKEOVER ? afterTakeover : null;
        }

        // Once the visitor takes over, the demo's remaining scroll would only scroll a frozen
        // console. Swap it for a short tail and refresh every ScrollTrigger on the page (so later
        // sections move up with it). The scale (VH_PER_UNIT per unit) is unchanged, so the
        // position stays put; only a reader already past the new end is clamped to it, where
        // the frame looks the same.
        // The takeover fires on pointerdown or keydown: a refresh right then would move the pinned
        // frame mid-click and swallow the click. Wait until the press is over.
        function afterTakeover() {
          var done = false;
          var run = function () {
            if (done) return;
            done = true;
            ["pointerup", "keyup", "click"].forEach(function (type) {
              document.removeEventListener(type, later, true);
            });
            shortenPinAfterTakeover();
          };
          var later = function () {
            window.setTimeout(run, 150);
          };
          ["pointerup", "keyup", "click"].forEach(function (type) {
            document.addEventListener(type, later, true);
          });
          window.setTimeout(run, 1200);
        }

        // Where the console has fully grown in, read from the live timeline (so it is right after
        // a resize or the takeover shortening as well). Used by the footer's "How it works" link.
        window.SITE_STORY = {
          consoleY: function () {
            var st = tl.scrollTrigger;
            if (!st || !st.enabled || !con || html.getAttribute("data-story") !== "pinned") return null;
            return st.start + ((T + CONSOLE_IN) / tl.duration()) * (st.end - st.start);
          },
        };

        function shortenPinAfterTakeover() {
          var st = tl.scrollTrigger;
          // A rebuild since the takeover already gave the scene the short tail.
          if (!st || !st.enabled || html.getAttribute("data-story") !== "pinned") return;
          var y = window.scrollY;
          con.removeDemo(tl);
          st.vars.end = "+=" + Math.round(tl.duration() * VH_PER_UNIT) + "%";
          window.ScrollTrigger.refresh();
          window.scrollTo(0, Math.min(y, st.end - 1));
        }

        return function () {
          setMoving(false);
          pin.classList.remove("is-console-moving");
          stage.style.visibility = "";
          stage.classList.remove("is-covered");
          splitNodes.forEach(unsplit);
          // A rebuild (resize, fonts) re-pins straight away; only fall back when the query no
          // longer matches (narrow window, reduced motion switched on).
          window.setTimeout(function () {
            if (!window.matchMedia(PINNED_QUERY).matches) renderStatic();
          }, 0);
        };
      }

      var hasGsap = html.getAttribute("data-motion") === "gsap";
      var mm = null;
      // Rebuilding (resize, late fonts) reverts the pin; keep the reader where they were.
      function rebuild() {
        var pinST = window.ScrollTrigger && window.ScrollTrigger.getAll().filter(function (s) {
          return s.pin;
        })[0];
        var progress = pinST ? pinST.progress : null;
        var y = window.scrollY;
        if (mm) mm.revert();
        setup();
        var next = window.ScrollTrigger && window.ScrollTrigger.getAll().filter(function (s) {
          return s.pin;
        })[0];
        window.scrollTo(0, next && progress !== null ? next.start + progress * (next.end - next.start) : y);
      }
      function setup() {
        if (!hasGsap) {
          renderStatic();
          return;
        }
        mm = window.gsap.matchMedia();
        mm.add(PINNED_QUERY, function () {
          return pinned(window.gsap);
        });
        if (!window.matchMedia(PINNED_QUERY).matches) renderStatic();
        // Triggers created after the load event are not measured until a refresh.
        else window.ScrollTrigger.refresh();
      }
      setup();

      // Stacked layout (not pinned), with GSAP and no reduced-motion preference: light, once-only
      // reveals. Start states are set here by JS, never in CSS, and each block plays its reveal
      // when scrolled to or past (a jump past still plays it), so nothing can stay hidden. The
      // context reverts on a switch to the pinned layout, and before printing.
      var revealMM = null;
      function staticReveal(gsap) {
        var cardCopy = [".closure-copy .eyebrow", "#closure-title", ".closure-lede", "[data-closure-card]"];
        var M = window.SITE_MOTION;
        M.reveal(gsap, cardCopy, { y: 20, opacity: 0, duration: 0.6, stagger: 0.08, ease: "power2.out" }, ".closure-copy", "top 90%");
        // The closed lane draws itself, then the chokepoint markers appear.
        var red = closure ? closure.closedRed : null;
        var markers = closure
          ? closure.markers.map(function (mk) {
              return mk.node;
            })
          : [];
        if (red) gsap.set(red, { opacity: 0 });
        gsap.set(markers, { opacity: 0, y: 6 });
        M.once(closureRoot, "top 75%", function () {
            if (red) {
              gsap.set(red, { opacity: 1 });
              Array.prototype.forEach.call(red.querySelectorAll("path"), function (path) {
                window.SITE_MOTION.draw(gsap, path, { duration: 1.2 });
              });
            }
            gsap.to(markers, { opacity: 1, y: 0, duration: 0.4, stagger: 0.12, delay: 0.7 });
        });
        if (con && con.staticReveal) con.staticReveal(gsap);
      }
      if (hasGsap) {
        revealMM = window.gsap.matchMedia();
        revealMM.add({ motion: MOTION_OK, pinned: PINNED_QUERY }, function (context) {
          if (!context.conditions.motion || context.conditions.pinned) return;
          // After a switch from the pinned layout the stacked frame is rebuilt a tick later
          // (renderStatic); add the reveals to this context once it exists.
          window.setTimeout(function () {
            context.add(function () {
              staticReveal(window.gsap);
            });
            window.ScrollTrigger.refresh();
          }, 30);
        });
        window.addEventListener("beforeprint", function () {
          revealMM.revert();
        });
      }

      // Printing: a pinned scene would print its current frame with later blocks still hidden.
      // Print the stacked layout instead, and rebuild the pinned scene afterwards.
      var printing = false;
      window.addEventListener("beforeprint", function () {
        if (!mm || html.getAttribute("data-story") !== "pinned") return;
        printing = true;
        mm.revert();
        renderStatic(); // leftover inline start states are overridden by the print rules in site.css
      });
      window.addEventListener("afterprint", function () {
        if (!printing) return;
        printing = false;
        rebuild();
      });

      // Line breaks and the fitted camera depend on the width: rebuild on width changes. A height
      // change only needs fresh pin lengths (they are in % of the viewport): a debounced refresh.
      // Crossing PINNED_QUERY in either direction is handled by gsap.matchMedia itself.
      var lastWidth = window.innerWidth;
      var timer = 0;
      window.addEventListener("resize", function () {
        window.clearTimeout(timer);
        timer = window.setTimeout(function () {
          if (window.innerWidth !== lastWidth) {
            lastWidth = window.innerWidth;
            rebuild();
          } else if (window.ScrollTrigger) {
            window.ScrollTrigger.refresh();
          }
        }, 250);
      });
      // Line breaks change once the web fonts arrive; rebuild only if they were not ready yet.
      if (document.fonts && document.fonts.status !== "loaded") {
        document.fonts.ready.then(rebuild);
      }
    }).catch(function (error) {
      console.error("Story scene unavailable:", error);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

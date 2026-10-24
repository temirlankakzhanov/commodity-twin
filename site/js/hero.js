// Hero: links from config, the route map, port labels, and tankers on the lanes the model uses.
// Lane status comes from site.json (the base-case plan); geometry comes from geo.json.
// Motion uses transform and opacity only; no SVG filters.
(function () {
  "use strict";

  var SVG_NS = "http://www.w3.org/2000/svg";
  var LANE_SPACING = 140; // map units between tankers on the same lane
  var SPEED = 9; // map units per second
  var HULL_UNITS = 12; // hull length in local units (stern -6, bow +6)
  var FADE_UNITS = 18; // fade in/out over this distance at each end of a lane
  var LABEL_GAP = 6; // px between a port marker and its label
  var LABELS = {
    Houston: "Houston",
    Rotterdam: "Rotterdam",
    "Ras Tanura": "Ras Tanura",
    "Sikka (India)": "Sikka",
    Ningbo: "Ningbo",
    "Novorossiysk (CPC)": "CPC",
  };
  var reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
  var narrow = window.matchMedia("(max-width: 760px)");

  function applyLinks() {
    var config = window.SITE_CONFIG || {};
    document.querySelectorAll("[data-github-link]").forEach(function (a) {
      a.href = config.githubUrl;
    });
    var app = document.querySelector("[data-app-link]");
    if (config.appUrl) {
      app.href = config.appUrl;
      return;
    }
    app.setAttribute("aria-disabled", "true");
    app.setAttribute("aria-describedby", "app-note");
    app.addEventListener("click", function (event) {
      event.preventDefault();
    });
    var note = document.querySelector("[data-app-note]");
    note.id = "app-note";
    note.hidden = false;
  }

  function el(name, attrs, parent) {
    var node = document.createElementNS(SVG_NS, name);
    Object.keys(attrs).forEach(function (key) {
      node.setAttribute(key, attrs[key]);
    });
    parent.appendChild(node);
    return node;
  }

  function formatDate(iso) {
    return new Date(iso + "T00:00:00Z").toLocaleDateString("en-GB", {
      day: "numeric",
      month: "long",
      year: "numeric",
      timeZone: "UTC",
    });
  }

  // Ship silhouette pointing along +x, with a wake that fades out behind the stern.
  function buildTanker(parent) {
    var group = el("g", { class: "tanker" }, parent);
    el("path", { d: "M-6 -1.2L-17 -3.2L-17 3.2L-6 1.2Z", fill: "url(#wake)" }, group);
    el(
      "path",
      { d: "M-6 -1.7L3.4 -1.7Q5.4 -1.7 6 0Q5.4 1.7 3.4 1.7L-6 1.7Z", class: "tanker-hull" },
      group
    );
    el("rect", { x: -5, y: -1, width: 2.2, height: 2, class: "tanker-bridge" }, group);
    return group;
  }

  function drawMap(svg, geo, site) {
    var defs = el("defs", {}, svg);
    var wake = el("linearGradient", { id: "wake", x1: "1", y1: "0", x2: "0", y2: "0" }, defs);
    el("stop", { offset: "0", "stop-color": "#f4f4f5", "stop-opacity": "0.45" }, wake);
    el("stop", { offset: "1", "stop-color": "#f4f4f5", "stop-opacity": "0" }, wake);

    el("path", { d: geo.land, class: "land" }, svg);
    var active = {};
    site.hormuz_closure.base.routes.forEach(function (row) {
      active[row.route] = row.status === "ACTIVE";
    });

    var idleGroup = el("g", {}, svg);
    var activeGroup = el("g", {}, svg);
    var lanes = [];
    Object.keys(geo.routes).forEach(function (name) {
      var d = geo.routes[name];
      if (active[name] === true) {
        el("path", { d: d, class: "lane-glow" }, activeGroup);
        lanes.push(el("path", { d: d, class: "lane-active" }, activeGroup));
      } else {
        el("path", { d: d, class: "lane-idle" }, idleGroup);
      }
    });

    var fleet = el("g", {}, svg);
    var tankers = [];
    lanes.forEach(function (path) {
      var length = path.getTotalLength();
      var count = Math.max(1, Math.min(4, Math.round(length / LANE_SPACING)));
      for (var i = 0; i < count; i += 1) {
        tankers.push({
          node: buildTanker(fleet),
          path: path,
          length: length,
          offset: ((i + 0.35) / count) * length,
        });
      }
    });

    var portGroup = el("g", {}, svg);
    var lanePoints = [];
    lanes.forEach(function (path) {
      var length = path.getTotalLength();
      for (var s = 0; s <= length; s += 3) {
        var pt = path.getPointAtLength(s);
        lanePoints.push([pt.x, pt.y]);
      }
    });
    var ports = Object.keys(geo.ports).map(function (name) {
      var xy = geo.ports[name];
      var marker = el("circle", { cx: xy[0], cy: xy[1], r: 3.2, class: "port" }, portGroup);
      return { name: LABELS[name] || name, x: xy[0], y: xy[1], marker: marker };
    });
    return { tankers: tankers, ports: ports, lanePoints: lanePoints };
  }

  // Hull length on screen: about 28 px on wide screens, 20 px on phones, whatever the zoom.
  function tankerScale(svg) {
    var pxPerUnit = svg.getScreenCTM().a;
    return (narrow.matches ? 20 : 28) / (HULL_UNITS * pxPerUnit);
  }

  function place(tanker, distance, scale) {
    var at = distance % tanker.length;
    var p = tanker.path.getPointAtLength(at);
    var q = tanker.path.getPointAtLength(Math.min(at + 1, tanker.length));
    var angle = (Math.atan2(q.y - p.y, q.x - p.x) * 180) / Math.PI;
    var fade = Math.min(1, at / FADE_UNITS, (tanker.length - at) / FADE_UNITS);
    tanker.node.setAttribute(
      "transform",
      "translate(" +
        p.x.toFixed(2) +
        " " +
        p.y.toFixed(2) +
        ") rotate(" +
        angle.toFixed(1) +
        ") scale(" +
        scale.toFixed(3) +
        ")"
    );
    tanker.node.setAttribute("opacity", Math.max(0, fade).toFixed(2));
  }

  function overlaps(a, b) {
    return a.left < b.right && a.right > b.left && a.top < b.bottom && a.bottom > b.top;
  }

  function inflate(rect, by) {
    return {
      left: rect.left - by,
      top: rect.top - by,
      right: rect.right + by,
      bottom: rect.bottom + by,
    };
  }

  // Screen boxes the labels must keep clear of: each headline line (not the whole text
  // column), the lede, the buttons and note, the map key and the masthead links.
  function obstacleRects() {
    var rects = [];
    var headline = document.getElementById("hero-title");
    if (headline) {
      var range = document.createRange();
      range.selectNodeContents(headline);
      Array.prototype.forEach.call(range.getClientRects(), function (r) {
        rects.push(inflate(r, 4));
      });
    }
    [".lede", ".actions", ".app-note:not([hidden])", ".map-key", ".wordmark", ".masthead-link"]
      .map(function (selector) {
        return document.querySelector(selector);
      })
      .filter(function (node) {
        return node && node.getClientRects().length > 0;
      })
      .forEach(function (node) {
        rects.push(inflate(node.getBoundingClientRect(), 4));
      });
    return rects;
  }

  // Each label tries eight spots around its marker. A label that cannot be placed clear of
  // the text, the map key, the masthead, other markers and labels and the map edges is
  // hidden together with its marker, so there are no unlabelled dots. Among clear spots,
  // one that does not cover an active lane is preferred.
  function placeLabels(svg, container, ports, lanePoints) {
    container.textContent = "";
    var box = container.getBoundingClientRect();
    var ctm = svg.getScreenCTM();
    var obstacles = obstacleRects();
    var visible = {
      left: Math.max(box.left, 0) + 4,
      top: Math.max(box.top, 0) + 4,
      right: Math.min(box.right, window.innerWidth) - 4,
      bottom: box.bottom - 4,
    };
    var placed = [];
    var lanes = lanePoints.map(function (p) {
      return [ctm.a * p[0] + ctm.c * p[1] + ctm.e, ctm.b * p[0] + ctm.d * p[1] + ctm.f];
    });
    var coversLane = function (r) {
      return lanes.some(function (p) {
        return p[0] > r.left && p[0] < r.right && p[1] > r.top && p[1] < r.bottom;
      });
    };
    var candidates = ports.map(function (port) {
      var cx = ctm.a * port.x + ctm.c * port.y + ctm.e;
      var cy = ctm.b * port.x + ctm.d * port.y + ctm.f;
      var marker = { left: cx - 5, top: cy - 5, right: cx + 5, bottom: cy + 5 };
      var onMap =
        cx >= visible.left && cx <= visible.right && cy >= visible.top && cy <= visible.bottom;
      var blocked = obstacles.some(function (o) {
        return overlaps(marker, o);
      });
      return { port: port, cx: cx, cy: cy, marker: marker, ok: onMap && !blocked };
    });
    candidates.forEach(function (c) {
      c.port.marker.style.visibility = c.ok ? "" : "hidden";
      if (c.ok) placed.push(c.marker);
    });
    candidates.forEach(function (c) {
      if (!c.ok) return;
      var port = c.port;
      var cx = c.cx;
      var cy = c.cy;
      var label = document.createElement("span");
      label.className = "port-label";
      label.textContent = port.name;
      container.appendChild(label);
      var w = label.offsetWidth;
      var h = label.offsetHeight;
      var g = LABEL_GAP;
      var options = [
        [cx + g, cy - h / 2], // right
        [cx - g - w, cy - h / 2], // left
        [cx - w / 2, cy - g - h], // above
        [cx - w / 2, cy + g], // below
        [cx + g / 2, cy - g / 2 - h], // above right
        [cx - g / 2 - w, cy - g / 2 - h], // above left
        [cx + g / 2, cy + g / 2], // below right
        [cx - g / 2 - w, cy + g / 2], // below left
      ];
      var spot = null;
      var fallback = null;
      for (var i = 0; i < options.length && !spot; i += 1) {
        var r = {
          left: options[i][0],
          top: options[i][1],
          right: options[i][0] + w,
          bottom: options[i][1] + h,
        };
        var inside =
          r.left >= visible.left &&
          r.right <= visible.right &&
          r.top >= visible.top &&
          r.bottom <= visible.bottom;
        var clear =
          inside &&
          !obstacles.some(function (o) {
            return overlaps(r, o);
          }) &&
          !placed.some(function (o) {
            return o !== c.marker && overlaps(inflate(r, 3), o);
          });
        if (clear && !coversLane(r)) spot = r;
        else if (clear && !fallback) fallback = r;
      }
      spot = spot || fallback;
      if (!spot) {
        label.hidden = true;
        port.marker.style.visibility = "hidden";
        return;
      }
      placed.push(spot);
      label.style.transform =
        "translate(" + Math.round(spot.left - box.left) + "px," + Math.round(spot.top - box.top) + "px)";
    });
  }

  function animate(svg, tankers, hero) {
    var running = false;
    var visible = true;
    var elapsed = 0;
    var last = 0;
    var scale = tankerScale(svg);

    function drawAll() {
      tankers.forEach(function (t) {
        place(t, t.offset + elapsed * SPEED, scale);
      });
    }

    function frame(now) {
      if (!running) return;
      if (last) elapsed += Math.min(now - last, 100) / 1000;
      last = now;
      drawAll();
      window.requestAnimationFrame(frame);
    }

    function update() {
      var shouldRun = visible && !document.hidden && !reduceMotion.matches;
      if (shouldRun && !running) {
        running = true;
        last = 0;
        window.requestAnimationFrame(frame);
      } else if (!shouldRun) {
        running = false;
      }
    }

    drawAll();
    new IntersectionObserver(function (entries) {
      visible = entries[0].isIntersecting;
      update();
    }).observe(hero);
    document.addEventListener("visibilitychange", update);
    reduceMotion.addEventListener("change", update);
    update();
    return function rescale() {
      scale = tankerScale(svg);
      drawAll();
    };
  }

  function init() {
    applyLinks();
    var svg = document.getElementById("route-map");
    var labels = document.querySelector(".port-labels");
    Promise.all([
      fetch("data/geo.json").then(function (r) {
        return r.json();
      }),
      fetch("data/site.json").then(function (r) {
        return r.json();
      }),
    ])
      .then(function (data) {
        var geo = data[0];
        var site = data[1];
        document.querySelectorAll("[data-prices-asof]").forEach(function (t) {
          t.dateTime = site.as_of.prices;
          t.textContent = formatDate(site.as_of.prices);
        });
        var setViewBox = function () {
          svg.setAttribute("viewBox", (narrow.matches ? geo.viewBoxNarrow : geo.viewBox).join(" "));
        };
        setViewBox();
        var map = drawMap(svg, geo, site);
        var rescale = animate(svg, map.tankers, document.getElementById("top"));
        var relayout = function () {
          setViewBox();
          rescale();
          placeLabels(svg, labels, map.ports, map.lanePoints);
        };
        var pending = false;
        window.addEventListener("resize", function () {
          if (pending) return;
          pending = true;
          window.requestAnimationFrame(function () {
            pending = false;
            relayout();
          });
        });
        relayout();
        if (document.fonts && document.fonts.ready) document.fonts.ready.then(relayout);
      })
      .catch(function (error) {
        console.error("Route map unavailable:", error);
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

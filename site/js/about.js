// Under the hood and the footer: numbers and dates from site.json, copy buttons, and light
// once-only effects (typing, count-up, the route divider, reveals, calm exits). With reduced
// motion, without GSAP, or when printing, everything is shown in its final state.
(function () {
  "use strict";

  function formatDate(iso) {
    return new Date(iso + "T00:00:00Z").toLocaleDateString("en-GB", {
      day: "numeric",
      month: "short",
      year: "numeric",
      timeZone: "UTC",
    });
  }

  function fill(site) {
    var get = function (key) {
      return document.querySelector('[data-a="' + key + '"]');
    };
    var f = site.facts;
    get("tests").textContent = String(f.tests_passed);
    get("tests-text").textContent = f.tests_passed + " tests pass" + (f.tests_skipped ? ", " + f.tests_skipped + " skipped" : "") + ".";
    get("tests-note").textContent =
      (f.tests_skipped ? f.tests_skipped + " skipped. " : "") + "Counted from the pytest run that built this page's data.";
    var a = site.as_of;
    get("bottom-line").textContent = "\u00a9 2026 Temirlan Kakzhanov \u00b7 Code: MIT \u00b7 Data as of " + formatDate(a.prices);
    get("asof").textContent =
      "Data as of: prices " + formatDate(a.prices) + ", transits " + formatDate(a.transits) +
      (a.snapshot_fetched ? "; snapshot taken " + formatDate(a.snapshot_fetched) : "") + ".";
  }

  // Copy to the clipboard: the async API first, then the older selection-based copy if the
  // browser refuses it (some embedded browsers deny clipboard permission).
  function legacyCopy(text) {
    var area = document.createElement("textarea");
    area.value = text;
    area.setAttribute("readonly", "");
    area.style.position = "fixed";
    area.style.top = "0";
    area.style.opacity = "0";
    document.body.appendChild(area);
    area.select();
    var ok = false;
    try {
      ok = document.execCommand("copy");
    } catch (e) {
      ok = false;
    }
    document.body.removeChild(area);
    return ok;
  }
  function copyText(text) {
    var fallback = function () {
      return legacyCopy(text) ? Promise.resolve() : Promise.reject(new Error("copy failed"));
    };
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text).catch(fallback);
    }
    return fallback();
  }

  // "How it works": in the pinned scene the console lives inside the pin, so the anchor would
  // land at the scene start (the hero). Scroll to where the console has grown in instead; in the
  // stacked layout the plain anchor is right.
  function wireJumps() {
    document.querySelectorAll('[data-jump="console"]').forEach(function (link) {
      link.addEventListener("click", function (event) {
        var story = window.SITE_STORY;
        if (!story || !story.consoleY || story.consoleY() === null) return;
        event.preventDefault();
        // This click may also end the console demo, which shortens the pin about 150 ms later
        // and resets the scroll position; start the scroll after that, from the live timeline.
        window.setTimeout(function () {
          var y = story.consoleY();
          if (y === null) return;
          var reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
          window.scrollTo({ top: Math.ceil(y) + 2, behavior: reduce ? "auto" : "smooth" });
        }, 250);
      });
    });
  }

  function wireCopy() {
    var status = document.querySelector('[data-a="copy-status"]');
    document.querySelectorAll(".copy-btn").forEach(function (button) {
      var label = button.querySelector(".copy-text");
      var idle = label.textContent;
      var timer = 0;
      button.addEventListener("click", function () {
        var text = button.getAttribute("data-copy-text");
        if (!text) {
          var source = document.getElementById(button.getAttribute("data-copy"));
          text = Array.prototype.map
            .call(source.querySelectorAll(".code-line"), function (line) {
              return line.textContent;
            })
            .join("\n");
        }
        copyText(text).then(
          function () {
            button.classList.add("is-copied");
            label.textContent = "Copied";
            if (status) status.textContent = "Copied to the clipboard.";
            window.clearTimeout(timer);
            timer = window.setTimeout(function () {
              button.classList.remove("is-copied");
              label.textContent = idle;
              if (status) status.textContent = "";
            }, 1500);
          },
          function () {
            if (status) status.textContent = "Copy failed; please select the text instead.";
          }
        );
      });
    });
  }

  // A scrubbed step back for a block while the next section comes up (as in the 3 to 4 change).
  function exit(gsap, target, next) {
    gsap.fromTo(
      target,
      { scale: 1, opacity: 1 },
      {
        scale: 0.98,
        opacity: 0.6,
        ease: "none",
        immediateRender: false,
        transformOrigin: "50% 0%",
        scrollTrigger: {
          trigger: next,
          start: "top bottom",
          end: "top 45%",
          scrub: true,
          onToggle: function (self) {
            target.style.willChange = self.isActive ? "transform, opacity" : "";
          },
        },
      }
    );
  }

  function motion(gsap, site) {
    var M = window.SITE_MOTION;
    var hood = document.getElementById("hood");
    var footer = document.getElementById("limits");
    var crisesGrid = document.querySelector(".crisis-grid");
    if (crisesGrid) exit(gsap, crisesGrid, hood);
    exit(gsap, hood.querySelector(".hood-inner"), footer);

    M.reveal(gsap, hood.querySelectorAll(".hood-head > *"), { y: 24, opacity: 0, duration: 0.6, stagger: 0.08, ease: "power2.out" }, hood, "top 80%");
    M.reveal(gsap, hood.querySelectorAll(".hood-facts, .hood-code"), { y: 28, opacity: 0, duration: 0.6, stagger: 0.12, ease: "power2.out" }, hood.querySelector(".hood-grid"), "top 80%");

    // The tests count runs up once; the final number is in the DOM all along.
    var num = hood.querySelector('[data-a="tests"]');
    var target = site.facts.tests_passed;
    var counter = { v: 0 };
    M.once(num, "top 85%", function () {
      gsap.fromTo(
        counter,
        { v: 0 },
        {
          v: target,
          duration: 0.8,
          ease: "power1.out",
          onUpdate: function () {
            num.textContent = String(Math.round(counter.v));
          },
          onComplete: function () {
            num.textContent = String(target);
          },
        }
      );
    });

    // The quick start lines type out once: a cover the colour of the block steps off each line.
    var lines = Array.prototype.slice.call(hood.querySelectorAll(".code-line"));
    var covers = lines.map(function (line) {
      var cover = document.createElement("span");
      cover.className = "type-cover";
      cover.setAttribute("aria-hidden", "true");
      line.appendChild(cover);
      return cover;
    });
    M.once(hood.querySelector(".code-block"), "top 85%", function () {
      var total = lines.reduce(function (n, line) {
        return n + line.textContent.length;
      }, 0);
      var at = 0.15;
      lines.forEach(function (line, i) {
        var chars = Math.max(1, line.textContent.length);
        var d = (1.0 * chars) / total;
        gsap.fromTo(covers[i], { scaleX: 1 }, { scaleX: 0, duration: d, delay: at, ease: "steps(" + chars + ")" });
        at += d;
      });
    });

    // The route divider draws once, left to right.
    var path = document.querySelector(".route-path");
    if (path) M.once(path.closest(".route-divider"), "top 90%", function () {
      M.draw(gsap, path, { duration: 1.4 });
    });

    M.reveal(gsap, footer.querySelectorAll("h2, .footer-block"), { y: 24, opacity: 0, duration: 0.6, stagger: 0.1, ease: "power2.out" }, footer, "top 85%");

    window.ScrollTrigger.refresh();
    // Leaving this context (reduced motion switched on, printing) shows every line whole.
    return function () {
      covers.forEach(function (cover) {
        if (cover.parentNode) cover.parentNode.removeChild(cover);
      });
      num.textContent = String(target);
    };
  }

  function init() {
    if (!document.getElementById("hood") || !window.SITE_DATA) return;
    Promise.all([window.SITE_DATA, window.SITE_DOM_READY]).then(function (results) {
      var site = results[0][1];
      fill(site);
      wireCopy();
      wireJumps();
      if (document.documentElement.getAttribute("data-motion") !== "gsap" || !window.SITE_MOTION) return;
      var mm = window.gsap.matchMedia();
      mm.add("(prefers-reduced-motion: no-preference)", function () {
        return motion(window.gsap, site);
      });
      window.addEventListener("beforeprint", function () {
        mm.revert();
      });
    }).catch(function (error) {
      console.error("Under-the-hood section unavailable:", error);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();

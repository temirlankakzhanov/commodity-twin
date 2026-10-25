// GSAP is optional. It is not in the repository: `make site-assets` and the Pages workflow
// download the pinned release into vendor/gsap. Without it the page stays fully usable and
// scroll sections render in their final, static state (the same path as reduced motion).
(function () {
  "use strict";

  var root = document.documentElement;
  var hasGsap = typeof window.gsap === "object" && typeof window.ScrollTrigger === "function";
  if (hasGsap) {
    window.gsap.registerPlugin(window.ScrollTrigger);
  }
  root.setAttribute("data-motion", hasGsap ? "gsap" : "static");

  // Shared helpers for the once-only reveals of the stacked (non-pinned) layout.
  window.SITE_MOTION = {
    // On-screen length of an SVG path in CSS pixels. Lanes and chart lines use
    // vector-effect: non-scaling-stroke, which makes dash lengths screen pixels, so a "draw" needs
    // the screen length, not getTotalLength(). Read once, when the drawing starts.
    screenLength: function (path) {
      var ctm = path.getScreenCTM();
      var total = path.getTotalLength();
      if (!ctm || !total) return 0;
      var steps = 160;
      var length = 0;
      var last = null;
      for (var i = 0; i <= steps; i += 1) {
        var p = path.getPointAtLength((total * i) / steps);
        var x = ctm.a * p.x + ctm.c * p.y + ctm.e;
        var y = ctm.b * p.x + ctm.d * p.y + ctm.f;
        if (last) length += Math.hypot(x - last[0], y - last[1]);
        last = [x, y];
      }
      return length;
    },
    // Run fn once when the trigger is reached or jumped past (anchor link, scrollbar drag): a
    // ScrollTrigger with once: true kills itself on a jump before a linked animation starts, so
    // the animation is kept separate and both onEnter and onLeave start it.
    once: function (trigger, start, fn) {
      var done = false;
      var run = function () {
        if (done) return;
        done = true;
        fn();
      };
      return window.ScrollTrigger.create({ trigger: trigger, start: start, onEnter: run, onLeave: run });
    },
    // A from-tween that waits (paused, start state already applied) until its block is reached.
    reveal: function (gsap, targets, vars, trigger, start) {
      var tween = gsap.from(targets, Object.assign({ paused: true, immediateRender: true }, vars));
      window.SITE_MOTION.once(trigger, start, function () {
        tween.play();
      });
      return tween;
    },
    // Draw a path once (dash offset from its length to 0), then drop the dash styles so the path
    // is exactly as before.
    draw: function (gsap, path, options) {
      var length = window.SITE_MOTION.screenLength(path);
      if (!length) return null;
      // gsap.set (not a style write) so that reverting the matchMedia context restores the path.
      gsap.set(path, { strokeDasharray: length + " " + length, strokeDashoffset: length });
      return gsap.to(path, {
        strokeDashoffset: 0,
        duration: (options && options.duration) || 1.1,
        delay: (options && options.delay) || 0,
        ease: "power2.inOut",
        onComplete: function () {
          path.style.strokeDasharray = "";
          path.style.strokeDashoffset = "";
        },
      });
    },
  };

  // Dev-only frame meter: nothing is loaded unless the URL asks for it.
  if (/[?&]debug=fps(&|$)/.test(window.location.search)) {
    var meter = document.createElement("script");
    meter.src = "js/debug-fps.js";
    document.head.appendChild(meter);
  }
})();

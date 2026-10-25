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

  // Dev-only frame meter: nothing is loaded unless the URL asks for it.
  if (/[?&]debug=fps(&|$)/.test(window.location.search)) {
    var meter = document.createElement("script");
    meter.src = "js/debug-fps.js";
    document.head.appendChild(meter);
  }
})();

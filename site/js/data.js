// Shared loader: every section reads the same two generated files, fetched once.
window.SITE_DATA = Promise.all(
  ["data/geo.json", "data/site.json"].map(function (url) {
    return fetch(url).then(function (response) {
      if (!response.ok) throw new Error(url + " returned " + response.status);
      return response.json();
    });
  })
);

// The daily backtest series (validation.json) is larger and only the Validation tab needs it:
// it is fetched in idle time after the page has loaded, never on a click, so the tab opens at
// once. SITE_VALIDATION resolves with the series, or rejects if the file cannot be loaded.
window.SITE_VALIDATION = new Promise(function (resolve, reject) {
  function load() {
    fetch("data/validation.json")
      .then(function (response) {
        if (!response.ok) throw new Error("data/validation.json returned " + response.status);
        return response.json();
      })
      .then(resolve, reject);
  }
  function idle() {
    if (window.requestIdleCallback) window.requestIdleCallback(load, { timeout: 2500 });
    else window.setTimeout(load, 600);
  }
  if (document.readyState === "complete") idle();
  else window.addEventListener("load", idle, { once: true });
});

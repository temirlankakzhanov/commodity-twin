// Shared loader: every section reads the same two generated files, fetched once.
window.SITE_DATA = Promise.all(
  ["data/geo.json", "data/site.json"].map(function (url) {
    return fetch(url).then(function (response) {
      if (!response.ok) throw new Error(url + " returned " + response.status);
      return response.json();
    });
  })
);

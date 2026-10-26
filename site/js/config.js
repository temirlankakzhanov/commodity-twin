// The one place to set public links. index.html repeats appUrl in its Launch the app links so
// they work without JavaScript; tests/test_site_assets.py fails if the two differ.
window.SITE_CONFIG = Object.freeze({
  appUrl: "https://commodity-twin.streamlit.app",
  githubUrl: "https://github.com/temirlankakzhanov/commodity-twin",
});

/**
 * Pre-paint dark-mode flip only. Extracted from theme-toggle.js's
 * stored()/preferred()/apply() so React pages can set data-theme on <html>
 * before first paint without pulling in theme-toggle.js's button-mounting
 * code (which assumes header.js's DOM-injection #appHeader, not present on
 * React-mounted pages).
 *
 * Load in <head> BEFORE the page renders, to avoid a flash:
 *   <script src="/static/theme-preboot.js"></script>
 *
 * theme-toggle.js itself is untouched and still used as-is by index.html,
 * admin.html and translate.html. Both scripts read/write the same
 * localStorage key ("zeno-theme"), so a choice made on either kind of page
 * carries over to the other.
 */
(function initThemePreboot() {
  var KEY = 'zeno-theme';

  function stored() {
    try { return localStorage.getItem(KEY); } catch (e) { return null; }
  }

  function preferred() {
    var s = stored();
    if (s === 'light' || s === 'dark') return s;
    return window.matchMedia &&
      window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  document.documentElement.setAttribute('data-theme', preferred());
})();

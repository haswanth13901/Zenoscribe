/**
 * Pre-paint dark-mode flip only, for the React SPA shell (frontend/index.html).
 * Sets data-theme on <html> before first paint so there's no flash while
 * React mounts and ThemeToggleButton takes over. Reads/writes the same
 * localStorage key ("zeno-theme") as the app's own theme toggle.
 *
 * Deliberately does NOT fall back to prefers-color-scheme - the app's
 * baseline is always light regardless of OS/browser setting; only an
 * explicit click on the theme toggle (which persists to the same
 * localStorage key) ever switches it to dark.
 *
 * Lives here in frontend/public/ (copied verbatim into frontend/dist/ on
 * build, same as every other public/ file).
 */
(function initThemePreboot() {
  var KEY = "zeno-theme";

  function stored() {
    try {
      return localStorage.getItem(KEY);
    } catch (e) {
      return null;
    }
  }

  function preferred() {
    var s = stored();
    return s === "dark" ? "dark" : "light";
  }

  document.documentElement.setAttribute("data-theme", preferred());
})();

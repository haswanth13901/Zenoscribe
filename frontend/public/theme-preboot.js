/**
 * Pre-paint dark-mode flip only, for the React SPA shell (frontend/index.html).
 * Sets data-theme on <html> before first paint so there's no flash while
 * React mounts and ThemeToggleButton takes over. Reads/writes the same
 * localStorage key ("zeno-theme") as the app's own theme toggle.
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
    if (s === "light" || s === "dark") return s;
    return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark"
      : "light";
  }

  document.documentElement.setAttribute("data-theme", preferred());
})();

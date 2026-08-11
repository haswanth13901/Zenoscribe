/**
 * Theme switch — light ("cool clinical") / dark (your original palette).
 *
 * Load in <head> BEFORE the page renders, to avoid a flash:
 *   <script src="/static/theme-toggle.js"></script>
 *
 * It sets data-theme on <html> immediately, then mounts an icon-only button
 * into #appHeader (just before the account chip) once header.js has run; if
 * the page has no header it falls back to a fixed bottom-left button.
 *
 * Choice is stored in localStorage under "zeno-theme"; first visit follows the
 * operating system setting.
 */
(function initThemeToggle() {
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

  // Each icon shows the theme a click switches TO, matching the old
  // "Light"/"Dark" button-text convention.
  var ICON_SUN = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="4"></circle><line x1="12" y1="2" x2="12" y2="4"></line><line x1="12" y1="20" x2="12" y2="22"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="2" y1="12" x2="4" y2="12"></line><line x1="20" y1="12" x2="22" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line></svg>';
  var ICON_MOON = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path></svg>';

  function apply(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    var btn = document.getElementById('themeToggle');
    if (btn) {
      btn.innerHTML = theme === 'dark' ? ICON_SUN : ICON_MOON;
      var label = theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme';
      btn.title = label;
      btn.setAttribute('aria-label', label);
    }
  }

  apply(preferred()); // before first paint when loaded in <head>

  var style = document.createElement('style');
  style.textContent = [
    '#themeToggle { width: 34px; height: 34px; padding: 0; flex: none;',
    '  display: flex; align-items: center; justify-content: center;',
    '  border-radius: 8px; cursor: pointer; }',
    '#themeToggle.floating { position: fixed; left: 14px; bottom: 14px; z-index: 20; }'
  ].join('\n');

  function mount() {
    if (document.getElementById('themeToggle')) return;
    if (!style.parentNode) document.head.appendChild(style);

    var btn = document.createElement('button');
    btn.id = 'themeToggle';
    btn.type = 'button';
    btn.onclick = function () {
      var next = document.documentElement.getAttribute('data-theme') === 'dark'
        ? 'light' : 'dark';
      try { localStorage.setItem(KEY, next); } catch (e) {}
      apply(next);
    };

    var header = document.getElementById('appHeader');
    var acct = document.getElementById('acct');
    if (header && acct) header.insertBefore(btn, acct);
    else if (header) header.appendChild(btn);
    else { btn.classList.add('floating'); document.body.appendChild(btn); }

    apply(document.documentElement.getAttribute('data-theme'));
  }

  document.addEventListener('zeno:header-ready', mount);

  function whenReady() {
    var tries = 0;
    (function poll() {
      if (document.getElementById('acct') || tries++ > 30) return mount();
      requestAnimationFrame(poll);
    })();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', whenReady);
  } else {
    whenReady();
  }
})();

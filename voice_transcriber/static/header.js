/**
 * Shared header: brand/home button + sign-out.
 *
 * STABLE FILE - do not edit, restructure, or add anything to #appHeader from
 * here or from any other script without checking with the project owner
 * first. This file renders exactly three things - the home button, the
 * "who" username (left in place by the host page), and sign-out - and
 * nothing else may ever be inserted into #appHeader. Any feature needing a
 * home-adjacent control (e.g. a sidebar toggle) belongs in its own element
 * placed elsewhere on the page, never inside the header.
 *
 * Included by index.html, admin.html and translate.html. Each host page
 * defines <header id="appHeader"> with whatever page-specific controls it
 * needs; this script prepends the Zenoscribe home button and appends the
 * Sign out button into that same element, so the markup and behaviour for
 * both live in one place instead of being duplicated per page.
 *
 * Home routes to /admin or /app depending on the signed-in user's role,
 * read directly from sessionStorage so this script has no dependency on
 * globals defined by the host page's own script.
 */
(function initHeader() {
  const header = document.getElementById('appHeader');
  if (!header) return; // page didn't opt in

  const me = JSON.parse(sessionStorage.getItem('user') || 'null');
  const homeHref = me && me.role === 'admin' ? '/admin' : '/app';

  const home = document.createElement('h1');
  home.id = 'homeBtn';
  home.textContent = 'Zenoscribe';
  home.title = 'Home';
  home.style.cursor = 'pointer';
  home.onclick = () => { location.href = homeHref; };
  header.insertBefore(home, header.firstChild);

  const signOut = document.createElement('button');
  signOut.id = 'out';
  signOut.textContent = 'Sign out';
  signOut.onclick = () => { sessionStorage.clear(); location.href = '/login'; };
  header.appendChild(signOut);
})();

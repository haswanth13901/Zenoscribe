/**
 * Shared header: brand, live status pill, account chip with a sign-out
 * dropdown.
 *
 * Replaces the previous header.js. Same contract as before — each host page
 * defines <header id="appHeader"> containing its own #status and #who; this
 * script prepends the brand and appends the account chip, so all pages share
 * one header implementation. theme-toggle.js mounts its own icon button into
 * this header once #acct exists (see zeno:header-ready below).
 *
 * Included by index.html, admin.html, home.html and translate.html.
 * Clicking the brand always goes to /home, the shared dashboard.
 */
(function initHeader() {
  var header = document.getElementById('appHeader');
  if (!header) return; // page didn't opt in

  var me = JSON.parse(sessionStorage.getItem('user') || 'null');
  var homeHref = '/home';

  var style = document.createElement('style');
  style.textContent = [
    '#appHeader { padding: 0 18px; height: 52px; background: var(--panel);',
    '  border-bottom: 1px solid var(--line); display: flex; align-items: center;',
    '  gap: 14px; flex: none; }',

    '#homeBtn { display: flex; align-items: center; gap: 9px; margin: 0;',
    '  font-size: 12.5px; font-weight: 700; letter-spacing: .14em; cursor: pointer;',
    '  color: var(--text); white-space: nowrap; }',
    '#homeBtn .dot { width: 10px; height: 10px; border-radius: 50%;',
    '  background: var(--accent); flex: none; }',

    /* #status is defined by the host page; render it as a pill here. */
    '#appHeader #status { font-size: 12px; color: var(--muted);',
    '  padding: 4px 10px; border-radius: 20px; border: 1px solid transparent;',
    '  white-space: nowrap; }',
    '#appHeader #status.live { color: var(--rec); background: var(--rec-soft);',
    '  border-color: var(--line); font-weight: 600; }',

    '#appHeader .spacer { flex: 1; }',

    '#acct { position: relative; display: flex; align-items: center; gap: 8px;',
    '  white-space: nowrap; cursor: pointer; padding: 5px 8px 5px 5px;',
    '  border-radius: 20px; border: 1px solid transparent; }',
    '#acct:hover, #acct.open { background: var(--hover); border-color: var(--line); }',
    '#acct .av { width: 24px; height: 24px; border-radius: 50%;',
    '  background: var(--accent); color: var(--accent-ink); display: grid;',
    '  place-items: center; font-size: 11px; font-weight: 700; flex: none; }',
    '#appHeader #who { font-size: 12.5px; color: var(--muted); }',

    '#acctMenu { position: absolute; top: calc(100% + 8px); right: 0;',
    '  min-width: 150px; background: var(--panel); border: 1px solid var(--line);',
    '  border-radius: 9px; box-shadow: 0 10px 28px rgba(0,0,0,.18);',
    '  padding: 6px; z-index: 40; display: none; }',
    '#acctMenu.open { display: block; }',
    '#acctMenu button { width: 100%; text-align: left; background: transparent;',
    '  border: 0; padding: 8px 10px; border-radius: 6px; font: inherit;',
    '  font-size: 13px; color: var(--text); cursor: pointer; }',
    '#acctMenu button:hover { background: var(--hover); }',

    '@media (max-width: 640px) {',
    '  #appHeader { gap: 10px; }',
    '  #appHeader #who { display: none; }',
    '}'
  ].join('\n');
  document.head.appendChild(style);

  var home = document.createElement('h1');
  home.id = 'homeBtn';
  home.title = 'Home';
  home.innerHTML = '<span class="dot"></span><span>ZENOSCRIBE</span>';
  home.onclick = function () { location.href = homeHref; };
  header.insertBefore(home, header.firstChild);

  // Wrap the page's #who in a clickable account chip with an initials
  // avatar; the chip opens a small dropdown holding Sign out.
  var who = document.getElementById('who');
  if (who) {
    var acct = document.createElement('span');
    acct.id = 'acct';
    acct.tabIndex = 0;

    var av = document.createElement('span');
    av.className = 'av';
    var name = (me && me.username) || who.textContent || '';
    var parts = String(name).split(/[\s._-]+/).filter(Boolean);
    av.textContent = (parts.length > 1
      ? parts[0][0] + parts[1][0]
      : String(name).slice(0, 2)).toUpperCase() || '··';

    who.parentNode.insertBefore(acct, who);
    acct.appendChild(av);
    acct.appendChild(who);

    var menu = document.createElement('div');
    menu.id = 'acctMenu';
    var signOut = document.createElement('button');
    signOut.id = 'out';
    signOut.textContent = 'Sign out';
    signOut.onclick = function (e) {
      e.stopPropagation();
      sessionStorage.clear();
      location.href = '/login';
    };
    menu.appendChild(signOut);
    acct.appendChild(menu);

    function toggleMenu(e) {
      e.stopPropagation();
      var open = menu.classList.toggle('open');
      acct.classList.toggle('open', open);
    }
    function closeMenu() {
      menu.classList.remove('open');
      acct.classList.remove('open');
    }
    acct.addEventListener('click', toggleMenu);
    acct.addEventListener('keydown', function (e) {
      if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleMenu(e); }
      if (e.key === 'Escape') closeMenu();
    });
    document.addEventListener('click', closeMenu);
  }

  // theme-toggle.js mounts its icon button here, before #acct.
  document.dispatchEvent(new Event('zeno:header-ready'));
})();

/**
 * Shared left-hand sidebar: static, identical cross-page navigation (Admin
 * console, All Recordings, Recorder, Translate, Upload) plus one per-page
 * feature trigger (My recordings, relocated only where it exists).
 *
 * Included by index.html, admin.html and translate.html, after each host
 * page's own inline script has already wired up its buttons. This script:
 *   1. Wraps the page's <main> in a flex row together with a new
 *      <nav id="appSidebar">, so the two sit side by side. Everything above
 *      that row (header, page-specific toolbars/tabs) is left untouched.
 *   2. Creates fresh nav links in a fixed order, identical on every page:
 *      Admin console and All Recordings (admin role only), Recorder,
 *      Translate, Upload. All Recordings deep-links into admin.html's
 *      existing Users/All Recordings tab switch (?tab=recordings) rather
 *      than duplicating that logic - see admin.html's own script.
 *   3. Relocates My recordings (histBtn) out of a hidden
 *      <div id="featureStaging"> into the sidebar, keeping whatever click
 *      handler the host page already attached to it - only its DOM parent
 *      changes. Pages without it simply don't get that entry.
 *   4. Adds a hamburger toggle for the sidebar inside its own thin strip
 *      (#sidebarBar), inserted directly above the sidebar+main row - below
 *      the header and below any page-specific bar (admin's tabs, translate's
 *      controls). This script never touches #appHeader or header.js's
 *      elements in any way. The toggle slides right to track the sidebar's
 *      edge when expanded, and back to the left edge when collapsed.
 */
(function initSidebar() {
  const main = document.querySelector('main');
  if (!main || !main.parentNode) return; // page didn't opt in

  const me = JSON.parse(sessionStorage.getItem('user') || 'null');
  const path = location.pathname.replace(/\/+$/, '') || '/';

  const style = document.createElement('style');
  style.textContent = `
    #appLayout { display: flex; flex: 1; min-height: 0; overflow: hidden; }
    #appSidebar {
      flex: 0 0 190px; width: 190px; background: var(--panel);
      border-right: 1px solid var(--line); padding: 14px 10px;
      display: flex; flex-direction: column; justify-content: flex-start;
      align-items: stretch; gap: 4px; overflow-y: auto;
      overflow-x: hidden; white-space: nowrap;
      transition: flex-basis .15s ease, width .15s ease, padding .15s ease;
    }
    #appSidebar.collapsed {
      flex-basis: 0; width: 0; padding-left: 0; padding-right: 0;
      border-right: none;
    }
    #appSidebar button {
      display: block; width: 100%; text-align: left; background: transparent;
      border: 1px solid transparent; padding: 9px 12px; border-radius: 7px;
      font: inherit; font-size: 14px; color: var(--text); cursor: pointer;
    }
    #appSidebar button:hover { background: var(--bg); border-color: var(--line); }
    #appSidebar button.active, #appSidebar button.on {
      background: var(--accent, #6ea8fe); color: #0b1220;
      font-weight: 600; border-color: var(--accent, #6ea8fe);
    }
    #sidebarBar {
      padding: 8px 20px; display: flex; align-items: center; position: relative;
    }
    #sidebarToggle {
      position: relative; left: 135px; padding: 8px 10px;
      font-size: 15px; line-height: 1;
      transition: left .15s ease;
    }
    #sidebarToggle.collapsed { left: 0; }
  `;
  document.head.appendChild(style);

  const bar = document.createElement('div');
  bar.id = 'sidebarBar';
  main.parentNode.insertBefore(bar, main);

  const toggle = document.createElement('button');
  toggle.id = 'sidebarToggle';
  toggle.textContent = '☰';
  toggle.title = 'Toggle sidebar';
  bar.appendChild(toggle);

  const layout = document.createElement('div');
  layout.id = 'appLayout';
  main.parentNode.insertBefore(layout, main);

  const sidebar = document.createElement('nav');
  sidebar.id = 'appSidebar';
  layout.appendChild(sidebar);
  layout.appendChild(main);

  function navLink(label, href) {
    const btn = document.createElement('button');
    btn.textContent = label;
    btn.onclick = () => { location.href = href; };
    if (path === href) btn.classList.add('active');
    sidebar.appendChild(btn);
  }

  function relocate(id) {
    const el = document.getElementById(id);
    if (el) sidebar.appendChild(el);
  }

  function allRecordingsLink() {
    const btn = document.createElement('button');
    btn.textContent = 'All Recordings';
    btn.onclick = () => {
      if (location.pathname.replace(/\/+$/, '') === '/admin') {
        const tabRecs = document.getElementById('tabRecs');
        if (tabRecs) tabRecs.click();
      } else {
        location.href = '/admin?tab=recordings';
      }
    };
    sidebar.appendChild(btn);
  }

  if (me && me.role === 'admin') {
    navLink('Admin console', '/admin');
    allRecordingsLink();
  }
  navLink('Recorder', '/app');
  navLink('Translate', '/translate');
  relocate('uploadBtn');
  relocate('histBtn');

  const staging = document.getElementById('featureStaging');
  if (staging) staging.remove();

  toggle.onclick = () => {
    const collapsed = sidebar.classList.toggle('collapsed');
    toggle.classList.toggle('collapsed', collapsed);
  };
})();

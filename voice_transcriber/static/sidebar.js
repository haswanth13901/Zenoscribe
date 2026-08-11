/**
 * Shared left-hand sidebar: static, identical cross-page navigation (Admin
 * console, All Recordings, Recorder, Translate, Upload) plus one per-page
 * feature trigger (My recordings, relocated only where it exists).
 *
 * Included by index.html, admin.html, home.html and translate.html, after
 * each host page's own inline script has already wired up its buttons. This
 * script:
 *   1. Wraps the page's <main> in a flex row together with a new
 *      <nav id="appSidebar">, so the two sit side by side. Everything above
 *      that row (header, page-specific toolbars/tabs) is left untouched.
 *   2. Creates fresh nav links in a fixed order, grouped under "Workspace"
 *      (Home, Recorder, Translate, Upload, My recordings) and, for admins
 *      only, "Admin" (Admin console, All Recordings). All Recordings
 *      deep-links into admin.html's existing Users/All Recordings tab switch
 *      (?tab=recordings) rather than duplicating that logic - see
 *      admin.html's own script.
 *   3. Relocates My recordings (histBtn) out of a hidden
 *      <div id="featureStaging"> into the sidebar, keeping whatever click
 *      handler the host page already attached to it - only its DOM parent
 *      changes. Pages without it simply don't get that entry.
 *   4. Adds a collapse toggle: a panel icon that visually sits next to the
 *      "Workspace" label. It's a sibling of #appSidebar inside #appLayout,
 *      absolutely positioned rather than a normal child of the sidebar, so
 *      it stays in place and clickable even after the sidebar collapses to
 *      zero width - collapsing only hides the "Workspace" text it lines up
 *      with, never the icon itself.
 */
(function initSidebar() {
  const main = document.querySelector('main');
  if (!main || !main.parentNode) return; // page didn't opt in

  const me = JSON.parse(sessionStorage.getItem('user') || 'null');
  const path = location.pathname.replace(/\/+$/, '') || '/';

  const style = document.createElement('style');
  style.textContent = `
    #appLayout { display: flex; flex: 1; min-height: 0; overflow: hidden; position: relative; }
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
      border: 1px solid transparent; padding: 10px 14px; border-radius: 10px;
      font: inherit; font-size: 14px; color: var(--text); cursor: pointer;
    }
    #appSidebar button:hover { background: var(--bg); border-color: var(--line); }
    #appSidebar button.active, #appSidebar button.on {
      background: var(--accent-soft); color: var(--accent);
      font-weight: 700; border-color: var(--accent-soft);
    }
    #appSidebar .navGroup {
      font-size: 10.5px; font-weight: 700; letter-spacing: .6px;
      text-transform: uppercase; color: var(--muted); padding: 12px 12px 4px 34px;
    }
    #appSidebar .navGroup:first-child { padding-top: 4px; }

    #appMainCol { flex: 1; min-width: 0; display: flex; flex-direction: column; min-height: 0; }

    #sidebarToggle {
      position: absolute; top: 15px; left: 14px; z-index: 5;
      width: 20px; height: 20px; padding: 0; display: flex;
      align-items: center; justify-content: center; background: transparent;
      border: 0; border-radius: 5px; color: var(--muted); cursor: pointer;
    }
    #sidebarToggle:hover { background: var(--hover); color: var(--text); }
  `;
  document.head.appendChild(style);

  const layout = document.createElement('div');
  layout.id = 'appLayout';
  main.parentNode.insertBefore(layout, main);

  const sidebar = document.createElement('nav');
  sidebar.id = 'appSidebar';
  layout.appendChild(sidebar);

  // Any page-specific toolbar sitting between the header and <main> (e.g.
  // Translate's .controls, Admin's .tabs) belongs in the same scrolling
  // column as main, so the sidebar spans the full height beside both -
  // instead of the toolbar spanning full width above the whole layout and
  // pushing the sidebar down below it.
  const header = document.getElementById('appHeader');
  const mainCol = document.createElement('div');
  mainCol.id = 'appMainCol';
  if (header) {
    let n = header.nextElementSibling;
    while (n && n !== layout) {
      const next = n.nextElementSibling;
      mainCol.appendChild(n);
      n = next;
    }
  }
  mainCol.appendChild(main);
  layout.appendChild(mainCol);

  const toggleBtn = document.createElement('button');
  toggleBtn.id = 'sidebarToggle';
  toggleBtn.type = 'button';
  toggleBtn.title = 'Toggle sidebar';
  toggleBtn.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"></rect><line x1="9" y1="3" x2="9" y2="21"></line></svg>';
  toggleBtn.onclick = () => { sidebar.classList.toggle('collapsed'); };
  layout.appendChild(toggleBtn);

  function groupLabel(text) {
    const label = document.createElement('div');
    label.className = 'navGroup';
    label.textContent = text;
    sidebar.appendChild(label);
  }

  function navLink(label, href) {
    const btn = document.createElement('button');
    btn.textContent = label;
    btn.onclick = () => { location.href = href; };
    if (path === href) btn.classList.add('active');
    sidebar.appendChild(btn);
  }

  // Pages that own the feature (index.html, admin.html) already render the
  // trigger button; relocate it in place so its click handler survives.
  // Pages that don't (home.html, translate.html) get a plain link to the
  // feature's home on /app instead, so the nav stays identical everywhere.
  function relocateOrLink(id, label, href) {
    const el = document.getElementById(id);
    if (el) sidebar.appendChild(el);
    else navLink(label, href);
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

  groupLabel('Workspace');
  navLink('Home', '/home');
  navLink('Recorder', '/app');
  navLink('Translate', '/translate');
  relocateOrLink('uploadBtn', 'Upload', '/app');
  relocateOrLink('histBtn', 'My recordings', '/app?recordings=1');

  if (me && me.role === 'admin') {
    groupLabel('Admin');
    navLink('Admin console', '/admin');
    allRecordingsLink();
  }

  const staging = document.getElementById('featureStaging');
  if (staging) staging.remove();
})();

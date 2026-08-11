/**
 * Translate views: Columns / Stacked / Focus.
 *
 * Drop-in for translate.html. Add AFTER the page's own inline script:
 *   <script src="/static/translate-views.js"></script>
 *
 * Columns  – the page as it is today (Heard | Translation side by side).
 * Stacked  – one chronological feed: each utterance with its translation
 *            indented directly underneath.
 * Focus    – only the newest utterance, large, for someone reading the room.
 *
 * No page logic is touched. The two existing streams keep receiving captions
 * exactly as before; Stacked and Focus are rendered from them by pairing
 * #srcStream .utt with #tgtStream .utt by index, rebuilt on mutation.
 * The choice is remembered in localStorage under "zeno-view".
 */
(function initTranslateViews() {
  var KEY = 'zeno-view';
  var main = document.querySelector('main');
  var src = document.getElementById('srcStream');
  var tgt = document.getElementById('tgtStream');
  var controls = document.querySelector('.controls');
  if (!main || !src || !tgt) return;

  var style = document.createElement('style');
  style.textContent = [
    '#viewSwitch { display: flex; gap: 3px; background: var(--bg);',
    '  border: 1px solid var(--line); padding: 3px; border-radius: 8px; }',
    '#viewSwitch button { padding: 6px 13px; font-size: 12.5px; border: 0;',
    '  background: transparent; color: var(--muted); border-radius: 5px;',
    '  white-space: nowrap; cursor: pointer; }',
    '#viewSwitch button.on { background: var(--accent); color: var(--accent-ink, #fff);',
    '  font-weight: 600; }',

    '#pairs { max-width: 720px; margin: 0 auto; display: none; }',
    'body[data-view="stacked"] .cols, body[data-view="focus"] .cols { display: none; }',
    'body[data-view="stacked"] #pairs, body[data-view="focus"] #pairs { display: block; }',

    '.pair { display: flex; gap: 12px; padding: 13px 0;',
    '  border-bottom: 1px solid var(--line); }',
    '.pair:last-child { border-bottom: 0; }',
    '.pair .avatar { flex: none; width: 28px; height: 28px; border-radius: 50%;',
    '  display: grid; place-items: center; font-size: 11px; font-weight: 700;',
    '  color: #fff; background: var(--accent); }',
    '.pair .col2 { flex: 1; min-width: 0; }',
    '.pair .nm { font-size: 13.5px; font-weight: 700; margin-bottom: 4px;',
    '  display: flex; align-items: baseline; gap: 8px; flex-wrap: wrap; }',
    '.pair .nm .meta { font-weight: 400; color: var(--muted); font-size: 12px; }',
    '.pair .nm .tag { font-weight: 600; font-size: 10.5px; text-transform: uppercase;',
    '  letter-spacing: .3px; color: var(--muted); background: var(--bg);',
    '  border: 1px solid var(--line); border-radius: 20px; padding: 1px 8px; }',
    '.pair .s { font-size: 16px; line-height: 1.55; }',
    '.pair .t { margin-top: 7px; padding-left: 12px; font-size: 15px;',
    '  line-height: 1.55; color: var(--tgt); border-left: 2px solid var(--tgt); }',
    '.pair .sp { margin-top: 8px; font-size: 12px; color: var(--muted);',
    '  display: flex; align-items: center; }',
    '.pair.live .s, .pair.live .t { color: var(--muted); }',
    '.pair.live .t { border-left-color: var(--line); }',
    '.pair.live .avatar { opacity: .5; }',

    'body[data-view="focus"] #pairs { max-width: 900px; }',
    'body[data-view="focus"] .pair { display: none; }',
    'body[data-view="focus"] .pair:last-child { display: block; padding: 30px 0;',
    '  text-align: center; border: 0; }',
    'body[data-view="focus"] .pair .avatar { display: none; }',
    'body[data-view="focus"] .pair .nm { font-size: 12px; letter-spacing: .14em;',
    '  text-transform: uppercase; color: var(--muted); margin-bottom: 14px; }',
    'body[data-view="focus"] .pair .s { font-size: 24px; line-height: 1.35;',
    '  color: var(--muted); }',
    'body[data-view="focus"] .pair .t { font-size: 34px; line-height: 1.3;',
    '  font-weight: 600; border: 0; padding: 0; margin-top: 24px;',
    '  border-top: 1px solid var(--line); padding-top: 24px; }',

    '.pairs-empty { color: var(--muted); text-align: center; padding: 50px 0;',
    '  font-size: 14px; }',
    '@media (max-width: 720px) { #viewSwitch button { padding: 6px 10px; } }'
  ].join('\n');
  document.head.appendChild(style);

  var pairs = document.createElement('div');
  pairs.id = 'pairs';
  main.appendChild(pairs);

  // ---- view switch, in the page's own controls bar (never the header) ----
  // Sits inline with the toggles/buttons (no heading label, like Speak
  // translation / Label speakers), so it doesn't stack the row taller.
  var wrap = document.createElement('div');
  var sw = document.createElement('div');
  sw.id = 'viewSwitch';
  sw.setAttribute('role', 'group');
  sw.setAttribute('aria-label', 'View');
  wrap.appendChild(sw);

  var VIEWS = [['columns', 'Columns'], ['stacked', 'Stacked'], ['focus', 'Focus']];
  var buttons = {};
  VIEWS.forEach(function (v) {
    var b = document.createElement('button');
    b.type = 'button';
    b.textContent = v[1];
    b.onclick = function () { setView(v[0]); };
    buttons[v[0]] = b;
    sw.appendChild(b);
  });

  if (controls) {
    var spacer = controls.querySelector('.spacer');
    if (spacer) {
      // Flank the view switch with a matching spacer on its left too, so it
      // sits centered in the free space between the toggles and the
      // Restart/Start buttons, rather than hugging the toggles.
      var leadSpacer = document.createElement('div');
      leadSpacer.className = 'spacer';
      spacer.parentNode.insertBefore(leadSpacer, spacer);
      spacer.parentNode.insertBefore(wrap, spacer);
    } else {
      controls.appendChild(wrap);
    }
  } else {
    main.insertBefore(wrap, main.firstChild);
  }

  function setView(v) {
    document.body.dataset.view = v;
    try { localStorage.setItem(KEY, v); } catch (e) {}
    Object.keys(buttons).forEach(function (k) {
      buttons[k].classList.toggle('on', k === v);
    });
    if (v !== 'columns') render();
  }

  // ---- pairing ----
  function initials(name) {
    var m = /^user[-_ ]?(\d+)$/i.exec(name || '');
    if (m) return 'S' + m[1];
    var parts = String(name || '').split(/[\s._-]+/).filter(Boolean);
    if (!parts.length) return '•';
    return (parts.length > 1 ? parts[0][0] + parts[1][0] : parts[0].slice(0, 2)).toUpperCase();
  }

  function displayName(name) {
    var m = /^user[-_ ]?(\d+)$/i.exec(name || '');
    return m ? 'Speaker ' + m[1] : (name || '');
  }

  function langName(code) {
    if (!code) return '';
    return (typeof window.zenoLangName === 'function') ? window.zenoLangName(code) : code;
  }

  function fmtTime(ts) {
    var d = new Date(ts);
    if (isNaN(d)) return '';
    var h = d.getHours() % 12; if (h === 0) h = 12;
    return h + ':' + String(d.getMinutes()).padStart(2, '0');
  }

  // Stable avatar color per speaker, assigned in order of first appearance.
  var PALETTE = ['var(--u1)', 'var(--u2)', 'var(--u3)', 'var(--u4)'];
  var speakerColors = {};
  var nextColor = 0;
  function avatarColor(speaker) {
    var key = speaker || '•';
    if (!speakerColors[key]) {
      speakerColors[key] = PALETTE[nextColor % PALETTE.length];
      nextColor++;
    }
    return speakerColors[key];
  }

  var SPK_ICON = '<svg width="11" height="11" viewBox="0 0 24 24" fill="none" ' +
    'stroke="currentColor" stroke-width="2.5" stroke-linecap="round" ' +
    'style="vertical-align:-1px;margin-right:5px;flex:none">' +
    '<path d="M4 20V10M12 20V4M20 20v-6"/></svg>';

  function readUtt(el) {
    if (!el) return null;
    var spk = el.querySelector('.spk');
    var clone = el.cloneNode(true);
    var s = clone.querySelector('.spk');
    if (s) s.remove();
    return {
      speaker: spk ? spk.textContent.trim() : '',
      text: clone.textContent.trim(),
      live: el.classList.contains('partial'),
      lang: el.dataset.lang || '',
      ts: el.dataset.ts ? parseInt(el.dataset.ts, 10) : null,
      spokenLang: el.dataset.spokenLang || ''
    };
  }

  function render() {
    if (document.body.dataset.view === 'columns') return;
    var a = src.querySelectorAll('.utt');
    var b = tgt.querySelectorAll('.utt');
    var n = Math.max(a.length, b.length);
    if (!n) {
      pairs.innerHTML = '<div class="pairs-empty">Speech and its translation appear here.</div>';
      return;
    }
    var html = '';
    for (var i = 0; i < n; i++) {
      var s = readUtt(a[i]);
      var t = readUtt(b[i]);
      var speaker = (s && s.speaker) || (t && t.speaker) || '';
      var live = (s && s.live) || (t && t.live);
      var lang = (s && s.lang) || (t && t.lang) || '';
      var ts = (s && s.ts) || (t && t.ts) || null;
      var spokenLang = (t && t.spokenLang) || '';
      var name = displayName(speaker);

      var metaBits = [];
      if (lang) metaBits.push(langName(lang));
      if (ts) metaBits.push(fmtTime(ts));
      var meta = metaBits.join(' · ');

      html += '<div class="pair' + (live ? ' live' : '') + '">' +
        '<div class="avatar" style="background:' + avatarColor(speaker) + '">' +
        esc(initials(speaker)) + '</div>' +
        '<div class="col2">' +
        '<div class="nm">' +
        (name ? esc(name) : '') +
        (meta ? '<span class="meta">' + esc(meta) + '</span>' : '') +
        (live ? '<span class="tag">interim</span>' : '') +
        '</div>' +
        '<div class="s">' + esc(s ? s.text : '') + '</div>' +
        (t && t.text ? '<div class="t">' + esc(t.text) + '</div>' : '') +
        (spokenLang ? '<div class="sp">' + SPK_ICON + 'spoken aloud in ' +
          esc(langName(spokenLang)) + '</div>' : '') +
        '</div></div>';
    }
    pairs.innerHTML = html;
    var last = pairs.lastElementChild;
    if (last && document.body.dataset.view === 'stacked') {
      main.scrollTop = main.scrollHeight;
    }
  }

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  var queued = false;
  function schedule() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(function () { queued = false; render(); });
  }

  var obs = new MutationObserver(schedule);
  [src, tgt].forEach(function (el) {
    obs.observe(el, { childList: true, subtree: true, characterData: true,
                      attributes: true, attributeFilter: ['class'] });
  });

  var saved;
  try { saved = localStorage.getItem(KEY); } catch (e) {}
  setView(saved === 'columns' || saved === 'focus' ? saved : 'stacked');
})();

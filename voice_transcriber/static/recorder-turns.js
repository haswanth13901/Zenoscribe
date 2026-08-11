/**
 * Recorder turns: avatar + speaker name per turn, instead of the plain
 * "user-1" label column.
 *
 * Drop-in for index.html. Add AFTER the page's own inline script:
 *   <script src="/static/recorder-turns.js"></script>
 *
 * It does not replace any logic. It wraps the page's existing addTurn() and
 * showPartial() and then decorates the element they just appended, so the
 * turns array, Save, Clear and the WebSocket handling are untouched. If the
 * page ever stops exposing those functions, this file quietly does nothing.
 */
(function initRecorderTurns() {
  var style = document.createElement('style');
  style.textContent = [
    '.turn { align-items: flex-start; }',
    '.turn .who { display: flex; align-items: center; gap: 9px; flex: 0 0 auto;',
    '  min-width: 132px; font-size: 12.5px; font-weight: 600; color: var(--text); }',
    '.turn .avatar { flex: none; width: 28px; height: 28px; border-radius: 50%;',
    '  display: grid; place-items: center; font-size: 11px; font-weight: 700;',
    '  color: #fff; letter-spacing: .02em; }',
    '.turn[data-s="user-1"] .avatar { background: var(--u1); }',
    '.turn[data-s="user-2"] .avatar { background: var(--u2); }',
    '.turn[data-s="user-3"] .avatar { background: var(--u3); }',
    '.turn[data-s="user-4"] .avatar { background: var(--u4); }',
    '.turn .avatar { background: var(--muted); }',
    '.turn[data-s="user-1"] .who, .turn[data-s="user-2"] .who,',
    '.turn[data-s="user-3"] .who, .turn[data-s="user-4"] .who { color: var(--text); }',
    '.turn .body { font-size: 15.5px; line-height: 1.6; }',
    '.turn.partial .avatar { opacity: .5; }',
    '.turn.partial .who { color: var(--muted); }',
    '.turn.partial .body::after { content: "interim"; margin-left: 8px;',
    '  font-size: 10.5px; padding: 1px 6px; border-radius: 10px;',
    '  background: var(--rowline); color: var(--muted); vertical-align: 2px; }',
    '@media (max-width: 640px) {',
    '  .turn { flex-direction: column; gap: 4px; }',
    '  .turn .who { min-width: 0; }',
    '}'
  ].join('\n');
  document.head.appendChild(style);

  // "user-1" -> "Speaker 1" / "S1"; anything else is used as given.
  function label(speaker) {
    var m = /^user[-_ ]?(\d+)$/i.exec(String(speaker || ''));
    if (m) return { name: 'Speaker ' + m[1], initials: 'S' + m[1] };
    var s = String(speaker || 'Speaker');
    var parts = s.split(/[\s._-]+/).filter(Boolean);
    var initials = (parts.length > 1
      ? parts[0][0] + parts[1][0]
      : s.slice(0, 2)).toUpperCase();
    return { name: s, initials: initials };
  }

  function decorate(el) {
    if (!el) return;
    var who = el.querySelector('.who');
    if (!who || who.querySelector('.avatar')) return;
    var l = label(el.dataset.s || who.textContent);
    who.textContent = '';
    var av = document.createElement('span');
    av.className = 'avatar';
    av.textContent = l.initials;
    var nm = document.createElement('span');
    nm.className = 'name';
    nm.textContent = l.name;
    who.appendChild(av);
    who.appendChild(nm);
  }

  function wrap(fnName) {
    var original = window[fnName];
    if (typeof original !== 'function') return false;
    window[fnName] = function () {
      var out = original.apply(this, arguments);
      var t = document.querySelectorAll('#transcript .turn');
      decorate(t[t.length - 1]);
      return out;
    };
    return true;
  }

  if (!wrap('addTurn') || !wrap('showPartial')) return;

  // Anything already on screen (e.g. after a hot reload).
  document.querySelectorAll('#transcript .turn').forEach(decorate);
})();

/**
 * Shared file-upload transcription feature.
 *
 * Included by both index.html (/app) and admin.html so the behaviour stays in
 * one place. Depends on three globals the host page already defines:
 *   - `token`  : the JWT from sessionStorage
 *   - `$`      : a querySelector helper, `s => document.querySelector(s)`
 *   - `api`    : the fetch wrapper (used only for /api/languages)
 *
 * The host page must provide a trigger button with id="uploadBtn". Everything
 * else (the hidden file input and the result panel) is injected by this module,
 * so pages only need the button plus <script src="/static/upload.js"></script>.
 *
 * Behaviour matches /app: the file is sent to /api/transcribe/translate, turns
 * come back and are shown inline. Nothing is saved to history — uploads are
 * ephemeral by design.
 */
(function initUploadFeature() {
  const uploadBtn = document.getElementById('uploadBtn');
  if (!uploadBtn) return; // page didn't opt in

  const uploadInput = document.createElement('input');
  uploadInput.type = 'file';
  uploadInput.accept = 'audio/*';
  uploadInput.style.display = 'none';
  uploadInput.id = 'uploadInput';
  document.body.appendChild(uploadInput);

  const panel = document.createElement('div');
  panel.id = 'uploadPanel';
  panel.style.cssText = 'max-width:780px;margin:14px auto;display:none;padding:12px;';
  panel.innerHTML = `
    <div class="rec">
      <div class="meta" id="uploadFilename"></div>
      <div style="margin-top:8px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        <div style="min-width:180px">
          <label style="display:block;font-size:11px;color:var(--muted);">Translate (target language)</label>
          <select id="uploadLang" style="min-width:160px;padding:6px;border-radius:6px;background:var(--panel);color:var(--text);border:1px solid var(--line)"></select>
        </div>
        <div>
          <button id="doTranscribe">Transcribe</button>
          <button id="doTranscribeTranslate">Transcribe &amp; Translate</button>
        </div>
      </div>
      <div id="uploadResult" class="prev" style="margin-top:10px;color:var(--text);"></div>
      <div id="uploadTranslateResult" class="prev" style="margin-top:10px;color:var(--text);"></div>
    </div>`;
  const main = document.querySelector('main');
  if (main && main.parentNode) {
    main.parentNode.insertBefore(panel, main.nextSibling);
  } else {
    document.body.appendChild(panel);
  }

  const q = s => panel.querySelector(s);
  const filenameEl = q('#uploadFilename');
  const langSel = q('#uploadLang');
  const doTranscribe = q('#doTranscribe');
  const doTranscribeTranslate = q('#doTranscribeTranslate');
  const resultEl = q('#uploadResult');
  const translateEl = q('#uploadTranslateResult');

  async function loadLanguages() {
    try {
      const r = await fetch('/api/languages', {
        headers: { 'Authorization': 'Bearer ' + token },
      });
      const data = await r.json();
      langSel.innerHTML = data.languages
        .map(l => `<option value="${l.code}">${l.name}</option>`)
        .join('');
      langSel.value = 'en';
    } catch (e) {
      langSel.innerHTML = '<option value="en">English</option>';
    }
  }

  uploadBtn.onclick = () => uploadInput.click();

  uploadInput.onchange = async () => {
    const f = uploadInput.files && uploadInput.files[0];
    if (!f) return;
    filenameEl.textContent = `Selected: ${f.name} (${Math.round(f.size / 1024)} KB)`;
    panel.style.display = 'block';
    resultEl.textContent = '';
    translateEl.textContent = '';
    await loadLanguages();
  };

  async function doUpload(targetLanguage) {
    const f = uploadInput.files && uploadInput.files[0];
    if (!f) { alert('Choose a file first'); return null; }
    const fd = new FormData();
    fd.append('file', f, f.name);
    const qs = targetLanguage
      ? ('?target_language=' + encodeURIComponent(targetLanguage))
      : '';
    try {
      const r = await fetch('/api/transcribe/translate' + qs, {
        method: 'POST',
        headers: { 'Authorization': 'Bearer ' + token },
        body: fd,
      });
      if (!r.ok) {
        const txt = await r.text();
        alert('Upload failed: ' + r.status + ' ' + txt);
        return null;
      }
      return await r.json();
    } catch (e) {
      alert('Upload error: ' + e.message);
      return null;
    }
  }

  doTranscribe.onclick = async () => {
    resultEl.textContent = 'Transcribing...';
    translateEl.textContent = '';
    const json = await doUpload(null);
    if (!json) { resultEl.textContent = ''; return; }
    const text = (json.turns || []).map(t => t.text || '').join(' ').trim();
    resultEl.textContent = text || '(no transcription)';
  };

  doTranscribeTranslate.onclick = async () => {
    const tgt = langSel.value;
    translateEl.textContent = 'Transcribing & translating...';
    const json = await doUpload(tgt);
    if (!json) { translateEl.textContent = ''; return; }
    const text = (json.turns || []).map(t => t.text || '').join(' ').trim();
    translateEl.textContent = text || '(no translation)';
  };
})();
/* A take stays in this tab until an explicit save is confirmed. No persistence. */
(() => {
  const block = document.querySelector('[data-record-retention]');
  if (!block) return;
  const form = block.closest('form');
  const status = block.querySelector('[data-retention-status]');
  const errors = block.querySelector('[data-retention-errors]');
  const recovery = block.querySelector('[data-retention-result]');
  let file, attempt, sending = false, confirmed = false, savedURL;
  const supported = !!(window.fetch && window.FormData && window.crypto?.getRandomValues);
  const message = key => { status.textContent = block.dataset[key]; };
  function localURL(value) {
    if (typeof value !== 'string') return null;
    try { const url = new URL(value, window.location.href); return url.origin === window.location.origin ? url.href : null; }
    catch (_) { return null; }
  }
  function showResult(url) {
    const safe = localURL(url);
    recovery.hidden = !safe;
    if (safe) recovery.href = safe; else recovery.removeAttribute('href');
    return safe;
  }
  function clearErrors() {
    errors.replaceChildren(); errors.hidden = true;
    form.querySelectorAll('[data-retention-invalid]').forEach(field => {
      field.removeAttribute('aria-invalid'); field.removeAttribute('data-retention-invalid');
    });
  }
  function showErrors(rows) {
    clearErrors();
    const list = document.createElement('ul');
    for (const row of Array.isArray(rows) ? rows : []) {
      for (const text of Array.isArray(row.messages) ? row.messages : []) {
        const item = document.createElement('li');
        item.textContent = (row.label ? String(row.label) + ': ' : '') + String(text);
        list.appendChild(item);
      }
      const field = form.elements.namedItem(row.field);
      if (field?.setAttribute) {
        field.setAttribute('aria-invalid', 'true'); field.setAttribute('data-retention-invalid', '');
      }
    }
    if (list.childNodes.length) { errors.appendChild(list); errors.hidden = false; errors.focus(); }
  }
  function requestID() {
    const bytes = window.crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 15) | 64; bytes[8] = (bytes[8] & 63) | 128;
    const hex = Array.from(bytes, n => n.toString(16).padStart(2, '0')).join('');
    return [hex.slice(0,8),hex.slice(8,12),hex.slice(12,16),hex.slice(16,20),hex.slice(20)].join('-');
  }
  function lock() {
    const states = Array.from(form.querySelectorAll('input,select,textarea,button'), field => [field, field.disabled]);
    states.forEach(([field]) => { field.disabled = true; });
    return () => { states.forEach(([field, disabled]) => { field.disabled = disabled; }); };
  }
  form.addEventListener('nehdrou:recording-attached', event => {
    file = event.detail.file; confirmed = false; savedURL = undefined;
    showResult(null); message(supported ? 'retained' : 'fallback');
  });
  form.addEventListener('nehdrou:recording-cleared', () => {
    file = undefined; attempt = undefined; confirmed = false; savedURL = undefined;
    clearErrors(); showResult(null); status.textContent = '';
  });
  form.addEventListener('submit', async event => {
    if (event.defaultPrevented) return; // Existing recorder blocks while capturing.
    if (sending) { event.preventDefault(); message('saving'); return; }
    if (!supported || !file || form.elements.file.files[0] !== file) return;
    event.preventDefault();
    if (savedURL) { window.location.assign(savedURL); return; }
    const body = new FormData(form); // Includes the ordinary CSRF field and file.
    attempt = attempt || requestID(); body.set('upload_attempt', attempt);
    clearErrors(); showResult(null); sending = true; message('saving');
    const unlock = lock();
    const controller = window.AbortController ? new window.AbortController() : null;
    let timeout;
    try {
      const {response, result} = await Promise.race([
        (async () => {
          const response = await window.fetch(form.action || window.location.href, {
            method:'POST', body, credentials:'same-origin', redirect:'manual', signal:controller?.signal,
            headers:{'Accept':'application/json','X-Nehedrou-Recording-Retention':'1'}
          });
          if (!(response.headers.get('Content-Type') || '').startsWith('application/json')) throw new Error('uncertain');
          return {response, result:await response.json()};
        })(),
        new Promise((_, reject) => {
          timeout = window.setTimeout(() => { controller?.abort(); reject(new Error('uncertain')); }, 60000);
        })
      ]);
      if (result.schema !== 'nehdrou-recording-upload-v1') throw new Error('uncertain');
      if (response.ok && result.status === 'saved') {
        savedURL = showResult(result.result_url);
        if (!savedURL) throw new Error('uncertain');
        confirmed = true; message('saved');
        // If navigation fails, the saved-result link and the same receipt remain.
        try { window.location.assign(savedURL); } catch (_) { /* Keep this page. */ }
      } else if ((response.status === 422 || response.status === 503) && ['invalid','retry'].includes(result.status)) {
        showErrors(result.errors); message('invalid');
      } else if (response.status === 409 && ['conflict','unavailable'].includes(result.status)) {
        showResult(result.result_url); message(result.status);
      } else { throw new Error('uncertain'); }
    } catch (_) {
      // A response may have been lost after a commit. Keep the same attempt key;
      // only an explicit retry occurs, and the server deduplicates exact content.
      message('uncertain');
    } finally { window.clearTimeout(timeout); sending = false; unlock(); }
  });
  window.addEventListener('beforeunload', event => {
    if (file && !confirmed) { event.preventDefault(); event.returnValue = ''; }
  });
})();

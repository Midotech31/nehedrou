(() => {
  const form = document.querySelector('.author-form');
  const configElement = document.getElementById('author-config');
  if (!form || !configElement) return;
  const config = JSON.parse(configElement.textContent);
  const navigation = document.querySelector('.author-steps');
  const buttons = Array.from(navigation.querySelectorAll('[data-go-step]'));
  const panels = Array.from(form.querySelectorAll('[data-author-step]'));
  const status = document.getElementById('working-status');
  const recovery = document.getElementById('working-recovery');
  const preview = document.getElementById('author-preview');
  let step = 0, revision = config.revision, dirty = false, saving = false, submitting = false;
  let timer;
  const input = name => form.elements.namedItem(name);
  const value = name => input(name)?.value || '';
  const show = (next, focus = true) => {
    step = Math.max(0, Math.min(3, next));
    panels.forEach(panel => { panel.hidden = Number(panel.dataset.authorStep) !== step; });
    buttons.forEach(button => {
      const selected = Number(button.dataset.goStep) === step;
      if (selected) button.setAttribute('aria-current', 'step'); else button.removeAttribute('aria-current');
    });
    document.getElementById('author-previous').disabled = step === 0;
    document.getElementById('author-next').hidden = step === 3;
    document.getElementById('author-step-label').textContent = config.labels.step + ' ' + (step + 1) + ' / 4';
    if (focus) {
      const heading = panels.find(panel => !panel.hidden)?.querySelector('h2');
      if (heading) { heading.tabIndex = -1; heading.focus(); }
    }
  };
  navigation.hidden = false;
  status.textContent = revision ? config.labels.saved : config.labels.unchanged;
  if (config.resume_url) { recovery.href = config.resume_url; recovery.hidden = false; }
  document.getElementById('author-step-controls').hidden = false;
  buttons.forEach(button => button.addEventListener('click', () => show(Number(button.dataset.goStep))));
  document.getElementById('author-previous').addEventListener('click', () => show(step - 1));
  document.getElementById('author-next').addEventListener('click', () => show(step + 1));
  const errorPanel = panels.find(panel => panel.querySelector('.errorlist'));
  show(errorPanel ? Number(errorPanel.dataset.authorStep) : 0, false);
  function refreshPreview() {
    ['a','b'].forEach(side => {
      document.getElementById('preview-word-' + side).textContent = value('word_' + side) || config.labels.empty_word;
      const image = document.getElementById('preview-image-' + side);
      const url = config.images[value('choose_image_' + side)];
      image.hidden = !url;
      if (url) image.src = url; else image.removeAttribute('src');
    });
    document.getElementById('preview-instruction').textContent = value('instructions_' + config.language) || config.labels.empty_instruction;
    const required = ['title','variety','word_a','word_b','contrast'];
    const count = required.filter(name => value(name).trim()).length;
    document.getElementById('author-essential-progress').textContent = count + ' / ' + required.length + ' · ' + config.labels.essentials;
  }
  preview.hidden = false;
  refreshPreview();
  function fields() {
    const values = {};
    config.fields.forEach(name => {
      const element = input(name);
      if (!element || element.disabled) return;
      values[name] = element.type === 'checkbox' ? (element.checked ? 'on' : '') : element.value;
    });
    return values;
  }
  async function saveWorking() {
    clearTimeout(timer);
    if (!dirty || saving || submitting) return;
    dirty = false; saving = true;
    status.textContent = config.labels.saving;
    try {
      const result = await fetch(config.autosave_url, {
        method:'POST', credentials:'same-origin', headers:{'Content-Type':'application/json', 'X-CSRFToken':value('csrfmiddlewaretoken')},
        body:JSON.stringify({fields:fields(), revision, activity:config.activity, base_digest:config.base_digest})
      });
      if (!result.ok) {
        dirty = true;
        const failure = await result.json().catch(() => ({}));
        status.textContent = failure.error === 'capacity' ? config.labels.capacity : result.status === 409 ? config.labels.conflict : config.labels.failed;
        return;
      }
      const response = await result.json();
      revision = response.revision;
      recovery.href = response.resume_url;
      recovery.hidden = false;
      status.textContent = dirty ? config.labels.pending : config.labels.saved;
    } catch (_) {
      dirty = true; status.textContent = config.labels.failed;
    } finally {
      saving = false;
      // Failed/conflicting copies require an explicit retry; avoid a request loop.
      if (dirty && status.textContent === config.labels.pending) timer = setTimeout(saveWorking, 2000);
    }
  }
  const changed = () => {
    refreshPreview(); dirty = true; status.textContent = config.labels.pending;
    clearTimeout(timer); timer = setTimeout(saveWorking, 2000);
  };
  form.addEventListener('input', changed);
  form.addEventListener('change', changed);
  document.getElementById('working-save').addEventListener('click', saveWorking);
  document.getElementById('author-template').addEventListener('click', () => {
    const structure = config.starters[value('kind')];
    if (!structure) return;
    // Starter text is proposed, editable and fills empty fields only.
    Object.entries(structure).forEach(([name, text]) => {
      const field = input(name);
      if (field && !field.value.trim()) field.value = text;
    });
    changed();
  });
  const sources = Array.from(form.querySelectorAll('.author-source'));
  sources.forEach((source, index) => {
    if (index && !source.querySelector('.errorlist') && !Array.from(source.querySelectorAll('input')).some(field => field.value.trim())) source.hidden = true;
  });
  const addSource = document.getElementById('author-add-source');
  if (addSource) addSource.addEventListener('click', () => {
    const source = sources.find(row => row.hidden);
    if (source) { source.hidden = false; source.open = true; source.querySelector('input')?.focus(); }
    addSource.disabled = !sources.some(row => row.hidden);
  });
  form.addEventListener('submit', () => {
    submitting = true; clearTimeout(timer);
    // Browser validation must not be blocked by a required field on a hidden step.
    panels.forEach(panel => { panel.hidden = false; });
  });
  window.addEventListener('beforeunload', event => {
    if ((dirty || saving) && !submitting) { event.preventDefault(); event.returnValue = ''; }
  });
})();

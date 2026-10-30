(() => {
  const form = document.querySelector('[data-guided-activity]');
  if (!form) return;
  const sections = [...form.querySelectorAll('[data-activity-step]')];
  const controls = form.querySelector('.guided-controls');
  const back = form.querySelector('[data-step-back]');
  const next = form.querySelector('[data-step-next]');
  const counter = document.querySelector('[data-step-counter]');
  const label = document.querySelector('[data-step-label]');
  const reportSection = sections[sections.length - 1];
  const reportHeading = form.querySelector('[data-report-heading]');
  const communication = form.querySelector('[data-communication-prompt]');
  const pause = form.querySelector('[data-step-pause]');
  const pausePanel = form.querySelector('[data-pause-panel]');
  const resume = form.querySelector('[data-step-resume]');
  const stop = form.querySelector('[data-stop-activity]');
  const choiceError = form.querySelector('[data-answer-error]');
  const choiceGroup = form.querySelector('#id_answer');
  const originalReportTitle = reportSection.dataset.title;
  let current = 0;
  let paused = false;
  const radios = [...form.querySelectorAll('input[name=answer]')];
  function stopAudio() {
    document.dispatchEvent(new Event('nehedrou:stop-audio'));
    sections.forEach(section => section.querySelectorAll('audio').forEach(audio => audio.pause()));
    if (window.speechSynthesis) window.speechSynthesis.cancel();
  }
  function reportMode() {
    if (!communication) return;
    const stopped = form.elements.completion.value === 'stopped';
    communication.hidden = stopped;
    reportSection.dataset.title = stopped ? form.dataset.reportLabel : originalReportTitle;
    reportHeading.textContent = reportSection.dataset.title;
    if (current === sections.length - 1) label.textContent = reportSection.dataset.title;
  }
  function choiceRequired() {
    return form.dataset.responseMode !== 'observation' && form.elements.completion.value !== 'stopped';
  }
  function hasChoice() { return !choiceRequired() || radios.some(radio => radio.checked); }
  function clearChoiceError() {
    if (choiceError) choiceError.hidden = true;
    if (choiceGroup) choiceGroup.removeAttribute('aria-invalid');
    radios.forEach(radio => radio.setCustomValidity(''));
  }
  function showChoiceError() {
    if (choiceError) choiceError.hidden = false;
    if (choiceGroup) choiceGroup.setAttribute('aria-invalid', 'true');
    const first = radios[0];
    if (first) {
      if (choiceError) {
        first.setAttribute('aria-describedby', choiceError.id);
        first.setCustomValidity(choiceError.textContent.trim());
      }
      first.focus();
    } else if (choiceGroup) choiceGroup.focus();
  }
  function show(index, focus = true) {
    stopAudio();
    paused = false;
    current = index;
    if (pausePanel) pausePanel.hidden = true;
    if (pause) pause.hidden = false;
    sections.forEach((section, i) => { section.hidden = i !== current; });
    back.hidden = current === 0;
    next.hidden = current === sections.length - 1;
    counter.textContent = String(current + 1) + ' / ' + String(sections.length);
    label.textContent = sections[current].dataset.title;
    if (focus) sections[current].querySelector('h2').focus();
  }
  controls.hidden = false;
  if (stop) {
    stop.hidden = false;
    stop.addEventListener('click', () => {
      form.elements.completion.value = 'stopped';
      radios.forEach(input => { input.checked = false; });
      clearChoiceError();
      reportMode();
      show(sections.length - 1);
      form.elements.parent_report.focus();
    });
  }
  if (pause && pausePanel && resume) {
    pause.addEventListener('click', () => {
      stopAudio();
      paused = true;
      sections.forEach(section => { section.hidden = true; });
      pausePanel.hidden = false;
      pause.hidden = true;
      back.hidden = true;
      next.hidden = true;
      label.textContent = pausePanel.dataset.title;
      resume.focus();
    });
    resume.addEventListener('click', () => show(current));
  }
  label.setAttribute('aria-live', 'polite');
  form.addEventListener('nehedrou:reveal', event => {
    const index = sections.indexOf(event.target.closest('[data-activity-step]'));
    if (index >= 0) show(index, false);
  });
  back.addEventListener('click', () => show(Math.max(0, current - 1)));
  next.addEventListener('click', () => {
    if (paused) return;
    if (current === 1 && !hasChoice()) { showChoiceError(); return; }
    clearChoiceError();
    show(Math.min(sections.length - 1, current + 1));
  });
  form.addEventListener('submit', event => {
    stopAudio();
    if (!hasChoice()) {
      event.preventDefault();
      show(1, false);
      showChoiceError();
    } else if (!form.checkValidity()) {
      event.preventDefault();
      show(sections.length - 1);
      form.reportValidity();
    }
  });
  radios.forEach(radio => radio.addEventListener('change', clearChoiceError));
  form.elements.completion.addEventListener('change', () => {
    reportMode();
    clearChoiceError();
  });
  reportMode();
  const answerError = form.querySelector('[data-error-field=answer]');
  show(answerError ? 1 : form.querySelector('[role=alert]:not([hidden])') ? 2 : 0, false);
  if (answerError) showChoiceError();
})();

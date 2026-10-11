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
  const originalReportTitle = reportSection.dataset.title;
  function reportMode() {
    if (!communication) return;
    const stopped = form.elements.completion.value === 'stopped';
    communication.hidden = stopped;
    reportSection.dataset.title = stopped ? form.dataset.reportLabel : originalReportTitle;
    reportHeading.textContent = reportSection.dataset.title;
    if (current === sections.length - 1) label.textContent = reportSection.dataset.title;
  }
  let current = 0;
  controls.hidden = false;
  const stop = form.querySelector('[data-stop-activity]');
  if (stop) {
    stop.hidden = false;
    stop.addEventListener('click', () => {
      form.elements.completion.value = 'stopped';
      form.querySelectorAll('input[name=answer]').forEach(input => { input.checked = false; input.setCustomValidity(''); });
      reportMode();
      show(sections.length - 1);
      form.elements.parent_report.focus();
    });
  }
  label.setAttribute('aria-live', 'polite');
  function show(index, focus = true) {
    current = index;
    if (form.querySelector('[data-device-voice]') && window.speechSynthesis) window.speechSynthesis.cancel();
    sections.forEach((section,i) => {
      section.hidden = i !== current;
      if (section.hidden) section.querySelectorAll('audio').forEach(audio => audio.pause());
    });
    back.hidden = current === 0;
    next.hidden = current === sections.length - 1;
    counter.textContent = `${current + 1} / ${sections.length}`;
    label.textContent = sections[current].dataset.title;
    if (focus) sections[current].querySelector('h2').focus({preventScroll: false});
  }
  form.addEventListener('nehedrou:reveal', event => {
    const index = sections.indexOf(event.target.closest('[data-activity-step]'));
    if (index >= 0) show(index, false);
  });
  back.addEventListener('click', () => show(Math.max(0, current - 1)));
  next.addEventListener('click', () => show(Math.min(sections.length - 1, current + 1)));
  form.addEventListener('submit', event => {
    if (form.dataset.responseMode !== 'observation' && form.elements.completion.value === 'completed' && !form.querySelector('input[name=answer]:checked')) {
      event.preventDefault();
      show(1);
      const radio = form.querySelector('input[name=answer]');
      radio.focus();
      radio.setCustomValidity(form.querySelector('legend').textContent);
      radio.reportValidity();
    } else if (!form.checkValidity()) {
      event.preventDefault();
      show(sections.length - 1);
      form.reportValidity();
    }
  });
  form.querySelectorAll('input[name=answer]').forEach(radio => radio.addEventListener('change', () => {
    form.querySelectorAll('input[name=answer]').forEach(input => input.setCustomValidity(''));
  }));
  form.elements.completion.addEventListener('change', () => {
    reportMode();
    form.querySelectorAll('input[name=answer]').forEach(input => input.setCustomValidity(''));
  });
  reportMode();
  const answerError = form.querySelector('[data-error-field=answer]');
  show(answerError ? 1 : form.querySelector('[role=alert]') ? 2 : 0, false);
})();

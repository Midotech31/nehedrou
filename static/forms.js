(() => {
  document.querySelectorAll('[data-error-summary]').forEach(summary => {
    summary.addEventListener('click', event => {
      const link = event.target.closest('a[href^="#"]');
      if (!link) return;
      const target = document.getElementById(link.hash.slice(1));
      if (!target) return;
      event.preventDefault();
      target.dispatchEvent(new CustomEvent('nehedrou:reveal', {bubbles:true}));
      target.focus();
      target.scrollIntoView({block:'center'});
    });
  });
  document.querySelector('[data-error-summary]')?.focus({preventScroll:false});
  const labels = document.body.dataset;
  document.querySelectorAll('input[type="password"]').forEach((input, index) => {
    if (!input.id) input.id = `password-field-${index + 1}`;
    const fieldLabel = Array.from(input.labels || []).map(label => label.textContent.trim()).join(' ');
    const wrapper = document.createElement('span');
    wrapper.className = 'password-control';
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'password-toggle';
    button.setAttribute('aria-controls', input.id);
    const setVisible = shown => {
      input.type = shown ? 'text' : 'password';
      button.textContent = shown ? labels.passwordHide || 'Hide' : labels.passwordShow || 'Show';
      const action = shown ? labels.passwordHideLabel || 'Hide password' : labels.passwordShowLabel || 'Show password';
      button.setAttribute('aria-label', fieldLabel ? `${action}: ${fieldLabel}` : action);
    };
    input.before(wrapper);
    wrapper.append(input, button);
    setVisible(false);
    button.addEventListener('click', () => setVisible(input.type === 'password'));
    input.form?.addEventListener('submit', () => setVisible(false));
    window.addEventListener('pagehide', () => setVisible(false));
  });
})();

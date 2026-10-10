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
})();

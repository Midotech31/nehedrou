(() => {
  const form = document.querySelector('[data-program-builder]');
  if (!form) return;
  const variety = form.querySelector('[name=variety]');
  const search = form.querySelector('[data-activity-search]');
  const choices = [...form.querySelectorAll('.builder-option')];
  const count = form.querySelector('[data-selection-count]');
  const orderField = form.elements.activity_order;
  const orderList = form.querySelector('[data-selected-order]');
  let order = orderField.value.split(',').filter(Boolean);
  form.querySelector('.builder-search').hidden = false;
  form.querySelector('.selection-order').hidden = false;
  function update() {
    const query = search.value.trim().toLocaleLowerCase();
    choices.forEach(choice => {
      choice.hidden = Boolean((variety.value && choice.dataset.variety !== variety.value) || !choice.dataset.title.toLocaleLowerCase().includes(query));
    });
    const selected = choices.filter(choice => choice.querySelector('input').checked);
    const ids = selected.map(choice => choice.querySelector('input').value);
    order = order.filter(id => ids.includes(id));
    ids.forEach(id => { if (!order.includes(id)) order.push(id); });
    orderField.value = order.join(',');
    count.textContent = selected.length;
    form.querySelector('.builder-no-results').hidden = choices.some(choice => !choice.hidden);
    orderList.replaceChildren();
    order.forEach((id,index) => {
      const choice = selected.find(choice => choice.querySelector('input').value === id);
      const li = document.createElement('li');
      const label = document.createElement('span');
      label.dir = 'auto'; label.textContent = choice.dataset.title;
      li.append(label);
      [-1,1].forEach(direction => {
        const button = document.createElement('button');
        button.type = 'button'; button.className = 'button secondary small';
        button.textContent = direction < 0 ? form.dataset.upLabel : form.dataset.downLabel;
        button.setAttribute('aria-label', button.textContent + ': ' + choice.dataset.title);
        button.disabled = index + direction < 0 || index + direction >= order.length;
        button.addEventListener('click', () => {
          [order[index],order[index + direction]] = [order[index + direction],order[index]];
          dirty(); update();
          orderList.children[index + direction].querySelector('button').focus();
        });
        li.append(button);
      });
      orderList.append(li);
    });
  }
  function dirty() {
    const confirm = form.querySelector('[data-confirm-assignment]');
    if (confirm) confirm.disabled = true;
  }
  variety.addEventListener('change', () => {
    choices.forEach(choice => {
      if (variety.value && choice.dataset.variety !== variety.value) choice.querySelector('input').checked = false;
    });
    dirty(); update();
  });
  search.addEventListener('input', update);
  choices.forEach(choice => choice.querySelector('input').addEventListener('change', () => { dirty(); update(); }));
  ['title','goal','guidance','schedule'].forEach(name => form.elements[name].addEventListener('input', dirty));
  update();
})();

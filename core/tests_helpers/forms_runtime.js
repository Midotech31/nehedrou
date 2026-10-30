/* Run the shipped forms.js against browser-API fixtures, without copying its listeners. */
const fs = require('fs'), vm = require('vm'), assert = require('assert');
class DOMEvent {
  constructor(type, options = {}) { this.type = type; this.bubbles = options.bubbles ?? true; this.defaultPrevented = false; this.preventions = 0; Object.assign(this, options); }
  preventDefault() { this.preventions++; this.defaultPrevented = true; }
}
class Element {
  constructor(tag, attrs = {}, children = []) {
    this.tagName = tag.toUpperCase(); this.attrs = {...attrs}; this.parentElement = null; this.children = []; this.handlers = {};
    this.value = attrs.value || ''; this.labels = []; this.append(...children);
    this.dataset = Object.fromEntries(Object.entries(attrs).filter(([key]) => key.startsWith('data-')).map(([key, value]) => [key.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase()), value]));
  }
  get id() { return this.attrs.id || ''; } set id(value) { this.attrs.id = value; }
  get type() { return this.attrs.type || (this.tagName === 'BUTTON' ? 'submit' : 'text'); } set type(value) { this.attrs.type = value; }
  get name() { return this.attrs.name || ''; } set name(value) { this.attrs.name = value; }
  get className() { return this.attrs.class || ''; } set className(value) { this.attrs.class = value; }
  get textContent() { return this.children.map(child => typeof child === 'string' ? child : child.textContent).join(''); }
  set textContent(value) { this.children = [String(value)]; }
  get form() { return this.closest('form'); }
  get disabled() { return Object.hasOwn(this.attrs, 'disabled'); }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  getAttribute(name) { return this.attrs[name] ?? null; }
  removeAttribute(name) { delete this.attrs[name]; }
  append(...children) { for (const child of children) { if (typeof child !== 'string') { child.remove(); child.parentElement = this; } this.children.push(child); } }
  remove() { if (this.parentElement) { this.parentElement.children = this.parentElement.children.filter(child => child !== this); this.parentElement = null; } }
  before(sibling) { sibling.remove(); const parent = this.parentElement; const index = parent.children.indexOf(this); sibling.parentElement = parent; parent.children.splice(index, 0, sibling); }
  all() { return this.children.flatMap(child => typeof child === 'string' ? [] : [child, ...child.all()]); }
  matches(selector) {
    const attributes = [...selector.matchAll(/\[([^=\]]+)(?:=["']?([^"'\]]+)["']?)?\]/g)];
    const bare = selector.replace(/\[[^\]]+\]/g, '');
    const tag = bare.match(/^[a-z][a-z0-9-]*/i)?.[0];
    if (tag && this.tagName.toLowerCase() !== tag.toLowerCase()) return false;
    if ([...bare.matchAll(/\.([\w-]+)/g)].some(match => !this.className.split(/\s+/).includes(match[1]))) return false;
    if (bare.includes('#') && this.id !== bare.split('#')[1]) return false;
    return attributes.every(([, name, value]) => Object.hasOwn(this.attrs, name) && (value === undefined || this.attrs[name] === value));
  }
  matchesChain(selector) {
    const parts = selector.trim().split(/\s+/); if (!this.matches(parts.pop())) return false;
    let ancestor = this.parentElement;
    while (parts.length) { const part = parts.pop(); while (ancestor && !ancestor.matches(part)) ancestor = ancestor.parentElement; if (!ancestor) return false; ancestor = ancestor.parentElement; }
    return true;
  }
  querySelectorAll(selector) { return this.all().filter(element => selector.split(',').some(part => element.matchesChain(part.trim()))); }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  closest(selector) { return this.matchesChain(selector) ? this : this.parentElement?.closest(selector) || null; }
  contains(element) { return element === this || this.all().includes(element); }
  addEventListener(type, listener) { (this.handlers[type] ||= []).push(listener); }
  dispatchEvent(event) { event.target ||= this; event.currentTarget = this; for (const listener of this.handlers[event.type] || []) listener(event); if (event.bubbles && this.parentElement) this.parentElement.dispatchEvent(event); return !event.defaultPrevented; }
}
class Form extends Element {
  constructor(attrs, children, supported) {
    super('form', attrs, children); this.requests = []; this.submissions = []; this.valid = true;
    if (supported) this.requestSubmit = submitter => { assert(submitter && submitter.form === this && submitter.type === 'submit', 'Keep the actual successful submit button'); this.requests.push(submitter); if (this.valid) this.nativeSubmit(submitter); };
  }
  submit() { throw new Error('Do not bypass submitter semantics with form.submit()'); }
  nativeSubmit(submitter) {
    if (!this.valid) return;
    const event = new DOMEvent('submit', {submitter}); this.dispatchEvent(event); if (event.defaultPrevented) return;
    const entries = this.all().filter(element => element.name && !element.disabled && (element.tagName === 'INPUT' || element === submitter)).map(element => [element.name, element.value]);
    this.submissions.push({submitter, entries});
  }
}
function fixture(supported = true, customLabels = true) {
  const buttons = ['fr', 'en', 'ar'].map(code => new Element('button', {type:'submit', name:'language', value:code}, [code]));
  const selector = new Form({class:'language', method:'post', action:'/i18n/setlang/'}, [new Element('input', {type:'hidden', name:'csrfmiddlewaretoken', value:'fictional-csrf'}), new Element('input', {type:'hidden', name:'next', value:'/fr/library/?q=chat'}), ...buttons], supported);
  const password = new Element('input', {type:'password', name:'password', value:'FictionalSecret!2026', autocomplete:'current-password'});
  const confirmation = new Element('input', {type:'password', id:'existing-confirmation', name:'confirmation', value:'FictionalConfirmation!2026'});
  password.labels = [new Element('label', {}, ['Account password'])]; confirmation.labels = [new Element('label', {}, ['Confirmation'])];
  const loginButton = new Element('button', {type:'submit', name:'login', value:'yes'}, ['Sign in']);
  const login = new Form({method:'post', action:'/fr/login/'}, [password, confirmation, loginButton], supported);
  const attrs = customLabels ? {'data-password-show':'Afficher', 'data-password-hide':'Masquer', 'data-password-show-label':'Afficher le mot de passe', 'data-password-hide-label':'Masquer le mot de passe'} : {};
  const body = new Element('body', attrs, [selector, login]);
  const document = new Element('document', {}, [body]); document.body = body;
  document.createElement = tag => new Element(tag); document.getElementById = id => document.all().find(element => element.id === id) || null;
  const window = new Element('window');
  vm.runInNewContext(fs.readFileSync('static/forms.js', 'utf8'), {document, window, CustomEvent:DOMEvent});
  return {buttons, selector, login, password, confirmation, loginButton, document, window};
}
function click(button) {
  const event = new DOMEvent('click'); button.dispatchEvent(event);
  if (!event.defaultPrevented && !button.disabled && button.type === 'submit') button.form?.nativeSubmit(button);
  return event;
}
function checkSubmission(form, button, code) {
  assert.strictEqual(form.submissions.length, 1, 'Exactly one successful submission');
  const submission = form.submissions[0]; assert.strictEqual(submission.submitter, button);
  assert.deepStrictEqual(submission.entries.filter(([key]) => key === 'language'), [['language', code]], 'Only the chosen language is successful');
  assert(submission.entries.some(([key, value]) => key === 'csrfmiddlewaretoken' && value === 'fictional-csrf'));
  assert(submission.entries.some(([key, value]) => key === 'next' && value === '/fr/library/?q=chat'));
}
const scenario = process.argv[2];
if (scenario === 'native-language') {
  for (const supported of [true, false]) {
    for (const code of ['fr', 'en', 'ar']) {
      const f = fixture(supported); const button = f.buttons.find(item => item.value === code); const event = click(button);
      assert.strictEqual(event.preventions, 0, 'forms.js must preserve native language form activation');
      assert.strictEqual(f.selector.requests.length, 0, 'Do not replace an ordinary language submit with script');
      checkSubmission(f.selector, button, code);
      assert.strictEqual(f.login.requests.length, 0); assert.strictEqual(f.login.submissions.length, 0);
    }
  }
} else if (scenario === 'password-controls') {
  for (const customLabels of [true, false]) {
    const f = fixture(true, customLabels); const fields = [f.password, f.confirmation];
    const original = fields.map(input => input.value); const toggles = f.login.querySelectorAll('button.password-toggle');
    assert.strictEqual(toggles.length, 2); assert.notStrictEqual(fields[0].id, fields[1].id); assert.strictEqual(fields[1].id, 'existing-confirmation');
    fields.forEach((input, index) => {
      const button = toggles[index]; assert.strictEqual(input.parentElement.className, 'password-control'); assert.strictEqual(button.parentElement, input.parentElement);
      assert.strictEqual(button.type, 'button'); assert.strictEqual(button.getAttribute('aria-controls'), input.id); assert.strictEqual(input.type, 'password');
      assert.strictEqual(button.textContent, customLabels ? 'Afficher' : 'Show');
      assert.strictEqual(button.getAttribute('aria-label'), (customLabels ? 'Afficher le mot de passe' : 'Show password') + ': ' + input.labels[0].textContent);
      click(button); assert.strictEqual(input.type, 'text'); assert.strictEqual(button.textContent, customLabels ? 'Masquer' : 'Hide');
      assert.strictEqual(button.getAttribute('aria-label'), (customLabels ? 'Masquer le mot de passe' : 'Hide password') + ': ' + input.labels[0].textContent);
      assert.strictEqual(f.login.submissions.length, 0, 'Visibility toggles never submit the login form'); click(button); assert.strictEqual(input.type, 'password');
    });
    click(toggles[0]); assert.strictEqual(f.confirmation.type, 'password'); click(toggles[1]);
    const event = click(f.loginButton); assert.strictEqual(event.preventions, 0); assert.strictEqual(f.login.requests.length, 0); assert.strictEqual(f.login.submissions.length, 1);
    assert(fields.every(input => input.type === 'password')); assert.deepStrictEqual(fields.map(input => input.value), original);
    assert(!f.login.submissions[0].entries.some(([key]) => key === 'language'));
    click(toggles[0]); click(toggles[1]); f.window.dispatchEvent(new DOMEvent('pagehide', {bubbles:false}));
    assert(fields.every(input => input.type === 'password')); assert.deepStrictEqual(fields.map(input => input.value), original);
    assert.strictEqual(f.login.submissions.length, 1); assert.strictEqual(f.selector.submissions.length, 0);
  }
} else { throw new Error('Unknown forms.js runtime scenario'); }
process.stdout.write('forms-runtime:' + scenario + ':ok\n');

/* Optional device synthesis for explicitly marked fictional MSA lexical cards. */
(() => {
  const blocks = [...document.querySelectorAll('[data-device-voice]')];
  if (!blocks.length) return;
  const engine = window.speechSynthesis;
  let voice;
  function status(block, name) {
    block.querySelector('[data-speech-status]').textContent = block.dataset[name];
  }
  function refresh() {
    const voices = engine ? engine.getVoices().filter(item => /^ar(?:-|$)/i.test(item.lang)) : [];
    voice = voices.find(item => /^ar-SA$/i.test(item.lang)) || voices.find(item => /^ar-EG$/i.test(item.lang)) || voices[0];
    blocks.forEach(block => {
      block.querySelector('button').disabled = !voice;
      status(block, voice ? 'ready' : 'missing');
    });
  }
  blocks.forEach(block => block.querySelector('button').addEventListener('click', () => {
    if (!voice || !engine) { refresh(); return; }
    engine.cancel();
    const utterance = new SpeechSynthesisUtterance(block.querySelector('button').dataset.speechText);
    utterance.voice = voice;
    utterance.lang = voice.lang;
    utterance.rate = 0.85;
    utterance.onstart = () => status(block, 'playing');
    utterance.onend = () => status(block, 'ready');
    utterance.onerror = () => status(block, 'failed');
    engine.speak(utterance);
  }));
  if (engine) {
    engine.addEventListener('voiceschanged', refresh);
    document.addEventListener('visibilitychange', () => { if (document.hidden) engine.cancel(); });
    window.addEventListener('pagehide', () => engine.cancel());
  }
  refresh();
})();

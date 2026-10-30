/* Optional lexical demonstration only; never substitutes MSA for Darja. */
(() => {
  const blocks = [...document.querySelectorAll('[data-device-voice]')];
  if (!blocks.length) return;
  const engine = window.speechSynthesis;
  const voices = new Map();
  const varieties = new Set(['fr-fr-pilot', 'en-us-general-pilot', 'ar-msa-pilot']);
  const forbiddenKinds = new Set(['word_pair', 'phonological_contrast']);
  const normalize = language => String(language || '').replace(/_/g, '-').toLowerCase();
  const eligible = block => block.dataset.demo === 'true' && varieties.has(block.dataset.variety) && !forbiddenKinds.has(block.dataset.kind);
  function status(block,key) { block.querySelector('[data-speech-status]').textContent = block.dataset[key]; }
  function refresh() {
    const installed = engine ? engine.getVoices() : [];
    blocks.forEach(block => {
      const language = normalize(block.dataset.language);
      const candidates = eligible(block) && language ? installed.filter(voice => normalize(voice.lang).split('-')[0] === language.split('-')[0]) : [];
      const voice = candidates.find(voice => normalize(voice.lang) === language) || candidates[0];
      voices.set(block,voice);
      block.querySelector('button').disabled = !voice;
      block.querySelector('[data-speech-voice]').hidden = !voice;
      block.querySelector('[data-speech-language]').textContent = voice ? voice.lang : '';
      block.querySelector('[data-speech-accent]').hidden = !voice || normalize(voice.lang) === language || normalize(voice.lang).split('-').length === 1;
      status(block, voice ? 'ready' : 'missing');
    });
  }
  const reset = () => blocks.forEach(block => status(block, voices.get(block) ? 'ready' : 'missing'));
  blocks.forEach(block => block.querySelector('button').addEventListener('click',() => {
    const voice = voices.get(block);
    if (!voice || !engine || !eligible(block)) { refresh(); return; }
    document.dispatchEvent(new Event('nehedrou:stop-audio')); engine.cancel(); reset();
    const utterance = new SpeechSynthesisUtterance(block.querySelector('button').dataset.speechText);
    utterance.voice = voice; utterance.lang = voice.lang; utterance.rate = 1;
    utterance.onstart = () => status(block,'playing');
    utterance.onend = () => status(block,'ready');
    utterance.onerror = event => { if (!['canceled','interrupted'].includes(event.error)) status(block,'failed'); };
    engine.speak(utterance);
  }));
  if (engine) {
    engine.addEventListener('voiceschanged',refresh);
    document.addEventListener('nehedrou:stop-audio', reset);
    document.addEventListener('visibilitychange',() => { if (document.hidden) { engine.cancel(); reset(); } });
    window.addEventListener('pagehide',() => engine.cancel());
    document.querySelectorAll('audio').forEach(audio => audio.addEventListener('play',reset));
  }
  refresh();
})();

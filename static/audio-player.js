/* Native controls remain usable without JS. No autoplay or remote player. */
(() => {
  const blocks = [...document.querySelectorAll('[data-audio-player]')];
  const players = [...document.querySelectorAll('audio')];
  function stopAll(except) {
    players.forEach(audio => { if (audio !== except) audio.pause(); });
  }
  document.addEventListener('nehedrou:stop-audio', () => {
    stopAll(); if (window.speechSynthesis) window.speechSynthesis.cancel();
  });
  document.addEventListener('visibilitychange', () => { if (document.hidden) stopAll(); });
  window.addEventListener('pagehide', () => stopAll());
  players.forEach(audio => audio.addEventListener('play', () => {
    stopAll(audio); if (window.speechSynthesis) window.speechSynthesis.cancel();
  }));
  blocks.forEach(block => {
    const audio = block.querySelector('audio');
    const status = block.querySelector('[data-audio-status]');
    const replay = block.querySelector('[data-audio-replay]');
    const speed = block.querySelector('[data-audio-speed]');
    replay.hidden = false; block.querySelector('[data-audio-speed-label]').hidden = false;
    const update = key => { status.textContent = block.dataset[key]; };
    replay.addEventListener('click', () => {
      audio.currentTime = 0;
      const pending = audio.play();
      if (pending?.catch) pending.catch(() => update('failed'));
    });
    speed.addEventListener('change', () => { audio.playbackRate = Number(speed.value); });
    audio.addEventListener('playing', () => update('playing'));
    audio.addEventListener('pause', () => { if (!audio.error) update('paused'); });
    audio.addEventListener('ended', () => update('ready'));
    audio.addEventListener('error', () => update('failed'));
    update('ready');
  });
})();

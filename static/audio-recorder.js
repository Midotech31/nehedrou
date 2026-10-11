/* Adult editorial capture: explicit permission, local preview, explicit upload. */
(() => {
  const block = document.querySelector('[data-audio-recorder]');
  if (!block) return;
  const form = block.closest('form');
  const start = block.querySelector('[data-record-start]');
  const stop = block.querySelector('[data-record-stop]');
  const cancel = block.querySelector('[data-record-cancel]');
  const use = block.querySelector('[data-record-use]');
  const preview = block.querySelector('[data-record-preview]');
  const download = block.querySelector('[data-record-download]');
  const progress = block.querySelector('[data-record-progress]');
  const status = block.querySelector('[data-record-status]');
  const consent = block.querySelector('[data-record-consent]');
  let stream, recorder, context, timer, blob, objectURL, attachedFile;
  let generation = 0;
  let busy = false;
  const message = key => { status.textContent = block.dataset[key]; };
  function freeMicrophone() {
    stream?.getTracks().forEach(track => track.stop()); stream = undefined;
    clearInterval(timer); timer = undefined;
  }
  function clearPreview() {
    if (attachedFile && form.elements.file.files[0] === attachedFile) form.elements.file.value = '';
    attachedFile = undefined;
    preview.pause(); preview.removeAttribute('src'); preview.load();
    if (objectURL) URL.revokeObjectURL(objectURL);
    objectURL = undefined; blob = undefined;
    preview.hidden = use.hidden = download.hidden = true;
    download.removeAttribute('href');
  }
  function idle() {
    busy = false; start.disabled = false; stop.disabled = cancel.disabled = true;
    progress.hidden = true; progress.value = 0;
  }
  function abort() {
    generation += 1;
    if (recorder?.state === 'recording') recorder.stop();
    freeMicrophone(); clearPreview(); context?.close().catch(() => {});
    context = undefined; idle(); message('cancelled');
  }
  function wavFromBuffer(buffer) {
    const frames = buffer.length, channels = buffer.numberOfChannels;
    if (buffer.duration < .05 || buffer.duration > 60 || buffer.sampleRate < 8000 || buffer.sampleRate > 96000) throw new Error('duration');
    const bytes = new ArrayBuffer(44 + frames * 2), view = new DataView(bytes);
    const put = (offset, text) => { for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i)); };
    put(0,'RIFF'); view.setUint32(4,36 + frames * 2,true); put(8,'WAVE'); put(12,'fmt ');
    view.setUint32(16,16,true); view.setUint16(20,1,true); view.setUint16(22,1,true);
    view.setUint32(24,buffer.sampleRate,true); view.setUint32(28,buffer.sampleRate * 2,true);
    view.setUint16(32,2,true); view.setUint16(34,16,true); put(36,'data'); view.setUint32(40,frames * 2,true);
    const data = Array.from({length:channels},(_,i) => buffer.getChannelData(i));
    for (let i = 0; i < frames; i++) {
      const value = Math.max(-1, Math.min(1, data.reduce((sum,channel) => sum + channel[i],0) / channels));
      view.setInt16(44 + i * 2, Math.round(value * (value < 0 ? 32768 : 32767)),true);
    }
    return new Blob([bytes],{type:'audio/wav'});
  }
  const AudioEngine = window.AudioContext || window.webkitAudioContext;
  if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || !window.MediaRecorder || !AudioEngine) {
    start.disabled = true; message('unsupported'); return;
  }
  message('ready');
  start.addEventListener('click', async () => {
    if (!consent.checked) { message('consent'); consent.focus(); return; }
    const token = ++generation;
    clearPreview(); busy = true; start.disabled = true; cancel.disabled = false; message('permission');
    try {
      // Construct/resume in the user gesture, including iOS audio restrictions.
      const engine = new AudioEngine(); context = engine; await engine.resume();
      if (token !== generation) { await engine.close().catch(() => {}); return; }
      const input = await navigator.mediaDevices.getUserMedia({audio:{channelCount:1,echoCancellation:false,noiseSuppression:false,autoGainControl:false},video:false});
      if (token !== generation) { input.getTracks().forEach(track => track.stop()); await engine.close().catch(() => {}); return; }
      stream = input;
      const mime = ['audio/webm;codecs=opus','audio/mp4','audio/ogg;codecs=opus'].find(type => MediaRecorder.isTypeSupported(type));
      recorder = mime ? new MediaRecorder(stream,{mimeType:mime}) : new MediaRecorder(stream);
      const parts = [];
      recorder.addEventListener('dataavailable',event => { if (event.data.size) parts.push(event.data); });
      recorder.addEventListener('error',() => { if (token === generation) { abort(); message('failed'); } });
      recorder.addEventListener('stop', async () => {
        if (token !== generation) return;
        freeMicrophone(); stop.disabled = true; message('processing');
        try {
          const encoded = new Blob(parts,{type:recorder.mimeType});
          if (!encoded.size || encoded.size > 15 * 1024 * 1024) throw new Error('empty');
          const buffer = await engine.decodeAudioData(await encoded.arrayBuffer());
          if (token !== generation) return;
          blob = wavFromBuffer(buffer);
          objectURL = URL.createObjectURL(blob); preview.src = objectURL; download.href = objectURL;
          preview.hidden = use.hidden = download.hidden = false;
          idle(); cancel.disabled = false; message('preview');
        } catch (_) { if (token === generation) { idle(); message('failed'); } }
        finally { await engine.close().catch(() => {}); if (context === engine) context = undefined; }
      });
      recorder.start(250); stop.disabled = false; progress.hidden = false; message('recording');
      form.elements.kind.value = 'audio'; if (form.elements.audio_source) form.elements.audio_source.value = 'human';
      const since = Date.now();
      timer = setInterval(() => {
        const seconds = (Date.now() - since) / 1000; progress.value = seconds;
        if (seconds >= 45 && recorder.state === 'recording') recorder.stop();
      },200);
    } catch (_) {
      if (token === generation) { freeMicrophone(); context?.close().catch(() => {}); context = undefined; idle(); message('failed'); }
    }
  });
  stop.addEventListener('click',() => { if (recorder?.state === 'recording') recorder.stop(); });
  cancel.addEventListener('click',abort);
  consent.addEventListener('change',() => { if (!consent.checked && (busy || blob)) abort(); });
  use.addEventListener('click',() => {
    if (!blob) return;
    try {
      const transfer = new DataTransfer(); transfer.items.add(new File([blob],'adult-model.wav',{type:'audio/wav'}));
      form.elements.file.files = transfer.files; attachedFile = transfer.files[0];
      if (!form.elements.file.files.length) throw new Error('file');
      form.elements.kind.value = 'audio'; form.elements.audio_source.value = 'human';
      message('attached'); form.elements.audio_text?.focus();
    } catch (_) { message('download'); }
  });
  form.elements.file.addEventListener('change',clearPreview);
  form.addEventListener('submit',event => { if (busy) { event.preventDefault(); message('recording'); } else freeMicrophone(); });
  document.addEventListener('visibilitychange',() => { if (document.hidden && busy) abort(); });
  window.addEventListener('pagehide',abort);
})();

'use strict';
(() => {
  const video = document.getElementById('qr-video');
  const canvas = document.getElementById('qr-canvas');
  const context = canvas.getContext('2d', { willReadFrequently: true });
  const status = document.getElementById('scan-status');
  const startButton = document.getElementById('start-camera');
  const stopButton = document.getElementById('stop-camera');
  const placeholder = document.getElementById('camera-placeholder');
  let stream = null, running = false, timer = null;
  function stop() {
    running = false;
    clearTimeout(timer);
    stream?.getTracks().forEach(track => track.stop());
    stream = null; video.srcObject = null; video.hidden = true;
    stopButton.hidden = true; startButton.hidden = false; placeholder.hidden = false;
  }
  function found(value) {
    stop(); status.textContent = 'Código lido. Identificando o local…';
    location.assign('/scan?code=' + encodeURIComponent(value));
  }
  function decode(source, width, height) {
    const ratio = Math.min(1, 1200 / Math.max(width, height));
    canvas.width = Math.round(width * ratio); canvas.height = Math.round(height * ratio);
    context.drawImage(source, 0, 0, canvas.width, canvas.height);
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height);
    return window.jsQR(pixels.data, pixels.width, pixels.height, { inversionAttempts: 'attemptBoth' });
  }
  function tick() {
    if (!running) return;
    if (video.readyState >= 2 && video.videoWidth) {
      const result = decode(video, video.videoWidth, video.videoHeight);
      if (result) { found(result.data); return; }
    }
    timer = setTimeout(tick, 180);
  }
  startButton.addEventListener('click', async () => {
    if (!navigator.mediaDevices?.getUserMedia) {
      status.textContent = 'A câmera precisa de HTTPS ou localhost. Selecione uma imagem do QR Code ou digite o código.'; return;
    }
    if (!window.jsQR) { status.textContent = 'O leitor não carregou. Recarregue a página ou digite o código.'; return; }
    try {
      stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: { ideal: 'environment' } }, audio: false });
      video.srcObject = stream; video.hidden = false; placeholder.hidden = true;
      await video.play(); running = true; startButton.hidden = true; stopButton.hidden = false;
      status.textContent = 'Mantenha a etiqueta dentro da imagem e aguarde a leitura.'; tick();
    } catch (_) { stop(); status.textContent = 'Não foi possível abrir a câmera. Verifique a permissão ou selecione uma imagem.'; }
  });
  stopButton.addEventListener('click', () => { stop(); status.textContent = 'Câmera desligada.'; });
  document.getElementById('qr-image').addEventListener('change', async event => {
    const file = event.target.files[0];
    if (!file) return;
    if (file.size > 12 * 1024 * 1024) { status.textContent = 'Selecione uma imagem de até 12 MB.'; return; }
    try {
      const bitmap = await createImageBitmap(file);
      const result = decode(bitmap, bitmap.width, bitmap.height);
      bitmap.close();
      if (result) found(result.data);
      else status.textContent = 'Nenhum QR Code encontrado. Use uma foto nítida da etiqueta completa.';
    } catch (_) { status.textContent = 'Não foi possível ler essa imagem. Tente JPG ou PNG.'; }
  });
  window.addEventListener('pagehide', stop);
})();

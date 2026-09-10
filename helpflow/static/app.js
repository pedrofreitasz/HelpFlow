'use strict';
document.querySelector('.menu-toggle')?.addEventListener('click', function () {
  const open = this.getAttribute('aria-expanded') !== 'true';
  this.setAttribute('aria-expanded', String(open));
  document.getElementById('side-nav').classList.toggle('open', open);
});
document.querySelectorAll('[data-copy]').forEach(button => button.addEventListener('click', async () => {
  const original = button.textContent;
  try {
    if (navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(button.dataset.copy);
    else {
      const text = document.createElement('textarea');
      text.value = button.dataset.copy;
      document.body.append(text); text.select();
      if (!document.execCommand('copy')) throw new Error('copy');
      text.remove();
    }
    button.textContent = 'Link copiado';
  } catch (_) {
    button.textContent = 'Selecione e copie o link';
    let fallback = button.parentElement.querySelector('.copy-fallback');
    if (!fallback) {
      fallback = document.createElement('input');
      fallback.className = 'copy-fallback'; fallback.readOnly = true;
      fallback.setAttribute('aria-label', 'Link para copiar manualmente');
      button.insertAdjacentElement('afterend', fallback);
    }
    fallback.value = button.dataset.copy; fallback.focus(); fallback.select();
  }
  setTimeout(() => { button.textContent = original; }, 3000);
}));
document.querySelectorAll('[data-print]').forEach(button => button.addEventListener('click', () => window.print()));
document.querySelectorAll('[data-back]').forEach(button => button.addEventListener('click', () => history.length > 1 ? history.back() : location.assign('/')));
document.querySelectorAll('form[method="post"]').forEach(form => form.addEventListener('submit', event => {
  if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) { event.preventDefault(); return; }
  if (form.dataset.submitted) { event.preventDefault(); return; }
  form.dataset.submitted = 'true';
  form.setAttribute('aria-busy', 'true');
}));
window.addEventListener('pageshow', () => document.querySelectorAll('form').forEach(form => {
  delete form.dataset.submitted; form.removeAttribute('aria-busy');
}));
document.querySelectorAll('[data-preview]').forEach(input => input.addEventListener('change', () => {
  const preview = input.parentElement.querySelector('.upload-preview');
  if (!preview) return;
  if (preview.dataset.url) URL.revokeObjectURL(preview.dataset.url);
  const file = input.files[0];
  input.setCustomValidity('');
  if (!file) { preview.hidden = true; return; }
  if (file.size > 5 * 1024 * 1024) { input.setCustomValidity('Escolha uma foto de até 5 MB.'); input.reportValidity(); preview.hidden = true; return; }
  preview.dataset.url = URL.createObjectURL(file); preview.src = preview.dataset.url; preview.hidden = false;
}));

/* ===========================================================
   OneStyleMariana — Utilidades de UI compartidas
   Depende de: OneStyleAPI (api.js) y OSM.toast (toast.js)
   =========================================================== */
window.OSM = window.OSM || {};

/* ---------- Texto y formato ---------- */
OSM.esc = value => OneStyleAPI.escapeHTML(value);

OSM.money = n => '$' + Number(n || 0).toLocaleString('es-CO') + ' COP';

OSM.formatDate = iso => {
  if (!iso) return '—';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '—';
  return d.toLocaleString('es-CO', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
};

/** Limpia texto libre del usuario antes de enviarlo: quita etiquetas y caracteres de control. */
OSM.clean = value => String(value ?? '')
  .replace(/<[^>]*>/g, '')
  .replace(/[\u0000-\u001f\u007f]+/g, ' ')
  .trim();

OSM.debounce = (fn, wait = 300) => {
  let t;
  return (...args) => {
    clearTimeout(t);
    t = setTimeout(() => fn(...args), wait);
  };
};

/* ---------- Manejo centralizado de errores HTTP ---------- */
/**
 * Muestra un toast entendible. El 401 no se notifica aquí porque el cierre de sesión
 * dispara el evento 'osm:session-expired', que ya avisa y redirige una sola vez.
 */
OSM.handleError = (err, fallbackTitle) => {
  if (err && err.status === 401) return;
  const type = err && (err.status === 409 || err.status === 429) ? 'warning' : 'error';
  OSM.toast[type](OneStyleAPI.friendlyError(err), fallbackTitle ? { title: fallbackTitle } : undefined);
};

/* ---------- Botones: estado de carga y anti doble clic ---------- */
OSM.setBusy = (btn, busy, loadingText) => {
  if (!btn) return;
  if (busy) {
    if (btn.dataset.busy === '1') return;
    btn.dataset.busy = '1';
    btn.dataset.originalHtml = btn.innerHTML;
    btn.disabled = true;
    btn.setAttribute('aria-busy', 'true');
    const label = loadingText || btn.textContent.trim();
    btn.innerHTML = `<span class="osm-spinner" aria-hidden="true"></span>${OSM.esc(label)}`;
  } else {
    if (btn.dataset.busy !== '1') return;
    btn.innerHTML = btn.dataset.originalHtml || btn.innerHTML;
    btn.disabled = false;
    btn.removeAttribute('aria-busy');
    delete btn.dataset.busy;
    delete btn.dataset.originalHtml;
  }
};

/**
 * Ejecuta una acción asíncrona con el botón deshabilitado mientras dura la petición.
 * Si el botón ya está ocupado ignora el clic (previene doble envío).
 */
OSM.run = async (btn, fn, loadingText) => {
  if (btn && btn.dataset.busy === '1') return undefined;
  OSM.setBusy(btn, true, loadingText);
  try {
    return await fn();
  } finally {
    OSM.setBusy(btn, false);
  }
};

/* ---------- Skeletons ---------- */
OSM.skeletonRows = (cols, rows = 5) => Array.from({ length: rows }, () =>
  `<tr>${Array.from({ length: cols }, () => '<td><span class="osm-skel"></span></td>').join('')}</tr>`
).join('');

OSM.skeletonBlock = () => `<span class="osm-skel osm-skel--block"></span>`;

OSM.emptyState = (icon, title, text, actionHtml = '') => `
  <div class="osm-empty">
    <i class="bi ${OSM.esc(icon)}" aria-hidden="true"></i>
    <strong>${OSM.esc(title)}</strong>
    <span>${OSM.esc(text)}</span>
    ${actionHtml ? `<div class="mt-3">${actionHtml}</div>` : ''}
  </div>`;

/* ---------- Confirmación (reemplaza confirm()) ---------- */
OSM.confirm = (message, { title = 'Confirmar acción', confirmText = 'Confirmar', danger = false } = {}) =>
  new Promise(resolve => {
    const wrap = document.createElement('div');
    wrap.className = 'modal fade';
    wrap.tabIndex = -1;
    wrap.innerHTML = `
      <div class="modal-dialog modal-dialog-centered">
        <div class="modal-content qv-content p-4">
          <h3 class="section-title mb-2">${OSM.esc(title)}</h3>
          <p class="text-muted mb-4">${OSM.esc(message)}</p>
          <div class="d-flex gap-2 justify-content-end">
            <button type="button" class="osm-btn" data-act="cancel">Cancelar</button>
            <button type="button" class="osm-btn ${danger ? 'osm-btn--danger' : 'osm-btn--primary'}" data-act="ok">${OSM.esc(confirmText)}</button>
          </div>
        </div>
      </div>`;
    document.body.appendChild(wrap);
    const modal = new bootstrap.Modal(wrap);
    let result = false;
    wrap.addEventListener('click', e => {
      const act = e.target.closest('[data-act]');
      if (!act) return;
      result = act.dataset.act === 'ok';
      modal.hide();
    });
    wrap.addEventListener('hidden.bs.modal', () => {
      modal.dispose();
      wrap.remove();
      resolve(result);
    });
    modal.show();
  });

/* ---------- Validación inline de formularios ---------- */
OSM.field = {
  /** Marca un campo como inválido y muestra el mensaje debajo. */
  error(input, message) {
    const box = input.closest('.osm-field');
    if (!box) return;
    box.classList.add('is-invalid');
    input.setAttribute('aria-invalid', 'true');
    let err = box.querySelector('.osm-field__error');
    if (!err) {
      err = document.createElement('div');
      err.className = 'osm-field__error';
      err.setAttribute('role', 'alert');
      box.appendChild(err);
    }
    err.textContent = message;
  },
  clear(input) {
    const box = input.closest('.osm-field');
    if (!box) return;
    box.classList.remove('is-invalid');
    input.removeAttribute('aria-invalid');
    const err = box.querySelector('.osm-field__error');
    if (err) err.textContent = '';
  }
};

OSM.passwordPolicy = {
  check(pwd) {
    const s = String(pwd ?? '');
    return {
      length: s.length >= 8,
      upper: /[A-Z]/.test(s),
      lower: /[a-z]/.test(s),
      digit: /[0-9]/.test(s)
    };
  },
  isValid(pwd) {
    const c = this.check(pwd);
    return c.length && c.upper && c.lower && c.digit;
  },
  message: 'La contraseña debe tener al menos 8 caracteres, una mayúscula, una minúscula y un número (RN-SEG-008).'
};

OSM.rules = {
  required: msg => v => (String(v ?? '').trim() ? '' : (msg || 'Este campo es obligatorio.')),
  minLength: (n, msg) => v => (String(v ?? '').trim().length >= n ? '' : (msg || `Debe tener al menos ${n} caracteres.`)),
  strongPassword: msg => v => (OSM.passwordPolicy.isValid(v) ? '' : (msg || OSM.passwordPolicy.message)),
  email: msg => v => (/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(String(v ?? '').trim()) ? '' : (msg || 'Ingresa un correo válido.')),
  phone: msg => v => (String(v ?? '').replace(/\D/g, '').length >= 7 ? '' : (msg || 'Ingresa un teléfono válido (mínimo 7 dígitos).')),
  positiveNumber: msg => v => (Number(v) > 0 ? '' : (msg || 'Debe ser un número mayor a cero.')),
  integerMin: (n, msg) => v => (Number.isInteger(Number(v)) && String(v).trim() !== '' && Number(v) >= n ? '' : (msg || `Debe ser un entero mayor o igual a ${n}.`)),
  match: (getOther, msg) => v => (v === getOther() ? '' : (msg || 'Los valores no coinciden.'))
};

/**
 * Valida un formulario con reglas por nombre de campo.
 * schema = { nombre: [OSM.rules.required(), ...], ... }
 * Devuelve true si todo es válido; si no, resalta los campos y enfoca el primero con error.
 */
OSM.validate = (form, schema) => {
  let firstBad = null;
  Object.entries(schema).forEach(([name, rules]) => {
    const input = form.elements[name];
    if (!input) return;
    let msg = '';
    for (const rule of rules) {
      msg = rule(input.value);
      if (msg) break;
    }
    if (msg) {
      OSM.field.error(input, msg);
      if (!firstBad) firstBad = input;
    } else {
      OSM.field.clear(input);
    }
  });
  if (firstBad) firstBad.focus();
  return !firstBad;
};

/** Validación en vivo: al salir del campo o escribir, se revalida solo ese campo. */
OSM.liveValidate = (form, schema) => {
  const check = e => {
    const input = e.target;
    const rules = schema[input.name];
    if (!rules) return;
    let msg = '';
    for (const rule of rules) {
      msg = rule(input.value);
      if (msg) break;
    }
    if (msg) OSM.field.error(input, msg);
    else OSM.field.clear(input);
  };
  form.addEventListener('blur', check, true);
  form.addEventListener('input', e => {
    if (e.target.closest('.osm-field.is-invalid')) check(e);
  });
};

/* ---------- WhatsApp: enlace al cliente con mensaje prearmado ---------- */
OSM.whatsappUrl = (phone, message) => {
  let digits = String(phone || '').replace(/\D/g, '');
  if (!digits) return null;
  if (digits.length === 10 && digits.startsWith('3')) digits = '57' + digits; // móvil colombiano
  return `https://wa.me/${digits}?text=${encodeURIComponent(OSM.clean(message))}`;
};

/* ---------- CSV seguro con prevención de Formula Injection (OWASP) ---------- */
OSM.csv = {
  sanitizeCell(value) {
    if (value === null || value === undefined) return '';
    let str = String(value);
    if (/^[=+\-@\t\r]/.test(str)) {
      str = `'${str}`;
    }
    if (/[",\n\r]/.test(str)) {
      return `"${str.replace(/"/g, '""')}"`;
    }
    return str;
  },
  toCSV(headers, rows) {
    const headerLine = (headers || []).map(h => this.sanitizeCell(h)).join(',');
    const bodyLines = (rows || []).map(row => (row || []).map(cell => this.sanitizeCell(cell)).join(','));
    return [headerLine, ...bodyLines].join('\r\n');
  },
  download(filename, headers, rows) {
    const csvContent = '\uFEFF' + this.toCSV(headers, rows);
    const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename || 'reporte.csv';
    document.body.appendChild(link);
    link.click();
    link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
};

/* ===========================================================
   OneStyleMariana — Notificaciones tipo toast (reemplaza alert())
   API: OSM.toast.success(msg, {title}) | error | warning | info
   =========================================================== */
window.OSM = window.OSM || {};

OSM.toast = (() => {
  const ICONS = {
    success: 'bi-check-circle-fill',
    error:   'bi-exclamation-octagon-fill',
    warning: 'bi-exclamation-triangle-fill',
    info:    'bi-info-circle-fill'
  };
  const DEFAULT_TITLES = {
    success: 'Listo',
    error:   'No se pudo completar',
    warning: 'Atención',
    info:    'Información'
  };
  const MAX_VISIBLE = 4;

  function container() {
    let el = document.getElementById('osmToasts');
    if (!el) {
      el = document.createElement('div');
      el.id = 'osmToasts';
      el.className = 'osm-toasts';
      el.setAttribute('role', 'region');
      el.setAttribute('aria-label', 'Notificaciones');
      el.setAttribute('aria-live', 'polite');
      document.body.appendChild(el);
    }
    return el;
  }

  function dismiss(node) {
    if (!node || node.classList.contains('is-leaving')) return;
    node.classList.add('is-leaving');
    setTimeout(() => node.remove(), 180);
  }

  function show(type, message, { title = null, duration = 5000 } = {}) {
    const box = container();
    while (box.children.length >= MAX_VISIBLE) box.firstElementChild.remove();

    const node = document.createElement('div');
    node.className = `osm-toast osm-toast--${type}`;
    node.setAttribute('role', type === 'error' ? 'alert' : 'status');

    // textContent evita cualquier inyección de HTML (XSS)
    const icon = document.createElement('i');
    icon.className = `bi ${ICONS[type] || ICONS.info} osm-toast__icon`;
    icon.setAttribute('aria-hidden', 'true');

    const body = document.createElement('div');
    body.className = 'osm-toast__body';
    const t = document.createElement('p');
    t.className = 'osm-toast__title';
    t.textContent = title || DEFAULT_TITLES[type] || '';
    const m = document.createElement('p');
    m.className = 'osm-toast__msg';
    m.textContent = message || '';
    body.append(t, m);

    const close = document.createElement('button');
    close.type = 'button';
    close.className = 'osm-toast__close';
    close.setAttribute('aria-label', 'Cerrar notificación');
    close.textContent = '×';
    close.addEventListener('click', () => dismiss(node));

    node.append(icon, body, close);
    box.appendChild(node);

    if (duration > 0) setTimeout(() => dismiss(node), duration);
    return node;
  }

  return {
    show,
    success: (msg, opts) => show('success', msg, opts),
    error:   (msg, opts) => show('error', msg, Object.assign({ duration: 7000 }, opts)),
    warning: (msg, opts) => show('warning', msg, opts),
    info:    (msg, opts) => show('info', msg, opts)
  };
})();

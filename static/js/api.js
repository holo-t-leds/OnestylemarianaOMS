/* ===========================================================
   OneStyleMariana — Cliente HTTP Desacoplado y Sanitización XSS
   Trazabilidad: RF-SEG-001 a RF-SEG-017 / OWASP Frontend Security
   =========================================================== */

const OneStyleAPI = (() => {
  const TOKEN_KEY   = 'osm_auth_token';
  const USER_KEY    = 'osm_auth_user';
  const REFRESH_KEY = 'osm_refresh_token';
  const EXPIRES_KEY = 'osm_token_expires_at';
  const SESSION_KEY = 'osm_cart_session_id';
  const REFRESH_MARGIN_MS = 90 * 1000; // Renovar cuando falten menos de 90 s

  function getSessionId() {
    try {
      let sid = sessionStorage.getItem(SESSION_KEY);
      if (!sid) {
        sid = 'sess-' + Math.random().toString(36).slice(2, 11) + '-' + Date.now();
        sessionStorage.setItem(SESSION_KEY, sid);
      }
      return sid;
    } catch (_) {
      return 'sess-default-guest';
    }
  }

  /**
   * Sanitiza cualquier cadena antes de inyectarla en el DOM para mitigar XSS (OWASP A03).
   */
  function escapeHTML(value) {
    if (value === null || value === undefined) return '';
    return String(value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  function getToken() {
    try { return sessionStorage.getItem(TOKEN_KEY); } catch (_) { return null; }
  }

  function getSavedUser() {
    try {
      const raw = sessionStorage.getItem(USER_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (_) {
      return null;
    }
  }

  function setSession(token, user, extra = null) {
    try {
      if (token) sessionStorage.setItem(TOKEN_KEY, token);
      if (user)  sessionStorage.setItem(USER_KEY, JSON.stringify(user));
      if (extra && extra.refresh_token) sessionStorage.setItem(REFRESH_KEY, extra.refresh_token);
      if (extra && extra.expires_in) {
        sessionStorage.setItem(EXPIRES_KEY, String(Date.now() + Number(extra.expires_in) * 1000));
      }
    } catch (_) {}
  }

  function clearSession() {
    try {
      [TOKEN_KEY, USER_KEY, REFRESH_KEY, EXPIRES_KEY].forEach(k => sessionStorage.removeItem(k));
    } catch (_) {}
  }

  function getRefreshToken() {
    try { return sessionStorage.getItem(REFRESH_KEY); } catch (_) { return null; }
  }

  function msUntilExpiry() {
    try {
      const exp = Number(sessionStorage.getItem(EXPIRES_KEY));
      return exp ? exp - Date.now() : Infinity;
    } catch (_) {
      return Infinity;
    }
  }

  /** Cierra la sesión local y notifica a la UI para que redirija al login. */
  function expireSession(reason = 'expired') {
    const hadSession = !!getToken();
    clearSession();
    if (hadSession) {
      window.dispatchEvent(new CustomEvent('osm:session-expired', { detail: { reason } }));
    }
  }

  /**
   * Renueva el par access/refresh (rotación). Una sola petición en vuelo aunque
   * varias llamadas la soliciten a la vez. Devuelve true si la renovación tuvo éxito.
   */
  let refreshInFlight = null;
  function refreshSession() {
    if (refreshInFlight) return refreshInFlight;
    const refresh = getRefreshToken();
    if (!refresh) return Promise.resolve(false);

    refreshInFlight = (async () => {
      try {
        const response = await fetch('/api/auth/refresh', {
          method: 'POST',
          headers: { 'Accept': 'application/json', 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: refresh })
        });
        if (!response.ok) return false;
        const payload = await response.json();
        const d = payload && payload.data;
        if (!d || !d.token) return false;
        setSession(d.token, null, d);
        return true;
      } catch (_) {
        return false;
      } finally {
        refreshInFlight = null;
      }
    })();
    return refreshInFlight;
  }

  /** Traduce errores HTTP a mensajes comprensibles para el usuario. */
  function friendlyError(err) {
    const status = err && err.status;
    const msg = (err && err.message) || '';
    if (status === 401) return msg || 'Tu sesión expiró. Inicia sesión nuevamente.';
    if (status === 403) return msg || 'No tienes permisos para realizar esta acción.';
    if (status === 404) return msg || 'No encontramos el recurso solicitado.';
    if (status === 409) return msg || 'La operación entra en conflicto con el estado actual.';
    if (status === 429) return msg || 'Demasiadas solicitudes. Intenta de nuevo en un momento.';
    if (status >= 500) return 'Ocurrió un problema en el servidor. Intenta más tarde.';
    if (!status) return 'No fue posible conectar con el servidor. Revisa tu conexión.';
    return msg || 'No fue posible completar la solicitud.';
  }

  /**
   * Gestiona el estado de carga de un botón (deshabilita durante petición en vuelo y restaura al finalizar).
   */
  async function withButtonLoading(buttonEl, loadingText, asyncFn) {
    if (!buttonEl) return asyncFn();
    const originalHTML = buttonEl.innerHTML;
    buttonEl.disabled = true;
    buttonEl.setAttribute('aria-busy', 'true');
    if (loadingText) buttonEl.textContent = loadingText;
    try {
      return await asyncFn();
    } finally {
      buttonEl.disabled = false;
      buttonEl.removeAttribute('aria-busy');
      buttonEl.innerHTML = originalHTML;
    }
  }

  /**
   * Petición HTTP base estandarizada hacia la API RESTful de Flask.
   */
  async function request(endpoint, { method = 'GET', body = null, auth = true, _retried = false } = {}) {
    // Renovación proactiva y transparente antes de que expire el access token
    if (auth && getToken() && getRefreshToken() && msUntilExpiry() < REFRESH_MARGIN_MS) {
      await refreshSession();
    }

    const headers = {
      'Accept': 'application/json',
      'X-Session-ID': getSessionId()
    };
    if (body !== null) {
      headers['Content-Type'] = 'application/json';
    }
    const usedToken = auth ? getToken() : null;
    if (usedToken) headers['Authorization'] = `Bearer ${usedToken}`;

    let response;
    try {
      response = await fetch(endpoint, {
        method,
        headers,
        body: body !== null ? JSON.stringify(body) : null
      });
    } catch (netErr) {
      const error = new Error('No fue posible conectar con el servidor.');
      error.status = 0;
      throw error;
    }

    let payload = null;
    try {
      payload = await response.json();
    } catch (_) {
      payload = { status: 'error', message: 'Respuesta inesperada del servidor.' };
    }

    // 401 con sesión activa: un reintento tras renovar; si falla, se cierra la sesión
    if (response.status === 401 && usedToken && !_retried) {
      const renewed = await refreshSession();
      if (renewed) {
        return request(endpoint, { method, body, auth, _retried: true });
      }
      expireSession('refresh_failed');
    }

    if (!response.ok || (payload && payload.status === 'error')) {
      const error = new Error((payload && payload.message) || `Error HTTP ${response.status}`);
      error.status = response.status;
      error.payload = payload;
      throw error;
    }

    return payload;
  }

  /** Construye una query string omitiendo valores vacíos. */
  function toQuery(params = {}) {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null && v !== '') qs.set(k, v);
    });
    const s = qs.toString();
    return s ? '?' + s : '';
  }

  /** Captura los tokens que devuelven login/registro sin que la UI tenga que conocerlos. */
  async function authAndStore(endpoint, body) {
    const res = await request(endpoint, { method: 'POST', auth: false, body });
    if (res && res.data && res.data.token) {
      setSession(res.data.token, res.data.usuario, res.data);
    }
    return res;
  }

  return {
    escapeHTML,
    getToken,
    getSavedUser,
    setSession,
    clearSession,
    withButtonLoading,
    request,
    refreshSession,
    friendlyError,

    // Endpoints Módulo 1: Seguridad y Usuarios (RF-SEG-006 a RF-SEG-017)
    auth: {
      register( { nombre, apellido, email, contrasena, telefono } ) {
        return authAndStore('/api/auth/register', { nombre, apellido, email, contrasena, telefono });
      },
      login( { email, contrasena } ) {
        return authAndStore('/api/auth/login', { email, contrasena });
      },
      logout() {
        return request('/api/auth/logout', { method: 'POST', auth: true });
      },
      forgotPassword( { email } ) {
        return request('/api/auth/forgot-password', {
          method: 'POST',
          auth: false,
          body: { email }
        });
      },
      resetPassword( { token, nueva_password } ) {
        return request('/api/auth/reset-password', {
          method: 'POST',
          auth: false,
          body: { token, nueva_password }
        });
      },
      getProfile() {
        return request('/api/perfil', { method: 'GET', auth: true });
      },
      updateProfile( { nombre, apellido, email, telefono } ) {
        return request('/api/perfil', {
          method: 'PUT',
          auth: true,
          body: { nombre, apellido, email, telefono }
        });
      },
      changePassword( { contrasena_actual, nueva_password } ) {
        return request('/api/perfil/password', {
          method: 'PUT',
          auth: true,
          body: { contrasena_actual, nueva_password }
        });
      }
    },

    // Panel Administrativo SPA (#admin): dashboard, OMS paginado y catálogo/inventario
    admin: {
      dashboard() {
        return request('/api/admin/dashboard', { method: 'GET' });
      },
      orders: {
        list(params = {}) { return request(`/api/admin/pedidos${toQuery(params)}`, { method: 'GET' }); },
        transition(id, { nuevo_estado, motivo = '' }) {
          return request(`/api/admin/pedidos/${encodeURIComponent(id)}/estado`, {
            method: 'PATCH',
            body: { nuevo_estado, motivo }
          });
        }
      },
      catalog: {
        products(params = {}) { return request(`/api/admin/productos${toQuery(params)}`, { method: 'GET' }); },
        createProduct(payload) { return request('/api/admin/productos', { method: 'POST', body: payload }); },
        updateProduct(id, payload) {
          return request(`/api/admin/productos/${encodeURIComponent(id)}`, { method: 'PUT', body: payload });
        },
        setVisibility(id, visible) {
          return request(`/api/admin/productos/${encodeURIComponent(id)}/visibilidad`, {
            method: 'PATCH',
            body: { estado_visibilidad: visible }
          });
        },
        addVariant(payload) { return request('/api/admin/variantes', { method: 'POST', body: payload }); },
        adjustStock(payload) { return request('/api/admin/inventario/ajuste', { method: 'POST', body: payload }); },
        alerts() { return request('/api/admin/inventario/alertas', { method: 'GET' }); },
        categories() { return request('/api/admin/categorias', { method: 'GET' }); },
        createCategory(payload) { return request('/api/admin/categorias', { method: 'POST', body: payload }); },
        attributes() { return request('/api/atributos', { method: 'GET', auth: false }); }
      }
    },

    // Endpoints Módulo 2: Catálogo, Categorías, Atributos e Inventario (RF-CAT-001 a RF-CAT-018)
    catalogo: {
      list(params = {}) {
        const qs = new URLSearchParams();
        Object.entries(params).forEach(([k, v]) => {
          if (v !== undefined && v !== null && v !== '') qs.set(k, v);
        });
        const queryString = qs.toString();
        return request(`/api/catalogo${queryString ? '?' + queryString : ''}`, { method: 'GET', auth: false });
      },
      detail(productKey) {
        return request(`/api/catalogo/${encodeURIComponent(productKey)}`, { method: 'GET', auth: false });
      },
      categories() {
        return request('/api/productos/categorias', { method: 'GET', auth: false });
      },
      attributes() {
        return request('/api/atributos', { method: 'GET', auth: false });
      },
      adminCreateProduct(payload) {
        return request('/api/admin/productos', { method: 'POST', auth: true, body: payload });
      },
      adminAdjustStock(payload) {
        return request('/api/admin/inventario/ajuste', { method: 'POST', auth: true, body: payload });
      }
    },

    // Endpoints Módulo 3: Carrito de Compras y Reservas Temporales de Stock (RF-CRT-001 a RF-CRT-003)
    carrito: {
      get() {
        return request('/api/carrito', { method: 'GET', auth: true });
      },
      addItem({ fk_id_variante, cantidad = 1 }) {
        return request('/api/carrito/items', {
          method: 'POST',
          auth: true,
          body: { fk_id_variante, cantidad }
        });
      },
      updateItem(varianteId, { cantidad }) {
        return request(`/api/carrito/items/${encodeURIComponent(varianteId)}`, {
          method: 'PUT',
          auth: true,
          body: { cantidad }
        });
      },
      removeItem(varianteId) {
        return request(`/api/carrito/items/${encodeURIComponent(varianteId)}`, {
          method: 'DELETE',
          auth: true
        });
      },
      clear() {
        return request('/api/carrito', { method: 'DELETE', auth: true });
      },
      saveDispatch({ direccion_envio, barrio, ciudad, telefono, observaciones, nombre_receptor, email }) {
        return request('/api/carrito/despacho', {
          method: 'POST',
          auth: true,
          body: { direccion_envio, barrio, ciudad, telefono, observaciones, nombre_receptor, email }
        });
      }
    },

    // Endpoints Módulo 4: Gestión de Pedidos (OMS), Máquina de Estados y Concierge WhatsApp (RF-PED-001 a RF-PED-004)
    pedidos: {
      checkout(payload) {
        return request('/api/pedidos/checkout', {
          method: 'POST',
          auth: true,
          body: payload
        });
      },
      track(codigoOrden, contacto = '') {
        const qs = contacto ? `?contacto=${encodeURIComponent(contacto)}` : '';
        return request(`/api/pedidos/seguimiento/${encodeURIComponent(codigoOrden)}${qs}`, {
          method: 'GET',
          auth: true
        });
      },
      myOrders() {
        return request('/api/pedidos/mis-pedidos', { method: 'GET', auth: true });
      },
      adminList(params = {}) {
        const qs = new URLSearchParams();
        Object.entries(params).forEach(([k, v]) => {
          if (v !== undefined && v !== null && v !== '') qs.set(k, v);
        });
        const s = qs.toString();
        return request(`/api/admin/pedidos${s ? '?' + s : ''}`, { method: 'GET', auth: true });
      },
      adminTransition(pedidoId, { nuevo_estado, motivo = '' }) {
        return request(`/api/admin/pedidos/${encodeURIComponent(pedidoId)}/estado`, {
          method: 'PATCH',
          auth: true,
          body: { nuevo_estado, motivo }
        });
      },
      adminReport(params = {}) {
        const qs = new URLSearchParams();
        Object.entries(params).forEach(([k, v]) => {
          if (v !== undefined && v !== null && v !== '') qs.set(k, v);
        });
        const s = qs.toString();
        return request(`/api/admin/pedidos/reporte${s ? '?' + s : ''}`, { method: 'GET', auth: true });
      }
    },

    // Endpoints Módulo 5: Centro de Ayuda, Preguntas Frecuentes y Soporte (RF-FAQ-001 a RF-FAQ-011)
    faqs: {
      list(params = {}) {
        const qs = new URLSearchParams();
        Object.entries(params).forEach(([k, v]) => {
          if (v !== undefined && v !== null && v !== '') qs.set(k, v);
        });
        const s = qs.toString();
        return request(`/api/v1/faqs/${s ? '?' + s : ''}`, { method: 'GET', auth: false });
      },
      vote(faqId, helpful = true) {
        return request(`/api/v1/faqs/${encodeURIComponent(faqId)}/vote/`, {
          method: 'POST',
          auth: false,
          body: { helpful }
        });
      },
      sendContact({ nombre, email, asunto, mensaje, codigo_orden = '' }) {
        return request('/api/v1/support/contact/', {
          method: 'POST',
          auth: false,
          body: { nombre, email, asunto, mensaje, codigo_orden }
        });
      },
      adminList() {
        return request('/api/admin/faqs', { method: 'GET', auth: true });
      },
      adminCreate(payload) {
        return request('/api/admin/faqs', { method: 'POST', auth: true, body: payload });
      },
      adminUpdate(faqId, payload) {
        return request(`/api/admin/faqs/${encodeURIComponent(faqId)}`, { method: 'PUT', auth: true, body: payload });
      },
      adminSetState(faqId, estado) {
        return request(`/api/admin/faqs/${encodeURIComponent(faqId)}/estado`, {
          method: 'PATCH',
          auth: true,
          body: { estado }
        });
      }
    }
  };
})();

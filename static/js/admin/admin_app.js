/* ===========================================================
   OneStyleMariana — Controlador SPA del Panel Administrativo (#/admin)
   Depende de: OneStyleAPI (api.js), OSM.toast (toast.js) y OSM.* (helpers.js)
   =========================================================== */
(() => {
  'use strict';

  window.OSM = window.OSM || {};

  const PANELS = ['resumen', 'pedidos', 'catalogo', 'inventario', 'perfil', 'personal', 'faqs', 'reportes', 'maestros', 'soporte'];
  const NEXT_STATE_BY_STAGE = {
    1: 'Confirmado',
    2: 'En Empaque',
    3: 'Despachado',
    4: 'Entregado'
  };
  const TICKET_ALLOWED_STATES = ['ABIERTO', 'EN_PROCESO', 'RESUELTO'];
  const TICKET_NEXT_STATE = {
    ABIERTO: 'EN_PROCESO',
    EN_PROCESO: 'RESUELTO'
  };

  const state = {
    initialized: false,
    activePanel: 'resumen',
    orders: { page: 1, per_page: 8, estado: '', q: '', items: [], pagination: null },
    catalog: { page: 1, per_page: 8, q: '', categoria: '', estado: '', items: [], pagination: null },
    support: { estado: '', items: [], ticketsAbiertos: 0, selectedTicket: null },
    audit: { items: [], q: '', tabla: '', accion: '', fecha_inicio: '', fecha_fin: '' },
    staff: { items: [], q: '', rol: '' },
    faqs: { items: [], categories: [], q: '', cat: '', estado: '', editingId: null },
    reports: { fecha_inicio: '', fecha_fin: '', estado: '', data: null },
    masters: { tab: 'categorias', categories: [], tallas: [], colores: [], editingCatId: null, editingSizeId: null, editingColorId: null },
    gallery: { items: [], pendingFiles: [], newProductFiles: [] },
    categories: [],
    attributes: { tallas: [], colores: [] },
    selectedOrder: null,
    selectedProductForVariant: null,
    selectedProductForEdit: null
  };

  let orderDrawer = null;
  let productModal = null;
  let editProductModal = null;
  let variantModal = null;
  let ticketDrawer = null;
  let staffModal = null;
  let faqModal = null;
  let masterCatModal = null;
  let masterSizeModal = null;
  let masterColorModal = null;

  function domEl(tag, className = '', text = null) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== null && text !== undefined) node.textContent = String(text);
    return node;
  }

  function updateTicketsBadge(openCount) {
    const count = Math.max(0, Number(openCount || 0));
    state.support.ticketsAbiertos = count;
    const navBadge = document.getElementById('admNavTicketsBadge');
    const tabBadge = document.getElementById('admTicketsTabCount');
    if (navBadge) {
      navBadge.textContent = String(count);
      navBadge.classList.toggle('d-none', count <= 0);
    }
    if (tabBadge) {
      tabBadge.textContent = String(count);
    }
  }

  function badgeForOrderState(estado, etapa) {
    const stage = Number(etapa ?? 1);
    if (stage === 0 || estado === 'Cancelado') return `<span class="osm-badge osm-badge--Cancelado">${OSM.esc(estado || 'Cancelado')}</span>`;
    const cls = `osm-badge--${String(estado || 'Registrado').replace(/\s+/g, '-')}`;
    return `<span class="osm-badge ${OSM.esc(cls)}">${OSM.esc(estado || 'Registrado')}</span>`;
  }

  function updateSidebarIdentity() {
    const user = OneStyleAPI.getSavedUser();
    const nameEl = document.getElementById('admUserName');
    const roleEl = document.getElementById('admUserRole');
    const personalNav = document.getElementById('admNavPersonalItem');
    const faqsNav     = document.getElementById('admNavFaqsItem');
    const reportesNav = document.getElementById('admNavReportesItem');
    const maestrosNav = document.getElementById('admNavMaestrosItem');
    const soporteNav  = document.getElementById('admNavSoporteItem');
    if (user && nameEl) {
      nameEl.textContent = `${user.nombre || ''} ${user.apellido || ''}`.trim() || user.email || 'Administradora';
    }
    if (user && roleEl) {
      roleEl.textContent = user.rol || 'Administradora';
    }
    const isAdmin = Boolean(user && user.rol === 'Administradora');
    [personalNav, faqsNav, reportesNav, maestrosNav, soporteNav].forEach(navEl => {
      if (navEl) navEl.classList.toggle('d-none', !isAdmin);
    });
  }

  /* =========================================================
     1. RESUMEN Y MÉTRICAS CONSOLIDADAS (GET /api/admin/dashboard)
     ========================================================= */
  async function loadResumen() {
    const kpiPending = document.getElementById('admKpiPending');
    const kpiRevenue = document.getElementById('admKpiRevenue');
    const kpiAlerts  = document.getElementById('admKpiAlerts');
    const kpiCatalog = document.getElementById('admKpiCatalog');
    const barsWrap   = document.getElementById('admStateBars');
    const alertsBody = document.getElementById('admLowStockBody');
    const recentBody = document.getElementById('admRecentOrdersBody');
    const navPending = document.getElementById('admNavPendingBadge');
    const navCatalog = document.getElementById('admNavCatalogBadge');
    const navAlerts  = document.getElementById('admNavAlertsBadge');

    if (barsWrap) barsWrap.innerHTML = OSM.skeletonBlock('8rem');
    if (alertsBody) alertsBody.innerHTML = OSM.skeletonRows(4, 3);
    if (recentBody) recentBody.innerHTML = OSM.skeletonRows(5, 4);

    try {
      const res = await OneStyleAPI.admin.dashboard();
      const d = (res && res.data) || {};
      const ped = d.pedidos || {};
      const inv = d.inventario || {};
      const cat = d.catalogo || {};
      const porEstado = ped.conteo_por_estado || ped.por_estado || {};
      const pendingCount = Number(ped.pedidos_pendientes ?? ped.pendientes_atencion ?? 0);
      const totalRevenue = Number(ped.ventas_totales ?? ped.ingresos_totales ?? 0);
      const alertCount   = Number(inv.alertas_total ?? ((inv.bajo_stock_count || 0) + (inv.agotados_count || 0)));
      const visCount     = Number(cat.productos_visibles ?? cat.productos_activos ?? 0);

      if (kpiPending) kpiPending.textContent = String(pendingCount);
      if (kpiRevenue) kpiRevenue.textContent = OSM.money(totalRevenue);
      if (kpiAlerts)  kpiAlerts.textContent  = String(alertCount);
      if (kpiCatalog) kpiCatalog.textContent = `${visCount} / ${cat.total_productos ?? 0}`;

      if (navPending) {
        navPending.textContent = String(pendingCount);
        navPending.classList.toggle('d-none', pendingCount <= 0);
      }
      if (navCatalog) {
        navCatalog.textContent = String(visCount);
        navCatalog.classList.toggle('d-none', visCount <= 0);
      }
      if (navAlerts) {
        navAlerts.textContent = String(alertCount);
        navAlerts.classList.toggle('d-none', alertCount <= 0);
      }

      const sop = d.soporte || {};
      updateTicketsBadge(Number(sop.tickets_abiertos ?? 0));

      const totalOrders = Math.max(1, Number(ped.total_pedidos || 0));
      const statesOrder = ['Registrado', 'Confirmado', 'En Empaque', 'Despachado', 'Entregado', 'Cancelado'];
      if (barsWrap) {
        barsWrap.innerHTML = statesOrder.map(st => {
          const count = Number(porEstado[st] || 0);
          const pct = Math.round((count / totalOrders) * 100);
          const cancelCls = st === 'Cancelado' ? 'is-cancel' : '';
          return `
            <div class="adm-bar__row ${cancelCls}">
              <span>${OSM.esc(st)}</span>
              <progress class="adm-bar__progress" value="${pct}" max="100"></progress>
              <span class="adm-bar__num">${count}</span>
            </div>`;
        }).join('');
      }

      const alertas = Array.isArray(inv.alertas)
        ? inv.alertas.slice(0, 6)
        : [
            ...(Array.isArray(inv.agotados) ? inv.agotados : []),
            ...(Array.isArray(inv.alertas_bajo_stock) ? inv.alertas_bajo_stock : [])
          ].slice(0, 6);

      if (alertsBody) {
        if (!alertas.length) {
          alertsBody.innerHTML = `<tr><td colspan="4">${OSM.emptyState('bi-check2-circle', 'Inventario saludable', 'Todas las variantes superan el umbral mínimo de stock.')}</td></tr>`;
        } else {
          alertsBody.innerHTML = alertas.map(a => `
            <tr>
              <td>
                <div class="t-strong">${OSM.esc(a.nombre_producto || a.sku)}</div>
                <div class="t-muted">${OSM.esc(a.sku)} · ${OSM.esc(a.color || '')} / Talla ${OSM.esc(a.talla || '')}</div>
              </td>
              <td>
                <span class="osm-badge ${Number(a.stock_disponible) === 0 ? 'osm-badge--low' : 'osm-badge--Registrado'}">
                  ${Number(a.stock_disponible)} disp.
                </span>
              </td>
              <td class="t-muted">Mín. ${Number(a.umbral_alerta ?? 3)}</td>
              <td class="t-right">
                <a href="#/admin/inventario" class="osm-btn osm-btn--sm">Ajustar</a>
              </td>
            </tr>`).join('');
        }
      }

      const recientes = Array.isArray(d.pedidos_recientes) ? d.pedidos_recientes : [];
      if (recentBody) {
        if (!recientes.length) {
          recentBody.innerHTML = `<tr><td colspan="5">${OSM.emptyState('bi-inbox', 'Sin pedidos recientes', 'Los nuevos pedidos aparecerán aquí en tiempo real.')}</td></tr>`;
        } else {
          recentBody.innerHTML = recientes.map(o => {
            const desp = o.datos_despacho || {};
            return `
              <tr>
                <td class="t-strong">${OSM.esc(o.codigo_orden)}</td>
                <td>
                  <div>${OSM.esc(desp.nombre_receptor || 'Cliente')}</div>
                  <div class="t-muted">${OSM.esc(desp.ciudad || 'Colombia')}</div>
                </td>
                <td class="t-strong">${OSM.money(o.total)}</td>
                <td>${badgeForOrderState(o.estado, o.etapa_fsm)}</td>
                <td class="t-right">
                  <button type="button" class="osm-btn osm-btn--sm" data-adm-open-order="${Number(o.id_pedido)}">
                    Gestionar
                  </button>
                </td>
              </tr>`;
          }).join('');
        }
      }
    } catch (err) {
      OSM.handleError(err, 'No se pudo cargar el resumen');
    }
  }

  /* =========================================================
     2. GESTIÓN DE PEDIDOS OMS + PAGINACIÓN EN SERVIDOR + DRAWER
     ========================================================= */
  async function loadPedidos() {
    const tbody = document.getElementById('admOrdersBody');
    const info  = document.getElementById('admOrdersPageInfo');
    const label = document.getElementById('admOrdersPageLabel');
    const prev  = document.getElementById('admOrdersPrev');
    const next  = document.getElementById('admOrdersNext');
    if (!tbody) return;

    tbody.innerHTML = OSM.skeletonRows(6, 5);

    try {
      const res = await OneStyleAPI.admin.orders.list({
        page: state.orders.page,
        per_page: state.orders.per_page,
        estado: state.orders.estado,
        q: state.orders.q
      });
      const data = (res && res.data) || {};
      const items = Array.isArray(data.items)
        ? data.items
        : (Array.isArray(data.pedidos) ? data.pedidos : []);
      state.orders.items = items;
      state.orders.pagination = data;

      if (!items.length) {
        tbody.innerHTML = `<tr><td colspan="6">${OSM.emptyState('bi-bag-x', 'No se encontraron pedidos', 'Prueba ajustando el filtro de estado o el término de búsqueda.')}</td></tr>`;
      } else {
        tbody.innerHTML = items.map(p => {
          const desp = p.datos_despacho || {};
          const itemsSummary = (p.detalle_items || [])
            .map(i => `${OSM.esc(i.nombre_producto)} (${OSM.esc(i.talla)}) ×${Number(i.cantidad)}`)
            .join(', ');
          const waMsg = `Hola ${desp.nombre_receptor || ''}, te escribimos de OneStyleMariana sobre tu pedido ${p.codigo_orden} (${p.estado}).`;
          const waHref = OSM.whatsappUrl(desp.telefono, waMsg);

          return `
            <tr>
              <td>
                <div class="t-strong">${OSM.esc(p.codigo_orden)}</div>
                <div class="t-muted">${OSM.formatDate(p.fecha_creacion)}</div>
              </td>
              <td>
                <div class="t-strong">${OSM.esc(desp.nombre_receptor || 'Cliente')}</div>
                <div class="t-muted">${OSM.esc(desp.ciudad || '')} · ${OSM.esc(desp.telefono || desp.email || '')}</div>
              </td>
              <td>
                <div class="text-truncate adm-cell-truncate" title="${OSM.esc(itemsSummary)}">${itemsSummary || '—'}</div>
              </td>
              <td class="t-strong">${OSM.money(p.total)}</td>
              <td>${badgeForOrderState(p.estado, p.etapa_fsm)}</td>
              <td class="t-right">
                <div class="adm-actions">
                  ${waHref ? `<a href="${OSM.esc(waHref)}" target="_blank" rel="noopener noreferrer" class="osm-btn osm-btn--sm osm-btn--whatsapp" title="Contactar por WhatsApp"><i class="bi bi-whatsapp"></i></a>` : ''}
                  <button type="button" class="osm-btn osm-btn--sm osm-btn--primary" data-adm-open-order="${Number(p.id_pedido)}">
                    <i class="bi bi-sliders"></i> Estado / Detalle
                  </button>
                </div>
              </td>
            </tr>`;
        }).join('');
      }

      const page = Number(data.page || 1);
      const totalPages = Number(data.total_pages || 1);
      const total = Number(data.total ?? items.length);
      if (info)  info.textContent  = `Mostrando ${items.length} de ${total} pedidos`;
      if (label) label.textContent = `Página ${page} de ${totalPages}`;
      if (prev)  prev.disabled     = !data.has_prev;
      if (next)  next.disabled     = !data.has_next;
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="6">${OSM.emptyState('bi-exclamation-triangle', 'Error al consultar pedidos', OneStyleAPI.friendlyError(err))}</td></tr>`;
      OSM.handleError(err);
    }
  }

  async function openOrderDetail(idPedido) {
    let order = state.orders.items.find(o => Number(o.id_pedido) === Number(idPedido));
    if (!order) {
      try {
        const res = await OneStyleAPI.admin.orders.list({ page: 1, per_page: 50 });
        const list = (res && res.data && (res.data.items || res.data.pedidos)) || [];
        order = list.find(o => Number(o.id_pedido) === Number(idPedido));
      } catch (_) {}
    }
    if (!order) {
      OSM.toast.warning('No se encontró el detalle del pedido seleccionado.');
      return;
    }
    state.selectedOrder = order;
    renderOrderDrawer(order);
    if (orderDrawer) orderDrawer.show();
  }

  function renderOrderDrawer(order) {
    const titleEl = document.getElementById('admDrawerOrderCode');
    const badgeEl = document.getElementById('admDrawerOrderBadge');
    const bodyEl  = document.getElementById('admDrawerOrderBody');
    const footEl  = document.getElementById('admDrawerOrderFoot');
    if (!bodyEl || !footEl) return;

    const stage = Number(order.etapa_fsm ?? 1);
    const nextState = NEXT_STATE_BY_STAGE[stage] || null;
    const canCancel = stage === 1 || stage === 2;
    const desp = order.datos_despacho || {};

    if (titleEl) titleEl.textContent = `Pedido ${order.codigo_orden}`;
    if (badgeEl) badgeEl.innerHTML   = badgeForOrderState(order.estado, stage);

    const steps = [
      { step: 1, label: 'Registrado', icon: 'bi-receipt' },
      { step: 2, label: 'Confirmado', icon: 'bi-check-lg' },
      { step: 3, label: 'En Empaque', icon: 'bi-box-seam' },
      { step: 4, label: 'Despachado', icon: 'bi-truck' },
      { step: 5, label: 'Entregado',  icon: 'bi-bag-check' }
    ];

    const stepperHtml = stage === 0
      ? `<div class="adm-cancelled"><i class="bi bi-x-octagon me-2"></i>Pedido cancelado — el stock ha sido reintegrado automáticamente al inventario.</div>`
      : `<ol class="adm-stepper">
          ${steps.map(s => {
            const cls = s.step < stage ? 'done' : (s.step === stage ? 'current' : '');
            return `
              <li class="adm-step ${cls}">
                <div class="adm-step__dot"><i class="bi ${s.icon}"></i></div>
                <div>${OSM.esc(s.label)}</div>
              </li>`;
          }).join('')}
        </ol>`;

    const itemsHtml = (order.detalle_items || []).map(it => `
      <div class="adm-line">
        <div>
          <strong>${OSM.esc(it.nombre_producto)}</strong>
          <small>SKU: ${OSM.esc(it.sku || '—')} · ${OSM.esc(it.color)} / Talla ${OSM.esc(it.talla)} × ${Number(it.cantidad)}</small>
        </div>
        <div class="t-strong">${OSM.money(it.subtotal)}</div>
      </div>`).join('');

    const histHtml = (order.historial || []).map(h => `
      <li>
        <strong>${OSM.esc(h.estado)}</strong>
        <small>${OSM.formatDate(h.fecha)} — ${OSM.esc(h.motivo_cambio || 'Actualizado en OMS')}</small>
      </li>`).join('');

    bodyEl.innerHTML = `
      ${stepperHtml}

      <div class="adm-section-title">Datos de Envío y Contacto</div>
      <dl class="adm-kv">
        <dt>Destinatario</dt><dd>${OSM.esc(desp.nombre_receptor || '—')}</dd>
        <dt>Teléfono</dt><dd>${OSM.esc(desp.telefono || '—')}</dd>
        <dt>Correo</dt><dd>${OSM.esc(desp.email || '—')}</dd>
        <dt>Dirección</dt><dd>${OSM.esc(desp.direccion_envio || '—')}${desp.barrio ? ' (' + OSM.esc(desp.barrio) + ')' : ''}</dd>
        <dt>Ciudad</dt><dd>${OSM.esc(desp.ciudad || '—')}</dd>
        <dt>Notas</dt><dd>${OSM.esc(desp.observaciones || 'Sin observaciones')}</dd>
      </dl>

      <div class="adm-section-title">Prendas Consolidadas</div>
      <div>${itemsHtml || '<p class="text-muted small">Sin detalle de ítems.</p>'}</div>
      <div class="d-flex justify-content-between align-items-center pt-3 mt-1">
        <span class="text-uppercase small fw-semibold">Total del Pedido</span>
        <strong class="fs-5">${OSM.money(order.total)}</strong>
      </div>

      <div class="adm-section-title">Trazabilidad FSM</div>
      <ul class="adm-timeline">${histHtml || '<li><small>Sin historial adicional</small></li>'}</ul>
    `;

    const waMsg = `Hola ${desp.nombre_receptor || ''}, te contactamos de OneStyleMariana sobre tu pedido ${order.codigo_orden} por valor de ${OSM.money(order.total)}. Estado actual: ${order.estado}.`;
    const waHref = OSM.whatsappUrl(desp.telefono, waMsg);

    footEl.innerHTML = `
      ${waHref ? `<a href="${OSM.esc(waHref)}" target="_blank" rel="noopener noreferrer" class="osm-btn osm-btn--whatsapp"><i class="bi bi-whatsapp"></i> WhatsApp Cliente</a>` : ''}
      ${canCancel ? `<button type="button" class="osm-btn osm-btn--danger" data-adm-fsm="Cancelado"><i class="bi bi-x-circle"></i> Cancelar y Liberar Stock</button>` : ''}
      ${nextState ? `<button type="button" class="osm-btn osm-btn--gold" data-adm-fsm="${OSM.esc(nextState)}">Avanzar a ${OSM.esc(nextState)} <i class="bi bi-arrow-right"></i></button>` : ''}
    `;
  }

  async function executeOrderTransition(btn, nuevoEstado) {
    const order = state.selectedOrder;
    if (!order) return;

    if (nuevoEstado === 'Cancelado') {
      const ok = await OSM.confirm(
        `¿Confirmas la cancelación del pedido ${order.codigo_orden}? Las unidades descontadas se reintegrarán inmediatamente al inventario disponible.`,
        { title: 'Cancelar pedido y reintegrar stock', confirmText: 'Sí, cancelar pedido', danger: true }
      );
      if (!ok) return;
    }

    await OSM.run(btn, async () => {
      try {
        const res = await OneStyleAPI.admin.orders.transition(order.id_pedido, {
          nuevo_estado: nuevoEstado,
          motivo: `Actualizado en Panel OMS a ${nuevoEstado}`
        });
        OSM.toast.success(res.message || `Pedido actualizado a ${nuevoEstado}`);
        if (res.data) {
          state.selectedOrder = res.data;
          renderOrderDrawer(res.data);
        }
        await loadPedidos();
        await loadResumen();
        if (typeof window.syncCatalogFromBackend === 'function') {
          window.syncCatalogFromBackend();
        }
      } catch (err) {
        OSM.handleError(err, 'Transición no permitida');
      }
    }, 'Actualizando...');
  }

  /* =========================================================
     3. CATÁLOGO INTEGRADO EN SPA (#/admin/catalogo)
     ========================================================= */
  async function loadCatalogMetadata() {
    try {
      const user = OneStyleAPI.getSavedUser();
      const isAdmin = Boolean(user && user.rol === 'Administradora');
      const [catRes, attrRes] = await Promise.all([
        isAdmin ? OneStyleAPI.admin.catalog.categories() : OneStyleAPI.catalogo.categories(),
        isAdmin ? OneStyleAPI.admin.catalog.adminAttributes() : OneStyleAPI.catalogo.attributes()
      ]);
      state.categories = (catRes && Array.isArray(catRes.data)) ? catRes.data : [];
      state.attributes = (attrRes && attrRes.data) || { tallas: [], colores: [] };

      const filterCat = document.getElementById('admCatFilterCat');
      const modalCat  = document.getElementById('admProdCategoria');
      const activeCategories = state.categories.filter(c => c.estado !== false);
      if (filterCat) {
        const prevCat = filterCat.value;
        const allOpt = domEl('option', '', 'Todas las categorías');
        allOpt.value = '';
        const catOpts = state.categories.map(c => {
          const opt = domEl('option', '', c.nombre_categoria || c.slug || '');
          opt.value = c.slug || '';
          return opt;
        });
        filterCat.replaceChildren(allOpt, ...catOpts);
        if (prevCat) filterCat.value = prevCat;
      }
      if (modalCat) {
        const prevModalCat = modalCat.value;
        const modalOpts = activeCategories.map(c => {
          const opt = domEl('option', '', c.nombre_categoria || '');
          opt.value = String(Number(c.id_categoria));
          return opt;
        });
        modalCat.replaceChildren(...modalOpts);
        if (prevModalCat && activeCategories.some(c => String(c.id_categoria) === String(prevModalCat))) {
          modalCat.value = prevModalCat;
        }
      }
      populateEditProductCategories(
        state.selectedProductForEdit ? state.selectedProductForEdit.fk_id_categoria : null
      );

      const activeTallas = (state.attributes.tallas || []).filter(t => t.estado !== false);
      const tallaSel = document.getElementById('admVarTalla');
      const prodTallaSel = document.getElementById('admProdTalla');
      [tallaSel, prodTallaSel].forEach(sel => {
        if (!sel) return;
        const prevT = sel.value;
        const opts = activeTallas.map(t => {
          const opt = domEl('option', '', t.nombre_talla || t.codigo_talla || `Talla #${t.id_talla}`);
          opt.value = String(Number(t.id_talla));
          return opt;
        });
        sel.replaceChildren(...opts);
        if (prevT && activeTallas.some(t => String(t.id_talla) === String(prevT))) {
          sel.value = prevT;
        }
      });

      const activeColores = (state.attributes.colores || []).filter(c => c.estado !== false);
      const colorSel = document.getElementById('admVarColor');
      const prodColorSel = document.getElementById('admProdColor');
      [colorSel, prodColorSel].forEach(sel => {
        if (!sel) return;
        const prevC = sel.value;
        const opts = activeColores.map(c => {
          const opt = domEl('option', '', c.nombre_color || `Color #${c.id_color}`);
          opt.value = String(Number(c.id_color));
          return opt;
        });
        sel.replaceChildren(...opts);
        if (prevC && activeColores.some(c => String(c.id_color) === String(prevC))) {
          sel.value = prevC;
        }
      });
    } catch (_) {}
  }

  function renderTableMessageRow(tbody, colspan, iconClass, title, text) {
    if (!tbody) return;
    const tr = domEl('tr');
    const td = domEl('td');
    td.colSpan = colspan;
    const box = domEl('div', 'osm-empty');
    const icon = domEl('i', `bi ${iconClass}`);
    icon.setAttribute('aria-hidden', 'true');
    box.append(icon, domEl('strong', '', title), domEl('span', '', text));
    td.appendChild(box);
    tr.appendChild(td);
    tbody.replaceChildren(tr);
  }

  function populateEditProductCategories(selectedId = null) {
    const sel = document.getElementById('admEditProdCategoria');
    if (!sel) return;
    const activeCategories = state.categories.filter(c => c.estado !== false);
    const opts = activeCategories.map(c => {
      const opt = domEl('option', '', c.nombre_categoria || c.slug || `Categoría #${c.id_categoria}`);
      opt.value = String(Number(c.id_categoria));
      return opt;
    });
    sel.replaceChildren(...opts);
    if (selectedId !== null && selectedId !== undefined) {
      const match = activeCategories.find(c => Number(c.id_categoria) === Number(selectedId));
      if (match) sel.value = String(Number(selectedId));
    }
  }

  async function openEditProductModal(productId) {
    if (!state.categories.length) {
      await loadCatalogMetadata();
    }
    const product = state.catalog.items.find(p => Number(p.id_producto) === Number(productId));
    if (!product) {
      OSM.toast.warning('No se encontró la prenda seleccionada en el catálogo.');
      return;
    }
    state.selectedProductForEdit = product;

    const form = document.getElementById('admEditProductForm');
    const subtitle = document.getElementById('admEditProdSubtitle');
    if (subtitle) {
      subtitle.textContent = `Editando #${Number(product.id_producto)} — ${product.name || product.nombre_producto || product.nombre || ''}`;
    }
    if (form) {
      ['nombre_producto', 'descripcion_producto', 'fk_id_categoria', 'precio_detallista'].forEach(fname => {
        if (form.elements[fname]) OSM.field.clear(form.elements[fname]);
      });
      if (form.elements.nombre_producto) {
        form.elements.nombre_producto.value = product.nombre_producto || product.name || product.nombre || '';
      }
      if (form.elements.descripcion_producto) {
        form.elements.descripcion_producto.value = product.descripcion_producto || product.desc || product.descripcion || '';
      }
      if (form.elements.precio_detallista) {
        const currentPrice = product.precio_detallista ?? product.precio ?? product.price ?? '';
        form.elements.precio_detallista.value = currentPrice !== '' ? String(currentPrice) : '';
      }
      populateEditProductCategories(product.fk_id_categoria);
    }

    const galSection = document.getElementById('admEditGallerySection');
    const galInput   = document.getElementById('admEditGalleryInput');
    const galPending = document.getElementById('admEditGalleryPending');
    if (galInput) galInput.value = '';
    if (galPending) galPending.replaceChildren();
    state.gallery.pendingFiles = [];

    const user = OneStyleAPI.getSavedUser();
    const isAdmin = Boolean(user && user.rol === 'Administradora');
    if (galSection) galSection.classList.toggle('d-none', !isAdmin);
    if (isAdmin && typeof loadEditProductGallery === 'function') {
      loadEditProductGallery(product.id_producto);
    }

    if (editProductModal) editProductModal.show();
  }

  async function loadCatalogo() {
    const tbody = document.getElementById('admCatalogBody');
    const info  = document.getElementById('admCatalogPageInfo');
    const label = document.getElementById('admCatalogPageLabel');
    const prev  = document.getElementById('admCatalogPrev');
    const next  = document.getElementById('admCatalogNext');
    if (!tbody) return;

    tbody.innerHTML = OSM.skeletonRows(6, 5);

    try {
      const res = await OneStyleAPI.admin.catalog.products({
        page: state.catalog.page,
        per_page: state.catalog.per_page,
        q: state.catalog.q,
        categoria: state.catalog.categoria,
        estado: state.catalog.estado
      });
      const data = (res && res.data) || {};
      const items = Array.isArray(data.items) ? data.items : [];
      state.catalog.items = items;

      if (!items.length) {
        renderTableMessageRow(tbody, 6, 'bi-tags', 'Sin prendas para este filtro', 'Crea una nueva prenda o limpia los filtros de búsqueda.');
      } else {
        const frag = document.createDocumentFragment();
        items.forEach(p => {
          const idProd = Number(p.id_producto);
          const prodName = p.name || p.nombre_producto || p.nombre || '';
          const prodDesc = p.desc || p.descripcion_producto || p.descripcion || '';
          const varCount = Array.isArray(p.variantes) ? p.variantes.length : 0;
          const totalStock = Number(p.stock_total_disponible ?? 0);
          const isVis = Boolean(p.estado_visibilidad);

          const tr = domEl('tr');

          // Columna Prenda
          const tdProd = domEl('td');
          const cellWrap = domEl('div', 'adm-cell-product');
          const thumb = domEl('div', 'adm-thumb');
          const safeImg = p.img && !/^\s*(?:javascript|data):/i.test(String(p.img)) ? String(p.img) : null;
          if (safeImg) {
            const img = domEl('img');
            img.src = safeImg;
            img.alt = prodName || 'Prenda';
            thumb.appendChild(img);
          } else {
            const bagIcon = domEl('i', 'bi bi-bag');
            bagIcon.setAttribute('aria-hidden', 'true');
            thumb.appendChild(bagIcon);
          }
          const textCol = domEl('div');
          textCol.append(
            domEl('div', 't-strong', prodName),
            domEl('div', 't-muted', prodDesc)
          );
          cellWrap.append(thumb, textCol);
          tdProd.appendChild(cellWrap);

          // Columna Categoría
          const tdCat = domEl('td');
          tdCat.appendChild(domEl('span', 'osm-badge', p.nombre_categoria || p.cat || 'General'));

          // Columna Precio
          const tdPrice = domEl('td', 't-strong', OSM.money(p.price ?? p.precio_detallista ?? p.precio_base));

          // Columna Stock
          const tdStock = domEl('td');
          const stockBadgeCls = totalStock === 0 ? 'osm-badge--low' : (totalStock <= 3 ? 'osm-badge--Registrado' : 'osm-badge--ok');
          tdStock.appendChild(domEl('span', `osm-badge ${stockBadgeCls}`, `${totalStock} uds (${varCount} SKU)`));

          // Columna Visibilidad
          const tdVis = domEl('td');
          const visWrap = domEl('div', 'd-inline-flex align-items-center gap-2');
          const switchLbl = domEl('label', 'osm-switch');
          switchLbl.title = 'Cambiar visibilidad en tienda';
          const switchInput = domEl('input');
          switchInput.type = 'checkbox';
          switchInput.dataset.admVis = String(idProd);
          switchInput.checked = isVis;
          switchInput.setAttribute('aria-label', `Visibilidad de ${prodName}`);
          const switchTrack = domEl('span', 'osm-switch__track');
          switchTrack.setAttribute('aria-hidden', 'true');
          switchLbl.append(switchInput, switchTrack);
          visWrap.append(switchLbl, domEl('span', 't-muted', isVis ? 'Visible' : 'Oculto'));
          tdVis.appendChild(visWrap);

          // Columna Acciones (Editar + Variante SKU)
          const tdAct = domEl('td', 't-right');
          const actions = domEl('div', 'adm-actions');

          const editBtn = domEl('button', 'osm-btn osm-btn--sm osm-btn--primary');
          editBtn.type = 'button';
          editBtn.dataset.admEditProd = String(idProd);
          const editIcon = domEl('i', 'bi bi-pencil-square');
          editIcon.setAttribute('aria-hidden', 'true');
          editBtn.append(editIcon, domEl('span', '', 'Editar'));

          const addVarBtn = domEl('button', 'osm-btn osm-btn--sm');
          addVarBtn.type = 'button';
          addVarBtn.dataset.admAddVar = String(idProd);
          const varIcon = domEl('i', 'bi bi-plus-lg');
          varIcon.setAttribute('aria-hidden', 'true');
          addVarBtn.append(varIcon, domEl('span', '', 'Variante SKU'));

          actions.append(editBtn, addVarBtn);
          tdAct.appendChild(actions);

          tr.append(tdProd, tdCat, tdPrice, tdStock, tdVis, tdAct);
          frag.appendChild(tr);
        });
        tbody.replaceChildren(frag);
      }

      const page = Number(data.page || 1);
      const totalPages = Number(data.total_pages || 1);
      const total = Number(data.total ?? items.length);
      if (info)  info.textContent  = `Mostrando ${items.length} de ${total} prendas`;
      if (label) label.textContent = `Página ${page} de ${totalPages}`;
      if (prev)  prev.disabled     = !data.has_prev;
      if (next)  next.disabled     = !data.has_next;
    } catch (err) {
      renderTableMessageRow(tbody, 6, 'bi-exclamation-triangle', 'No se pudo cargar el catálogo', OneStyleAPI.friendlyError(err));
      OSM.handleError(err);
    }
  }

  /* =========================================================
     4. INVENTARIO Y AJUSTE DE STOCK POR SKU (#/admin/inventario)
     ========================================================= */
  async function loadInventario() {
    const tbody = document.getElementById('admInventoryBody');
    if (!tbody) return;
    tbody.innerHTML = OSM.skeletonRows(6, 6);

    try {
      const res = await OneStyleAPI.admin.catalog.products({ page: 1, per_page: 50 });
      const items = (res && res.data && res.data.items) || [];
      const variants = [];
      items.forEach(p => {
        (p.variantes || []).forEach(v => {
          variants.push({
            ...v,
            nombre_producto: p.name || p.nombre,
            categoria: p.nombre_categoria || p.cat
          });
        });
      });

      if (!variants.length) {
        tbody.innerHTML = `<tr><td colspan="6">${OSM.emptyState('bi-boxes', 'Sin variantes registradas', 'Agrega variantes de talla y color desde la pestaña Catálogo.')}</td></tr>`;
        return;
      }

      variants.sort((a, b) => Number(a.stock_disponible ?? 0) - Number(b.stock_disponible ?? 0));

      tbody.innerHTML = variants.map(v => {
        const disp = Number(v.stock_disponible ?? v.stock ?? 0);
        const fis  = Number(v.stock_fisico ?? v.stock ?? 0);
        const resv = Number(v.stock_reservado ?? 0);
        const badgeCls = disp === 0 ? 'osm-badge--low' : (disp <= 3 ? 'osm-badge--Registrado' : 'osm-badge--ok');
        return `
          <tr>
            <td class="t-strong">${OSM.esc(v.sku)}</td>
            <td>
              <div class="t-strong">${OSM.esc(v.nombre_producto)}</div>
              <div class="t-muted">${OSM.esc(v.color)} · Talla ${OSM.esc(v.talla)}</div>
            </td>
            <td class="t-strong">${OSM.money(v.precio)}</td>
            <td>${fis} físico <span class="t-muted">(${resv} reservado)</span></td>
            <td><span class="osm-badge ${badgeCls}">${disp} disponible</span></td>
            <td class="t-right">
              <div class="adm-stock-adjust justify-content-end">
                <input type="number" min="0" class="osm-input" value="${fis}" data-stock-input="${Number(v.id_variante)}" aria-label="Nuevo stock físico para ${OSM.esc(v.sku)}">
                <button type="button" class="osm-btn osm-btn--sm osm-btn--primary" data-stock-save="${Number(v.id_variante)}">
                  Guardar
                </button>
              </div>
            </td>
          </tr>`;
      }).join('');
    } catch (err) {
      tbody.innerHTML = `<tr><td colspan="6">${OSM.emptyState('bi-exclamation-triangle', 'Error al cargar inventario', OneStyleAPI.friendlyError(err))}</td></tr>`;
      OSM.handleError(err);
    }
  }

  /* =========================================================
     5. PERFIL DE LA ADMINISTRADORA Y CAMBIO DE CONTRASEÑA
     ========================================================= */
  async function loadPerfil() {
    try {
      const res = await OneStyleAPI.auth.getProfile();
      const u = (res && res.data) || OneStyleAPI.getSavedUser() || {};
      const form = document.getElementById('admProfileForm');
      if (form) {
        form.elements.nombre.value   = u.nombre || '';
        form.elements.apellido.value = u.apellido || '';
        form.elements.email.value    = u.email || '';
        form.elements.telefono.value = u.telefono || '';
      }
      updateSidebarIdentity();
    } catch (err) {
      OSM.handleError(err);
    }
  }

  /* =========================================================
     5B. SOPORTE (TICKETS FSM) Y AUDITORÍA INMUTABLE
     ========================================================= */
  function badgeClassForTicketState(estado) {
    if (estado === 'RESUELTO') return 'osm-badge osm-badge--RESUELTO';
    if (estado === 'EN_PROCESO') return 'osm-badge osm-badge--EN_PROCESO';
    return 'osm-badge osm-badge--ABIERTO';
  }

  function renderTicketsTable(tickets) {
    const tbody = document.getElementById('admTicketsBody');
    if (!tbody) return;

    if (!Array.isArray(tickets) || !tickets.length) {
      const tr = domEl('tr');
      const td = domEl('td', 't-muted text-center py-4', 'No hay tickets de soporte para el filtro seleccionado.');
      td.colSpan = 6;
      tr.appendChild(td);
      tbody.replaceChildren(tr);
      return;
    }

    const frag = document.createDocumentFragment();
    tickets.forEach(t => {
      const tr = domEl('tr');

      const tdId = domEl('td');
      tdId.append(
        domEl('div', 't-strong', `#${Number(t.id_ticket)}`),
        domEl('div', 't-muted', OSM.formatDate(t.created_at))
      );

      const tdClient = domEl('td');
      tdClient.append(
        domEl('div', 't-strong', t.nombre || 'Clienta'),
        domEl('div', 't-muted', t.contacto || '—')
      );

      const tdSubject = domEl('td');
      const subjDiv = domEl('div', 'text-truncate adm-cell-truncate', t.asunto || 'Sin asunto');
      subjDiv.title = String(t.asunto || '');
      tdSubject.appendChild(subjDiv);

      const tdOrder = domEl('td', 't-muted', t.codigo_orden || '—');

      const tdState = domEl('td');
      tdState.appendChild(domEl('span', badgeClassForTicketState(t.estado), t.estado || 'ABIERTO'));

      const tdAct = domEl('td', 't-right');
      const openBtn = domEl('button', 'osm-btn osm-btn--sm osm-btn--primary');
      openBtn.type = 'button';
      openBtn.dataset.admOpenTicket = String(Number(t.id_ticket));
      const icon = domEl('i', 'bi bi-chat-square-text');
      icon.setAttribute('aria-hidden', 'true');
      const txt = domEl('span', '', 'Responder / Estado');
      openBtn.append(icon, txt);
      tdAct.appendChild(openBtn);

      tr.append(tdId, tdClient, tdSubject, tdOrder, tdState, tdAct);
      frag.appendChild(tr);
    });

    tbody.replaceChildren(frag);
  }

  async function loadSoporteTickets() {
    const tbody = document.getElementById('admTicketsBody');
    if (!tbody) return;
    tbody.innerHTML = OSM.skeletonRows(6, 4);

    try {
      const params = {};
      if (state.support.estado && TICKET_ALLOWED_STATES.includes(state.support.estado)) {
        params.estado = state.support.estado;
      }
      const res = await OneStyleAPI.admin.support.tickets(params);
      const data = (res && res.data) || {};
      const items = Array.isArray(data.items) ? data.items : [];
      state.support.items = items;
      updateTicketsBadge(Number(data.tickets_abiertos ?? 0));
      renderTicketsTable(items);
    } catch (err) {
      const tr = domEl('tr');
      const td = domEl('td', 'text-danger text-center py-4');
      td.colSpan = 6;
      td.textContent = (err && (err.status === 401 || err.status === 403))
        ? 'Acceso restringido: solo Administradora puede gestionar tickets.'
        : OneStyleAPI.friendlyError(err);
      tr.appendChild(td);
      tbody.replaceChildren(tr);
    }
  }

  function openTicketDrawer(ticketId) {
    const ticket = state.support.items.find(t => Number(t.id_ticket) === Number(ticketId));
    if (!ticket) return;
    state.support.selectedTicket = ticket;

    const titleEl = document.getElementById('admDrawerTicketTitle');
    const badgeEl = document.getElementById('admDrawerTicketBadge');
    const bodyEl  = document.getElementById('admDrawerTicketBody');
    const replyInput = document.getElementById('admTicketReplyText');
    const transBtn   = document.getElementById('admTicketTransitionBtn');
    const publishBtn = document.getElementById('admTicketPublishFaqBtn');

    if (titleEl) titleEl.textContent = `Ticket #${Number(ticket.id_ticket)}`;
    if (badgeEl) {
      const badgeSpan = domEl('span', badgeClassForTicketState(ticket.estado), ticket.estado || 'ABIERTO');
      badgeEl.replaceChildren(badgeSpan);
    }

    if (bodyEl) {
      const frag = document.createDocumentFragment();
      frag.appendChild(domEl('h3', 'adm-section-title mt-0', 'Datos de la Solicitud'));

      const kv = domEl('dl', 'adm-kv mb-3');
      const pairs = [
        ['Clienta', ticket.nombre || '—'],
        ['Contacto', ticket.contacto || '—'],
        ['Orden', ticket.codigo_orden || 'Sin orden asociada'],
        ['Fecha', OSM.formatDate(ticket.created_at)],
        ['Asunto', ticket.asunto || '—']
      ];
      pairs.forEach(([k, v]) => {
        kv.append(domEl('dt', '', k), domEl('dd', '', v));
      });
      frag.appendChild(kv);

      frag.appendChild(domEl('h3', 'adm-section-title', 'Mensaje del Cliente'));
      frag.appendChild(domEl('p', 'adm-ticket-msg', ticket.mensaje || ''));

      if (ticket.respuesta_soporte) {
        frag.appendChild(domEl('h3', 'adm-section-title', 'Respuesta Registrada'));
        frag.appendChild(domEl('p', 'adm-ticket-reply-box', ticket.respuesta_soporte));
      }

      bodyEl.replaceChildren(frag);
    }

    if (replyInput) replyInput.value = ticket.respuesta_soporte || '';

    if (transBtn) {
      const nextState = TICKET_NEXT_STATE[ticket.estado];
      if (nextState) {
        transBtn.classList.remove('d-none');
        transBtn.disabled = false;
        transBtn.dataset.nextState = nextState;
        transBtn.textContent = nextState === 'EN_PROCESO'
          ? 'Pasar a En Proceso'
          : 'Marcar como Resuelto';
      } else {
        transBtn.classList.add('d-none');
        transBtn.disabled = true;
        delete transBtn.dataset.nextState;
      }
    }

    if (publishBtn) {
      const canPublish = ticket.estado === 'RESUELTO' && Boolean(String(ticket.respuesta_soporte || '').trim());
      publishBtn.classList.toggle('d-none', !canPublish);
      publishBtn.disabled = !canPublish;
    }

    if (ticketDrawer) ticketDrawer.show();
  }

  async function submitTicketUpdate(btnEl, { nextState = null, requireReply = false } = {}) {
    const current = state.support.selectedTicket;
    if (!current) return;

    const replyEl = document.getElementById('admTicketReplyText');
    const cleanReply = OSM.clean(replyEl ? replyEl.value : '');
    const payload = {};

    if (nextState) {
      const expected = TICKET_NEXT_STATE[current.estado];
      if (nextState !== expected) {
        OSM.toast.warning(`Transición inválida: ${current.estado} -> ${nextState}.`);
        return;
      }
      payload.estado = nextState;
    }

    if (requireReply && !cleanReply) {
      OSM.toast.warning('Escribe una respuesta antes de guardar.');
      if (replyEl) replyEl.focus();
      return;
    }
    if (cleanReply) {
      payload.respuesta = cleanReply;
    }

    await OSM.run(btnEl, async () => {
      try {
        const res = await OneStyleAPI.admin.support.updateTicket(current.id_ticket, payload);
        const updated = res && res.data && res.data.ticket ? res.data.ticket : null;
        if (updated) {
          const idx = state.support.items.findIndex(t => Number(t.id_ticket) === Number(updated.id_ticket));
          if (idx >= 0) state.support.items[idx] = updated;
          else state.support.items.unshift(updated);
          state.support.selectedTicket = updated;
        }
        if (res && res.data && res.data.tickets_abiertos !== undefined) {
          updateTicketsBadge(res.data.tickets_abiertos);
        }
        const visibleList = state.support.estado
          ? state.support.items.filter(t => t.estado === state.support.estado)
          : state.support.items;
        renderTicketsTable(visibleList);
        openTicketDrawer(current.id_ticket);
        if (state.activePanel === 'soporte') loadAuditLogs();
        OSM.toast.success(res.message || 'Ticket actualizado.');
      } catch (err) {
        OSM.handleError(err, 'No se pudo actualizar el ticket');
      }
    }, 'Guardando...');
  }

  function populateAuditSelect(selectEl, defaultLabel, values) {
    if (!selectEl) return;
    const prevVal = selectEl.value;
    const opts = [domEl('option', '', defaultLabel)];
    opts[0].value = '';
    values.forEach(val => {
      const opt = domEl('option', '', val);
      opt.value = val;
      opts.push(opt);
    });
    selectEl.replaceChildren(...opts);
    if (values.includes(prevVal)) selectEl.value = prevVal;
  }

  function getFilteredAuditItems() {
    const q = state.audit.q.toLowerCase();
    const tablaFilter = state.audit.tabla.toLowerCase();
    const accionFilter = state.audit.accion.toLowerCase();
    const dateFrom = state.audit.fecha_inicio;
    const dateTo = state.audit.fecha_fin;

    return state.audit.items.filter(log => {
      if (tablaFilter && String(log.tabla_afectada || '').toLowerCase() !== tablaFilter) return false;
      if (accionFilter && String(log.tipo_accion || '').toLowerCase() !== accionFilter) return false;
      const isoDay = String(log.fecha_accion || log.fecha || '').slice(0, 10);
      if (dateFrom && (!isoDay || isoDay < dateFrom)) return false;
      if (dateTo && (!isoDay || isoDay > dateTo)) return false;
      if (q) {
        const hay = [
          log.usuario_nombre,
          log.usuario_email,
          log.usuario_id,
          log.tipo_accion,
          log.tabla_afectada,
          log.ip_address,
          log.user_agent,
          log.valor_anterior,
          log.valor_nuevo,
          log.id_registro_afectado
        ].map(v => String(v ?? '').toLowerCase()).join(' ');
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }

  function renderAuditTable() {
    const tbody = document.getElementById('admAuditBody');
    if (!tbody) return;

    const filtered = getFilteredAuditItems();

    if (!filtered.length) {
      const tr = domEl('tr');
      const td = domEl('td', 't-muted text-center py-4', 'No hay registros de auditoría que coincidan con el filtro.');
      td.colSpan = 6;
      tr.appendChild(td);
      tbody.replaceChildren(tr);
      return;
    }

    const frag = document.createDocumentFragment();
    filtered.forEach(log => {
      const tr = domEl('tr');

      const tdDate = domEl('td', 't-muted', OSM.formatDate(log.fecha_accion || log.fecha));

      const tdUser = domEl('td');
      tdUser.append(
        domEl('div', 't-strong', log.usuario_nombre || `Usuario #${log.usuario_id ?? 'Sistema'}`),
        domEl('div', 't-muted', log.usuario_email || `ID ${log.usuario_id ?? '—'}`)
      );

      const tdAct = domEl('td');
      tdAct.appendChild(domEl('span', 'osm-badge osm-badge--info', log.tipo_accion || 'EVENTO'));

      const tdNet = domEl('td');
      tdNet.appendChild(domEl('div', 't-strong', log.ip_address || '—'));
      const uaEl = domEl('div', 't-muted adm-audit-ua', log.user_agent || '—');
      if (log.user_agent) uaEl.title = String(log.user_agent);
      tdNet.appendChild(uaEl);

      const entText = log.id_registro_afectado !== null && log.id_registro_afectado !== undefined
        ? `${log.tabla_afectada || 'sistema'} #${log.id_registro_afectado}`
        : (log.tabla_afectada || 'sistema');
      const tdEnt = domEl('td', '', entText);

      const prevText = log.valor_anterior !== null && log.valor_anterior !== undefined ? String(log.valor_anterior) : '—';
      const nextText = log.valor_nuevo !== null && log.valor_nuevo !== undefined ? String(log.valor_nuevo) : '—';
      const tdDiff = domEl('td');
      tdDiff.appendChild(domEl('div', 'adm-audit-diff', `${prevText} → ${nextText}`));

      tr.append(tdDate, tdUser, tdAct, tdNet, tdEnt, tdDiff);
      frag.appendChild(tr);
    });

    tbody.replaceChildren(frag);
  }

  async function loadAuditLogs() {
    const tbody = document.getElementById('admAuditBody');
    if (!tbody) return;
    if (state.audit.fecha_inicio && state.audit.fecha_fin && state.audit.fecha_inicio > state.audit.fecha_fin) {
      OSM.toast.warning('La fecha de inicio de auditoría no puede ser mayor que la fecha fin.');
      return;
    }

    tbody.innerHTML = OSM.skeletonRows(6, 4);

    try {
      const params = {};
      if (state.audit.fecha_inicio) params.fecha_inicio = state.audit.fecha_inicio;
      if (state.audit.fecha_fin) params.fecha_fin = state.audit.fecha_fin;
      const res = await OneStyleAPI.admin.audit.list(params);
      const logs = (res && Array.isArray(res.data)) ? res.data : [];
      state.audit.items = logs;

      const tables = Array.from(new Set(logs.map(l => String(l.tabla_afectada || '').trim()).filter(Boolean))).sort();
      const actions = Array.from(new Set(logs.map(l => String(l.tipo_accion || '').trim()).filter(Boolean))).sort();
      populateAuditSelect(document.getElementById('admAuditTableFilter'), 'Todas las entidades', tables);
      populateAuditSelect(document.getElementById('admAuditActionFilter'), 'Todas las acciones', actions);

      renderAuditTable();
    } catch (err) {
      const tr = domEl('tr');
      const td = domEl('td', 'text-danger text-center py-4');
      td.colSpan = 6;
      td.textContent = (err && (err.status === 401 || err.status === 403))
        ? 'Acceso exclusivo de Administradora para logs de auditoría.'
        : OneStyleAPI.friendlyError(err);
      tr.appendChild(td);
      tbody.replaceChildren(tr);
    }
  }

  function exportAuditCsv() {
    if (state.audit.fecha_inicio && state.audit.fecha_fin && state.audit.fecha_inicio > state.audit.fecha_fin) {
      OSM.toast.warning('La fecha de inicio de auditoría no puede ser mayor que la fecha fin.');
      return;
    }
    const items = getFilteredAuditItems();
    if (!items.length) {
      OSM.toast.warning('No hay registros de auditoría filtrados para exportar.');
      return;
    }
    const headers = [
      'ID Log',
      'Fecha y Hora',
      'Usuario',
      'Correo',
      'Accion',
      'IP',
      'Dispositivo (User-Agent)',
      'Tabla Afectada',
      'ID Registro',
      'Valor Anterior',
      'Valor Nuevo'
    ];
    const rows = items.map(log => [
      log.id_log ?? '',
      log.fecha_accion || log.fecha || '',
      log.usuario_nombre || `Usuario #${log.usuario_id ?? 'Sistema'}`,
      log.usuario_email || '',
      log.tipo_accion || '',
      log.ip_address || '',
      log.user_agent || '',
      log.tabla_afectada || '',
      log.id_registro_afectado !== null && log.id_registro_afectado !== undefined ? log.id_registro_afectado : '',
      log.valor_anterior !== null && log.valor_anterior !== undefined ? log.valor_anterior : '',
      log.valor_nuevo !== null && log.valor_nuevo !== undefined ? log.valor_nuevo : ''
    ]);
    OSM.csv.download('auditoria_onestyle.csv', headers, rows);
    OSM.toast.success(`CSV exportado (${items.length} registro(s)).`);
  }

  function setSoporteSubTab(tabName = 'tickets') {
    const showAudit = tabName === 'auditoria';
    const ticketsPane = document.getElementById('admSoporteTabTickets');
    const auditPane   = document.getElementById('admSoporteTabAuditoria');
    if (ticketsPane) ticketsPane.classList.toggle('d-none', showAudit);
    if (auditPane)   auditPane.classList.toggle('d-none', !showAudit);

    document.querySelectorAll('#admSoporteTabs [data-soporte-tab]').forEach(btn => {
      const active = btn.dataset.soporteTab === (showAudit ? 'auditoria' : 'tickets');
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-selected', String(active));
    });

    if (showAudit) loadAuditLogs();
  }

  /* =========================================================
     5C. GESTIÓN DE PERSONAL OPERATIVO (RF-SEG-012 A RF-SEG-015)
     ========================================================= */
  function renderStaffTable() {
    const tbody = document.getElementById('admStaffBody');
    if (!tbody) return;

    const allItems = Array.isArray(state.staff.items) ? state.staff.items : [];
    const activeAdminsCount = allItems.filter(
      u => u.rol === 'Administradora' && u.estado_usuario !== false
    ).length;
    const me = OneStyleAPI.getSavedUser();

    const q = state.staff.q.toLowerCase();
    const roleFilter = state.staff.rol;
    const filtered = allItems.filter(u => {
      if (roleFilter && u.rol !== roleFilter) return false;
      if (q) {
        const hay = [u.nombre, u.apellido, u.email, u.telefono, u.rol]
          .map(v => String(v ?? '').toLowerCase())
          .join(' ');
        if (!hay.includes(q)) return false;
      }
      return true;
    });

    if (!filtered.length) {
      renderTableMessageRow(tbody, 5, 'bi-people', 'Sin personal para mostrar', 'Registra un miembro operativo o ajusta los filtros.');
      return;
    }

    const frag = document.createDocumentFragment();
    filtered.forEach(u => {
      const uid = Number(u.id_usuario);
      const isSelf = Boolean(me && Number(me.id_usuario) === uid);
      const isActive = u.estado_usuario !== false;
      const isAdmin = u.rol === 'Administradora';
      const nextRole = isAdmin ? 'Vendedora' : 'Administradora';
      const isLastActiveAdmin = isAdmin && isActive && activeAdminsCount <= 1;

      const tr = domEl('tr');

      // 1. Nombre + indicador sesión propia + teléfono
      const tdName = domEl('td');
      const nameRow = domEl('div', 't-strong');
      nameRow.appendChild(document.createTextNode(`${u.nombre || ''} ${u.apellido || ''}`.trim() || 'Sin nombre'));
      if (isSelf) {
        nameRow.appendChild(domEl('span', 'osm-badge osm-badge--info adm-self-tag', 'Tú'));
      }
      tdName.append(nameRow, domEl('div', 't-muted', u.telefono || 'Sin teléfono'));

      // 2. Correo
      const tdEmail = domEl('td', '', u.email || '—');

      // 3. Rol
      const tdRole = domEl('td');
      tdRole.appendChild(domEl('span', `osm-badge ${isAdmin ? 'osm-badge--gold' : 'osm-badge--neutral'}`, u.rol || 'Vendedora'));

      // 4. Estado activo/inactivo
      const tdState = domEl('td');
      tdState.appendChild(
        domEl('span', `osm-badge ${isActive ? 'osm-badge--success' : 'osm-badge--danger'}`, isActive ? 'Activo' : 'Inactivo')
      );

      // 5. Acciones (Cambio de rol y Baja lógica / Reactivación con protección anti auto-bloqueo)
      const tdAct = domEl('td', 't-right');
      const actions = domEl('div', 'adm-actions');

      const roleLocked = isLastActiveAdmin;
      const roleBtn = domEl('button', `osm-btn osm-btn--sm${roleLocked ? ' adm-btn-locked' : ''}`);
      roleBtn.type = 'button';
      roleBtn.dataset.admStaffRole = String(uid);
      roleBtn.dataset.targetRole = nextRole;
      roleBtn.disabled = roleLocked;
      roleBtn.title = roleLocked
        ? 'Debe existir al menos una Administradora activa en el sistema.'
        : `Cambiar rol a ${nextRole}`;
      const roleIcon = domEl('i', 'bi bi-arrow-left-right');
      roleIcon.setAttribute('aria-hidden', 'true');
      roleBtn.append(roleIcon, domEl('span', '', `Pasar a ${nextRole}`));

      const stateLocked = isSelf || (isActive && isLastActiveAdmin);
      const nextActive = !isActive;
      const stateBtnCls = isActive
        ? `osm-btn osm-btn--sm ${stateLocked ? 'adm-btn-locked' : 'osm-btn--danger'}`
        : 'osm-btn osm-btn--sm osm-btn--primary';
      const stateBtn = domEl('button', stateBtnCls);
      stateBtn.type = 'button';
      stateBtn.dataset.admStaffToggle = String(uid);
      stateBtn.dataset.targetActive = String(nextActive);
      stateBtn.disabled = stateLocked;
      if (isSelf) {
        stateBtn.title = 'No puedes desactivar tu propia cuenta mientras tienes sesión iniciada.';
      } else if (stateLocked) {
        stateBtn.title = 'No se puede desactivar la última Administradora activa.';
      } else {
        stateBtn.title = isActive ? 'Aplicar baja lógica' : 'Reactivar acceso operativo';
      }
      const stateIcon = domEl('i', `bi ${isActive ? 'bi-person-slash' : 'bi-person-check'}`);
      stateIcon.setAttribute('aria-hidden', 'true');
      stateBtn.append(stateIcon, domEl('span', '', isActive ? 'Dar de baja' : 'Reactivar'));

      actions.append(roleBtn, stateBtn);
      tdAct.appendChild(actions);

      tr.append(tdName, tdEmail, tdRole, tdState, tdAct);
      frag.appendChild(tr);
    });

    tbody.replaceChildren(frag);
  }

  async function loadPersonal() {
    const tbody = document.getElementById('admStaffBody');
    if (!tbody) return;
    tbody.innerHTML = OSM.skeletonRows(5, 4);

    try {
      const res = await OneStyleAPI.admin.staff.list();
      state.staff.items = (res && Array.isArray(res.data)) ? res.data : [];
      renderStaffTable();
    } catch (err) {
      const msg = (err && (err.status === 401 || err.status === 403))
        ? 'Acceso exclusivo del rol Administradora.'
        : OneStyleAPI.friendlyError(err);
      renderTableMessageRow(tbody, 5, 'bi-shield-lock', 'No se pudo consultar el equipo', msg);
    }
  }

  async function handleStaffRoleChange(btnEl, targetId, nextRole) {
    const member = state.staff.items.find(u => Number(u.id_usuario) === Number(targetId));
    if (!member) return;
    if (!['Administradora', 'Vendedora'].includes(nextRole)) return;

    const fullName = `${member.nombre || ''} ${member.apellido || ''}`.trim() || member.email;
    const confirmed = await OSM.confirm(
      `¿Confirmas cambiar el rol de ${fullName} de "${member.rol}" a "${nextRole}"?`,
      { title: 'Cambiar rol de personal', confirmText: `Cambiar a ${nextRole}`, danger: nextRole === 'Vendedora' }
    );
    if (!confirmed) return;

    await OSM.run(btnEl, async () => {
      try {
        const res = await OneStyleAPI.admin.staff.update(targetId, { rol: nextRole });
        OSM.toast.success(res.message || `Rol actualizado a ${nextRole}.`);
        await loadPersonal();
      } catch (err) {
        OSM.handleError(err, 'No se pudo actualizar el rol');
      }
    }, 'Guardando...');
  }

  async function handleStaffStateToggle(btnEl, targetId, activar) {
    const member = state.staff.items.find(u => Number(u.id_usuario) === Number(targetId));
    if (!member) return;

    const fullName = `${member.nombre || ''} ${member.apellido || ''}`.trim() || member.email;
    const confirmed = await OSM.confirm(
      activar
        ? `¿Confirmas reactivar el acceso operativo para ${fullName}?`
        : `¿Confirmas aplicar baja lógica a ${fullName}? Se cerrarán sus sesiones activas sin eliminar su historial.`,
      {
        title: activar ? 'Reactivar personal operativo' : 'Aplicar baja lógica',
        confirmText: activar ? 'Sí, reactivar' : 'Sí, dar de baja',
        danger: !activar
      }
    );
    if (!confirmed) return;

    await OSM.run(btnEl, async () => {
      try {
        const res = await OneStyleAPI.admin.staff.setState(targetId, activar);
        OSM.toast.success(res.message || (activar ? 'Usuario reactivado.' : 'Baja lógica aplicada.'));
        await loadPersonal();
      } catch (err) {
        OSM.handleError(err, 'No se pudo cambiar el estado del usuario');
      }
    }, 'Aplicando...');
  }

  /* =========================================================
     5D. GESTIÓN DE FAQs Y CONVERSIÓN DE TICKETS (RF-FAQ-005..010)
     ========================================================= */
  function populateFaqCategorySelects() {
    const filterSel = document.getElementById('admFaqCatFilter');
    const modalSel  = document.getElementById('admFaqCategoria');
    const cats = Array.isArray(state.faqs.categories) ? state.faqs.categories : [];

    if (filterSel) {
      const prev = filterSel.value;
      const allOpt = domEl('option', '', 'Todas las categorías');
      allOpt.value = '';
      const opts = cats.map(c => {
        const o = domEl('option', '', c.nombre || `Categoría #${c.id_categoria}`);
        o.value = String(Number(c.id_categoria));
        return o;
      });
      filterSel.replaceChildren(allOpt, ...opts);
      if (prev) filterSel.value = prev;
    }

    if (modalSel) {
      const prevM = modalSel.value;
      const opts = cats.map(c => {
        const o = domEl('option', '', c.nombre || `Categoría #${c.id_categoria}`);
        o.value = String(Number(c.id_categoria));
        return o;
      });
      modalSel.replaceChildren(...opts);
      if (prevM && cats.some(c => String(c.id_categoria) === String(prevM))) {
        modalSel.value = prevM;
      }
    }
  }

  async function loadFaqCategories() {
    try {
      const res = await OneStyleAPI.admin.faqs.categories();
      state.faqs.categories = (res && Array.isArray(res.data)) ? res.data : [];
      populateFaqCategorySelects();
    } catch (_) {}
  }

  function nextOrderForFaqCategory(catId) {
    const numCat = Number(catId || 1);
    const sameCat = state.faqs.items.filter(f => Number(f.id_categoria) === numCat);
    const maxOrd = sameCat.reduce((mx, f) => Math.max(mx, Number(f.orden || 0)), 0);
    return maxOrd + 1;
  }

  function renderFaqsTable() {
    const tbody = document.getElementById('admFaqsBody');
    if (!tbody) return;

    const allItems = Array.isArray(state.faqs.items) ? state.faqs.items : [];
    const byCatSorted = new Map();
    allItems.forEach(f => {
      const cid = Number(f.id_categoria);
      if (!byCatSorted.has(cid)) byCatSorted.set(cid, []);
      byCatSorted.get(cid).push(f);
    });
    byCatSorted.forEach(list => list.sort((a, b) => Number(a.orden) - Number(b.orden)));

    const q = state.faqs.q.toLowerCase();
    const catFilter = state.faqs.cat;
    const stateFilter = state.faqs.estado;

    const filtered = allItems.filter(f => {
      if (catFilter && String(f.id_categoria) !== String(catFilter)) return false;
      if (stateFilter && String(f.estado || '').toLowerCase() !== stateFilter) return false;
      if (q) {
        const hay = [f.pregunta, f.respuesta, f.categoria]
          .map(v => String(v ?? '').toLowerCase())
          .join(' ');
        if (!hay.includes(q)) return false;
      }
      return true;
    }).sort((a, b) => (Number(a.id_categoria) - Number(b.id_categoria)) || (Number(a.orden) - Number(b.orden)));

    if (!filtered.length) {
      renderTableMessageRow(tbody, 5, 'bi-question-circle', 'Sin FAQs para mostrar', 'Crea una nueva pregunta frecuente o limpia los filtros.');
      return;
    }

    const frag = document.createDocumentFragment();
    filtered.forEach(f => {
      const fid = Number(f.id_faq);
      const isActive = f.estado !== 'inactivo';
      const siblings = byCatSorted.get(Number(f.id_categoria)) || [];
      const pos = siblings.findIndex(s => Number(s.id_faq) === fid);
      const prevSib = pos > 0 ? siblings[pos - 1] : null;
      const nextSib = (pos >= 0 && pos < siblings.length - 1) ? siblings[pos + 1] : null;

      const tr = domEl('tr');

      // 1. Orden y flechas de prioridad
      const tdOrd = domEl('td');
      const ordWrap = domEl('div', 'adm-faq-order');

      const upBtn = domEl('button', 'osm-btn osm-btn--sm');
      upBtn.type = 'button';
      upBtn.dataset.admFaqMove = 'up';
      upBtn.dataset.faqId = String(fid);
      upBtn.dataset.targetOrden = prevSib ? String(Number(prevSib.orden)) : '';
      upBtn.disabled = !prevSib;
      upBtn.title = 'Subir prioridad en su categoría';
      upBtn.setAttribute('aria-label', `Subir orden de FAQ #${fid}`);
      const upIcon = domEl('i', 'bi bi-arrow-up');
      upIcon.setAttribute('aria-hidden', 'true');
      upBtn.appendChild(upIcon);

      const downBtn = domEl('button', 'osm-btn osm-btn--sm');
      downBtn.type = 'button';
      downBtn.dataset.admFaqMove = 'down';
      downBtn.dataset.faqId = String(fid);
      downBtn.dataset.targetOrden = nextSib ? String(Number(nextSib.orden)) : '';
      downBtn.disabled = !nextSib;
      downBtn.title = 'Bajar prioridad en su categoría';
      downBtn.setAttribute('aria-label', `Bajar orden de FAQ #${fid}`);
      const downIcon = domEl('i', 'bi bi-arrow-down');
      downIcon.setAttribute('aria-hidden', 'true');
      downBtn.appendChild(downIcon);

      ordWrap.append(domEl('span', 'osm-badge osm-badge--neutral', `#${Number(f.orden)}`), upBtn, downBtn);
      tdOrd.appendChild(ordWrap);

      // 2. Pregunta y Respuesta
      const tdContent = domEl('td');
      tdContent.append(
        domEl('div', 't-strong', f.pregunta || ''),
        domEl('div', 't-muted', f.respuesta || '')
      );

      // 3. Categoría
      const tdCat = domEl('td');
      tdCat.appendChild(domEl('span', 'osm-badge', f.categoria || `Cat #${f.id_categoria}`));

      // 4. Estado
      const tdState = domEl('td');
      tdState.appendChild(
        domEl('span', `osm-badge ${isActive ? 'osm-badge--success' : 'osm-badge--danger'}`, isActive ? 'Activa' : 'Inactiva')
      );

      // 5. Acciones
      const tdAct = domEl('td', 't-right');
      const actions = domEl('div', 'adm-actions');

      const editBtn = domEl('button', 'osm-btn osm-btn--sm osm-btn--primary');
      editBtn.type = 'button';
      editBtn.dataset.admFaqEdit = String(fid);
      const editIcon = domEl('i', 'bi bi-pencil-square');
      editIcon.setAttribute('aria-hidden', 'true');
      editBtn.append(editIcon, domEl('span', '', 'Editar'));

      const nextState = isActive ? 'inactivo' : 'activo';
      const toggleBtn = domEl('button', `osm-btn osm-btn--sm ${isActive ? 'osm-btn--danger' : ''}`);
      toggleBtn.type = 'button';
      toggleBtn.dataset.admFaqToggle = String(fid);
      toggleBtn.dataset.targetEstado = nextState;
      const tIcon = domEl('i', `bi ${isActive ? 'bi-eye-slash' : 'bi-eye'}`);
      tIcon.setAttribute('aria-hidden', 'true');
      toggleBtn.append(tIcon, domEl('span', '', isActive ? 'Desactivar' : 'Activar'));

      actions.append(editBtn, toggleBtn);
      tdAct.appendChild(actions);

      tr.append(tdOrd, tdContent, tdCat, tdState, tdAct);
      frag.appendChild(tr);
    });

    tbody.replaceChildren(frag);
  }

  async function loadFaqsAdmin() {
    const tbody = document.getElementById('admFaqsBody');
    if (!tbody) return;
    tbody.innerHTML = OSM.skeletonRows(5, 4);

    try {
      if (!state.faqs.categories.length) {
        await loadFaqCategories();
      }
      const res = await OneStyleAPI.admin.faqs.list();
      state.faqs.items = (res && Array.isArray(res.data)) ? res.data : [];
      renderFaqsTable();
    } catch (err) {
      const msg = (err && (err.status === 401 || err.status === 403))
        ? 'Acceso exclusivo del rol Administradora.'
        : OneStyleAPI.friendlyError(err);
      renderTableMessageRow(tbody, 5, 'bi-shield-lock', 'No se pudieron cargar las FAQs', msg);
    }
  }

  async function openFaqModal({ mode = 'create', faq = null, fromTicket = null } = {}) {
    if (!state.faqs.categories.length) {
      await loadFaqCategories();
    }
    const form = document.getElementById('admFaqForm');
    const titleEl = document.getElementById('admFaqModalTitle');
    const privacyEl = document.getElementById('admFaqPrivacyNotice');
    const saveBtn = document.getElementById('admSaveFaqBtn');

    if (form) {
      ['pregunta', 'id_categoria', 'orden', 'respuesta'].forEach(fname => {
        if (form.elements[fname]) OSM.field.clear(form.elements[fname]);
      });
    }

    const isEdit = mode === 'edit' && Boolean(faq);
    state.faqs.editingId = isEdit ? Number(faq.id_faq) : null;

    if (titleEl) {
      if (isEdit) titleEl.textContent = `Editar FAQ #${Number(faq.id_faq)}`;
      else if (fromTicket) titleEl.textContent = 'Convertir Ticket en FAQ Pública';
      else titleEl.textContent = 'Nueva Pregunta Frecuente';
    }
    if (saveBtn) {
      saveBtn.textContent = isEdit ? 'Guardar Cambios' : 'Guardar FAQ';
    }
    if (privacyEl) {
      privacyEl.classList.toggle('d-none', !fromTicket);
    }

    if (form) {
      populateFaqCategorySelects();
      const defaultCatId = state.faqs.categories[0] ? Number(state.faqs.categories[0].id_categoria) : 1;

      if (isEdit) {
        if (form.elements.pregunta) form.elements.pregunta.value = faq.pregunta || '';
        if (form.elements.id_categoria) form.elements.id_categoria.value = String(Number(faq.id_categoria || defaultCatId));
        if (form.elements.orden) form.elements.orden.value = String(Number(faq.orden || 1));
        if (form.elements.respuesta) form.elements.respuesta.value = faq.respuesta || '';
      } else if (fromTicket) {
        const asunto = String(fromTicket.asunto || '').trim();
        const mensaje = String(fromTicket.mensaje || '').trim();
        const draftQ = (asunto && mensaje) ? `${asunto} — ${mensaje}` : (asunto || mensaje);
        if (form.elements.pregunta) form.elements.pregunta.value = draftQ;
        if (form.elements.id_categoria) form.elements.id_categoria.value = String(defaultCatId);
        if (form.elements.orden) form.elements.orden.value = String(nextOrderForFaqCategory(defaultCatId));
        if (form.elements.respuesta) form.elements.respuesta.value = String(fromTicket.respuesta_soporte || '').trim();
      } else {
        form.reset();
        if (form.elements.id_categoria) form.elements.id_categoria.value = String(defaultCatId);
        if (form.elements.orden) form.elements.orden.value = String(nextOrderForFaqCategory(defaultCatId));
      }
    }

    if (faqModal) faqModal.show();
  }

  function refreshHelpFaqsView() {
    if (typeof window.loadFaqsPublicas === 'function') {
      window.loadFaqsPublicas();
    }
  }

  async function handleFaqReorder(btnEl, faqId, targetOrden) {
    if (!targetOrden || targetOrden < 1) return;
    await OSM.run(btnEl, async () => {
      try {
        const res = await OneStyleAPI.admin.faqs.reorder(faqId, targetOrden);
        if (res && res.data && Array.isArray(res.data.items)) {
          state.faqs.items = res.data.items;
          renderFaqsTable();
        } else {
          await loadFaqsAdmin();
        }
        refreshHelpFaqsView();
        OSM.toast.success(res.message || 'Orden actualizado.');
      } catch (err) {
        OSM.handleError(err, 'No se pudo reordenar la FAQ');
      }
    }, '...');
  }

  async function handleFaqToggleState(btnEl, faqId, nextEstado) {
    const faq = state.faqs.items.find(f => Number(f.id_faq) === Number(faqId));
    if (!faq) return;
    const isDeactivating = nextEstado === 'inactivo';
    const confirmed = await OSM.confirm(
      isDeactivating
        ? `¿Deseas desactivar la FAQ "${faq.pregunta}"? Dejará de mostrarse en #/ayuda.`
        : `¿Deseas activar nuevamente la FAQ "${faq.pregunta}" para mostrarla en #/ayuda?`,
      {
        title: isDeactivating ? 'Desactivar FAQ' : 'Activar FAQ',
        confirmText: isDeactivating ? 'Sí, desactivar' : 'Sí, activar',
        danger: isDeactivating
      }
    );
    if (!confirmed) return;

    await OSM.run(btnEl, async () => {
      try {
        const res = await OneStyleAPI.admin.faqs.setState(faqId, nextEstado);
        OSM.toast.success(res.message || 'Estado de FAQ actualizado.');
        await loadFaqsAdmin();
        refreshHelpFaqsView();
      } catch (err) {
        OSM.handleError(err, 'No se pudo cambiar el estado de la FAQ');
      }
    }, '...');
  }

  /* =========================================================
     5E. REPORTES POR VENDEDORA Y EXPORTACIÓN CSV (RF-PED-004)
     ========================================================= */
  function validateReportDateRange() {
    if (state.reports.fecha_inicio && state.reports.fecha_fin && state.reports.fecha_inicio > state.reports.fecha_fin) {
      OSM.toast.warning('La fecha de inicio no puede ser mayor que la fecha fin.');
      return false;
    }
    return true;
  }

  function renderReportsTable() {
    const tbody = document.getElementById('admReportsBody');
    const ordKpi = document.getElementById('admRepTotalOrders');
    const revKpi = document.getElementById('admRepTotalRevenue');
    const selKpi = document.getElementById('admRepSellersCount');
    const d = state.reports.data || {};
    const sellers = Array.isArray(d.resumen_vendedoras) ? d.resumen_vendedoras : [];

    if (ordKpi) ordKpi.textContent = String(Number(d.total_pedidos || 0));
    if (revKpi) revKpi.textContent = OSM.money(Number(d.ingresos_totales || 0));
    if (selKpi) selKpi.textContent = String(sellers.length);

    if (!tbody) return;
    if (!sellers.length) {
      renderTableMessageRow(tbody, 6, 'bi-bar-chart-line', 'Sin ventas para el rango elegido', 'Ajusta las fechas o el estado de pedido para consultar otro periodo.');
      return;
    }

    const frag = document.createDocumentFragment();
    sellers.forEach(s => {
      const tr = domEl('tr');
      const isAct = s.estado_usuario !== false;

      const tdName = domEl('td', 't-strong', s.nombre || `Vendedora #${s.vendedora_id}`);
      const tdContact = domEl('td');
      tdContact.append(
        domEl('div', '', s.email || '—'),
        domEl('div', 't-muted', s.rol || 'Vendedora')
      );

      const tdState = domEl('td');
      tdState.appendChild(
        domEl('span', `osm-badge ${isAct ? 'osm-badge--success' : 'osm-badge--danger'}`, isAct ? 'Activo' : 'Inactivo')
      );

      const tdCount = domEl('td');
      tdCount.appendChild(domEl('div', 't-strong', `${Number(s.cantidad_pedidos || 0)} pedido(s)`));
      if (Number(s.pedidos_cancelados || 0) > 0) {
        tdCount.appendChild(domEl('div', 't-muted', `${Number(s.pedidos_cancelados)} cancelado(s)`));
      }

      const tdTotal = domEl('td', 't-strong', OSM.money(Number(s.total_vendido || 0)));

      const estPairs = Object.entries(s.por_estado || {}).map(([k, v]) => `${k}: ${v}`).join(' · ') || '—';
      const tdBreak = domEl('td', 't-muted', estPairs);

      tr.append(tdName, tdContact, tdState, tdCount, tdTotal, tdBreak);
      frag.appendChild(tr);
    });

    tbody.replaceChildren(frag);
  }

  async function loadReportesVendedoras() {
    const tbody = document.getElementById('admReportsBody');
    if (!validateReportDateRange()) return;
    if (tbody) tbody.innerHTML = OSM.skeletonRows(6, 4);

    try {
      const params = {};
      if (state.reports.fecha_inicio) params.fecha_inicio = state.reports.fecha_inicio;
      if (state.reports.fecha_fin) params.fecha_fin = state.reports.fecha_fin;
      if (state.reports.estado) params.estado = state.reports.estado;
      const res = await OneStyleAPI.admin.reports.sellers(params);
      state.reports.data = (res && res.data) || { total_pedidos: 0, ingresos_totales: 0, resumen_vendedoras: [] };
      renderReportsTable();
    } catch (err) {
      state.reports.data = null;
      const msg = (err && (err.status === 401 || err.status === 403))
        ? 'Acceso exclusivo del rol Administradora.'
        : OneStyleAPI.friendlyError(err);
      if (tbody) renderTableMessageRow(tbody, 6, 'bi-shield-lock', 'No se pudo cargar el reporte', msg);
    }
  }

  function exportReportsCsv() {
    if (!validateReportDateRange()) return;
    const sellers = (state.reports.data && Array.isArray(state.reports.data.resumen_vendedoras))
      ? state.reports.data.resumen_vendedoras
      : [];
    if (!sellers.length) {
      OSM.toast.warning('No hay registros de vendedoras en el periodo actual para exportar.');
      return;
    }
    const headers = [
      'ID Vendedora',
      'Nombre',
      'Correo',
      'Rol',
      'Estado Cuenta',
      'Cantidad Pedidos',
      'Pedidos Cancelados',
      'Total Vendido (COP)',
      'Detalle por Estado'
    ];
    const rows = sellers.map(s => [
      s.vendedora_id,
      s.nombre || '',
      s.email || '',
      s.rol || '',
      s.estado_cuenta || (s.estado_usuario !== false ? 'Activo' : 'Inactivo'),
      Number(s.cantidad_pedidos || 0),
      Number(s.pedidos_cancelados || 0),
      Number(s.total_vendido || 0),
      Object.entries(s.por_estado || {}).map(([k, v]) => `${k}: ${v}`).join('; ')
    ]);
    OSM.csv.download('reporte_vendedoras.csv', headers, rows);
    OSM.toast.success(`Reporte CSV exportado (${sellers.length} fila(s)).`);
  }

  /* =========================================================
     5F. CATÁLOGOS MAESTROS (CATEGORÍAS, TALLAS Y COLORES)
     ========================================================= */
  async function refreshAllCatalogConsumers() {
    await loadCatalogMetadata();
    if (state.activePanel === 'catalogo') await loadCatalogo();
    if (typeof window.syncCatalogFromBackend === 'function') window.syncCatalogFromBackend();
  }

  function setMaestrosSubTab(tabName = 'categorias') {
    const allowed = ['categorias', 'tallas', 'colores'];
    const target = allowed.includes(tabName) ? tabName : 'categorias';
    state.masters.tab = target;

    const panes = {
      categorias: document.getElementById('admMaestrosTabCategorias'),
      tallas: document.getElementById('admMaestrosTabTallas'),
      colores: document.getElementById('admMaestrosTabColores')
    };
    Object.entries(panes).forEach(([k, el]) => {
      if (el) el.classList.toggle('d-none', k !== target);
    });

    document.querySelectorAll('#admMaestrosTabs [data-maestro-tab]').forEach(btn => {
      const act = btn.dataset.maestroTab === target;
      btn.classList.toggle('active', act);
      btn.setAttribute('aria-selected', String(act));
    });
  }

  function renderMasterCatsTable() {
    const tbody = document.getElementById('admMasterCatsBody');
    if (!tbody) return;
    const cats = Array.isArray(state.masters.categories) ? state.masters.categories : [];
    if (!cats.length) {
      renderTableMessageRow(tbody, 5, 'bi-tags', 'Sin categorías registradas', 'Crea la primera categoría maestra.');
      return;
    }

    const frag = document.createDocumentFragment();
    cats.forEach(c => {
      const cid = Number(c.id_categoria);
      const isAct = c.estado !== false;
      const vinculados = Number(c.total_productos_vinculados ?? c.total_productos ?? 0);

      const tr = domEl('tr');
      tr.appendChild(domEl('td', 't-strong', c.nombre_categoria || ''));
      tr.appendChild(domEl('td', 't-muted', c.descripcion_categoria || '—'));
      tr.appendChild(domEl('td', '', `${vinculados} prenda(s)`));

      const tdState = domEl('td');
      tdState.appendChild(domEl('span', `osm-badge ${isAct ? 'osm-badge--success' : 'osm-badge--danger'}`, isAct ? 'Activa' : 'Inactiva'));
      tr.appendChild(tdState);

      const tdAct = domEl('td', 't-right');
      const acts = domEl('div', 'adm-actions');

      const editBtn = domEl('button', 'osm-btn osm-btn--sm osm-btn--primary');
      editBtn.type = 'button';
      editBtn.dataset.admCatEdit = String(cid);
      editBtn.append(domEl('i', 'bi bi-pencil-square'), domEl('span', '', 'Editar'));

      const toggleBtn = domEl('button', 'osm-btn osm-btn--sm');
      toggleBtn.type = 'button';
      toggleBtn.dataset.admCatToggle = String(cid);
      toggleBtn.dataset.targetEstado = String(!isAct);
      toggleBtn.appendChild(domEl('span', '', isAct ? 'Desactivar' : 'Activar'));

      const delBtn = domEl('button', `osm-btn osm-btn--sm ${vinculados > 0 ? 'adm-btn-locked' : 'osm-btn--danger'}`);
      delBtn.type = 'button';
      delBtn.dataset.admCatDel = String(cid);
      delBtn.title = vinculados > 0 ? 'Tiene prendas vinculadas (devolverá 409 o desactívala primero).' : 'Eliminar categoría';
      delBtn.append(domEl('i', 'bi bi-trash'), domEl('span', '', 'Eliminar'));

      acts.append(editBtn, toggleBtn, delBtn);
      tdAct.appendChild(acts);
      tr.appendChild(tdAct);
      frag.appendChild(tr);
    });
    tbody.replaceChildren(frag);
  }

  function renderMasterSizesTable() {
    const tbody = document.getElementById('admMasterSizesBody');
    if (!tbody) return;
    const tallas = Array.isArray(state.masters.tallas) ? state.masters.tallas : [];
    if (!tallas.length) {
      renderTableMessageRow(tbody, 4, 'bi-rulers', 'Sin tallas registradas', 'Crea la primera talla maestra.');
      return;
    }

    const frag = document.createDocumentFragment();
    tallas.forEach(t => {
      const tid = Number(t.id_talla);
      const isAct = t.estado !== false;
      const totalVars = Number(t.total_variantes ?? 0);

      const tr = domEl('tr');
      tr.appendChild(domEl('td', 't-strong', t.nombre_talla || ''));
      tr.appendChild(domEl('td', '', `${totalVars} variante(s)`));

      const tdState = domEl('td');
      tdState.appendChild(domEl('span', `osm-badge ${isAct ? 'osm-badge--success' : 'osm-badge--danger'}`, isAct ? 'Activa' : 'Inactiva'));
      tr.appendChild(tdState);

      const tdAct = domEl('td', 't-right');
      const acts = domEl('div', 'adm-actions');

      const editBtn = domEl('button', 'osm-btn osm-btn--sm osm-btn--primary');
      editBtn.type = 'button';
      editBtn.dataset.admSizeEdit = String(tid);
      editBtn.append(domEl('i', 'bi bi-pencil-square'), domEl('span', '', 'Editar'));

      const toggleBtn = domEl('button', 'osm-btn osm-btn--sm');
      toggleBtn.type = 'button';
      toggleBtn.dataset.admSizeToggle = String(tid);
      toggleBtn.dataset.targetEstado = String(!isAct);
      toggleBtn.appendChild(domEl('span', '', isAct ? 'Desactivar' : 'Activar'));

      const delBtn = domEl('button', `osm-btn osm-btn--sm ${totalVars > 0 ? 'adm-btn-locked' : 'osm-btn--danger'}`);
      delBtn.type = 'button';
      delBtn.dataset.admSizeDel = String(tid);
      delBtn.append(domEl('i', 'bi bi-trash'), domEl('span', '', 'Eliminar'));

      acts.append(editBtn, toggleBtn, delBtn);
      tdAct.appendChild(acts);
      tr.appendChild(tdAct);
      frag.appendChild(tr);
    });
    tbody.replaceChildren(frag);
  }

  function renderMasterColorsTable() {
    const tbody = document.getElementById('admMasterColorsBody');
    if (!tbody) return;
    const colores = Array.isArray(state.masters.colores) ? state.masters.colores : [];
    if (!colores.length) {
      renderTableMessageRow(tbody, 5, 'bi-palette', 'Sin colores registrados', 'Crea el primer color maestro.');
      return;
    }

    const frag = document.createDocumentFragment();
    colores.forEach(c => {
      const cid = Number(c.id_color);
      const isAct = c.estado !== false;
      const totalVars = Number(c.total_variantes ?? 0);
      const hex = /^#[0-9A-Fa-f]{6}$/.test(String(c.codigo_hex || '')) ? String(c.codigo_hex).toUpperCase() : '#17140F';

      const tr = domEl('tr');
      tr.appendChild(domEl('td', 't-strong', c.nombre_color || ''));

      const tdHex = domEl('td');
      const hexWrap = domEl('div', 'd-inline-flex align-items-center gap-2');
      const swatch = domEl('input', 'adm-color-swatch');
      swatch.type = 'color';
      swatch.value = hex;
      swatch.disabled = true;
      swatch.setAttribute('aria-label', `Tono ${c.nombre_color || hex}`);
      hexWrap.append(swatch, domEl('span', 't-muted', hex));
      tdHex.appendChild(hexWrap);
      tr.appendChild(tdHex);

      tr.appendChild(domEl('td', '', `${totalVars} variante(s)`));

      const tdState = domEl('td');
      tdState.appendChild(domEl('span', `osm-badge ${isAct ? 'osm-badge--success' : 'osm-badge--danger'}`, isAct ? 'Activo' : 'Inactivo'));
      tr.appendChild(tdState);

      const tdAct = domEl('td', 't-right');
      const acts = domEl('div', 'adm-actions');

      const editBtn = domEl('button', 'osm-btn osm-btn--sm osm-btn--primary');
      editBtn.type = 'button';
      editBtn.dataset.admColorEdit = String(cid);
      editBtn.append(domEl('i', 'bi bi-pencil-square'), domEl('span', '', 'Editar'));

      const toggleBtn = domEl('button', 'osm-btn osm-btn--sm');
      toggleBtn.type = 'button';
      toggleBtn.dataset.admColorToggle = String(cid);
      toggleBtn.dataset.targetEstado = String(!isAct);
      toggleBtn.appendChild(domEl('span', '', isAct ? 'Desactivar' : 'Activar'));

      const delBtn = domEl('button', `osm-btn osm-btn--sm ${totalVars > 0 ? 'adm-btn-locked' : 'osm-btn--danger'}`);
      delBtn.type = 'button';
      delBtn.dataset.admColorDel = String(cid);
      delBtn.append(domEl('i', 'bi bi-trash'), domEl('span', '', 'Eliminar'));

      acts.append(editBtn, toggleBtn, delBtn);
      tdAct.appendChild(acts);
      tr.appendChild(tdAct);
      frag.appendChild(tr);
    });
    tbody.replaceChildren(frag);
  }

  async function loadMaestros() {
    try {
      const [catsRes, attrRes] = await Promise.all([
        OneStyleAPI.admin.catalog.categories(),
        OneStyleAPI.admin.catalog.adminAttributes()
      ]);
      state.masters.categories = (catsRes && Array.isArray(catsRes.data)) ? catsRes.data : [];
      const attrData = (attrRes && attrRes.data) || {};
      state.masters.tallas = Array.isArray(attrData.tallas) ? attrData.tallas : [];
      state.masters.colores = Array.isArray(attrData.colores) ? attrData.colores : [];
      renderMasterCatsTable();
      renderMasterSizesTable();
      renderMasterColorsTable();
    } catch (err) {
      OSM.handleError(err, 'No se pudieron cargar los catálogos maestros');
    }
  }

  function openMasterCatModal(cat = null) {
    state.masters.editingCatId = cat ? Number(cat.id_categoria) : null;
    const form = document.getElementById('admMasterCatForm');
    const title = document.getElementById('admMasterCatModalTitle');
    if (title) title.textContent = cat ? `Editar Categoría #${Number(cat.id_categoria)}` : 'Nueva Categoría';
    if (form) {
      ['nombre_categoria', 'descripcion_categoria'].forEach(f => {
        if (form.elements[f]) OSM.field.clear(form.elements[f]);
      });
      if (cat) {
        form.elements.nombre_categoria.value = cat.nombre_categoria || '';
        form.elements.descripcion_categoria.value = cat.descripcion_categoria || '';
      } else {
        form.reset();
      }
    }
    if (masterCatModal) masterCatModal.show();
  }

  function openMasterSizeModal(size = null) {
    state.masters.editingSizeId = size ? Number(size.id_talla) : null;
    const form = document.getElementById('admMasterSizeForm');
    const title = document.getElementById('admMasterSizeModalTitle');
    if (title) title.textContent = size ? `Editar Talla #${Number(size.id_talla)}` : 'Nueva Talla';
    if (form) {
      if (form.elements.nombre_talla) OSM.field.clear(form.elements.nombre_talla);
      if (size) form.elements.nombre_talla.value = size.nombre_talla || '';
      else form.reset();
    }
    if (masterSizeModal) masterSizeModal.show();
  }

  function openMasterColorModal(color = null) {
    state.masters.editingColorId = color ? Number(color.id_color) : null;
    const form = document.getElementById('admMasterColorForm');
    const title = document.getElementById('admMasterColorModalTitle');
    const picker = document.getElementById('admColorHexPicker');
    if (title) title.textContent = color ? `Editar Color #${Number(color.id_color)}` : 'Nuevo Color';
    if (form) {
      ['nombre_color', 'codigo_hex'].forEach(f => {
        if (form.elements[f]) OSM.field.clear(form.elements[f]);
      });
      const hex = color && /^#[0-9A-Fa-f]{6}$/.test(String(color.codigo_hex || ''))
        ? String(color.codigo_hex).toUpperCase()
        : '#17140F';
      if (color) {
        form.elements.nombre_color.value = color.nombre_color || '';
        form.elements.codigo_hex.value = hex;
      } else {
        form.reset();
        form.elements.codigo_hex.value = hex;
      }
      if (picker) picker.value = hex;
    }
    if (masterColorModal) masterColorModal.show();
  }

  /* =========================================================
     5G. GESTOR DE GALERÍA 1..N POR PRENDA (RF-CAT-017)
     ========================================================= */
  function validateClientImageFiles(fileList) {
    const allowedExt = /\.(jpe?g|png|webp)$/i;
    const maxBytes = 5 * 1024 * 1024;
    const accepted = [];
    Array.from(fileList || []).forEach(file => {
      if (!file || !file.name) return;
      if (!allowedExt.test(file.name)) {
        OSM.toast.warning(`Archivo "${file.name}" rechazado: usa JPG, JPEG, PNG o WEBP.`);
        return;
      }
      if (Number(file.size || 0) > maxBytes) {
        OSM.toast.warning(`"${file.name}" supera el límite de 5 MB.`);
        return;
      }
      accepted.push(file);
    });
    return accepted;
  }

  function renderFilePreviewStrip(files, previewEl) {
    if (!previewEl) return;
    if (!files || !files.length) {
      previewEl.replaceChildren();
      return;
    }
    const nodes = files.map(file => {
      const img = domEl('img', 'adm-gallery-preview-img');
      img.alt = file.name || 'Vista previa';
      if (typeof FileReader !== 'undefined') {
        const reader = new FileReader();
        reader.onload = ev => {
          if (ev && ev.target && typeof ev.target.result === 'string') {
            img.src = ev.target.result;
          }
        };
        reader.readAsDataURL(file);
      }
      return img;
    });
    previewEl.replaceChildren(...nodes);
  }

  function renderEditGalleryGrid() {
    const grid = document.getElementById('admEditGalleryList');
    if (!grid) return;
    const imgs = Array.isArray(state.gallery.items) ? state.gallery.items : [];
    const prod = state.selectedProductForEdit;
    const prodName = prod ? (prod.nombre_producto || prod.name || 'Prenda') : 'Prenda';

    if (!imgs.length) {
      const empty = domEl('p', 'text-muted small mb-0', 'Esta prenda aún no tiene imágenes en su galería.');
      grid.replaceChildren(empty);
      return;
    }

    const sorted = [...imgs].sort((a, b) => Number(a.orden || 0) - Number(b.orden || 0));
    const cards = sorted.map((im, idx) => {
      const card = domEl('div', `adm-gallery-card${im.es_principal ? ' is-principal' : ''}`);
      const thumb = domEl('img', 'adm-gallery-thumb');
      const safeSrc = im.url_imagen && !/^\s*(?:javascript|data):/i.test(String(im.url_imagen)) ? String(im.url_imagen) : '';
      if (safeSrc) thumb.src = safeSrc;
      thumb.alt = `${prodName} - imagen ${idx + 1}`;
      thumb.loading = 'lazy';

      const meta = domEl('div', 'd-flex justify-content-between align-items-center');
      meta.appendChild(domEl('span', 'osm-badge osm-badge--neutral', `#${idx + 1} · ${im.formato || 'IMG'}`));
      if (im.es_principal) {
        meta.appendChild(domEl('span', 'osm-badge osm-badge--gold', 'Portada'));
      }

      const controls = domEl('div', 'd-flex flex-wrap gap-1');

      if (!im.es_principal) {
        const starBtn = domEl('button', 'osm-btn osm-btn--sm osm-btn--gold');
        starBtn.type = 'button';
        starBtn.dataset.admImgPrincipal = String(Number(im.id_imagen));
        starBtn.title = 'Definir como imagen principal';
        starBtn.appendChild(domEl('span', '', 'Portada'));
        controls.appendChild(starBtn);
      }

      const upBtn = domEl('button', 'osm-btn osm-btn--sm');
      upBtn.type = 'button';
      upBtn.dataset.admImgMove = 'up';
      upBtn.dataset.imgId = String(Number(im.id_imagen));
      upBtn.disabled = idx === 0;
      upBtn.setAttribute('aria-label', `Mover imagen ${idx + 1} arriba`);
      upBtn.appendChild(domEl('i', 'bi bi-arrow-left'));

      const downBtn = domEl('button', 'osm-btn osm-btn--sm');
      downBtn.type = 'button';
      downBtn.dataset.admImgMove = 'down';
      downBtn.dataset.imgId = String(Number(im.id_imagen));
      downBtn.disabled = idx === sorted.length - 1;
      downBtn.setAttribute('aria-label', `Mover imagen ${idx + 1} abajo`);
      downBtn.appendChild(domEl('i', 'bi bi-arrow-right'));

      const delBtn = domEl('button', 'osm-btn osm-btn--sm osm-btn--danger ms-auto');
      delBtn.type = 'button';
      delBtn.dataset.admImgDel = String(Number(im.id_imagen));
      delBtn.setAttribute('aria-label', `Eliminar imagen ${idx + 1}`);
      delBtn.appendChild(domEl('i', 'bi bi-trash'));

      controls.append(upBtn, downBtn, delBtn);
      card.append(thumb, meta, controls);
      return card;
    });

    grid.replaceChildren(...cards);
  }

  async function loadEditProductGallery(productId) {
    const grid = document.getElementById('admEditGalleryList');
    if (grid) grid.replaceChildren(domEl('p', 'text-muted small mb-0', 'Cargando galería...'));
    try {
      const res = await OneStyleAPI.admin.catalog.listImages(productId);
      const data = (res && res.data) || {};
      state.gallery.items = Array.isArray(data.imagenes) ? data.imagenes : [];
      renderEditGalleryGrid();
    } catch (err) {
      state.gallery.items = [];
      if (grid) grid.replaceChildren(domEl('p', 'text-danger small mb-0', OneStyleAPI.friendlyError(err)));
    }
  }

  async function uploadPendingEditGalleryImages(btnEl) {
    const prod = state.selectedProductForEdit;
    if (!prod) return;
    const files = state.gallery.pendingFiles;
    if (!files || !files.length) {
      OSM.toast.warning('Selecciona una o más imágenes válidas antes de subir.');
      return;
    }
    const fd = new FormData();
    files.forEach(f => fd.append('imagenes', f));

    await OSM.run(btnEl, async () => {
      try {
        const res = await OneStyleAPI.admin.catalog.uploadImages(prod.id_producto, fd);
        const data = (res && res.data) || {};
        state.gallery.items = Array.isArray(data.imagenes) ? data.imagenes : [];
        state.gallery.pendingFiles = [];
        const input = document.getElementById('admEditGalleryInput');
        const pending = document.getElementById('admEditGalleryPending');
        if (input) input.value = '';
        if (pending) pending.replaceChildren();
        renderEditGalleryGrid();
        OSM.toast.success(res.message || 'Imágenes subidas a la galería.');
        await loadCatalogo();
        if (typeof window.syncCatalogFromBackend === 'function') window.syncCatalogFromBackend();
      } catch (err) {
        OSM.handleError(err, 'No se pudieron subir las imágenes');
      }
    }, 'Subiendo...');
  }

  async function handleGalleryMove(btnEl, imgId, direction) {
    const prod = state.selectedProductForEdit;
    if (!prod) return;
    const sorted = [...state.gallery.items].sort((a, b) => Number(a.orden || 0) - Number(b.orden || 0));
    const ids = sorted.map(i => Number(i.id_imagen));
    const idx = ids.indexOf(Number(imgId));
    const swapIdx = direction === 'up' ? idx - 1 : idx + 1;
    if (idx < 0 || swapIdx < 0 || swapIdx >= ids.length) return;
    [ids[idx], ids[swapIdx]] = [ids[swapIdx], ids[idx]];

    await OSM.run(btnEl, async () => {
      try {
        const res = await OneStyleAPI.admin.catalog.reorderImages(prod.id_producto, ids);
        state.gallery.items = (res && res.data && Array.isArray(res.data.imagenes)) ? res.data.imagenes : [];
        renderEditGalleryGrid();
        OSM.toast.success('Orden de galería actualizado.');
        if (typeof window.syncCatalogFromBackend === 'function') window.syncCatalogFromBackend();
      } catch (err) {
        OSM.handleError(err, 'No se pudo reordenar la galería');
      }
    }, '...');
  }

  async function handleGallerySetPrincipal(btnEl, imgId) {
    const prod = state.selectedProductForEdit;
    if (!prod) return;
    await OSM.run(btnEl, async () => {
      try {
        const res = await OneStyleAPI.admin.catalog.setPrincipalImage(prod.id_producto, imgId);
        state.gallery.items = (res && res.data && Array.isArray(res.data.imagenes)) ? res.data.imagenes : [];
        renderEditGalleryGrid();
        OSM.toast.success(res.message || 'Imagen principal actualizada.');
        await loadCatalogo();
        if (typeof window.syncCatalogFromBackend === 'function') window.syncCatalogFromBackend();
      } catch (err) {
        OSM.handleError(err, 'No se pudo actualizar la imagen principal');
      }
    }, '...');
  }

  async function handleGalleryDeleteImage(btnEl, imgId) {
    const prod = state.selectedProductForEdit;
    if (!prod) return;
    const ok = await OSM.confirm(
      '¿Eliminar esta imagen de la galería de la prenda?',
      { title: 'Eliminar imagen', confirmText: 'Sí, eliminar', danger: true }
    );
    if (!ok) return;

    await OSM.run(btnEl, async () => {
      try {
        const res = await OneStyleAPI.admin.catalog.deleteImage(prod.id_producto, imgId);
        state.gallery.items = (res && res.data && Array.isArray(res.data.imagenes)) ? res.data.imagenes : [];
        renderEditGalleryGrid();
        OSM.toast.success(res.message || 'Imagen eliminada.');
        await loadCatalogo();
        if (typeof window.syncCatalogFromBackend === 'function') window.syncCatalogFromBackend();
      } catch (err) {
        OSM.handleError(err, 'No se pudo eliminar la imagen');
      }
    }, '...');
  }

  /* =========================================================
     6. EVENTOS Y NAVEGACIÓN INTERNA DEL PANEL
     ========================================================= */
  function bindEvents() {
    if (state.initialized) return;
    state.initialized = true;

    const drawerEl = document.getElementById('admOrderDrawer');
    if (drawerEl) orderDrawer = new bootstrap.Offcanvas(drawerEl);

    const ticketDrawerEl = document.getElementById('admTicketDrawer');
    if (ticketDrawerEl) ticketDrawer = new bootstrap.Offcanvas(ticketDrawerEl);

    const prodModalEl = document.getElementById('admProductModal');
    if (prodModalEl) productModal = new bootstrap.Modal(prodModalEl);

    const editProdModalEl = document.getElementById('admEditProductModal');
    if (editProdModalEl) editProductModal = new bootstrap.Modal(editProdModalEl);

    const varModalEl = document.getElementById('admVariantModal');
    if (varModalEl) variantModal = new bootstrap.Modal(varModalEl);

    const staffModalEl = document.getElementById('admStaffModal');
    if (staffModalEl) staffModal = new bootstrap.Modal(staffModalEl);

    const faqModalEl = document.getElementById('admFaqModal');
    if (faqModalEl) faqModal = new bootstrap.Modal(faqModalEl);

    const masterCatModalEl = document.getElementById('admMasterCatModal');
    if (masterCatModalEl) masterCatModal = new bootstrap.Modal(masterCatModalEl);

    const masterSizeModalEl = document.getElementById('admMasterSizeModal');
    if (masterSizeModalEl) masterSizeModal = new bootstrap.Modal(masterSizeModalEl);

    const masterColorModalEl = document.getElementById('admMasterColorModal');
    if (masterColorModalEl) masterColorModal = new bootstrap.Modal(masterColorModalEl);

    // Filtros y búsqueda con debounce en Pedidos
    const orderSearch = document.getElementById('admOrderSearch');
    if (orderSearch) {
      orderSearch.addEventListener('input', OSM.debounce(() => {
        state.orders.q = OSM.clean(orderSearch.value);
        state.orders.page = 1;
        loadPedidos();
      }, 300));
    }

    const orderStateSel = document.getElementById('admOrderStateFilter');
    if (orderStateSel) {
      orderStateSel.addEventListener('change', () => {
        state.orders.estado = orderStateSel.value;
        state.orders.page = 1;
        loadPedidos();
      });
    }

    const ordPrev = document.getElementById('admOrdersPrev');
    const ordNext = document.getElementById('admOrdersNext');
    if (ordPrev) ordPrev.addEventListener('click', () => { if (state.orders.page > 1) { state.orders.page--; loadPedidos(); } });
    if (ordNext) ordNext.addEventListener('click', () => { state.orders.page++; loadPedidos(); });

    // Filtros y búsqueda en Catálogo
    const catSearch = document.getElementById('admCatSearch');
    if (catSearch) {
      catSearch.addEventListener('input', OSM.debounce(() => {
        state.catalog.q = OSM.clean(catSearch.value);
        state.catalog.page = 1;
        loadCatalogo();
      }, 300));
    }

    const catFilterCat = document.getElementById('admCatFilterCat');
    if (catFilterCat) {
      catFilterCat.addEventListener('change', () => {
        state.catalog.categoria = catFilterCat.value;
        state.catalog.page = 1;
        loadCatalogo();
      });
    }

    const catFilterState = document.getElementById('admCatFilterState');
    if (catFilterState) {
      catFilterState.addEventListener('change', () => {
        state.catalog.estado = catFilterState.value;
        state.catalog.page = 1;
        loadCatalogo();
      });
    }

    const catPrev = document.getElementById('admCatalogPrev');
    const catNext = document.getElementById('admCatalogNext');
    if (catPrev) catPrev.addEventListener('click', () => { if (state.catalog.page > 1) { state.catalog.page--; loadCatalogo(); } });
    if (catNext) catNext.addEventListener('click', () => { state.catalog.page++; loadCatalogo(); });

    // Delegación en contenedor Admin
    const adminView = document.getElementById('view-admin');
    if (adminView) {
      adminView.addEventListener('click', async e => {
        const openOrdBtn = e.target.closest('[data-adm-open-order]');
        if (openOrdBtn) {
          openOrderDetail(Number(openOrdBtn.dataset.admOpenOrder));
          return;
        }

        const openTicketBtn = e.target.closest('[data-adm-open-ticket]');
        if (openTicketBtn) {
          openTicketDrawer(Number(openTicketBtn.dataset.admOpenTicket));
          return;
        }

        const newProdBtn = e.target.closest('#admOpenNewProductBtn');
        if (newProdBtn && productModal) {
          const f = document.getElementById('admProductForm');
          if (f) f.reset();
          state.gallery.newProductFiles = [];
          const prevEl = document.getElementById('admNewProdImgPreview');
          if (prevEl) prevEl.replaceChildren();
          const imgIn = document.getElementById('admProdImagesInput');
          if (imgIn) imgIn.value = '';
          productModal.show();
          return;
        }

        const editProdBtn = e.target.closest('[data-adm-edit-prod]');
        if (editProdBtn) {
          openEditProductModal(Number(editProdBtn.dataset.admEditProd));
          return;
        }

        const openNewStaffBtn = e.target.closest('#admOpenNewStaffBtn');
        if (openNewStaffBtn && staffModal) {
          const sf = document.getElementById('admStaffForm');
          if (sf) {
            sf.reset();
            ['nombre', 'apellido', 'email', 'telefono', 'rol', 'contrasena'].forEach(fname => {
              if (sf.elements[fname]) OSM.field.clear(sf.elements[fname]);
            });
            const pwdEl = document.getElementById('admStaffPassword');
            if (pwdEl) pwdEl.dispatchEvent(new Event('input'));
          }
          staffModal.show();
          return;
        }

        const staffRoleBtn = e.target.closest('[data-adm-staff-role]');
        if (staffRoleBtn && !staffRoleBtn.disabled) {
          handleStaffRoleChange(
            staffRoleBtn,
            Number(staffRoleBtn.dataset.admStaffRole),
            staffRoleBtn.dataset.targetRole
          );
          return;
        }

        const staffToggleBtn = e.target.closest('[data-adm-staff-toggle]');
        if (staffToggleBtn && !staffToggleBtn.disabled) {
          handleStaffStateToggle(
            staffToggleBtn,
            Number(staffToggleBtn.dataset.admStaffToggle),
            staffToggleBtn.dataset.targetActive === 'true'
          );
          return;
        }

        const newFaqBtn = e.target.closest('#admOpenNewFaqBtn');
        if (newFaqBtn) {
          openFaqModal({ mode: 'create' });
          return;
        }

        const editFaqBtn = e.target.closest('[data-adm-faq-edit]');
        if (editFaqBtn) {
          const fid = Number(editFaqBtn.dataset.admFaqEdit);
          const faq = state.faqs.items.find(f => Number(f.id_faq) === fid);
          if (faq) openFaqModal({ mode: 'edit', faq });
          return;
        }

        const moveFaqBtn = e.target.closest('[data-adm-faq-move]');
        if (moveFaqBtn && !moveFaqBtn.disabled) {
          handleFaqReorder(
            moveFaqBtn,
            Number(moveFaqBtn.dataset.faqId),
            Number(moveFaqBtn.dataset.targetOrden)
          );
          return;
        }

        const toggleFaqBtn = e.target.closest('[data-adm-faq-toggle]');
        if (toggleFaqBtn) {
          handleFaqToggleState(
            toggleFaqBtn,
            Number(toggleFaqBtn.dataset.admFaqToggle),
            toggleFaqBtn.dataset.targetEstado
          );
          return;
        }

        const repApplyBtn = e.target.closest('#admRepApplyBtn');
        if (repApplyBtn) {
          const df = document.getElementById('admRepDateFrom');
          const dt = document.getElementById('admRepDateTo');
          const st = document.getElementById('admRepStateFilter');
          state.reports.fecha_inicio = df ? df.value : '';
          state.reports.fecha_fin    = dt ? dt.value : '';
          state.reports.estado       = st ? st.value : '';
          loadReportesVendedoras();
          return;
        }

        const repClearBtn = e.target.closest('#admRepClearBtn');
        if (repClearBtn) {
          const df = document.getElementById('admRepDateFrom');
          const dt = document.getElementById('admRepDateTo');
          const st = document.getElementById('admRepStateFilter');
          if (df) df.value = '';
          if (dt) dt.value = '';
          if (st) st.value = '';
          state.reports.fecha_inicio = '';
          state.reports.fecha_fin = '';
          state.reports.estado = '';
          loadReportesVendedoras();
          return;
        }

        const repExportBtn = e.target.closest('#admRepExportCsvBtn');
        if (repExportBtn) {
          exportReportsCsv();
          return;
        }

        // Acciones de Catálogos Maestros (Categorías, Tallas, Colores)
        if (e.target.closest('#admOpenNewCatBtn')) {
          openMasterCatModal(null);
          return;
        }
        const catEditBtn = e.target.closest('[data-adm-cat-edit]');
        if (catEditBtn) {
          const cid = Number(catEditBtn.dataset.admCatEdit);
          const cat = state.masters.categories.find(c => Number(c.id_categoria) === cid);
          if (cat) openMasterCatModal(cat);
          return;
        }
        const catToggleBtn = e.target.closest('[data-adm-cat-toggle]');
        if (catToggleBtn) {
          const cid = Number(catToggleBtn.dataset.admCatToggle);
          const nextEstado = catToggleBtn.dataset.targetEstado === 'true';
          await OSM.run(catToggleBtn, async () => {
            try {
              const res = await OneStyleAPI.admin.catalog.setCategoryState(cid, nextEstado);
              OSM.toast.success(res.message || 'Estado de categoría actualizado.');
              await loadMaestros();
              await refreshAllCatalogConsumers();
            } catch (err) {
              OSM.handleError(err, 'No se pudo cambiar el estado de la categoría');
            }
          }, '...');
          return;
        }
        const catDelBtn = e.target.closest('[data-adm-cat-del]');
        if (catDelBtn) {
          const cid = Number(catDelBtn.dataset.admCatDel);
          const ok = await OSM.confirm('¿Eliminar esta categoría maestra?', {
            title: 'Eliminar Categoría', confirmText: 'Sí, eliminar', danger: true
          });
          if (!ok) return;
          await OSM.run(catDelBtn, async () => {
            try {
              const res = await OneStyleAPI.admin.catalog.deleteCategory(cid);
              OSM.toast.success(res.message || 'Categoría eliminada.');
              await loadMaestros();
              await refreshAllCatalogConsumers();
            } catch (err) {
              OSM.handleError(err, 'No se pudo eliminar la categoría');
            }
          }, '...');
          return;
        }

        if (e.target.closest('#admOpenNewSizeBtn')) {
          openMasterSizeModal(null);
          return;
        }
        const sizeEditBtn = e.target.closest('[data-adm-size-edit]');
        if (sizeEditBtn) {
          const tid = Number(sizeEditBtn.dataset.admSizeEdit);
          const sz = state.masters.tallas.find(t => Number(t.id_talla) === tid);
          if (sz) openMasterSizeModal(sz);
          return;
        }
        const sizeToggleBtn = e.target.closest('[data-adm-size-toggle]');
        if (sizeToggleBtn) {
          const tid = Number(sizeToggleBtn.dataset.admSizeToggle);
          const nextEstado = sizeToggleBtn.dataset.targetEstado === 'true';
          await OSM.run(sizeToggleBtn, async () => {
            try {
              const res = await OneStyleAPI.admin.catalog.setSizeState(tid, nextEstado);
              OSM.toast.success(res.message || 'Estado de talla actualizado.');
              await loadMaestros();
              await refreshAllCatalogConsumers();
            } catch (err) {
              OSM.handleError(err, 'No se pudo cambiar el estado de la talla');
            }
          }, '...');
          return;
        }
        const sizeDelBtn = e.target.closest('[data-adm-size-del]');
        if (sizeDelBtn) {
          const tid = Number(sizeDelBtn.dataset.admSizeDel);
          const ok = await OSM.confirm('¿Eliminar esta talla maestra?', {
            title: 'Eliminar Talla', confirmText: 'Sí, eliminar', danger: true
          });
          if (!ok) return;
          await OSM.run(sizeDelBtn, async () => {
            try {
              const res = await OneStyleAPI.admin.catalog.deleteSize(tid);
              OSM.toast.success(res.message || 'Talla eliminada.');
              await loadMaestros();
              await refreshAllCatalogConsumers();
            } catch (err) {
              OSM.handleError(err, 'No se pudo eliminar la talla');
            }
          }, '...');
          return;
        }

        if (e.target.closest('#admOpenNewColorBtn')) {
          openMasterColorModal(null);
          return;
        }
        const colorEditBtn = e.target.closest('[data-adm-color-edit]');
        if (colorEditBtn) {
          const cid = Number(colorEditBtn.dataset.admColorEdit);
          const col = state.masters.colores.find(c => Number(c.id_color) === cid);
          if (col) openMasterColorModal(col);
          return;
        }
        const colorToggleBtn = e.target.closest('[data-adm-color-toggle]');
        if (colorToggleBtn) {
          const cid = Number(colorToggleBtn.dataset.admColorToggle);
          const nextEstado = colorToggleBtn.dataset.targetEstado === 'true';
          await OSM.run(colorToggleBtn, async () => {
            try {
              const res = await OneStyleAPI.admin.catalog.setColorState(cid, nextEstado);
              OSM.toast.success(res.message || 'Estado de color actualizado.');
              await loadMaestros();
              await refreshAllCatalogConsumers();
            } catch (err) {
              OSM.handleError(err, 'No se pudo cambiar el estado del color');
            }
          }, '...');
          return;
        }
        const colorDelBtn = e.target.closest('[data-adm-color-del]');
        if (colorDelBtn) {
          const cid = Number(colorDelBtn.dataset.admColorDel);
          const ok = await OSM.confirm('¿Eliminar este color maestro?', {
            title: 'Eliminar Color', confirmText: 'Sí, eliminar', danger: true
          });
          if (!ok) return;
          await OSM.run(colorDelBtn, async () => {
            try {
              const res = await OneStyleAPI.admin.catalog.deleteColor(cid);
              OSM.toast.success(res.message || 'Color eliminado.');
              await loadMaestros();
              await refreshAllCatalogConsumers();
            } catch (err) {
              OSM.handleError(err, 'No se pudo eliminar el color');
            }
          }, '...');
          return;
        }

        const addVarBtn = e.target.closest('[data-adm-add-var]');
        if (addVarBtn && variantModal) {
          const pid = Number(addVarBtn.dataset.admAddVar);
          state.selectedProductForVariant = state.catalog.items.find(p => Number(p.id_producto) === pid) || { id_producto: pid };
          const titleEl = document.getElementById('admVarProductName');
          if (titleEl) titleEl.textContent = state.selectedProductForVariant.name || `Producto #${pid}`;
          const f = document.getElementById('admVariantForm');
          if (f) f.reset();
          variantModal.show();
          return;
        }

        const stockBtn = e.target.closest('[data-stock-save]');
        if (stockBtn) {
          const vid = Number(stockBtn.dataset.stockSave);
          const input = adminView.querySelector(`[data-stock-input="${vid}"]`);
          const nuevoStock = Number(input ? input.value : -1);
          if (!Number.isInteger(nuevoStock) || nuevoStock < 0) {
            OSM.toast.warning('Ingresa una cantidad entera mayor o igual a 0.');
            return;
          }
          await OSM.run(stockBtn, async () => {
            try {
              const res = await OneStyleAPI.admin.catalog.adjustStock(vid, { stock_fisico: nuevoStock });
              OSM.toast.success(res.message || 'Stock actualizado correctamente.');
              await loadInventario();
              await loadResumen();
              if (typeof window.syncCatalogFromBackend === 'function') window.syncCatalogFromBackend();
            } catch (err) {
              OSM.handleError(err, 'No se pudo ajustar el stock');
            }
          }, '...');
        }
      });

      adminView.addEventListener('change', async e => {
        const visInput = e.target.closest('[data-adm-vis]');
        if (!visInput) return;
        const pid = Number(visInput.dataset.admVis);
        const visible = visInput.checked;
        visInput.disabled = true;
        try {
          const res = await OneStyleAPI.admin.catalog.setVisibility(pid, visible);
          OSM.toast.success(res.message || 'Visibilidad actualizada.');
          await loadCatalogo();
          if (typeof window.syncCatalogFromBackend === 'function') window.syncCatalogFromBackend();
        } catch (err) {
          visInput.checked = !visible;
          OSM.handleError(err, 'Error al cambiar visibilidad');
        } finally {
          visInput.disabled = false;
        }
      });
    }

    // Botones de transición dentro del Drawer de Pedido
    const drawerFoot = document.getElementById('admDrawerOrderFoot');
    if (drawerFoot) {
      drawerFoot.addEventListener('click', e => {
        const fsmBtn = e.target.closest('[data-adm-fsm]');
        if (!fsmBtn) return;
        executeOrderTransition(fsmBtn, fsmBtn.dataset.admFsm);
      });
    }

    // Subpanel Soporte y Auditoría: pestañas, filtros y acciones FSM de tickets
    const soporteTabs = document.getElementById('admSoporteTabs');
    if (soporteTabs) {
      soporteTabs.addEventListener('click', e => {
        const tabBtn = e.target.closest('[data-soporte-tab]');
        if (!tabBtn) return;
        setSoporteSubTab(tabBtn.dataset.soporteTab);
      });
    }

    const ticketFilter = document.getElementById('admTicketStateFilter');
    if (ticketFilter) {
      ticketFilter.addEventListener('change', () => {
        state.support.estado = ticketFilter.value;
        loadSoporteTickets();
      });
    }

    const refreshTicketsBtn = document.getElementById('admRefreshTicketsBtn');
    if (refreshTicketsBtn) {
      refreshTicketsBtn.addEventListener('click', () => loadSoporteTickets());
    }

    const ticketReplyForm = document.getElementById('admTicketReplyForm');
    if (ticketReplyForm) {
      ticketReplyForm.addEventListener('submit', e => {
        e.preventDefault();
        submitTicketUpdate(document.getElementById('admTicketSaveReplyBtn'), { requireReply: true });
      });
    }

    const ticketTransitionBtn = document.getElementById('admTicketTransitionBtn');
    if (ticketTransitionBtn) {
      ticketTransitionBtn.addEventListener('click', () => {
        const nextState = ticketTransitionBtn.dataset.nextState;
        if (!nextState) return;
        submitTicketUpdate(ticketTransitionBtn, { nextState });
      });
    }

    const auditSearch = document.getElementById('admAuditSearch');
    if (auditSearch) {
      auditSearch.addEventListener('input', OSM.debounce(() => {
        state.audit.q = OSM.clean(auditSearch.value);
        renderAuditTable();
      }, 200));
    }

    const auditTableSel = document.getElementById('admAuditTableFilter');
    if (auditTableSel) {
      auditTableSel.addEventListener('change', () => {
        state.audit.tabla = auditTableSel.value;
        renderAuditTable();
      });
    }

    const auditActionSel = document.getElementById('admAuditActionFilter');
    if (auditActionSel) {
      auditActionSel.addEventListener('change', () => {
        state.audit.accion = auditActionSel.value;
        renderAuditTable();
      });
    }

    const refreshAuditBtn = document.getElementById('admRefreshAuditBtn');
    if (refreshAuditBtn) {
      refreshAuditBtn.addEventListener('click', () => loadAuditLogs());
    }

    const auditDateFrom = document.getElementById('admAuditDateFrom');
    const auditDateTo   = document.getElementById('admAuditDateTo');
    const onAuditDateChange = () => {
      state.audit.fecha_inicio = auditDateFrom ? auditDateFrom.value : '';
      state.audit.fecha_fin    = auditDateTo ? auditDateTo.value : '';
      if (state.audit.fecha_inicio && state.audit.fecha_fin && state.audit.fecha_inicio > state.audit.fecha_fin) {
        OSM.toast.warning('La fecha de inicio de auditoría no puede ser mayor que la fecha fin.');
        return;
      }
      loadAuditLogs();
    };
    if (auditDateFrom) auditDateFrom.addEventListener('change', onAuditDateChange);
    if (auditDateTo)   auditDateTo.addEventListener('change', onAuditDateChange);

    const exportAuditCsvBtn = document.getElementById('admExportAuditCsvBtn');
    if (exportAuditCsvBtn) {
      exportAuditCsvBtn.addEventListener('click', () => exportAuditCsv());
    }

    const publishFaqBtn = document.getElementById('admTicketPublishFaqBtn');
    if (publishFaqBtn) {
      publishFaqBtn.addEventListener('click', () => {
        const ticket = state.support.selectedTicket;
        if (!ticket || ticket.estado !== 'RESUELTO' || !String(ticket.respuesta_soporte || '').trim()) {
          OSM.toast.warning('Solo se pueden convertir tickets en estado RESUELTO que tengan respuesta.');
          return;
        }
        if (ticketDrawer) ticketDrawer.hide();
        openFaqModal({ mode: 'create', fromTicket: ticket });
      });
    }

    // Filtros y formulario modal de Preguntas Frecuentes (RF-FAQ-005..010)
    const faqSearch = document.getElementById('admFaqSearch');
    if (faqSearch) {
      faqSearch.addEventListener('input', OSM.debounce(() => {
        state.faqs.q = OSM.clean(faqSearch.value);
        renderFaqsTable();
      }, 200));
    }

    const faqCatFilter = document.getElementById('admFaqCatFilter');
    if (faqCatFilter) {
      faqCatFilter.addEventListener('change', () => {
        state.faqs.cat = faqCatFilter.value;
        renderFaqsTable();
      });
    }

    const faqStateFilter = document.getElementById('admFaqStateFilter');
    if (faqStateFilter) {
      faqStateFilter.addEventListener('change', () => {
        state.faqs.estado = faqStateFilter.value;
        renderFaqsTable();
      });
    }

    const refreshFaqsBtn = document.getElementById('admRefreshFaqsBtn');
    if (refreshFaqsBtn) {
      refreshFaqsBtn.addEventListener('click', () => loadFaqsAdmin());
    }

    const faqForm = document.getElementById('admFaqForm');
    if (faqForm) {
      const faqSchema = {
        pregunta: [OSM.rules.required('Ingresa la pregunta frecuente.'), OSM.rules.minLength(5)],
        id_categoria: [
          OSM.rules.required('Selecciona una categoría.'),
          v => (Number.isInteger(Number(v)) && Number(v) >= 1 ? '' : 'Selecciona una categoría válida.')
        ],
        orden: [OSM.rules.integerMin(1, 'El orden debe ser un número entero mayor o igual a 1.')],
        respuesta: [OSM.rules.required('Ingresa la respuesta pública.'), OSM.rules.minLength(5)]
      };
      OSM.liveValidate(faqForm, faqSchema);

      faqForm.addEventListener('submit', async e => {
        e.preventDefault();
        if (!OSM.validate(faqForm, faqSchema)) return;

        const btn = document.getElementById('admSaveFaqBtn');
        await OSM.run(btn, async () => {
          try {
            const payload = {
              pregunta: OSM.clean(faqForm.elements.pregunta.value),
              respuesta: OSM.clean(faqForm.elements.respuesta.value),
              id_categoria: Number(faqForm.elements.id_categoria.value),
              orden: Number(faqForm.elements.orden.value)
            };
            const isEdit = Boolean(state.faqs.editingId);
            const res = isEdit
              ? await OneStyleAPI.admin.faqs.update(state.faqs.editingId, payload)
              : await OneStyleAPI.admin.faqs.create(payload);

            state.faqs.editingId = null;
            if (faqModal) faqModal.hide();
            OSM.toast.success(res.message || (isEdit ? 'FAQ actualizada.' : 'FAQ publicada exitosamente.'));
            await loadFaqsAdmin();
            refreshHelpFaqsView();
          } catch (err) {
            OSM.handleError(err, 'No se pudo guardar la FAQ');
          }
        }, 'Guardando...');
      });
    }

    // Filtros y búsqueda de Personal Operativo
    const staffSearch = document.getElementById('admStaffSearch');
    if (staffSearch) {
      staffSearch.addEventListener('input', OSM.debounce(() => {
        state.staff.q = OSM.clean(staffSearch.value);
        renderStaffTable();
      }, 200));
    }

    const staffRoleFilter = document.getElementById('admStaffRoleFilter');
    if (staffRoleFilter) {
      staffRoleFilter.addEventListener('change', () => {
        state.staff.rol = staffRoleFilter.value;
        renderStaffTable();
      });
    }

    const refreshStaffBtn = document.getElementById('admRefreshStaffBtn');
    if (refreshStaffBtn) {
      refreshStaffBtn.addEventListener('click', () => loadPersonal());
    }

    // Formulario de Edición Completa de Prenda (RF-CAT-003)
    const editProdForm = document.getElementById('admEditProductForm');
    if (editProdForm) {
      const editProdSchema = {
        nombre_producto: [OSM.rules.required('Ingresa el nombre de la prenda.'), OSM.rules.minLength(3)],
        descripcion_producto: [OSM.rules.required('Ingresa una descripción para la prenda.')],
        fk_id_categoria: [
          OSM.rules.required('Selecciona una categoría activa.'),
          v => {
            const catId = Number(v);
            const ok = state.categories.some(c => Number(c.id_categoria) === catId && c.estado !== false);
            return ok ? '' : 'Selecciona una categoría activa válida.';
          }
        ],
        precio_detallista: [OSM.rules.positiveNumber('Ingresa un precio numérico mayor a 0.')]
      };
      OSM.liveValidate(editProdForm, editProdSchema);

      editProdForm.addEventListener('submit', async e => {
        e.preventDefault();
        if (!state.selectedProductForEdit) return;
        if (!OSM.validate(editProdForm, editProdSchema)) return;

        const btn = document.getElementById('admSaveEditProductBtn');
        await OSM.run(btn, async () => {
          try {
            const payload = {
              nombre_producto: OSM.clean(editProdForm.elements.nombre_producto.value),
              descripcion_producto: OSM.clean(editProdForm.elements.descripcion_producto.value),
              fk_id_categoria: Number(editProdForm.elements.fk_id_categoria.value),
              precio_detallista: Number(editProdForm.elements.precio_detallista.value)
            };
            const res = await OneStyleAPI.admin.catalog.updateProduct(state.selectedProductForEdit.id_producto, payload);
            OSM.toast.success(res.message || 'Prenda actualizada correctamente.');
            if (editProductModal) editProductModal.hide();
            await loadCatalogo();
            await loadResumen();
            if (typeof window.syncCatalogFromBackend === 'function') {
              window.syncCatalogFromBackend();
            }
          } catch (err) {
            OSM.handleError(err, 'No se pudo actualizar la prenda');
          }
        }, 'Guardando...');
      });
    }

    // Formulario de Creación de Personal Operativo (RF-SEG-012 + RN-SEG-008)
    const staffForm = document.getElementById('admStaffForm');
    if (staffForm) {
      const staffSchema = {
        nombre: [OSM.rules.required('El nombre es obligatorio.'), OSM.rules.minLength(2)],
        apellido: [OSM.rules.required('El apellido es obligatorio.'), OSM.rules.minLength(2)],
        email: [OSM.rules.required('El correo es obligatorio.'), OSM.rules.email()],
        rol: [v => (['Vendedora', 'Administradora'].includes(v) ? '' : 'Selecciona un rol operativo válido.')],
        contrasena: [OSM.rules.required('Ingresa una contraseña inicial.'), OSM.rules.strongPassword()]
      };
      OSM.liveValidate(staffForm, staffSchema);

      const staffPwdInput = document.getElementById('admStaffPassword');
      const staffPwdHints = document.getElementById('admStaffPwdHints');
      const syncStaffPwdHints = () => {
        if (!staffPwdInput || !staffPwdHints || !OSM.passwordPolicy) return;
        const checks = OSM.passwordPolicy.check(staffPwdInput.value);
        staffPwdHints.querySelectorAll('[data-pwd-rule]').forEach(li => {
          li.classList.toggle('is-valid', Boolean(checks[li.dataset.pwdRule]));
        });
      };
      if (staffPwdInput) staffPwdInput.addEventListener('input', syncStaffPwdHints);

      staffForm.addEventListener('submit', async e => {
        e.preventDefault();
        if (!OSM.validate(staffForm, staffSchema)) return;

        const btn = document.getElementById('admSaveStaffBtn');
        await OSM.run(btn, async () => {
          try {
            const payload = {
              nombre: OSM.clean(staffForm.elements.nombre.value),
              apellido: OSM.clean(staffForm.elements.apellido.value),
              email: OSM.clean(staffForm.elements.email.value),
              rol: staffForm.elements.rol.value,
              contrasena: staffForm.elements.contrasena.value
            };
            const telClean = OSM.clean(staffForm.elements.telefono ? staffForm.elements.telefono.value : '');
            if (telClean) payload.telefono = telClean;

            const res = await OneStyleAPI.admin.staff.create(payload);
            OSM.toast.success(res.message || 'Personal operativo registrado exitosamente.');
            staffForm.reset();
            syncStaffPwdHints();
            if (staffModal) staffModal.hide();
            await loadPersonal();
          } catch (err) {
            OSM.handleError(err, 'No se pudo registrar el personal');
          }
        }, 'Registrando...');
      });
    }

    // Subtabs y formularios de Catálogos Maestros (Categorías, Tallas, Colores)
    const maestrosTabs = document.getElementById('admMaestrosTabs');
    if (maestrosTabs) {
      maestrosTabs.addEventListener('click', e => {
        const tabBtn = e.target.closest('[data-maestro-tab]');
        if (!tabBtn) return;
        setMaestrosSubTab(tabBtn.dataset.maestroTab);
      });
    }

    const masterCatForm = document.getElementById('admMasterCatForm');
    if (masterCatForm) {
      const catSchema = {
        nombre_categoria: [OSM.rules.required('El nombre de la categoría es obligatorio.')]
      };
      OSM.liveValidate(masterCatForm, catSchema);
      masterCatForm.addEventListener('submit', async e => {
        e.preventDefault();
        if (!OSM.validate(masterCatForm, catSchema)) return;
        const btn = document.getElementById('admSaveMasterCatBtn');
        await OSM.run(btn, async () => {
          try {
            const payload = {
              nombre_categoria: OSM.clean(masterCatForm.elements.nombre_categoria.value),
              descripcion_categoria: OSM.clean(masterCatForm.elements.descripcion_categoria ? masterCatForm.elements.descripcion_categoria.value : '')
            };
            const isEdit = Boolean(state.masters.editingCatId);
            const res = isEdit
              ? await OneStyleAPI.admin.catalog.updateCategory(state.masters.editingCatId, payload)
              : await OneStyleAPI.admin.catalog.createCategory(payload);
            state.masters.editingCatId = null;
            if (masterCatModal) masterCatModal.hide();
            OSM.toast.success(res.message || (isEdit ? 'Categoría actualizada.' : 'Categoría creada.'));
            await loadMaestros();
            await refreshAllCatalogConsumers();
          } catch (err) {
            OSM.handleError(err, 'No se pudo guardar la categoría');
          }
        }, 'Guardando...');
      });
    }

    const masterSizeForm = document.getElementById('admMasterSizeForm');
    if (masterSizeForm) {
      const sizeSchema = {
        nombre_talla: [OSM.rules.required('El nombre de la talla es obligatorio.')]
      };
      OSM.liveValidate(masterSizeForm, sizeSchema);
      masterSizeForm.addEventListener('submit', async e => {
        e.preventDefault();
        if (!OSM.validate(masterSizeForm, sizeSchema)) return;
        const btn = document.getElementById('admSaveMasterSizeBtn');
        await OSM.run(btn, async () => {
          try {
            const payload = { nombre_talla: OSM.clean(masterSizeForm.elements.nombre_talla.value).toUpperCase() };
            const isEdit = Boolean(state.masters.editingSizeId);
            const res = isEdit
              ? await OneStyleAPI.admin.catalog.updateSize(state.masters.editingSizeId, payload)
              : await OneStyleAPI.admin.catalog.createSize(payload);
            state.masters.editingSizeId = null;
            if (masterSizeModal) masterSizeModal.hide();
            OSM.toast.success(res.message || (isEdit ? 'Talla actualizada.' : 'Talla creada.'));
            await loadMaestros();
            await refreshAllCatalogConsumers();
          } catch (err) {
            OSM.handleError(err, 'No se pudo guardar la talla');
          }
        }, 'Guardando...');
      });
    }

    const hexPicker = document.getElementById('admColorHexPicker');
    const hexInput  = document.getElementById('admColorHexInput');
    if (hexPicker && hexInput) {
      hexPicker.addEventListener('input', () => {
        hexInput.value = String(hexPicker.value || '#17140F').toUpperCase();
      });
      hexInput.addEventListener('input', () => {
        const val = String(hexInput.value || '').trim();
        if (/^#[0-9A-Fa-f]{6}$/.test(val)) hexPicker.value = val.toUpperCase();
      });
    }

    const masterColorForm = document.getElementById('admMasterColorForm');
    if (masterColorForm) {
      const colorSchema = {
        nombre_color: [OSM.rules.required('El nombre del color es obligatorio.')],
        codigo_hex: [v => (/^#[0-9A-Fa-f]{6}$/.test(String(v || '').trim()) ? '' : 'Ingresa un código hexadecimal (#RRGGBB).')]
      };
      OSM.liveValidate(masterColorForm, colorSchema);
      masterColorForm.addEventListener('submit', async e => {
        e.preventDefault();
        if (!OSM.validate(masterColorForm, colorSchema)) return;
        const btn = document.getElementById('admSaveMasterColorBtn');
        await OSM.run(btn, async () => {
          try {
            const payload = {
              nombre_color: OSM.clean(masterColorForm.elements.nombre_color.value),
              codigo_hex: OSM.clean(masterColorForm.elements.codigo_hex.value).toUpperCase()
            };
            const isEdit = Boolean(state.masters.editingColorId);
            const res = isEdit
              ? await OneStyleAPI.admin.catalog.updateColor(state.masters.editingColorId, payload)
              : await OneStyleAPI.admin.catalog.createColor(payload);
            state.masters.editingColorId = null;
            if (masterColorModal) masterColorModal.hide();
            OSM.toast.success(res.message || (isEdit ? 'Color actualizado.' : 'Color creado.'));
            await loadMaestros();
            await refreshAllCatalogConsumers();
          } catch (err) {
            OSM.handleError(err, 'No se pudo guardar el color');
          }
        }, 'Guardando...');
      });
    }

    // Gestor de carga múltiple y galería 1..N (Creación y Edición)
    const newProdImagesInput = document.getElementById('admProdImagesInput');
    if (newProdImagesInput) {
      newProdImagesInput.addEventListener('change', e => {
        const valid = validateClientImageFiles(e.target.files);
        state.gallery.newProductFiles = valid;
        renderFilePreviewStrip(valid, document.getElementById('admNewProdImgPreview'));
      });
    }

    const editGalleryInput = document.getElementById('admEditGalleryInput');
    if (editGalleryInput) {
      editGalleryInput.addEventListener('change', e => {
        const valid = validateClientImageFiles(e.target.files);
        state.gallery.pendingFiles = valid;
        renderFilePreviewStrip(valid, document.getElementById('admEditGalleryPending'));
      });
    }

    const uploadGalleryBtn = document.getElementById('admUploadGalleryBtn');
    if (uploadGalleryBtn) {
      uploadGalleryBtn.addEventListener('click', () => uploadPendingEditGalleryImages(uploadGalleryBtn));
    }

    const editGalleryList = document.getElementById('admEditGalleryList');
    if (editGalleryList) {
      editGalleryList.addEventListener('click', e => {
        const prinBtn = e.target.closest('[data-adm-img-principal]');
        if (prinBtn) {
          handleGallerySetPrincipal(prinBtn, Number(prinBtn.dataset.admImgPrincipal));
          return;
        }
        const moveBtn = e.target.closest('[data-adm-img-move]');
        if (moveBtn && !moveBtn.disabled) {
          handleGalleryMove(moveBtn, Number(moveBtn.dataset.imgId), moveBtn.dataset.admImgMove);
          return;
        }
        const delBtn = e.target.closest('[data-adm-img-del]');
        if (delBtn) {
          handleGalleryDeleteImage(delBtn, Number(delBtn.dataset.admImgDel));
        }
      });
    }

    // Formulario de Creación de Prenda + Primera Variante + Imágenes 1..N
    const prodForm = document.getElementById('admProductForm');
    if (prodForm) {
      const prodSchema = {
        nombre: [OSM.rules.required('Ingresa el nombre de la prenda.'), OSM.rules.minLength(3)],
        descripcion: [OSM.rules.required('Ingresa una descripción breve.')],
        precio_base: [OSM.rules.positiveNumber('Ingresa un precio base mayor a 0.')],
        sku_inicial: [OSM.rules.required('Ingresa el SKU inicial.')],
        stock_inicial: [OSM.rules.integerMin(0, 'Ingresa un stock inicial válido (0 o más).')]
      };
      OSM.liveValidate(prodForm, prodSchema);

      prodForm.addEventListener('submit', async e => {
        e.preventDefault();
        if (!OSM.validate(prodForm, prodSchema)) return;
        const btn = document.getElementById('admSaveProductBtn');
        await OSM.run(btn, async () => {
          try {
            const payload = {
              nombre_producto: OSM.clean(prodForm.elements.nombre.value),
              descripcion_producto: OSM.clean(prodForm.elements.descripcion.value),
              precio_detallista: Number(prodForm.elements.precio_base.value),
              fk_id_categoria: Number(prodForm.elements.fk_id_categoria.value || 1),
              fk_id_talla: Number(prodForm.elements.fk_id_talla.value || 2),
              fk_id_color: Number(prodForm.elements.fk_id_color.value || 1),
              stock_real: Number(prodForm.elements.stock_inicial.value || 0),
              codigo_sku: OSM.clean(prodForm.elements.sku_inicial.value).toUpperCase(),
              precio_variante: Number(prodForm.elements.precio_base.value)
            };
            const res = await OneStyleAPI.admin.catalog.createProduct(payload);
            const createdId = res && res.data && res.data.id_producto;
            const filesToUpload = state.gallery.newProductFiles || [];
            if (createdId && filesToUpload.length) {
              const user = OneStyleAPI.getSavedUser();
              if (user && user.rol === 'Administradora') {
                const fd = new FormData();
                filesToUpload.forEach(f => fd.append('imagenes', f));
                await OneStyleAPI.admin.catalog.uploadImages(createdId, fd);
              }
            }
            state.gallery.newProductFiles = [];
            const prevEl = document.getElementById('admNewProdImgPreview');
            if (prevEl) prevEl.replaceChildren();
            OSM.toast.success(res.message || 'Prenda creada exitosamente.');
            if (productModal) productModal.hide();
            await loadCatalogo();
            await loadResumen();
            if (typeof window.syncCatalogFromBackend === 'function') window.syncCatalogFromBackend();
          } catch (err) {
            OSM.handleError(err, 'No se pudo registrar la prenda');
          }
        }, 'Guardando...');
      });
    }

    // Formulario para añadir variante SKU
    const varForm = document.getElementById('admVariantForm');
    if (varForm) {
      const varSchema = {
        sku: [OSM.rules.required('Ingresa el código SKU.')],
        precio_variante: [OSM.rules.positiveNumber('El precio debe ser mayor a 0.')],
        stock_fisico: [OSM.rules.integerMin(0, 'Ingresa un stock entero mayor o igual a 0.')]
      };
      OSM.liveValidate(varForm, varSchema);

      varForm.addEventListener('submit', async e => {
        e.preventDefault();
        if (!state.selectedProductForVariant) return;
        if (!OSM.validate(varForm, varSchema)) return;
        const btn = document.getElementById('admSaveVariantBtn');
        await OSM.run(btn, async () => {
          try {
            const res = await OneStyleAPI.admin.catalog.addVariant(state.selectedProductForVariant.id_producto, {
              sku: OSM.clean(varForm.elements.sku.value).toUpperCase(),
              fk_id_talla: Number(varForm.elements.fk_id_talla.value),
              fk_id_color: Number(varForm.elements.fk_id_color.value),
              precio_variante: Number(varForm.elements.precio_variante.value),
              stock_fisico: Number(varForm.elements.stock_fisico.value)
            });
            OSM.toast.success(res.message || 'Variante SKU agregada.');
            if (variantModal) variantModal.hide();
            await loadCatalogo();
            await loadInventario();
            if (typeof window.syncCatalogFromBackend === 'function') window.syncCatalogFromBackend();
          } catch (err) {
            OSM.handleError(err, 'No se pudo crear la variante');
          }
        }, 'Guardando...');
      });
    }

    // Formulario de Perfil de la Administradora
    const profForm = document.getElementById('admProfileForm');
    if (profForm) {
      const profSchema = {
        nombre: [OSM.rules.required('El nombre es obligatorio.'), OSM.rules.minLength(2)],
        apellido: [OSM.rules.required('El apellido es obligatorio.'), OSM.rules.minLength(2)],
        email: [OSM.rules.required('El correo es obligatorio.'), OSM.rules.email()],
        telefono: [OSM.rules.phone()]
      };
      OSM.liveValidate(profForm, profSchema);

      profForm.addEventListener('submit', async e => {
        e.preventDefault();
        if (!OSM.validate(profForm, profSchema)) return;
        const btn = document.getElementById('admSaveProfileBtn');
        await OSM.run(btn, async () => {
          try {
            const res = await OneStyleAPI.auth.updateProfile({
              nombre: OSM.clean(profForm.elements.nombre.value),
              apellido: OSM.clean(profForm.elements.apellido.value),
              email: OSM.clean(profForm.elements.email.value),
              telefono: OSM.clean(profForm.elements.telefono.value)
            });
            OneStyleAPI.setSession(OneStyleAPI.getToken(), res.data);
            if (typeof window.syncCurrentUserFromStorage === 'function') {
              window.syncCurrentUserFromStorage();
            }
            updateSidebarIdentity();
            OSM.toast.success(res.message || 'Perfil actualizado.');
          } catch (err) {
            OSM.handleError(err, 'No se pudo actualizar el perfil');
          }
        }, 'Guardando...');
      });
    }

    // Formulario de Cambio de Contraseña Autenticado
    const pwdForm = document.getElementById('admPasswordForm');
    if (pwdForm) {
      const pwdSchema = {
        contrasena_actual: [OSM.rules.required('Ingresa tu contraseña actual.')],
        nueva_password: [OSM.rules.required('Ingresa la nueva contraseña.'), OSM.rules.strongPassword()],
        confirmar_password: [
          OSM.rules.required('Confirma la nueva contraseña.'),
          OSM.rules.match(() => pwdForm.elements.nueva_password.value, 'Las contraseñas no coinciden.')
        ]
      };
      OSM.liveValidate(pwdForm, pwdSchema);

      const admPwdInput = document.getElementById('admPwdNew');
      const admPwdHints = document.getElementById('admPwdHints');
      const syncAdmPwdHints = () => {
        if (!admPwdInput || !admPwdHints || !OSM.passwordPolicy) return;
        const checks = OSM.passwordPolicy.check(admPwdInput.value);
        admPwdHints.querySelectorAll('[data-pwd-rule]').forEach(li => {
          li.classList.toggle('is-valid', Boolean(checks[li.dataset.pwdRule]));
        });
      };
      if (admPwdInput) admPwdInput.addEventListener('input', syncAdmPwdHints);

      pwdForm.addEventListener('submit', async e => {
        e.preventDefault();
        if (!OSM.validate(pwdForm, pwdSchema)) return;
        const btn = document.getElementById('admSavePasswordBtn');
        await OSM.run(btn, async () => {
          try {
            const res = await OneStyleAPI.auth.changePassword({
              contrasena_actual: pwdForm.elements.contrasena_actual.value,
              nueva_password: pwdForm.elements.nueva_password.value
            });
            pwdForm.reset();
            syncAdmPwdHints();
            OSM.toast.success(res.message || 'Contraseña actualizada exitosamente.');
          } catch (err) {
            OSM.handleError(err, 'Error al cambiar contraseña');
          }
        }, 'Actualizando...');
      });
    }
  }

  /* =========================================================
     7. APERTURA DE SUBPANELES (#/admin, #/admin/pedidos, etc.)
     ========================================================= */
  async function open(panelName = 'resumen') {
    bindEvents();
    updateSidebarIdentity();

    const user = OneStyleAPI.getSavedUser();
    let target = PANELS.includes(panelName) ? panelName : 'resumen';
    if (['soporte', 'personal', 'faqs', 'reportes', 'maestros'].includes(target) && (!user || user.rol !== 'Administradora')) {
      OSM.toast.warning('Solo el rol Administradora puede acceder a esta sección.');
      location.hash = '#/admin';
      return;
    }
    state.activePanel = target;

    document.querySelectorAll('#view-admin .adm-panel').forEach(p => {
      p.classList.toggle('active', p.id === `adm-panel-${target}`);
    });
    document.querySelectorAll('#admSidebarNav a[data-adm-nav]').forEach(a => {
      a.classList.toggle('active', a.dataset.admNav === target);
    });

    if (!state.categories.length) {
      await loadCatalogMetadata();
    }

    if (target === 'resumen')    await loadResumen();
    if (target === 'pedidos')    await loadPedidos();
    if (target === 'catalogo')   await loadCatalogo();
    if (target === 'inventario') await loadInventario();
    if (target === 'perfil')     await loadPerfil();
    if (target === 'personal')   await loadPersonal();
    if (target === 'faqs')       await loadFaqsAdmin();
    if (target === 'reportes')   await loadReportesVendedoras();
    if (target === 'maestros')   await loadMaestros();
    if (target === 'soporte') {
      await loadSoporteTickets();
      await loadAuditLogs();
    }
  }

  OSM.admin = { open, reload: () => open(state.activePanel) };
})();

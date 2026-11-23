/* ===========================================================
   OneStyleMariana — lógica de la tienda conectada al Backend
   =========================================================== */

/* ------------------------- Datos (Sincronizados desde /api/catalogo y /api/productos/categorias) ------------------------- */
const PRODUCTS = [];
const CATEGORIES = [];
let catalogLoaded = false;
let categoriesLoaded = false;

const esc   = s => (typeof OneStyleAPI !== 'undefined' ? OneStyleAPI.escapeHTML(s) : String(s ?? ''));
const money = n => '$' + Number(n || 0).toLocaleString('es-CO') + ' COP';
const byId  = id => PRODUCTS.find(p => String(p.id) === String(id));

/* ------------------------- Lista de Deseos Sanitizada (Wishlist) ------------------------- */
const WISHLIST_STORAGE_KEY = 'onestyle_wishlist';
let wishlist = [];
let wishlistDrawer = null;
let sizeGuideModal = null;

function loadWishlist(){
  try {
    const raw = localStorage.getItem(WISHLIST_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    if(!Array.isArray(parsed)) { wishlist = []; return; }
    wishlist = parsed
      .filter(it => it && it.id)
      .map(it => ({
        id: String(it.id).replace(/[<>"'`]/g, ''),
        name: String(it.name || ''),
        price: Number(it.price || 0),
        img: it.img ? String(it.img) : null,
        colorName: String(it.colorName || ''),
        colorKey: String(it.colorKey || ''),
        sizes: Array.isArray(it.sizes) ? it.sizes.map(s => String(s)) : []
      }));
  } catch (_) {
    wishlist = [];
  }
}

function saveWishlist(){
  try {
    localStorage.setItem(WISHLIST_STORAGE_KEY, JSON.stringify(wishlist));
  } catch (_) {}
}

function isInWishlist(productId){
  return wishlist.some(item => String(item.id) === String(productId));
}

function updateWishlistBadgesAndButtons(){
  const badge = document.getElementById('wishlistCount');
  if(badge){
    badge.textContent = String(wishlist.length);
    badge.classList.toggle('d-none', wishlist.length === 0);
  }

  document.querySelectorAll('[data-wishlist]').forEach(btn => {
    const pid = btn.getAttribute('data-wishlist');
    const active = isInWishlist(pid);
    btn.classList.toggle('is-active', active);
    btn.setAttribute('aria-pressed', String(active));
    const icon = btn.querySelector('i');
    if(icon) icon.className = active ? 'bi bi-heart-fill' : 'bi bi-heart';
  });

  const pdpWishBtn = document.getElementById('pdpWishlistBtn');
  if(pdpWishBtn && currentProduct){
    const active = isInWishlist(currentProduct.id);
    pdpWishBtn.innerHTML = active
      ? `<i class="bi bi-heart-fill"></i> <span>En tu Lista de Deseos</span>`
      : `<i class="bi bi-heart"></i> <span>Agregar a Lista de Deseos</span>`;
  }
}

function renderWishlistDrawer(){
  const wrap = document.getElementById('wishlistItemsWrap');
  if(!wrap) return;
  if(!wishlist.length){
    wrap.innerHTML = `<div class="empty-cart">Tu lista de deseos está vacía.<br>
      <a href="#/catalogo" class="link-osm text-decoration-underline" data-bs-dismiss="offcanvas">Explorar colección</a></div>`;
    updateWishlistBadgesAndButtons();
    return;
  }

  wrap.innerHTML = wishlist.map(item => {
    const safeId    = OneStyleAPI.escapeHTML(item.id);
    const safeName  = OneStyleAPI.escapeHTML(item.name);
    const safeColor = OneStyleAPI.escapeHTML(item.colorName || 'Exclusivo');
    const safeSizes = OneStyleAPI.escapeHTML((item.sizes || []).join(', ') || 'S, M');
    const safeImg   = item.img
      ? `<img src="${OneStyleAPI.escapeHTML(item.img)}" alt="${safeName}">`
      : `<div class="card-placeholder card-placeholder--fill"><i class="bi bi-bag"></i></div>`;

    return `
      <div class="drawer-item">
        <a href="#/producto/${safeId}" data-bs-dismiss="offcanvas">${safeImg}</a>
        <div>
          <h4><a href="#/producto/${safeId}" data-bs-dismiss="offcanvas">${safeName}</a></h4>
          <div class="meta">${safeColor} · Tallas ${safeSizes}</div>
          <div class="d-flex justify-content-between align-items-center mt-2">
            <span class="price">${money(item.price)}</span>
            <div class="d-flex gap-2">
              <a href="#/producto/${safeId}" class="osm-btn osm-btn--sm" data-bs-dismiss="offcanvas">Ver</a>
              <button type="button" class="osm-btn osm-btn--sm" data-wishlist-remove="${safeId}" aria-label="Quitar de favoritos">
                <i class="bi bi-trash"></i>
              </button>
            </div>
          </div>
        </div>
      </div>`;
  }).join('');

  updateWishlistBadgesAndButtons();
}

function toggleWishlistProduct(productId){
  const idx = wishlist.findIndex(item => String(item.id) === String(productId));
  if(idx >= 0){
    const removed = wishlist.splice(idx, 1)[0];
    saveWishlist();
    renderWishlistDrawer();
    if(window.OSM && OSM.toast){
      OSM.toast.info(`${removed.name || 'Prenda'} eliminada de tu Lista de Deseos.`);
    }
    return;
  }

  const p = byId(productId) || (currentProduct && String(currentProduct.id) === String(productId) ? currentProduct : null);
  if(!p) return;

  wishlist.push({
    id: String(p.id),
    name: String(p.name || p.nombre_producto || ''),
    price: Number(p.price || p.precio || 0),
    img: p.img || p.url_imagen_principal || null,
    colorName: String(p.colorName || ''),
    colorKey: String(p.colorKey || ''),
    sizes: Array.isArray(p.sizes) ? p.sizes : []
  });
  saveWishlist();
  renderWishlistDrawer();
  if(window.OSM && OSM.toast){
    OSM.toast.success(`${p.name} agregada a tu Lista de Deseos.`);
  }
}

/* ------------------------- Plantillas ------------------------- */
function mediaHTML(p, overrideImg = null){
  const src = overrideImg || p.img;
  return src
    ? `<img src="${esc(src)}" alt="${esc(p.name)}" loading="lazy">`
    : `<div class="card-placeholder"><i class="bi bi-bag"></i></div>`;
}

function cardHTML(p, col = 'col-6 col-lg-4'){
  const wished = isInWishlist(p.id);
  const sizesLabel = Array.isArray(p.sizes) && p.sizes.length ? `Tallas ${esc(p.sizes.join(', '))}` : esc(p.desc);
  const coloresList = Array.isArray(p.colores) && p.colores.length
    ? p.colores
    : [{ slug: p.colorKey || 'negro', nombre_color: p.colorName || 'Negro', imagen_url: p.img }];

  const activeColObj = (catalogColor && coloresList.find(c => c.slug === catalogColor)) || coloresList[0];
  const initialImg = (activeColObj && activeColObj.imagen_url) || p.img;

  const swatchesHTML = coloresList.map(c => {
    const isAct = activeColObj && c.slug === activeColObj.slug;
    const cImg  = c.imagen_url || p.img || '';
    return `<button type="button" class="card-swatch-btn ${isAct ? 'active' : ''}"
              data-card-swatch="${esc(c.slug)}"
              data-card-img="${esc(cImg)}"
              data-color-key="${esc(c.slug)}"
              title="${esc(c.nombre_color)}"
              aria-label="Ver ${esc(p.name)} en color ${esc(c.nombre_color)}"></button>`;
  }).join('');

  return `
  <div class="${col}">
    <div class="product-card" data-product-card="${esc(p.id)}">
      <div class="card-media">
        <a href="#/producto/${esc(p.id)}">${mediaHTML(p, initialImg)}</a>
        <button class="wishlist-btn ${wished ? 'is-active' : ''}" type="button" data-wishlist="${esc(p.id)}" aria-pressed="${wished}" aria-label="Agregar ${esc(p.name)} a favoritos">
          <i class="bi ${wished ? 'bi-heart-fill' : 'bi-heart'}"></i>
        </button>
        <button class="qv-btn" type="button" data-qv="${esc(p.id)}" aria-label="Vista rápida de ${esc(p.name)}">
          Vista Rápida
        </button>
      </div>
      <div class="d-flex flex-column gap-1 flex-grow-1 justify-content-between">
        <div class="d-flex justify-content-between align-items-center gap-2">
          <a href="#/producto/${esc(p.id)}"><h3>${esc(p.name)}</h3></a>
          <div class="card-swatches" role="group" aria-label="Colores disponibles">${swatchesHTML}</div>
        </div>
        <a href="#/producto/${esc(p.id)}" class="d-flex justify-content-between align-items-center gap-2">
          <span class="sizes-meta">${sizesLabel}</span>
          <span class="price">${money(p.price)}</span>
        </a>
      </div>
    </div>
  </div>`;
}

/* ------------------------- Grids y Categorías Reales (GET /api/productos/categorias) ------------------------- */
function skeletonCardsHTML(count = 3, col = 'col-12 col-sm-4'){
  return Array.from({ length: count }, () => `
    <div class="${col}">
      <div class="product-card">
        <div class="card-media"><span class="osm-skel osm-skel--media"></span></div>
        <span class="osm-skel osm-skel--w75 mb-2"></span>
        <span class="osm-skel osm-skel--w45"></span>
      </div>
    </div>`).join('');
}

function renderHomeCategories(){
  const grid = document.getElementById('homeCategoriesGrid');
  if(!grid) return;
  if(!categoriesLoaded && !CATEGORIES.length){
    grid.innerHTML = skeletonCardsHTML(6, 'col-6 col-sm-4 col-lg-2');
    return;
  }
  grid.innerHTML = CATEGORIES.slice(0, 6).map(cat => {
    const slug = esc(cat.slug || cat.id_categoria);
    const name = esc(cat.nombre_categoria);
    const img  = esc(cat.imagen_representativa || 'img/corset-canela.jpg');
    const count = Number(cat.total_productos ?? 0);
    return `
      <div class="col-6 col-sm-4 col-lg-2">
        <button type="button" class="category-card" data-home-cat="${slug}" data-home-cat-id="${Number(cat.id_categoria)}">
          <div class="category-card__media">
            <img src="${img}" alt="${name}" loading="lazy">
          </div>
          <span class="category-card__name">${name}</span>
          <span class="category-card__count">${count} ${count === 1 ? 'pieza' : 'piezas'}</span>
        </button>
      </div>`;
  }).join('');
}

function renderCatalogCategorySidebar(){
  const wrap = document.getElementById('catalogCatFilter');
  if(!wrap || !CATEGORIES.length) return;
  wrap.innerHTML = [
    `<button class="filter-opt ${catalogCategory === 'todos' ? 'active' : ''}" data-cat="todos">Todas las Colecciones</button>`,
    ...CATEGORIES.map(c => {
      const slug = esc(c.slug);
      const isAct = catalogCategory === c.slug || String(catalogCategory) === String(c.id_categoria);
      return `<button class="filter-opt ${isAct ? 'active' : ''}" data-cat="${slug}" data-cat-id="${Number(c.id_categoria)}">${esc(c.nombre_categoria)}</button>`;
    })
  ].join('');
}

function renderHomeRecs(){
  const el = document.getElementById('homeRecsGrid');
  if(!el) return;
  if(!catalogLoaded && !PRODUCTS.length){
    el.innerHTML = skeletonCardsHTML(3, 'col-12 col-sm-4');
    return;
  }
  const picks = ['corset-canela','corset-noir','jeans-wide'];
  const found = picks.map(byId).filter(Boolean);
  const list = found.length ? found : PRODUCTS.slice(0, 3);
  el.innerHTML = list.map(p => cardHTML(p, 'col-12 col-sm-4')).join('');
}

function renderCuration(){
  const el = document.getElementById('curationGrid');
  if(!el) return;
  el.innerHTML = PRODUCTS.slice(0, 4).map(p => cardHTML(p, 'col-6 col-lg-3')).join('');
}

function renderSearchRecs(){
  const el = document.getElementById('searchRecsGrid');
  if(!el) return;
  const picks = ['top-escote','corset-noir'];
  const found = picks.map(byId).filter(Boolean);
  const list = found.length ? found : PRODUCTS.slice(0, 2);
  el.innerHTML = list.map(p => cardHTML(p, 'col-12 col-md-6')).join('');
}

function renderCatalogBanner(){
  const picks = ['body-nocturno','corset-noir'];
  document.getElementById('catalogBannerStrip').innerHTML = picks.map(id => {
    const p = byId(id);
    if(!p) return '';
    return `
    <div class="banner-cell">
      <a href="#/producto/${esc(p.id)}">${mediaHTML(p)}</a>
      <div class="banner-caption">
        <h4>${esc(p.name)}</h4>
        <div class="price">${money(p.price)}</div>
      </div>
    </div>`;
  }).join('');
}

/* ------------------------- Filtros del catálogo ------------------------- */
let catalogCategory = 'todos';
let catalogSizes    = new Set();
let catalogColor    = '';

function renderCatalog(){
  const grid      = document.getElementById('catalogGrid');
  const emptyWrap = document.getElementById('catalogEmptyWrap');
  const countEl   = document.getElementById('catalogResultsCount');

  if(!catalogLoaded && !PRODUCTS.length){
    grid.classList.remove('d-none');
    emptyWrap.classList.add('d-none');
    grid.innerHTML = skeletonCardsHTML(6, 'col-6 col-lg-4');
    countEl.textContent = 'Cargando catálogo…';
    return;
  }

  let list = catalogCategory === 'todos'
    ? PRODUCTS.slice()
    : PRODUCTS.filter(p =>
        p.cat === catalogCategory ||
        String(p.fk_id_categoria) === String(catalogCategory) ||
        (p.nombre_categoria && p.nombre_categoria.toLowerCase() === String(catalogCategory).toLowerCase())
      );

  if(catalogSizes.size) list = list.filter(p => p.sizes.some(s => catalogSizes.has(s)));
  if(catalogColor){
    list = list.filter(p =>
      p.colorKey === catalogColor ||
      (Array.isArray(p.colores) && p.colores.some(c => c.slug === catalogColor))
    );
  }

  if(!list.length){
    grid.innerHTML = '';
    grid.classList.add('d-none');
    emptyWrap.classList.remove('d-none');
    document.getElementById('catalogEmptyTitle').textContent = 'No encontramos prendas con estos filtros';
    document.getElementById('catalogEmptyDesc').textContent  =
      'Prueba con otra talla, color o tipo de prenda, o quita los filtros para ver toda la colección.';
  }else{
    grid.classList.remove('d-none');
    emptyWrap.classList.add('d-none');
    grid.innerHTML = list.map(p => cardHTML(p)).join('');
  }

  countEl.textContent = `Mostrando ${list.length} de ${PRODUCTS.length} piezas`;
  updateWishlistBadgesAndButtons();
}

function initCatalogFilters(){
  document.getElementById('catalogCatFilter').addEventListener('click', e => {
    const btn = e.target.closest('.filter-opt');
    if(!btn) return;
    catalogCategory = btn.dataset.cat;
    document.querySelectorAll('#catalogCatFilter .filter-opt')
      .forEach(el => el.classList.toggle('active', el === btn));
    renderCatalog();
  });

  const homeCatGrid = document.getElementById('homeCategoriesGrid');
  if(homeCatGrid){
    homeCatGrid.addEventListener('click', e => {
      const btn = e.target.closest('[data-home-cat]');
      if(!btn) return;
      catalogCategory = btn.dataset.homeCat || 'todos';
      catalogSizes.clear();
      catalogColor = '';
      renderCatalogCategorySidebar();
      document.querySelectorAll('#catalogCatFilter .filter-opt')
        .forEach(el => el.classList.toggle('active', el.dataset.cat === catalogCategory));
      renderCatalog();
      location.hash = '#/catalogo';
    });
  }

  document.getElementById('catalogSizeFilter').addEventListener('click', e => {
    const chip = e.target.closest('.size-chip');
    if(!chip) return;
    const size = chip.dataset.size;
    if(catalogSizes.has(size)){ catalogSizes.delete(size); chip.classList.remove('active'); }
    else { catalogSizes.add(size); chip.classList.add('active'); }
    renderCatalog();
  });

  document.getElementById('catalogColorFilter').addEventListener('click', e => {
    const dot = e.target.closest('.color-pick');
    if(!dot) return;
    catalogColor = dot.dataset.color;
    document.querySelectorAll('#catalogColorFilter .color-pick')
      .forEach(el => el.classList.toggle('active', el === dot));
    renderCatalog();
  });

  document.getElementById('resetFiltersBtn').addEventListener('click', () => {
    catalogCategory = 'todos';
    catalogSizes.clear();
    catalogColor = '';
    document.querySelectorAll('#catalogCatFilter .filter-opt')
      .forEach(el => el.classList.toggle('active', el.dataset.cat === 'todos'));
    document.querySelectorAll('#catalogSizeFilter .size-chip').forEach(el => el.classList.remove('active'));
    document.querySelectorAll('#catalogColorFilter .color-pick').forEach(el => el.classList.remove('active'));
    renderCatalog();
  });
}

/* ------------------------- Detalle de producto y Variantes en Tiempo Real (RF-CAT-018) ------------------------- */
let currentProduct = null;
let selectedSize   = null;
let selectedColor  = null;

function findActiveVariant(p, size, colorSlug){
  if(!p || !Array.isArray(p.variantes) || !p.variantes.length) return null;
  return p.variantes.find(v =>
    (!size || v.talla === size) &&
    (!colorSlug || v.color_slug === colorSlug)
  ) || p.variantes.find(v => !size || v.talla === size) || p.variantes[0];
}

function renderPdpSizes(p){
  const sizesWrap = document.getElementById('pdpSizes');
  if(!sizesWrap || !p) return;
  sizesWrap.innerHTML = ['XS','S','M','L','XL'].map(s => {
    const varMatch = Array.isArray(p.variantes)
      ? p.variantes.find(v => v.talla === s && (!selectedColor || v.color_slug === selectedColor))
      : null;
    const available = varMatch ? varMatch.stock_disponible > 0 : (Array.isArray(p.sizes) && p.sizes.includes(s));
    return `<button class="size-chip ${available && s === selectedSize ? 'active' : ''}"
             ${available ? '' : 'disabled'} data-size="${esc(s)}">${esc(s)}</button>`;
  }).join('');
}

function updatePdpVariantUI(p){
  if(!p) return;
  const activeVar = findActiveVariant(p, selectedSize, selectedColor);
  const priceVal  = activeVar && activeVar.precio ? activeVar.precio : p.price;
  const skuVal    = activeVar && activeVar.sku ? activeVar.sku : `OSM-${String(p.id).toUpperCase()}`;
  const dispStock = activeVar && typeof activeVar.stock_disponible === 'number'
    ? activeVar.stock_disponible
    : (p.stock_total_disponible ?? 5);

  const coloresList = Array.isArray(p.colores) ? p.colores : [];
  const colorObj = coloresList.find(c => c.slug === selectedColor);
  const variantImg = (activeVar && activeVar.imagen_url) || (colorObj && colorObj.imagen_url) || p.img;

  if(variantImg){
    const mainWrap = document.getElementById('pdpMain');
    if(mainWrap){
      mainWrap.innerHTML = mediaHTML(p, variantImg);
    }
    document.querySelectorAll('#pdpThumbs img').forEach(thumb => {
      thumb.classList.toggle('active', thumb.getAttribute('src') === variantImg);
    });
  }

  document.getElementById('pdpPrice').textContent = money(priceVal);
  const skuEl = document.getElementById('pdpSku');
  if(skuEl) skuEl.textContent = `SKU: ${skuVal}`;

  const addBtn = document.getElementById('addToCartBtn');
  if(dispStock > 0){
    document.getElementById('pdpStock').textContent =
      `Stock disponible: ${dispStock} unidades — Talla ${selectedSize || p.sizes[0]} (${skuVal})`;
    addBtn.disabled = false;
  }else{
    document.getElementById('pdpStock').textContent =
      `Agotado en Talla ${selectedSize || ''} — selecciona otra combinación`;
    addBtn.disabled = true;
  }

  const colorName = (activeVar && activeVar.color) || (colorObj && colorObj.nombre_color) || p.colorName;
  document.getElementById('pdpColorLabel').textContent = `Color: ${colorName}`;
}

async function loadProduct(id){
  let p = byId(id) || PRODUCTS[1];
  try {
    const res = await OneStyleAPI.catalogo.detail(id);
    if(res && res.data){
      p = res.data;
      const idx = PRODUCTS.findIndex(item => item.id === p.id);
      if(idx >= 0) PRODUCTS[idx] = p;
      else PRODUCTS.push(p);
    }
  } catch (_) {}

  currentProduct = p;
  selectedSize   = (p.sizes && p.sizes[0]) || 'S';
  selectedColor  = p.colorKey || 'negro';

  document.getElementById('pdpCrumb').innerHTML =
    `Lujo Importado / ${esc(p.cat.charAt(0).toUpperCase() + p.cat.slice(1))} / <b>${esc(p.name)}</b>`;
  document.getElementById('pdpName').textContent = p.name;
  document.getElementById('pdpDesc').textContent =
    `${p.desc}. Confeccionado con materiales importados de la más alta calidad, una prenda diseñada para la mujer que valora la sofisticación en cada detalle.`;

  const coloresList = Array.isArray(p.colores) && p.colores.length
    ? p.colores
    : [{ slug: p.colorKey, nombre_color: p.colorName, codigo_hex: p.color, imagen_url: p.img }];

  const thumbEntries = [];
  coloresList.forEach(c => {
    const cImg = c.imagen_url || p.img;
    if(cImg && !thumbEntries.some(t => t.img === cImg)){
      thumbEntries.push({ img: cImg, colorSlug: c.slug, label: c.nombre_color });
    }
  });
  while(thumbEntries.length < 3 && p.img){
    thumbEntries.push({ img: p.img, colorSlug: selectedColor, label: p.colorName });
  }

  document.getElementById('pdpMain').innerHTML = mediaHTML(p);
  document.getElementById('pdpThumbs').innerHTML = thumbEntries.slice(0, 3).map((t, i) => `
    <div class="col-4 pdp-thumb">
      <img src="${esc(t.img)}" alt="${esc(p.name)} - ${esc(t.label)}" data-thumb-color="${esc(t.colorSlug)}" class="${i === 0 ? 'active' : ''}" loading="lazy">
    </div>
  `).join('');

  renderPdpSizes(p);

  document.getElementById('pdpColors').innerHTML = coloresList.map(c => `
    <button type="button" class="color-pick ${c.slug === selectedColor ? 'active' : ''}"
            data-color-slug="${esc(c.slug)}" data-color-name="${esc(c.nombre_color)}"
            data-color-img="${esc(c.imagen_url || p.img || '')}"
            title="${esc(c.nombre_color)}"></button>
  `).join('');

  updatePdpVariantUI(p);
  updateWishlistBadgesAndButtons();
}

function initPdp(){
  const sgEl = document.getElementById('sizeGuideModal');
  if(sgEl) sizeGuideModal = new bootstrap.Modal(sgEl);

  const openSgBtn = document.getElementById('openSizeGuideBtn');
  if(openSgBtn && sizeGuideModal){
    openSgBtn.addEventListener('click', () => sizeGuideModal.show());
  }

  const pdpWishBtn = document.getElementById('pdpWishlistBtn');
  if(pdpWishBtn){
    pdpWishBtn.addEventListener('click', () => {
      if(currentProduct) toggleWishlistProduct(currentProduct.id);
    });
  }

  document.getElementById('pdpSizes').addEventListener('click', e => {
    const chip = e.target.closest('.size-chip');
    if(!chip || chip.disabled) return;
    document.querySelectorAll('#pdpSizes .size-chip').forEach(c => c.classList.remove('active'));
    chip.classList.add('active');
    selectedSize = chip.dataset.size;
    updatePdpVariantUI(currentProduct);
  });

  document.getElementById('pdpColors').addEventListener('click', e => {
    const dot = e.target.closest('.color-pick');
    if(!dot || !currentProduct) return;
    document.querySelectorAll('#pdpColors .color-pick').forEach(c => c.classList.remove('active'));
    dot.classList.add('active');
    selectedColor = dot.dataset.colorSlug;
    renderPdpSizes(currentProduct);
    const activeChip = document.querySelector('#pdpSizes .size-chip.active:not(:disabled)') ||
                       document.querySelector('#pdpSizes .size-chip:not(:disabled)');
    if(activeChip){
      activeChip.classList.add('active');
      selectedSize = activeChip.dataset.size;
    }
    updatePdpVariantUI(currentProduct);
  });

  document.getElementById('pdpThumbs').addEventListener('click', e => {
    const img = e.target.closest('img');
    if(!img) return;
    document.querySelectorAll('#pdpThumbs img').forEach(i => i.classList.remove('active'));
    img.classList.add('active');
    const thumbColor = img.getAttribute('data-thumb-color');
    const thumbSrc = img.getAttribute('src');
    if(thumbColor && currentProduct){
      selectedColor = thumbColor;
      document.querySelectorAll('#pdpColors .color-pick').forEach(c => {
        c.classList.toggle('active', c.dataset.colorSlug === thumbColor);
      });
      renderPdpSizes(currentProduct);
      updatePdpVariantUI(currentProduct);
    } else if(thumbSrc && currentProduct){
      document.getElementById('pdpMain').innerHTML = mediaHTML(currentProduct, thumbSrc);
    }
  });

  document.getElementById('addToCartBtn').addEventListener('click', () => {
    if(!currentProduct) return;
    const size = document.querySelector('#pdpSizes .size-chip.active')?.dataset.size || selectedSize || currentProduct.sizes[0];
    const activeVar = findActiveVariant(currentProduct, size, selectedColor);
    const skuLabel  = activeVar && activeVar.sku ? ` (${activeVar.sku})` : '';
    const unitPrice = activeVar && activeVar.precio ? activeVar.precio : currentProduct.price;
    addToCart(
      { ...currentProduct, price: unitPrice, id_variante: activeVar ? activeVar.id_variante : 1 },
      `${currentProduct.colorName} / Talla ${size}${skuLabel}`
    );
  });
}

/* ------------------------- Carrito y Reservas Temporales (RF-CRT-001 a RF-CRT-003) ------------------------- */
let cart = [];
let cartDrawer = null;
let cartTtlSeconds = 0;
let cartTtlInterval = null;

function formatTtl(seconds){
  const s = Math.max(0, Math.floor(seconds));
  const mins = String(Math.floor(s / 60)).padStart(2, '0');
  const secs = String(s % 60).padStart(2, '0');
  return `${mins}:${secs}`;
}

function updateTtlIndicators(){
  const drawerBadge   = document.getElementById('cartDrawerTtlBadge');
  const drawerTimer   = document.getElementById('cartDrawerTtlTimer');
  const checkoutBadge = document.getElementById('checkoutTtlBadge');
  const checkoutTimer = document.getElementById('checkoutTtlTimer');

  if(cart.length > 0 && cartTtlSeconds > 0){
    const label = formatTtl(cartTtlSeconds);
    if(drawerTimer)   drawerTimer.textContent   = label;
    if(checkoutTimer) checkoutTimer.textContent = label;
    if(drawerBadge)   drawerBadge.classList.remove('d-none');
    if(checkoutBadge) checkoutBadge.classList.remove('d-none');
  }else{
    if(drawerBadge)   drawerBadge.classList.add('d-none');
    if(checkoutBadge) checkoutBadge.classList.add('d-none');
  }
}

function startCartTtlCountdown(seconds){
  cartTtlSeconds = Math.max(0, Math.floor(Number(seconds) || 0));
  updateTtlIndicators();
  if(cartTtlInterval) clearInterval(cartTtlInterval);
  if(cartTtlSeconds <= 0) return;

  cartTtlInterval = setInterval(() => {
    if(cartTtlSeconds > 0){
      cartTtlSeconds--;
      updateTtlIndicators();
      if(cartTtlSeconds === 0){
        clearInterval(cartTtlInterval);
        syncCartFromBackend();
      }
    }
  }, 1000);
}

function applyBackendCartSummary(summary){
  if(!summary || !Array.isArray(summary.items)) return;
  cart = summary.items.map(it => ({
    id: it.slug_producto || String(it.fk_id_producto),
    id_variante: it.fk_id_variante,
    name: it.nombre_producto,
    variant: `${it.color} / Talla ${it.talla} (${it.sku})`,
    price: Number(it.precio_unitario_congelado),
    qty: Number(it.cantidad),
    subtotal: Number(it.subtotal),
    img: it.imagen,
    ttl_restante_segundos: Number(it.ttl_restante_segundos || 0)
  }));
  startCartTtlCountdown(summary.ttl_restante_segundos || 0);
  renderCart();
}

async function syncCartFromBackend(){
  try {
    const res = await OneStyleAPI.carrito.get();
    if(res && res.data){
      applyBackendCartSummary(res.data);
    }
  } catch (_) {}
}

async function addToCart(p, variant, triggerBtn = null){
  const drawerErr = document.getElementById('cartDrawerError');
  if(drawerErr) drawerErr.classList.add('d-none');

  const varId = p.id_variante || (Array.isArray(p.variantes) && p.variantes[0] ? p.variantes[0].id_variante : null);
  if(varId){
    try {
      await OneStyleAPI.withButtonLoading(triggerBtn || document.getElementById('addToCartBtn'), 'Reservando stock...', async () => {
        const res = await OneStyleAPI.carrito.addItem({ fk_id_variante: varId, cantidad: 1 });
        if(res && res.data) applyBackendCartSummary(res.data);
        if(currentProduct && currentProduct.id === p.id) await loadProduct(p.id);
      });
      cartDrawer.show();
      return;
    } catch (err) {
      if(drawerErr){
        drawerErr.textContent = err.message || 'No hay suficiente stock disponible.';
        drawerErr.classList.remove('d-none');
      }
      cartDrawer.show();
      return;
    }
  }

  const existing = cart.find(i => i.id === p.id && i.variant === variant);
  if(existing) existing.qty++;
  else cart.push({ id:p.id, name:p.name, variant, price:p.price, qty:1, img:p.img });
  startCartTtlCountdown(900);
  renderCart();
  cartDrawer.show();
}

async function changeQty(idx, delta, btnEl = null){
  const item = cart[idx];
  if(!item) return;
  const drawerErr = document.getElementById('cartDrawerError');
  if(drawerErr) drawerErr.classList.add('d-none');

  const newQty = item.qty + delta;
  if(item.id_variante){
    try {
      await OneStyleAPI.withButtonLoading(btnEl, null, async () => {
        const res = newQty <= 0
          ? await OneStyleAPI.carrito.removeItem(item.id_variante)
          : await OneStyleAPI.carrito.updateItem(item.id_variante, { cantidad: newQty });
        if(res && res.data) applyBackendCartSummary(res.data);
      });
      return;
    } catch (err) {
      if(drawerErr){
        drawerErr.textContent = err.message || 'Conflicto de stock al actualizar cantidad.';
        drawerErr.classList.remove('d-none');
      }
      return;
    }
  }

  item.qty = Math.max(1, newQty);
  renderCart();
}

async function removeItem(idx, btnEl = null){
  const item = cart[idx];
  if(!item) return;
  if(item.id_variante){
    try {
      await OneStyleAPI.withButtonLoading(btnEl, '...', async () => {
        const res = await OneStyleAPI.carrito.removeItem(item.id_variante);
        if(res && res.data) applyBackendCartSummary(res.data);
      });
      return;
    } catch (_) {}
  }
  cart.splice(idx, 1);
  renderCart();
}

function cartTotals(){
  const subtotal = cart.reduce((s, i) => s + i.price * i.qty, 0);
  const shipping = cart.length ? 45000 : 0;
  const tax      = Math.round(subtotal * 0.12 / 1000) * 1000;
  return { subtotal, shipping, tax, total: subtotal + shipping + tax };
}

function itemImg(item, cls = ''){
  return item.img
    ? `<img src="${esc(item.img)}" alt="${esc(item.name)}" class="${esc(cls)}">`
    : `<div class="card-placeholder card-placeholder--fill ${esc(cls)}"><i class="bi bi-bag"></i></div>`;
}

function renderCart(){
  const wrap = document.getElementById('cartItemsWrap');
  if(!cart.length){
    wrap.innerHTML = `<div class="empty-cart">Tu selección está vacía.
      <a href="#/catalogo" class="link-osm text-decoration-underline">Explora la colección</a></div>`;
  }else{
    wrap.innerHTML = cart.map((item, idx) => `
      <div class="cart-item">
        ${itemImg(item)}
        <div>
          <h4>${esc(item.name)}</h4>
          <div class="meta">${esc(item.variant)}</div>
          <div class="qty">
            <button type="button" data-qty="-1" data-idx="${idx}">−</button>
            <span>${Number(item.qty)}</span>
            <button type="button" data-qty="1" data-idx="${idx}">+</button>
          </div>
        </div>
        <div class="text-end">
          <div class="price">${money(item.price * item.qty)}</div>
          <button class="remove" type="button" data-remove="${idx}">Eliminar</button>
        </div>
      </div>`).join('');
  }

  const drawer = document.getElementById('drawerItems');
  if(!cart.length){
    drawer.innerHTML = `<div class="empty-cart">Tu carrito está vacío.<br>
      <a href="#/catalogo" class="link-osm text-decoration-underline" data-bs-dismiss="offcanvas">Explorar colección</a></div>`;
  }else{
    drawer.innerHTML = cart.map((item, idx) => `
      <div class="drawer-item">
        ${itemImg(item)}
        <div>
          <h4>${esc(item.name)}</h4>
          <div class="meta">${esc(item.variant)}</div>
          <div class="d-flex justify-content-between align-items-center">
            <div class="qty">
              <button type="button" data-qty="-1" data-idx="${idx}">−</button>
              <span>${Number(item.qty)}</span>
              <button type="button" data-qty="1" data-idx="${idx}">+</button>
            </div>
            <div class="price">${money(item.price * item.qty)}</div>
          </div>
        </div>
      </div>`).join('');
  }

  const t = cartTotals();
  const totalQty = cart.reduce((s, i) => s + i.qty, 0);
  document.getElementById('sumSubtotal').textContent   = money(t.subtotal);
  document.getElementById('sumShip').textContent       = money(t.shipping);
  document.getElementById('sumTax').textContent        = money(t.tax);
  document.getElementById('sumTotal').textContent      = money(t.total);
  document.getElementById('drawerSubtotal').textContent = money(t.subtotal);
  document.getElementById('cartCount').textContent     = totalQty;
  const drawerTitle = document.getElementById('cartDrawerTitle');
  if(drawerTitle) drawerTitle.textContent = `Tu Bolsa (${totalQty})`;

  const summaryItemsEl = document.getElementById('checkoutSummaryItems');
  if(summaryItemsEl){
    summaryItemsEl.innerHTML = cart.length
      ? cart.map(item => `
          <div class="sum-row mb-2">
            <span>${esc(item.name)} (${esc(item.variant.split(' (')[0])} × ${Number(item.qty)})</span>
            <span>${money(item.price * item.qty)}</span>
          </div>`).join('')
      : `<div class="text-muted small">Sin prendas en la bolsa.</div>`;
  }
  updateTtlIndicators();
}

function initCart(){
  cartDrawer = new bootstrap.Offcanvas('#cartDrawer');
  const wishEl = document.getElementById('wishlistDrawer');
  if(wishEl) wishlistDrawer = new bootstrap.Offcanvas(wishEl);

  const wishBtn = document.getElementById('wishlistBtn');
  if(wishBtn && wishlistDrawer){
    wishBtn.addEventListener('click', () => {
      renderWishlistDrawer();
      wishlistDrawer.show();
    });
  }

  document.getElementById('cartBtn').addEventListener('click', () => {
    syncCartFromBackend();
    cartDrawer.show();
  });

  document.body.addEventListener('click', e => {
    const cardSwatch = e.target.closest('[data-card-swatch]');
    if(cardSwatch){
      e.preventDefault();
      e.stopPropagation();
      const card = cardSwatch.closest('.product-card');
      if(card){
        card.querySelectorAll('[data-card-swatch]').forEach(b => b.classList.toggle('active', b === cardSwatch));
        const imgEl = card.querySelector('.card-media img');
        const newImg = cardSwatch.getAttribute('data-card-img');
        if(imgEl && newImg){
          imgEl.setAttribute('src', newImg);
        }
      }
      return;
    }
    const wishToggle = e.target.closest('[data-wishlist]');
    if(wishToggle){
      e.preventDefault();
      e.stopPropagation();
      toggleWishlistProduct(wishToggle.getAttribute('data-wishlist'));
      return;
    }
    const wishRm = e.target.closest('[data-wishlist-remove]');
    if(wishRm){
      e.preventDefault();
      toggleWishlistProduct(wishRm.getAttribute('data-wishlist-remove'));
      return;
    }
    const qtyBtn = e.target.closest('[data-qty]');
    if(qtyBtn){ changeQty(+qtyBtn.dataset.idx, +qtyBtn.dataset.qty, qtyBtn); return; }
    const rmBtn = e.target.closest('[data-remove]');
    if(rmBtn){ removeItem(+rmBtn.dataset.remove, rmBtn); }
  });

  document.getElementById('drawerCheckoutBtn').addEventListener('click', () => cartDrawer.hide());
  document.getElementById('completeOrderBtn').addEventListener('click', completeOrder);
}

async function completeOrder(){
  const err = document.getElementById('checkoutError');
  err.classList.add('d-none');

  if(!cart.length){
    err.textContent = 'Tu selección está vacía. Añade una prenda antes de completar el pedido.';
    err.classList.remove('d-none');
    return;
  }

  const nombre_receptor = document.getElementById('shipName').value.trim();
  const email           = document.getElementById('shipEmail').value.trim();
  const direccion_envio = document.getElementById('shipAddress').value.trim();
  const barrioEl        = document.getElementById('shipBarrio');
  const barrio          = (barrioEl && barrioEl.value.trim()) || 'Centro';
  const telefono        = document.getElementById('shipPhone').value.trim();
  const ciudad          = document.getElementById('shipCity').value.trim();
  const notesEl         = document.getElementById('shipNotes');
  const observaciones   = (notesEl && notesEl.value.trim()) || '';

  if(!nombre_receptor || !email || !direccion_envio || !barrio || !telefono || !ciudad){
    err.textContent = 'Completa nombre, correo, dirección, barrio, teléfono y ciudad para continuar (RN-CRT-003).';
    err.classList.remove('d-none');
    return;
  }

  const btn = document.getElementById('completeOrderBtn');
  await OneStyleAPI.withButtonLoading(btn, 'Procesando Pedido...', async () => {
    let orden = null;
    try {
      const res = await OneStyleAPI.pedidos.checkout({
        direccion_envio,
        barrio,
        ciudad,
        telefono,
        observaciones,
        nombre_receptor,
        email,
        metodo_entrega: 'Domicilio Express'
      });
      orden = res && res.data ? res.data : null;
    } catch (apiErr) {
      err.textContent = apiErr.message || 'Error al procesar y consolidar el pedido.';
      err.classList.remove('d-none');
      return;
    }

    const orderId = (orden && orden.codigo_orden) || ('ORD-' + Math.floor(10000 + Math.random() * 89999));
    cart = [];
    cartTtlSeconds = 0;
    renderCart();

    if(orden){
      renderOrderConfirmationCard(orden);
    }

    location.hash = '#/seguimiento';
    document.getElementById('trackOrderId').value = orderId;
    document.getElementById('trackContact').value = email;
    document.getElementById('trackAddress').textContent = `${direccion_envio} (${barrio}), ${ciudad}`;
    await runTracking();
  });
}

function renderOrderConfirmationCard(orden){
  const card  = document.getElementById('orderConfirmCard');
  const code  = document.getElementById('confirmOrderCode');
  const total = document.getElementById('confirmOrderTotal');
  const items = document.getElementById('confirmOrderItems');
  const waBtn = document.getElementById('whatsappConciergeBtn');
  if(!card || !orden) return;

  code.textContent  = orden.codigo_orden || `ORD-${orden.id_pedido}`;
  total.textContent = money(orden.total || 0);
  if(Array.isArray(orden.detalle_items)){
    items.innerHTML = orden.detalle_items.map(it =>
      `<div class="d-flex justify-content-between py-1 border-bottom">
         <span>${esc(it.nombre_producto)} <small class="text-muted">(${esc(it.color)} / ${esc(it.talla)} × ${Number(it.cantidad)})</small></span>
         <strong>${money(it.subtotal)}</strong>
       </div>`
    ).join('');
  }
  if(waBtn && orden.url_comprobante_whatsapp){
    waBtn.setAttribute('href', orden.url_comprobante_whatsapp);
  }
  card.classList.remove('d-none');
}

/* ------------------------- Vista rápida ------------------------- */
let qvModal = null;
let qvProduct = null;

function openQuickView(id){
  const p = byId(id);
  if(!p) return;
  qvProduct = p;

  document.getElementById('qvImage').innerHTML   = mediaHTML(p);
  document.getElementById('qvName').textContent  = p.name;
  document.getElementById('qvPrice').textContent = money(p.price);
  document.getElementById('qvColorDot').setAttribute('data-color-key', p.colorKey || '');
  document.getElementById('qvColorName').textContent = `Color: ${p.colorName}`;
  document.getElementById('qvDesc').textContent  = p.desc + '.';
  document.getElementById('qvFullLink').setAttribute('href', `#/producto/${p.id}`);

  document.getElementById('qvSizes').innerHTML = ['XS','S','M','L','XL'].map(s => {
    const available = p.sizes.includes(s);
    return `<button class="size-chip ${available && s === p.sizes[0] ? 'active' : ''}"
             ${available ? '' : 'disabled'} data-size="${esc(s)}">${esc(s)}</button>`;
  }).join('');

  qvModal.show();
}

function initQuickView(){
  qvModal = new bootstrap.Modal('#quickViewModal');

  document.body.addEventListener('click', e => {
    const btn = e.target.closest('[data-qv]');
    if(btn){ e.preventDefault(); openQuickView(btn.dataset.qv); }
  });

  document.getElementById('qvSizes').addEventListener('click', e => {
    const chip = e.target.closest('.size-chip');
    if(!chip || chip.disabled) return;
    document.querySelectorAll('#qvSizes .size-chip').forEach(c => c.classList.remove('active'));
    chip.classList.add('active');
  });

  document.getElementById('qvAddBtn').addEventListener('click', () => {
    if(!qvProduct) return;
    const size = document.querySelector('#qvSizes .size-chip.active')?.dataset.size || qvProduct.sizes[0];
    qvModal.hide();
    addToCart(qvProduct, `${qvProduct.colorName} / Talla ${size}`);
  });

  document.getElementById('qvFullLink').addEventListener('click', () => qvModal.hide());
}

/* ------------------------- Búsqueda ------------------------- */
const normalize = s => s.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');

function runSearch(){
  const term = document.getElementById('searchInput').value.trim();
  const resultsWrap = document.getElementById('searchResultsWrap');
  const emptyWrap   = document.getElementById('searchEmptyWrap');

  if(!term){ clearSearch(); return; }

  const q = normalize(term);
  const results = PRODUCTS.filter(p =>
    normalize(p.name).includes(q) ||
    normalize(p.desc).includes(q) ||
    normalize(p.cat).includes(q)  ||
    normalize(p.colorName).includes(q));

  if(results.length){
    resultsWrap.classList.remove('d-none');
    emptyWrap.classList.add('d-none');
    document.getElementById('searchHeading').textContent = `Resultados para: "${term}"`;
    document.getElementById('searchCount').textContent =
      `${results.length} ${results.length === 1 ? 'resultado encontrado' : 'resultados encontrados'}`;
    document.getElementById('searchGrid').innerHTML = results.map(p => cardHTML(p)).join('');
  }else{
    resultsWrap.classList.add('d-none');
    emptyWrap.classList.remove('d-none');
    document.getElementById('noResultsHeading').textContent = `No encontramos resultados para "${term}"`;
  }
}

function clearSearch(){
  document.getElementById('searchInput').value = '';
  document.getElementById('searchResultsWrap').classList.add('d-none');
  document.getElementById('searchEmptyWrap').classList.remove('d-none');
  document.getElementById('noResultsHeading').textContent = 'No encontramos resultados';
}

function initSearch(){
  document.getElementById('searchBtn').addEventListener('click', runSearch);
  document.getElementById('searchInput').addEventListener('keydown', e => {
    if(e.key === 'Enter'){ e.preventDefault(); runSearch(); }
  });
  document.getElementById('clearSearchBtn').addEventListener('click', clearSearch);
}

/* ------------------------- Seguimiento en Tiempo Real y FSM (RF-PED-003) ------------------------- */
function applyTrackingStateUI(orden){
  const stage = Number(orden.etapa_fsm ?? 1);
  const stateBadge = document.getElementById('trackCurrentState');
  if(stateBadge){
    stateBadge.textContent = orden.estado || 'Registrado';
    stateBadge.className = stage === 0 ? 'badge bg-danger' : 'badge bg-dark';
  }

  document.querySelectorAll('#trackSteps .step').forEach(stepEl => {
    const s = Number(stepEl.dataset.step);
    stepEl.classList.remove('done', 'current');
    if(stage === 0) return;
    if(s < stage) stepEl.classList.add('done');
    else if(s === stage) stepEl.classList.add('current');
  });

  const desp = orden.datos_despacho || {};
  if(desp.direccion_envio){
    document.getElementById('trackAddress').textContent =
      `${desp.direccion_envio}${desp.barrio ? ' (' + desp.barrio + ')' : ''}, ${desp.ciudad || ''}`;
  }
  const hist = Array.isArray(orden.historial) && orden.historial.length
    ? orden.historial[orden.historial.length - 1]
    : null;
  const lastUpd = document.getElementById('trackLastUpdate');
  if(lastUpd && hist){
    lastUpd.textContent = `${hist.estado} — ${hist.motivo_cambio || 'Actualizado en OMS'}`;
  }
}

async function runTracking(){
  const id = document.getElementById('trackOrderId').value.trim();
  const contact = document.getElementById('trackContact').value.trim();
  const errEl = document.getElementById('trackError');
  if(errEl) errEl.classList.add('d-none');

  if(!id){ document.getElementById('trackOrderId').focus(); return; }

  const btn = document.getElementById('trackBtn');
  await OneStyleAPI.withButtonLoading(btn, 'Consultando...', async () => {
    try {
      const res = await OneStyleAPI.pedidos.track(id, contact);
      if(res && res.data){
        document.getElementById('trackResultId').textContent = 'Pedido ' + (res.data.codigo_orden || id.toUpperCase());
        applyTrackingStateUI(res.data);
        document.getElementById('trackResult').classList.remove('d-none');
        return;
      }
    } catch (err) {
      if(err.status === 403 && errEl){
        errEl.textContent = err.message;
        errEl.classList.remove('d-none');
        return;
      }
    }
    document.getElementById('trackResultId').textContent = 'Pedido ' + id.toUpperCase();
    document.getElementById('trackResult').classList.remove('d-none');
  });
}

function initTracking(){
  document.getElementById('trackBtn').addEventListener('click', runTracking);
}

/* ------------------------- Módulo 1 y 4: Cuenta, Seguridad y Panel OMS ------------------------- */
let currentUser = OneStyleAPI.getSavedUser();
let recoveryModal = null;
let profileModal  = null;
let omsModal      = null;

function showError(id, msg){
  const el = document.getElementById(id);
  if(!el) return;
  el.textContent = msg;
  el.classList.remove('d-none');
}

function resetAccountView(){
  document.getElementById('accountForms').classList.remove('d-none');
  document.getElementById('authSuccess').classList.add('d-none');
  document.getElementById('loginError').classList.add('d-none');
  document.getElementById('registerError').classList.add('d-none');
}

function finishAuth(title, sub){
  document.getElementById('accountForms').classList.add('d-none');
  document.getElementById('authSuccessTitle').textContent = title;
  document.getElementById('authSuccessSub').textContent   = sub;
  document.getElementById('authSuccess').classList.remove('d-none');
  updateAccountUI();
}

function updateAccountUI(){
  const label   = document.getElementById('accountLabel');
  const icon    = document.getElementById('accountIcon');
  const roleEl  = document.getElementById('accountMenuRole');
  const omsItem = document.getElementById('omsMenuItem');
  if(currentUser){
    const displayName = currentUser.nombre || currentUser.name || currentUser.email;
    label.textContent = displayName.split(' ')[0];
    icon.className = 'bi bi-person-fill';
    document.getElementById('accountMenuName').textContent =
      `${currentUser.nombre || ''} ${currentUser.apellido || ''}`.trim() || displayName;
    if(roleEl) roleEl.textContent = currentUser.rol || 'Clienta';
    if(omsItem){
      const isStaff = currentUser.rol === 'Administradora' || currentUser.rol === 'Vendedora';
      omsItem.classList.toggle('d-none', !isStaff);
    }
  }else{
    label.textContent = 'Iniciar Sesión';
    icon.className = 'bi bi-person';
    if(roleEl) roleEl.textContent = '';
    if(omsItem) omsItem.classList.add('d-none');
  }
}

function initAccount(){
  const menu = new bootstrap.Dropdown(document.getElementById('accountBtn'));
  recoveryModal = new bootstrap.Modal('#recoveryModal');
  profileModal  = new bootstrap.Modal('#profileModal');

  document.getElementById('accountBtn').addEventListener('click', e => {
    if(currentUser){ menu.toggle(); }
    else { e.preventDefault(); location.hash = '#/cuenta'; }
  });

  // 1. Inicio de Sesión Seguro (RF-SEG-008)
  document.getElementById('loginForm').addEventListener('submit', async e => {
    e.preventDefault();
    document.getElementById('loginError').classList.add('d-none');
    const email      = document.getElementById('loginUser').value.trim();
    const contrasena = document.getElementById('loginPassword').value;
    const btn        = document.getElementById('loginBtn');

    if(!email || !contrasena){
      showError('loginError', 'Ingresa tu correo electrónico y contraseña.');
      return;
    }

    await OneStyleAPI.withButtonLoading(btn, 'Verificando...', async () => {
      try {
        const res = await OneStyleAPI.auth.login({ email, contrasena });
        currentUser = res.data.usuario;
        OneStyleAPI.setSession(res.data.token, currentUser, {
          refreshToken: res.data.refresh_token,
          expiresIn: res.data.expires_in
        });
        if(window.OSM && OSM.toast){
          OSM.toast.success(`Bienvenida de nuevo, ${currentUser.nombre}.`);
        }
        finishAuth('¡Bienvenida de nuevo!', `Iniciaste sesión como ${currentUser.nombre} (${currentUser.rol}).`);
        if(currentUser.rol === 'Administradora' || currentUser.rol === 'Vendedora'){
          location.hash = '#/admin';
        }
      } catch (err) {
        showError('loginError', err.message || 'Credenciales inválidas.');
      }
    });
  });

  // 2. Auto-registro de Clienta (RF-SEG-007)
  document.getElementById('registerForm').addEventListener('submit', async e => {
    e.preventDefault();
    document.getElementById('registerError').classList.add('d-none');
    const nombre     = document.getElementById('regName').value.trim();
    const apellido   = document.getElementById('regApellido').value.trim();
    const email      = document.getElementById('regEmail').value.trim();
    const telefono   = document.getElementById('regTelefono').value.trim();
    const contrasena = document.getElementById('regPassword').value;
    const p2         = document.getElementById('regPassword2').value;
    const btn        = document.getElementById('registerBtn');

    if(!nombre || !apellido || !email || !contrasena || !p2){
      showError('registerError', 'Completa todos los campos obligatorios.');
      return;
    }
    if(!email.includes('@')){
      showError('registerError', 'Ingresa un correo electrónico válido.');
      return;
    }
    if(contrasena.length < 8){
      showError('registerError', 'La contraseña debe tener al menos 8 caracteres (RN-SEG-008).');
      return;
    }
    if(contrasena !== p2){
      showError('registerError', 'Las contraseñas no coinciden.');
      return;
    }

    await OneStyleAPI.withButtonLoading(btn, 'Registrando...', async () => {
      try {
        const res = await OneStyleAPI.auth.register({ nombre, apellido, email, contrasena, telefono });
        currentUser = res.data.usuario;
        OneStyleAPI.setSession(res.data.token, currentUser, {
          refreshToken: res.data.refresh_token,
          expiresIn: res.data.expires_in
        });
        if(window.OSM && OSM.toast){
          OSM.toast.success(`Cuenta creada exitosamente, ${currentUser.nombre}.`);
        }
        finishAuth('¡Cuenta creada!', `Bienvenida a OneStyleMariana, ${currentUser.nombre}.`);
      } catch (err) {
        showError('registerError', err.message || 'No fue posible completar el registro.');
      }
    });
  });

  // 3. Cierre de Sesión Seguro (RF-SEG-009)
  document.getElementById('logoutBtn').addEventListener('click', async () => {
    try {
      await OneStyleAPI.auth.logout();
    } catch (_) {}
    OneStyleAPI.clearSession();
    currentUser = null;
    updateAccountUI();
    location.hash = '#/';
  });

  // 4. Recuperación y Restablecimiento de Contraseña (RF-SEG-016 / RF-SEG-017)
  document.getElementById('forgotLink').addEventListener('click', e => {
    e.preventDefault();
    document.getElementById('recoveryError').classList.add('d-none');
    document.getElementById('recoverySuccess').classList.add('d-none');
    document.getElementById('resetPasswordForm').classList.add('d-none');
    recoveryModal.show();
  });

  document.getElementById('forgotPasswordForm').addEventListener('submit', async e => {
    e.preventDefault();
    const errEl = document.getElementById('recoveryError');
    const okEl  = document.getElementById('recoverySuccess');
    errEl.classList.add('d-none');
    okEl.classList.add('d-none');

    const email = document.getElementById('recEmail').value.trim();
    const btn   = document.getElementById('sendRecoveryBtn');
    if(!email){ showError('recoveryError', 'Ingresa tu correo registrado.'); return; }

    await OneStyleAPI.withButtonLoading(btn, 'Enviando...', async () => {
      try {
        const res = await OneStyleAPI.auth.forgotPassword({ email });
        okEl.textContent = res.message;
        okEl.classList.remove('d-none');
        document.getElementById('resetPasswordForm').classList.remove('d-none');
        if(res.data && res.data.reset_token_demo){
          document.getElementById('recToken').value = res.data.reset_token_demo;
        }
      } catch (err) {
        showError('recoveryError', err.message);
      }
    });
  });

  document.getElementById('resetPasswordForm').addEventListener('submit', async e => {
    e.preventDefault();
    const errEl = document.getElementById('recoveryError');
    const okEl  = document.getElementById('recoverySuccess');
    errEl.classList.add('d-none');
    okEl.classList.add('d-none');

    const token          = document.getElementById('recToken').value.trim();
    const nueva_password = document.getElementById('recNewPassword').value;
    const btn            = document.getElementById('confirmResetBtn');

    await OneStyleAPI.withButtonLoading(btn, 'Actualizando...', async () => {
      try {
        const res = await OneStyleAPI.auth.resetPassword({ token, nueva_password });
        okEl.textContent = res.message;
        okEl.classList.remove('d-none');
        document.getElementById('resetPasswordForm').classList.add('d-none');
      } catch (err) {
        showError('recoveryError', err.message);
      }
    });
  });

  // 5. Consulta y Actualización de Perfil (RF-SEG-010 / RF-SEG-011)
  document.getElementById('openProfileBtn').addEventListener('click', async () => {
    document.getElementById('profileError').classList.add('d-none');
    document.getElementById('profileSuccess').classList.add('d-none');
    try {
      const res = await OneStyleAPI.auth.getProfile();
      const u = res.data;
      document.getElementById('profNombre').value   = u.nombre || '';
      document.getElementById('profApellido').value = u.apellido || '';
      document.getElementById('profEmail').value    = u.email || '';
      document.getElementById('profTelefono').value = u.telefono || '';
      profileModal.show();
    } catch (err) {
      OneStyleAPI.clearSession();
      currentUser = null;
      updateAccountUI();
      location.hash = '#/cuenta';
    }
  });

  document.getElementById('profileForm').addEventListener('submit', async e => {
    e.preventDefault();
    const errEl = document.getElementById('profileError');
    const okEl  = document.getElementById('profileSuccess');
    errEl.classList.add('d-none');
    okEl.classList.add('d-none');

    const nombre   = document.getElementById('profNombre').value.trim();
    const apellido = document.getElementById('profApellido').value.trim();
    const email    = document.getElementById('profEmail').value.trim();
    const telefono = document.getElementById('profTelefono').value.trim();
    const btn      = document.getElementById('saveProfileBtn');

    await OneStyleAPI.withButtonLoading(btn, 'Guardando...', async () => {
      try {
        const res = await OneStyleAPI.auth.updateProfile({ nombre, apellido, email, telefono });
        currentUser = res.data;
        OneStyleAPI.setSession(OneStyleAPI.getToken(), currentUser);
        updateAccountUI();
        okEl.textContent = res.message;
        okEl.classList.remove('d-none');
      } catch (err) {
        showError('profileError', err.message);
      }
    });
  });

  // 6. Panel Administrativo OMS — Gestión de Pedidos y FSM (RF-PED-002 / RF-PED-004)
  const omsEl = document.getElementById('omsModal');
  if(omsEl) omsModal = new bootstrap.Modal(omsEl);

  const openOmsBtn = document.getElementById('openOmsBtn');
  if(openOmsBtn){
    openOmsBtn.addEventListener('click', () => {
      location.hash = '#/admin';
    });
  }

  const omsBody = document.getElementById('omsTableBody');
  if(omsBody){
    omsBody.addEventListener('click', async e => {
      const btn = e.target.closest('[data-oms-transition]');
      if(!btn) return;
      const pid = Number(btn.dataset.pedidoId);
      const nextState = btn.dataset.omsTransition;
      const errEl = document.getElementById('omsError');
      const okEl  = document.getElementById('omsSuccess');
      if(errEl) errEl.classList.add('d-none');
      if(okEl)  okEl.classList.add('d-none');

      await OneStyleAPI.withButtonLoading(btn, '...', async () => {
        try {
          const res = await OneStyleAPI.pedidos.adminTransition(pid, {
            nuevo_estado: nextState,
            motivo: `Cambio ejecutado desde Panel OMS a ${nextState}`
          });
          if(okEl){
            okEl.textContent = res.message;
            okEl.classList.remove('d-none');
          }
          await loadOmsDashboard();
          await syncCatalogFromBackend();
        } catch (err) {
          if(errEl){
            errEl.textContent = err.message || 'Transición no permitida por la Máquina de Estados.';
            errEl.classList.remove('d-none');
          }
        }
      });
    });
  }
}

async function loadOmsDashboard(){
  const tbody = document.getElementById('omsTableBody');
  const kpiCount = document.getElementById('omsKpiCount');
  const kpiRev   = document.getElementById('omsKpiRevenue');
  if(!tbody) return;

  try {
    const res = await OneStyleAPI.pedidos.adminReport();
    const rep = (res && res.data) || {};
    const list = Array.isArray(rep.pedidos) ? rep.pedidos : [];
    if(kpiCount) kpiCount.textContent = String(rep.total_pedidos || list.length);
    if(kpiRev)   kpiRev.textContent   = money(rep.ingresos_totales || 0);

    if(!list.length){
      tbody.innerHTML = '<tr><td colspan="6" class="text-center text-muted py-4">Sin pedidos registrados.</td></tr>';
      return;
    }

    const nextStateByStage = {
      1: 'Confirmado',
      2: 'En Empaque',
      3: 'Despachado',
      4: 'Entregado'
    };

    tbody.innerHTML = list.map(p => {
      const stage = Number(p.etapa_fsm ?? 1);
      const nextState = nextStateByStage[stage] || null;
      const canCancel = stage === 1 || stage === 2;
      const desp = p.datos_despacho || {};
      const itemsText = (p.detalle_items || [])
        .map(i => `${esc(i.nombre_producto)} (${esc(i.talla)}) ×${Number(i.cantidad)}`)
        .join(', ');

      return `
        <tr>
          <td class="fw-semibold">${esc(p.codigo_orden)}</td>
          <td>
            <div>${esc(desp.nombre_receptor || 'Cliente')}</div>
            <small class="text-muted">${esc(desp.direccion_envio || '')}, ${esc(desp.ciudad || '')}</small>
          </td>
          <td>${itemsText || '—'}</td>
          <td class="fw-semibold">${money(p.total)}</td>
          <td><span class="badge ${stage === 0 ? 'bg-danger' : 'bg-dark'}">${esc(p.estado)}</span></td>
          <td class="text-end">
            ${nextState ? `<button type="button" class="btn btn-sm btn-dark me-1" data-pedido-id="${Number(p.id_pedido)}" data-oms-transition="${esc(nextState)}">Avanzar a ${esc(nextState)}</button>` : ''}
            ${canCancel ? `<button type="button" class="btn btn-sm btn-outline-danger" data-pedido-id="${Number(p.id_pedido)}" data-oms-transition="Cancelado">Cancelar</button>` : ''}
            ${!nextState && !canCancel ? '<span class="text-muted small">Estado final</span>' : ''}
          </td>
        </tr>`;
    }).join('');
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" class="text-center text-danger py-3">${esc(err.message || 'No autorizado para consultar OMS.')}</td></tr>`;
  }
}

/* ------------------------- Módulo 5: Centro de Ayuda y FAQ (RF-FAQ-001 a RF-FAQ-011) ------------------------- */
let activeFaqCat = 'todas';

async function loadFaqsPublicas(){
  const accEl   = document.getElementById('faqAccordion');
  const catWrap = document.getElementById('faqCatFilter');
  const qInput  = document.getElementById('faqSearchInput');
  const waBtn   = document.getElementById('faqWhatsappBtn');
  if(!accEl) return;

  const q = qInput ? qInput.value.trim() : '';
  try {
    const res = await OneStyleAPI.faqs.list({
      categoria: activeFaqCat !== 'todas' ? activeFaqCat : '',
      q
    });
    const payload = (res && res.data) || {};
    const items = Array.isArray(payload.items) ? payload.items : [];
    const cats  = Array.isArray(payload.categorias) ? payload.categorias : [];

    if(waBtn && payload.canal_soporte && payload.canal_soporte.whatsapp_url){
      waBtn.setAttribute('href', payload.canal_soporte.whatsapp_url);
    }

    if(catWrap && cats.length && catWrap.children.length <= 1){
      catWrap.innerHTML = [
        `<button type="button" class="size-chip ${activeFaqCat === 'todas' ? 'active' : ''}" data-faq-cat="todas">Todas</button>`,
        ...cats.map(c =>
          `<button type="button" class="size-chip ${activeFaqCat === String(c.id_categoria) ? 'active' : ''}" data-faq-cat="${esc(c.id_categoria)}">${esc(c.nombre)}</button>`
        )
      ].join('');
    }

    if(!items.length){
      accEl.innerHTML = `<div class="text-muted py-4 text-center">No encontramos preguntas frecuentes para tu filtro. Escríbenos mediante el formulario de soporte.</div>`;
      return;
    }

    accEl.innerHTML = items.map((f, idx) => `
      <div class="accordion-item">
        <h2 class="accordion-header">
          <button class="accordion-button ${idx === 0 ? '' : 'collapsed'}" type="button" data-bs-toggle="collapse" data-bs-target="#faqCollapse${Number(f.id_faq)}">
            <div>
              <small class="text-muted d-block">${esc(f.categoria)}</small>
              <span>${esc(f.pregunta)}</span>
            </div>
          </button>
        </h2>
        <div id="faqCollapse${Number(f.id_faq)}" class="accordion-collapse collapse ${idx === 0 ? 'show' : ''}" data-bs-parent="#faqAccordion">
          <div class="accordion-body">
            <p class="mb-3">${esc(f.respuesta)}</p>
            <div class="d-flex justify-content-between align-items-center small text-muted border-top pt-2">
              <span>¿Te resultó útil esta respuesta?</span>
              <div class="d-flex gap-2">
                <button type="button" class="btn btn-sm btn-outline-dark py-0 px-2" data-faq-vote="true" data-faq-id="${Number(f.id_faq)}">
                  <i class="bi bi-hand-thumbs-up me-1"></i>Sí (<span id="faqHelpYes${Number(f.id_faq)}">${Number(f.helpful_count || 0)}</span>)
                </button>
                <button type="button" class="btn btn-sm btn-outline-secondary py-0 px-2" data-faq-vote="false" data-faq-id="${Number(f.id_faq)}">
                  <i class="bi bi-hand-thumbs-down me-1"></i>No (<span id="faqHelpNo${Number(f.id_faq)}">${Number(f.not_helpful_count || 0)}</span>)
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    `).join('');
  } catch (_) {}
}

function initFaqHelpCenter(){
  const searchBtn   = document.getElementById('faqSearchBtn');
  const searchInput = document.getElementById('faqSearchInput');
  const catWrap     = document.getElementById('faqCatFilter');
  const accEl       = document.getElementById('faqAccordion');
  const contactForm = document.getElementById('supportContactForm');

  if(searchBtn) searchBtn.addEventListener('click', loadFaqsPublicas);
  if(searchInput){
    searchInput.addEventListener('input', loadFaqsPublicas);
  }

  if(catWrap){
    catWrap.addEventListener('click', e => {
      const btn = e.target.closest('[data-faq-cat]');
      if(!btn) return;
      activeFaqCat = btn.dataset.faqCat;
      catWrap.querySelectorAll('[data-faq-cat]').forEach(el => el.classList.toggle('active', el === btn));
      loadFaqsPublicas();
    });
  }

  if(accEl){
    accEl.addEventListener('click', async e => {
      const voteBtn = e.target.closest('[data-faq-vote]');
      if(!voteBtn) return;
      const fid = Number(voteBtn.dataset.faqId);
      const helpful = voteBtn.dataset.faqVote === 'true';
      await OneStyleAPI.withButtonLoading(voteBtn, null, async () => {
        try {
          const res = await OneStyleAPI.faqs.vote(fid, helpful);
          if(res && res.data){
            const yesEl = document.getElementById('faqHelpYes' + fid);
            const noEl  = document.getElementById('faqHelpNo' + fid);
            if(yesEl) yesEl.textContent = String(res.data.helpful_count);
            if(noEl)  noEl.textContent  = String(res.data.not_helpful_count);
          }
        } catch (_) {}
      });
    });
  }

  if(contactForm){
    contactForm.addEventListener('submit', async e => {
      e.preventDefault();
      const errEl = document.getElementById('supportError');
      const okEl  = document.getElementById('supportSuccess');
      errEl.classList.add('d-none');
      okEl.classList.add('d-none');

      const nombre       = document.getElementById('supName').value.trim();
      const email        = document.getElementById('supEmail').value.trim();
      const codigo_orden = document.getElementById('supOrderCode').value.trim();
      const asunto       = document.getElementById('supSubject').value.trim();
      const mensaje      = document.getElementById('supMessage').value.trim();
      const btn          = document.getElementById('sendSupportBtn');

      if(!nombre || !email || !asunto || !mensaje){
        errEl.textContent = 'Completa tu nombre, correo electrónico, asunto y mensaje.';
        errEl.classList.remove('d-none');
        return;
      }

      await OneStyleAPI.withButtonLoading(btn, 'Enviando...', async () => {
        try {
          const res = await OneStyleAPI.faqs.sendContact({ nombre, email, codigo_orden, asunto, mensaje });
          okEl.textContent = `${res.message} (Ticket #${res.data.id_ticket})`;
          okEl.classList.remove('d-none');
          contactForm.reset();
        } catch (err) {
          errEl.textContent = err.message || 'No fue posible registrar tu solicitud.';
          errEl.classList.remove('d-none');
        }
      });
    });
  }
}

/* ------------------------- Router ------------------------- */
const ROUTES = ['catalogo','checkout','buscar','seguimiento','cuenta','ayuda','admin'];

function currentRoute(){
  const h = location.hash.replace(/^#\/?/, '');
  if(!h) return { name:'home' };
  const parts = h.split('/');
  if(parts[0] === 'producto') return { name:'pdp', id:parts[1] };
  if(parts[0] === 'admin')    return { name:'admin', sub:parts[1] || 'resumen' };
  if(ROUTES.includes(parts[0])) return { name:parts[0] };
  return { name:'404' };
}

function render(){
  const r = currentRoute();

  // Protección RBAC para ruta SPA #/admin
  if(r.name === 'admin'){
    currentUser = OneStyleAPI.getSavedUser();
    if(!currentUser || !OneStyleAPI.getToken()){
      if(window.OSM && OSM.toast){
        OSM.toast.warning('Inicia sesión con tu cuenta administrativa para acceder al panel.');
      }
      location.hash = '#/cuenta';
      return;
    }
    if(currentUser.rol !== 'Administradora' && currentUser.rol !== 'Vendedora'){
      if(window.OSM && OSM.toast){
        OSM.toast.error('Acceso restringido: esta sección es exclusiva para personal autorizado.');
      }
      location.hash = '#/';
      return;
    }
  }

  document.body.classList.toggle('is-admin', r.name === 'admin');
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  const el = document.getElementById('view-' + r.name) || document.getElementById('view-404');
  el.classList.add('active');

  document.querySelectorAll('.nav-route').forEach(a =>
    a.classList.toggle('active', a.dataset.route === r.name));

  if(r.name === 'pdp')    loadProduct(r.id);
  if(r.name === 'cuenta') resetAccountView();
  if(r.name === 'ayuda')  loadFaqsPublicas();
  if(r.name === 'admin' && window.OSM && OSM.admin) OSM.admin.open(r.sub);

  const nav = document.getElementById('mainNav');
  if(nav.classList.contains('show')) bootstrap.Collapse.getOrCreateInstance(nav).hide();

  window.scrollTo({ top:0, behavior:'instant' });
}

/* ------------------------- Arranque ------------------------- */
window.addEventListener('hashchange', render);

window.addEventListener('osm:session-expired', () => {
  currentUser = null;
  updateAccountUI();
  if(window.OSM && OSM.toast){
    OSM.toast.warning('Tu sesión ha expirado por seguridad. Inicia sesión nuevamente.');
  }
  location.hash = '#/cuenta';
});

async function syncCatalogFromBackend(){
  try {
    const [prodRes, catRes] = await Promise.all([
      OneStyleAPI.catalogo.list({ per_page: 50 }),
      OneStyleAPI.catalogo.categories()
    ]);
    catalogLoaded = true;
    categoriesLoaded = true;

    if(catRes && Array.isArray(catRes.data)){
      CATEGORIES.splice(0, CATEGORIES.length, ...catRes.data);
      renderHomeCategories();
      renderCatalogCategorySidebar();
    }

    if(prodRes && prodRes.data && Array.isArray(prodRes.data.items)){
      PRODUCTS.splice(0, PRODUCTS.length, ...prodRes.data.items);
      renderHomeRecs();
      renderCatalog();
      renderCatalogBanner();
      renderCuration();
      renderSearchRecs();
      renderWishlistDrawer();
      const r = currentRoute();
      if(r.name === 'pdp') loadProduct(r.id);
    }
  } catch (_) {
    catalogLoaded = true;
    categoriesLoaded = true;
    renderHomeCategories();
    renderHomeRecs();
    renderCatalog();
  }
}

window.syncCatalogFromBackend = syncCatalogFromBackend;
window.syncCurrentUserFromStorage = () => {
  currentUser = OneStyleAPI.getSavedUser();
  updateAccountUI();
};

document.addEventListener('DOMContentLoaded', () => {
  loadWishlist();
  renderHomeCategories();
  renderHomeRecs();
  renderCatalog();
  renderCatalogBanner();
  renderCuration();
  renderSearchRecs();
  renderCart();
  renderWishlistDrawer();

  initCatalogFilters();
  initPdp();
  initCart();
  initQuickView();
  initSearch();
  initTracking();
  initAccount();
  initFaqHelpCenter();

  clearSearch();
  updateAccountUI();
  render();
  syncCatalogFromBackend();
  syncCartFromBackend();
  loadFaqsPublicas();
});

# tests/unit/test_catalogo.py
import pytest
from src.catalogo.service import CatalogoService, ConflictError, NotFoundError
from src.auditoria.service import AuditoriaService


@pytest.fixture
def auditoria():
    return AuditoriaService()


@pytest.fixture
def catalogo(auditoria):
    return CatalogoService(auditoria_service=auditoria)


def test_rf_cat_001_004_creacion_y_listado_productos_con_variantes(catalogo):
    """RF-CAT-001, RF-CAT-004, RF-CAT-005: Crear producto maestro, asociar variantes con SKU y listar."""
    cat_id = catalogo.crear_categoria("Corsets", "Corsets estructurados de lujo")
    talla_s = catalogo.crear_talla("S")
    talla_m = catalogo.crear_talla("M")
    color_negro = catalogo.crear_color("Negro", "#17140F")

    prod_id = catalogo.crear_producto(
        nombre="Corset Encaje Noir",
        descripcion="Diseño floral contrastante",
        precio=160000.0,
        categoria_id=cat_id,
        url_imagen_principal="https://res.cloudinary.com/onestyle/image/upload/v1/corset-noir.webp"
    )

    var_s = catalogo.agregar_variante(
        producto_id=prod_id,
        stock=8,
        punto_reposicion=3,
        talla_id=talla_s,
        color_id=color_negro,
        sku="OSM-COR-NOIR-S",
        precio_especifico=160000.0
    )
    var_m = catalogo.agregar_variante(
        producto_id=prod_id,
        stock=5,
        punto_reposicion=3,
        talla_id=talla_m,
        color_id=color_negro,
        sku="OSM-COR-NOIR-M",
        precio_especifico=165000.0
    )

    detalle = catalogo.obtener_detalle_producto(prod_id)
    assert detalle["nombre_producto"] == "Corset Encaje Noir"
    assert len(detalle["variantes"]) == 2
    assert detalle["stock_total_disponible"] == 13
    skus = [v["sku"] for v in detalle["variantes"]]
    assert "OSM-COR-NOIR-S" in skus
    assert "OSM-COR-NOIR-M" in skus


def test_rf_cat_001_003_validacion_precio_positivo_y_auditoria(catalogo, auditoria):
    """RF-CAT-001, RF-CAT-003 / RN-CAT-001, RN-CAT-003: Precio > 0 obligatorio y auditoría al cambiar precio."""
    cat_id = catalogo.crear_categoria("Blusas", "Blusas elegantes")

    with pytest.raises(ValueError, match="mayor a cero"):
        catalogo.crear_producto("Blusa Inválida", "Desc", 0, cat_id)

    with pytest.raises(ValueError, match="mayor a cero"):
        catalogo.crear_producto("Blusa Negativa", "Desc", -50000, cat_id)

    prod_id = catalogo.crear_producto("Blusa Seda", "Seda fría", 120000.0, cat_id, usuario_id=1)
    catalogo.actualizar_producto(prod_id, precio=135000.0, usuario_id=1)

    assert catalogo.productos[prod_id]["precio"] == 135000.0
    acciones = [log["tipo_accion"] for log in auditoria.logs]
    assert "ACTUALIZACION_PRODUCTO" in acciones


def test_rf_cat_002_baja_logica_producto_oculta_en_vitrina_publica(catalogo):
    """RF-CAT-002 y RF-CAT-012: Baja lógica oculta prenda del catálogo público pero la mantiene en admin."""
    cat_id = catalogo.crear_categoria("Vestidos", "Vestidos de gala")
    prod_id = catalogo.crear_producto("Vestido Aurora", "Corte sirena", 210000.0, cat_id)
    catalogo.agregar_variante(prod_id, stock=4)

    publico_antes = catalogo.obtener_catalogo_publico()
    assert len(publico_antes["items"]) == 1

    catalogo.cambiar_visibilidad_producto(prod_id, visible=False, usuario_id=1)

    publico_despues = catalogo.obtener_catalogo_publico()
    assert len(publico_despues["items"]) == 0

    admin_list = catalogo.listar_productos_admin()
    assert len(admin_list) == 1
    assert admin_list[0]["estado_visibilidad"] is False


def test_rf_cat_005_unicidad_sku_y_combinacion_talla_color(catalogo):
    """RF-CAT-005 / RN-CAT-005: Prohibido duplicar SKU o combinación (producto, talla, color)."""
    cat_id = catalogo.crear_categoria("Pantalones", "Pantalones sastre")
    talla_m = catalogo.crear_talla("M")
    talla_l = catalogo.crear_talla("L")
    color_azul = catalogo.crear_color("Azul", "#4E6484")

    prod_id = catalogo.crear_producto("Pantalón Palazzo", "Tiro alto", 140000.0, cat_id)
    catalogo.agregar_variante(
        prod_id, stock=6, talla_id=talla_m, color_id=color_azul, sku="OSM-PAL-AZ-M"
    )

    # 1. Rechazar misma combinación (producto, talla, color)
    with pytest.raises(ConflictError, match="combinación de producto, talla y color"):
        catalogo.agregar_variante(
            prod_id, stock=3, talla_id=talla_m, color_id=color_azul, sku="OSM-PAL-AZ-M-DUP"
        )

    # 2. Rechazar SKU duplicado aunque sea otra talla
    with pytest.raises(ConflictError, match="SKU"):
        catalogo.agregar_variante(
            prod_id, stock=3, talla_id=talla_l, color_id=color_azul, sku="OSM-PAL-AZ-M"
        )


def test_rf_cat_006_007_ajuste_stock_atomico_restriccion_no_negativo_y_alertas(catalogo, auditoria):
    """RF-CAT-006, RF-CAT-007 y RNF-011: Impide existencias negativas, audita ajuste y detecta punto de reposición."""
    cat_id = catalogo.crear_categoria("Faldas", "Faldas midi")
    prod_id = catalogo.crear_producto("Falda Isabella", "Plisada", 95000.0, cat_id)
    var_id = catalogo.agregar_variante(prod_id, stock=5, punto_reposicion=3, sku="OSM-FAL-ISA-S")

    # Intentar descontar más unidades de las disponibles debe fallar semánticamente (RNF-011)
    with pytest.raises(ConflictError, match="Stock insuficiente"):
        catalogo.ajustar_stock_variante(
            variante_id=var_id, delta=-6, motivo="Salida excesiva", usuario_id=1
        )

    # Ajuste válido (-3 deja stock en 2 <= punto_reposicion 3)
    nuevo_stock = catalogo.ajustar_stock_variante(
        variante_id=var_id, delta=-3, motivo="Merma verificada", usuario_id=1
    )
    assert nuevo_stock == 2
    assert catalogo.alerta_punto_reposicion(var_id) is True

    alertas = catalogo.listar_alertas_reposicion()
    assert len(alertas) == 1
    assert alertas[0]["id_variante"] == var_id

    logs_stock = [l for l in auditoria.logs if l["tipo_accion"] == "AJUSTE_STOCK"]
    assert len(logs_stock) == 1


def test_rf_cat_008_al_011_unicidad_y_bloqueo_desactivacion_categorias(catalogo):
    """RF-CAT-008..011 / RN-CAT-008..011: Categorías únicas y bloqueo al desactivar con prendas activas."""
    cat_id = catalogo.crear_categoria("Chaquetas", "Chaquetas importadas")

    with pytest.raises(ConflictError, match="categoría"):
        catalogo.crear_categoria("chaquetas", "Duplicada case-insensitive")

    prod_id = catalogo.crear_producto("Blazer Dorado", "Botones cruzados", 220000.0, cat_id)
    catalogo.agregar_variante(prod_id, stock=4)

    # RN-CAT-010 / RN-CAT-011: Bloquea desactivar categoría si tiene productos activos con stock
    with pytest.raises(ConflictError, match="productos activos"):
        catalogo.desactivar_categoria(cat_id, usuario_id=1)

    # Al ocultar el producto, sí permite desactivar la categoría
    catalogo.cambiar_visibilidad_producto(prod_id, visible=False, usuario_id=1)
    assert catalogo.desactivar_categoria(cat_id, usuario_id=1) is True


def test_rf_cat_013_al_016_atributos_maestros_integridad_referencial(catalogo):
    """RF-CAT-013..016 / RN-CAT-015: Unicidad de tallas/colores y bloqueo de edición si tienen inventario vinculado."""
    talla_xs = catalogo.crear_talla("XS")
    color_vino = catalogo.crear_color("Vinotinto", "#5E1914")

    with pytest.raises(ConflictError, match="talla"):
        catalogo.crear_talla("xs")

    cat_id = catalogo.crear_categoria("Bodies", "Bodies ajustados")
    prod_id = catalogo.crear_producto("Body Nocturno", "Malla", 128000.0, cat_id)
    catalogo.agregar_variante(prod_id, stock=5, talla_id=talla_xs, color_id=color_vino)

    # RN-CAT-015: No permite modificar nomenclatura de talla si ya tiene variantes en inventario
    with pytest.raises(ConflictError, match="inventario"):
        catalogo.actualizar_talla(talla_xs, "XXS")


def test_rf_cat_017_galeria_imagenes_y_cloudinary(catalogo):
    """RF-CAT-017 / RN-CAT-017: Validación de URL Cloudinary, formatos permitidos y única imagen principal."""
    cat_id = catalogo.crear_categoria("Tops", "Tops de fiesta")
    prod_id = catalogo.crear_producto("Top Carmesí", "Manga corta", 115000.0, cat_id)

    img1 = catalogo.agregar_imagen_producto(
        prod_id, "https://res.cloudinary.com/onestyle/image/upload/top1.webp", formato="WEBP", es_principal=True
    )
    img2 = catalogo.agregar_imagen_producto(
        prod_id, "https://res.cloudinary.com/onestyle/image/upload/top2.jpg", formato="JPG", es_principal=True
    )

    galeria = catalogo.listar_imagenes_producto(prod_id)
    assert len(galeria) == 2
    principales = [img for img in galeria if img["es_principal"]]
    assert len(principales) == 1
    assert principales[0]["id_imagen"] == img2


def test_api_rest_catalogo_paginacion_filtros_y_codigos_http():
    """Pruebas de integración HTTP para endpoints de Catálogo e Inventario (200, 201, 400, 404, 409)."""
    from run import app, auth_service

    client = app.test_client()

    # 1. Consulta pública con paginación, filtros y ordenamiento (200) — RF-CAT-012
    res_cat = client.get("/api/catalogo?page=1&per_page=4&sort=priceAsc")
    assert res_cat.status_code == 200
    body_cat = res_cat.get_json()
    assert body_cat["status"] == "success"
    assert len(body_cat["data"]["items"]) <= 4
    assert body_cat["data"]["pagination"]["total"] >= 1

    # Verificar orden ascendente por precio
    precios = [p["precio"] for p in body_cat["data"]["items"]]
    assert precios == sorted(precios)

    # 2. Detalle de producto y variantes con stock y SKU (200 y 404) — RF-CAT-018
    primer_id = body_cat["data"]["items"][0]["id"]
    res_det = client.get(f"/api/catalogo/{primer_id}")
    assert res_det.status_code == 200
    det_data = res_det.get_json()["data"]
    assert "variantes" in det_data
    assert len(det_data["variantes"]) >= 1
    assert "sku" in det_data["variantes"][0]

    res_404 = client.get("/api/catalogo/producto-inexistente-99999")
    assert res_404.status_code == 404

    # 3. Operaciones administrativas con token de Administradora (201, 409, 400)
    token_admin = auth_service.validar_credenciales("admin@onestylemariana.co", "AdminOneStyle2026")
    headers = {"Authorization": f"Bearer {token_admin}"}

    res_new_prod = client.post("/api/admin/productos", headers=headers, json={
        "nombre_producto": "Vestido Esmeralda Imperial",
        "descripcion_producto": "Seda italiana importada",
        "precio_detallista": 280000,
        "fk_id_categoria": 1,
        "fk_id_talla": 2,
        "fk_id_color": 1,
        "stock_real": 5,
        "punto_reposicion": 2,
        "codigo_sku": "OSM-VES-ESM-S"
    })
    assert res_new_prod.status_code == 201
    created = res_new_prod.get_json()["data"]

    # 4. Conflicto 409 al intentar registrar variante con SKU duplicado — RF-CAT-005
    res_dup_sku = client.post("/api/admin/variantes", headers=headers, json={
        "fk_id_producto": created["id_producto"],
        "fk_id_talla": 3,
        "fk_id_color": 1,
        "stock_real": 4,
        "punto_reposicion": 2,
        "codigo_sku": "OSM-VES-ESM-S"
    })
    assert res_dup_sku.status_code == 409

    # 5. Conflicto 409 al intentar descontar más stock del disponible — RNF-011 / RF-CAT-006
    res_over_stock = client.post("/api/admin/inventario/ajuste", headers=headers, json={
        "fk_id_variante": created["id_variante"],
        "tipo_accion": "salida",
        "cantidad": 999,
        "motivo": "Intento de sobreventa"
    })
    assert res_over_stock.status_code == 409


def test_catalogo_sort_whitelist_y_ui_mejoras_owasp():
    """Verifica lista blanca de sort en /api/catalogo y marcado limpio CSP de las 4 mejoras UX."""
    import re
    from run import app, ALLOWED_CATALOG_SORTS

    assert {"destacados", "priceAsc", "priceDesc", "name", "stock"} <= ALLOWED_CATALOG_SORTS
    client = app.test_client()

    # 1. Validar todos los modos de ordenamiento permitidos
    r_asc = client.get("/api/catalogo?per_page=50&sort=priceAsc")
    assert r_asc.status_code == 200
    precios_asc = [p["precio"] for p in r_asc.get_json()["data"]["items"]]
    assert precios_asc == sorted(precios_asc)

    r_desc = client.get("/api/catalogo?per_page=50&sort=priceDesc")
    assert r_desc.status_code == 200
    precios_desc = [p["precio"] for p in r_desc.get_json()["data"]["items"]]
    assert precios_desc == sorted(precios_desc, reverse=True)

    r_name = client.get("/api/catalogo?per_page=50&sort=name")
    assert r_name.status_code == 200
    nombres = [p["nombre_producto"].lower() for p in r_name.get_json()["data"]["items"]]
    assert nombres == sorted(nombres)

    r_stock = client.get("/api/catalogo?per_page=50&sort=stock")
    assert r_stock.status_code == 200
    stocks = [p["stock_total_disponible"] for p in r_stock.get_json()["data"]["items"]]
    assert stocks == sorted(stocks, reverse=True)

    # 2. Lista blanca en parámetro sort: valores manipulados caen en 'destacados' sin fallo
    r_dest = client.get("/api/catalogo?per_page=50&sort=destacados")
    r_bad = client.get("/api/catalogo?per_page=50&sort=priceAsc;DROP%20TABLE%20usuarios")
    assert r_dest.status_code == 200
    assert r_bad.status_code == 200
    ids_dest = [p["id"] for p in r_dest.get_json()["data"]["items"]]
    ids_bad = [p["id"] for p in r_bad.get_json()["data"]["items"]]
    assert ids_bad == ids_dest

    # 3. Verificar controles HTML y cumplimiento CSP (cero inline styles / event handlers)
    r_home = client.get("/")
    assert r_home.status_code == 200
    html = r_home.get_data(as_text=True)

    assert 'id="catalogSortSelect"' in html
    for opt_val in ("destacados", "priceAsc", "priceDesc", "stock"):
        assert f'value="{opt_val}"' in html

    assert 'id="searchQuickChips"' in html
    for chip in ("Corsets", "Blanco", "Noir", "Denim", "Vestidos"):
        assert f'data-search-chip="{chip}"' in html

    assert "<style" not in html
    assert 'style="' not in html
    assert not re.search(r"\bon(?:click|change|input|keyup|keydown)=", html, re.IGNORECASE)


def test_admin_visibilidad_y_filtro_ocultos():
    """RF-CAT-002 / RF-CAT-004: Ocultar prenda y filtrar por estado=inactivo / estado=oculto."""
    from run import app, auth_service

    client = app.test_client()
    tok_adm = auth_service.validar_credenciales("admin@onestylemariana.co", "AdminOneStyle2026")
    h = {"Authorization": f"Bearer {tok_adm}"}

    lista = client.get("/api/admin/productos?per_page=5", headers=h).get_json()["data"]["items"]
    target = lista[0]
    pid = target["id_producto"]
    assert target["estado_visibilidad"] is True

    try:
        r_hide = client.patch(
            f"/api/admin/productos/{pid}/visibilidad",
            headers=h,
            json={"estado_visibilidad": False},
        )
        assert r_hide.status_code == 200
        assert r_hide.get_json()["data"]["estado_visibilidad"] is False

        for estado_param in ("inactivo", "oculto"):
            res_hidden = client.get(f"/api/admin/productos?per_page=50&estado={estado_param}", headers=h)
            assert res_hidden.status_code == 200
            hidden_ids = [p["id_producto"] for p in res_hidden.get_json()["data"]["items"]]
            assert pid in hidden_ids

        # En catálogo público no debe aparecer mientras esté oculto
        pub_ids = [p["id_producto"] for p in client.get("/api/catalogo?per_page=50").get_json()["data"]["items"]]
        assert pid not in pub_ids
    finally:
        client.patch(
            f"/api/admin/productos/{pid}/visibilidad",
            headers=h,
            json={"estado_visibilidad": True},
        )


def test_rf_cat_003_edicion_completa_prenda_validaciones_y_persistencia():
    """
    RF-CAT-003 (Punto 8): Edición completa de prenda (nombre, descripción, categoría y precio)
    vía PUT /api/admin/productos/<id>, validación de entrada (400/404) y persistencia en lecturas posteriores.
    """
    import uuid
    from run import app, auth_service

    client = app.test_client()
    tok_adm = auth_service.validar_credenciales("admin@onestylemariana.co", "AdminOneStyle2026")
    h = {"Authorization": f"Bearer {tok_adm}"}
    suffix = uuid.uuid4().hex[:8]

    cats = [c for c in client.get("/api/admin/categorias", headers=h).get_json()["data"] if c.get("estado", True)]
    assert len(cats) >= 2
    cat_1 = cats[0]["id_categoria"]
    cat_2 = cats[1]["id_categoria"]

    r_create = client.post(
        "/api/admin/productos",
        headers=h,
        json={
            "nombre_producto": f"Corset Prueba {suffix}",
            "descripcion_producto": "Descripción inicial de prueba",
            "precio_detallista": 150000,
            "fk_id_categoria": cat_1,
        },
    )
    assert r_create.status_code == 201
    pid = r_create.get_json()["data"]["id_producto"]

    try:
        # Validaciones negativas -> 400 / 404
        assert client.put(f"/api/admin/productos/{pid}", headers=h, json={"precio_detallista": 0}).status_code == 400
        assert client.put(f"/api/admin/productos/{pid}", headers=h, json={"precio_detallista": -500}).status_code == 400
        assert client.put(f"/api/admin/productos/{pid}", headers=h, json={"precio_detallista": "invalido"}).status_code == 400
        assert client.put(f"/api/admin/productos/{pid}", headers=h, json={"nombre_producto": "   "}).status_code == 400
        assert client.put(f"/api/admin/productos/{pid}", headers=h, json={"fk_id_categoria": 999999}).status_code == 400
        assert client.put("/api/admin/productos/999999", headers=h, json={"nombre_producto": "No existe"}).status_code == 404

        # Actualización completa válida -> 200
        nuevo_nombre = f"Corset Imperial Editado {suffix}"
        nueva_desc = "Confección premium con varillas flexibles actualizadas"
        nuevo_precio = 215000.0
        r_upd = client.put(
            f"/api/admin/productos/{pid}",
            headers=h,
            json={
                "nombre_producto": nuevo_nombre,
                "descripcion_producto": nueva_desc,
                "fk_id_categoria": cat_2,
                "precio_detallista": nuevo_precio,
            },
        )
        assert r_upd.status_code == 200
        upd = r_upd.get_json()["data"]
        assert upd["nombre_producto"] == nuevo_nombre
        assert upd["descripcion_producto"] == nueva_desc
        assert upd["fk_id_categoria"] == cat_2
        assert float(upd["precio_detallista"]) == nuevo_precio

        # Verificar persistencia al recargar listado admin y catálogo público
        r_list = client.get(f"/api/admin/productos?q={suffix}&per_page=20", headers=h)
        assert r_list.status_code == 200
        adm_items = r_list.get_json()["data"]["items"]
        match_adm = next(p for p in adm_items if p["id_producto"] == pid)
        assert match_adm["nombre_producto"] == nuevo_nombre
        assert match_adm["fk_id_categoria"] == cat_2
        assert float(match_adm["precio_detallista"]) == nuevo_precio

        r_pub = client.get("/api/catalogo?per_page=50")
        assert r_pub.status_code == 200
        pub_items = r_pub.get_json()["data"]["items"]
        match_pub = next(p for p in pub_items if p["id_producto"] == pid)
        assert match_pub["nombre_producto"] == nuevo_nombre
        assert match_pub["fk_id_categoria"] == cat_2
        assert float(match_pub["precio_detallista"]) == nuevo_precio
    finally:
        client.patch(
            f"/api/admin/productos/{pid}/visibilidad",
            headers=h,
            json={"estado_visibilidad": False},
        )


def test_maestros_crud_integridad_409_y_rbac_solo_admin():
    """
    RF-CAT-008..016 (OWASP A01 / Integridad Referencial):
    - Endpoints de Categorías, Atributos, Tallas y Colores maestros exigen rol Administradora (403 a Vendedora/Clienta).
    - Alta, edición, activación/desactivación y validación de HEX.
    - Bloqueo HTTP 409 al intentar eliminar registros en uso; borrado limpio 200 cuando están libres.
    """
    import uuid
    from run import app, auth_service

    client = app.test_client()
    suffix = uuid.uuid4().hex[:8]
    tok_adm = auth_service.validar_credenciales("admin@onestylemariana.co", "AdminOneStyle2026")
    tok_ven = auth_service.validar_credenciales("vendedora@onestylemariana.co", "VentasOneStyle2026")
    r_cli = client.post(
        "/api/auth/register",
        json={"nombre": "Sara", "apellido": "Master", "email": f"sara.master.{suffix}@test.co", "contrasena": "MasterPass1"},
    )
    assert r_cli.status_code == 201
    tok_cli = r_cli.get_json()["data"]["token"]

    adm_hdr = {"Authorization": f"Bearer {tok_adm}"}
    ven_hdr = {"Authorization": f"Bearer {tok_ven}"}
    cli_hdr = {"Authorization": f"Bearer {tok_cli}"}

    # 1. RBAC estricto para Vendedora y Clienta
    for bad_hdr in (ven_hdr, cli_hdr):
        assert client.get("/api/admin/categorias", headers=bad_hdr).status_code == 403
        assert client.post("/api/admin/categorias", headers=bad_hdr, json={"nombre_categoria": "Hack"}).status_code == 403
        assert client.put("/api/admin/categorias/1", headers=bad_hdr, json={"nombre_categoria": "Hack"}).status_code == 403
        assert client.patch("/api/admin/categorias/1/estado", headers=bad_hdr, json={"estado": False}).status_code == 403
        assert client.delete("/api/admin/categorias/1", headers=bad_hdr).status_code == 403
        assert client.get("/api/admin/atributos", headers=bad_hdr).status_code == 403
        assert client.post("/api/admin/tallas", headers=bad_hdr, json={"nombre_talla": "H"}).status_code == 403
        assert client.put("/api/admin/tallas/1", headers=bad_hdr, json={"nombre_talla": "H"}).status_code == 403
        assert client.patch("/api/admin/tallas/1/estado", headers=bad_hdr, json={"estado": False}).status_code == 403
        assert client.delete("/api/admin/tallas/1", headers=bad_hdr).status_code == 403
        assert client.post("/api/admin/colores", headers=bad_hdr, json={"nombre_color": "H", "codigo_hex": "#000000"}).status_code == 403
        assert client.put("/api/admin/colores/1", headers=bad_hdr, json={"nombre_color": "H"}).status_code == 403
        assert client.patch("/api/admin/colores/1/estado", headers=bad_hdr, json={"estado": False}).status_code == 403
        assert client.delete("/api/admin/colores/1", headers=bad_hdr).status_code == 403

    # 2. Categoría libre: CRUD completo + bloqueo 409 en categoría en uso
    assert client.delete("/api/admin/categorias/1", headers=adm_hdr).status_code == 409

    r_cat = client.post(
        "/api/admin/categorias",
        headers=adm_hdr,
        json={"nombre_categoria": f"Línea Gala {suffix}", "descripcion_categoria": "Colección limitada"},
    )
    assert r_cat.status_code == 201
    cat_id = r_cat.get_json()["data"]["id_categoria"]
    assert client.put(
        f"/api/admin/categorias/{cat_id}",
        headers=adm_hdr,
        json={"nombre_categoria": f"Línea Gala VIP {suffix}", "descripcion_categoria": "Actualizada"},
    ).status_code == 200
    assert client.patch(f"/api/admin/categorias/{cat_id}/estado", headers=adm_hdr, json={"estado": False}).status_code == 200
    assert client.patch(f"/api/admin/categorias/{cat_id}/estado", headers=adm_hdr, json={"estado": True}).status_code == 200
    assert client.delete(f"/api/admin/categorias/{cat_id}", headers=adm_hdr).status_code == 200

    # 3. Tallas y Colores: validación HEX, uso 409 y borrado limpio 200
    attrs_before = client.get("/api/admin/atributos", headers=adm_hdr).get_json()["data"]
    used_size = next(t for t in attrs_before["tallas"] if t["en_uso"])
    used_color = next(c for c in attrs_before["colores"] if c["en_uso"])
    assert client.delete(f"/api/admin/tallas/{used_size['id_talla']}", headers=adm_hdr).status_code == 409
    assert client.delete(f"/api/admin/colores/{used_color['id_color']}", headers=adm_hdr).status_code == 409

    r_sz = client.post("/api/admin/tallas", headers=adm_hdr, json={"nombre_talla": f"T{suffix[:4].upper()}"})
    assert r_sz.status_code == 201
    tid = r_sz.get_json()["data"]["id_talla"]
    assert client.put(f"/api/admin/tallas/{tid}", headers=adm_hdr, json={"nombre_talla": f"U{suffix[:4].upper()}"}).status_code == 200
    assert client.patch(f"/api/admin/tallas/{tid}/estado", headers=adm_hdr, json={"estado": False}).status_code == 200
    assert client.patch(f"/api/admin/tallas/{tid}/estado", headers=adm_hdr, json={"estado": True}).status_code == 200
    assert client.delete(f"/api/admin/tallas/{tid}", headers=adm_hdr).status_code == 200

    assert client.post(
        "/api/admin/colores",
        headers=adm_hdr,
        json={"nombre_color": f"BadHex {suffix}", "codigo_hex": "no-hex"},
    ).status_code == 400
    r_col = client.post(
        "/api/admin/colores",
        headers=adm_hdr,
        json={"nombre_color": f"Zafiro {suffix}", "codigo_hex": "#1b4d89"},
    )
    assert r_col.status_code == 201
    cid = r_col.get_json()["data"]["id_color"]
    r_col_upd = client.put(
        f"/api/admin/colores/{cid}",
        headers=adm_hdr,
        json={"nombre_color": f"Zafiro Real {suffix}", "codigo_hex": "#224488"},
    )
    assert r_col_upd.status_code == 200
    assert r_col_upd.get_json()["data"]["codigo_hex"] == "#224488"
    assert client.patch(f"/api/admin/colores/{cid}/estado", headers=adm_hdr, json={"estado": False}).status_code == 200
    assert client.patch(f"/api/admin/colores/{cid}/estado", headers=adm_hdr, json={"estado": True}).status_code == 200
    assert client.delete(f"/api/admin/colores/{cid}", headers=adm_hdr).status_code == 200


def test_galeria_1_a_n_upload_seguro_owasp_reorden_portada_y_borrado():
    """
    RF-CAT-017 (OWASP Unrestricted File Upload + A01):
    - Exige rol Administradora en subida, portada, reordenamiento y borrado.
    - Rechaza .php, .svg, spoofing de magic bytes (texto renombrado a .png) y archivos > 5 MB (413).
    - Permite subir 1..N imágenes válidas (PNG/WEBP) con UUID, marcar portada, reordenar, ver en /api/catalogo y eliminar de disco.
    """
    import io
    import os
    import uuid
    from PIL import Image
    from run import app, auth_service, UPLOAD_PRODUCTS_DIR

    def _make_img_bytes(fmt: str, color: tuple) -> bytes:
        buf = io.BytesIO()
        Image.new("RGB", (6, 6), color).save(buf, format=fmt)
        return buf.getvalue()

    client = app.test_client()
    suffix = uuid.uuid4().hex[:8]
    tok_adm = auth_service.validar_credenciales("admin@onestylemariana.co", "AdminOneStyle2026")
    tok_ven = auth_service.validar_credenciales("vendedora@onestylemariana.co", "VentasOneStyle2026")
    adm_hdr = {"Authorization": f"Bearer {tok_adm}"}
    ven_hdr = {"Authorization": f"Bearer {tok_ven}"}

    r_prod = client.post(
        "/api/admin/productos",
        headers=adm_hdr,
        json={
            "nombre_producto": f"Vestido Galeria {suffix}",
            "descripcion_producto": "Prenda para validar galería 1..N",
            "precio_detallista": 195000,
            "fk_id_categoria": 1,
        },
    )
    assert r_prod.status_code == 201
    pid = r_prod.get_json()["data"]["id_producto"]

    png_bytes = _make_img_bytes("PNG", (180, 120, 90))
    webp_bytes = _make_img_bytes("WEBP", (40, 80, 140))

    try:
        # 1. Vendedora bloqueada con 403 en endpoints de galería
        assert client.get(f"/api/admin/productos/{pid}/imagenes", headers=ven_hdr).status_code == 403
        assert client.post(
            f"/api/admin/productos/{pid}/imagenes",
            headers=ven_hdr,
            data={"imagenes": (io.BytesIO(png_bytes), "foto.png")},
            content_type="multipart/form-data",
        ).status_code == 403

        # 2. Rechazo de extensiones peligrosas, spoofing y tamaño > 5 MB
        for fname, content in (
            ("shell.php", b"<?php system($_GET['c']); ?>"),
            ("xss.svg", b"<svg onload=alert(1)></svg>"),
            ("pagina.html", b"<script>alert(1)</script>"),
            ("spoof.png", b"Este archivo NO es un PNG real"),
        ):
            r_bad = client.post(
                f"/api/admin/productos/{pid}/imagenes",
                headers=adm_hdr,
                data={"imagenes": (io.BytesIO(content), fname)},
                content_type="multipart/form-data",
            )
            assert r_bad.status_code == 400

        oversized = b"\x89PNG\r\n\x1a\n" + (b"\x00" * (5 * 1024 * 1024 + 32))
        r_big = client.post(
            f"/api/admin/productos/{pid}/imagenes",
            headers=adm_hdr,
            data={"imagenes": (io.BytesIO(oversized), "gigante.png")},
            content_type="multipart/form-data",
        )
        assert r_big.status_code == 413

        # 3. Subida múltiple válida (PNG + WEBP) con nombres UUID en static/img/uploads
        r_up = client.post(
            f"/api/admin/productos/{pid}/imagenes",
            headers=adm_hdr,
            data={
                "imagenes": [
                    (io.BytesIO(png_bytes), "../../malicioso.png"),
                    (io.BytesIO(webp_bytes), "vista_trasera.webp"),
                ]
            },
            content_type="multipart/form-data",
        )
        assert r_up.status_code == 201
        up_data = r_up.get_json()["data"]
        imgs = up_data["imagenes"]
        assert len(imgs) == 2
        id_1, id_2 = imgs[0]["id_imagen"], imgs[1]["id_imagen"]
        url_1, url_2 = imgs[0]["url_imagen"], imgs[1]["url_imagen"]
        assert url_1.startswith("img/uploads/") and "malicioso" not in url_1
        assert url_2.startswith("img/uploads/")
        assert os.path.isfile(os.path.join(UPLOAD_PRODUCTS_DIR, os.path.basename(url_1)))
        assert os.path.isfile(os.path.join(UPLOAD_PRODUCTS_DIR, os.path.basename(url_2)))

        # 4. Vitrina pública y PDP exponen la portada y la galería completa 1..N
        r_det = client.get(f"/api/catalogo/{pid}")
        assert r_det.status_code == 200
        det = r_det.get_json()["data"]
        assert det["img"] == url_1
        assert len(det["imagenes"]) == 2

        # 5. Marcar segunda imagen como principal y reordenar
        r_prin = client.patch(f"/api/admin/productos/{pid}/imagenes/{id_2}/principal", headers=adm_hdr)
        assert r_prin.status_code == 200
        assert r_prin.get_json()["data"]["url_imagen_principal"] == url_2

        assert client.patch(
            f"/api/admin/productos/{pid}/imagenes/reordenar",
            headers=adm_hdr,
            json={"orden_ids": [id_2]},
        ).status_code == 400

        r_reord = client.patch(
            f"/api/admin/productos/{pid}/imagenes/reordenar",
            headers=adm_hdr,
            json={"orden_ids": [id_2, id_1]},
        )
        assert r_reord.status_code == 200
        reord_imgs = r_reord.get_json()["data"]["imagenes"]
        assert [i["id_imagen"] for i in reord_imgs] == [id_2, id_1]
        assert reord_imgs[0]["orden"] == 1

        # 6. Eliminar imagen 2: borra archivo físico en disco y promueve imagen 1 como portada
        r_del2 = client.delete(f"/api/admin/productos/{pid}/imagenes/{id_2}", headers=adm_hdr)
        assert r_del2.status_code == 200
        assert not os.path.exists(os.path.join(UPLOAD_PRODUCTS_DIR, os.path.basename(url_2)))
        assert r_del2.get_json()["data"]["url_imagen_principal"] == url_1
    finally:
        restantes = client.get(f"/api/admin/productos/{pid}/imagenes", headers=adm_hdr).get_json()["data"]["imagenes"]
        for im in restantes:
            client.delete(f"/api/admin/productos/{pid}/imagenes/{im['id_imagen']}", headers=adm_hdr)
        client.patch(
            f"/api/admin/productos/{pid}/visibilidad",
            headers=adm_hdr,
            json={"estado_visibilidad": False},
        )

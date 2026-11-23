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

import pytest
import urllib.parse
from src.pedidos.service import PedidosService
from src.catalogo.service import CatalogoService

@pytest.fixture
def catalogo():
    cat = CatalogoService()
    # Create products and variants
    prod_id1 = cat.crear_producto("Blusa", "Blusa roja", 50.0, 1)
    var_id1 = cat.agregar_variante(prod_id1, stock=10)

    prod_id2 = cat.crear_producto("Pantalón", "Jean azul", 80.0, 2)
    var_id2 = cat.agregar_variante(prod_id2, stock=5)

    return cat, var_id1, var_id2

@pytest.fixture
def pedidos(catalogo):
    cat, _, _ = catalogo
    return PedidosService(cat)

def test_crear_pedido(pedidos, catalogo):
    _, var_id1, var_id2 = catalogo

    items = {
        var_id1: 2, # 2 * 50 = 100
        var_id2: 1  # 1 * 80 = 80
    }

    pedido_id = pedidos.crear_pedido(usuario_id=1, items_carrito=items)

    assert pedido_id == 1
    pedido = pedidos.pedidos[pedido_id]
    assert pedido['usuario_id'] == 1
    assert pedido['total'] == 180.0
    assert pedido['estado'] == 'Registrado'

def test_crear_pedido_vacio(pedidos):
    with pytest.raises(ValueError, match="El carrito está vacío."):
        pedidos.crear_pedido(usuario_id=1, items_carrito={})

def test_calcular_total(pedidos, catalogo):
    _, var_id1, var_id2 = catalogo

    items = {
        var_id1: 3, # 3 * 50 = 150
        var_id2: 2  # 2 * 80 = 160
    }

    total = pedidos.calcular_total(items)
    assert total == 310.0

def test_generar_enlace_whatsapp(pedidos, catalogo):
    _, var_id1, _ = catalogo

    items = {var_id1: 1} # total = 50.0
    pedido_id = pedidos.crear_pedido(usuario_id=1, items_carrito=items)

    enlace = pedidos.generar_enlace_whatsapp(pedido_id, "573001234567")

    mensaje_esperado = f"Hola, me gustaría confirmar el pedido #{pedido_id}. El total es $50.00."
    mensaje_codificado = urllib.parse.quote(mensaje_esperado)

    assert enlace == f"https://wa.me/573001234567?text={mensaje_codificado}"

def test_calcular_total_vacio(pedidos):
    total = pedidos.calcular_total({})
    assert total == 0.0

def test_transicion_secuencial_estricta(pedidos, catalogo):
    cat, var_id1, _ = catalogo
    items = {var_id1: 2}
    # Simulate reserving stock
    cat.variantes[var_id1]['stock_reservado'] += 2

    pedido_id = pedidos.crear_pedido(usuario_id=1, items_carrito=items)

    assert pedidos.pedidos[pedido_id]['estado'] == 'Registrado'

    pedidos.transicionar_estado(pedido_id, 'Confirmado')
    assert pedidos.pedidos[pedido_id]['estado'] == 'Confirmado'
    assert cat.variantes[var_id1]['stock_reservado'] == 0
    assert cat.variantes[var_id1]['stock_real'] == 8

    pedidos.transicionar_estado(pedido_id, 'En Empaque')
    assert pedidos.pedidos[pedido_id]['estado'] == 'En Empaque'

    pedidos.transicionar_estado(pedido_id, 'Despachado')
    assert pedidos.pedidos[pedido_id]['estado'] == 'Despachado'

    pedidos.transicionar_estado(pedido_id, 'Entregado')
    assert pedidos.pedidos[pedido_id]['estado'] == 'Entregado'

def test_rechazo_saltos_ilegales(pedidos, catalogo):
    _, var_id1, _ = catalogo
    items = {var_id1: 1}
    pedido_id = pedidos.crear_pedido(usuario_id=1, items_carrito=items)

    with pytest.raises(ValueError, match="Transición inválida"):
        pedidos.transicionar_estado(pedido_id, 'Despachado')

    pedidos.transicionar_estado(pedido_id, 'Confirmado')

    with pytest.raises(ValueError, match="Transición inválida"):
        pedidos.transicionar_estado(pedido_id, 'Entregado')

def test_formateo_codificacion_url_whatsapp(pedidos, catalogo):
    _, var_id1, _ = catalogo
    items = {var_id1: 1}
    pedido_id = pedidos.crear_pedido(usuario_id=1, items_carrito=items)
    enlace = pedidos.generar_enlace_whatsapp(pedido_id, "573001234567")

    assert "%20" in enlace or "%23" in enlace
    assert enlace.startswith("https://wa.me/573001234567?text=")


# =========================================================================
# NUEVAS PRUEBAS TDD — MÓDULO 4: GESTIÓN DE PEDIDOS (OMS), FSM Y WHATSAPP
# Trazabilidad: RF-PED-001 a RF-PED-004 / Reglas: RN-PED-001 a RN-PED-004
# =========================================================================

def test_rf_ped_001_creacion_orden_desde_carrito_descuento_definitivo_y_vaciado():
    """
    RF-PED-001 / RN-PED-001: Creación exitosa de orden desde un carrito con reserva activa,
    consolidando el descuento definitivo de stock de forma atómica, congelando precio histórico
    y vaciando el carrito.
    """
    from src.carrito.service import CarritoService

    cat = CatalogoService()
    prod_id = cat.crear_producto("Corset Imperial", "Edición limitada", 150000.0, 1)
    var_id = cat.agregar_variante(prod_id, stock=5, talla_id=2, color_id=1, sku="OSM-IMP-S-NEG", precio_especifico=150000.0)

    carrito = CarritoService(cat, usuario_id=10, session_id="sess-oms-1")
    carrito.agregar_item(var_id, 2)
    carrito.capturar_datos_despacho(
        direccion_envio="Calle 93 # 12-54",
        barrio="Chicó",
        ciudad="Bogotá D.C.",
        telefono="3109876543",
        observaciones="Entregar en recepción",
        nombre_receptor="Camila Restrepo",
        email="camila@cliente.co"
    )

    # Cambiar precio en catálogo después de reservar para verificar inmutabilidad en OrderItem
    cat.variantes[var_id]["precio_variante"] = 220000.0

    # Antes de confirmar pedido: stock_real=5, stock_reservado=2, disponible=3
    assert cat.variantes[var_id]["stock_real"] == 5
    assert cat.variantes[var_id]["stock_reservado"] == 2
    assert cat.consultar_stock_disponible(var_id) == 3

    pedidos_srv = PedidosService(cat)
    orden = pedidos_srv.crear_pedido_desde_carrito(carrito, usuario_id=10)

    assert orden["id_pedido"] == 1
    assert orden["codigo_orden"] == "ORD-00001"
    assert orden["subtotal"] == 300000.0
    assert orden["detalle_items"][0]["precio_unitario"] == 150000.0
    assert orden["detalle_items"][0]["subtotal"] == 300000.0
    assert orden["url_comprobante_whatsapp"].startswith("https://wa.me/")

    # Stock consolidado definitivamente: stock_real=3, stock_reservado=0, carrito vacío
    assert cat.variantes[var_id]["stock_real"] == 3
    assert cat.variantes[var_id]["stock_reservado"] == 0
    assert carrito.items == {}


def test_rf_ped_002_fsm_estados_estrictos_y_reintegro_stock_en_cancelacion():
    """
    RF-PED-002 / RN-PED-002: Validación de la Máquina de Estados Finita (FSM):
    - Soporta flujo PENDIENTE_PAGO -> CONFIRMADO -> EN_PREPARACION -> DESPACHADO -> ENTREGADO
    - Rechaza saltos arbitrarios (ej. de PENDIENTE_PAGO directo a ENTREGADO) y reversiones.
    - Al cancelar un pedido, reintegra exactamente el stock descontado o reservado.
    """
    from src.carrito.service import CarritoService

    cat = CatalogoService()
    prod_id = cat.crear_producto("Top Seda", "Seda italiana", 120000.0, 1)
    var_id = cat.agregar_variante(prod_id, stock=4, talla_id=2, color_id=2, sku="OSM-TOP-S-MAR")

    carrito = CarritoService(cat, usuario_id=12, session_id="sess-oms-2")
    carrito.agregar_item(var_id, 3)
    carrito.capturar_datos_despacho("Cra 15 # 85-20", "Virrey", "Bogotá", "3001234567")

    pedidos_srv = PedidosService(cat)
    orden = pedidos_srv.crear_pedido_desde_carrito(carrito, usuario_id=12, estado_inicial="PENDIENTE_PAGO")
    pid = orden["id_pedido"]

    # Stock tras creación del pedido: real=1, reservado=0
    assert cat.variantes[var_id]["stock_real"] == 1

    # Intentar salto ilegal de PENDIENTE_PAGO directo a ENTREGADO debe fallar
    with pytest.raises(ValueError, match="Transición inválida"):
        pedidos_srv.transicionar_estado(pid, "ENTREGADO")

    # Transición válida a CONFIRMADO
    pedidos_srv.transicionar_estado(pid, "CONFIRMADO", usuario_responsable=1, motivo="Pago verificado por Nequi")
    assert pedidos_srv.pedidos[pid]["estado"] == "CONFIRMADO"

    # Cancelación desde CONFIRMADO debe reintegrar las 3 unidades al stock_real (1 + 3 = 4)
    pedidos_srv.transicionar_estado(pid, "CANCELADO", usuario_responsable=1, motivo="Solicitud de cambio de prenda")
    assert pedidos_srv.pedidos[pid]["estado"] == "CANCELADO"
    assert cat.variantes[var_id]["stock_real"] == 4
    assert cat.consultar_stock_disponible(var_id) == 4

    # Intentar transicionar un pedido ya CANCELADO debe fallar
    with pytest.raises(ValueError, match="estado final"):
        pedidos_srv.transicionar_estado(pid, "CONFIRMADO")


def test_rf_ped_001_codificacion_segura_mensaje_concierge_whatsapp():
    """
    RF-PED-001: Verifica formato del enlace Concierge WhatsApp, resumen de ítems,
    cálculo correcto del total y sanitización contra inyección de parámetros/XSS.
    """
    from src.carrito.service import CarritoService

    cat = CatalogoService()
    prod_id = cat.crear_producto("Blusa Encaje", "Encaje floral", 100000.0, 1)
    var_id = cat.agregar_variante(prod_id, stock=5, talla_id=3, color_id=1, sku="OSM-BLU-M-NEG")

    carrito = CarritoService(cat, usuario_id=15, session_id="sess-oms-wa")
    carrito.agregar_item(var_id, 2)
    carrito.capturar_datos_despacho(
        direccion_envio="Av. El Poblado # 10-20 <script>evil()</script>",
        barrio="El Poblado & Sur",
        ciudad="Medellín",
        telefono="3150001122",
        nombre_receptor="Valentina & Co."
    )

    pedidos_srv = PedidosService(cat)
    orden = pedidos_srv.crear_pedido_desde_carrito(carrito, usuario_id=15)
    url = pedidos_srv.generar_enlace_whatsapp(orden["id_pedido"], "573001112233", formato_concierge=True)

    assert url.startswith("https://wa.me/573001112233?text=")
    decoded = urllib.parse.unquote(url.split("?text=")[1])
    assert orden["codigo_orden"] in decoded
    assert "Blusa Encaje" in decoded
    assert "OSM-BLU-M-NEG" in decoded
    assert "Medellín" in decoded
    # No debe contener etiquetas <script> sin sanitizar
    assert "<script>" not in decoded


def test_rf_ped_003_004_api_rest_checkout_seguimiento_oms_y_reportes():
    """
    Prueba de integración de los endpoints REST del Módulo 4 (RF-PED-001 a RF-PED-004):
    - POST /api/pedidos/checkout (crea pedido desde carrito, descuenta stock y retorna URL WhatsApp)
    - GET /api/pedidos/seguimiento/<codigo_orden> (rastreo en tiempo real)
    - GET /api/admin/pedidos y PATCH /api/admin/pedidos/<id>/estado (panel OMS y FSM)
    - GET /api/admin/pedidos/reporte (reportes consolidados RF-PED-004)
    """
    from run import app, auth_service

    client = app.test_client()
    headers = {"X-Session-ID": "test-checkout-oms-session"}

    # 1. Añadir prenda al carrito (stock inicial variante 1 = 8)
    r_add = client.post("/api/carrito/items", headers=headers, json={"fk_id_variante": 1, "cantidad": 2})
    assert r_add.status_code == 201

    # 2. Crear pedido en /api/pedidos/checkout enviando datos de despacho
    r_chk = client.post("/api/pedidos/checkout", headers=headers, json={
        "nombre_receptor": "Mariana Cliente",
        "email": "mariana.cliente@test.co",
        "direccion_envio": "Calle 100 # 15-20",
        "barrio": "Chicó Norte",
        "ciudad": "Bogotá D.C.",
        "telefono": "3112223344",
        "observaciones": "Dejar en portería"
    })
    assert r_chk.status_code == 201
    orden_data = r_chk.get_json()["data"]
    codigo_orden = orden_data["codigo_orden"]
    id_pedido = orden_data["id_pedido"]
    assert codigo_orden.startswith("ORD-")
    assert "https://wa.me/" in orden_data["url_comprobante_whatsapp"]

    # 3. Verificar que el carrito quedó vacío tras el checkout
    r_cart = client.get("/api/carrito", headers=headers)
    assert r_cart.get_json()["data"]["total_unidades"] == 0

    # 4. Consultar seguimiento público por código de orden y contacto (RF-PED-003)
    r_trk = client.get(f"/api/pedidos/seguimiento/{codigo_orden}?contacto=mariana.cliente@test.co")
    assert r_trk.status_code == 200
    assert r_trk.get_json()["data"]["codigo_orden"] == codigo_orden

    # 5. Autenticar como Administradora para operar el OMS (RF-PED-002 y RF-PED-004)
    token_admin = auth_service.validar_credenciales("admin@onestylemariana.co", "AdminOneStyle2026")
    admin_headers = {"Authorization": f"Bearer {token_admin}"}

    # Intentar salto inválido en OMS (de Registrado directo a Entregado) -> 400 Bad Request
    r_bad_fsm = client.patch(f"/api/admin/pedidos/{id_pedido}/estado", headers=admin_headers, json={
        "nuevo_estado": "Entregado",
        "motivo": "Intento salto ilegal"
    })
    assert r_bad_fsm.status_code == 400

    # Transición válida a Confirmado -> 200 OK
    r_ok_fsm = client.patch(f"/api/admin/pedidos/{id_pedido}/estado", headers=admin_headers, json={
        "nuevo_estado": "Confirmado",
        "motivo": "Comprobante recibido vía WhatsApp"
    })
    assert r_ok_fsm.status_code == 200
    assert r_ok_fsm.get_json()["data"]["estado"] == "Confirmado"

    # 6. Generar reporte consolidado de ventas (RF-PED-004)
    r_rep = client.get("/api/admin/pedidos/reporte", headers=admin_headers)
    assert r_rep.status_code == 200
    assert r_rep.get_json()["data"]["total_pedidos"] >= 1


def test_checkout_identidad_inmutable_para_usuaria_autenticada():
    """
    Punto 5 (OWASP A01 / A04): Para usuarias autenticadas, el backend toma nombre_receptor
    y email desde la sesión autenticada ignorando alteraciones enviadas desde el cliente,
    conservando editables teléfono, dirección, barrio, ciudad y observaciones.
    """
    import uuid
    from run import app, auth_service

    client = app.test_client()
    email_real = f"camila.checkout.{uuid.uuid4().hex[:8]}@test.co"
    r_reg = client.post(
        "/api/auth/register",
        json={
            "nombre": "Camila",
            "apellido": "Rojas",
            "email": email_real,
            "contrasena": "CheckoutPass1",
            "telefono": "3001119900",
        },
    )
    if r_reg.status_code == 201:
        token_user = r_reg.get_json()["data"]["token"]
    else:
        token_user = auth_service.validar_credenciales(email_real, "CheckoutPass1")

    headers = {
        "Authorization": f"Bearer {token_user}",
        "X-Session-ID": f"test-checkout-auth-{uuid.uuid4().hex[:8]}",
    }

    r_add = client.post("/api/carrito/items", headers=headers, json={"fk_id_variante": 1, "cantidad": 1})
    assert r_add.status_code == 201

    # Intentar alterar nombre y correo en /api/carrito/despacho
    r_desp = client.post(
        "/api/carrito/despacho",
        headers=headers,
        json={
            "nombre_receptor": "Atacante Suplantador",
            "email": "impostor@evil.test",
            "direccion_envio": "Cra 7 # 45-10",
            "barrio": "Chapinero",
            "ciudad": "Bogotá",
            "telefono": "3005559988",
            "observaciones": "Llamar antes de subir",
        },
    )
    assert r_desp.status_code == 200
    desp = r_desp.get_json()["data"]
    assert desp["email"] == email_real
    assert "Camila" in desp["nombre_receptor"]
    assert "Atacante" not in desp["nombre_receptor"]

    # Confirmar pedido enviando nuevamente identidad alterada en /api/pedidos/checkout
    r_chk = client.post(
        "/api/pedidos/checkout",
        headers=headers,
        json={
            "nombre_receptor": "Otro Nombre Falso",
            "email": "otro@evil.test",
            "direccion_envio": "Cra 7 # 45-10 Apto 302",
            "barrio": "Chapinero Alto",
            "ciudad": "Bogotá D.C.",
            "telefono": "3007776655",
            "observaciones": "Entregar en recepción",
        },
    )
    assert r_chk.status_code == 201
    despacho_final = r_chk.get_json()["data"]["datos_despacho"]
    assert despacho_final["email"] == email_real
    assert "Camila" in despacho_final["nombre_receptor"]
    assert "Otro Nombre" not in despacho_final["nombre_receptor"]
    assert despacho_final["telefono"] == "3007776655"
    assert despacho_final["direccion_envio"] == "Cra 7 # 45-10 Apto 302"
    assert despacho_final["barrio"] == "Chapinero Alto"
    assert despacho_final["ciudad"] == "Bogotá D.C."
    assert despacho_final["observaciones"] == "Entregar en recepción"


def test_reporte_vendedoras_fechas_csv_injection_y_rbac():
    """
    RF-PED-004 (OWASP A01 / CSV Injection):
    - Endpoints de reporte por vendedora (/reporte y /reporte/csv) exclusivos para Administradora (403 a Vendedora/Clienta).
    - Validación fecha_inicio <= fecha_fin (400 si rango invertido) y filtrado por fechas.
    - Neutralización contra Formula Injection (=, +, -, @) en CSV.
    """
    import uuid
    from datetime import datetime, timedelta
    from run import app, auth_service, pedidos_service

    client = app.test_client()
    suffix = uuid.uuid4().hex[:8]
    tok_adm = auth_service.validar_credenciales("admin@onestylemariana.co", "AdminOneStyle2026")
    tok_ven = auth_service.validar_credenciales("vendedora@onestylemariana.co", "VentasOneStyle2026")
    adm_hdr = {"Authorization": f"Bearer {tok_adm}"}
    ven_hdr = {"Authorization": f"Bearer {tok_ven}"}

    r_cli = client.post(
        "/api/auth/register",
        json={"nombre": "Paula", "apellido": "Rep", "email": f"paula.rep.{suffix}@test.co", "contrasena": "ReportPass1"},
    )
    assert r_cli.status_code == 201
    tok_cli = r_cli.get_json()["data"]["token"]
    cli_hdr = {"Authorization": f"Bearer {tok_cli}"}

    # 1. RBAC: Vendedora y Clienta reciben 403
    for bad_hdr in (ven_hdr, cli_hdr):
        assert client.get("/api/admin/pedidos/reporte", headers=bad_hdr).status_code == 403
        assert client.get("/api/admin/pedidos/reporte/csv", headers=bad_hdr).status_code == 403

    # 2. Rango de fechas invertido devuelve 400
    assert client.get("/api/admin/pedidos/reporte?fecha_inicio=2026-12-31&fecha_fin=2026-01-01", headers=adm_hdr).status_code == 400
    assert client.get("/api/admin/pedidos/reporte/csv?fecha_inicio=2026-12-31&fecha_fin=2026-01-01", headers=adm_hdr).status_code == 400

    # 3. Crear vendedora con nombre potencial de CSV Injection y asignar un pedido con fecha controlada
    vend_formula_id = auth_service.registrar_personal(
        tok_adm,
        "=CMD|'/C calc'!A0",
        "Asesora",
        f"formula.{suffix}@onestyle.co",
        "VentasFormula1",
        "Vendedora",
    )
    ped_id = pedidos_service.crear_pedido(usuario_id=r_cli.get_json()["data"]["id_usuario"], items_carrito={1: 1})
    hoy_dt = datetime.now()
    ayer_str = (hoy_dt - timedelta(days=1)).strftime("%Y-%m-%d")
    hoy_str = hoy_dt.strftime("%Y-%m-%d")
    futuro_ini = (hoy_dt + timedelta(days=10)).strftime("%Y-%m-%d")
    futuro_fin = (hoy_dt + timedelta(days=15)).strftime("%Y-%m-%d")

    pedidos_service.pedidos[ped_id]["fk_id_vendedora_asig"] = vend_formula_id

    try:
        r_rep = client.get(
            f"/api/admin/pedidos/reporte?fecha_inicio={ayer_str}&fecha_fin={hoy_str}",
            headers=adm_hdr,
        )
        assert r_rep.status_code == 200
        data_rep = r_rep.get_json()["data"]
        vendedoras = data_rep.get("resumen_vendedoras", [])
        match_v = next(v for v in vendedoras if v["vendedora_id"] == vend_formula_id)
        assert match_v["cantidad_pedidos"] >= 1
        assert match_v["total_vendido"] > 0

        # Rango futuro sin pedidos excluye la orden
        r_empty = client.get(
            f"/api/admin/pedidos/reporte?fecha_inicio={futuro_ini}&fecha_fin={futuro_fin}",
            headers=adm_hdr,
        )
        assert r_empty.status_code == 200
        assert r_empty.get_json()["data"]["total_pedidos"] == 0

        # Exportación CSV neutraliza Formula Injection
        r_csv = client.get(
            f"/api/admin/pedidos/reporte/csv?fecha_inicio={ayer_str}&fecha_fin={hoy_str}",
            headers=adm_hdr,
        )
        assert r_csv.status_code == 200
        assert "text/csv" in r_csv.headers.get("Content-Type", "")
        csv_body = r_csv.get_data(as_text=True)
        assert "'=CMD|'/C calc'!A0 Asesora" in csv_body
    finally:
        auth_service.desactivar_personal(tok_adm, vend_formula_id)


import pytest
from src.carrito.service import CarritoService
from src.catalogo.service import CatalogoService

@pytest.fixture
def catalogo():
    cat = CatalogoService()
    # Create a mock product and variant
    prod_id = cat.crear_producto("Blusa", "Blusa roja", 50.0, 1)
    var_id = cat.agregar_variante(prod_id, stock=10)
    return cat, var_id

@pytest.fixture
def carrito(catalogo):
    cat, _ = catalogo
    return CarritoService(cat)

def test_agregar_al_carrito_exito(carrito, catalogo):
    _, var_id = catalogo

    qty = carrito.agregar_al_carrito(var_id, 2)
    assert qty == 2

    qty = carrito.agregar_al_carrito(var_id, 3)
    assert qty == 5

def test_agregar_al_carrito_sin_stock(carrito, catalogo):
    _, var_id = catalogo

    with pytest.raises(ValueError, match="Stock insuficiente"):
        carrito.agregar_al_carrito(var_id, 15)

def test_agregar_cantidad_invalida(carrito, catalogo):
    _, var_id = catalogo

    with pytest.raises(ValueError, match="mayor a cero"):
        carrito.agregar_al_carrito(var_id, 0)

    with pytest.raises(ValueError, match="mayor a cero"):
        carrito.agregar_al_carrito(var_id, -5)

def test_modificar_cantidad_carrito(carrito, catalogo):
    _, var_id = catalogo

    carrito.agregar_al_carrito(var_id, 2)
    qty = carrito.modificar_cantidad_carrito(var_id, 5)

    assert qty == 5
    assert carrito.get_items()[var_id] == 5

def test_modificar_cantidad_sin_stock(carrito, catalogo):
    _, var_id = catalogo

    carrito.agregar_al_carrito(var_id, 2)

    with pytest.raises(ValueError, match="Stock insuficiente"):
        carrito.modificar_cantidad_carrito(var_id, 15)

def test_vaciar_carrito(carrito, catalogo):
    _, var_id = catalogo

    carrito.agregar_al_carrito(var_id, 2)
    assert len(carrito.get_items()) == 1

    carrito.vaciar_carrito()
    assert len(carrito.get_items()) == 0

def test_impedir_reservar_mas_existencias(carrito, catalogo):
    cat, var_id = catalogo

    # Hay 10 en stock real inicialmente
    carrito.agregar_item(var_id, 8)
    assert cat.variantes[var_id]['stock_reservado'] == 8

    # Intentar reservar 3 más debería fallar, dado que 8 + 3 = 11 > 10
    with pytest.raises(ValueError, match="Stock insuficiente"):
        carrito.agregar_item(var_id, 3)

    assert cat.variantes[var_id]['stock_reservado'] == 8

def test_confirmar_liberacion_stock(carrito, catalogo):
    cat, var_id = catalogo

    carrito.agregar_item(var_id, 5)
    assert cat.variantes[var_id]['stock_reservado'] == 5

    # Remover 2
    carrito.remover_item(var_id, 2)
    assert cat.variantes[var_id]['stock_reservado'] == 3
    assert carrito.get_items()[var_id] == 3

    # Remover el resto
    carrito.remover_item(var_id)
    assert cat.variantes[var_id]['stock_reservado'] == 0
    assert var_id not in carrito.get_items()


# =========================================================================
# NUEVOS CASOS DE PRUEBA TDD — MÓDULO 3: CARRITO Y RESERVAS TEMPORALES (TTL)
# Trazabilidad: RF-CRT-001 a RF-CRT-003 / RN-CRT-001 a RN-CRT-003 / RNF-002
# =========================================================================

import threading
from datetime import datetime, timedelta
from src.catalogo.service import ConflictError


def test_rf_crt_001_002_precio_congelado_subtotales_y_total(carrito, catalogo):
    """RF-CRT-001 y RF-CRT-002: Congela precio unitario al añadir y calcula subtotales y total dinámicamente."""
    cat, var_id = catalogo
    carrito.agregar_item(var_id, 2)

    # Si el precio del producto cambia después en catálogo, el carrito conserva el precio congelado
    prod_id = cat.variantes[var_id]["producto_id"]
    cat.productos[prod_id]["precio"] = 999.0

    resumen = carrito.obtener_resumen()
    assert len(resumen["items"]) == 1
    assert resumen["items"][0]["precio_unitario"] == 50.0
    assert resumen["items"][0]["subtotal"] == 100.0
    assert resumen["total"] == 100.0
    assert resumen["ttl_segundos"] > 0


def test_rf_crt_001_concurrencia_dos_carritos_ultima_unidad():
    """RNF-002 y RF-CRT-001: Dos carritos intentando reservar simultáneamente la última unidad disponible."""
    cat = CatalogoService()
    prod_id = cat.crear_producto("Corset Edición Limitada", "Pieza única", 180000.0, 1)
    var_id = cat.agregar_variante(prod_id, stock=1)

    carrito_clienta_1 = CarritoService(cat, ttl_minutos=15)
    carrito_clienta_2 = CarritoService(cat, ttl_minutos=15)

    resultados = []
    errores = []

    def intentar_reserva(c):
        try:
            c.agregar_item(var_id, 1)
            resultados.append("OK")
        except ConflictError as e:
            errores.append(str(e))

    t1 = threading.Thread(target=intentar_reserva, args=(carrito_clienta_1,))
    t2 = threading.Thread(target=intentar_reserva, args=(carrito_clienta_2,))
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    # Exactamente uno tiene éxito y el segundo es rechazado con ConflictError
    assert len(resultados) == 1
    assert len(errores) == 1
    assert cat.variantes[var_id]["stock_reservado"] == 1
    assert cat.consultar_disponibilidad(var_id) == 0


def test_rf_crt_001_expiracion_ttl_libera_stock_automaticamente():
    """RN-CRT-001: Una reserva vencida libera automáticamente el stock y no bloquea compras posteriores."""
    cat = CatalogoService()
    prod_id = cat.crear_producto("Vestido Gala", "Seda", 250000.0, 1)
    var_id = cat.agregar_variante(prod_id, stock=2)

    carrito_abandonado = CarritoService(cat, ttl_minutos=15)
    carrito_nuevo = CarritoService(cat, ttl_minutos=15)

    # El primer carrito reserva las 2 únicas unidades disponibles
    carrito_abandonado.agregar_item(var_id, 2)
    assert cat.consultar_disponibilidad(var_id) == 0

    # Simular expiración del TTL del primer carrito retrocediendo su timestamp
    carrito_abandonado.timestamps[var_id] = datetime.now() - timedelta(seconds=10)
    if var_id in carrito_abandonado.reservas:
        carrito_abandonado.reservas[var_id]["expires_at"] = datetime.now() - timedelta(seconds=10)

    # El segundo carrito intenta comprarlas: la evaluación perezosa libera la reserva expirada y permite la compra
    qty = carrito_nuevo.agregar_item(var_id, 2)
    assert qty == 2
    assert len(carrito_abandonado.get_items()) == 0
    assert cat.variantes[var_id]["stock_reservado"] == 2


def test_rf_crt_003_validacion_datos_despacho_obligatorios(carrito):
    """RF-CRT-003 / RN-CRT-003: Obligatoriedad de dirección, barrio, ciudad y teléfono antes de checkout."""
    with pytest.raises(ValueError, match="barrio"):
        carrito.capturar_datos_despacho(
            direccion_envio="Calle 93 # 12-54",
            barrio="",
            ciudad="Bogotá",
            telefono="3001234567"
        )

    datos = carrito.capturar_datos_despacho(
        direccion_envio="Calle 93 # 12-54",
        barrio="Chicó Reservado",
        ciudad="Bogotá D.C.",
        telefono="3001234567",
        observaciones="Apto 502"
    )
    assert datos["barrio"] == "Chicó Reservado"
    assert datos["ciudad"] == "Bogotá D.C."


def test_api_rest_carrito_codigos_http_y_reserva_stock():
    """Pruebas de integración HTTP para endpoints /api/carrito/* (200, 201, 400, 404, 409)."""
    from run import app

    client = app.test_client()
    headers = {"X-Session-ID": "test-session-crt-001"}

    # Limpiar carrito de la sesión de prueba
    client.delete("/api/carrito", headers=headers)

    # 1. Agregar variante válida al carrito (201) — RF-CRT-001
    res_add = client.post("/api/carrito/items", headers=headers, json={
        "fk_id_variante": 1,
        "cantidad": 2
    })
    assert res_add.status_code == 201
    data_add = res_add.get_json()["data"]
    assert data_add["total_unidades"] == 2
    assert data_add["total"] > 0

    # 2. Cantidad inválida <= 0 retorna 400
    res_bad = client.post("/api/carrito/items", headers=headers, json={
        "fk_id_variante": 1,
        "cantidad": 0
    })
    assert res_bad.status_code == 400

    # 3. Variante inexistente retorna 404
    res_404 = client.post("/api/carrito/items", headers=headers, json={
        "fk_id_variante": 99999,
        "cantidad": 1
    })
    assert res_404.status_code == 404

    # 4. Intentar reservar más del stock disponible retorna 409 Conflict — RN-CRT-001
    res_409 = client.post("/api/carrito/items", headers=headers, json={
        "fk_id_variante": 1,
        "cantidad": 500
    })
    assert res_409.status_code == 409

    # 5. Modificar cantidad (PUT 200) — RF-CRT-002
    res_put = client.put("/api/carrito/items/1", headers=headers, json={
        "cantidad": 3
    })
    assert res_put.status_code == 200
    assert res_put.get_json()["data"]["total_unidades"] == 3

    # 6. Capturar datos de despacho (POST 200) — RF-CRT-003
    res_desp = client.post("/api/carrito/despacho", headers=headers, json={
        "direccion_envio": "Cra 43A # 1-50",
        "barrio": "El Poblado",
        "ciudad": "Medellín",
        "telefono": "3105556677",
        "observaciones": "Entregar en portería"
    })
    assert res_desp.status_code == 200

    # 7. Eliminar ítem y vaciar carrito (200) — RF-CRT-002
    res_del = client.delete("/api/carrito/items/1", headers=headers)
    assert res_del.status_code == 200
    assert res_del.get_json()["data"]["total_unidades"] == 0


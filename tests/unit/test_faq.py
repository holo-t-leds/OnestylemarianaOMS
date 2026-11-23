# tests/unit/test_faq.py
import pytest
from src.faq.service import FAQService

def test_creacion_y_listado_publico_faq():
    service = FAQService()
    fid = service.crear_faq("¿Cómo compro?", "Selecciona prendas y confirma por WhatsApp.", 1, 1, "admin")
    
    publicas = service.obtener_faqs_publicas()
    assert len(publicas) == 1
    assert publicas[0]["pregunta"] == "¿Cómo compro?"
    assert publicas[0]["categoria"] == "Envíos y Entregas"

def test_baja_logica_oculta_de_vista_publica():
    service = FAQService()
    fid = service.crear_faq("¿Puedo pagar con Nequi?", "Sí, aceptamos Nequi.", 2, 1, "admin")
    
    # Desactivar pregunta (RF-FAQ-008)
    service.cambiar_estado(fid, "inactivo", "admin")
    
    # En vista pública no debe aparecer
    assert len(service.obtener_faqs_publicas()) == 0
    # En panel administrativo sí debe existir
    assert len(service.listar_todas_admin()) == 1

def test_busqueda_dinamica_palabra_clave():
    service = FAQService()
    service.crear_faq("Tiempos de entrega", "Tardamos entre 2 y 4 días hábiles.", 1, 1, "admin")
    service.crear_faq("Costos de envío", "El envío cuesta $10.000.", 1, 2, "admin")

    coincidencias = service.buscar_faqs("hábiles")
    assert len(coincidencias) == 1
    assert coincidencias[0]["pregunta"] == "Tiempos de entrega"

def test_enlace_soporte_whatsapp():
    service = FAQService()
    url = service.generar_enlace_soporte_whatsapp()
    assert "https://api.whatsapp.com/send?phone=" in url
    assert "OneStyle" in url


# =========================================================================
# NUEVAS PRUEBAS TDD — MÓDULO 5: CENTRO DE AYUDA, FAQ Y CANALES DE SOPORTE
# Trazabilidad: RF-FAQ-001 a RF-FAQ-011 / Reglas: RN-FAQ-001 a RN-FAQ-011
# =========================================================================

def test_rf_faq_001_003_004_paginacion_filtro_categoria_y_busqueda_exacta_parcial():
    """
    RF-FAQ-001 a RF-FAQ-004: Consulta pública de FAQs activas (excluyendo inactivas),
    filtrado por categoría/slug, búsqueda por término clave exacta/parcial y votos de utilidad.
    """
    service = FAQService(seed_defaults=True)
    # Desactivar una pregunta para comprobar que no se liste en público
    todas = service.listar_todas_admin()
    assert len(todas) >= 3
    fid_inactiva = todas[0]["id_faq"]
    service.cambiar_estado(fid_inactiva, "inactivo", "admin")

    publicas = service.obtener_faqs_publicas()
    assert all(f["id_faq"] != fid_inactiva for f in publicas)

    # Búsqueda exacta y parcial insensible a mayúsculas/minúsculas (RF-FAQ-004)
    res_parcial = service.buscar_faqs("camB")
    assert len(res_parcial) >= 1

    # Voto de utilidad en una FAQ activa
    fid_activa = publicas[0]["id_faq"]
    votos = service.registrar_voto_faq(fid_activa, util=True, client_key="ip-1")
    assert votos["helpful_count"] == 1
    assert votos["not_helpful_count"] == 0


def test_rf_faq_005_al_010_crud_admin_unicidad_orden_y_reactivacion():
    """
    RF-FAQ-005 a RF-FAQ-010 / RN-FAQ-010: Creación administrativa validando orden entero positivo
    único por categoría, edición, baja lógica y reactivación inmediata.
    """
    service = FAQService()
    f1 = service.crear_faq("¿Envían a Medellín?", "Sí, a todo el país.", 1, 1, "admin")

    # Orden duplicado en la misma categoría debe fallar (RN-FAQ-010)
    with pytest.raises(ValueError, match="orden"):
        service.crear_faq("¿Cuánto tarda a Cali?", "2 a 3 días.", 1, 1, "admin")

    # Orden negativo o cero debe fallar
    with pytest.raises(ValueError, match="positivo"):
        service.crear_faq("Pregunta inválida", "Respuesta", 1, 0, "admin")

    # Baja lógica (RF-FAQ-008) y reactivación inmediata (RF-FAQ-009)
    service.cambiar_estado(f1, "inactivo", "admin")
    assert len(service.obtener_faqs_publicas()) == 0
    service.cambiar_estado(f1, "activo", "admin")
    assert len(service.obtener_faqs_publicas()) == 1


def test_rf_faq_011_envio_mensaje_contacto_sanitizacion_xss_y_validaciones():
    """
    RF-FAQ-011: Creación de ticket de soporte (SupportTicket / ContactMessage) con sanitización
    estricta contra XSS, validación de correo y longitud de mensaje.
    """
    service = FAQService()
    ticket = service.crear_ticket_soporte(
        nombre="Laura <script>alert(1)</script> Gómez",
        contacto="laura@cliente.co",
        asunto="Consulta sobre talla de Corset",
        mensaje="Hola, quisiera saber las medidas exactas de la talla S en centímetros.",
        codigo_orden="ORD-00001",
        client_key="client-test-1"
    )
    assert ticket["id_ticket"] == 1
    assert ticket["estado"] == "ABIERTO"
    assert "<script>" not in ticket["nombre"]
    assert ticket["codigo_orden"] == "ORD-00001"

    # Correo inválido o mensaje demasiado corto deben ser rechazados con ValueError (400)
    with pytest.raises(ValueError, match="correo"):
        service.crear_ticket_soporte(
            nombre="Laura",
            contacto="correo-invalido-sin-arroba",
            asunto="Duda",
            mensaje="Mensaje suficientemente largo para prueba.",
            client_key="client-test-2"
        )

    with pytest.raises(ValueError, match="mensaje"):
        service.crear_ticket_soporte(
            nombre="Laura",
            contacto="laura@cliente.co",
            asunto="Duda",
            mensaje="Corto",
            client_key="client-test-2"
        )


def test_rf_faq_rate_limiting_429_en_contacto_y_endpoints_api_v1():
    """
    Prueba integral de los endpoints REST de Módulo 5:
    - GET /api/v1/faqs/ (paginado, filtro por categoría y búsqueda)
    - POST /api/v1/faqs/<id>/vote/ (feedback de utilidad)
    - POST /api/v1/support/contact/ (201 en envío válido, 400 en inválido y 429 Too Many Requests ante ráfaga)
    - POST /api/admin/faqs (protegido por RBAC)
    """
    from run import app, faq_service

    faq_service.reset_rate_limits()
    client = app.test_client()

    # 1. GET /api/v1/faqs/ público paginado y filtrado
    r_list = client.get("/api/v1/faqs/?q=envío&page=1&per_page=5")
    assert r_list.status_code == 200
    data_list = r_list.get_json()["data"]
    assert "items" in data_list
    assert len(data_list["items"]) >= 1
    faq_id = data_list["items"][0]["id_faq"]

    # 2. POST /api/v1/faqs/<id>/vote/
    r_vote = client.post(f"/api/v1/faqs/{faq_id}/vote/", json={"helpful": True})
    assert r_vote.status_code == 200
    assert r_vote.get_json()["data"]["helpful_count"] >= 1

    # 3. POST /api/v1/support/contact/ con payload incompleto -> 400 Bad Request
    r_bad = client.post("/api/v1/support/contact/", json={
        "nombre": "Test",
        "email": "no-es-correo",
        "asunto": "Ayuda",
        "mensaje": "Corto"
    })
    assert r_bad.status_code == 400

    # 4. POST /api/v1/support/contact/ con payload válido -> 201 Created
    headers_burst = {"X-Forwarded-For": "198.51.100.77"}
    for i in range(3):
        r_ok = client.post("/api/v1/support/contact/", headers=headers_burst, json={
            "nombre": f"Usuaria {i}",
            "email": f"usuaria{i}@onestyle.co",
            "asunto": "Soporte de Pedido",
            "mensaje": "Necesito confirmar el horario de entrega de mi prenda en Bogotá.",
            "codigo_orden": "ORD-00001"
        })
        assert r_ok.status_code == 201

    # 5. Cuarto envío consecutivo desde la misma IP en la ventana de tiempo -> 429 Too Many Requests
    r_429 = client.post("/api/v1/support/contact/", headers=headers_burst, json={
        "nombre": "Spam Bot",
        "email": "bot@spam.co",
        "asunto": "Ráfaga automatizada",
        "mensaje": "Intento de flooding al formulario de contacto del centro de ayuda."
    })
    assert r_429.status_code == 429

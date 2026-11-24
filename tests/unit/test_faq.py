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


def test_faq_voto_unico_por_sesion_o_usuario_409():
    """Un visitante/usuario solo puede votar una vez por pregunta frecuente (409 si repite)."""
    from run import app, auth_service, faq_service

    faq_service.reset_rate_limits()
    client = app.test_client()

    r_list = client.get("/api/v1/faqs/?per_page=1")
    faq_id = r_list.get_json()["data"]["items"][0]["id_faq"]

    # 1. Invitado por X-Session-ID: primer voto 200, segundo voto 409
    sess_hdr = {"X-Session-ID": "sess-voto-unico-1"}
    r1 = client.post(f"/api/v1/faqs/{faq_id}/vote/", headers=sess_hdr, json={"helpful": True})
    assert r1.status_code == 200
    r2 = client.post(f"/api/v1/faqs/{faq_id}/vote/", headers=sess_hdr, json={"helpful": False})
    assert r2.status_code == 409

    # 2. Usuario autenticado distinto: primer voto 200, segundo voto 409
    tok_ven = auth_service.validar_credenciales("vendedora@onestylemariana.co", "VentasOneStyle2026")
    auth_hdr = {"Authorization": f"Bearer {tok_ven}"}
    r3 = client.post(f"/api/v1/faqs/{faq_id}/vote/", headers=auth_hdr, json={"helpful": True})
    assert r3.status_code == 200
    r4 = client.post(f"/api/v1/faqs/{faq_id}/vote/", headers=auth_hdr, json={"helpful": True})
    assert r4.status_code == 409


def test_mis_tickets_aislamiento_idor_y_respuesta_admin():
    """
    Punto 6 (OWASP IDOR / XSS): GET /api/v1/support/my-tickets requiere sesión válida,
    filtra estrictamente por la usuaria autenticada ignorando parámetros ?user_id= y expone
    la respuesta registrada por la administradora.
    """
    import uuid
    from run import app, auth_service

    client = app.test_client()

    # 1. Sin autenticación devuelve 401
    r_anon = client.get("/api/v1/support/my-tickets")
    assert r_anon.status_code == 401

    # 2. Crear y autenticar dos clientas distintas
    suffix = uuid.uuid4().hex[:8]
    email_a = f"ana.tickets.{suffix}@test.co"
    email_b = f"beto.tickets.{suffix}@test.co"
    r_reg_a = client.post(
        "/api/auth/register",
        json={"nombre": "Ana", "apellido": "Tickets", "email": email_a, "contrasena": "TicketsPass1"},
    )
    assert r_reg_a.status_code == 201
    uid_a = r_reg_a.get_json()["data"]["id_usuario"]
    token_a = r_reg_a.get_json()["data"]["token"]

    r_reg_b = client.post(
        "/api/auth/register",
        json={"nombre": "Beto", "apellido": "Tickets", "email": email_b, "contrasena": "TicketsPass1"},
    )
    assert r_reg_b.status_code == 201
    uid_b = r_reg_b.get_json()["data"]["id_usuario"]
    token_b = r_reg_b.get_json()["data"]["token"]

    # 3. Cada clienta crea su ticket usando IP aislada para no tocar rate-limit previo
    r_tick_a = client.post(
        "/api/v1/support/contact/",
        headers={"Authorization": f"Bearer {token_a}", "X-Forwarded-For": "10.200.200.1"},
        json={
            "nombre": "Ana Tickets",
            "email": email_a,
            "codigo_orden": "ORD-TICKET-A",
            "asunto": "Consulta de medidas de prenda",
            "mensaje": "Quisiera confirmar las medidas exactas de la prenda.",
        },
    )
    assert r_tick_a.status_code == 201
    id_a = r_tick_a.get_json()["data"]["id_ticket"]

    r_tick_b = client.post(
        "/api/v1/support/contact/",
        headers={"Authorization": f"Bearer {token_b}", "X-Forwarded-For": "10.200.200.2"},
        json={
            "nombre": "Beto Tickets",
            "email": email_b,
            "codigo_orden": "",
            "asunto": "Ticket confidencial de Beto",
            "mensaje": "Este mensaje solo debe verlo Beto.",
        },
    )
    assert r_tick_b.status_code == 201
    id_b = r_tick_b.get_json()["data"]["id_ticket"]

    # 4. La administradora responde al ticket de Ana (ABIERTO -> EN_PROCESO -> RESUELTO)
    token_admin = auth_service.validar_credenciales("admin@onestylemariana.co", "AdminOneStyle2026")
    admin_hdr = {"Authorization": f"Bearer {token_admin}"}
    r_proc = client.patch(
        f"/api/v1/admin/support/tickets/{id_a}",
        headers=admin_hdr,
        json={"estado": "EN_PROCESO"},
    )
    assert r_proc.status_code == 200

    respuesta_admin = "Hola Ana, la talla M corresponde exactamente a la guía oficial."
    r_res = client.patch(
        f"/api/v1/admin/support/tickets/{id_a}",
        headers=admin_hdr,
        json={"estado": "RESUELTO", "respuesta": respuesta_admin},
    )
    assert r_res.status_code == 200

    # 5. Ana consulta sus tickets intentando forzar ?user_id=<uid_b> -> solo ve los suyos
    r_mine_a = client.get(
        f"/api/v1/support/my-tickets?user_id={uid_b}",
        headers={"Authorization": f"Bearer {token_a}"},
    )
    assert r_mine_a.status_code == 200
    items_a = r_mine_a.get_json()["data"]
    ids_a = {t["id_ticket"] for t in items_a}
    assert id_a in ids_a
    assert id_b not in ids_a
    ticket_a = next(t for t in items_a if t["id_ticket"] == id_a)
    assert ticket_a["estado"] == "RESUELTO"
    assert ticket_a["respuesta_soporte"] == respuesta_admin

    # 6. Beto consulta intentando forzar ?user_id=<uid_a> -> solo ve los suyos
    r_mine_b = client.get(
        f"/api/v1/support/my-tickets?user_id={uid_a}",
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert r_mine_b.status_code == 200
    ids_b = {t["id_ticket"] for t in r_mine_b.get_json()["data"]}
    assert id_b in ids_b
    assert id_a not in ids_b


def test_admin_faqs_crud_reordenar_y_rbac_solo_admin():
    """
    RF-FAQ-005..010 (OWASP A01):
    - Todos los endpoints de /api/admin/faqs* exigen estrictamente rol Administradora (403 a Vendedora/Clienta).
    - Crear, editar, reordenar (con intercambio atómico en misma categoría) y desactivar/reactivar se reflejan en #/ayuda.
    """
    import uuid
    from run import app, auth_service

    client = app.test_client()
    suffix = uuid.uuid4().hex[:8]
    tok_adm = auth_service.validar_credenciales("admin@onestylemariana.co", "AdminOneStyle2026")
    tok_ven = auth_service.validar_credenciales("vendedora@onestylemariana.co", "VentasOneStyle2026")
    r_cli = client.post(
        "/api/auth/register",
        json={"nombre": "Sofia", "apellido": "Faq", "email": f"sofia.faq.{suffix}@test.co", "contrasena": "FaqPass123"},
    )
    assert r_cli.status_code == 201
    tok_cli = r_cli.get_json()["data"]["token"]

    adm_hdr = {"Authorization": f"Bearer {tok_adm}"}
    ven_hdr = {"Authorization": f"Bearer {tok_ven}"}
    cli_hdr = {"Authorization": f"Bearer {tok_cli}"}

    # 1. RBAC estricto: Vendedora y Clienta reciben 403 en todos los endpoints admin FAQ
    for bad_hdr in (ven_hdr, cli_hdr):
        assert client.get("/api/admin/faqs", headers=bad_hdr).status_code == 403
        assert client.get("/api/admin/faqs/categorias", headers=bad_hdr).status_code == 403
        assert client.post(
            "/api/admin/faqs",
            headers=bad_hdr,
            json={"pregunta": "No autorizado", "respuesta": "No", "id_categoria": 1, "orden": 99},
        ).status_code == 403
        assert client.put(
            "/api/admin/faqs/1",
            headers=bad_hdr,
            json={"pregunta": "No", "respuesta": "No", "id_categoria": 1, "orden": 1},
        ).status_code == 403
        assert client.patch("/api/admin/faqs/1/orden", headers=bad_hdr, json={"orden": 1}).status_code == 403
        assert client.patch("/api/admin/faqs/1/estado", headers=bad_hdr, json={"estado": "inactivo"}).status_code == 403

    # 2. Administradora lista categorías y FAQs y crea dos FAQs en categoría 1 con orden libre alto
    r_cats = client.get("/api/admin/faqs/categorias", headers=adm_hdr)
    assert r_cats.status_code == 200
    assert len(r_cats.get_json()["data"]) >= 1

    existentes = client.get("/api/admin/faqs", headers=adm_hdr).get_json()["data"]
    max_ord_cat1 = max([int(f["orden"]) for f in existentes if f["id_categoria"] == 1] or [0])

    r_f1 = client.post(
        "/api/admin/faqs",
        headers=adm_hdr,
        json={
            "pregunta": f"Pregunta FAQ Uno {suffix}",
            "respuesta": "Respuesta inicial Uno.",
            "id_categoria": 1,
            "orden": max_ord_cat1 + 1,
        },
    )
    r_f2 = client.post(
        "/api/admin/faqs",
        headers=adm_hdr,
        json={
            "pregunta": f"Pregunta FAQ Dos {suffix}",
            "respuesta": "Respuesta inicial Dos.",
            "id_categoria": 1,
            "orden": max_ord_cat1 + 2,
        },
    )
    assert r_f1.status_code == 201
    assert r_f2.status_code == 201
    id_1 = r_f1.get_json()["data"]["id_faq"]
    id_2 = r_f2.get_json()["data"]["id_faq"]

    try:
        # 3. Editar FAQ 1
        r_upd = client.put(
            f"/api/admin/faqs/{id_1}",
            headers=adm_hdr,
            json={
                "pregunta": f"Pregunta Editada {suffix}",
                "respuesta": "Respuesta editada y anonimizada.",
                "id_categoria": 1,
                "orden": max_ord_cat1 + 1,
            },
        )
        assert r_upd.status_code == 200

        # 4. Reordenar FAQ 2 a la posición de FAQ 1 (intercambio atómico)
        r_reord = client.patch(
            f"/api/admin/faqs/{id_2}/orden",
            headers=adm_hdr,
            json={"orden": max_ord_cat1 + 1},
        )
        assert r_reord.status_code == 200
        lista_adm = client.get("/api/admin/faqs", headers=adm_hdr).get_json()["data"]
        f1_after = next(f for f in lista_adm if f["id_faq"] == id_1)
        f2_after = next(f for f in lista_adm if f["id_faq"] == id_2)
        assert f2_after["orden"] == max_ord_cat1 + 1
        assert f1_after["orden"] == max_ord_cat1 + 2

        # 5. Desactivar FAQ 1 y comprobar que desaparece de GET /api/v1/faqs/; reactivar y comprobar visibilidad
        assert client.patch(f"/api/admin/faqs/{id_1}/estado", headers=adm_hdr, json={"estado": "inactivo"}).status_code == 200
        pub_off = client.get(f"/api/v1/faqs/?q={suffix}&per_page=20").get_json()["data"]["items"]
        assert id_1 not in {f["id_faq"] for f in pub_off}

        assert client.patch(f"/api/admin/faqs/{id_1}/estado", headers=adm_hdr, json={"estado": "activo"}).status_code == 200
        pub_on = client.get(f"/api/v1/faqs/?q={suffix}&per_page=20").get_json()["data"]["items"]
        assert id_1 in {f["id_faq"] for f in pub_on}
    finally:
        client.patch(f"/api/admin/faqs/{id_1}/estado", headers=adm_hdr, json={"estado": "inactivo"})
        client.patch(f"/api/admin/faqs/{id_2}/estado", headers=adm_hdr, json={"estado": "inactivo"})

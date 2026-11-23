# tests/unit/test_admin_panel.py
"""
Pruebas del Panel Administrativo SPA (#admin):
- Renovación de token con rotación (POST /api/auth/refresh)
- Paginación real del lado del servidor (GET /api/admin/pedidos, GET /api/admin/productos)
- Dashboard agregado (GET /api/admin/dashboard)
Trazabilidad: RF-SEG-006/008/009, RF-PED-002/004, RF-CAT-004/007.
"""
from run import app

ADMIN = {"email": "admin@onestylemariana.co", "contrasena": "AdminOneStyle2026"}


def _login_admin(client):
    res = client.post("/api/auth/login", json=ADMIN)
    assert res.status_code == 200
    return res.get_json()["data"]


def _crear_pedido(client, session_id, variante_id, nombre):
    h = {"X-Session-ID": session_id}
    assert client.post("/api/carrito/items", headers=h, json={"fk_id_variante": variante_id, "cantidad": 1}).status_code == 201
    res = client.post("/api/pedidos/checkout", headers=h, json={
        "nombre_receptor": nombre,
        "email": f"{session_id}@test.co",
        "direccion_envio": "Calle 1 # 2-3",
        "barrio": "Centro",
        "ciudad": "Bogotá D.C.",
        "telefono": "3101234567",
    })
    assert res.status_code == 201
    return res.get_json()["data"]


def test_refresh_token_rotacion_y_revocacion_del_par_anterior():
    client = app.test_client()
    data = _login_admin(client)
    assert data["refresh_token"] and data["expires_in"] > 0
    old_access, old_refresh = data["token"], data["refresh_token"]

    res = client.post("/api/auth/refresh", json={"refresh_token": old_refresh})
    assert res.status_code == 200
    nuevo = res.get_json()["data"]
    assert nuevo["token"] != old_access
    assert nuevo["refresh_token"] != old_refresh

    # El nuevo access funciona y el anterior quedó revocado
    assert client.get("/api/perfil", headers={"Authorization": f"Bearer {nuevo['token']}"}).status_code == 200
    assert client.get("/api/perfil", headers={"Authorization": f"Bearer {old_access}"}).status_code == 401

    # El refresh es de un solo uso
    assert client.post("/api/auth/refresh", json={"refresh_token": old_refresh}).status_code == 401


def test_refresh_token_invalido_vencido_o_ausente():
    client = app.test_client()
    assert client.post("/api/auth/refresh", json={"refresh_token": "no-existe"}).status_code == 401
    assert client.post("/api/auth/refresh", json={}).status_code == 400

    from run import auth_service
    from datetime import datetime, timedelta
    data = _login_admin(client)
    auth_service.refresh_tokens[data["refresh_token"]]["expires_at"] = datetime.now() - timedelta(seconds=1)
    assert client.post("/api/auth/refresh", json={"refresh_token": data["refresh_token"]}).status_code == 401


def test_logout_revoca_refresh_token():
    client = app.test_client()
    data = _login_admin(client)
    h = {"Authorization": f"Bearer {data['token']}"}
    assert client.post("/api/auth/logout", headers=h).status_code == 200
    assert client.post("/api/auth/refresh", json={"refresh_token": data["refresh_token"]}).status_code == 401


def test_pedidos_paginacion_servidor_filtros_y_rbac():
    client = app.test_client()
    for i, var in enumerate((1, 2, 3)):
        _crear_pedido(client, f"pag-sess-{i}", var, f"Clienta Paginada {i}")

    token = _login_admin(client)["token"]
    h = {"Authorization": f"Bearer {token}"}

    p1 = client.get("/api/admin/pedidos?page=1&per_page=2", headers=h).get_json()["data"]
    assert len(p1["items"]) == 2
    assert p1["total"] >= 3 and p1["has_next"] is True and p1["has_prev"] is False
    p2 = client.get("/api/admin/pedidos?page=2&per_page=2", headers=h).get_json()["data"]
    assert p2["has_prev"] is True
    assert {i["id_pedido"] for i in p1["items"]}.isdisjoint({i["id_pedido"] for i in p2["items"]})

    # Búsqueda en vivo y filtro por estado
    busq = client.get("/api/admin/pedidos?q=Paginada 1", headers=h).get_json()["data"]
    assert busq["total"] == 1
    assert client.get("/api/admin/pedidos?estado=Entregado", headers=h).get_json()["data"]["total"] == 0

    # Entradas inválidas y acceso no autorizado
    assert client.get("/api/admin/pedidos?page=0", headers=h).status_code == 400
    assert client.get("/api/admin/pedidos?page=abc", headers=h).status_code == 400
    assert client.get("/api/admin/pedidos?estado=Inventado", headers=h).status_code == 400
    assert client.get("/api/admin/pedidos").status_code == 401


def test_dashboard_agregado_y_proteccion_rbac():
    client = app.test_client()
    assert client.get("/api/admin/dashboard").status_code == 401

    # Una clienta no puede acceder (403)
    reg = client.post("/api/auth/register", json={
        "nombre": "Cli", "apellido": "Ente", "email": "dash.clienta@test.co", "contrasena": "ClaveSegura123"
    })
    tok_cli = reg.get_json()["data"]["token"]
    assert client.get("/api/admin/dashboard", headers={"Authorization": f"Bearer {tok_cli}"}).status_code == 403

    token = _login_admin(client)["token"]
    res = client.get("/api/admin/dashboard", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    d = res.get_json()["data"]
    for clave in ("pedidos", "inventario", "catalogo", "soporte", "pedidos_recientes"):
        assert clave in d
    assert {"pedidos_pendientes", "ventas_totales", "conteo_por_estado"} <= set(d["pedidos"])
    assert {"alertas_total", "agotadas", "stock_bajo"} <= set(d["inventario"])


def test_productos_admin_paginados_y_redireccion_del_prototipo():
    client = app.test_client()
    token = _login_admin(client)["token"]
    h = {"Authorization": f"Bearer {token}"}
    data = client.get("/api/admin/productos?page=1&per_page=4", headers=h).get_json()["data"]
    assert len(data["items"]) <= 4 and data["total"] >= 9 and data["total_pages"] >= 3
    assert client.get("/api/admin/productos?per_page=0", headers=h).status_code == 400

    res = client.get("/admin/catalogo")
    assert res.status_code == 302 and "#/admin/catalogo" in res.headers["Location"]


def test_cambio_de_password_autenticado_validaciones():
    client = app.test_client()
    token = _login_admin(client)["token"]
    h = {"Authorization": f"Bearer {token}"}

    assert client.put("/api/perfil/password", json={"contrasena_actual": "x", "nueva_password": "NuevaPassword1!"}).status_code == 401
    assert client.put("/api/perfil/password", headers=h, json={"contrasena_actual": "Incorrecta!", "nueva_password": "NuevaPassword1!"}).status_code == 400
    assert client.put("/api/perfil/password", headers=h, json={"contrasena_actual": ADMIN["contrasena"], "nueva_password": "123"}).status_code == 400

    r_ok = client.put("/api/perfil/password", headers=h, json={"contrasena_actual": ADMIN["contrasena"], "nueva_password": "AdminNueva99!"})
    assert r_ok.status_code == 200
    client.put("/api/perfil/password", headers=h, json={"contrasena_actual": "AdminNueva99!", "nueva_password": ADMIN["contrasena"]})


def test_owasp_zap_csp_sin_unsafe_inline_directivas_sin_fallback_y_sri():
    import re
    client = app.test_client()
    r1 = client.get("/")
    r2 = client.get("/")
    assert r1.status_code == 200

    csp1 = r1.headers.get("Content-Security-Policy", "")
    csp2 = r2.headers.get("Content-Security-Policy", "")

    # 1. Sin unsafe-inline en script-src ni style-src
    assert "'unsafe-inline'" not in csp1

    # 2. Directivas sin fallback definidas explícitamente
    assert "frame-ancestors 'self'" in csp1
    assert "form-action 'self'" in csp1
    assert "base-uri 'self'" in csp1

    # 3. Nonce criptográfico único por petición
    m1 = re.search(r"'nonce-([A-Za-z0-9_\-]+)'", csp1)
    m2 = re.search(r"'nonce-([A-Za-z0-9_\-]+)'", csp2)
    assert m1 and m2 and m1.group(1) != m2.group(1)

    # 4. Todos los recursos externos en HTML poseen integrity="sha384-..." y crossorigin="anonymous"
    html = r1.get_data(as_text=True)
    external_tags = re.findall(r"<(?:script|link)\b[^>]+(?:src|href)=\"https?://[^\"]+\"[^>]*>", html)
    assert len(external_tags) >= 3
    for tag in external_tags:
        assert 'integrity="sha384-' in tag
        assert 'crossorigin="anonymous"' in tag

    # 5. Cero bloques <style> o atributos style= inline en plantillas
    assert "<style" not in html
    assert 'style="' not in html

    # 6. Endpoint GET /api/productos/categorias devuelve las 6 categorías reales del catálogo
    rc = client.get("/api/productos/categorias")
    assert rc.status_code == 200
    cats = rc.get_json()["data"]
    assert len(cats) >= 6
    for c in cats:
        assert {"id_categoria", "nombre_categoria", "slug", "imagen_representativa", "total_productos"} <= set(c.keys())

    # 7. Logo oficial img/logo.jpg presente en la plantilla y colores r/n/ros/b con imagen por variante
    assert 'src="img/logo.jpg"' in html
    r_ves = client.get("/api/catalogo/vestido-imperial")
    assert r_ves.status_code == 200
    ves_data = r_ves.get_json()["data"]
    colores_ves = {c["slug"]: c["imagen_url"] for c in ves_data["colores"]}
    assert colores_ves.get("blanco") == "img/vestidoamericanoB.jpg"
    assert colores_ves.get("negro") == "img/vestidoamericanoN.jpg"
    assert colores_ves.get("rojo") == "img/vestidoamericanoR.jpg"





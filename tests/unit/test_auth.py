import pytest
from src.auth.service import AuthService

@pytest.fixture
def auth():
    return AuthService()

def test_registrar_cliente_exito(auth):
    user_id = auth.registrar_cliente("Ana", "Gomez", "ana@example.com", "SecurePwd123")
    assert user_id == 1
    assert auth.usuarios[user_id]['email'] == "ana@example.com"
    assert auth.usuarios[user_id]['rol'] == "Clienta"

def test_registrar_cliente_contrasena_corta(auth):
    with pytest.raises(ValueError, match="al menos 8 caracteres"):
        auth.registrar_cliente("Ana", "Gomez", "ana@example.com", "short")

def test_registrar_cliente_email_duplicado(auth):
    auth.registrar_cliente("Ana", "Gomez", "ana@example.com", "SecurePwd123")

    with pytest.raises(ValueError, match="ya está registrado"):
        auth.registrar_cliente("Otra", "Ana", "ana@example.com", "AnotherPwd1")

def test_validar_credenciales_exito(auth):
    auth.registrar_cliente("Ana", "Gomez", "ana@example.com", "SecurePwd123")
    token = auth.validar_credenciales("ana@example.com", "SecurePwd123")

    assert token is not None
    assert auth.verificar_sesion(token) is True

def test_validar_credenciales_fallo(auth):
    auth.registrar_cliente("Ana", "Gomez", "ana@example.com", "SecurePwd123")

    with pytest.raises(ValueError, match="Credenciales inválidas"):
        auth.validar_credenciales("ana@example.com", "wrongpwd")

    with pytest.raises(ValueError, match="Credenciales inválidas"):
         auth.validar_credenciales("nonexistent@example.com", "SecurePwd123")

def test_get_user_role(auth):
    auth.registrar_cliente("Ana", "Gomez", "ana@example.com", "SecurePwd123")
    token = auth.validar_credenciales("ana@example.com", "SecurePwd123")

    role = auth.get_user_role(token)
    assert role == "Clienta"

def test_get_user_role_token_invalido(auth):
    with pytest.raises(ValueError, match="Sesión inválida o expirada"):
        auth.get_user_role("invalid-token")

from datetime import datetime, timedelta
from src.auditoria.service import AuditoriaService

def test_recuperacion_token_ttl(auth):
    user_id = auth.registrar_cliente("Ana", "Gomez", "ana@example.com", "SecurePwd123")
    token = auth.solicitar_recuperacion("ana@example.com")

    assert token is not None
    assert auth.usuarios[user_id]['reset_token_hash'] is not None
    assert auth.usuarios[user_id]['reset_token_expira'] is not None

    # Check TTL is around 60 minutes (RN-SEG-016)
    expira = auth.usuarios[user_id]['reset_token_expira']
    expected_expira = datetime.now() + timedelta(minutes=60)

    # Compare timestamps allowing a tiny margin of error (seconds)
    delta = abs((expira - expected_expira).total_seconds())
    assert delta < 5

def test_rechazo_token_vencido(auth):
    user_id = auth.registrar_cliente("Ana", "Gomez", "ana@example.com", "SecurePwd123")
    token = auth.solicitar_recuperacion("ana@example.com")

    # Simulate expiration by rolling back the expiration time to the past
    auth.usuarios[user_id]['reset_token_expira'] = datetime.now() - timedelta(minutes=1)

    with pytest.raises(ValueError, match="El token de recuperación ha expirado"):
        auth.restablecer_password(token, "NewSecurePwd1")

def test_invalidacion_inmediata_token(auth):
    user_id = auth.registrar_cliente("Ana", "Gomez", "ana@example.com", "SecurePwd123")
    token = auth.solicitar_recuperacion("ana@example.com")

    # Reset password successfully
    result = auth.restablecer_password(token, "NewSecurePwd1")
    assert result is True

    # Validate the token hash and expiration are immediately cleared
    assert auth.usuarios[user_id]['reset_token_hash'] is None
    assert auth.usuarios[user_id]['reset_token_expira'] is None


# =========================================================================
# NUEVOS CASOS DE PRUEBA TDD — MÓDULO 1: SEGURIDAD, RBAC Y AUDITORÍA
# Trazabilidad: RF-SEG-001 a RF-SEG-017 / RN-SEG-001 a RN-SEG-017
# =========================================================================

def test_rf_seg_006_008_bloqueo_temporal_tras_3_intentos_fallidos(auth):
    """RN-SEG-008: Bloqueo temporal de 15 minutos tras 3 intentos fallidos consecutivos."""
    auth.registrar_cliente("Laura", "Perez", "laura@example.com", "SecurePass123")

    for _ in range(3):
        with pytest.raises(ValueError, match="Credenciales inválidas"):
            auth.validar_credenciales("laura@example.com", "WrongPass999")

    # El 4to intento debe ser rechazado por cuenta bloqueada aunque la clave sea correcta
    with pytest.raises(ValueError, match="Cuenta bloqueada temporalmente"):
        auth.validar_credenciales("laura@example.com", "SecurePass123")


def test_rf_seg_009_cierre_sesion_invalida_token_y_audita():
    """RF-SEG-009 / RN-SEG-009: Destruye sesión activa y registra evento LOGOUT en auditoría."""
    auditoria = AuditoriaService()
    auth = AuthService(auditoria_service=auditoria)
    auth.registrar_cliente("Maria", "Lopez", "maria@example.com", "SecurePass123")
    token = auth.validar_credenciales("maria@example.com", "SecurePass123")

    assert auth.verificar_sesion(token) is True
    assert auth.cerrar_sesion(token) is True
    assert auth.verificar_sesion(token) is False

    acciones = [log["tipo_accion"] for log in auditoria.logs]
    assert "LOGIN_SUCCESS" in acciones
    assert "LOGOUT" in acciones


def test_rf_seg_010_011_consulta_y_actualizacion_perfil():
    """RF-SEG-010 y RF-SEG-011: Consulta de perfil sin exponer hash y actualización validando unicidad."""
    auditoria = AuditoriaService()
    auth = AuthService(auditoria_service=auditoria)
    auth.registrar_cliente("Camila", "Diaz", "camila@example.com", "SecurePass123", telefono="3001112233")
    auth.registrar_cliente("Sofia", "Rios", "sofia@example.com", "SecurePass123")

    token = auth.validar_credenciales("camila@example.com", "SecurePass123")
    perfil = auth.obtener_perfil(token)

    assert perfil["nombre"] == "Camila"
    assert perfil["email"] == "camila@example.com"
    assert "pwd_hash" not in perfil
    assert "contrasena" not in perfil

    # Actualización válida
    actualizado = auth.actualizar_perfil(token, nombre="Camila Andrea", apellido="Diaz", telefono="3109998877")
    assert actualizado["nombre"] == "Camila Andrea"
    assert actualizado["telefono"] == "3109998877"

    # Intento de duplicar correo de otro usuario (RN-SEG-011)
    with pytest.raises(ValueError, match="ya está registrado"):
        auth.actualizar_perfil(token, nombre="Camila", apellido="Diaz", email="sofia@example.com")


def test_rf_seg_012_al_015_crud_y_baja_logica_personal():
    """RF-SEG-012..015: Creación, consulta, actualización y baja lógica de personal exclusivo para Administradora."""
    auditoria = AuditoriaService()
    auth = AuthService(auditoria_service=auditoria)

    # Crear usuario administrador semilla y clienta
    admin_id = auth.crear_usuario_sistema("Mariana", "Admin", "admin@onestyle.com", "AdminPass123", rol="Administradora")
    auth.registrar_cliente("Cliente", "Uno", "cliente1@example.com", "ClientPass123")

    token_admin = auth.validar_credenciales("admin@onestyle.com", "AdminPass123")
    token_clienta = auth.validar_credenciales("cliente1@example.com", "ClientPass123")

    # RN-SEG-012: Clienta no puede registrar personal operativo
    with pytest.raises(PermissionError, match="exclusivo para el rol Administradora"):
        auth.registrar_personal(token_clienta, "Valeria", "Ventas", "valeria@onestyle.com", "VentasPass123", "Vendedora")

    # Administradora registra Vendedora
    vend_id = auth.registrar_personal(
        token_admin, "Valeria", "Ventas", "valeria@onestyle.com", "VentasPass123", "Vendedora", telefono="3005554433"
    )
    assert vend_id is not None

    # RF-SEG-013: Listar personal excluye a Clientas y no expone contraseñas
    personal = auth.listar_personal(token_admin)
    emails_personal = [p["email"] for p in personal]
    assert "valeria@onestyle.com" in emails_personal
    assert "cliente1@example.com" not in emails_personal
    assert all("pwd_hash" not in p and "contrasena" not in p for p in personal)

    # RF-SEG-014: Actualizar rol/datos de personal y auditar
    auth.actualizar_personal(token_admin, vend_id, nombre="Valeria Sofia", rol="Administradora")
    assert auth.usuarios[vend_id]["rol"] == "Administradora"

    # RF-SEG-015: Baja lógica revoca sesiones activas e impide login
    token_vend = auth.validar_credenciales("valeria@onestyle.com", "VentasPass123")
    assert auth.verificar_sesion(token_vend) is True

    auth.desactivar_personal(token_admin, vend_id)
    assert auth.usuarios[vend_id]["estado_usuario"] is False
    assert auth.verificar_sesion(token_vend) is False

    with pytest.raises(ValueError, match="inactiva"):
        auth.validar_credenciales("valeria@onestyle.com", "VentasPass123")


def test_rf_seg_001_005_consulta_auditoria_inmutable_solo_admin():
    """RF-SEG-001..005 / RN-SEG-005: Solo Administradora consulta auditoría y los registros son inmutables."""
    auditoria = AuditoriaService()
    auth = AuthService(auditoria_service=auditoria)
    auth.crear_usuario_sistema("Mariana", "Admin", "admin@onestyle.com", "AdminPass123", rol="Administradora")
    auth.registrar_cliente("Elena", "Cliente", "elena@example.com", "ElenaPass123")

    token_admin = auth.validar_credenciales("admin@onestyle.com", "AdminPass123")
    token_clienta = auth.validar_credenciales("elena@example.com", "ElenaPass123")

    with pytest.raises(PermissionError, match="exclusivo para el rol Administradora"):
        auditoria.consultar_logs(rol_solicitante=auth.get_user_role(token_clienta))

    logs = auditoria.consultar_logs(rol_solicitante=auth.get_user_role(token_admin))
    assert len(logs) >= 2

    # Verificar inmutabilidad (modificar la copia devuelta no altera el log interno)
    logs[0]["tipo_accion"] = "ALTERADO"
    logs_reales = auditoria.consultar_logs(rol_solicitante="Administradora")
    assert logs_reales[0]["tipo_accion"] != "ALTERADO"


def test_api_rest_seguridad_owasp_y_endpoints():
    """Pruebas de integración HTTP sobre endpoints /api/auth/*, /api/perfil y /api/admin/* (OWASP y códigos HTTP)."""
    from run import app

    client = app.test_client()

    # 1. Registro exitoso (201) — RF-SEG-007
    res_reg = client.post("/api/auth/register", json={
        "nombre": "Natalia",
        "apellido": "Restrepo",
        "email": "natalia.test@onestyle.com",
        "contrasena": "Password123",
        "telefono": "3001234567"
    })
    assert res_reg.status_code == 201
    data_reg = res_reg.get_json()
    assert data_reg["status"] == "success"
    assert data_reg["data"]["rol"] == "Clienta"

    # Verificar encabezados de seguridad OWASP
    assert res_reg.headers.get("X-Content-Type-Options") == "nosniff"
    assert res_reg.headers.get("X-Frame-Options") == "DENY"

    # 2. Registro duplicado (400) — RN-SEG-007
    res_dup = client.post("/api/auth/register", json={
        "nombre": "Natalia",
        "apellido": "Restrepo",
        "email": "natalia.test@onestyle.com",
        "contrasena": "Password123"
    })
    assert res_dup.status_code == 400

    # 3. Rechazo de payload con intento XSS o campos no permitidos por whitelist (400)
    res_xss = client.post("/api/auth/register", json={
        "nombre": "<script>alert(1)</script>",
        "apellido": "Restrepo",
        "email": "xss@onestyle.com",
        "contrasena": "Password123",
        "fk_id_rol": 1  # Campo prohibido en auto-registro
    })
    assert res_xss.status_code == 400

    # 4. Login exitoso (200) — RF-SEG-008
    res_login = client.post("/api/auth/login", json={
        "email": "natalia.test@onestyle.com",
        "contrasena": "Password123"
    })
    assert res_login.status_code == 200
    token = res_login.get_json()["data"]["token"]
    assert token is not None

    # 5. Consulta de perfil autenticado (200) — RF-SEG-010
    res_perfil = client.get("/api/perfil", headers={"Authorization": f"Bearer {token}"})
    assert res_perfil.status_code == 200
    assert res_perfil.get_json()["data"]["email"] == "natalia.test@onestyle.com"

    # 6. Acceso denegado a ruta administrativa con token de Clienta (403) — RNF-001 / RN-SEG-005
    res_forb = client.get("/api/admin/auditoria", headers={"Authorization": f"Bearer {token}"})
    assert res_forb.status_code == 403

    # 7. Logout invalida sesión (200 y luego 401) — RF-SEG-009
    res_logout = client.post("/api/auth/logout", headers={"Authorization": f"Bearer {token}"})
    assert res_logout.status_code == 200

    res_after = client.get("/api/perfil", headers={"Authorization": f"Bearer {token}"})
    assert res_after.status_code == 401


def test_rf_seg_016_forgot_password_sin_token_demo_anti_enumeracion_y_smtp():
    """RF-SEG-016 / RN-SEG-016: Sin reset_token_demo, respuesta idéntica y despacho SMTP/consola."""
    import os
    from unittest.mock import MagicMock, patch
    from app.mailer import send_password_recovery_email
    from run import app

    client = app.test_client()

    # 1. Correo existente y correo inexistente devuelven exactamente la misma respuesta con data=None
    with patch.dict(os.environ, {"SMTP_HOST": "", "SMTP_USER": "", "SMTP_PASS": ""}, clear=False):
        r_exist = client.post("/api/auth/forgot-password", json={"email": "admin@onestylemariana.co"})
        r_missing = client.post("/api/auth/forgot-password", json={"email": "no-existe-seguridad@test.co"})

    assert r_exist.status_code == 200
    assert r_missing.status_code == 200
    b_exist = r_exist.get_json()
    b_missing = r_missing.get_json()
    assert b_exist["data"] is None
    assert b_missing["data"] is None
    assert b_exist["message"] == b_missing["message"]
    assert "reset_token_demo" not in r_exist.get_data(as_text=True)

    # 2. Fallback seguro a consola sin SMTP
    with patch.dict(os.environ, {"SMTP_HOST": "", "SMTP_USER": "", "SMTP_PASS": ""}, clear=False):
        mode_console = send_password_recovery_email("clienta@test.co", "tok-local-123", ttl_minutes=60)
        assert mode_console == "console"

    # 3. Envío SMTP cuando hay configuración en .env
    mock_smtp_instance = MagicMock()
    mock_smtp_cls = MagicMock()
    mock_smtp_cls.return_value.__enter__.return_value = mock_smtp_instance

    with patch.dict(
        os.environ,
        {
            "SMTP_HOST": "smtp.example.com",
            "SMTP_PORT": "587",
            "SMTP_USER": "tienda@example.com",
            "SMTP_PASS": "app-secret-pass",
            "SMTP_FROM": "OneStyle <tienda@example.com>",
        },
        clear=False,
    ), patch("smtplib.SMTP", mock_smtp_cls):
        mode_smtp = send_password_recovery_email("clienta@test.co", "tok-smtp-456", ttl_minutes=60)
        assert mode_smtp == "smtp"
        mock_smtp_instance.starttls.assert_called_once()
        mock_smtp_instance.login.assert_called_once_with("tienda@example.com", "app-secret-pass")
        mock_smtp_instance.send_message.assert_called_once()


def test_rn_seg_008_complejidad_password_registro_cambio_y_reset():
    """
    RN-SEG-008: Registro, cambio de contraseña autenticado y restablecimiento rechazan con HTTP 400
    claves sin mínimo 8 caracteres, mayúscula, minúscula y número.
    """
    import uuid
    from run import app, auth_service

    client = app.test_client()
    email_unico = f"valeria.rn008.{uuid.uuid4().hex[:8]}@test.co"
    debil_cases = ["Ab1cdef", "lowercase123", "UPPERCASE123", "NoDigitsPass"]

    # 1. Rechazo en /api/auth/register
    for pwd in debil_cases:
        r_bad = client.post(
            "/api/auth/register",
            json={
                "nombre": "Valeria",
                "apellido": "Castro",
                "email": email_unico,
                "contrasena": pwd,
            },
        )
        assert r_bad.status_code == 400

    # Registro válido
    r_ok = client.post(
        "/api/auth/register",
        json={
            "nombre": "Valeria",
            "apellido": "Castro",
            "email": email_unico,
            "contrasena": "ValeriaPass1",
            "telefono": "3001112233",
        },
    )
    assert r_ok.status_code == 201
    token = r_ok.get_json()["data"]["token"]

    # 2. Rechazo en /api/perfil/password
    for pwd in debil_cases:
        r_chg_bad = client.put(
            "/api/perfil/password",
            headers={"Authorization": f"Bearer {token}"},
            json={"contrasena_actual": "ValeriaPass1", "nueva_password": pwd},
        )
        assert r_chg_bad.status_code == 400

    r_chg_ok = client.put(
        "/api/perfil/password",
        headers={"Authorization": f"Bearer {token}"},
        json={"contrasena_actual": "ValeriaPass1", "nueva_password": "ValeriaPass2"},
    )
    assert r_chg_ok.status_code == 200

    # 3. Rechazo en /api/auth/reset-password
    rec_token = auth_service.solicitar_recuperacion(email_unico)
    for pwd in debil_cases:
        r_rst_bad = client.post(
            "/api/auth/reset-password",
            json={"token": rec_token, "nueva_password": pwd},
        )
        assert r_rst_bad.status_code == 400

    r_rst_ok = client.post(
        "/api/auth/reset-password",
        json={"token": rec_token, "nueva_password": "ValeriaPass3"},
    )
    assert r_rst_ok.status_code == 200


def test_rf_seg_012_015_personal_rbac_autobloqueo_y_reactivacion():
    """
    RF-SEG-012..015 (OWASP A01):
    - Endpoints /api/admin/personal exigen rol Administradora (403 para Vendedora y Clienta).
    - Validación RN-SEG-008 al crear personal operativo.
    - Bloqueo contra auto-baja lógica y contra degradar/desactivar la última Administradora activa.
    - Cambio de rol, baja lógica con revocación de sesión y reactivación funcional.
    """
    import uuid
    from run import app, auth_service

    client = app.test_client()
    suffix = uuid.uuid4().hex[:8]
    tok_admin = auth_service.validar_credenciales("admin@onestylemariana.co", "AdminOneStyle2026")
    admin_hdr = {"Authorization": f"Bearer {tok_admin}"}

    # 1. Crear clienta y comprobar rechazo 403 en todos los endpoints de personal
    r_cli = client.post(
        "/api/auth/register",
        json={
            "nombre": "Lucia",
            "apellido": "Clienta",
            "email": f"lucia.cli.{suffix}@test.co",
            "contrasena": "ClientaPass1",
        },
    )
    assert r_cli.status_code == 201
    cli_hdr = {"Authorization": f"Bearer {r_cli.get_json()['data']['token']}"}

    # 2. Administradora rechaza clave débil al crear personal (400) y luego crea Vendedora (201)
    vend_email = f"carolina.vend.{suffix}@test.co"
    r_weak = client.post(
        "/api/admin/personal",
        headers=admin_hdr,
        json={
            "nombre": "Carolina",
            "apellido": "Vendedora",
            "email": vend_email,
            "contrasena": "debil",
            "rol": "Vendedora",
        },
    )
    assert r_weak.status_code == 400

    r_vend = client.post(
        "/api/admin/personal",
        headers=admin_hdr,
        json={
            "nombre": "Carolina",
            "apellido": "Vendedora",
            "email": vend_email,
            "contrasena": "VentasPass1",
            "rol": "Vendedora",
            "telefono": "3008887766",
        },
    )
    assert r_vend.status_code == 201
    vend_id = r_vend.get_json()["data"]["id_usuario"]

    tok_vend = auth_service.validar_credenciales(vend_email, "VentasPass1")
    vend_hdr = {"Authorization": f"Bearer {tok_vend}"}

    for forbidden_hdr in (cli_hdr, vend_hdr):
        assert client.get("/api/admin/personal", headers=forbidden_hdr).status_code == 403
        assert client.post(
            "/api/admin/personal",
            headers=forbidden_hdr,
            json={
                "nombre": "Intruso",
                "apellido": "Staff",
                "email": f"intruso.{suffix}@test.co",
                "contrasena": "ValidPass1",
                "rol": "Vendedora",
            },
        ).status_code == 403
        assert client.put(
            f"/api/admin/personal/{vend_id}",
            headers=forbidden_hdr,
            json={"rol": "Administradora"},
        ).status_code == 403
        assert client.patch(
            f"/api/admin/personal/{vend_id}/estado",
            headers=forbidden_hdr,
            json={"estado_usuario": False},
        ).status_code == 403

    # 3. Protección contra auto-baja lógica y degradación de última Administradora activa
    r_me = client.get("/api/perfil", headers=admin_hdr)
    assert r_me.status_code == 200
    admin_id = r_me.get_json()["data"]["id_usuario"]

    r_self_off = client.patch(
        f"/api/admin/personal/{admin_id}/estado",
        headers=admin_hdr,
        json={"estado_usuario": False},
    )
    assert r_self_off.status_code == 400

    lista_antes = client.get("/api/admin/personal", headers=admin_hdr).get_json()["data"]
    admins_activas = [u for u in lista_antes if u["rol"] == "Administradora" and u.get("estado_usuario", True)]
    if len(admins_activas) == 1:
        r_last_demote = client.put(
            f"/api/admin/personal/{admin_id}",
            headers=admin_hdr,
            json={"rol": "Vendedora"},
        )
        assert r_last_demote.status_code == 400

    # 4. Cambio de rol Vendedora -> Administradora -> Vendedora
    r_promote = client.put(
        f"/api/admin/personal/{vend_id}",
        headers=admin_hdr,
        json={"rol": "Administradora"},
    )
    assert r_promote.status_code == 200
    assert r_promote.get_json()["data"]["rol"] == "Administradora"

    r_demote = client.put(
        f"/api/admin/personal/{vend_id}",
        headers=admin_hdr,
        json={"rol": "Vendedora"},
    )
    assert r_demote.status_code == 200
    assert r_demote.get_json()["data"]["rol"] == "Vendedora"

    # 5. Baja lógica revoca sesiones y conserva registro inactivo; luego reactivación restaura login
    r_off = client.patch(
        f"/api/admin/personal/{vend_id}/estado",
        headers=admin_hdr,
        json={"estado_usuario": False},
    )
    assert r_off.status_code == 200
    assert r_off.get_json()["data"]["estado_usuario"] is False
    assert client.get("/api/perfil", headers=vend_hdr).status_code == 401
    assert client.post("/api/auth/login", json={"email": vend_email, "contrasena": "VentasPass1"}).status_code in (401, 403)

    lista_despues = client.get("/api/admin/personal", headers=admin_hdr).get_json()["data"]
    assert any(u["id_usuario"] == vend_id and u["estado_usuario"] is False for u in lista_despues)

    r_on = client.patch(
        f"/api/admin/personal/{vend_id}/estado",
        headers=admin_hdr,
        json={"estado_usuario": True},
    )
    assert r_on.status_code == 200
    assert r_on.get_json()["data"]["estado_usuario"] is True
    assert client.post("/api/auth/login", json={"email": vend_email, "contrasena": "VentasPass1"}).status_code == 200


def test_auditoria_filtro_fechas_csv_injection_y_rbac():
    """
    RF-SEG-005 (OWASP A01 / CSV Injection):
    - GET /api/admin/auditoria y /api/admin/auditoria/csv exigen Administradora (403 a Vendedora/Clienta).
    - Validación fecha_inicio <= fecha_fin (400 si rango invertido) y filtrado por rango válido.
    - Neutralización contra Formula Injection (=, +, -, @) al exportar CSV.
    """
    import uuid
    from datetime import datetime, timedelta
    from run import app, auth_service, auditoria_service

    client = app.test_client()
    suffix = uuid.uuid4().hex[:8]
    tok_adm = auth_service.validar_credenciales("admin@onestylemariana.co", "AdminOneStyle2026")
    tok_ven = auth_service.validar_credenciales("vendedora@onestylemariana.co", "VentasOneStyle2026")
    adm_hdr = {"Authorization": f"Bearer {tok_adm}"}
    ven_hdr = {"Authorization": f"Bearer {tok_ven}"}

    r_cli = client.post(
        "/api/auth/register",
        json={"nombre": "Clara", "apellido": "Audit", "email": f"clara.audit.{suffix}@test.co", "contrasena": "AuditPass1"},
    )
    assert r_cli.status_code == 201
    cli_hdr = {"Authorization": f"Bearer {r_cli.get_json()['data']['token']}"}

    # 1. RBAC: Vendedora y Clienta reciben 403
    for bad_hdr in (ven_hdr, cli_hdr):
        assert client.get("/api/admin/auditoria", headers=bad_hdr).status_code == 403
        assert client.get("/api/admin/auditoria/csv", headers=bad_hdr).status_code == 403

    # 2. Rango inválido retorna 400
    assert client.get("/api/admin/auditoria?fecha_inicio=2026-12-31&fecha_fin=2026-01-01", headers=adm_hdr).status_code == 400
    assert client.get("/api/admin/auditoria/csv?fecha_inicio=2026-12-31&fecha_fin=2026-01-01", headers=adm_hdr).status_code == 400

    # 3. Registrar traza con payload de Formula Injection (=CMD|...)
    marker_csv = f"CSVMARKER_{suffix}"
    auditoria_service.registrar_traza_auditoria(
        usuario_id=1,
        tipo_accion="PRUEBA_CSV_SEGURIDAD",
        tabla_afectada="auditoria_test",
        registro_id=9001,
        valor_anterior="+SUM(1,1)",
        valor_nuevo=f"=CMD|'/C calc'!A0 {marker_csv}",
    )

    hoy = datetime.now()
    ayer_str = (hoy - timedelta(days=1)).strftime("%Y-%m-%d")
    hoy_str = hoy.strftime("%Y-%m-%d")
    pasado_ini = (hoy - timedelta(days=30)).strftime("%Y-%m-%d")
    pasado_fin = (hoy - timedelta(days=20)).strftime("%Y-%m-%d")

    r_ok = client.get(
        f"/api/admin/auditoria?fecha_inicio={ayer_str}&fecha_fin={hoy_str}&q={marker_csv}",
        headers=adm_hdr,
    )
    assert r_ok.status_code == 200
    items = r_ok.get_json()["data"]
    assert len(items) == 1
    assert items[0]["tipo_accion"] == "PRUEBA_CSV_SEGURIDAD"

    # Rango antiguo excluye la traza actual
    r_past = client.get(
        f"/api/admin/auditoria?fecha_inicio={pasado_ini}&fecha_fin={pasado_fin}&q={marker_csv}",
        headers=adm_hdr,
    )
    assert r_past.status_code == 200
    assert len(r_past.get_json()["data"]) == 0

    # Exportar CSV filtrado y verificar neutralización OWASP
    r_csv = client.get(
        f"/api/admin/auditoria/csv?fecha_inicio={ayer_str}&fecha_fin={hoy_str}&q={marker_csv}",
        headers=adm_hdr,
    )
    assert r_csv.status_code == 200
    assert "text/csv" in r_csv.headers.get("Content-Type", "")
    csv_txt = r_csv.get_data(as_text=True)
    assert "'+SUM(1,1)" in csv_txt
    assert f"'=CMD|'/C calc'!A0 {marker_csv}" in csv_txt


def test_rf_seg_007_010_011_registro_perfil_documento_direccion_y_validaciones():
    """RF-SEG-007/010/011: Registro y perfil con tipo_documento, documento y dirección validados y persistidos."""
    import uuid
    from run import app

    client = app.test_client()
    suffix = uuid.uuid4().hex[:8]
    email = f"docperfil.{suffix}@test.co"

    # 1. Rechazos de validación en registro
    r_bad_type = client.post("/api/auth/register", json={
        "nombre": "Paula",
        "apellido": "Rojas",
        "email": f"badtype.{suffix}@test.co",
        "contrasena": "Password123",
        "tipo_documento": "DNI",
        "documento": "12345678",
    })
    assert r_bad_type.status_code == 400

    r_bad_doc = client.post("/api/auth/register", json={
        "nombre": "Paula",
        "apellido": "Rojas",
        "email": f"baddoc.{suffix}@test.co",
        "contrasena": "Password123",
        "tipo_documento": "CC",
        "documento": "12$%",
    })
    assert r_bad_doc.status_code == 400

    r_half_doc = client.post("/api/auth/register", json={
        "nombre": "Paula",
        "apellido": "Rojas",
        "email": f"halfdoc.{suffix}@test.co",
        "contrasena": "Password123",
        "tipo_documento": "CC",
    })
    assert r_half_doc.status_code == 400

    # 2. Registro exitoso con documento y dirección predeterminada
    r_ok = client.post("/api/auth/register", json={
        "nombre": "Paula",
        "apellido": "Rojas",
        "email": email,
        "contrasena": "Password123",
        "telefono": "3112223344",
        "tipo_documento": "CC",
        "documento": "1012345678",
        "direccion": "Calle 93 # 12-54, Apto 402",
    })
    assert r_ok.status_code == 201
    data_reg = r_ok.get_json()["data"]
    token = data_reg["token"]
    u_reg = data_reg["usuario"]
    assert u_reg["tipo_documento"] == "CC"
    assert u_reg["documento"] == "1012345678"
    assert u_reg["direccion"] == "Calle 93 # 12-54, Apto 402"

    # 3. GET /api/perfil devuelve los campos nuevos
    hdr = {"Authorization": f"Bearer {token}"}
    r_get = client.get("/api/perfil", headers=hdr)
    assert r_get.status_code == 200
    u_get = r_get.get_json()["data"]
    assert u_get["tipo_documento"] == "CC"
    assert u_get["documento"] == "1012345678"
    assert u_get["direccion"] == "Calle 93 # 12-54, Apto 402"

    # 4. PUT /api/perfil parcial (omitiendo documento/dirección) conserva los existentes
    r_partial = client.put("/api/perfil", headers=hdr, json={
        "nombre": "Paula Andrea",
        "apellido": "Rojas",
    })
    assert r_partial.status_code == 200
    u_part = r_partial.get_json()["data"]
    assert u_part["nombre"] == "Paula Andrea"
    assert u_part["tipo_documento"] == "CC"
    assert u_part["documento"] == "1012345678"
    assert u_part["direccion"] == "Calle 93 # 12-54, Apto 402"

    # 5. PUT /api/perfil actualizando a Pasaporte y nueva dirección
    r_upd = client.put("/api/perfil", headers=hdr, json={
        "nombre": "Paula Andrea",
        "apellido": "Rojas",
        "tipo_documento": "PASAPORTE",
        "documento": "AB987654",
        "direccion": "Carrera 15 # 100-20, Bogota",
    })
    assert r_upd.status_code == 200
    u_upd = r_upd.get_json()["data"]
    assert u_upd["tipo_documento"] == "Pasaporte"
    assert u_upd["documento"] == "AB987654"
    assert u_upd["direccion"] == "Carrera 15 # 100-20, Bogota"

    # 6. Rechazar dirección mayor a 255 caracteres
    r_long_dir = client.put("/api/perfil", headers=hdr, json={
        "nombre": "Paula Andrea",
        "apellido": "Rojas",
        "direccion": "A" * 260,
    })
    assert r_long_dir.status_code == 400


def test_rf_seg_006_auditoria_ip_y_user_agent_login_logout_anti_log_injection():
    """RF-SEG-006: Registra IP (remote_addr) y User-Agent sanitizado en LOGIN_SUCCESS, LOGIN_FAILED y LOGOUT."""
    import os
    import uuid
    from unittest.mock import patch
    from run import app

    client = app.test_client()
    suffix = uuid.uuid4().hex[:8]
    email = f"auditip.{suffix}@test.co"

    r_reg = client.post("/api/auth/register", json={
        "nombre": "Valentina",
        "apellido": "Castro",
        "email": email,
        "contrasena": "Password123",
    })
    assert r_reg.status_code == 201
    uid_cliente = r_reg.get_json()["data"]["id_usuario"]

    # 1. Login fallido con intento de Log Injection (\r\n vía WSGI environ + exceso >255 chars) y header X-Forwarded-For falso
    evil_ua = "BadAgent/1.0\r\nFAKE_ADMIN_EVENT\t\n" + ("Z" * 300)
    r_fail = client.post(
        "/api/auth/login",
        json={"email": email, "contrasena": "WrongPassword9"},
        environ_base={"REMOTE_ADDR": "192.0.2.44", "HTTP_USER_AGENT": evil_ua},
        headers={"X-Forwarded-For": "198.51.100.99"},
    )
    assert r_fail.status_code == 401

    # 2. Login exitoso captura REMOTE_ADDR y User-Agent
    r_ok = client.post(
        "/api/auth/login",
        json={"email": email, "contrasena": "Password123"},
        environ_base={"REMOTE_ADDR": "192.0.2.45"},
        headers={"User-Agent": "OneStyleClient/3.1"},
    )
    assert r_ok.status_code == 200
    tok_cli = r_ok.get_json()["data"]["token"]

    # 3. Logout con TRUST_PROXY_HEADERS=true respeta X-Forwarded-For validado
    with patch.dict(os.environ, {"TRUST_PROXY_HEADERS": "true"}, clear=False):
        r_out = client.post(
            "/api/auth/logout",
            headers={
                "Authorization": f"Bearer {tok_cli}",
                "X-Forwarded-For": "203.0.113.77",
                "User-Agent": "OneStyleLogout/3.1",
            },
            environ_base={"REMOTE_ADDR": "10.0.0.1"},
        )
    assert r_out.status_code == 200

    # 4. Consultar auditoría y CSV como Administradora
    r_adm = client.post("/api/auth/login", json={
        "email": "admin@onestylemariana.co",
        "contrasena": "AdminOneStyle2026",
    })
    assert r_adm.status_code == 200
    adm_hdr = {"Authorization": f"Bearer {r_adm.get_json()['data']['token']}"}

    r_aud = client.get(f"/api/admin/auditoria?usuario_id={uid_cliente}", headers=adm_hdr)
    assert r_aud.status_code == 200
    logs = r_aud.get_json()["data"]

    failed_logs = [l for l in logs if l["tipo_accion"] == "LOGIN_FAILED"]
    success_logs = [l for l in logs if l["tipo_accion"] == "LOGIN_SUCCESS" and l["ip_address"] == "192.0.2.45"]
    logout_logs = [l for l in logs if l["tipo_accion"] == "LOGOUT"]

    assert failed_logs and failed_logs[0]["ip_address"] == "192.0.2.44"
    ua_failed = failed_logs[0]["user_agent"]
    assert "\r" not in ua_failed and "\n" not in ua_failed
    assert len(ua_failed) <= 255

    assert success_logs and success_logs[0]["user_agent"] == "OneStyleClient/3.1"
    assert logout_logs and logout_logs[0]["ip_address"] == "203.0.113.77"
    assert logout_logs[0]["user_agent"] == "OneStyleLogout/3.1"

    r_csv = client.get("/api/admin/auditoria/csv?q=203.0.113.77", headers=adm_hdr)
    assert r_csv.status_code == 200
    csv_txt = r_csv.get_data(as_text=True)
    assert "Dispositivo (User-Agent)" in csv_txt
    assert "203.0.113.77" in csv_txt
    assert "OneStyleLogout/3.1" in csv_txt


def test_rf_seg_008_google_oauth_sin_stub_y_verificacion_criptografica():
    """RF-SEG-008: Elimina el stub inseguro google123456, exige GOOGLE_CLIENT_ID y verifica ID Token."""
    import os
    import sys
    import types
    import uuid
    from unittest.mock import patch
    from run import app, auth_service

    client = app.test_client()
    suffix = uuid.uuid4().hex[:8]

    # 1. Sin GOOGLE_CLIENT_ID: config lo desactiva y /api/auth/google retorna 501 (stub muerto)
    with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": ""}, clear=False):
        r_cfg = client.get("/api/auth/config")
        assert r_cfg.status_code == 200
        assert r_cfg.get_json()["data"]["google_oauth_enabled"] is False

        r_stub = client.post("/api/auth/google", json={"id_token": "google123456"})
        assert r_stub.status_code == 501

        try:
            auth_service.google_oauth_verify("cualquier_token", client_id="")
            assert False, "Debió fallar cerrado cuando GOOGLE_CLIENT_ID está vacío"
        except NotImplementedError:
            pass

    # 2. Con GOOGLE_CLIENT_ID configurado y verificación criptográfica mockeada en google.oauth2.id_token
    fake_client_id = "1234567890-onestyle.apps.googleusercontent.com"

    def _build_google_modules(verify_fn):
        g_pkg = types.ModuleType("google")
        g_oauth2 = types.ModuleType("google.oauth2")
        g_id_token = types.ModuleType("google.oauth2.id_token")
        g_id_token.verify_oauth2_token = verify_fn
        g_auth = types.ModuleType("google.auth")
        g_transport = types.ModuleType("google.auth.transport")
        g_requests = types.ModuleType("google.auth.transport.requests")
        g_requests.Request = lambda: object()
        return {
            "google": g_pkg,
            "google.oauth2": g_oauth2,
            "google.oauth2.id_token": g_id_token,
            "google.auth": g_auth,
            "google.auth.transport": g_transport,
            "google.auth.transport.requests": g_requests,
        }

    # 2a. Token con firma inválida / excepción de verificación -> 401
    def _verify_bad(token_str, req_obj, aud):
        raise ValueError("Invalid token signature")

    with patch.dict(os.environ, {"GOOGLE_CLIENT_ID": fake_client_id}, clear=False):
        r_cfg_on = client.get("/api/auth/config")
        assert r_cfg_on.status_code == 200
        assert r_cfg_on.get_json()["data"]["google_oauth_enabled"] is True

        with patch.dict(sys.modules, _build_google_modules(_verify_bad)):
            r_bad = client.post(
                "/api/auth/google",
                json={"id_token": "fake.jwt.invalid"},
                environ_base={"REMOTE_ADDR": "198.51.100.10"},
                headers={"User-Agent": "OAuthTest/1.0"},
            )
            assert r_bad.status_code == 401

        # 2b. Token con correo sin verificar o emisor inválido -> 401
        def _verify_unverified(token_str, req_obj, aud):
            return {
                "iss": "https://accounts.google.com",
                "aud": aud,
                "sub": f"sub-unv-{suffix}",
                "email": f"unv.{suffix}@gmail.com",
                "email_verified": False,
            }

        with patch.dict(sys.modules, _build_google_modules(_verify_unverified)):
            r_unv = client.post("/api/auth/google", json={"id_token": "fake.jwt.unverified"})
            assert r_unv.status_code == 401

        # 2c. Token válido verificable -> 200 + creación/vinculación de Clienta + sesión real + auditoría
        g_email = f"mariana.oauth.{suffix}@gmail.com"
        g_sub = f"google-sub-{suffix}"

        def _verify_ok(token_str, req_obj, aud):
            return {
                "iss": "https://accounts.google.com",
                "aud": aud,
                "sub": g_sub,
                "email": g_email,
                "email_verified": True,
                "given_name": "Lucia",
                "family_name": "Gomez",
            }

        with patch.dict(sys.modules, _build_google_modules(_verify_ok)):
            r_ok = client.post(
                "/api/auth/google",
                json={"id_token": "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ0ZXN0In0.sig"},
                environ_base={"REMOTE_ADDR": "198.51.100.25"},
                headers={"User-Agent": "ChromeTest/130.0"},
            )
            assert r_ok.status_code == 200
            body = r_ok.get_json()["data"]
            assert body["token"]
            assert body["refresh_token"]
            assert body["usuario"]["email"] == g_email
            assert body["usuario"]["rol"] == "Clienta"

            # Sesión real utilizable en /api/perfil
            r_prof = client.get("/api/perfil", headers={"Authorization": f"Bearer {body['token']}"})
            assert r_prof.status_code == 200
            assert r_prof.get_json()["data"]["email"] == g_email

    # Confirmar que la traza LOGIN_SUCCESS de Google quedó con IP y User-Agent
    g_uid = body["usuario"]["id_usuario"]
    logs_g = [l for l in auth_service.auditoria_service.logs if l["usuario_id"] == g_uid and l["tipo_accion"] == "LOGIN_SUCCESS"]
    assert logs_g and logs_g[-1]["ip_address"] == "198.51.100.25"
    assert logs_g[-1]["user_agent"] == "ChromeTest/130.0"


def test_migracion_idempotente_preserva_datos_sqlite():
    """Verifica que migrate_sqlite agregue columnas faltantes dos veces seguidas sin perder filas existentes."""
    import os
    import sqlite3
    import tempfile
    from database.migrate_group4_security import migrate_sqlite

    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = os.path.join(tmpdir, "legacy_test.db")
        conn = sqlite3.connect(db_file)
        conn.executescript("""
            CREATE TABLE usuarios (
                id_usuario INTEGER PRIMARY KEY,
                fk_id_rol INTEGER NOT NULL,
                nombre TEXT NOT NULL,
                apellido TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                contrasena TEXT NOT NULL,
                telefono TEXT,
                estado_usuario INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE auditoria (
                id_log INTEGER PRIMARY KEY AUTOINCREMENT,
                fk_id_usuario_accion INTEGER NOT NULL,
                tipo_accion TEXT NOT NULL,
                tabla_afectada TEXT NOT NULL,
                id_registro_afectado INTEGER,
                valor_anterior TEXT,
                valor_nuevo TEXT,
                fecha_accion TEXT DEFAULT CURRENT_TIMESTAMP
            );
            INSERT INTO usuarios VALUES (1, 3, 'Elena', 'Existente', 'elena@legacy.co', 'hash', '3000000000', 1);
            INSERT INTO auditoria (fk_id_usuario_accion, tipo_accion, tabla_afectada, id_registro_afectado) VALUES (1, 'LEGACY', 'usuarios', 1);
        """)
        conn.commit()
        conn.close()

        res1 = migrate_sqlite(db_file)
        assert "usuarios.tipo_documento" in res1["added"]
        assert "usuarios.documento" in res1["added"]
        assert "usuarios.direccion" in res1["added"]
        assert "auditoria.ip_address" in res1["added"]
        assert "auditoria.user_agent" in res1["added"]

        res2 = migrate_sqlite(db_file)
        assert res2["added"] == []
        assert "usuarios.tipo_documento" in res2["existing"]
        assert "auditoria.user_agent" in res2["existing"]

        conn = sqlite3.connect(db_file)
        row_u = conn.execute("SELECT email, tipo_documento, documento, direccion FROM usuarios WHERE id_usuario = 1").fetchone()
        row_a = conn.execute("SELECT tipo_accion, ip_address, user_agent FROM auditoria WHERE id_log = 1").fetchone()
        conn.close()

        assert row_u == ("elena@legacy.co", None, None, None)
        assert row_a == ("LEGACY", None, None)



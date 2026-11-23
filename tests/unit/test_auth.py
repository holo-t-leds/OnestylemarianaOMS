import pytest
from src.auth.service import AuthService

@pytest.fixture
def auth():
    return AuthService()

def test_registrar_cliente_exito(auth):
    user_id = auth.registrar_cliente("Ana", "Gomez", "ana@example.com", "securepwd123")
    assert user_id == 1
    assert auth.usuarios[user_id]['email'] == "ana@example.com"
    assert auth.usuarios[user_id]['rol'] == "Clienta"

def test_registrar_cliente_contrasena_corta(auth):
    with pytest.raises(ValueError, match="al menos 8 caracteres"):
        auth.registrar_cliente("Ana", "Gomez", "ana@example.com", "short")

def test_registrar_cliente_email_duplicado(auth):
    auth.registrar_cliente("Ana", "Gomez", "ana@example.com", "securepwd123")

    with pytest.raises(ValueError, match="ya está registrado"):
        auth.registrar_cliente("Otra", "Ana", "ana@example.com", "anotherpwd")

def test_validar_credenciales_exito(auth):
    auth.registrar_cliente("Ana", "Gomez", "ana@example.com", "securepwd123")
    token = auth.validar_credenciales("ana@example.com", "securepwd123")

    assert token is not None
    assert auth.verificar_sesion(token) is True

def test_validar_credenciales_fallo(auth):
    auth.registrar_cliente("Ana", "Gomez", "ana@example.com", "securepwd123")

    with pytest.raises(ValueError, match="Credenciales inválidas"):
        auth.validar_credenciales("ana@example.com", "wrongpwd")

    with pytest.raises(ValueError, match="Credenciales inválidas"):
         auth.validar_credenciales("nonexistent@example.com", "securepwd123")

def test_get_user_role(auth):
    auth.registrar_cliente("Ana", "Gomez", "ana@example.com", "securepwd123")
    token = auth.validar_credenciales("ana@example.com", "securepwd123")

    role = auth.get_user_role(token)
    assert role == "Clienta"

def test_get_user_role_token_invalido(auth):
    with pytest.raises(ValueError, match="Sesión inválida o expirada"):
        auth.get_user_role("invalid-token")

from datetime import datetime, timedelta
from src.auditoria.service import AuditoriaService

def test_recuperacion_token_ttl(auth):
    user_id = auth.registrar_cliente("Ana", "Gomez", "ana@example.com", "securepwd123")
    token = auth.solicitar_recuperacion("ana@example.com")

    assert token is not None
    assert auth.usuarios[user_id]['reset_token_hash'] is not None
    assert auth.usuarios[user_id]['reset_token_expira'] is not None

    # Check TTL is around 15 minutes
    expira = auth.usuarios[user_id]['reset_token_expira']
    expected_expira = datetime.now() + timedelta(minutes=15)

    # Compare timestamps allowing a tiny margin of error (seconds)
    delta = abs((expira - expected_expira).total_seconds())
    assert delta < 5

def test_rechazo_token_vencido(auth):
    user_id = auth.registrar_cliente("Ana", "Gomez", "ana@example.com", "securepwd123")
    token = auth.solicitar_recuperacion("ana@example.com")

    # Simulate expiration by rolling back the expiration time to the past
    auth.usuarios[user_id]['reset_token_expira'] = datetime.now() - timedelta(minutes=1)

    with pytest.raises(ValueError, match="El token de recuperación ha expirado"):
        auth.restablecer_password(token, "new_secure_pwd")

def test_invalidacion_inmediata_token(auth):
    user_id = auth.registrar_cliente("Ana", "Gomez", "ana@example.com", "securepwd123")
    token = auth.solicitar_recuperacion("ana@example.com")

    # Reset password successfully
    result = auth.restablecer_password(token, "new_secure_pwd")
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


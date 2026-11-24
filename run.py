import csv
import io
import os
import re
import secrets
import uuid
from datetime import datetime
from flask import Flask, Response, g, jsonify, render_template, request, redirect, url_for, send_from_directory
from PIL import Image, UnidentifiedImageError
import pymysql
from werkzeug.utils import secure_filename
from app.database import get_db_connection
from app.mailer import send_password_recovery_email
from app.security import api_response, validate_whitelist_payload, extract_bearer_token
from src.auditoria.service import AuditoriaService
from src.auth.service import AuthService
from src.catalogo.service import CatalogoService, ConflictError, NotFoundError
from src.carrito.service import CarritoService
from src.pedidos.service import PedidosService
from src.faq.service import FAQService, RateLimitError

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "onestyle-mariana-secret-key-2026")

UPLOAD_PRODUCTS_DIR = os.path.abspath(os.path.join(app.static_folder, "img", "uploads"))
ALLOWED_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB por archivo


class ImageTooLargeError(ValueError):
    """Excepción para archivos de imagen que exceden el límite permitido (HTTP 413)."""
    pass


def _validate_image_file(file_storage):
    """
    Valida carga segura de imágenes (OWASP Unrestricted File Upload):
    - Lista blanca de extensiones (.jpg, .jpeg, .png, .webp)
    - Tamaño máximo 5 MB
    - Magic bytes reales + verificación estructural con Pillow y correspondencia de formato
    """
    raw_name = getattr(file_storage, "filename", "") or ""
    safe_name = secure_filename(raw_name)
    if not safe_name or "." not in safe_name:
        raise ValueError("El archivo de imagen es inválido o no tiene extensión.")

    ext = os.path.splitext(safe_name)[1].lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("Extensión no permitida. Solo se aceptan imágenes JPG, JPEG, PNG o WEBP.")

    raw_bytes = file_storage.read(MAX_IMAGE_BYTES + 1)
    if not raw_bytes:
        raise ValueError("El archivo de imagen está vacío.")
    if len(raw_bytes) > MAX_IMAGE_BYTES:
        raise ImageTooLargeError("La imagen supera el límite máximo de 5 MB.")

    # Verificación estricta de magic bytes
    if ext in (".jpg", ".jpeg"):
        if not raw_bytes.startswith(b"\xff\xd8\xff"):
            raise ValueError("El contenido del archivo no corresponde a una imagen JPEG válida.")
        expected_fmt = "JPEG"
        canonical_ext = ".jpg"
        formato_upper = "JPG"
    elif ext == ".png":
        if not raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("El contenido del archivo no corresponde a una imagen PNG válida.")
        expected_fmt = "PNG"
        canonical_ext = ".png"
        formato_upper = "PNG"
    else:
        if len(raw_bytes) < 12 or raw_bytes[:4] != b"RIFF" or raw_bytes[8:12] != b"WEBP":
            raise ValueError("El contenido del archivo no corresponde a una imagen WEBP válida.")
        expected_fmt = "WEBP"
        canonical_ext = ".webp"
        formato_upper = "WEBP"

    try:
        with Image.open(io.BytesIO(raw_bytes)) as img:
            detected_fmt = (img.format or "").upper()
            img.verify()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise ValueError("El archivo no es una imagen válida o está corrupto.")

    if detected_fmt != expected_fmt:
        raise ValueError("El formato binario real de la imagen no coincide con su extensión.")

    return raw_bytes, canonical_ext, formato_upper


def _save_validated_image_bytes(raw_bytes: bytes, canonical_ext: str):
    """Guarda la imagen con nombre UUID seguro únicamente dentro de UPLOAD_PRODUCTS_DIR."""
    os.makedirs(UPLOAD_PRODUCTS_DIR, exist_ok=True)
    filename = f"{uuid.uuid4().hex}{canonical_ext}"
    target_path = os.path.abspath(os.path.join(UPLOAD_PRODUCTS_DIR, filename))
    if os.path.commonpath([UPLOAD_PRODUCTS_DIR, target_path]) != UPLOAD_PRODUCTS_DIR:
        raise ValueError("Ruta de almacenamiento fuera del directorio autorizado.")
    with open(target_path, "wb") as f:
        f.write(raw_bytes)
    return f"img/uploads/{filename}", target_path


def _delete_local_upload_if_safe(url_imagen: str | None):
    """Elimina físicamente una imagen subida localmente validando que no haya Path Traversal."""
    if not url_imagen or not str(url_imagen).startswith("img/uploads/"):
        return
    rel_name = os.path.basename(str(url_imagen))
    target_path = os.path.abspath(os.path.join(UPLOAD_PRODUCTS_DIR, rel_name))
    if os.path.commonpath([UPLOAD_PRODUCTS_DIR, target_path]) == UPLOAD_PRODUCTS_DIR and os.path.isfile(target_path):
        try:
            os.remove(target_path)
        except OSError:
            pass

# Instancias de servicios de Módulos 1 al 5 (Seguridad, Catálogo, Carrito, Pedidos OMS y Centro de Ayuda FAQ)
auditoria_service = AuditoriaService()
auth_service = AuthService(auditoria_service=auditoria_service, persist_db=True)
catalogo_service = CatalogoService(auditoria_service=auditoria_service, seed_defaults=True)
pedidos_service = PedidosService(catalogo_service=catalogo_service, auditoria_service=auditoria_service)
faq_service = FAQService(auditoria_service=auditoria_service, seed_defaults=True)
carritos_activos = {}

# Semilla en memoria para pruebas e inicio inmediato de los 3 roles oficiales (RF-SEG-008, RF-SEG-012)
auth_service.crear_usuario_sistema(
    "Mariana", "OneStyle", "admin@onestylemariana.co", "AdminOneStyle2026", rol="Administradora", telefono="3001112233"
)
auth_service.crear_usuario_sistema(
    "Valeria", "Asesora", "vendedora@onestylemariana.co", "VentasOneStyle2026", rol="Vendedora", telefono="3004445566"
)


# =========================================================================
# MIDDLEWARE DE CIBERSEGURIDAD OWASP: CABECERAS HTTP, NONCE CSP Y CORS
# =========================================================================

def _extract_client_metadata():
    """
    Extrae de forma segura la IP del cliente y el encabezado User-Agent (RF-SEG-006).
    Usa request.remote_addr como fuente primaria y solo consulta X-Forwarded-For si TRUST_PROXY_HEADERS=true.
    """
    ip_val = request.remote_addr or "desconocida"
    if os.getenv("TRUST_PROXY_HEADERS", "").strip().lower() == "true":
        xff = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
        if xff and re.match(r"^[0-9a-fA-F:.]{3,45}$", xff):
            ip_val = xff
    ip_clean = re.sub(r"[\x00-\x1f\x7f]+", "", str(ip_val)).strip()[:45] or "desconocida"

    ua_raw = request.headers.get("User-Agent") or ""
    ua_clean = re.sub(r"[\x00-\x1f\x7f]+", " ", str(ua_raw)).strip()[:255] or None
    return ip_clean, ua_clean


@app.before_request
def generate_csp_nonce():
    g.csp_nonce = secrets.token_urlsafe(16)


@app.context_processor
def inject_csp_nonce():
    return {"csp_nonce": getattr(g, "csp_nonce", "")}


@app.after_request
def apply_security_headers(response):
    allowed_origins = [
        o.strip() for o in os.getenv("CORS_ALLOWED_ORIGINS", "http://localhost:5000,http://127.0.0.1:5000").split(",")
    ]
    origin = request.headers.get("Origin")
    if origin and origin in allowed_origins:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Session-ID"
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"

    nonce = getattr(g, "csp_nonce", "")
    nonce_token = f" 'nonce-{nonce}'" if nonce else ""
    google_oauth_enabled = bool((os.getenv("GOOGLE_CLIENT_ID") or "").strip())
    gsi_script = " https://accounts.google.com/gsi/client" if google_oauth_enabled else ""
    gsi_style = " https://accounts.google.com/gsi/style" if google_oauth_enabled else ""
    gsi_connect = " https://accounts.google.com/gsi/" if google_oauth_enabled else ""
    gsi_frame = "frame-src 'self' https://accounts.google.com/gsi/; " if google_oauth_enabled else ""

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        f"script-src 'self'{nonce_token} https://cdn.jsdelivr.net{gsi_script}; "
        f"style-src 'self'{nonce_token} https://cdn.jsdelivr.net https://fonts.googleapis.com{gsi_style}; "
        "font-src 'self' https://cdn.jsdelivr.net https://fonts.gstatic.com data:; "
        "img-src 'self' data: https://res.cloudinary.com; "
        f"connect-src 'self' https://cdn.jsdelivr.net{gsi_connect}; "
        f"{gsi_frame}"
        "object-src 'none'; "
        "frame-ancestors 'self'; "
        "form-action 'self'; "
        "base-uri 'self';"
    )
    if request.path.startswith("/api/auth") or request.path.startswith("/api/perfil"):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    return response


@app.errorhandler(404)
def handle_404(err):
    if request.path.startswith("/api/"):
        return api_response("error", "Recurso o endpoint no encontrado.", None, 404)
    return render_template("index.html"), 404


@app.errorhandler(405)
def handle_405(err):
    return api_response("error", "Método HTTP no permitido para este endpoint.", None, 405)


@app.errorhandler(500)
def handle_500(err):
    # OWASP: Nunca exponer stack traces internos al cliente
    return api_response("error", "Error interno del servidor. Intente nuevamente más tarde.", None, 500)


# =========================================================================
# VISTAS FRONTEND (SPA PRINCIPAL Y TIENDA SSR)
# =========================================================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/img/<path:filename>")
def serve_legacy_img(filename):
    return send_from_directory(os.path.join(app.static_folder, "img"), filename)


@app.route("/css/<path:filename>")
def serve_legacy_css(filename):
    return send_from_directory(os.path.join(app.static_folder, "css"), filename)


@app.route("/js/<path:filename>")
def serve_legacy_js(filename):
    return send_from_directory(os.path.join(app.static_folder, "js"), filename)


# RUTA ORIGINAL 1: La página web visual para la tienda
@app.route("/tienda")
def ver_tienda():
    conn = get_db_connection()
    mensaje = request.args.get("msg", None)
    try:
        with conn.cursor() as cursor:
            sql = """
                SELECT p.id_producto, p.nombre_producto, p.precio_detallista, c.nombre_categoria
                FROM producto p
                INNER JOIN categorias c ON p.fk_id_categoria = c.id_categoria
                WHERE p.estado_visibilidad = TRUE;
            """
            cursor.execute(sql)
            productos = cursor.fetchall()
        return render_template("tienda.html", productos=productos, mensaje=mensaje)
    finally:
        conn.close()


# RUTA ORIGINAL 2: Acción de comprar (aquí se pone a prueba el Trigger)
@app.route("/comprar", methods=["POST"])
def procesar_compra():
    id_variante = int(request.form.get("id_variante", 1))
    cantidad = int(request.form.get("cantidad", 1))

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute("INSERT INTO pedido (fk_id_usuario, total_pedido) VALUES (1, %s);", (cantidad * 120000.00,))
            id_pedido = cursor.lastrowid

            cursor.execute("""
                INSERT INTO detalle_pedido (fk_id_pedido, fk_id_variante, cantidad, precio)
                VALUES (%s, %s, %s, %s);
            """, (id_pedido, id_variante, cantidad, 120000.00))

        conn.commit()
        return redirect(url_for('ver_tienda', msg=f"¡Compra confirmada! Pedido #{id_pedido} registrado con éxito."))

    except pymysql.MySQLError as e:
        conn.rollback()
        return redirect(url_for('ver_tienda', msg=f"Error al procesar: {e.args[1]}"))
    finally:
        conn.close()


# =========================================================================
# ENDPOINTS REST — MÓDULO 1: SEGURIDAD, USUARIOS Y AUDITORÍA (RF-SEG-001..017)
# =========================================================================

@app.route("/api/auth/config", methods=["GET"])
def api_auth_config():
    """Expone configuración pública de métodos de acceso (Google OAuth habilitado solo si existe GOOGLE_CLIENT_ID)."""
    google_client_id = (os.getenv("GOOGLE_CLIENT_ID") or "").strip()
    return api_response(
        "success",
        "Configuración de autenticación.",
        {
            "google_oauth_enabled": bool(google_client_id),
            "google_client_id": google_client_id or None,
        },
        200,
    )


@app.route("/api/auth/register", methods=["POST"])
def api_register_cliente():
    """
    RF-SEG-007 / RN-SEG-007: Auto-registro público de Clientas (fk_id_rol = 3).
    """
    try:
        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(
            payload,
            allowed_fields={
                "nombre", "apellido", "email", "contrasena", "telefono",
                "tipo_documento", "documento", "direccion"
            },
            required_fields={"nombre", "apellido", "email", "contrasena"}
        )
        ip_address, user_agent = _extract_client_metadata()
        user_id = auth_service.registrar_cliente(
            nombre=clean["nombre"],
            apellido=clean["apellido"],
            email=clean["email"],
            contrasena=clean["contrasena"],
            telefono=clean.get("telefono"),
            tipo_documento=clean.get("tipo_documento"),
            documento=clean.get("documento"),
            direccion=clean.get("direccion")
        )
        token = auth_service.validar_credenciales(
            clean["email"],
            clean["contrasena"],
            ip_address=ip_address,
            user_agent=user_agent
        )
        perfil = auth_service.obtener_perfil(token)
        return api_response(
            "success",
            "Cuenta de clienta registrada exitosamente.",
            {
                "id_usuario": user_id,
                "rol": "Clienta",
                "token": token,
                "refresh_token": auth_service.obtener_refresh_token(token),
                "expires_in": auth_service.segundos_restantes_sesion(token),
                "usuario": perfil
            },
            201
        )
    except ValueError as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/auth/login", methods=["POST"])
def api_login():
    """
    RF-SEG-006 y RF-SEG-008 / RN-SEG-008: Inicio de sesión seguro con bloqueo tras 3 intentos fallidos.
    """
    try:
        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(
            payload,
            allowed_fields={"email", "contrasena"},
            required_fields={"email", "contrasena"}
        )
        ip_address, user_agent = _extract_client_metadata()
        token = auth_service.validar_credenciales(
            clean["email"],
            clean["contrasena"],
            ip_address=ip_address,
            user_agent=user_agent
        )
        perfil = auth_service.obtener_perfil(token)
        return api_response(
            "success",
            "Inicio de sesión exitoso.",
            {
                "token": token,
                "refresh_token": auth_service.obtener_refresh_token(token),
                "expires_in": auth_service.segundos_restantes_sesion(token),
                "usuario": perfil
            },
            200
        )
    except ValueError as e:
        msg = str(e)
        if "bloqueada" in msg.lower() or "inactiva" in msg.lower():
            return api_response("error", msg, None, 403)
        if "credenciales" in msg.lower():
            return api_response("error", msg, None, 401)
        return api_response("error", msg, None, 400)


@app.route("/api/auth/google", methods=["POST"])
def api_google_oauth():
    """
    RF-SEG-008: Autenticación federada con Google OAuth 2.0 (verificación criptográfica real de ID Token).
    """
    google_client_id = (os.getenv("GOOGLE_CLIENT_ID") or "").strip()
    if not google_client_id:
        return api_response(
            "error",
            "El inicio de sesión con Google OAuth 2.0 no está configurado en el servidor.",
            None,
            501,
        )
    try:
        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(
            payload,
            allowed_fields={"id_token"},
            required_fields={"id_token"}
        )
        ip_address, user_agent = _extract_client_metadata()
        sesion = auth_service.autenticar_con_google(
            clean["id_token"],
            client_id=google_client_id,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return api_response("success", "Inicio de sesión con Google exitoso.", sesion, 200)
    except NotImplementedError as e:
        return api_response("error", str(e), None, 501)
    except PermissionError as e:
        return api_response("error", str(e), None, 403)
    except ValueError as e:
        return api_response("error", str(e), None, 401)


@app.route("/api/auth/refresh", methods=["POST"])
def api_refresh_token():
    """
    Renovación transparente de sesión: intercambia un refresh token válido por un nuevo par
    access/refresh (rotación de un solo uso). Responde 401 si el refresh venció o es inválido.
    """
    try:
        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(
            payload,
            allowed_fields={"refresh_token"},
            required_fields={"refresh_token"}
        )
        nuevos = auth_service.renovar_sesion(clean["refresh_token"])
        return api_response("success", "Sesión renovada.", nuevos, 200)
    except ValueError as e:
        msg = str(e)
        if "inválida" in msg.lower() or "expirada" in msg.lower():
            return api_response("error", msg, None, 401)
        return api_response("error", msg, None, 400)


@app.route("/api/auth/logout", methods=["POST"])
def api_logout():
    """
    RF-SEG-009 / RN-SEG-009 y RF-SEG-006: Cierre de sesión seguro e invalidación inmediata de token con traza de IP/UA.
    """
    token = extract_bearer_token()
    if not token:
        return api_response("error", "Token de autorización requerido.", None, 401)
    try:
        ip_address, user_agent = _extract_client_metadata()
        auth_service.cerrar_sesion(token, ip_address=ip_address, user_agent=user_agent)
        return api_response("success", "Sesión cerrada correctamente.", None, 200)
    except ValueError as e:
        return api_response("error", str(e), None, 401)


@app.route("/api/auth/forgot-password", methods=["POST"])
def api_forgot_password():
    """
    RF-SEG-016 / RN-SEG-016: Solicitud de recuperación de contraseña con respuesta genérica anti-enumeración.
    Nunca expone el token en la respuesta HTTP.
    """
    try:
        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(
            payload,
            allowed_fields={"email"},
            required_fields={"email"}
        )
        token_generado = None
        try:
            token_generado = auth_service.solicitar_recuperacion(clean["email"])
        except ValueError:
            # RN-SEG-016: Si no existe, se responde de manera idéntica por seguridad anti-enumeración
            token_generado = None

        if token_generado:
            try:
                send_password_recovery_email(
                    clean["email"],
                    token_generado,
                    ttl_minutes=auth_service.RECOVERY_TTL_MINUTES,
                )
            except Exception as mail_err:
                app.logger.warning("Fallo al despachar correo de recuperación: %s", mail_err)

        return api_response(
            "success",
            "Si el correo ingresado se encuentra registrado, recibirás instrucciones temporales para restablecer tu contraseña.",
            None,
            200
        )
    except ValueError as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/auth/reset-password", methods=["POST"])
def api_reset_password():
    """
    RF-SEG-017 / RN-SEG-017: Restablecimiento de contraseña mediante token temporal.
    """
    try:
        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(
            payload,
            allowed_fields={"token", "nueva_password"},
            required_fields={"token", "nueva_password"}
        )
        auth_service.restablecer_password(clean["token"], clean["nueva_password"])
        return api_response("success", "Contraseña restablecida exitosamente.", None, 200)
    except ValueError as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/perfil", methods=["GET", "PUT"])
def api_perfil():
    """
    RF-SEG-010 y RF-SEG-011: Consulta y actualización del perfil del usuario autenticado.
    """
    token = extract_bearer_token()
    if not token:
        return api_response("error", "No autorizado. Inicie sesión.", None, 401)

    try:
        if request.method == "GET":
            perfil = auth_service.obtener_perfil(token)
            return api_response("success", "Perfil obtenido correctamente.", perfil, 200)

        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(
            payload,
            allowed_fields={"nombre", "apellido", "email", "telefono", "tipo_documento", "documento", "direccion"},
            required_fields={"nombre", "apellido"}
        )
        kwargs = {}
        for opt_key in ("email", "telefono", "tipo_documento", "documento", "direccion"):
            if opt_key in clean:
                kwargs[opt_key] = clean[opt_key]
        actualizado = auth_service.actualizar_perfil(
            token=token,
            nombre=clean["nombre"],
            apellido=clean["apellido"],
            **kwargs
        )
        return api_response("success", "Perfil actualizado exitosamente.", actualizado, 200)
    except ValueError as e:
        msg = str(e)
        if "sesión" in msg.lower():
            return api_response("error", msg, None, 401)
        return api_response("error", msg, None, 400)


@app.route("/api/perfil/password", methods=["PUT"])
def api_cambiar_password():
    """Cambio de contraseña del usuario autenticado (exige la contraseña actual)."""
    token = extract_bearer_token()
    if not token or not auth_service.verificar_sesion(token):
        return api_response("error", "No autorizado. Inicie sesión.", None, 401)
    try:
        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(
            payload,
            allowed_fields={"contrasena_actual", "nueva_password"},
            required_fields={"contrasena_actual", "nueva_password"}
        )
        auth_service.cambiar_password(token, clean["contrasena_actual"], clean["nueva_password"])
        return api_response("success", "Contraseña actualizada correctamente.", None, 200)
    except ValueError as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/admin/personal", methods=["GET", "POST"])
def api_admin_personal():
    """
    RF-SEG-012 y RF-SEG-013: Registro y listado de personal operativo (exclusivo Administradora).
    """
    token = extract_bearer_token()
    if not token or not auth_service.verificar_sesion(token):
        return api_response("error", "No autorizado. Token inválido o expirado.", None, 401)

    try:
        if request.method == "GET":
            personal = auth_service.listar_personal(token)
            return api_response("success", "Listado de personal operativo.", personal, 200)

        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(
            payload,
            allowed_fields={"nombre", "apellido", "email", "contrasena", "rol", "telefono"},
            required_fields={"nombre", "apellido", "email", "contrasena", "rol"}
        )
        new_id = auth_service.registrar_personal(
            token_admin=token,
            nombre=clean["nombre"],
            apellido=clean["apellido"],
            email=clean["email"],
            contrasena=clean["contrasena"],
            rol=clean["rol"],
            telefono=clean.get("telefono")
        )
        return api_response("success", "Personal operativo registrado.", {"id_usuario": new_id}, 201)
    except PermissionError as e:
        return api_response("error", str(e), None, 403)
    except ValueError as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/admin/personal/<int:target_id>", methods=["PUT"])
def api_admin_actualizar_personal(target_id: int):
    """
    RF-SEG-014: Actualización de datos y rol de personal operativo.
    """
    token = extract_bearer_token()
    if not token or not auth_service.verificar_sesion(token):
        return api_response("error", "No autorizado.", None, 401)

    try:
        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(
            payload,
            allowed_fields={"nombre", "apellido", "telefono", "rol"}
        )
        actualizado = auth_service.actualizar_personal(
            token_admin=token,
            target_user_id=target_id,
            nombre=clean.get("nombre"),
            apellido=clean.get("apellido"),
            telefono=clean.get("telefono"),
            rol=clean.get("rol")
        )
        return api_response("success", "Personal actualizado correctamente.", actualizado, 200)
    except PermissionError as e:
        return api_response("error", str(e), None, 403)
    except ValueError as e:
        msg = str(e)
        if "no existe" in msg.lower():
            return api_response("error", msg, None, 404)
        return api_response("error", msg, None, 400)


@app.route("/api/admin/personal/<int:target_id>/estado", methods=["PATCH"])
def api_admin_baja_logica_personal(target_id: int):
    """
    RF-SEG-015 / RN-SEG-015: Desactivación o reactivación mediante baja lógica y revocación de sesiones.
    """
    token = extract_bearer_token()
    if not token or not auth_service.verificar_sesion(token):
        return api_response("error", "No autorizado.", None, 401)

    try:
        activar = False
        raw_body = request.get_data(as_text=True) or ""
        if raw_body.strip():
            payload = request.get_json(silent=True)
            clean = validate_whitelist_payload(
                payload,
                allowed_fields={"estado_usuario"},
                required_fields={"estado_usuario"},
            )
            raw_state = clean["estado_usuario"]
            if isinstance(raw_state, bool):
                activar = raw_state
            elif isinstance(raw_state, str) and raw_state.strip().lower() in ("true", "1", "activo"):
                activar = True
            elif isinstance(raw_state, str) and raw_state.strip().lower() in ("false", "0", "inactivo"):
                activar = False
            else:
                raise ValueError("Valor inválido para 'estado_usuario'. Use booleano true o false.")

        actualizado = auth_service.cambiar_estado_personal(token, target_id, activar=activar)
        msg = "Usuario reactivado exitosamente." if actualizado["estado_usuario"] else "Usuario desactivado mediante baja lógica."
        return api_response(
            "success",
            msg,
            {"id_usuario": target_id, "estado_usuario": actualizado["estado_usuario"], "usuario": actualizado},
            200,
        )
    except PermissionError as e:
        return api_response("error", str(e), None, 403)
    except ValueError as e:
        msg = str(e)
        status_code = 404 if "no existe" in msg.lower() else 400
        return api_response("error", msg, None, status_code)


def _require_admin_token():
    """Valida token Bearer vigente y rol exclusivo Administradora (OWASP A01)."""
    token = extract_bearer_token()
    if not token or not auth_service.verificar_sesion(token):
        return None, api_response("error", "No autorizado. Inicie sesión.", None, 401)
    if auth_service.get_user_role(token) != "Administradora":
        return None, api_response("error", "Acceso exclusivo para el rol Administradora.", None, 403)
    return auth_service.get_user_id(token), None


def _parse_date_range(fecha_inicio_raw: str | None, fecha_fin_raw: str | None):
    """Parsea fechas YYYY-MM-DD opcionales y valida que fecha_inicio <= fecha_fin."""
    dt_ini = None
    dt_fin = None
    if fecha_inicio_raw and str(fecha_inicio_raw).strip():
        try:
            d_ini = datetime.strptime(str(fecha_inicio_raw).strip(), "%Y-%m-%d")
            dt_ini = d_ini.replace(hour=0, minute=0, second=0, microsecond=0)
        except ValueError:
            raise ValueError("El parámetro 'fecha_inicio' debe tener formato YYYY-MM-DD.")
    if fecha_fin_raw and str(fecha_fin_raw).strip():
        try:
            d_fin = datetime.strptime(str(fecha_fin_raw).strip(), "%Y-%m-%d")
            dt_fin = d_fin.replace(hour=23, minute=59, second=59, microsecond=999999)
        except ValueError:
            raise ValueError("El parámetro 'fecha_fin' debe tener formato YYYY-MM-DD.")
    if dt_ini is not None and dt_fin is not None and dt_ini > dt_fin:
        raise ValueError("La fecha de inicio no puede ser mayor que la fecha fin.")
    return dt_ini, dt_fin


def _csv_safe_cell(value) -> str:
    """Neutraliza CSV / Formula Injection (OWASP) anteponiendo comilla simple a prefijos peligrosos."""
    if value is None:
        return ""
    s = str(value)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s


def _build_csv_response(headers: list, rows: list, filename: str) -> Response:
    """Construye una respuesta CSV UTF-8 protegida contra CSV Injection."""
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL, lineterminator="\r\n")
    writer.writerow([_csv_safe_cell(h) for h in headers])
    for row in rows:
        writer.writerow([_csv_safe_cell(cell) for cell in row])
    return Response(
        buf.getvalue(),
        status=200,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _consultar_auditoria_filtrada(rol: str, args) -> list:
    tabla = args.get("tabla_afectada")
    accion = args.get("tipo_accion")
    usuario_id_param = args.get("usuario_id")
    uid = int(usuario_id_param) if usuario_id_param and usuario_id_param.isdigit() else None
    dt_ini, dt_fin = _parse_date_range(args.get("fecha_inicio"), args.get("fecha_fin"))
    q = (args.get("q") or "").strip().lower()

    logs = auditoria_service.consultar_logs(
        rol_solicitante=rol,
        usuario_id=uid,
        tabla_afectada=tabla,
        tipo_accion=accion,
        fecha_inicio=dt_ini,
        fecha_fin=dt_fin,
    )
    enriquecidos = []
    for entry in sorted(logs, key=lambda l: l.get("id_log", 0), reverse=True):
        item = dict(entry)
        u_info = auth_service.usuarios.get(item.get("usuario_id"))
        if u_info:
            item["usuario_nombre"] = f"{u_info.get('nombre', '')} {u_info.get('apellido', '')}".strip()
            item["usuario_email"] = u_info.get("email")
        else:
            item["usuario_nombre"] = f"Usuario #{item.get('usuario_id', 'Sistema')}"
            item["usuario_email"] = None
        if q:
            haystack = " ".join([
                str(item.get("usuario_nombre") or ""),
                str(item.get("usuario_email") or ""),
                str(item.get("usuario_id") or ""),
                str(item.get("tipo_accion") or ""),
                str(item.get("tabla_afectada") or ""),
                str(item.get("ip_address") or ""),
                str(item.get("user_agent") or ""),
                str(item.get("valor_anterior") or ""),
                str(item.get("valor_nuevo") or ""),
                str(item.get("id_registro_afectado") or ""),
            ]).lower()
            if q not in haystack:
                continue
        enriquecidos.append(item)
    return enriquecidos


@app.route("/api/admin/auditoria", methods=["GET"])
def api_admin_auditoria():
    """
    RF-SEG-001 a RF-SEG-005 / RN-SEG-005: Consulta de logs inmutables de auditoría (exclusivo Administradora).
    """
    token = extract_bearer_token()
    if not token or not auth_service.verificar_sesion(token):
        return api_response("error", "No autorizado. Inicie sesión.", None, 401)

    try:
        rol = auth_service.get_user_role(token)
        enriquecidos = _consultar_auditoria_filtrada(rol, request.args)
        return api_response("success", "Registros de auditoría consultados.", enriquecidos, 200)
    except PermissionError as e:
        return api_response("error", str(e), None, 403)
    except ValueError as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/admin/auditoria/csv", methods=["GET"])
def api_admin_auditoria_csv():
    """Exportación CSV segura (anti Formula Injection) de logs de auditoría filtrados (exclusivo Administradora)."""
    _, err_resp = _require_admin_token()
    if err_resp:
        return err_resp

    try:
        enriquecidos = _consultar_auditoria_filtrada("Administradora", request.args)
        headers = [
            "ID Log",
            "Fecha y Hora",
            "Usuario",
            "Correo",
            "Accion",
            "IP",
            "Dispositivo (User-Agent)",
            "Tabla Afectada",
            "ID Registro",
            "Valor Anterior",
            "Valor Nuevo",
        ]
        rows = [
            [
                item.get("id_log"),
                item.get("fecha_accion") or item.get("fecha"),
                item.get("usuario_nombre"),
                item.get("usuario_email") or "",
                item.get("tipo_accion"),
                item.get("ip_address") or "",
                item.get("user_agent") or "",
                item.get("tabla_afectada"),
                item.get("id_registro_afectado") if item.get("id_registro_afectado") is not None else "",
                item.get("valor_anterior") if item.get("valor_anterior") is not None else "",
                item.get("valor_nuevo") if item.get("valor_nuevo") is not None else "",
            ]
            for item in enriquecidos
        ]
        return _build_csv_response(headers, rows, "auditoria_onestyle.csv")
    except ValueError as e:
        return api_response("error", str(e), None, 400)


# =========================================================================
# ENDPOINTS REST — MÓDULO 2: CATÁLOGO, CATEGORÍAS, ATRIBUTOS E INVENTARIO
# Trazabilidad: RF-CAT-001 a RF-CAT-018 / Códigos HTTP: 200, 201, 400, 404, 409
# =========================================================================

def _require_staff_token():
    """Valida token y rol autorizado (Administradora o Vendedora)."""
    token = extract_bearer_token()
    if not token or not auth_service.verificar_sesion(token):
        return None, None, api_response("error", "No autorizado. Inicie sesión.", None, 401)
    rol = auth_service.get_user_role(token)
    if rol not in ("Administradora", "Vendedora"):
        return None, None, api_response("error", "Acceso restringido al personal autorizado.", None, 403)
    return auth_service.get_user_id(token), rol, None


@app.route("/admin/catalogo")
def vista_admin_catalogo():
    # El prototipo aislado se integró a la SPA: se redirige al panel unificado.
    return redirect("/#/admin/catalogo", code=302)


ALLOWED_CATALOG_SORTS = {"destacados", "priceAsc", "priceDesc", "name", "stock"}


@app.route("/api/catalogo", methods=["GET"])
def api_catalogo_publico():
    """
    RF-CAT-012: Consulta paginada del catálogo público con filtrado por categoría, talla, color, búsqueda y ordenamiento.
    """
    try:
        categoria = request.args.get("categoria")
        talla = request.args.get("talla")
        color = request.args.get("color")
        termino = request.args.get("q") or request.args.get("termino")
        raw_sort = (request.args.get("sort") or "destacados").strip()
        sort = raw_sort if raw_sort in ALLOWED_CATALOG_SORTS else "destacados"
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 12))

        resultado = catalogo_service.obtener_catalogo_publico(
            categoria=categoria,
            talla=talla,
            color=color,
            termino=termino,
            sort=sort,
            page=page,
            per_page=per_page
        )
        return api_response("success", "Catálogo público obtenido exitosamente.", resultado, 200)
    except ValueError as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/catalogo/<path:product_key>", methods=["GET"])
def api_detalle_producto(product_key: str):
    """
    RF-CAT-018: Ficha detallada de producto con sus variantes (talla, color, SKU, precio y stock disponible).
    """
    try:
        detalle = catalogo_service.obtener_detalle_producto(product_key)
        return api_response("success", "Detalle de prenda obtenido.", detalle, 200)
    except NotFoundError as e:
        return api_response("error", str(e), None, 404)
    except ValueError as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/categorias", methods=["GET"])
@app.route("/api/productos/categorias", methods=["GET"])
def api_listar_categorias_publicas():
    """RF-CAT-009: Listado de categorías activas para navegación pública."""
    cats = catalogo_service.listar_categorias(solo_activas=True)
    return api_response("success", "Categorías activas.", cats, 200)


@app.route("/api/atributos", methods=["GET"])
def api_listar_atributos_publicos():
    """RF-CAT-014: Listado de tallas y colores activos."""
    atributos = catalogo_service.listar_atributos_maestros(solo_activos=True)
    return api_response("success", "Atributos maestros activos.", atributos, 200)


@app.route("/api/admin/categorias", methods=["GET", "POST"])
def api_admin_categorias():
    """RF-CAT-008 y RF-CAT-009: Consulta y creación administrativa de categorías (exclusivo Administradora)."""
    uid, err_resp = _require_admin_token()
    if err_resp:
        return err_resp

    if request.method == "GET":
        return api_response("success", "Categorías registradas.", catalogo_service.listar_categorias(solo_activas=False), 200)

    try:
        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(
            payload,
            allowed_fields={"nombre_categoria", "descripcion_categoria"},
            required_fields={"nombre_categoria"}
        )
        cat_id = catalogo_service.crear_categoria(
            nombre_categoria=clean["nombre_categoria"],
            descripcion_categoria=clean.get("descripcion_categoria", ""),
            usuario_id=uid
        )
        return api_response("success", "Categoría creada exitosamente.", {"id_categoria": cat_id}, 201)
    except ConflictError as e:
        return api_response("error", str(e), None, 409)
    except ValueError as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/admin/categorias/<int:id_cat>", methods=["PUT", "DELETE"])
def api_admin_actualizar_categoria(id_cat: int):
    """RF-CAT-010: Actualización o eliminación segura de categoría maestra (exclusivo Administradora)."""
    uid, err_resp = _require_admin_token()
    if err_resp:
        return err_resp

    try:
        if request.method == "DELETE":
            catalogo_service.eliminar_categoria(id_cat, usuario_id=uid)
            return api_response("success", "Categoría eliminada exitosamente.", {"id_categoria": id_cat}, 200)

        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(
            payload,
            allowed_fields={"nombre_categoria", "descripcion_categoria"}
        )
        actualizada = catalogo_service.actualizar_categoria(
            categoria_id=id_cat,
            nombre_categoria=clean.get("nombre_categoria"),
            descripcion_categoria=clean.get("descripcion_categoria"),
            usuario_id=uid
        )
        return api_response("success", "Categoría actualizada.", actualizada, 200)
    except NotFoundError as e:
        return api_response("error", str(e), None, 404)
    except ConflictError as e:
        return api_response("error", str(e), None, 409)
    except ValueError as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/admin/categorias/<int:id_cat>/estado", methods=["PATCH"])
def api_admin_desactivar_categoria(id_cat: int):
    """RF-CAT-011: Baja lógica o reactivación de categoría (bloquea baja si posee productos activos)."""
    uid, err_resp = _require_admin_token()
    if err_resp:
        return err_resp

    try:
        activar = False
        raw_body = request.get_data(as_text=True) or ""
        if raw_body.strip():
            payload = request.get_json(silent=True)
            clean = validate_whitelist_payload(payload, allowed_fields={"estado"}, required_fields={"estado"})
            raw_est = clean["estado"]
            if isinstance(raw_est, bool):
                activar = raw_est
            elif str(raw_est).strip().lower() in ("true", "1", "activo"):
                activar = True
            elif str(raw_est).strip().lower() in ("false", "0", "inactivo"):
                activar = False
            else:
                raise ValueError("Valor inválido para 'estado'.")

        if activar:
            catalogo_service.activar_categoria(id_cat, usuario_id=uid)
            return api_response("success", "Categoría activada.", {"id_categoria": id_cat, "estado": True}, 200)

        catalogo_service.desactivar_categoria(id_cat, usuario_id=uid)
        return api_response("success", "Categoría desactivada mediante baja lógica.", {"id_categoria": id_cat, "estado": False}, 200)
    except NotFoundError as e:
        return api_response("error", str(e), None, 404)
    except ConflictError as e:
        return api_response("error", str(e), None, 409)
    except ValueError as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/admin/atributos", methods=["GET"])
def api_admin_listar_atributos():
    """RF-CAT-014: Listado completo administrativo de tallas y colores (incluye inactivos y conteo en uso)."""
    _, err_resp = _require_admin_token()
    if err_resp:
        return err_resp
    return api_response("success", "Atributos maestros consultados.", catalogo_service.listar_atributos_maestros(solo_activos=False), 200)


@app.route("/api/admin/tallas", methods=["POST"])
def api_admin_crear_talla():
    """RF-CAT-013: Creación de talla maestra (exclusivo Administradora)."""
    uid, err_resp = _require_admin_token()
    if err_resp:
        return err_resp
    try:
        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(payload, allowed_fields={"nombre_talla"}, required_fields={"nombre_talla"})
        tid = catalogo_service.crear_talla(clean["nombre_talla"], usuario_id=uid)
        return api_response("success", "Talla creada exitosamente.", {"id_talla": tid}, 201)
    except ConflictError as e:
        return api_response("error", str(e), None, 409)
    except ValueError as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/admin/tallas/<int:id_talla>", methods=["PUT", "DELETE"])
def api_admin_gestionar_talla(id_talla: int):
    """RF-CAT-015: Edición o eliminación segura de talla maestra (exclusivo Administradora)."""
    uid, err_resp = _require_admin_token()
    if err_resp:
        return err_resp
    try:
        if request.method == "DELETE":
            catalogo_service.eliminar_talla(id_talla, usuario_id=uid)
            return api_response("success", "Talla eliminada exitosamente.", {"id_talla": id_talla}, 200)
        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(payload, allowed_fields={"nombre_talla"}, required_fields={"nombre_talla"})
        actualizada = catalogo_service.actualizar_talla(id_talla, clean["nombre_talla"], usuario_id=uid)
        return api_response("success", "Talla actualizada.", actualizada, 200)
    except NotFoundError as e:
        return api_response("error", str(e), None, 404)
    except ConflictError as e:
        return api_response("error", str(e), None, 409)
    except ValueError as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/admin/tallas/<int:id_talla>/estado", methods=["PATCH"])
def api_admin_estado_talla(id_talla: int):
    """RF-CAT-016: Activación o baja lógica de talla maestra (exclusivo Administradora)."""
    uid, err_resp = _require_admin_token()
    if err_resp:
        return err_resp
    try:
        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(payload, allowed_fields={"estado"}, required_fields={"estado"})
        activar = clean["estado"] if isinstance(clean["estado"], bool) else str(clean["estado"]).lower() in ("true", "1", "activo")
        if activar:
            catalogo_service.activar_talla(id_talla, usuario_id=uid)
            return api_response("success", "Talla activada.", {"id_talla": id_talla, "estado": True}, 200)
        catalogo_service.desactivar_talla(id_talla, usuario_id=uid)
        return api_response("success", "Talla desactivada mediante baja lógica.", {"id_talla": id_talla, "estado": False}, 200)
    except NotFoundError as e:
        return api_response("error", str(e), None, 404)
    except ValueError as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/admin/colores", methods=["POST"])
def api_admin_crear_color():
    """RF-CAT-013: Creación de color maestro con código HEX (exclusivo Administradora)."""
    uid, err_resp = _require_admin_token()
    if err_resp:
        return err_resp
    try:
        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(
            payload,
            allowed_fields={"nombre_color", "codigo_hex"},
            required_fields={"nombre_color"}
        )
        cid = catalogo_service.crear_color(
            clean["nombre_color"],
            codigo_hex=clean.get("codigo_hex", "#17140F"),
            usuario_id=uid
        )
        return api_response("success", "Color creado exitosamente.", {"id_color": cid}, 201)
    except ConflictError as e:
        return api_response("error", str(e), None, 409)
    except ValueError as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/admin/colores/<int:id_color>", methods=["PUT", "DELETE"])
def api_admin_gestionar_color(id_color: int):
    """RF-CAT-015: Edición o eliminación segura de color maestro (exclusivo Administradora)."""
    uid, err_resp = _require_admin_token()
    if err_resp:
        return err_resp
    try:
        if request.method == "DELETE":
            catalogo_service.eliminar_color(id_color, usuario_id=uid)
            return api_response("success", "Color eliminado exitosamente.", {"id_color": id_color}, 200)
        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(payload, allowed_fields={"nombre_color", "codigo_hex"})
        actualizado = catalogo_service.actualizar_color(
            id_color,
            nombre_color=clean.get("nombre_color"),
            codigo_hex=clean.get("codigo_hex"),
            usuario_id=uid
        )
        return api_response("success", "Color actualizado.", actualizado, 200)
    except NotFoundError as e:
        return api_response("error", str(e), None, 404)
    except ConflictError as e:
        return api_response("error", str(e), None, 409)
    except ValueError as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/admin/colores/<int:id_color>/estado", methods=["PATCH"])
def api_admin_estado_color(id_color: int):
    """RF-CAT-016: Activación o baja lógica de color maestro (exclusivo Administradora)."""
    uid, err_resp = _require_admin_token()
    if err_resp:
        return err_resp
    try:
        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(payload, allowed_fields={"estado"}, required_fields={"estado"})
        activar = clean["estado"] if isinstance(clean["estado"], bool) else str(clean["estado"]).lower() in ("true", "1", "activo")
        if activar:
            catalogo_service.activar_color(id_color, usuario_id=uid)
            return api_response("success", "Color activado.", {"id_color": id_color, "estado": True}, 200)
        catalogo_service.desactivar_color(id_color, usuario_id=uid)
        return api_response("success", "Color desactivado mediante baja lógica.", {"id_color": id_color, "estado": False}, 200)
    except NotFoundError as e:
        return api_response("error", str(e), None, 404)
    except ValueError as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/admin/productos", methods=["GET", "POST"])
def api_admin_productos():
    """
    RF-CAT-001 y RF-CAT-004: Listado administrativo y creación de producto maestro + variante inicial.
    """
    uid, _, err_resp = _require_staff_token()
    if err_resp:
        return err_resp

    if request.method == "GET":
        termino = request.args.get("q")
        categoria = request.args.get("categoria")
        estado = request.args.get("estado")
        try:
            page = int(request.args.get("page", 1))
            per_page = min(int(request.args.get("per_page", 10)), 100)
            if page < 1 or per_page < 1:
                raise ValueError
        except ValueError:
            return api_response("error", "Los parámetros 'page' y 'per_page' deben ser enteros positivos.", None, 400)
        lista = catalogo_service.listar_productos_admin(termino=termino, categoria=categoria, estado=estado)
        total = len(lista)
        total_pages = max(1, (total + per_page - 1) // per_page)
        inicio = (page - 1) * per_page
        return api_response(
            "success",
            "Listado administrativo de productos.",
            {
                "items": lista[inicio:inicio + per_page],
                "page": page,
                "per_page": per_page,
                "total": total,
                "total_pages": total_pages,
                "has_next": page < total_pages,
                "has_prev": page > 1
            },
            200
        )

    try:
        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(
            payload,
            allowed_fields={
                "nombre_producto", "descripcion_producto", "precio_detallista",
                "fk_id_categoria", "url_imagen_principal", "estado_visibilidad",
                "fk_id_talla", "fk_id_color", "stock_real", "punto_reposicion",
                "codigo_sku", "precio_variante"
            },
            required_fields={"nombre_producto", "precio_detallista", "fk_id_categoria"}
        )

        prod_id = catalogo_service.crear_producto(
            nombre=clean["nombre_producto"],
            descripcion=clean.get("descripcion_producto", ""),
            precio=float(clean["precio_detallista"]),
            categoria_id=int(clean["fk_id_categoria"]),
            url_imagen_principal=clean.get("url_imagen_principal"),
            estado_visibilidad=bool(clean.get("estado_visibilidad", True)),
            usuario_id=uid
        )

        var_id = None
        if "stock_real" in clean or "fk_id_talla" in clean or "codigo_sku" in clean:
            var_id = catalogo_service.agregar_variante(
                producto_id=prod_id,
                stock=int(clean.get("stock_real", 0)),
                punto_reposicion=int(clean.get("punto_reposicion", 3)),
                talla_id=int(clean["fk_id_talla"]) if clean.get("fk_id_talla") is not None else None,
                color_id=int(clean["fk_id_color"]) if clean.get("fk_id_color") is not None else None,
                sku=clean.get("codigo_sku"),
                precio_especifico=float(clean["precio_variante"]) if clean.get("precio_variante") is not None else None,
                usuario_id=uid
            )

        return api_response(
            "success",
            "Producto registrado exitosamente.",
            {"id_producto": prod_id, "id_variante": var_id, "producto": catalogo_service.obtener_detalle_producto(prod_id)},
            201
        )
    except NotFoundError as e:
        return api_response("error", str(e), None, 404)
    except ConflictError as e:
        return api_response("error", str(e), None, 409)
    except ValueError as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/admin/productos/<int:id_prod>", methods=["PUT"])
def api_admin_actualizar_producto(id_prod: int):
    """RF-CAT-003: Modificación de datos básicos de una prenda."""
    uid, _, err_resp = _require_staff_token()
    if err_resp:
        return err_resp

    try:
        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(
            payload,
            allowed_fields={
                "nombre_producto", "descripcion_producto", "precio_detallista",
                "fk_id_categoria", "url_imagen_principal"
            }
        )
        precio_parsed = None
        if "precio_detallista" in clean:
            raw_precio = clean["precio_detallista"]
            if raw_precio is None or isinstance(raw_precio, bool):
                raise ValueError("El precio debe ser un valor numérico mayor a cero.")
            precio_parsed = float(raw_precio)
            if precio_parsed != precio_parsed or abs(precio_parsed) == float("inf") or precio_parsed <= 0:
                raise ValueError("RN-CAT-003: El precio actualizado debe ser mayor a cero.")

        cat_parsed = None
        if "fk_id_categoria" in clean:
            raw_cat = clean["fk_id_categoria"]
            if raw_cat is None or isinstance(raw_cat, bool):
                raise ValueError("La categoría especificada es inválida.")
            cat_parsed = int(raw_cat)

        catalogo_service.actualizar_producto(
            producto_id=id_prod,
            nombre=clean.get("nombre_producto"),
            descripcion=clean.get("descripcion_producto"),
            precio=precio_parsed,
            categoria_id=cat_parsed,
            url_imagen_principal=clean.get("url_imagen_principal"),
            usuario_id=uid
        )
        return api_response("success", "Producto actualizado correctamente.", catalogo_service.obtener_detalle_producto(id_prod), 200)
    except NotFoundError as e:
        return api_response("error", str(e), None, 404)
    except ConflictError as e:
        return api_response("error", str(e), None, 409)
    except (ValueError, TypeError) as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/admin/productos/<int:id_prod>/visibilidad", methods=["PATCH"])
def api_admin_visibilidad_producto(id_prod: int):
    """RF-CAT-002: Baja o activación lógica de visibilidad de prenda."""
    uid, _, err_resp = _require_staff_token()
    if err_resp:
        return err_resp

    try:
        payload = request.get_json(silent=True) or {}
        clean = validate_whitelist_payload(payload, allowed_fields={"estado_visibilidad"}, required_fields={"estado_visibilidad"})
        visible = str(clean["estado_visibilidad"]).lower() in ("true", "1", "activo")
        catalogo_service.cambiar_visibilidad_producto(id_prod, visible=visible, usuario_id=uid)
        return api_response("success", "Visibilidad del producto actualizada.", {"id_producto": id_prod, "estado_visibilidad": visible}, 200)
    except NotFoundError as e:
        return api_response("error", str(e), None, 404)
    except ValueError as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/admin/productos/<int:id_prod>/imagenes", methods=["GET", "POST"])
def api_admin_imagenes_producto(id_prod: int):
    """
    RF-CAT-017: Consulta y carga segura multipart (1..N) de imágenes de prenda (exclusivo Administradora).
    """
    uid, err_resp = _require_admin_token()
    if err_resp:
        return err_resp

    if request.method == "GET":
        try:
            imgs = catalogo_service.listar_imagenes_producto(id_prod)
            prod = catalogo_service.productos.get(id_prod, {})
            return api_response(
                "success",
                "Galería de imágenes consultada.",
                {"imagenes": imgs, "url_imagen_principal": prod.get("url_imagen_principal")},
                200,
            )
        except NotFoundError as e:
            return api_response("error", str(e), None, 404)

    saved_paths = []
    try:
        actuales = catalogo_service.listar_imagenes_producto(id_prod)
        archivos = []
        for field_name in ("imagenes", "files", "imagen"):
            archivos.extend([f for f in request.files.getlist(field_name) if f and getattr(f, "filename", "")])
        if not archivos:
            for key in request.files:
                archivos.extend([f for f in request.files.getlist(key) if f and getattr(f, "filename", "")])
        if not archivos:
            raise ValueError("Debes adjuntar al menos una imagen (.jpg, .jpeg, .png o .webp).")

        if len(actuales) + len(archivos) > catalogo_service.MAX_IMAGENES_POR_PRODUCTO:
            raise ValueError(
                f"Supera el límite máximo de {catalogo_service.MAX_IMAGENES_POR_PRODUCTO} imágenes por prenda."
            )

        # Validar todo el lote ANTES de persistir archivos en disco
        validated_batch = [_validate_image_file(fs) for fs in archivos]
        make_first_principal = str(request.form.get("es_principal", "")).strip().lower() in ("true", "1", "yes", "si")

        agregadas = []
        for idx, (raw_bytes, canonical_ext, fmt_upper) in enumerate(validated_batch):
            rel_url, abs_path = _save_validated_image_bytes(raw_bytes, canonical_ext)
            saved_paths.append(abs_path)
            img_id = catalogo_service.agregar_imagen_producto(
                producto_id=id_prod,
                url_imagen=rel_url,
                formato=fmt_upper,
                es_principal=(idx == 0 and make_first_principal),
                usuario_id=uid,
            )
            agregadas.append({"id_imagen": img_id, "url_imagen": rel_url, "formato": fmt_upper})

        galeria = catalogo_service.listar_imagenes_producto(id_prod)
        return api_response(
            "success",
            f"Se subieron {len(agregadas)} imagen(es) exitosamente.",
            {
                "agregadas": agregadas,
                "imagenes": galeria,
                "url_imagen_principal": catalogo_service.productos[id_prod].get("url_imagen_principal"),
            },
            201,
        )
    except ImageTooLargeError as e:
        return api_response("error", str(e), None, 413)
    except NotFoundError as e:
        return api_response("error", str(e), None, 404)
    except ValueError as e:
        for p in saved_paths:
            if os.path.isfile(p):
                try:
                    os.remove(p)
                except OSError:
                    pass
        return api_response("error", str(e), None, 400)


@app.route("/api/admin/productos/<int:id_prod>/imagenes/<int:id_img>/principal", methods=["PATCH"])
def api_admin_imagen_principal(id_prod: int, id_img: int):
    """RF-CAT-017: Marca una imagen de la galería como portada principal (exclusivo Administradora)."""
    uid, err_resp = _require_admin_token()
    if err_resp:
        return err_resp

    try:
        galeria = catalogo_service.marcar_imagen_principal(id_prod, id_img, usuario_id=uid)
        return api_response(
            "success",
            "Imagen principal actualizada.",
            {"imagenes": galeria, "url_imagen_principal": catalogo_service.productos[id_prod].get("url_imagen_principal")},
            200,
        )
    except NotFoundError as e:
        return api_response("error", str(e), None, 404)


@app.route("/api/admin/productos/<int:id_prod>/imagenes/reordenar", methods=["PATCH"])
def api_admin_reordenar_imagenes(id_prod: int):
    """RF-CAT-017: Reordena las imágenes 1..N de una prenda (exclusivo Administradora)."""
    uid, err_resp = _require_admin_token()
    if err_resp:
        return err_resp

    try:
        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(payload, allowed_fields={"orden_ids"}, required_fields={"orden_ids"})
        orden_ids = clean["orden_ids"]
        if not isinstance(orden_ids, list):
            raise ValueError("El campo 'orden_ids' debe ser una lista de identificadores.")
        galeria = catalogo_service.reordenar_imagenes_producto(id_prod, orden_ids, usuario_id=uid)
        return api_response("success", "Orden de galería actualizado.", {"imagenes": galeria}, 200)
    except NotFoundError as e:
        return api_response("error", str(e), None, 404)
    except (ValueError, TypeError) as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/admin/productos/<int:id_prod>/imagenes/<int:id_img>", methods=["DELETE"])
def api_admin_eliminar_imagen(id_prod: int, id_img: int):
    """RF-CAT-017: Elimina una imagen individual de la galería de prenda (exclusivo Administradora)."""
    uid, err_resp = _require_admin_token()
    if err_resp:
        return err_resp

    try:
        res = catalogo_service.eliminar_imagen_producto(id_prod, id_img, usuario_id=uid)
        _delete_local_upload_if_safe(res["eliminada"].get("url_imagen"))
        return api_response(
            "success",
            "Imagen eliminada de la galería.",
            {"imagenes": res["imagenes"], "url_imagen_principal": res["url_imagen_principal"]},
            200,
        )
    except NotFoundError as e:
        return api_response("error", str(e), None, 404)


@app.route("/api/admin/variantes", methods=["POST"])
def api_admin_crear_variante():
    """
    RF-CAT-005 / RN-CAT-005: Asociar variante (talla, color, SKU, precio y stock inicial) a un producto.
    Retorna 409 Conflict si el SKU o la combinación (producto, talla, color) ya existe.
    """
    uid, _, err_resp = _require_staff_token()
    if err_resp:
        return err_resp

    try:
        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(
            payload,
            allowed_fields={
                "fk_id_producto", "fk_id_talla", "fk_id_color",
                "stock_real", "punto_reposicion", "codigo_sku", "precio_variante"
            },
            required_fields={"fk_id_producto", "fk_id_talla", "fk_id_color", "stock_real"}
        )
        var_id = catalogo_service.agregar_variante(
            producto_id=int(clean["fk_id_producto"]),
            stock=int(clean["stock_real"]),
            punto_reposicion=int(clean.get("punto_reposicion", 3)),
            talla_id=int(clean["fk_id_talla"]),
            color_id=int(clean["fk_id_color"]),
            sku=clean.get("codigo_sku"),
            precio_especifico=float(clean["precio_variante"]) if clean.get("precio_variante") is not None else None,
            usuario_id=uid
        )
        return api_response("success", "Variante registrada exitosamente.", {"id_variante": var_id}, 201)
    except NotFoundError as e:
        return api_response("error", str(e), None, 404)
    except ConflictError as e:
        return api_response("error", str(e), None, 409)
    except ValueError as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/admin/inventario/ajuste", methods=["POST"])
def api_admin_ajuste_inventario():
    """
    RF-CAT-006 y RNF-011: Ajuste atómico de existencias físicas con motivo obligatorio.
    Retorna 409 Conflict si una salida intenta dejar el stock en negativo.
    """
    uid, _, err_resp = _require_staff_token()
    if err_resp:
        return err_resp

    try:
        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(
            payload,
            allowed_fields={"fk_id_variante", "tipo_accion", "cantidad", "motivo", "punto_reposicion"},
            required_fields={"fk_id_variante", "tipo_accion", "cantidad", "motivo"}
        )
        cantidad = int(clean["cantidad"])
        if cantidad <= 0:
            return api_response("error", "La cantidad del movimiento debe ser mayor a cero.", None, 400)

        tipo = clean["tipo_accion"].lower()
        if tipo not in ("entrada", "salida", "ajuste"):
            return api_response("error", "El tipo_accion debe ser 'entrada' o 'salida'.", None, 400)

        delta = -cantidad if tipo == "salida" else cantidad
        nuevo_stock = catalogo_service.ajustar_stock_variante(
            variante_id=int(clean["fk_id_variante"]),
            delta=delta,
            motivo=clean["motivo"],
            usuario_id=uid,
            nuevo_punto_reposicion=int(clean["punto_reposicion"]) if clean.get("punto_reposicion") is not None else None
        )
        return api_response(
            "success",
            "Movimiento de inventario aplicado correctamente.",
            {
                "id_variante": int(clean["fk_id_variante"]),
                "stock_real": nuevo_stock,
                "alerta_reposicion": catalogo_service.alerta_punto_reposicion(int(clean["fk_id_variante"]))
            },
            200
        )
    except NotFoundError as e:
        return api_response("error", str(e), None, 404)
    except ConflictError as e:
        return api_response("error", str(e), None, 409)
    except ValueError as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/admin/inventario/alertas", methods=["GET"])
def api_admin_alertas_inventario():
    """RF-CAT-007: Monitoreo de variantes en punto de reposición o agotadas."""
    _, _, err_resp = _require_staff_token()
    if err_resp:
        return err_resp
    alertas = catalogo_service.listar_alertas_reposicion()
    return api_response("success", "Alertas de punto de reposición.", alertas, 200)


# =========================================================================
# ENDPOINTS REST — MÓDULO 3: CARRITO DE COMPRAS Y RESERVAS TEMPORALES
# Trazabilidad: RF-CRT-001 a RF-CRT-003 / Códigos HTTP: 200, 201, 400, 404, 409
# =========================================================================

def _get_current_cart() -> CarritoService:
    """
    Resuelve la instancia persistente de CarritoService para el usuario autenticado
    o la clave de sesión/invitado enviada en X-Session-ID.
    """
    token = extract_bearer_token()
    uid = None
    if token and auth_service.verificar_sesion(token):
        uid = auth_service.get_user_id(token)

    session_header = (request.headers.get("X-Session-ID") or "default-session").strip()
    cart_key = f"user-{uid}" if uid else f"sess-{session_header}"

    if cart_key not in carritos_activos:
        carritos_activos[cart_key] = CarritoService(
            catalogo_service=catalogo_service,
            usuario_id=uid,
            session_id=session_header
        )
    return carritos_activos[cart_key]


@app.route("/api/carrito", methods=["GET", "DELETE"])
def api_carrito_general():
    """
    RF-CRT-001 y RF-CRT-002:
    - GET: Consulta el estado del carrito, ítems con precio congelado, subtotales y TTL de reserva.
    - DELETE: Vacía el carrito liberando de inmediato todas las reservas temporales.
    """
    carrito = _get_current_cart()
    if request.method == "DELETE":
        carrito.vaciar_carrito()
        return api_response("success", "Carrito vaciado y reservas de stock liberadas.", carrito.obtener_resumen(), 200)

    return api_response("success", "Resumen del carrito de compras.", carrito.obtener_resumen(), 200)


@app.route("/api/carrito/items", methods=["POST"])
def api_carrito_agregar_item():
    """
    RF-CRT-001 / RN-CRT-001: Añade una variante al carrito congelando su precio unitario
    y creando una reserva temporal (TTL) con control atómico de concurrencia.
    Códigos: 201 (creado), 400 (cantidad inválida), 404 (variante inexistente), 409 (conflicto de stock).
    """
    carrito = _get_current_cart()
    try:
        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(
            payload,
            allowed_fields={"fk_id_variante", "cantidad"},
            required_fields={"fk_id_variante", "cantidad"}
        )
        variante_id = int(clean["fk_id_variante"])
        cantidad = int(clean["cantidad"])

        carrito.agregar_item(variante_id, cantidad)
        return api_response("success", "Prenda añadida al carrito con reserva temporal de stock.", carrito.obtener_resumen(), 201)
    except NotFoundError as e:
        return api_response("error", str(e), None, 404)
    except ConflictError as e:
        return api_response("error", str(e), None, 409)
    except ValueError as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/carrito/items/<int:variante_id>", methods=["PUT", "DELETE"])
def api_carrito_item_especifico(variante_id: int):
    """
    RF-CRT-002 / RN-CRT-002:
    - PUT: Modifica la cantidad de un ítem recalculando reservas temporales y subtotales.
    - DELETE: Elimina el ítem del carrito liberando la reserva temporal inmediatamente.
    """
    carrito = _get_current_cart()
    try:
        if request.method == "DELETE":
            carrito.remover_item(variante_id)
            return api_response("success", "Ítem eliminado del carrito y reserva liberada.", carrito.obtener_resumen(), 200)

        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(
            payload,
            allowed_fields={"cantidad"},
            required_fields={"cantidad"}
        )
        nueva_cantidad = int(clean["cantidad"])
        carrito.modificar_cantidad_carrito(variante_id, nueva_cantidad)
        return api_response("success", "Cantidad actualizada en el carrito.", carrito.obtener_resumen(), 200)
    except NotFoundError as e:
        return api_response("error", str(e), None, 404)
    except ConflictError as e:
        return api_response("error", str(e), None, 409)
    except ValueError as e:
        return api_response("error", str(e), None, 400)


def _apply_authenticated_identity(clean: dict, uid):
    """
    Para usuarias autenticadas, la fuente de verdad de Nombre y Correo es siempre
    el registro del usuario en el servidor, ignorando cualquier alteración en payload.
    """
    if uid is not None and uid in auth_service.usuarios:
        u = auth_service.usuarios[uid]
        full_name = f"{u.get('nombre', '')} {u.get('apellido', '')}".strip() or u["email"]
        clean["nombre_receptor"] = full_name
        clean["email"] = u["email"]
    return clean


@app.route("/api/carrito/despacho", methods=["POST"])
def api_carrito_despacho():
    """
    RF-CRT-003 / RN-CRT-003: Captura y valida los datos obligatorios de despacho
    (dirección exacta, barrio, ciudad, teléfono de contacto y observaciones).
    """
    carrito = _get_current_cart()
    token = extract_bearer_token()
    uid = auth_service.get_user_id(token) if token and auth_service.verificar_sesion(token) else None
    try:
        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(
            payload,
            allowed_fields={"direccion_envio", "barrio", "ciudad", "telefono", "observaciones", "nombre_receptor", "email"},
            required_fields={"direccion_envio", "barrio", "ciudad", "telefono"}
        )
        _apply_authenticated_identity(clean, uid)
        datos = carrito.capturar_datos_despacho(
            direccion_envio=clean["direccion_envio"],
            barrio=clean["barrio"],
            ciudad=clean["ciudad"],
            telefono=clean["telefono"],
            observaciones=clean.get("observaciones", ""),
            nombre_receptor=clean.get("nombre_receptor", ""),
            email=clean.get("email", "")
        )
        return api_response("success", "Datos de despacho validados y vinculados al carrito.", datos, 200)
    except ValueError as e:
        return api_response("error", str(e), None, 400)


# =========================================================================
# ENDPOINTS REST — MÓDULO 4: GESTIÓN DE PEDIDOS (OMS), FSM Y WHATSAPP
# Trazabilidad: RF-PED-001 a RF-PED-004 / Códigos HTTP: 200, 201, 400, 403, 404, 409
# =========================================================================

@app.route("/api/pedidos/checkout", methods=["POST"])
def api_pedidos_checkout():
    """
    RF-PED-001 / RN-PED-001: Crea un pedido desde el carrito activo, consolida atómicamente
    las reservas temporales en descuento definitivo de stock, vacía el carrito y genera
    el enlace codificado hacia el Concierge de WhatsApp.
    """
    carrito = _get_current_cart()
    token = extract_bearer_token()
    uid = auth_service.get_user_id(token) if token and auth_service.verificar_sesion(token) else None

    try:
        payload = request.get_json(silent=True) or {}
        clean = validate_whitelist_payload(
            payload,
            allowed_fields={
                "direccion_envio", "barrio", "ciudad", "telefono",
                "observaciones", "nombre_receptor", "email", "metodo_entrega"
            }
        )
        datos_despacho = clean if any(k in clean for k in ("direccion_envio", "barrio", "ciudad", "telefono")) else None
        if datos_despacho is not None:
            _apply_authenticated_identity(datos_despacho, uid)
        elif carrito.datos_despacho and uid is not None:
            _apply_authenticated_identity(carrito.datos_despacho, uid)
        orden = pedidos_service.crear_pedido_desde_carrito(
            carrito=carrito,
            usuario_id=uid,
            datos_despacho=datos_despacho,
            metodo_entrega=clean.get("metodo_entrega", "Domicilio Express")
        )
        return api_response("success", "Pedido confirmado exitosamente.", orden, 201)
    except NotFoundError as e:
        return api_response("error", str(e), None, 404)
    except ConflictError as e:
        return api_response("error", str(e), None, 409)
    except ValueError as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/pedidos/seguimiento/<string:codigo_orden>", methods=["GET"])
def api_pedidos_seguimiento(codigo_orden: str):
    """
    RF-PED-003 / RN-PED-003: Consulta en tiempo real del estado e historial de un pedido
    por su código alfanumérico (`ORD-00001`) o ID.
    """
    token = extract_bearer_token()
    uid = None
    rol = None
    if token and auth_service.verificar_sesion(token):
        uid = auth_service.get_user_id(token)
        rol = auth_service.get_user_role(token)

    contacto = request.args.get("contacto")
    try:
        orden = pedidos_service.obtener_pedido_por_codigo_o_id(
            key=codigo_orden,
            solicitante_id=uid,
            rol=rol,
            contacto_verificacion=contacto
        )
        return api_response("success", "Estado del pedido consultado.", orden, 200)
    except PermissionError as e:
        return api_response("error", str(e), None, 403)
    except NotFoundError as e:
        return api_response("error", str(e), None, 404)
    except ValueError as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/pedidos/mis-pedidos", methods=["GET"])
def api_mis_pedidos():
    """
    RF-PED-003: Historial de pedidos de la clienta autenticada.
    """
    token = extract_bearer_token()
    if not token or not auth_service.verificar_sesion(token):
        return api_response("error", "No autorizado. Inicie sesión.", None, 401)
    uid = auth_service.get_user_id(token)
    lista = pedidos_service.listar_pedidos_usuario(uid)
    return api_response("success", "Historial de pedidos del cliente.", lista, 200)


@app.route("/api/admin/pedidos", methods=["GET"])
def api_admin_listar_pedidos():
    """
    RF-PED-002: Listado administrativo OMS de pedidos con filtro por estado o vendedora.
    """
    _, _, err_resp = _require_staff_token()
    if err_resp:
        return err_resp
    estado = request.args.get("estado")
    vendedora_param = request.args.get("vendedora_id")
    vid = int(vendedora_param) if vendedora_param and vendedora_param.isdigit() else None
    try:
        data = pedidos_service.listar_pedidos_paginados(
            page=request.args.get("page", 1),
            per_page=request.args.get("per_page", 10),
            estado=estado,
            vendedora_id=vid,
            termino=request.args.get("q")
        )
        return api_response("success", "Listado de pedidos en OMS.", data, 200)
    except ValueError as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/admin/dashboard", methods=["GET"])
def api_admin_dashboard():
    """
    Métricas consolidadas del panel administrativo en una sola respuesta:
    pedidos por estado, ventas, alertas de stock, catálogo y tickets de soporte abiertos.
    """
    _, rol, err_resp = _require_staff_token()
    if err_resp:
        return err_resp

    metricas = pedidos_service.obtener_metricas_dashboard()
    alertas = catalogo_service.listar_alertas_reposicion()
    productos = catalogo_service.listar_productos_admin()
    tickets_abiertos = sum(1 for t in faq_service.tickets.values() if t.get("estado") == "ABIERTO")

    recientes = pedidos_service.listar_pedidos_paginados(page=1, per_page=5)["items"]

    return api_response(
        "success",
        "Métricas del dashboard administrativo.",
        {
            "rol": rol,
            "pedidos": metricas,
            "inventario": {
                "alertas_total": len(alertas),
                "agotadas": sum(1 for a in alertas if a["estado_alerta"] == "AGOTADO"),
                "stock_bajo": sum(1 for a in alertas if a["estado_alerta"] == "STOCK_BAJO"),
                "alertas": alertas[:8]
            },
            "catalogo": {
                "total_productos": len(productos),
                "productos_visibles": sum(1 for p in productos if p["estado_visibilidad"]),
            },
            "soporte": {"tickets_abiertos": tickets_abiertos},
            "pedidos_recientes": recientes
        },
        200
    )


@app.route("/api/admin/pedidos/<int:pedido_id>/estado", methods=["PATCH"])
def api_admin_transicionar_estado_pedido(pedido_id: int):
    """
    RF-PED-002 / RN-PED-002: Ejecuta una transición secuencial validada en la Máquina de Estados (FSM)
    del pedido y reintegra existencias automáticamente si se cancela.
    """
    uid, _, err_resp = _require_staff_token()
    if err_resp:
        return err_resp

    try:
        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(
            payload,
            allowed_fields={"nuevo_estado", "motivo"},
            required_fields={"nuevo_estado"}
        )
        pedidos_service.transicionar_estado(
            pedido_id=pedido_id,
            nuevo_estado=clean["nuevo_estado"],
            usuario_responsable=uid,
            motivo=clean.get("motivo", "")
        )
        actualizado = pedidos_service.serializar_pedido(pedido_id)
        return api_response("success", f"Estado del pedido actualizado a '{clean['nuevo_estado']}'.", actualizado, 200)
    except NotFoundError as e:
        return api_response("error", str(e), None, 404)
    except ValueError as e:
        return api_response("error", str(e), None, 400)


def _generar_reporte_vendedoras_enriquecido(
    uid: int,
    rol: str,
    estado: str | None,
    vendedora_id: int | None,
    fecha_inicio_raw: str | None,
    fecha_fin_raw: str | None,
) -> dict:
    dt_ini, dt_fin = _parse_date_range(fecha_inicio_raw, fecha_fin_raw)
    reporte = pedidos_service.generar_reporte_ventas(
        rol_solicitante=rol,
        usuario_id=uid,
        estado=estado,
        vendedora_id=vendedora_id,
        fecha_inicio=dt_ini,
        fecha_fin=dt_fin,
    )
    resumen_enriquecido = []
    for item in reporte.get("resumen_vendedoras_raw", []):
        vid = int(item["vendedora_id"])
        u_info = auth_service.usuarios.get(vid) or {}
        nombre = f"{u_info.get('nombre', '')} {u_info.get('apellido', '')}".strip() or f"Vendedora #{vid}"
        email = u_info.get("email") or ""
        rol_u = u_info.get("rol") or "Vendedora"
        estado_u = bool(u_info.get("estado_usuario", True)) if u_info else True
        resumen_enriquecido.append({
            "vendedora_id": vid,
            "nombre": nombre,
            "email": email,
            "rol": rol_u,
            "estado_usuario": estado_u,
            "estado_cuenta": "Activo" if estado_u else "Inactivo",
            "cantidad_pedidos": item["cantidad_pedidos"],
            "pedidos_activos": item["pedidos_activos"],
            "pedidos_cancelados": item["pedidos_cancelados"],
            "total_vendido": item["total_vendido"],
            "por_estado": item["por_estado"],
        })
    resumen_enriquecido.sort(key=lambda r: (r["total_vendido"], r["cantidad_pedidos"]), reverse=True)
    reporte["resumen_vendedoras"] = resumen_enriquecido
    reporte["filtros"] = {
        "fecha_inicio": (fecha_inicio_raw or "").strip(),
        "fecha_fin": (fecha_fin_raw or "").strip(),
        "estado": (estado or "").strip(),
    }
    return reporte


@app.route("/api/admin/pedidos/reporte", methods=["GET"])
def api_admin_reporte_pedidos():
    """
    RF-PED-004 / RN-PED-004: Reporte consolidado de ventas e indicadores de gestión por estado y vendedora.
    Acceso exclusivo Administradora (OWASP A01).
    """
    uid, err_resp = _require_admin_token()
    if err_resp:
        return err_resp

    try:
        estado = request.args.get("estado")
        vendedora_param = request.args.get("vendedora_id")
        vid = int(vendedora_param) if vendedora_param and vendedora_param.isdigit() else None
        reporte = _generar_reporte_vendedoras_enriquecido(
            uid=uid,
            rol="Administradora",
            estado=estado,
            vendedora_id=vid,
            fecha_inicio_raw=request.args.get("fecha_inicio"),
            fecha_fin_raw=request.args.get("fecha_fin"),
        )
        return api_response("success", "Reporte consolidado de ventas generado.", reporte, 200)
    except PermissionError as e:
        return api_response("error", str(e), None, 403)
    except ValueError as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/admin/pedidos/reporte/csv", methods=["GET"])
def api_admin_reporte_pedidos_csv():
    """Exportación CSV segura (anti Formula Injection) de reportes por vendedora (exclusivo Administradora)."""
    uid, err_resp = _require_admin_token()
    if err_resp:
        return err_resp

    try:
        estado = request.args.get("estado")
        vendedora_param = request.args.get("vendedora_id")
        vid = int(vendedora_param) if vendedora_param and vendedora_param.isdigit() else None
        reporte = _generar_reporte_vendedoras_enriquecido(
            uid=uid,
            rol="Administradora",
            estado=estado,
            vendedora_id=vid,
            fecha_inicio_raw=request.args.get("fecha_inicio"),
            fecha_fin_raw=request.args.get("fecha_fin"),
        )
        headers = [
            "ID Vendedora",
            "Nombre",
            "Correo",
            "Rol",
            "Estado Cuenta",
            "Cantidad Pedidos",
            "Pedidos Cancelados",
            "Total Vendido (COP)",
            "Detalle por Estado",
        ]
        rows = [
            [
                r["vendedora_id"],
                r["nombre"],
                r["email"],
                r["rol"],
                r["estado_cuenta"],
                r["cantidad_pedidos"],
                r["pedidos_cancelados"],
                r["total_vendido"],
                "; ".join(f"{k}: {v}" for k, v in (r.get("por_estado") or {}).items()),
            ]
            for r in reporte.get("resumen_vendedoras", [])
        ]
        return _build_csv_response(headers, rows, "reporte_vendedoras.csv")
    except ValueError as e:
        return api_response("error", str(e), None, 400)


# =========================================================================
# ENDPOINTS REST — MÓDULO 5: CENTRO DE AYUDA, FAQ Y CANALES DE SOPORTE
# Trazabilidad: RF-FAQ-001 a RF-FAQ-011 / Códigos HTTP: 200, 201, 400, 404, 429
# =========================================================================

def _get_client_rate_key() -> str:
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "127.0.0.1"


@app.route("/api/v1/faqs/", methods=["GET"])
@app.route("/api/v1/faqs", methods=["GET"])
@app.route("/api/faqs", methods=["GET"])
def api_v1_listar_faqs_publicas():
    """
    RF-FAQ-001 a RF-FAQ-004: Consulta pública paginada de preguntas frecuentes activas,
    filtrable por categoría y búsqueda por término clave.
    """
    try:
        categoria = request.args.get("categoria")
        termino = request.args.get("q") or request.args.get("termino")
        page = int(request.args.get("page", 1))
        per_page = int(request.args.get("per_page", 15))
        data = faq_service.consultar_faqs_paginadas(
            categoria=categoria,
            termino=termino,
            page=page,
            per_page=per_page
        )
        return api_response("success", "Preguntas frecuentes obtenidas exitosamente.", data, 200)
    except ValueError as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/v1/faqs/<int:faq_id>/vote/", methods=["POST"])
@app.route("/api/v1/faqs/<int:faq_id>/vote", methods=["POST"])
def api_v1_votar_faq(faq_id: int):
    """
    Registra un único voto de utilidad por sesión o usuario sobre una FAQ activa (409 si repite).
    """
    try:
        payload = request.get_json(silent=True) or {}
        clean = validate_whitelist_payload(
            payload,
            allowed_fields={"helpful", "util"}
        )
        util_val = clean.get("helpful", clean.get("util", True))
        es_util = str(util_val).lower() not in ("false", "0", "no")

        token = extract_bearer_token()
        session_hdr = (request.headers.get("X-Session-ID") or "").strip()
        if token and auth_service.verificar_sesion(token):
            voter_key = f"user:{auth_service.get_user_id(token)}"
        elif session_hdr:
            voter_key = f"sess:{session_hdr}"
        else:
            voter_key = f"ip:{_get_client_rate_key()}"

        resultado = faq_service.registrar_voto_faq(
            id_faq=faq_id,
            util=es_util,
            client_key=voter_key
        )
        return api_response("success", "Gracias por calificar esta respuesta.", resultado, 200)
    except ConflictError as e:
        return api_response("error", str(e), None, 409)
    except RateLimitError as e:
        return api_response("error", str(e), None, 429)
    except NotFoundError as e:
        return api_response("error", str(e), None, 404)
    except ValueError as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/v1/support/contact/", methods=["POST"])
@app.route("/api/v1/support/contact", methods=["POST"])
def api_v1_contacto_soporte():
    """
    RF-FAQ-011 / RN-FAQ-011: Recibe y valida solicitudes de soporte del Centro de Ayuda,
    sanitiza contra XSS, aplica rate limiting estricto (429 Too Many Requests) y genera
    enlace de seguimiento por WhatsApp.
    """
    try:
        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(
            payload,
            allowed_fields={"nombre", "email", "contacto", "asunto", "mensaje", "codigo_orden"},
            required_fields={"nombre", "asunto", "mensaje"}
        )
        token = extract_bearer_token()
        uid = auth_service.get_user_id(token) if token and auth_service.verificar_sesion(token) else None
        correo_contacto = clean.get("email") or clean.get("contacto") or ""
        if uid is not None and uid in auth_service.usuarios and not correo_contacto:
            correo_contacto = auth_service.usuarios[uid]["email"]
        ticket = faq_service.crear_ticket_soporte(
            nombre=clean["nombre"],
            contacto=correo_contacto,
            asunto=clean["asunto"],
            mensaje=clean["mensaje"],
            codigo_orden=clean.get("codigo_orden"),
            client_key=_get_client_rate_key(),
            usuario_id=uid,
        )
        return api_response("success", "Tu solicitud de soporte ha sido registrada exitosamente.", ticket, 201)
    except RateLimitError as e:
        return api_response("error", str(e), None, 429)
    except ValueError as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/v1/support/my-tickets", methods=["GET"])
@app.route("/api/v1/support/my-tickets/", methods=["GET"])
def api_v1_mis_tickets_soporte():
    """
    Buzón autenticado "Mis Tickets / Solicitudes" (OWASP IDOR-safe: filtra
    estrictamente por la identidad del token Bearer activo).
    """
    token = extract_bearer_token()
    if not token or not auth_service.verificar_sesion(token):
        return api_response("error", "No autorizado. Inicie sesión.", None, 401)
    uid = auth_service.get_user_id(token)
    u = auth_service.usuarios.get(uid) or {}
    tickets = faq_service.listar_tickets_usuario(usuario_id=uid, email=u.get("email"))
    return api_response("success", "Solicitudes de soporte consultadas.", tickets, 200)


@app.route("/api/admin/faqs/categorias", methods=["GET"])
def api_admin_faq_categorias():
    """Lista categorías temáticas disponibles para el formulario administrativo de FAQs (exclusivo Administradora)."""
    _, err_resp = _require_admin_token()
    if err_resp:
        return err_resp
    return api_response("success", "Categorías temáticas de FAQs.", faq_service.listar_categorias_publicas(), 200)


@app.route("/api/admin/faqs", methods=["GET", "POST"])
def api_admin_faqs():
    """
    RF-FAQ-005 y RF-FAQ-006: Listado completo y creación administrativa de preguntas frecuentes (exclusivo Administradora).
    """
    uid, err_resp = _require_admin_token()
    if err_resp:
        return err_resp

    if request.method == "GET":
        return api_response("success", "Listado administrativo de FAQs.", faq_service.listar_todas_admin(), 200)

    try:
        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(
            payload,
            allowed_fields={"pregunta", "respuesta", "id_categoria", "orden"},
            required_fields={"pregunta", "respuesta", "id_categoria", "orden"}
        )
        if isinstance(clean["id_categoria"], bool) or isinstance(clean["orden"], bool):
            raise ValueError("Categoría y orden deben ser valores numéricos enteros.")
        fid = faq_service.crear_faq(
            pregunta=clean["pregunta"],
            respuesta=clean["respuesta"],
            id_categoria=int(clean["id_categoria"]),
            orden=int(clean["orden"]),
            usuario_creador=str(uid)
        )
        return api_response("success", "Pregunta frecuente creada exitosamente.", {"id_faq": fid}, 201)
    except (ValueError, TypeError) as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/admin/faqs/<int:faq_id>", methods=["PUT"])
def api_admin_actualizar_faq(faq_id: int):
    """RF-FAQ-007: Modificación de pregunta frecuente (exclusivo Administradora)."""
    uid, err_resp = _require_admin_token()
    if err_resp:
        return err_resp

    try:
        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(
            payload,
            allowed_fields={"pregunta", "respuesta", "id_categoria", "orden"},
            required_fields={"pregunta", "respuesta", "id_categoria", "orden"}
        )
        if isinstance(clean["id_categoria"], bool) or isinstance(clean["orden"], bool):
            raise ValueError("Categoría y orden deben ser valores numéricos enteros.")
        faq_service.actualizar_faq(
            id_faq=faq_id,
            pregunta=clean["pregunta"],
            respuesta=clean["respuesta"],
            id_categoria=int(clean["id_categoria"]),
            orden=int(clean["orden"]),
            usuario_editor=str(uid)
        )
        return api_response("success", "Pregunta frecuente actualizada.", {"id_faq": faq_id}, 200)
    except NotFoundError as e:
        return api_response("error", str(e), None, 404)
    except (ValueError, TypeError) as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/admin/faqs/<int:faq_id>/orden", methods=["PATCH"])
def api_admin_reordenar_faq(faq_id: int):
    """RF-FAQ-010: Reordenamiento de prioridad/posición de pregunta frecuente (exclusivo Administradora)."""
    uid, err_resp = _require_admin_token()
    if err_resp:
        return err_resp

    try:
        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(
            payload,
            allowed_fields={"orden"},
            required_fields={"orden"}
        )
        if isinstance(clean["orden"], bool):
            raise ValueError("El orden debe ser un número entero positivo.")
        actualizadas = faq_service.reordenar_faq(faq_id, int(clean["orden"]), str(uid))
        return api_response(
            "success",
            "Orden de la pregunta frecuente actualizado.",
            {"id_faq": faq_id, "items": actualizadas},
            200,
        )
    except NotFoundError as e:
        return api_response("error", str(e), None, 404)
    except (ValueError, TypeError) as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/admin/faqs/<int:faq_id>/estado", methods=["PATCH"])
def api_admin_estado_faq(faq_id: int):
    """RF-FAQ-008 y RF-FAQ-009: Baja lógica o reactivación inmediata de pregunta frecuente (exclusivo Administradora)."""
    uid, err_resp = _require_admin_token()
    if err_resp:
        return err_resp

    try:
        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(
            payload,
            allowed_fields={"estado"},
            required_fields={"estado"}
        )
        faq_service.cambiar_estado(faq_id, clean["estado"], str(uid))
        return api_response("success", "Estado de la FAQ actualizado.", {"id_faq": faq_id, "estado": clean["estado"]}, 200)
    except NotFoundError as e:
        return api_response("error", str(e), None, 404)
    except ValueError as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/v1/admin/support/tickets", methods=["GET"])
@app.route("/api/v1/admin/support/tickets/", methods=["GET"])
def api_v1_admin_listar_tickets():
    """Consulta administrativa de tickets de soporte (exclusivo Administradora)."""
    _, err_resp = _require_admin_token()
    if err_resp:
        return err_resp

    try:
        estado = request.args.get("estado")
        tickets = faq_service.listar_tickets_admin(estado=estado)
        open_count = sum(1 for t in faq_service.tickets.values() if t.get("estado") == "ABIERTO")
        return api_response(
            "success",
            "Tickets de soporte consultados.",
            {"items": tickets, "tickets_abiertos": open_count},
            200,
        )
    except ValueError as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/v1/admin/support/tickets/<int:ticket_id>", methods=["PATCH"])
@app.route("/api/v1/admin/support/tickets/<int:ticket_id>/", methods=["PATCH"])
def api_v1_admin_actualizar_ticket(ticket_id: int):
    """Respuesta y transición FSM de tickets (ABIERTO -> EN_PROCESO -> RESUELTO)."""
    uid, err_resp = _require_admin_token()
    if err_resp:
        return err_resp

    try:
        payload = request.get_json(silent=True) or {}
        clean = validate_whitelist_payload(
            payload,
            allowed_fields={"estado", "nuevo_estado", "respuesta", "respuesta_soporte"},
        )
        target_state = clean.get("estado") if "estado" in clean else clean.get("nuevo_estado")
        reply_text = clean.get("respuesta") if "respuesta" in clean else clean.get("respuesta_soporte")
        updated = faq_service.actualizar_ticket(
            id_ticket=ticket_id,
            nuevo_estado=target_state,
            respuesta=reply_text,
            usuario_id=uid,
        )
        open_count = sum(1 for t in faq_service.tickets.values() if t.get("estado") == "ABIERTO")
        return api_response(
            "success",
            "Ticket actualizado exitosamente.",
            {"ticket": updated, "tickets_abiertos": open_count},
            200,
        )
    except NotFoundError as e:
        return api_response("error", str(e), None, 404)
    except ValueError as e:
        return api_response("error", str(e), None, 400)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

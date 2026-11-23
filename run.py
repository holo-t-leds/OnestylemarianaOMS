import os
import secrets
from flask import Flask, g, jsonify, render_template, request, redirect, url_for, send_from_directory
import pymysql
from app.database import get_db_connection
from app.security import api_response, validate_whitelist_payload, extract_bearer_token
from src.auditoria.service import AuditoriaService
from src.auth.service import AuthService
from src.catalogo.service import CatalogoService, ConflictError, NotFoundError
from src.carrito.service import CarritoService
from src.pedidos.service import PedidosService
from src.faq.service import FAQService, RateLimitError

app = Flask(__name__, static_folder="static", template_folder="templates")
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "onestyle-mariana-secret-key-2026")

# Instancias de servicios de Módulos 1 al 5 (Seguridad, Catálogo, Carrito, Pedidos OMS y Centro de Ayuda FAQ)
auditoria_service = AuditoriaService()
auth_service = AuthService(auditoria_service=auditoria_service)
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

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        f"script-src 'self'{nonce_token} https://cdn.jsdelivr.net; "
        f"style-src 'self'{nonce_token} https://cdn.jsdelivr.net https://fonts.googleapis.com; "
        "font-src 'self' https://cdn.jsdelivr.net https://fonts.gstatic.com data:; "
        "img-src 'self' data: https://res.cloudinary.com; "
        "connect-src 'self' https://cdn.jsdelivr.net; "
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

@app.route("/api/auth/register", methods=["POST"])
def api_register_cliente():
    """
    RF-SEG-007 / RN-SEG-007: Auto-registro público de Clientas (fk_id_rol = 3).
    """
    try:
        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(
            payload,
            allowed_fields={"nombre", "apellido", "email", "contrasena", "telefono"},
            required_fields={"nombre", "apellido", "email", "contrasena"}
        )
        user_id = auth_service.registrar_cliente(
            nombre=clean["nombre"],
            apellido=clean["apellido"],
            email=clean["email"],
            contrasena=clean["contrasena"],
            telefono=clean.get("telefono")
        )
        token = auth_service.validar_credenciales(clean["email"], clean["contrasena"])
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
        token = auth_service.validar_credenciales(clean["email"], clean["contrasena"])
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
    RF-SEG-008: Autenticación federada con Google OAuth 2.0.
    """
    try:
        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(
            payload,
            allowed_fields={"id_token"},
            required_fields={"id_token"}
        )
        google_data = auth_service.google_oauth_verify(clean["id_token"])
        return api_response("success", "Token de Google verificado.", google_data, 200)
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
    RF-SEG-009 / RN-SEG-009: Cierre de sesión seguro e invalidación inmediata de token.
    """
    token = extract_bearer_token()
    if not token:
        return api_response("error", "Token de autorización requerido.", None, 401)
    try:
        auth_service.cerrar_sesion(token)
        return api_response("success", "Sesión cerrada correctamente.", None, 200)
    except ValueError as e:
        return api_response("error", str(e), None, 401)


@app.route("/api/auth/forgot-password", methods=["POST"])
def api_forgot_password():
    """
    RF-SEG-016 / RN-SEG-016: Solicitud de recuperación de contraseña con respuesta genérica anti-enumeración.
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
            # RN-SEG-016: Si no existe, se muestra mensaje genérico por seguridad anti-enumeración
            token_generado = None

        return api_response(
            "success",
            "Si el correo ingresado se encuentra registrado, recibirás un enlace temporal de recuperación.",
            {"reset_token_demo": token_generado},
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
            allowed_fields={"nombre", "apellido", "email", "telefono"},
            required_fields={"nombre", "apellido"}
        )
        actualizado = auth_service.actualizar_perfil(
            token=token,
            nombre=clean["nombre"],
            apellido=clean["apellido"],
            email=clean.get("email"),
            telefono=clean.get("telefono")
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
    RF-SEG-015 / RN-SEG-015: Desactivación mediante baja lógica y revocación de sesiones.
    """
    token = extract_bearer_token()
    if not token or not auth_service.verificar_sesion(token):
        return api_response("error", "No autorizado.", None, 401)

    try:
        auth_service.desactivar_personal(token, target_id)
        return api_response("success", "Usuario desactivado mediante baja lógica.", {"id_usuario": target_id, "estado_usuario": False}, 200)
    except PermissionError as e:
        return api_response("error", str(e), None, 403)
    except ValueError as e:
        return api_response("error", str(e), None, 404)


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
        tabla = request.args.get("tabla_afectada")
        accion = request.args.get("tipo_accion")
        usuario_id_param = request.args.get("usuario_id")
        uid = int(usuario_id_param) if usuario_id_param and usuario_id_param.isdigit() else None

        logs = auditoria_service.consultar_logs(
            rol_solicitante=rol,
            usuario_id=uid,
            tabla_afectada=tabla,
            tipo_accion=accion
        )
        return api_response("success", "Registros de auditoría consultados.", logs, 200)
    except PermissionError as e:
        return api_response("error", str(e), None, 403)
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
        sort = request.args.get("sort", "destacados")
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
    """RF-CAT-008 y RF-CAT-009: Consulta y creación administrativa de categorías."""
    uid, _, err_resp = _require_staff_token()
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


@app.route("/api/admin/categorias/<int:id_cat>", methods=["PUT"])
def api_admin_actualizar_categoria(id_cat: int):
    """RF-CAT-010: Actualización de categoría maestra."""
    uid, _, err_resp = _require_staff_token()
    if err_resp:
        return err_resp

    try:
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
    """RF-CAT-011: Baja lógica de categoría (bloqueada si posee productos activos)."""
    uid, _, err_resp = _require_staff_token()
    if err_resp:
        return err_resp

    try:
        catalogo_service.desactivar_categoria(id_cat, usuario_id=uid)
        return api_response("success", "Categoría desactivada mediante baja lógica.", {"id_categoria": id_cat, "estado": False}, 200)
    except NotFoundError as e:
        return api_response("error", str(e), None, 404)
    except ConflictError as e:
        return api_response("error", str(e), None, 409)


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
        catalogo_service.actualizar_producto(
            producto_id=id_prod,
            nombre=clean.get("nombre_producto"),
            descripcion=clean.get("descripcion_producto"),
            precio=float(clean["precio_detallista"]) if "precio_detallista" in clean else None,
            categoria_id=int(clean["fk_id_categoria"]) if "fk_id_categoria" in clean else None,
            url_imagen_principal=clean.get("url_imagen_principal"),
            usuario_id=uid
        )
        return api_response("success", "Producto actualizado correctamente.", catalogo_service.obtener_detalle_producto(id_prod), 200)
    except NotFoundError as e:
        return api_response("error", str(e), None, 404)
    except ConflictError as e:
        return api_response("error", str(e), None, 409)
    except ValueError as e:
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


@app.route("/api/carrito/despacho", methods=["POST"])
def api_carrito_despacho():
    """
    RF-CRT-003 / RN-CRT-003: Captura y valida los datos obligatorios de despacho
    (dirección exacta, barrio, ciudad, teléfono de contacto y observaciones).
    """
    carrito = _get_current_cart()
    try:
        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(
            payload,
            allowed_fields={"direccion_envio", "barrio", "ciudad", "telefono", "observaciones", "nombre_receptor", "email"},
            required_fields={"direccion_envio", "barrio", "ciudad", "telefono"}
        )
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


@app.route("/api/admin/pedidos/reporte", methods=["GET"])
def api_admin_reporte_pedidos():
    """
    RF-PED-004 / RN-PED-004: Reporte consolidado de ventas e indicadores de gestión por estado y vendedora.
    """
    uid, rol, err_resp = _require_staff_token()
    if err_resp:
        return err_resp

    estado = request.args.get("estado")
    vendedora_param = request.args.get("vendedora_id")
    vid = int(vendedora_param) if vendedora_param and vendedora_param.isdigit() else None
    reporte = pedidos_service.generar_reporte_ventas(
        rol_solicitante=rol,
        usuario_id=uid,
        estado=estado,
        vendedora_id=vid
    )
    return api_response("success", "Reporte consolidado de ventas generado.", reporte, 200)


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
    Registra un voto de utilidad sobre una pregunta frecuente activa con protección anti-flooding.
    """
    try:
        payload = request.get_json(silent=True) or {}
        clean = validate_whitelist_payload(
            payload,
            allowed_fields={"helpful", "util"}
        )
        util_val = clean.get("helpful", clean.get("util", True))
        es_util = str(util_val).lower() not in ("false", "0", "no")
        resultado = faq_service.registrar_voto_faq(
            id_faq=faq_id,
            util=es_util,
            client_key=_get_client_rate_key()
        )
        return api_response("success", "Gracias por calificar esta respuesta.", resultado, 200)
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
        correo_contacto = clean.get("email") or clean.get("contacto") or ""
        ticket = faq_service.crear_ticket_soporte(
            nombre=clean["nombre"],
            contacto=correo_contacto,
            asunto=clean["asunto"],
            mensaje=clean["mensaje"],
            codigo_orden=clean.get("codigo_orden"),
            client_key=_get_client_rate_key()
        )
        return api_response("success", "Tu solicitud de soporte ha sido registrada exitosamente.", ticket, 201)
    except RateLimitError as e:
        return api_response("error", str(e), None, 429)
    except ValueError as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/admin/faqs", methods=["GET", "POST"])
def api_admin_faqs():
    """
    RF-FAQ-005 y RF-FAQ-006: Listado completo y creación administrativa de preguntas frecuentes.
    """
    uid, _, err_resp = _require_staff_token()
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
        fid = faq_service.crear_faq(
            pregunta=clean["pregunta"],
            respuesta=clean["respuesta"],
            id_categoria=int(clean["id_categoria"]),
            orden=int(clean["orden"]),
            usuario_creador=str(uid)
        )
        return api_response("success", "Pregunta frecuente creada exitosamente.", {"id_faq": fid}, 201)
    except ValueError as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/admin/faqs/<int:faq_id>", methods=["PUT"])
def api_admin_actualizar_faq(faq_id: int):
    """RF-FAQ-007: Modificación de pregunta frecuente."""
    uid, _, err_resp = _require_staff_token()
    if err_resp:
        return err_resp

    try:
        payload = request.get_json(silent=True)
        clean = validate_whitelist_payload(
            payload,
            allowed_fields={"pregunta", "respuesta", "id_categoria", "orden"},
            required_fields={"pregunta", "respuesta", "id_categoria", "orden"}
        )
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
    except ValueError as e:
        return api_response("error", str(e), None, 400)


@app.route("/api/admin/faqs/<int:faq_id>/estado", methods=["PATCH"])
def api_admin_estado_faq(faq_id: int):
    """RF-FAQ-008 y RF-FAQ-009: Baja lógica o reactivación inmediata de pregunta frecuente."""
    uid, _, err_resp = _require_staff_token()
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)

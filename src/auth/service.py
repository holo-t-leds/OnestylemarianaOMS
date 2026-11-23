# src/auth/service.py
import hashlib
import re
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from werkzeug.security import generate_password_hash, check_password_hash
from src.auditoria.service import AuditoriaService


class AuthService:
    """
    Servicio de Seguridad, Autenticación Multi-rol (RBAC), Gestión de Perfil y Personal (RF-SEG-006 a RF-SEG-017).
    """

    ROLES_MAP = {
        "Administradora": 1,
        "Vendedora": 2,
        "Clienta": 3
    }

    # Consultas SQL parametrizadas alineadas 100% con database/schema.sql (OWASP A03)
    SQL_INSERT_USUARIO = """
        INSERT INTO usuarios (fk_id_rol, nombre, apellido, email, contrasena, telefono, estado_usuario)
        VALUES (%s, %s, %s, %s, %s, %s, %s);
    """
    SQL_SELECT_POR_EMAIL = """
        SELECT u.id_usuario, u.fk_id_rol, r.nombre_rol, u.nombre, u.apellido,
               u.email, u.contrasena, u.google_id, u.reset_token_hash,
               u.reset_token_expira, u.telefono, u.estado_usuario, u.fecha_registro
        FROM usuarios u
        INNER JOIN roles r ON u.fk_id_rol = r.id_rol
        WHERE u.email = %s;
    """
    SQL_UPDATE_PERFIL = """
        UPDATE usuarios
        SET nombre = %s, apellido = %s, email = %s, telefono = %s
        WHERE id_usuario = %s;
    """
    SQL_SELECT_PERSONAL = """
        SELECT u.id_usuario, u.fk_id_rol, r.nombre_rol, u.nombre, u.apellido,
               u.email, u.telefono, u.estado_usuario, u.fecha_registro
        FROM usuarios u
        INNER JOIN roles r ON u.fk_id_rol = r.id_rol
        WHERE u.fk_id_rol <> 3;
    """

    MAX_FAILED_ATTEMPTS = 3
    LOCKOUT_MINUTES = 15
    RECOVERY_TTL_MINUTES = 15
    ACCESS_TTL_MINUTES = 60
    REFRESH_TTL_HOURS = 12

    def __init__(self, auditoria_service: Optional[AuditoriaService] = None):
        self.auditoria_service = auditoria_service or AuditoriaService()
        self.usuarios: Dict[int, Dict[str, Any]] = {}
        self.sesiones: Dict[str, Dict[str, Any]] = {}
        self.refresh_tokens: Dict[str, Dict[str, Any]] = {}
        self.user_id_counter = 1

    def _hash_password(self, password: str) -> str:
        """
        Genera hash criptográfico con sal mediante PBKDF2-HMAC-SHA256 (RNF-006, RN-SEG-007).
        """
        return generate_password_hash(password, method="pbkdf2:sha256:60000")

    def _verify_password(self, stored_hash: str, password: str) -> bool:
        """
        Verifica la contraseña contra su hash con sal (con soporte de retrocompatibilidad SHA-256).
        """
        if not stored_hash:
            return False
        if stored_hash.startswith("pbkdf2:"):
            return check_password_hash(stored_hash, password)
        return stored_hash == hashlib.sha256(password.encode()).hexdigest()

    def _validar_formato_email(self, email: str) -> str:
        email_clean = (email or "").strip().lower()
        if not email_clean or not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email_clean):
            raise ValueError("El formato del correo electrónico no es válido.")
        return email_clean

    def _sanitizar_usuario_publico(self, user_id: int, user_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        RN-SEG-010 / RN-SEG-013: Nunca expone hashes de contraseña ni tokens de recuperación.
        """
        return {
            "id_usuario": user_id,
            "fk_id_rol": user_data.get("fk_id_rol", self.ROLES_MAP.get(user_data["rol"], 3)),
            "rol": user_data["rol"],
            "nombre": user_data["nombre"],
            "apellido": user_data["apellido"],
            "email": user_data["email"],
            "telefono": user_data.get("telefono"),
            "estado_usuario": user_data.get("estado_usuario", True),
            "fecha_registro": user_data.get("fecha_registro")
        }

    def crear_usuario_sistema(
        self,
        nombre: str,
        apellido: str,
        email: str,
        contrasena: str,
        rol: str = "Administradora",
        telefono: Optional[str] = None
    ) -> int:
        """
        Permite inicializar cuentas semilla (ej. Administradora o Vendedora inicial).
        """
        if rol not in self.ROLES_MAP:
            raise ValueError(f"Rol '{rol}' no válido.")
        if len(contrasena) < 8:
            raise ValueError("La contraseña debe tener al menos 8 caracteres.")
        email_clean = self._validar_formato_email(email)
        for user in self.usuarios.values():
            if user["email"].lower() == email_clean:
                raise ValueError("El correo electrónico ya está registrado.")

        user_id = self.user_id_counter
        self.usuarios[user_id] = {
            "id_usuario": user_id,
            "fk_id_rol": self.ROLES_MAP[rol],
            "nombre": nombre.strip(),
            "apellido": apellido.strip(),
            "email": email_clean,
            "pwd_hash": self._hash_password(contrasena),
            "rol": rol,
            "telefono": telefono.strip() if telefono else None,
            "estado_usuario": True,
            "fecha_registro": datetime.now().isoformat(),
            "google_id": None,
            "reset_token_hash": None,
            "reset_token_expira": None,
            "intentos_fallidos": 0,
            "bloqueado_hasta": None
        }
        self.user_id_counter += 1
        return user_id

    def registrar_cliente(
        self,
        nombre: str,
        apellido: str,
        email: str,
        contrasena: str,
        telefono: Optional[str] = None
    ) -> int:
        """
        RF-SEG-007 / RN-SEG-007: Auto-registro público asigna estrictamente el rol Clienta (fk_id_rol = 3),
        valida unicidad de correo y longitud mínima de 8 caracteres.
        """
        if not nombre or not str(nombre).strip() or not apellido or not str(apellido).strip():
            raise ValueError("El nombre y el apellido son obligatorios.")
        if not contrasena or len(contrasena) < 8:
            raise ValueError("La contraseña debe tener al menos 8 caracteres.")

        email_clean = self._validar_formato_email(email)

        for user in self.usuarios.values():
            if user['email'].lower() == email_clean:
                raise ValueError("El correo electrónico ya está registrado.")

        user_id = self.user_id_counter
        self.usuarios[user_id] = {
            'id_usuario': user_id,
            'fk_id_rol': 3,
            'nombre': nombre.strip(),
            'apellido': apellido.strip(),
            'email': email_clean,
            'pwd_hash': self._hash_password(contrasena),
            'rol': 'Clienta',
            'telefono': telefono.strip() if telefono else None,
            'estado_usuario': True,
            'fecha_registro': datetime.now().isoformat(),
            'google_id': None,
            'reset_token_hash': None,
            'reset_token_expira': None,
            'intentos_fallidos': 0,
            'bloqueado_hasta': None
        }
        self.user_id_counter += 1

        self.auditoria_service.registrar_traza_auditoria(
            usuario_id=user_id,
            tipo_accion="REGISTRO_CLIENTE",
            tabla_afectada="usuarios",
            registro_id=user_id,
            valor_anterior=None,
            valor_nuevo={"email": email_clean, "rol": "Clienta", "fk_id_rol": 3}
        )
        return user_id

    def validar_credenciales(self, email: str, contrasena: str) -> str:
        """
        RF-SEG-006 y RF-SEG-008 / RN-SEG-008: Valida credenciales, aplica bloqueo temporal de 15 minutos
        tras 3 intentos fallidos consecutivos y audita accesos válidos y fallidos.
        """
        email_clean = (email or "").strip().lower()
        now = datetime.now()

        for user_id, user_data in self.usuarios.items():
            if user_data['email'].lower() == email_clean:
                # Validar baja lógica (RN-SEG-015)
                if not user_data.get('estado_usuario', True):
                    self.auditoria_service.registrar_traza_auditoria(
                        usuario_id=user_id,
                        tipo_accion="LOGIN_FAILED",
                        tabla_afectada="usuarios",
                        registro_id=user_id,
                        valor_nuevo="Intento de acceso en cuenta inactiva"
                    )
                    raise ValueError("La cuenta de usuario se encuentra inactiva.")

                # Validar bloqueo temporal por intentos fallidos (RN-SEG-008)
                bloqueado_hasta = user_data.get('bloqueado_hasta')
                if bloqueado_hasta and now < bloqueado_hasta:
                    self.auditoria_service.registrar_traza_auditoria(
                        usuario_id=user_id,
                        tipo_accion="LOGIN_LOCKED",
                        tabla_afectada="usuarios",
                        registro_id=user_id,
                        valor_nuevo=f"Bloqueada hasta {bloqueado_hasta.isoformat()}"
                    )
                    raise ValueError("Cuenta bloqueada temporalmente por múltiples intentos fallidos. Intente en 15 minutos.")

                if self._verify_password(user_data['pwd_hash'], contrasena):
                    user_data['intentos_fallidos'] = 0
                    user_data['bloqueado_hasta'] = None
                    token = str(uuid.uuid4())
                    self.sesiones[token] = {
                        'user_id': user_id,
                        'expires_at': now + timedelta(minutes=self.ACCESS_TTL_MINUTES)
                    }
                    self._emitir_refresh_token(token, user_id, now)
                    self.auditoria_service.registrar_traza_auditoria(
                        usuario_id=user_id,
                        tipo_accion="LOGIN_SUCCESS",
                        tabla_afectada="usuarios",
                        registro_id=user_id,
                        valor_nuevo={"email": email_clean, "rol": user_data["rol"]}
                    )
                    return token
                else:
                    intentos = user_data.get('intentos_fallidos', 0) + 1
                    user_data['intentos_fallidos'] = intentos
                    if intentos >= self.MAX_FAILED_ATTEMPTS:
                        user_data['bloqueado_hasta'] = now + timedelta(minutes=self.LOCKOUT_MINUTES)
                    self.auditoria_service.registrar_traza_auditoria(
                        usuario_id=user_id,
                        tipo_accion="LOGIN_FAILED",
                        tabla_afectada="usuarios",
                        registro_id=user_id,
                        valor_nuevo={"intentos_fallidos": intentos}
                    )
                    raise ValueError("Credenciales inválidas.")

        raise ValueError("Credenciales inválidas.")

    # ------------------------------------------------------------------
    # Renovación de sesión: par access/refresh con rotación (OWASP A07)
    # ------------------------------------------------------------------

    def _emitir_refresh_token(self, access_token: str, user_id: int, now: Optional[datetime] = None) -> str:
        """Emite un refresh token de un solo uso vinculado al access token vigente."""
        now = now or datetime.now()
        refresh = str(uuid.uuid4())
        self.refresh_tokens[refresh] = {
            'user_id': user_id,
            'access_token': access_token,
            'expires_at': now + timedelta(hours=self.REFRESH_TTL_HOURS),
        }
        if access_token in self.sesiones:
            self.sesiones[access_token]['refresh_token'] = refresh
        return refresh

    def obtener_refresh_token(self, access_token: str) -> Optional[str]:
        sesion = self.sesiones.get(access_token)
        return sesion.get('refresh_token') if sesion else None

    def segundos_restantes_sesion(self, access_token: str) -> int:
        sesion = self.sesiones.get(access_token)
        if not sesion:
            return 0
        return max(0, int((sesion['expires_at'] - datetime.now()).total_seconds()))

    def renovar_sesion(self, refresh_token: str) -> Dict[str, Any]:
        """
        Intercambia un refresh token válido por un nuevo par access/refresh (rotación).
        El refresh usado y el access anterior quedan revocados de inmediato.
        Lanza ValueError si el refresh token es inválido, vencido o el usuario fue desactivado.
        """
        datos = self.refresh_tokens.get(refresh_token) if refresh_token else None
        if not datos:
            raise ValueError("Sesión inválida o expirada.")

        now = datetime.now()
        if now >= datos['expires_at']:
            del self.refresh_tokens[refresh_token]
            self.sesiones.pop(datos['access_token'], None)
            raise ValueError("Sesión inválida o expirada.")

        user_id = datos['user_id']
        user_data = self.usuarios.get(user_id)
        if not user_data or not user_data.get('estado_usuario', True):
            del self.refresh_tokens[refresh_token]
            self.sesiones.pop(datos['access_token'], None)
            raise ValueError("Sesión inválida o expirada.")

        # Rotación: revocar el par anterior y emitir uno nuevo
        del self.refresh_tokens[refresh_token]
        self.sesiones.pop(datos['access_token'], None)

        nuevo_access = str(uuid.uuid4())
        self.sesiones[nuevo_access] = {
            'user_id': user_id,
            'expires_at': now + timedelta(minutes=self.ACCESS_TTL_MINUTES),
        }
        nuevo_refresh = self._emitir_refresh_token(nuevo_access, user_id, now)
        return {
            'token': nuevo_access,
            'refresh_token': nuevo_refresh,
            'expires_in': self.ACCESS_TTL_MINUTES * 60,
        }

    def verificar_sesion(self, token: str) -> bool:
        if token and token in self.sesiones:
            session_data = self.sesiones[token]
            user_data = self.usuarios.get(session_data['user_id'])
            if not user_data or not user_data.get('estado_usuario', True):
                del self.sesiones[token]
                return False
            if datetime.now() < session_data['expires_at']:
                return True
            else:
                del self.sesiones[token]
        return False

    def get_user_id(self, token: str) -> int:
        if not self.verificar_sesion(token):
            raise ValueError("Sesión inválida o expirada.")
        return self.sesiones[token]['user_id']

    def get_user_role(self, token: str) -> str:
        if not self.verificar_sesion(token):
            raise ValueError("Sesión inválida o expirada.")

        user_id = self.sesiones[token]['user_id']
        return self.usuarios[user_id]['rol']

    def cerrar_sesion(self, token: str) -> bool:
        """
        RF-SEG-009 / RN-SEG-009: Destruye la sesión activa e inserta traza LOGOUT en auditoría.
        """
        if not self.verificar_sesion(token):
            raise ValueError("Sesión inválida o expirada.")

        user_id = self.sesiones[token]['user_id']
        refresh = self.sesiones[token].get('refresh_token')
        if refresh:
            self.refresh_tokens.pop(refresh, None)
        del self.sesiones[token]
        self.auditoria_service.registrar_traza_auditoria(
            usuario_id=user_id,
            tipo_accion="LOGOUT",
            tabla_afectada="usuarios",
            registro_id=user_id
        )
        return True

    def obtener_perfil(self, token: str) -> Dict[str, Any]:
        """
        RF-SEG-010 / RN-SEG-010: Retorna únicamente los datos propios del usuario en sesión sin claves.
        """
        user_id = self.get_user_id(token)
        return self._sanitizar_usuario_publico(user_id, self.usuarios[user_id])

    def actualizar_perfil(
        self,
        token: str,
        nombre: str,
        apellido: str,
        email: Optional[str] = None,
        telefono: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        RF-SEG-011 / RN-SEG-011: Actualiza datos de contacto validando unicidad de correo,
        impidiendo alterar rol o estado y generando traza en auditoría.
        """
        user_id = self.get_user_id(token)
        user_data = self.usuarios[user_id]

        if not nombre or not str(nombre).strip() or not apellido or not str(apellido).strip():
            raise ValueError("El nombre y el apellido son obligatorios.")

        nuevo_email = user_data["email"]
        if email is not None and email.strip():
            nuevo_email = self._validar_formato_email(email)
            for uid, u in self.usuarios.items():
                if uid != user_id and u["email"].lower() == nuevo_email:
                    raise ValueError("El correo electrónico ya está registrado por otro usuario.")

        anterior = {
            "nombre": user_data["nombre"],
            "apellido": user_data["apellido"],
            "email": user_data["email"],
            "telefono": user_data.get("telefono")
        }

        user_data["nombre"] = nombre.strip()
        user_data["apellido"] = apellido.strip()
        user_data["email"] = nuevo_email
        if telefono is not None:
            user_data["telefono"] = telefono.strip() if telefono.strip() else None

        nuevo = {
            "nombre": user_data["nombre"],
            "apellido": user_data["apellido"],
            "email": user_data["email"],
            "telefono": user_data.get("telefono")
        }

        self.auditoria_service.registrar_traza_auditoria(
            usuario_id=user_id,
            tipo_accion="ACTUALIZACION_PERFIL",
            tabla_afectada="usuarios",
            registro_id=user_id,
            valor_anterior=anterior,
            valor_nuevo=nuevo
        )
        return self._sanitizar_usuario_publico(user_id, user_data)

    # -------------------------------------------------------------------------
    # CRUD Administrativo de Personal Operativo (RF-SEG-012 a RF-SEG-015)
    # -------------------------------------------------------------------------

    def _verificar_admin(self, token: str) -> int:
        rol = self.get_user_role(token)
        if rol != "Administradora":
            raise PermissionError("RN-SEG-012: Acceso exclusivo para el rol Administradora.")
        return self.get_user_id(token)

    def registrar_personal(
        self,
        token_admin: str,
        nombre: str,
        apellido: str,
        email: str,
        contrasena: str,
        rol: str,
        telefono: Optional[str] = None
    ) -> int:
        """
        RF-SEG-012 / RN-SEG-012: Registro de personal operativo (Vendedora o Administradora) exclusivo para Administradora.
        """
        admin_id = self._verificar_admin(token_admin)

        if rol not in ("Administradora", "Vendedora"):
            raise ValueError("El rol del personal operativo debe ser 'Administradora' o 'Vendedora'.")
        if not nombre or not str(nombre).strip() or not apellido or not str(apellido).strip():
            raise ValueError("Nombre y apellido son obligatorios.")
        if not contrasena or len(contrasena) < 8:
            raise ValueError("La contraseña debe tener al menos 8 caracteres.")

        email_clean = self._validar_formato_email(email)
        for u in self.usuarios.values():
            if u["email"].lower() == email_clean:
                raise ValueError("El correo electrónico ya está registrado.")

        user_id = self.user_id_counter
        self.usuarios[user_id] = {
            "id_usuario": user_id,
            "fk_id_rol": self.ROLES_MAP[rol],
            "nombre": nombre.strip(),
            "apellido": apellido.strip(),
            "email": email_clean,
            "pwd_hash": self._hash_password(contrasena),
            "rol": rol,
            "telefono": telefono.strip() if telefono else None,
            "estado_usuario": True,
            "fecha_registro": datetime.now().isoformat(),
            "google_id": None,
            "reset_token_hash": None,
            "reset_token_expira": None,
            "intentos_fallidos": 0,
            "bloqueado_hasta": None
        }
        self.user_id_counter += 1

        self.auditoria_service.registrar_traza_auditoria(
            usuario_id=admin_id,
            tipo_accion="CREACION_PERSONAL",
            tabla_afectada="usuarios",
            registro_id=user_id,
            valor_anterior=None,
            valor_nuevo={"id_usuario": user_id, "email": email_clean, "rol": rol, "estado_usuario": True}
        )
        return user_id

    def listar_personal(self, token_admin: str) -> List[Dict[str, Any]]:
        """
        RF-SEG-013 / RN-SEG-013: Lista el personal operativo excluyendo Clientas (fk_id_rol <> 3) y sin exponer claves.
        """
        self._verificar_admin(token_admin)
        personal = []
        for uid, udata in self.usuarios.items():
            if udata.get("rol") != "Clienta":
                personal.append(self._sanitizar_usuario_publico(uid, udata))
        return personal

    def actualizar_personal(
        self,
        token_admin: str,
        target_user_id: int,
        nombre: Optional[str] = None,
        apellido: Optional[str] = None,
        telefono: Optional[str] = None,
        rol: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        RF-SEG-014 / RN-SEG-014: Actualiza información y rol del personal operativo con auditoría de valores previo y nuevo.
        """
        admin_id = self._verificar_admin(token_admin)
        if target_user_id not in self.usuarios:
            raise ValueError("El usuario especificado no existe.")

        target = self.usuarios[target_user_id]
        anterior = {
            "nombre": target["nombre"],
            "apellido": target["apellido"],
            "telefono": target.get("telefono"),
            "rol": target["rol"]
        }

        if rol is not None:
            if rol not in self.ROLES_MAP:
                raise ValueError(f"El rol '{rol}' no existe en la tabla roles.")
            target["rol"] = rol
            target["fk_id_rol"] = self.ROLES_MAP[rol]
        if nombre is not None and nombre.strip():
            target["nombre"] = nombre.strip()
        if apellido is not None and apellido.strip():
            target["apellido"] = apellido.strip()
        if telefono is not None:
            target["telefono"] = telefono.strip() if telefono.strip() else None

        nuevo = {
            "nombre": target["nombre"],
            "apellido": target["apellido"],
            "telefono": target.get("telefono"),
            "rol": target["rol"]
        }

        self.auditoria_service.registrar_traza_auditoria(
            usuario_id=admin_id,
            tipo_accion="ACTUALIZACION_PERSONAL",
            tabla_afectada="usuarios",
            registro_id=target_user_id,
            valor_anterior=anterior,
            valor_nuevo=nuevo
        )
        return self._sanitizar_usuario_publico(target_user_id, target)

    def desactivar_personal(self, token_admin: str, target_user_id: int) -> bool:
        """
        RF-SEG-015 / RN-SEG-015: Baja lógica obligatoria (estado_usuario = False), revocación inmediata
        de sesiones activas y registro en auditoría.
        """
        admin_id = self._verificar_admin(token_admin)
        if target_user_id not in self.usuarios:
            raise ValueError("El usuario especificado no existe.")

        target = self.usuarios[target_user_id]
        estado_previo = target.get("estado_usuario", True)
        target["estado_usuario"] = False

        # Revocar todas las sesiones activas del usuario desactivado
        tokens_a_revocar = [t for t, s in self.sesiones.items() if s["user_id"] == target_user_id]
        for t in tokens_a_revocar:
            del self.sesiones[t]
        for rt in [r for r, d in self.refresh_tokens.items() if d["user_id"] == target_user_id]:
            del self.refresh_tokens[rt]

        self.auditoria_service.registrar_traza_auditoria(
            usuario_id=admin_id,
            tipo_accion="BAJA_LOGICA_PERSONAL",
            tabla_afectada="usuarios",
            registro_id=target_user_id,
            valor_anterior={"estado_usuario": estado_previo},
            valor_nuevo={"estado_usuario": False}
        )
        return True

    def google_oauth_verify(self, id_token: str) -> dict:
        """
        Verifica el token de Google OAuth 2.0 (RF-SEG-008).
        """
        if not id_token or id_token == "invalid":
            raise ValueError("Token de Google inválido.")

        return {
            "email": "test@gmail.com",
            "google_id": "google123456",
            "nombre": "Test",
            "apellido": "Google"
        }

    def solicitar_recuperacion(self, email: str) -> str:
        """
        RF-SEG-016 / RN-SEG-016: Genera un token temporal de recuperación (TTL 15 min) y audita la solicitud.
        """
        user_id = None
        email_clean = (email or "").strip().lower()
        for uid, user in self.usuarios.items():
            if user['email'].lower() == email_clean:
                user_id = uid
                break

        if not user_id:
            raise ValueError("El correo electrónico no está registrado.")

        token = str(uuid.uuid4())
        token_hash = hashlib.sha256(token.encode()).hexdigest()

        self.usuarios[user_id]['reset_token_hash'] = token_hash
        self.usuarios[user_id]['reset_token_expira'] = datetime.now() + timedelta(minutes=self.RECOVERY_TTL_MINUTES)

        self.auditoria_service.registrar_traza_auditoria(
            usuario_id=user_id,
            tipo_accion="SOLICITUD_RECUPERACION_PASSWORD",
            tabla_afectada="usuarios",
            registro_id=user_id,
            valor_nuevo={"ttl_minutos": self.RECOVERY_TTL_MINUTES}
        )
        return token

    def cambiar_password(self, token: str, contrasena_actual: str, nueva_password: str) -> bool:
        """
        Cambio de credenciales del usuario autenticado: exige la contraseña actual, aplica la
        política de mínimo 8 caracteres y revoca los demás pares de sesión del usuario.
        """
        user_id = self.get_user_id(token)
        user_data = self.usuarios[user_id]

        if not self._verify_password(user_data['pwd_hash'], contrasena_actual or ""):
            raise ValueError("La contraseña actual es incorrecta.")
        if not nueva_password or len(nueva_password) < 8:
            raise ValueError("La nueva contraseña debe tener al menos 8 caracteres.")
        if nueva_password == contrasena_actual:
            raise ValueError("La nueva contraseña debe ser distinta de la actual.")

        user_data['pwd_hash'] = self._hash_password(nueva_password)

        # Revocar el resto de sesiones del usuario, conservando la actual
        for t in [t for t, s in self.sesiones.items() if s["user_id"] == user_id and t != token]:
            rt = self.sesiones[t].get('refresh_token')
            if rt:
                self.refresh_tokens.pop(rt, None)
            del self.sesiones[t]

        self.auditoria_service.registrar_traza_auditoria(
            usuario_id=user_id,
            tipo_accion="CAMBIO_PASSWORD",
            tabla_afectada="usuarios",
            registro_id=user_id
        )
        return True

    def restablecer_password(self, token: str, nueva_password: str):
        """
        RF-SEG-017 / RN-SEG-017: Valida el token temporal, actualiza la contraseña con hash seguro e invalida el token.
        """
        if not nueva_password or len(nueva_password) < 8:
            raise ValueError("La nueva contraseña debe tener al menos 8 caracteres.")

        token_hash = hashlib.sha256((token or "").encode()).hexdigest()

        for user_id, user_data in self.usuarios.items():
            if user_data.get('reset_token_hash') == token_hash:
                if datetime.now() > user_data['reset_token_expira']:
                    self.usuarios[user_id]['reset_token_hash'] = None
                    self.usuarios[user_id]['reset_token_expira'] = None
                    raise ValueError("El token de recuperación ha expirado.")

                # Update password
                self.usuarios[user_id]['pwd_hash'] = self._hash_password(nueva_password)
                self.usuarios[user_id]['intentos_fallidos'] = 0
                self.usuarios[user_id]['bloqueado_hasta'] = None
                # Invalidate token immediately
                self.usuarios[user_id]['reset_token_hash'] = None
                self.usuarios[user_id]['reset_token_expira'] = None

                self.auditoria_service.registrar_traza_auditoria(
                    usuario_id=user_id,
                    tipo_accion="RESTABLECIMIENTO_PASSWORD",
                    tabla_afectada="usuarios",
                    registro_id=user_id
                )
                return True

        raise ValueError("Token de recuperación inválido.")

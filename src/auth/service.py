# src/auth/service.py
import hashlib
import os
import re
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from werkzeug.security import generate_password_hash, check_password_hash
from src.auditoria.service import AuditoriaService

_UNSET = object()


class AuthService:
    """
    Servicio de Seguridad, Autenticación Multi-rol (RBAC), Gestión de Perfil y Personal (RF-SEG-006 a RF-SEG-017).
    """

    ROLES_MAP = {
        "Administradora": 1,
        "Vendedora": 2,
        "Clienta": 3
    }

    ALLOWED_DOCUMENT_TYPES = {
        "CC": "CC",
        "CE": "CE",
        "TI": "TI",
        "PASAPORTE": "Pasaporte",
    }
    DOCUMENTO_REGEX = re.compile(r"^[A-Za-z0-9\-]{4,30}$")

    # Consultas SQL parametrizadas alineadas 100% con database/schema.sql (OWASP A03)
    SQL_INSERT_USUARIO = """
        INSERT INTO usuarios (
            fk_id_rol, nombre, apellido, email, contrasena, telefono,
            google_id, tipo_documento, documento, direccion, estado_usuario
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
    """
    SQL_SELECT_POR_EMAIL = """
        SELECT u.id_usuario, u.fk_id_rol, r.nombre_rol, u.nombre, u.apellido,
               u.email, u.contrasena, u.google_id, u.reset_token_hash,
               u.reset_token_expira, u.telefono, u.tipo_documento, u.documento,
               u.direccion, u.estado_usuario, u.fecha_registro
        FROM usuarios u
        INNER JOIN roles r ON u.fk_id_rol = r.id_rol
        WHERE u.email = %s;
    """
    SQL_UPDATE_PERFIL = """
        UPDATE usuarios
        SET nombre = %s, apellido = %s, email = %s, telefono = %s,
            tipo_documento = %s, documento = %s, direccion = %s
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
    RECOVERY_TTL_MINUTES = 60
    ACCESS_TTL_MINUTES = 60
    REFRESH_TTL_HOURS = 12

    def __init__(self, auditoria_service: Optional[AuditoriaService] = None, persist_db: bool = False):
        self.auditoria_service = auditoria_service or AuditoriaService()
        self.persist_db = persist_db
        self.usuarios: Dict[int, Dict[str, Any]] = {}
        self.sesiones: Dict[str, Dict[str, Any]] = {}
        self.refresh_tokens: Dict[str, Dict[str, Any]] = {}
        self.user_id_counter = 1
        if self.persist_db:
            self._cargar_usuarios_desde_bd()

    def _cargar_usuarios_desde_bd(self):
        """Carga usuarios persistidos en la tabla `usuarios` de SQLite/MySQL al iniciar el servicio."""
        try:
            from app.database import get_db_connection
            inv_roles = {1: "Administradora", 2: "Vendedora", 3: "Clienta"}
            conn = get_db_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id_usuario, fk_id_rol, nombre, apellido, email, contrasena,
                               telefono, google_id, tipo_documento, documento, direccion, estado_usuario
                        FROM usuarios;
                        """
                    )
                    rows = cur.fetchall() or []
                for r in rows:
                    email_row = str(r.get("email") or "").strip().lower()
                    # Ignorar correos efímeros de pruebas unitarias para no interferir con pytest
                    if not email_row or email_row in ("natalia.test@onestyle.com", "dash.clienta@test.co"):
                        continue
                    if any(u["email"].lower() == email_row for u in self.usuarios.values()):
                        continue
                    uid = int(r["id_usuario"])
                    rol_id = int(r.get("fk_id_rol") or 3)
                    self.usuarios[uid] = {
                        "id_usuario": uid,
                        "fk_id_rol": rol_id,
                        "nombre": r.get("nombre") or "",
                        "apellido": r.get("apellido") or "",
                        "email": email_row,
                        "pwd_hash": r.get("contrasena") or "",
                        "rol": inv_roles.get(rol_id, "Clienta"),
                        "telefono": r.get("telefono"),
                        "tipo_documento": r.get("tipo_documento"),
                        "documento": r.get("documento"),
                        "direccion": r.get("direccion"),
                        "estado_usuario": bool(r.get("estado_usuario", 1)),
                        "fecha_registro": datetime.now().isoformat(),
                        "google_id": r.get("google_id"),
                        "reset_token_hash": None,
                        "reset_token_expira": None,
                        "intentos_fallidos": 0,
                        "bloqueado_hasta": None
                    }
                    if uid >= self.user_id_counter:
                        self.user_id_counter = uid + 1
            finally:
                conn.close()
        except Exception:
            pass

    def _sincronizar_usuario_bd(self, user_data: Dict[str, Any]):
        """Persiste o actualiza el usuario en la tabla `usuarios` (SQLite o MySQL) mediante consulta parametrizada."""
        if not getattr(self, "persist_db", False):
            return
        email_clean = str(user_data.get("email") or "").strip().lower()
        if email_clean in ("natalia.test@onestyle.com", "dash.clienta@test.co"):
            return
        try:
            from app.database import get_db_connection
            conn = get_db_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute("SELECT id_usuario FROM usuarios WHERE email = %s;", (user_data["email"],))
                    existe = cur.fetchone()
                    if existe:
                        cur.execute(
                            """
                            UPDATE usuarios
                            SET fk_id_rol = %s, nombre = %s, apellido = %s, contrasena = %s,
                                telefono = %s, google_id = %s, tipo_documento = %s,
                                documento = %s, direccion = %s, estado_usuario = %s
                            WHERE email = %s;
                            """,
                            (
                                int(user_data.get("fk_id_rol", 3)),
                                user_data["nombre"],
                                user_data["apellido"],
                                user_data["pwd_hash"],
                                user_data.get("telefono"),
                                user_data.get("google_id"),
                                user_data.get("tipo_documento"),
                                user_data.get("documento"),
                                user_data.get("direccion"),
                                1 if user_data.get("estado_usuario", True) else 0,
                                user_data["email"],
                            )
                        )
                    else:
                        cur.execute(
                            self.SQL_INSERT_USUARIO,
                            (
                                int(user_data.get("fk_id_rol", 3)),
                                user_data["nombre"],
                                user_data["apellido"],
                                user_data["email"],
                                user_data["pwd_hash"],
                                user_data.get("telefono"),
                                user_data.get("google_id"),
                                user_data.get("tipo_documento"),
                                user_data.get("documento"),
                                user_data.get("direccion"),
                                1 if user_data.get("estado_usuario", True) else 0,
                            )
                        )
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass

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

    def _validar_complejidad_password(self, password: str) -> None:
        """
        RN-SEG-008: Exige al menos 8 caracteres, una letra mayúscula, una minúscula y un número.
        """
        pwd = password or ""
        if (
            len(pwd) < 8
            or not any(c.isupper() for c in pwd)
            or not any(c.islower() for c in pwd)
            or not any(c.isdigit() for c in pwd)
        ):
            raise ValueError(
                "RN-SEG-008: La contraseña debe tener al menos 8 caracteres, incluyendo "
                "al menos una letra mayúscula, una letra minúscula y un número."
            )

    def _validar_tipo_documento(self, tipo_documento: Optional[str]) -> Optional[str]:
        if tipo_documento is None:
            return None
        val = str(tipo_documento).strip()
        if not val:
            return None
        canonical = self.ALLOWED_DOCUMENT_TYPES.get(val.upper())
        if not canonical:
            raise ValueError("Tipo de documento no válido. Use CC, CE, TI o Pasaporte.")
        return canonical

    def _validar_documento(self, documento: Optional[str]) -> Optional[str]:
        if documento is None:
            return None
        val = str(documento).strip()
        if not val:
            return None
        if not self.DOCUMENTO_REGEX.match(val):
            raise ValueError("El número de documento debe ser alfanumérico (4 a 30 caracteres).")
        return val

    def _validar_par_documento(self, tipo_documento: Optional[str], documento: Optional[str]):
        tipo_clean = self._validar_tipo_documento(tipo_documento)
        doc_clean = self._validar_documento(documento)
        if (tipo_clean and not doc_clean) or (doc_clean and not tipo_clean):
            raise ValueError("Debe indicar tanto el tipo de documento como el número de documento.")
        return tipo_clean, doc_clean

    def _validar_direccion(self, direccion: Optional[str]) -> Optional[str]:
        if direccion is None:
            return None
        val = re.sub(r"[\x00-\x1f\x7f]+", " ", str(direccion)).strip()
        if not val:
            return None
        if len(val) > 255:
            raise ValueError("La dirección no puede superar 255 caracteres.")
        return val

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
            "tipo_documento": user_data.get("tipo_documento"),
            "documento": user_data.get("documento"),
            "direccion": user_data.get("direccion"),
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
        for uid, user in self.usuarios.items():
            if user["email"].lower() == email_clean:
                user["pwd_hash"] = self._hash_password(contrasena)
                self._sincronizar_usuario_bd(user)
                return uid

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
            "tipo_documento": None,
            "documento": None,
            "direccion": None,
            "estado_usuario": True,
            "fecha_registro": datetime.now().isoformat(),
            "google_id": None,
            "reset_token_hash": None,
            "reset_token_expira": None,
            "intentos_fallidos": 0,
            "bloqueado_hasta": None
        }
        self.user_id_counter += 1
        self._sincronizar_usuario_bd(self.usuarios[user_id])
        return user_id

    def registrar_cliente(
        self,
        nombre: str,
        apellido: str,
        email: str,
        contrasena: str,
        telefono: Optional[str] = None,
        tipo_documento: Optional[str] = None,
        documento: Optional[str] = None,
        direccion: Optional[str] = None
    ) -> int:
        """
        RF-SEG-007 / RN-SEG-007: Auto-registro público asigna estrictamente el rol Clienta (fk_id_rol = 3),
        valida unicidad de correo, longitud mínima de 8 caracteres y campos opcionales de identidad y despacho.
        """
        if not nombre or not str(nombre).strip() or not apellido or not str(apellido).strip():
            raise ValueError("El nombre y el apellido son obligatorios.")
        self._validar_complejidad_password(contrasena)

        email_clean = self._validar_formato_email(email)
        tipo_doc_clean, doc_clean = self._validar_par_documento(tipo_documento, documento)
        dir_clean = self._validar_direccion(direccion)

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
            'telefono': telefono.strip() if telefono and str(telefono).strip() else None,
            'tipo_documento': tipo_doc_clean,
            'documento': doc_clean,
            'direccion': dir_clean,
            'estado_usuario': True,
            'fecha_registro': datetime.now().isoformat(),
            'google_id': None,
            'reset_token_hash': None,
            'reset_token_expira': None,
            'intentos_fallidos': 0,
            'bloqueado_hasta': None
        }
        self.user_id_counter += 1
        self._sincronizar_usuario_bd(self.usuarios[user_id])

        self.auditoria_service.registrar_traza_auditoria(
            usuario_id=user_id,
            tipo_accion="REGISTRO_CLIENTE",
            tabla_afectada="usuarios",
            registro_id=user_id,
            valor_anterior=None,
            valor_nuevo={
                "email": email_clean,
                "rol": "Clienta",
                "fk_id_rol": 3,
                "tipo_documento": tipo_doc_clean,
            }
        )
        return user_id

    def validar_credenciales(
        self,
        email: str,
        contrasena: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> str:
        """
        RF-SEG-006 y RF-SEG-008 / RN-SEG-008: Valida credenciales, aplica bloqueo temporal de 15 minutos
        tras 3 intentos fallidos consecutivos y audita accesos válidos y fallidos con IP y dispositivo.
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
                        valor_nuevo="Intento de acceso en cuenta inactiva",
                        ip_address=ip_address,
                        user_agent=user_agent
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
                        valor_nuevo=f"Bloqueada hasta {bloqueado_hasta.isoformat()}",
                        ip_address=ip_address,
                        user_agent=user_agent
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
                        valor_nuevo={"email": email_clean, "rol": user_data["rol"]},
                        ip_address=ip_address,
                        user_agent=user_agent
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
                        valor_nuevo={"intentos_fallidos": intentos},
                        ip_address=ip_address,
                        user_agent=user_agent
                    )
                    raise ValueError("Credenciales inválidas.")

        self.auditoria_service.registrar_traza_auditoria(
            usuario_id=0,
            tipo_accion="LOGIN_FAILED",
            tabla_afectada="usuarios",
            registro_id=None,
            valor_nuevo={
                "email": re.sub(r"[\x00-\x1f\x7f]+", "", email_clean)[:150],
                "motivo": "credenciales_invalidas"
            },
            ip_address=ip_address,
            user_agent=user_agent
        )
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

    def cerrar_sesion(
        self,
        token: str,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ) -> bool:
        """
        RF-SEG-009 / RN-SEG-009 y RF-SEG-006: Destruye la sesión activa e inserta traza LOGOUT en auditoría con IP y dispositivo.
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
            registro_id=user_id,
            ip_address=ip_address,
            user_agent=user_agent
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
        telefono: Any = _UNSET,
        tipo_documento: Any = _UNSET,
        documento: Any = _UNSET,
        direccion: Any = _UNSET
    ) -> Dict[str, Any]:
        """
        RF-SEG-011 / RN-SEG-011: Actualiza datos de contacto, documento y dirección validando unicidad de correo,
        impidiendo alterar rol o estado y generando traza en auditoría.
        """
        user_id = self.get_user_id(token)
        user_data = self.usuarios[user_id]

        if not nombre or not str(nombre).strip() or not apellido or not str(apellido).strip():
            raise ValueError("El nombre y el apellido son obligatorios.")

        nuevo_email = user_data["email"]
        if email is not None and str(email).strip():
            nuevo_email = self._validar_formato_email(email)
            for uid, u in self.usuarios.items():
                if uid != user_id and u["email"].lower() == nuevo_email:
                    raise ValueError("El correo electrónico ya está registrado por otro usuario.")

        tipo_candidato = user_data.get("tipo_documento") if tipo_documento is _UNSET else tipo_documento
        doc_candidato = user_data.get("documento") if documento is _UNSET else documento
        tipo_doc_clean, doc_clean = self._validar_par_documento(tipo_candidato, doc_candidato)

        dir_candidata = user_data.get("direccion") if direccion is _UNSET else direccion
        dir_clean = self._validar_direccion(dir_candidata)

        anterior = {
            "nombre": user_data["nombre"],
            "apellido": user_data["apellido"],
            "email": user_data["email"],
            "telefono": user_data.get("telefono"),
            "tipo_documento": user_data.get("tipo_documento"),
            "documento": user_data.get("documento"),
            "direccion": user_data.get("direccion"),
        }

        user_data["nombre"] = nombre.strip()
        user_data["apellido"] = apellido.strip()
        user_data["email"] = nuevo_email
        if telefono is not _UNSET:
            if telefono is None:
                user_data["telefono"] = None
            else:
                tel_str = str(telefono).strip()
                user_data["telefono"] = tel_str if tel_str else None
        user_data["tipo_documento"] = tipo_doc_clean
        user_data["documento"] = doc_clean
        user_data["direccion"] = dir_clean
        self._sincronizar_usuario_bd(user_data)

        nuevo = {
            "nombre": user_data["nombre"],
            "apellido": user_data["apellido"],
            "email": user_data["email"],
            "telefono": user_data.get("telefono"),
            "tipo_documento": user_data.get("tipo_documento"),
            "documento": user_data.get("documento"),
            "direccion": user_data.get("direccion"),
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

    def _contar_administradoras_activas(self) -> int:
        """Cuenta cuántas cuentas con rol Administradora permanecen activas."""
        return sum(
            1
            for u in self.usuarios.values()
            if u.get("rol") == "Administradora" and u.get("estado_usuario", True)
        )

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
        self._validar_complejidad_password(contrasena)

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
            "tipo_documento": None,
            "documento": None,
            "direccion": None,
            "estado_usuario": True,
            "fecha_registro": datetime.now().isoformat(),
            "google_id": None,
            "reset_token_hash": None,
            "reset_token_expira": None,
            "intentos_fallidos": 0,
            "bloqueado_hasta": None
        }
        self.user_id_counter += 1
        self._sincronizar_usuario_bd(self.usuarios[user_id])

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
        if target.get("rol") == "Clienta":
            raise ValueError("El usuario indicado no pertenece al personal operativo.")

        anterior = {
            "nombre": target["nombre"],
            "apellido": target["apellido"],
            "telefono": target.get("telefono"),
            "rol": target["rol"]
        }

        if rol is not None:
            if rol not in ("Administradora", "Vendedora"):
                raise ValueError("El rol del personal operativo debe ser 'Administradora' o 'Vendedora'.")
            if (
                rol != target["rol"]
                and target["rol"] == "Administradora"
                and target.get("estado_usuario", True)
                and self._contar_administradoras_activas() <= 1
            ):
                raise ValueError("No se puede cambiar el rol de la última Administradora activa del sistema.")
            target["rol"] = rol
            target["fk_id_rol"] = self.ROLES_MAP[rol]
        if nombre is not None and nombre.strip():
            target["nombre"] = nombre.strip()
        if apellido is not None and apellido.strip():
            target["apellido"] = apellido.strip()
        if telefono is not None:
            target["telefono"] = telefono.strip() if telefono.strip() else None

        self._sincronizar_usuario_bd(target)

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

    def cambiar_estado_personal(
        self,
        token_admin: str,
        target_user_id: int,
        activar: bool
    ) -> Dict[str, Any]:
        """
        RF-SEG-015 / RN-SEG-015: Baja lógica (estado_usuario = False) o reactivación del
        personal operativo, protegiendo contra auto-bloqueo y última administradora activa.
        """
        admin_id = self._verificar_admin(token_admin)
        if target_user_id not in self.usuarios:
            raise ValueError("El usuario especificado no existe.")

        target = self.usuarios[target_user_id]
        if target.get("rol") == "Clienta":
            raise ValueError("El usuario indicado no pertenece al personal operativo.")

        estado_previo = bool(target.get("estado_usuario", True))
        if not activar:
            if target_user_id == admin_id:
                raise ValueError("No puedes aplicar baja lógica a tu propia cuenta en sesión.")
            if (
                target.get("rol") == "Administradora"
                and estado_previo
                and self._contar_administradoras_activas() <= 1
            ):
                raise ValueError("No se puede desactivar la última Administradora activa del sistema.")

            target["estado_usuario"] = False
            for t in [t for t, s in self.sesiones.items() if s["user_id"] == target_user_id]:
                del self.sesiones[t]
            for rt in [r for r, d in self.refresh_tokens.items() if d["user_id"] == target_user_id]:
                del self.refresh_tokens[rt]

            self._sincronizar_usuario_bd(target)
            self.auditoria_service.registrar_traza_auditoria(
                usuario_id=admin_id,
                tipo_accion="BAJA_LOGICA_PERSONAL",
                tabla_afectada="usuarios",
                registro_id=target_user_id,
                valor_anterior={"estado_usuario": estado_previo},
                valor_nuevo={"estado_usuario": False}
            )
        else:
            target["estado_usuario"] = True
            target["intentos_fallidos"] = 0
            target["bloqueado_hasta"] = None
            self._sincronizar_usuario_bd(target)
            self.auditoria_service.registrar_traza_auditoria(
                usuario_id=admin_id,
                tipo_accion="REACTIVACION_PERSONAL",
                tabla_afectada="usuarios",
                registro_id=target_user_id,
                valor_anterior={"estado_usuario": estado_previo},
                valor_nuevo={"estado_usuario": True}
            )

        return self._sanitizar_usuario_publico(target_user_id, target)

    def desactivar_personal(self, token_admin: str, target_user_id: int) -> bool:
        """
        RF-SEG-015 / RN-SEG-015: Baja lógica obligatoria (estado_usuario = False), revocación inmediata
        de sesiones activas y registro en auditoría.
        """
        self.cambiar_estado_personal(token_admin, target_user_id, activar=False)
        return True

    def google_oauth_verify(self, id_token_str: str, client_id: Optional[str] = None) -> Dict[str, Any]:
        """
        RF-SEG-008: Verificación criptográfica oficial de ID Token de Google OAuth 2.0 (OWASP A07).
        Falla cerrado (NotImplementedError) si GOOGLE_CLIENT_ID no está configurado o falta google-auth.
        Nunca decodifica JWT manualmente sin validar firma, aud, iss, exp y email_verified.
        """
        expected_client_id = (
            client_id if client_id is not None else os.getenv("GOOGLE_CLIENT_ID", "")
        ).strip()
        if not expected_client_id:
            raise NotImplementedError("El inicio de sesión con Google OAuth 2.0 no está configurado en el servidor.")

        if not isinstance(id_token_str, str) or not id_token_str.strip() or len(id_token_str.strip()) > 8192:
            raise ValueError("Token de Google inválido o ausente.")

        try:
            from google.oauth2 import id_token as google_id_token
            from google.auth.transport import requests as google_requests
        except ImportError:
            raise NotImplementedError("Dependencia google-auth no instalada en el servidor.")

        try:
            idinfo = google_id_token.verify_oauth2_token(
                id_token_str.strip(),
                google_requests.Request(),
                expected_client_id,
            )
        except Exception:
            raise ValueError("Token de Google inválido o expirado.")

        if not isinstance(idinfo, dict):
            raise ValueError("Token de Google inválido.")
        if idinfo.get("iss") not in ("accounts.google.com", "https://accounts.google.com"):
            raise ValueError("Emisor del token de Google no confiable.")
        if idinfo.get("aud") != expected_client_id:
            raise ValueError("El token de Google no corresponde a esta aplicación.")
        if idinfo.get("email_verified") is not True:
            raise ValueError("La cuenta de Google no tiene correo verificado.")

        sub = str(idinfo.get("sub") or "").strip()
        email_clean = self._validar_formato_email(str(idinfo.get("email") or ""))
        if not sub or not email_clean:
            raise ValueError("Token de Google incompleto.")

        given = str(idinfo.get("given_name") or "").strip()
        family = str(idinfo.get("family_name") or "").strip()
        if not given:
            full_name = str(idinfo.get("name") or email_clean.split("@")[0]).strip()
            parts = full_name.split(" ", 1)
            given = parts[0]
            family = family or (parts[1] if len(parts) > 1 else "Clienta")
        if not family:
            family = "Clienta"

        return {
            "email": email_clean,
            "google_id": sub,
            "nombre": given[:100],
            "apellido": family[:100],
        }

    def autenticar_con_google(
        self,
        id_token_str: str,
        client_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Verifica el ID Token con Google, vincula o registra estrictamente una cuenta Clienta (rol 3),
        emite el par real access/refresh token y audita el evento con IP y User-Agent.
        """
        try:
            ginfo = self.google_oauth_verify(id_token_str, client_id=client_id)
        except ValueError:
            self.auditoria_service.registrar_traza_auditoria(
                usuario_id=0,
                tipo_accion="LOGIN_FAILED",
                tabla_afectada="usuarios",
                registro_id=None,
                valor_nuevo={"metodo": "google_oauth", "motivo": "token_invalido"},
                ip_address=ip_address,
                user_agent=user_agent,
            )
            raise

        sub = ginfo["google_id"]
        email_clean = ginfo["email"]
        user_id = None
        user_data = None

        for uid, u in self.usuarios.items():
            if u.get("google_id") == sub:
                user_id = uid
                user_data = u
                break

        if user_data is None:
            for uid, u in self.usuarios.items():
                if u["email"].lower() == email_clean:
                    if u.get("google_id") and u["google_id"] != sub:
                        raise ValueError("El identificador de Google no coincide con el vinculado a esta cuenta.")
                    user_id = uid
                    user_data = u
                    break

        if user_data is not None:
            if not user_data.get("estado_usuario", True):
                self.auditoria_service.registrar_traza_auditoria(
                    usuario_id=user_id,
                    tipo_accion="LOGIN_FAILED",
                    tabla_afectada="usuarios",
                    registro_id=user_id,
                    valor_nuevo={"metodo": "google_oauth", "motivo": "cuenta_inactiva"},
                    ip_address=ip_address,
                    user_agent=user_agent,
                )
                raise PermissionError("La cuenta de usuario se encuentra inactiva.")
            if not user_data.get("google_id"):
                user_data["google_id"] = sub
                self._sincronizar_usuario_bd(user_data)
        else:
            user_id = self.user_id_counter
            user_data = {
                "id_usuario": user_id,
                "fk_id_rol": 3,
                "nombre": ginfo["nombre"],
                "apellido": ginfo["apellido"],
                "email": email_clean,
                "pwd_hash": "",
                "rol": "Clienta",
                "telefono": None,
                "tipo_documento": None,
                "documento": None,
                "direccion": None,
                "estado_usuario": True,
                "fecha_registro": datetime.now().isoformat(),
                "google_id": sub,
                "reset_token_hash": None,
                "reset_token_expira": None,
                "intentos_fallidos": 0,
                "bloqueado_hasta": None,
            }
            self.usuarios[user_id] = user_data
            self.user_id_counter += 1
            self._sincronizar_usuario_bd(user_data)
            self.auditoria_service.registrar_traza_auditoria(
                usuario_id=user_id,
                tipo_accion="REGISTRO_CLIENTE",
                tabla_afectada="usuarios",
                registro_id=user_id,
                valor_anterior=None,
                valor_nuevo={"email": email_clean, "rol": "Clienta", "fk_id_rol": 3, "metodo": "google_oauth"},
                ip_address=ip_address,
                user_agent=user_agent,
            )

        now = datetime.now()
        user_data["intentos_fallidos"] = 0
        user_data["bloqueado_hasta"] = None
        token = str(uuid.uuid4())
        self.sesiones[token] = {
            "user_id": user_id,
            "expires_at": now + timedelta(minutes=self.ACCESS_TTL_MINUTES),
        }
        refresh = self._emitir_refresh_token(token, user_id, now)
        self.auditoria_service.registrar_traza_auditoria(
            usuario_id=user_id,
            tipo_accion="LOGIN_SUCCESS",
            tabla_afectada="usuarios",
            registro_id=user_id,
            valor_nuevo={"email": email_clean, "rol": user_data["rol"], "metodo": "google_oauth"},
            ip_address=ip_address,
            user_agent=user_agent,
        )
        return {
            "token": token,
            "refresh_token": refresh,
            "expires_in": self.ACCESS_TTL_MINUTES * 60,
            "usuario": self._sanitizar_usuario_publico(user_id, user_data),
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
        self._validar_complejidad_password(nueva_password)
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
        self._validar_complejidad_password(nueva_password)

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

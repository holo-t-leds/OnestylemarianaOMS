# src/faq/service.py
"""
Servicio de Dominio para el Módulo 5: Centro de Ayuda, Preguntas Frecuentes (FAQ)
y Canales de Soporte (RF-FAQ-001 a RF-FAQ-011 / Reglas: RN-FAQ-001 a RN-FAQ-011).
"""
import re
import time
import urllib.parse
from datetime import datetime
from typing import Any, Dict, List, Optional
from src.catalogo.service import NotFoundError


class RateLimitError(ValueError):
    """Excepción semántica para límite de peticiones excedido (HTTP 429 Too Many Requests)."""
    pass


class FAQService:
    """
    Gestiona categorías temáticas (`FaqCategory`), preguntas frecuentes (`FaqItem`) con
    votos de utilidad y baja lógica, canal directo de WhatsApp (`RF-FAQ-011`) y tickets de
    contacto (`SupportTicket` / `ContactMessage`) con sanitización XSS y rate limiting.
    """

    def __init__(self, auditoria_service=None, seed_defaults: bool = False):
        self.auditoria_service = auditoria_service
        self.categorias: Dict[int, Dict[str, Any]] = {
            1: {
                "id_categoria": 1,
                "nombre": "Envíos y Entregas",
                "slug": "envios-y-entregas",
                "icono": "bi-truck",
                "order_index": 1,
                "estado": "activo",
            },
            2: {
                "id_categoria": 2,
                "nombre": "Medios de Pago",
                "slug": "medios-de-pago",
                "icono": "bi-credit-card",
                "order_index": 2,
                "estado": "activo",
            },
            3: {
                "id_categoria": 3,
                "nombre": "Cambios y Devoluciones",
                "slug": "cambios-y-devoluciones",
                "icono": "bi-arrow-repeat",
                "order_index": 3,
                "estado": "activo",
            },
            4: {
                "id_categoria": 4,
                "nombre": "Cuidado de Prendas y Tallas",
                "slug": "cuidado-y-tallas",
                "icono": "bi-rulers",
                "order_index": 4,
                "estado": "activo",
            },
        }
        self.faqs: Dict[int, Dict[str, Any]] = {}
        self.faq_id_counter = 1

        # Tickets de contacto/soporte (SupportTicket)
        self.tickets: Dict[int, Dict[str, Any]] = {}
        self.ticket_id_counter = 1

        # Control de Rate Limiting por clave de cliente/IP
        self._contact_rate_log: Dict[str, List[float]] = {}
        self._vote_rate_log: Dict[str, List[float]] = {}
        self.max_contact_requests_per_window = 3
        self.contact_window_seconds = 60.0

        # Configuración del canal oficial de soporte (RF-FAQ-011)
        self.config_soporte = {
            "tipo": "WhatsApp",
            "telefono": "573001234567",
            "correo": "concierge@onestylemariana.co",
            "horario_atencion": "Lunes a Sábado de 9:00 a.m. a 7:00 p.m.",
            "mensaje_predeterminado": "Hola, tengo una consulta sobre OneStyle Mariana que no encontré en las preguntas frecuentes.",
            "estado": "activo",
        }

        if seed_defaults:
            self._cargar_semilla_faqs()

    def _cargar_semilla_faqs(self):
        semilla = [
            (
                "¿Cuáles son los tiempos y costos de envío en Colombia?",
                "Realizamos despachos Express asegurados a toda Colombia. En Bogotá la entrega toma de 1 a 2 días hábiles y en el resto del país de 2 a 4 días hábiles.",
                1,
                1,
            ),
            (
                "¿Cómo puedo rastrear el estado de mi pedido?",
                "Con tu código único de orden (ej. ORD-00001) puedes consultar en tiempo real la etapa de preparación y despacho desde la sección Seguimiento.",
                1,
                2,
            ),
            (
                "¿Qué medios de pago aceptan a través del Concierge?",
                "Aceptamos transferencia inmediata por PSE, Nequi, Bancolombia y tarjetas débito/crédito mediante enlace seguro verificado por nuestra asesora en WhatsApp.",
                2,
                1,
            ),
            (
                "¿Cuál es la política de cambios por talla o referencia?",
                "Puedes solicitar cambio de talla dentro de los primeros 15 días calendario posteriores a la entrega, siempre que la prenda conserve sus etiquetas originales.",
                3,
                1,
            ),
            (
                "¿Cómo elegir mi talla ideal en corsets y blusas estructuradas?",
                "En cada ficha de producto encontrarás la guía de medidas exactas de busto y cintura. Si estás entre dos tallas, en corsets con varillaje recomendamos elegir la talla superior.",
                4,
                1,
            ),
        ]
        for preg, resp, cat_id, orden in semilla:
            self.crear_faq(preg, resp, cat_id, orden, "admin")

    @staticmethod
    def _sanitize_text(val: Any) -> str:
        if val is None:
            return ""
        text = str(val)
        text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<[^>]+>", "", text)
        return text.strip()

    def reset_rate_limits(self):
        self._contact_rate_log.clear()
        self._vote_rate_log.clear()

    def _check_rate_limit(self, bucket: Dict[str, List[float]], key: str, max_reqs: int, window_sec: float):
        now = time.time()
        timestamps = [t for t in bucket.get(key, []) if (now - t) < window_sec]
        if len(timestamps) >= max_reqs:
            raise RateLimitError("Demasiadas solicitudes en poco tiempo. Por favor intente nuevamente en un minuto.")
        timestamps.append(now)
        bucket[key] = timestamps

    # -------------------------------------------------------------------------
    # Flujo Público (RF-FAQ-001, RF-FAQ-002, RF-FAQ-003, RF-FAQ-004)
    # -------------------------------------------------------------------------

    def listar_categorias_publicas(self) -> List[Dict[str, Any]]:
        cats = [c for c in self.categorias.values() if c.get("estado") == "activo"]
        return sorted(cats, key=lambda x: x.get("order_index", x["id_categoria"]))

    def obtener_faqs_publicas(self) -> List[Dict[str, Any]]:
        """
        Retorna únicamente preguntas con estado 'activo' pertenecientes a categorías activas,
        ordenadas por el índice configurado. RF-FAQ-001, RF-FAQ-002, RF-FAQ-003, RF-FAQ-010.
        """
        resultado = []
        for faq in self.faqs.values():
            cat = self.categorias.get(faq["id_categoria"])
            if faq["estado"] == "activo" and cat and cat["estado"] == "activo":
                resultado.append({
                    "id_faq": faq["id_faq"],
                    "pregunta": faq["pregunta"],
                    "respuesta": faq["respuesta"],
                    "id_categoria": faq["id_categoria"],
                    "categoria": cat["nombre"],
                    "categoria_slug": cat.get("slug", ""),
                    "orden": faq["orden"],
                    "helpful_count": faq.get("helpful_count", 0),
                    "not_helpful_count": faq.get("not_helpful_count", 0),
                })
        return sorted(resultado, key=lambda x: (x["orden"], x["id_faq"]))

    def buscar_faqs(self, termino: str) -> List[Dict[str, Any]]:
        """
        Búsqueda por palabra clave insensible a mayúsculas/minúsculas y tildes sobre
        pregunta, respuesta y categoría (RF-FAQ-004 / RN-FAQ-004).
        """
        if not termino or not termino.strip():
            return self.obtener_faqs_publicas()

        t_clean = termino.strip().lower()
        publicas = self.obtener_faqs_publicas()

        coincidencias = [
            faq
            for faq in publicas
            if t_clean in faq["pregunta"].lower()
            or t_clean in faq["respuesta"].lower()
            or t_clean in faq["categoria"].lower()
        ]
        return coincidencias

    def consultar_faqs_paginadas(
        self,
        categoria: Optional[str] = None,
        termino: Optional[str] = None,
        page: int = 1,
        per_page: int = 10,
    ) -> Dict[str, Any]:
        """
        Consulta optimizada, filtrable por categoría (ID, nombre o slug), con búsqueda
        por palabra clave y paginación para `GET /api/v1/faqs/`.
        """
        base = self.buscar_faqs(termino) if termino else self.obtener_faqs_publicas()

        if categoria and str(categoria).strip().lower() not in ("todas", "todos", "all"):
            cat_q = str(categoria).strip().lower()
            base = [
                f
                for f in base
                if str(f["id_categoria"]) == cat_q
                or f["categoria"].lower() == cat_q
                or f.get("categoria_slug", "").lower() == cat_q
            ]

        total = len(base)
        page = max(1, int(page))
        per_page = max(1, min(50, int(per_page)))
        start = (page - 1) * per_page
        items = base[start : start + per_page]

        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "categorias": self.listar_categorias_publicas(),
            "canal_soporte": {
                "whatsapp_url": self.generar_enlace_soporte_whatsapp(),
                "correo": self.config_soporte.get("correo"),
                "horario": self.config_soporte.get("horario_atencion"),
            },
        }

    def registrar_voto_faq(
        self, id_faq: int, util: bool = True, client_key: str = "default-ip"
    ) -> Dict[str, Any]:
        """
        Registra un voto de utilidad (`helpful_count` / `not_helpful_count`) en una FAQ activa
        con protección contra flooding.
        """
        if id_faq not in self.faqs or self.faqs[id_faq].get("estado") != "activo":
            raise NotFoundError("La pregunta frecuente solicitada no existe o no está activa.")

        self._check_rate_limit(self._vote_rate_log, f"{client_key}:{id_faq}", max_reqs=5, window_sec=60.0)

        faq = self.faqs[id_faq]
        if util:
            faq["helpful_count"] = faq.get("helpful_count", 0) + 1
        else:
            faq["not_helpful_count"] = faq.get("not_helpful_count", 0) + 1

        return {
            "id_faq": id_faq,
            "helpful_count": faq["helpful_count"],
            "not_helpful_count": faq["not_helpful_count"],
        }

    def generar_enlace_soporte_whatsapp(self, mensaje_personalizado: Optional[str] = None) -> str:
        """
        Genera la URL del Click-to-Chat hacia el canal oficial de soporte (RF-FAQ-011 / RN-FAQ-011).
        """
        if self.config_soporte.get("estado") != "activo":
            raise ValueError("El canal de soporte no está disponible actualmente.")

        tel = self.config_soporte["telefono"]
        msg = self._sanitize_text(mensaje_personalizado) or self.config_soporte["mensaje_predeterminado"]
        msg_encoded = urllib.parse.quote(msg)

        return f"https://api.whatsapp.com/send?phone={tel}&text={msg_encoded}"

    # -------------------------------------------------------------------------
    # Formulario de Contacto y Tickets de Soporte (RF-FAQ-011)
    # -------------------------------------------------------------------------

    def crear_ticket_soporte(
        self,
        nombre: str,
        contacto: str,
        asunto: str,
        mensaje: str,
        codigo_orden: Optional[str] = None,
        client_key: str = "default-ip",
    ) -> Dict[str, Any]:
        """
        Crea un ticket de soporte (`SupportTicket` / `ContactMessage`) aplicando:
        - Rate limiting estricto por IP/cliente (HTTP 429 ante ráfagas).
        - Sanitización contra XSS e inyección de scripts.
        - Validación rigurosa de correo electrónico y longitud mínima del mensaje.
        """
        self._check_rate_limit(
            self._contact_rate_log,
            client_key,
            max_reqs=self.max_contact_requests_per_window,
            window_sec=self.contact_window_seconds,
        )

        nombre_clean = self._sanitize_text(nombre)
        contacto_clean = self._sanitize_text(contacto)
        asunto_clean = self._sanitize_text(asunto)
        mensaje_clean = self._sanitize_text(mensaje)
        orden_clean = self._sanitize_text(codigo_orden) if codigo_orden else None

        if not nombre_clean or len(nombre_clean) < 2:
            raise ValueError("El nombre de contacto es obligatorio.")

        email_regex = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
        if not contacto_clean or not re.match(email_regex, contacto_clean):
            raise ValueError("Debe proporcionar un correo electrónico de contacto válido.")

        if not asunto_clean or len(asunto_clean) < 3:
            raise ValueError("El asunto de la consulta es obligatorio.")

        if not mensaje_clean or len(mensaje_clean) < 10:
            raise ValueError("El mensaje debe contener al menos 10 caracteres descriptivos.")

        tid = self.ticket_id_counter
        ticket = {
            "id_ticket": tid,
            "nombre": nombre_clean,
            "contacto": contacto_clean,
            "asunto": asunto_clean,
            "mensaje": mensaje_clean,
            "codigo_orden": orden_clean,
            "estado": "ABIERTO",
            "created_at": datetime.now().isoformat(),
            "whatsapp_followup_url": self.generar_enlace_soporte_whatsapp(
                f"Hola OneStyle Mariana, envié el ticket #{tid} ({asunto_clean})"
                + (f" sobre el pedido {orden_clean}." if orden_clean else ".")
            ),
        }
        self.tickets[tid] = ticket
        self.ticket_id_counter += 1
        return dict(ticket)

    # -------------------------------------------------------------------------
    # Flujo Administrativo (RF-FAQ-005 a RF-FAQ-010)
    # -------------------------------------------------------------------------

    def crear_faq(self, pregunta: str, respuesta: str, id_categoria: int, orden: int, usuario_creador: str) -> int:
        """
        Registra una nueva pregunta frecuente validando categoría existente y orden entero positivo
        único dentro de la categoría (RF-FAQ-005, RF-FAQ-010 / RN-FAQ-005, RN-FAQ-010).
        """
        preg_clean = self._sanitize_text(pregunta)
        resp_clean = self._sanitize_text(respuesta)

        if not preg_clean or not resp_clean:
            raise ValueError("La pregunta y la respuesta no pueden estar vacías.")

        if id_categoria not in self.categorias:
            raise ValueError("La categoría temática especificada no existe.")

        if int(orden) <= 0:
            raise ValueError("El orden debe ser un número entero positivo.")

        for faq in self.faqs.values():
            if faq["id_categoria"] == id_categoria and faq["orden"] == int(orden):
                raise ValueError(f"Ya existe una pregunta con el orden {orden} en esta categoría.")

        faq_id = self.faq_id_counter
        self.faqs[faq_id] = {
            "id_faq": faq_id,
            "pregunta": preg_clean,
            "respuesta": resp_clean,
            "id_categoria": int(id_categoria),
            "orden": int(orden),
            "estado": "activo",
            "helpful_count": 0,
            "not_helpful_count": 0,
            "fecha_creacion": datetime.now(),
            "usuario_creacion": usuario_creador,
            "fecha_actualizacion": datetime.now(),
            "usuario_actualizacion": usuario_creador,
        }
        self.faq_id_counter += 1
        return faq_id

    def actualizar_faq(
        self, id_faq: int, pregunta: str, respuesta: str, id_categoria: int, orden: int, usuario_editor: str
    ) -> bool:
        """
        Modifica el contenido, categoría y orden de una pregunta existente (RF-FAQ-007 / RN-FAQ-007).
        """
        if id_faq not in self.faqs:
            raise NotFoundError("La pregunta frecuente no existe.")

        preg_clean = self._sanitize_text(pregunta)
        resp_clean = self._sanitize_text(respuesta)
        if not preg_clean or not resp_clean:
            raise ValueError("La pregunta y respuesta son obligatorias.")

        if id_categoria not in self.categorias:
            raise ValueError("Categoría inválida.")

        if int(orden) <= 0:
            raise ValueError("El orden debe ser un número entero positivo.")

        for fid, faq in self.faqs.items():
            if fid != id_faq and faq["id_categoria"] == id_categoria and faq["orden"] == int(orden):
                raise ValueError(f"El orden {orden} ya está ocupado por otra pregunta en esta categoría.")

        item = self.faqs[id_faq]
        item.update({
            "pregunta": preg_clean,
            "respuesta": resp_clean,
            "id_categoria": int(id_categoria),
            "orden": int(orden),
            "fecha_actualizacion": datetime.now(),
            "usuario_actualizacion": usuario_editor,
        })
        return True

    def cambiar_estado(self, id_faq: int, nuevo_estado: str, usuario_editor: str) -> bool:
        """
        Implementa la baja lógica ('inactivo') y la reactivación inmediata ('activo').
        RF-FAQ-008, RF-FAQ-009 / RN-FAQ-008, RN-FAQ-009.
        """
        if id_faq not in self.faqs:
            raise NotFoundError("La pregunta frecuente no existe.")

        if nuevo_estado not in ["activo", "inactivo"]:
            raise ValueError("Estado no válido. Use 'activo' o 'inactivo'.")

        self.faqs[id_faq]["estado"] = nuevo_estado
        self.faqs[id_faq]["fecha_actualizacion"] = datetime.now()
        self.faqs[id_faq]["usuario_actualizacion"] = usuario_editor
        return True

    def listar_todas_admin(self) -> List[Dict[str, Any]]:
        """
        Lista preguntas activas e inactivas con sus metadatos para el panel de administración (RF-FAQ-006).
        """
        resultado = []
        for faq in self.faqs.values():
            cat = self.categorias.get(faq["id_categoria"], {})
            copia = dict(faq)
            copia["categoria"] = cat.get("nombre", "General")
            copia["fecha_creacion"] = (
                faq["fecha_creacion"].isoformat()
                if isinstance(faq.get("fecha_creacion"), datetime)
                else str(faq.get("fecha_creacion"))
            )
            copia["fecha_actualizacion"] = (
                faq["fecha_actualizacion"].isoformat()
                if isinstance(faq.get("fecha_actualizacion"), datetime)
                else str(faq.get("fecha_actualizacion"))
            )
            resultado.append(copia)
        return sorted(resultado, key=lambda x: (x["id_categoria"], x["orden"]))

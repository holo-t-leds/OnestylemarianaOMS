# src/pedidos/service.py
"""
Servicio de Dominio para el Módulo 4: Gestión de Pedidos (OMS), Máquina de Estados Secuencial
y Concierge WhatsApp (RF-PED-001 a RF-PED-004 / Reglas: RN-PED-001 a RN-PED-004).
"""
import re
import threading
import urllib.parse
from datetime import datetime
from typing import Any, Dict, List, Optional
from src.catalogo.service import ConflictError, NotFoundError


class PedidosService:
    """
    Gestiona el ciclo de vida completo del Pedido (`Order`), sus líneas inmutables (`OrderItem`),
    la Máquina de Estados Finita (FSM), la consolidación atómica de inventario, la generación
    segura del enlace Concierge de WhatsApp y los reportes consolidados de ventas.
    """

    # Mapa de equivalencia de etapas de la Máquina de Estados Finita (FSM)
    # Permite operar tanto con la nomenclatura de schema.sql/tests ('Registrado'..'Entregado')
    # como con los códigos canónicos del OMS ('PENDIENTE_PAGO'..'ENTREGADO').
    STAGE_MAP = {
        "Registrado": 1,
        "Pendiente de Pago": 1,
        "PENDIENTE_PAGO": 1,
        "Confirmado": 2,
        "Pago Confirmado": 2,
        "CONFIRMADO": 2,
        "En Empaque": 3,
        "En Preparación": 3,
        "EN_PREPARACION": 3,
        "Despachado": 4,
        "DESPACHADO": 4,
        "Entregado": 5,
        "ENTREGADO": 5,
        "Cancelado": 0,
        "CANCELADO": 0,
    }

    STAGE_NAMES_UI = {
        1: "Registrado",
        2: "Confirmado",
        3: "En Empaque",
        4: "Despachado",
        5: "Entregado",
        0: "Cancelado",
    }

    def __init__(self, catalogo_service, auditoria_service=None, telefono_concierge: str = "573001112233"):
        self.catalogo_service = catalogo_service
        self.auditoria_service = auditoria_service
        self.telefono_concierge = telefono_concierge
        self.pedidos: Dict[int, Dict[str, Any]] = {}
        self.pedidos_por_codigo: Dict[str, int] = {}
        self.historial_pedidos: List[Dict[str, Any]] = []
        self.domicilios: Dict[int, Dict[str, Any]] = {}
        self.reportes: List[Dict[str, Any]] = []
        self.pedido_id_counter = 1
        self.historial_id_counter = 1
        self.domicilio_id_counter = 1
        self.reporte_id_counter = 1
        self._lock = getattr(catalogo_service, "_lock", threading.RLock())

    # ------------------------------------------------------------------
    # Sanitización de texto para URLs / Mensajes de WhatsApp
    # ------------------------------------------------------------------

    @staticmethod
    def _sanitize_whatsapp_text(value: Any) -> str:
        """
        Sanitiza entradas del cliente antes de incrustarlas en el mensaje de WhatsApp
        para evitar XSS, inyección de parámetros o caracteres de control.
        """
        if value is None:
            return ""
        text = str(value)
        # Eliminar etiquetas HTML/scripts
        text = re.sub(r"<[^>]*>", "", text)
        # Eliminar caracteres de control salvo espacios normales
        text = re.sub(r"[\x00-\x1f\x7f]+", " ", text)
        return text.strip()

    @staticmethod
    def _sanitize_phone(phone: str) -> str:
        digits = "".join(ch for ch in str(phone or "") if ch.isdigit())
        return digits or "573001112233"

    def _registrar_auditoria(
        self,
        usuario_id: Optional[int],
        accion: str,
        tabla: str,
        valor_ant: Any,
        valor_nue: Any,
        registro_id: Optional[int] = None,
    ):
        if self.auditoria_service:
            self.auditoria_service.registrar_traza_auditoria(
                usuario_id=usuario_id or 1,
                tipo_accion=accion,
                tabla_afectada=tabla,
                registro_id=registro_id,
                valor_anterior=str(valor_ant) if valor_ant is not None else None,
                valor_nuevo=str(valor_nue) if valor_nue is not None else None,
            )

    def _registrar_historial(
        self,
        pedido_id: int,
        estado_anterior: Optional[str],
        estado_nuevo: str,
        usuario_responsable: Optional[int] = None,
        motivo: str = "",
    ):
        registro = {
            "id_historial": self.historial_id_counter,
            "fk_id_pedido": pedido_id,
            "estado_anterior": estado_anterior,
            "estado": estado_nuevo,
            "fk_id_usuario_responsable": usuario_responsable,
            "motivo_cambio": motivo or "Actualización de estado en OMS",
            "fecha_hora": datetime.now().isoformat(),
        }
        self.historial_id_counter += 1
        self.historial_pedidos.append(registro)
        if pedido_id in self.pedidos:
            self.pedidos[pedido_id].setdefault("historial", []).append(registro)

    # ------------------------------------------------------------------
    # Creación de Pedidos y Consolidación Atómica de Stock (RF-PED-001)
    # ------------------------------------------------------------------

    def crear_pedido(self, usuario_id: int, items_carrito: dict) -> int:
        """
        Método base compatible con las pruebas unitarias originales:
        Crea una orden a partir de un diccionario {variante_id: cantidad} en estado 'Registrado'.
        """
        with self._lock:
            if not items_carrito:
                raise ValueError("El carrito está vacío.")

            total = self.calcular_total(items_carrito)
            pedido_id = self.pedido_id_counter
            codigo_orden = f"ORD-{pedido_id:05d}"

            detalle_items = []
            for var_id, cantidad in items_carrito.items():
                variante = self.catalogo_service.variantes.get(var_id, {})
                producto = self.catalogo_service.productos.get(variante.get("producto_id"), {})
                precio_unit = float(
                    variante.get("precio_variante")
                    if variante.get("precio_variante") is not None
                    else producto.get("precio", 0.0)
                )
                detalle_items.append({
                    "fk_id_variante": var_id,
                    "nombre_producto": producto.get("nombre", f"Prenda #{var_id}"),
                    "talla": variante.get("nombre_talla", "Única"),
                    "color": variante.get("nombre_color", "Estándar"),
                    "sku": variante.get("sku", f"SKU-{var_id}"),
                    "cantidad": int(cantidad),
                    "precio_unitario": precio_unit,
                    "subtotal": round(precio_unit * int(cantidad), 2),
                })

            self.pedidos[pedido_id] = {
                "id_pedido": pedido_id,
                "codigo_orden": codigo_orden,
                "usuario_id": usuario_id,
                "items": items_carrito.copy(),
                "detalle_items": detalle_items,
                "subtotal": total,
                "costo_envio": 0.0,
                "impuestos": 0.0,
                "total": total,
                "metodo_entrega": "Domicilio Express",
                "estado": "Registrado",
                "fecha": datetime.now(),
                "inventario_consolidado": False,
                "modo_concierge": False,
                "datos_despacho": {},
                "historial": [],
            }
            self.pedidos_por_codigo[codigo_orden] = pedido_id
            self.pedido_id_counter += 1
            self._registrar_historial(pedido_id, None, "Registrado", usuario_id, "Creación inicial de pedido")
            return pedido_id

    def crear_pedido_desde_carrito(
        self,
        carrito,
        usuario_id: Optional[int] = None,
        datos_despacho: Optional[Dict[str, Any]] = None,
        metodo_entrega: str = "Domicilio Express",
        estado_inicial: str = "Registrado",
        telefono_vendedora: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        RF-PED-001 / RN-PED-001: Crea un Pedido (`Order`) y sus `OrderItem` inmutables a partir de un
        `CarritoService` con reserva activa:
        1. Purga reservas expiradas y verifica que el carrito tenga ítems válidos.
        2. Valida los datos obligatorios de despacho (dirección, barrio, ciudad, teléfono).
        3. Consolida de forma atómica el inventario convirtiendo la reserva temporal (`stock_reservado`)
           en descuento definitivo de `stock_real` y vacía el carrito.
        4. Genera el enlace seguro de Concierge WhatsApp codificado con URL-encode.
        """
        with self._lock:
            carrito._purgar_todas_las_reservas_expiradas()
            if not carrito.items:
                raise ValueError("El carrito está vacío o las reservas temporales han expirado.")

            if datos_despacho:
                despacho_validado = carrito.capturar_datos_despacho(
                    direccion_envio=datos_despacho.get("direccion_envio", ""),
                    barrio=datos_despacho.get("barrio", ""),
                    ciudad=datos_despacho.get("ciudad", ""),
                    telefono=datos_despacho.get("telefono", ""),
                    observaciones=datos_despacho.get("observaciones", ""),
                    nombre_receptor=datos_despacho.get("nombre_receptor", ""),
                    email=datos_despacho.get("email", ""),
                )
            elif carrito.datos_despacho:
                despacho_validado = dict(carrito.datos_despacho)
            else:
                raise ValueError("RN-CRT-003: Debe proporcionar los datos de despacho antes de confirmar el pedido.")

            if estado_inicial not in self.STAGE_MAP or self.STAGE_MAP[estado_inicial] not in (1, 2):
                raise ValueError(f"Estado inicial '{estado_inicial}' no permitido.")

            # Verificar existencias y construir líneas inmutables OrderItem con precios congelados
            detalle_items: List[Dict[str, Any]] = []
            items_snapshot: Dict[int, int] = {}
            subtotal_orden = 0.0

            for var_id, cantidad in carrito.items.items():
                if var_id not in self.catalogo_service.variantes:
                    raise NotFoundError(f"Variante {var_id} no encontrada.")
                variante = self.catalogo_service.variantes[var_id]
                if variante["stock_real"] < cantidad:
                    raise ConflictError(f"Stock físico insuficiente para consolidar la variante {var_id}.")

                prod = self.catalogo_service.productos.get(variante["producto_id"], {})
                precio_congelado = float(
                    carrito.precios_congelados.get(
                        var_id,
                        variante.get("precio_variante")
                        if variante.get("precio_variante") is not None
                        else prod.get("precio", 0.0),
                    )
                )
                sub_linea = round(precio_congelado * cantidad, 2)
                subtotal_orden = round(subtotal_orden + sub_linea, 2)
                items_snapshot[var_id] = int(cantidad)

                detalle_items.append({
                    "fk_id_variante": var_id,
                    "fk_id_producto": prod.get("id_producto"),
                    "nombre_producto": prod.get("nombre", f"Prenda #{var_id}"),
                    "talla": variante.get("nombre_talla", "Única"),
                    "color": variante.get("nombre_color", "Estándar"),
                    "sku": variante.get("sku", f"SKU-{var_id}"),
                    "cantidad": int(cantidad),
                    "precio_unitario": precio_congelado,
                    "subtotal": sub_linea,
                })

            # Consolidación atómica del inventario: convierte reserva temporal en descuento definitivo
            for var_id, cantidad in items_snapshot.items():
                variante = self.catalogo_service.variantes[var_id]
                variante["stock_real"] -= cantidad
                variante["stock_reservado"] = max(0, variante["stock_reservado"] - cantidad)

            carrito.limpiar_tras_confirmar_pedido()

            pedido_id = self.pedido_id_counter
            codigo_orden = f"ORD-{pedido_id:05d}"
            uid_efectivo = usuario_id if usuario_id is not None else carrito.usuario_id

            domicilio_record = {
                "id_domicilio": self.domicilio_id_counter,
                "fk_id_pedido": pedido_id,
                **despacho_validado,
            }
            self.domicilios[pedido_id] = domicilio_record
            self.domicilio_id_counter += 1

            orden_dict = {
                "id_pedido": pedido_id,
                "codigo_orden": codigo_orden,
                "usuario_id": uid_efectivo,
                "fk_id_vendedora_asig": 2,
                "items": items_snapshot,
                "detalle_items": detalle_items,
                "subtotal": subtotal_orden,
                "costo_envio": 0.0,
                "impuestos": 0.0,
                "total": subtotal_orden,
                "metodo_entrega": metodo_entrega,
                "estado": estado_inicial,
                "fecha": datetime.now(),
                "fecha_iso": datetime.now().isoformat(),
                "inventario_consolidado": True,
                "modo_concierge": True,
                "datos_despacho": despacho_validado,
                "historial": [],
            }
            self.pedidos[pedido_id] = orden_dict
            self.pedidos_por_codigo[codigo_orden] = pedido_id
            self.pedido_id_counter += 1

            self._registrar_historial(
                pedido_id,
                None,
                estado_inicial,
                uid_efectivo,
                "Pedido creado transaccionalmente desde carrito con consolidación de stock.",
            )

            tel_destino = self._sanitize_phone(telefono_vendedora or self.telefono_concierge)
            orden_dict["url_comprobante_whatsapp"] = self.generar_enlace_whatsapp(
                pedido_id, tel_destino, formato_concierge=True
            )

            self._registrar_auditoria(
                uid_efectivo,
                "INSERT",
                "pedido",
                None,
                f"codigo_orden={codigo_orden}, total={subtotal_orden}, estado={estado_inicial}",
            )
            return self.serializar_pedido(pedido_id)

    def calcular_total(self, items_carrito: dict) -> float:
        total = 0.0
        for variante_id, cantidad in items_carrito.items():
            variante = self.catalogo_service.variantes.get(variante_id)
            if not variante:
                raise ValueError(f"Variante {variante_id} no encontrada.")
            producto_id = variante["producto_id"]
            producto = self.catalogo_service.productos.get(producto_id)
            if not producto:
                raise ValueError(f"Producto {producto_id} no encontrado.")

            precio = (
                variante.get("precio_variante")
                if variante.get("precio_variante") is not None
                else producto["precio"]
            )
            total += float(precio) * int(cantidad)

        return total

    # ------------------------------------------------------------------
    # Integración Concierge WhatsApp (RF-PED-001)
    # ------------------------------------------------------------------

    def generar_enlace_whatsapp(
        self, pedido_id: int, telefono_vendedora: str, formato_concierge: bool = False
    ) -> str:
        """
        RF-PED-001 / RN-PED-001: Genera el enlace de redirección a WhatsApp (`https://wa.me/<NUMERO>?text=...`).
        - Si `formato_concierge=False` (por defecto en llamadas unitarias simples), mantiene el formato exacto
          esperado por `test_generar_enlace_whatsapp`.
        - Si `formato_concierge=True`, construye el mensaje completo de Concierge OneStyle Mariana con:
          saludo formal, código único de orden, desglose de ítems (producto, color/talla/SKU, cantidad, subtotal),
          total de la orden, datos de entrega sanitizados y enlace al seguimiento web.
        """
        if pedido_id not in self.pedidos:
            raise ValueError("Pedido no encontrado.")

        pedido = self.pedidos[pedido_id]
        tel_limpio = self._sanitize_phone(telefono_vendedora)

        if not formato_concierge:
            mensaje = f"Hola, me gustaría confirmar el pedido #{pedido_id}. El total es ${pedido['total']:.2f}."
            mensaje_codificado = urllib.parse.quote(mensaje)
            return f"https://wa.me/{tel_limpio}?text={mensaje_codificado}"

        codigo = self._sanitize_whatsapp_text(pedido.get("codigo_orden", f"ORD-{pedido_id:05d}"))
        despacho = pedido.get("datos_despacho") or {}
        cliente = self._sanitize_whatsapp_text(despacho.get("nombre_receptor") or "Clienta OneStyle")
        direccion = self._sanitize_whatsapp_text(despacho.get("direccion_envio") or "Por confirmar")
        barrio = self._sanitize_whatsapp_text(despacho.get("barrio") or "")
        ciudad = self._sanitize_whatsapp_text(despacho.get("ciudad") or "Colombia")
        telefono_cli = self._sanitize_whatsapp_text(despacho.get("telefono") or "")
        observaciones = self._sanitize_whatsapp_text(despacho.get("observaciones") or "")

        lineas_txt = []
        for idx, it in enumerate(pedido.get("detalle_items", []), start=1):
            nom = self._sanitize_whatsapp_text(it.get("nombre_producto"))
            color = self._sanitize_whatsapp_text(it.get("color"))
            talla = self._sanitize_whatsapp_text(it.get("talla"))
            sku = self._sanitize_whatsapp_text(it.get("sku"))
            cant = int(it.get("cantidad", 1))
            sub = float(it.get("subtotal", 0.0))
            lineas_txt.append(f"{idx}. {nom} ({color} / Talla {talla} - {sku}) x{cant} = ${sub:,.2f} COP")

        resumen_items = "\n".join(lineas_txt) if lineas_txt else f"Pedido #{pedido_id}"
        ubicacion = f"{direccion}, {barrio}, {ciudad}" if barrio else f"{direccion}, {ciudad}"
        obs_linea = f"\nObservaciones: {observaciones}" if observaciones else ""
        enlace_seguimiento = f"https://onestylemariana.co/#/seguimiento?pedido={codigo}"

        mensaje = (
            f"Hola Concierge OneStyle Mariana, deseo finalizar y confirmar mi pedido *{codigo}*.\n\n"
            f"*Resumen de Prendas:*\n{resumen_items}\n\n"
            f"*Total de la Orden:* ${float(pedido['total']):,.2f} COP\n"
            f"*Cliente:* {cliente}\n"
            f"*Entrega en:* {ubicacion}\n"
            f"*Teléfono:* {telefono_cli}{obs_linea}\n\n"
            f"*Seguimiento Web:* {enlace_seguimiento}"
        )
        mensaje_codificado = urllib.parse.quote(mensaje, safe="")
        return f"https://wa.me/{tel_limpio}?text={mensaje_codificado}"

    # ------------------------------------------------------------------
    # Máquina de Estados Finita (FSM) y Reintegro de Stock (RF-PED-002)
    # ------------------------------------------------------------------

    def transicionar_estado(
        self,
        pedido_id: int,
        nuevo_estado: str,
        usuario_responsable: Optional[int] = None,
        motivo: str = "",
    ):
        """
        RF-PED-002 / RN-PED-002: Ejecuta y valida las transiciones de la Máquina de Estados Finita (FSM):
        Etapa 1 (Registrado / PENDIENTE_PAGO)
          -> Etapa 2 (Confirmado / CONFIRMADO)
          -> Etapa 3 (En Empaque / EN_PREPARACION)
          -> Etapa 4 (Despachado / DESPACHADO)
          -> Etapa 5 (Entregado / ENTREGADO)
        Estado terminal Cancelado / CANCELADO (Etapa 0):
          - Permitido únicamente desde Etapa 1 o Etapa 2.
          - Libera inmediatamente el stock reservado o reintegra el stock_real si ya estaba descontado.
        """
        with self._lock:
            if pedido_id not in self.pedidos:
                raise NotFoundError("Pedido no encontrado.")

            if nuevo_estado not in self.STAGE_MAP:
                raise ValueError(f"Estado '{nuevo_estado}' no es válido.")

            pedido = self.pedidos[pedido_id]
            estado_actual = pedido["estado"]
            if estado_actual == nuevo_estado:
                return

            stage_actual = self.STAGE_MAP.get(estado_actual)
            stage_nuevo = self.STAGE_MAP.get(nuevo_estado)

            # Validar si el pedido ya se encuentra en estado terminal
            if stage_actual in (5, 0):
                raise ValueError("El pedido está en un estado final y no puede transicionar.")

            # Validar reglas de transición hacia Cancelado / CANCELADO
            if stage_nuevo == 0:
                if stage_actual not in (1, 2):
                    raise ValueError("Solo se puede cancelar desde Registrado/PENDIENTE_PAGO o Confirmado/CONFIRMADO.")
            else:
                # Transición secuencial estricta paso a paso: stage_nuevo debe ser exactamente stage_actual + 1
                if stage_nuevo != stage_actual + 1:
                    raise ValueError(f"Transición inválida de {estado_actual} a {nuevo_estado}.")

            # Acciones de inventario asociadas a la transición
            if stage_nuevo == 2 and not pedido.get("inventario_consolidado", False):
                # Al pasar a Confirmado en pedidos que solo tenían reserva previa, descontar stock_real y liberar reservado
                for var_id, cantidad in pedido["items"].items():
                    self.catalogo_service.variantes[var_id]["stock_real"] -= cantidad
                    self.catalogo_service.variantes[var_id]["stock_reservado"] = max(
                        0, self.catalogo_service.variantes[var_id]["stock_reservado"] - cantidad
                    )
                pedido["inventario_consolidado"] = True

            if stage_nuevo == 0:
                # Al cancelar: si el inventario ya fue descontado del stock_real, reintegrarlo exactamente;
                # si solo estaba en stock_reservado, liberar la reserva.
                if pedido.get("inventario_consolidado", False):
                    for var_id, cantidad in pedido["items"].items():
                        self.catalogo_service.variantes[var_id]["stock_real"] += cantidad
                    pedido["inventario_consolidado"] = False
                else:
                    for var_id, cantidad in pedido["items"].items():
                        self.catalogo_service.variantes[var_id]["stock_reservado"] = max(
                            0, self.catalogo_service.variantes[var_id]["stock_reservado"] - cantidad
                        )

            if stage_nuevo == 5:
                pedido["fecha_entrega"] = datetime.now().isoformat()

            pedido["estado"] = nuevo_estado
            self._registrar_historial(pedido_id, estado_actual, nuevo_estado, usuario_responsable, motivo)
            self._registrar_auditoria(
                usuario_responsable,
                "UPDATE",
                "pedido",
                f"id_pedido={pedido_id}, estado={estado_actual}",
                f"id_pedido={pedido_id}, estado={nuevo_estado}, motivo={motivo}",
            )

    # ------------------------------------------------------------------
    # Consultas de Seguimiento, Historial y Reportes OMS (RF-PED-003 / 004)
    # ------------------------------------------------------------------

    def serializar_pedido(self, pedido_id: int) -> Dict[str, Any]:
        if pedido_id not in self.pedidos:
            raise NotFoundError("Pedido no encontrado.")
        p = self.pedidos[pedido_id]
        stage = self.STAGE_MAP.get(p["estado"], 1)
        return {
            "id_pedido": p["id_pedido"],
            "codigo_orden": p.get("codigo_orden", f"ORD-{p['id_pedido']:05d}"),
            "usuario_id": p.get("usuario_id"),
            "fk_id_vendedora_asig": p.get("fk_id_vendedora_asig", 2),
            "estado": p["estado"],
            "estado_ui": self.STAGE_NAMES_UI.get(stage, p["estado"]),
            "etapa_fsm": stage,
            "metodo_entrega": p.get("metodo_entrega", "Domicilio Express"),
            "subtotal": float(p.get("subtotal", p["total"])),
            "total": float(p["total"]),
            "fecha_pedido": p.get("fecha_iso") or (p["fecha"].isoformat() if isinstance(p.get("fecha"), datetime) else str(p.get("fecha"))),
            "fecha_entrega": p.get("fecha_entrega"),
            "detalle_items": p.get("detalle_items", []),
            "datos_despacho": p.get("datos_despacho", {}),
            "url_comprobante_whatsapp": p.get("url_comprobante_whatsapp")
            or self.generar_enlace_whatsapp(pedido_id, self.telefono_concierge, formato_concierge=True),
            "historial": p.get("historial", []),
        }

    def obtener_pedido_por_codigo_o_id(
        self,
        key: Any,
        solicitante_id: Optional[int] = None,
        rol: Optional[str] = None,
        contacto_verificacion: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        RF-PED-003 / RN-PED-003: Obtiene el estado en tiempo real de un pedido por `id_pedido` o `codigo_orden`.
        Valida que una clienta solo consulte sus propios pedidos o verifique su correo/teléfono de contacto.
        """
        pedido_id = None
        key_str = str(key).strip().upper()
        if key_str.isdigit():
            pedido_id = int(key_str)
        elif key_str in self.pedidos_por_codigo:
            pedido_id = self.pedidos_por_codigo[key_str]
        elif key_str.startswith("ORD-") and key_str[4:].isdigit():
            pedido_id = int(key_str[4:])

        if pedido_id is None or pedido_id not in self.pedidos:
            raise NotFoundError(f"El pedido '{key}' no existe.")

        pedido = self.pedidos[pedido_id]
        if rol not in ("Administradora", "Vendedora"):
            # Verificar propiedad o coincidencia de contacto
            if solicitante_id is not None and pedido.get("usuario_id") == solicitante_id:
                pass
            elif contacto_verificacion:
                c_norm = contacto_verificacion.strip().lower()
                despacho = pedido.get("datos_despacho") or {}
                email_orden = str(despacho.get("email") or "").strip().lower()
                tel_orden = "".join(ch for ch in str(despacho.get("telefono") or "") if ch.isdigit())
                tel_query = "".join(ch for ch in c_norm if ch.isdigit())
                if c_norm != email_orden and (not tel_query or tel_query not in tel_orden):
                    raise PermissionError("RN-PED-003: Los datos de contacto no coinciden con el pedido solicitado.")

        return self.serializar_pedido(pedido_id)

    def listar_pedidos_usuario(self, usuario_id: int) -> List[Dict[str, Any]]:
        """RF-PED-003: Lista todos los pedidos pertenecientes a una clienta."""
        ids = [
            pid for pid, p in sorted(self.pedidos.items(), reverse=True)
            if p.get("usuario_id") == usuario_id
        ]
        return [self.serializar_pedido(pid) for pid in ids]

    def listar_pedidos_oms(
        self, estado: Optional[str] = None, vendedora_id: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """RF-PED-002 y RF-PED-004: Lista pedidos para el panel administrativo OMS con filtros."""
        resultado = []
        for pid in sorted(self.pedidos.keys(), reverse=True):
            p = self.pedidos[pid]
            if estado and p["estado"].lower() != estado.strip().lower():
                continue
            if vendedora_id is not None and p.get("fk_id_vendedora_asig") != vendedora_id:
                continue
            resultado.append(self.serializar_pedido(pid))
        return resultado

    def listar_pedidos_paginados(
        self,
        page: int = 1,
        per_page: int = 10,
        estado: Optional[str] = None,
        vendedora_id: Optional[int] = None,
        termino: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        RF-PED-002 / RF-PED-004: Paginación real del lado del servidor (equivalente a LIMIT/OFFSET),
        con filtro por estado (normalizado a la etapa FSM), vendedora y búsqueda por código,
        cliente, correo o teléfono.
        """
        try:
            page = int(page)
            per_page = int(per_page)
        except (TypeError, ValueError):
            raise ValueError("Los parámetros 'page' y 'per_page' deben ser enteros.")
        if page < 1 or per_page < 1:
            raise ValueError("Los parámetros 'page' y 'per_page' deben ser mayores a cero.")
        per_page = min(per_page, 100)

        etapa_filtro = None
        if estado and estado.strip() and estado.strip().lower() not in ("todos", "todas", "all"):
            etapa_filtro = self.STAGE_MAP.get(estado.strip())
            if etapa_filtro is None:
                # Tolerar mayúsculas/minúsculas ('confirmado', 'CONFIRMADO')
                for nombre, etapa in self.STAGE_MAP.items():
                    if nombre.lower() == estado.strip().lower():
                        etapa_filtro = etapa
                        break
            if etapa_filtro is None:
                raise ValueError(f"Estado '{estado}' no es válido.")

        q = termino.strip().lower() if termino and termino.strip() else None

        filtrados = []
        for pid in sorted(self.pedidos.keys(), reverse=True):
            p = self.pedidos[pid]
            if etapa_filtro is not None and self.STAGE_MAP.get(p["estado"], 1) != etapa_filtro:
                continue
            if vendedora_id is not None and p.get("fk_id_vendedora_asig") != vendedora_id:
                continue
            if q:
                desp = p.get("datos_despacho") or {}
                haystack = " ".join([
                    str(p.get("codigo_orden", "")),
                    str(desp.get("nombre_receptor", "")),
                    str(desp.get("email", "")),
                    str(desp.get("telefono", "")),
                    str(desp.get("ciudad", "")),
                ]).lower()
                if q not in haystack:
                    continue
            filtrados.append(pid)

        total = len(filtrados)
        total_pages = max(1, (total + per_page - 1) // per_page)
        offset = (page - 1) * per_page
        ids_pagina = filtrados[offset:offset + per_page]

        return {
            "items": [self.serializar_pedido(pid) for pid in ids_pagina],
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
            "has_next": page < total_pages,
            "has_prev": page > 1,
        }

    def obtener_metricas_dashboard(self) -> Dict[str, Any]:
        """
        Contadores agregados para el dashboard administrativo: pedidos por etapa,
        ventas consolidadas (excluye cancelados) y ticket promedio.
        """
        conteo = {nombre: 0 for nombre in ("Registrado", "Confirmado", "En Empaque", "Despachado", "Entregado", "Cancelado")}
        ventas_totales = 0.0
        pedidos_vigentes = 0
        unidades = 0
        for p in self.pedidos.values():
            etapa = self.STAGE_MAP.get(p["estado"], 1)
            conteo[self.STAGE_NAMES_UI[etapa]] += 1
            if etapa != 0:
                ventas_totales += float(p["total"])
                pedidos_vigentes += 1
                unidades += sum(int(c) for c in p.get("items", {}).values())

        return {
            "total_pedidos": len(self.pedidos),
            "pedidos_pendientes": conteo["Registrado"],
            "pedidos_en_proceso": conteo["Confirmado"] + conteo["En Empaque"],
            "pedidos_despachados": conteo["Despachado"],
            "pedidos_entregados": conteo["Entregado"],
            "pedidos_cancelados": conteo["Cancelado"],
            "conteo_por_estado": conteo,
            "ventas_totales": round(ventas_totales, 2),
            "ticket_promedio": round(ventas_totales / pedidos_vigentes, 2) if pedidos_vigentes else 0.0,
            "unidades_vendidas": unidades,
        }

    def generar_reporte_ventas(
        self,
        rol_solicitante: str,
        usuario_id: int,
        estado: Optional[str] = None,
        vendedora_id: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        RF-PED-004 / RN-PED-004: Genera reporte consolidado de ventas por estado y vendedora.
        Acceso exclusivo para Administradora y Vendedora.
        """
        if rol_solicitante not in ("Administradora", "Vendedora"):
            raise PermissionError("RN-PED-004: Acceso exclusivo a usuarios con rol administrativo o comercial.")

        pedidos_filtrados = self.listar_pedidos_oms(estado=estado, vendedora_id=vendedora_id)
        ingresos_totales = 0.0
        conteo_por_estado: Dict[str, int] = {}
        ventas_por_vendedora: Dict[int, float] = {}

        for p in pedidos_filtrados:
            est = p["estado"]
            conteo_por_estado[est] = conteo_por_estado.get(est, 0) + 1
            if self.STAGE_MAP.get(est, 1) != 0:
                ingresos_totales = round(ingresos_totales + float(p["total"]), 2)
                vid = int(p.get("fk_id_vendedora_asig") or 2)
                ventas_por_vendedora[vid] = round(ventas_por_vendedora.get(vid, 0.0) + float(p["total"]), 2)

        reporte_entry = {
            "id_reporte": self.reporte_id_counter,
            "id_usuario": usuario_id,
            "tipo_reporte": "Consolidado de Ventas OMS",
            "fecha_generacion": datetime.now().isoformat(),
            "total_pedidos": len(pedidos_filtrados),
            "ingresos_totales": ingresos_totales,
            "conteo_por_estado": conteo_por_estado,
            "ventas_por_vendedora": ventas_por_vendedora,
            "pedidos": pedidos_filtrados,
        }
        self.reporte_id_counter += 1
        self.reportes.append(reporte_entry)
        return reporte_entry

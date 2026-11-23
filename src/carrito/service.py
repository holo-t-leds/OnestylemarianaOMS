# src/carrito/service.py
import threading
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from src.catalogo.service import ConflictError, NotFoundError


class CarritoService:
    """
    Servicio de Carrito de Compras y Reservas Temporales de Stock con TTL (RF-CRT-001 a RF-CRT-003).
    Implementa control de concurrencia atómico (RNF-002), evaluación perezosa de expiración TTL (RN-CRT-001)
    y captura obligatoria de datos de despacho (RN-CRT-003).
    """

    DEFAULT_TTL_MINUTES = 15

    # Consultas SQL Parametrizadas (OWASP A03)
    SQL_SELECT_FOR_UPDATE_STOCK = """
        SELECT id_inventario, fk_id_variante, stock_real, stock_reservado
        FROM inventario
        WHERE fk_id_variante = %s
        FOR UPDATE;
    """
    SQL_INSERT_RESERVA = """
        INSERT INTO inventario_reserva (fk_id_variante, fk_id_carrito, fk_id_usuario, session_id, cantidad_reservada, expires_at, estado)
        VALUES (%s, %s, %s, %s, %s, %s, 'activa');
    """
    SQL_LIBERAR_RESERVA = """
        UPDATE inventario_reserva
        SET estado = 'liberada'
        WHERE fk_id_carrito = %s AND fk_id_variante = %s AND estado = 'activa';
    """

    def __init__(
        self,
        catalogo_service,
        usuario_id: Optional[int] = None,
        session_id: Optional[str] = None,
        ttl_minutos: int = DEFAULT_TTL_MINUTES
    ):
        self.catalogo_service = catalogo_service
        self.usuario_id = usuario_id
        self.session_id = session_id or "default-session"
        self.ttl_minutos = int(ttl_minutos)

        self.items: Dict[int, int] = {}                # variante_id: cantidad
        self.timestamps: Dict[int, datetime] = {}      # variante_id: expires_at
        self.precios_congelados: Dict[int, float] = {} # variante_id: precio unitario congelado al añadir
        self.reservas: Dict[int, Dict[str, Any]] = {}  # variante_id: StockReservation metadata
        self.datos_despacho: Optional[Dict[str, str]] = None

        # Asegurar lock compartido y registro global de carritos en catalogo_service para concurrencia y TTL
        if not hasattr(self.catalogo_service, "_lock"):
            self.catalogo_service._lock = threading.RLock()
        if not hasattr(self.catalogo_service, "_carritos_registrados"):
            self.catalogo_service._carritos_registrados = []
        self.catalogo_service._carritos_registrados.append(self)

    def _get_lock(self) -> threading.RLock:
        return getattr(self.catalogo_service, "_lock", threading.RLock())

    def _purgar_todas_las_reservas_expiradas(self):
        """
        Evaluación perezosa global (RN-CRT-001): Libera automáticamente las reservas cuyo TTL haya expirado
        en cualquier carrito antes de validar disponibilidad de stock.
        """
        carritos = getattr(self.catalogo_service, "_carritos_registrados", [self])
        for c in list(carritos):
            c.purgar_reservas_expiradas(self.ttl_minutos)

    def _obtener_precio_unitario_variante(self, variante_id: int) -> float:
        var = self.catalogo_service.variantes.get(variante_id)
        if not var:
            raise NotFoundError("Variante no encontrada")
        if var.get("precio_variante") is not None:
            return float(var["precio_variante"])
        prod = self.catalogo_service.productos.get(var["producto_id"], {})
        return float(prod.get("precio", 0.0))

    def agregar_item(self, variante_id: int, cantidad: int) -> int:
        """
        RF-CRT-001 / RN-CRT-001: Agrega unidades al carrito con validación atómica
        StockDisponible = StockFisico - StockReservado, congela el precio unitario y asigna TTL.
        """
        if cantidad is None or int(cantidad) <= 0:
            raise ValueError("La cantidad debe ser mayor a cero.")
        cantidad = int(cantidad)

        with self._get_lock():
            self._purgar_todas_las_reservas_expiradas()

            if variante_id not in self.catalogo_service.variantes:
                raise NotFoundError("Variante no encontrada.")

            stock_disponible = self.catalogo_service.consultar_disponibilidad(variante_id)
            current_quantity = self.items.get(variante_id, 0)

            if cantidad > stock_disponible:
                raise ConflictError(f"Stock insuficiente. Solo hay {stock_disponible} unidades disponibles.")

            # Congelar precio unitario en la primera adición al carrito
            if variante_id not in self.precios_congelados:
                self.precios_congelados[variante_id] = self._obtener_precio_unitario_variante(variante_id)

            now = datetime.now()
            expires_at = now + timedelta(minutes=self.ttl_minutos)
            nueva_cantidad = current_quantity + cantidad

            self.items[variante_id] = nueva_cantidad
            self.timestamps[variante_id] = expires_at
            self.reservas[variante_id] = {
                "fk_id_variante": variante_id,
                "fk_id_usuario": self.usuario_id,
                "session_id": self.session_id,
                "cantidad_reservada": nueva_cantidad,
                "created_at": now,
                "expires_at": expires_at,
                "estado": "activa"
            }

            # Incrementar atómicamente stock reservado
            self.catalogo_service.variantes[variante_id]['stock_reservado'] += cantidad
            return self.items[variante_id]

    def agregar_al_carrito(self, variante_id: int, cantidad: int) -> int:
        return self.agregar_item(variante_id, cantidad)

    def modificar_cantidad_carrito(self, variante_id: int, cantidad: int) -> int:
        """
        RF-CRT-002 / RN-CRT-002: Modifica cantidad de prenda en el carrito, ajustando o liberando
        atómicamente la reserva temporal y recalculando subtotales.
        """
        if cantidad is None or int(cantidad) <= 0:
            raise ValueError("La cantidad debe ser mayor a cero.")
        cantidad = int(cantidad)

        with self._get_lock():
            self._purgar_todas_las_reservas_expiradas()

            if variante_id not in self.catalogo_service.variantes:
                raise NotFoundError("Variante no encontrada.")

            current_quantity = self.items.get(variante_id, 0)
            difference = cantidad - current_quantity

            if difference > 0:
                stock_disponible = self.catalogo_service.consultar_disponibilidad(variante_id)
                if difference > stock_disponible:
                    raise ConflictError(
                        f"Stock insuficiente. Solo hay {stock_disponible} unidades disponibles para añadir."
                    )
                self.catalogo_service.variantes[variante_id]['stock_reservado'] += difference
            elif difference < 0:
                self.catalogo_service.variantes[variante_id]['stock_reservado'] = max(
                    0, self.catalogo_service.variantes[variante_id]['stock_reservado'] + difference
                )

            if variante_id not in self.precios_congelados:
                self.precios_congelados[variante_id] = self._obtener_precio_unitario_variante(variante_id)

            now = datetime.now()
            expires_at = now + timedelta(minutes=self.ttl_minutos)
            self.items[variante_id] = cantidad
            self.timestamps[variante_id] = expires_at
            self.reservas[variante_id] = {
                "fk_id_variante": variante_id,
                "fk_id_usuario": self.usuario_id,
                "session_id": self.session_id,
                "cantidad_reservada": cantidad,
                "created_at": now,
                "expires_at": expires_at,
                "estado": "activa"
            }
            return self.items[variante_id]

    def remover_item(self, variante_id: int, cantidad: Optional[int] = None):
        """
        RF-CRT-002 / RN-CRT-002: Remueve parcial o totalmente un ítem liberando de inmediato su reserva.
        """
        with self._get_lock():
            if variante_id not in self.items:
                return

            current_quantity = self.items[variante_id]
            if cantidad is None or int(cantidad) >= current_quantity:
                if variante_id in self.catalogo_service.variantes:
                    self.catalogo_service.variantes[variante_id]['stock_reservado'] = max(
                        0, self.catalogo_service.variantes[variante_id]['stock_reservado'] - current_quantity
                    )
                del self.items[variante_id]
                self.timestamps.pop(variante_id, None)
                self.precios_congelados.pop(variante_id, None)
                if variante_id in self.reservas:
                    self.reservas[variante_id]["estado"] = "liberada"
                    del self.reservas[variante_id]
            else:
                cant_int = int(cantidad)
                if variante_id in self.catalogo_service.variantes:
                    self.catalogo_service.variantes[variante_id]['stock_reservado'] = max(
                        0, self.catalogo_service.variantes[variante_id]['stock_reservado'] - cant_int
                    )
                self.items[variante_id] -= cant_int
                if variante_id in self.reservas:
                    self.reservas[variante_id]["cantidad_reservada"] = self.items[variante_id]

    def purgar_reservas_expiradas(self, tiempo_limite_minutos: int = 15):
        """
        RN-CRT-001: Libera automáticamente las reservas cuyo timestamp haya vencido.
        """
        with self._get_lock():
            now = datetime.now()
            variantes_a_remover = []
            for var_id, expires_at in list(self.timestamps.items()):
                reserva = self.reservas.get(var_id)
                exp_efectiva = reserva["expires_at"] if reserva and "expires_at" in reserva else expires_at
                if now > exp_efectiva:
                    variantes_a_remover.append(var_id)

            for var_id in variantes_a_remover:
                self.remover_item(var_id)

    def vaciar_carrito(self):
        with self._get_lock():
            for var_id in list(self.items.keys()):
                self.remover_item(var_id)

    def get_items(self) -> Dict[int, int]:
        with self._get_lock():
            self._purgar_todas_las_reservas_expiradas()
            return self.items.copy()

    def obtener_resumen(self) -> Dict[str, Any]:
        """
        RF-CRT-001 y RF-CRT-002: Construye el desglose detallado del carrito con precios congelados,
        subtotales por línea, total consolidado y tiempo restante de reserva (TTL).
        """
        with self._get_lock():
            self._purgar_todas_las_reservas_expiradas()
            now = datetime.now()
            lineas = []
            subtotal_general = 0.0
            total_unidades = 0
            min_ttl_segundos = 0

            for var_id, cantidad in self.items.items():
                var = self.catalogo_service.variantes.get(var_id, {})
                prod = self.catalogo_service.productos.get(var.get("producto_id"), {})
                precio_unit = self.precios_congelados.get(
                    var_id, self._obtener_precio_unitario_variante(var_id)
                )
                sub = round(precio_unit * cantidad, 2)
                subtotal_general = round(subtotal_general + sub, 2)
                total_unidades += cantidad

                exp_at = self.timestamps.get(var_id, now + timedelta(minutes=self.ttl_minutos))
                ttl_sec = max(0, int((exp_at - now).total_seconds()))
                if min_ttl_segundos == 0 or ttl_sec < min_ttl_segundos:
                    min_ttl_segundos = ttl_sec

                talla_str = var.get("nombre_talla", "Única")
                color_str = var.get("nombre_color", "Estándar")
                sku_str = var.get("sku", f"SKU-{var_id}")

                lineas.append({
                    "id_variante": var_id,
                    "fk_id_variante": var_id,
                    "id_producto": prod.get("id_producto"),
                    "slug": prod.get("slug", str(prod.get("id_producto", ""))),
                    "nombre_producto": prod.get("nombre", f"Prenda #{var_id}"),
                    "variante_label": f"{color_str} / Talla {talla_str} ({sku_str})",
                    "talla": talla_str,
                    "color": color_str,
                    "sku": sku_str,
                    "img": prod.get("url_imagen_principal"),
                    "cantidad": cantidad,
                    "precio_unitario": precio_unit,
                    "subtotal": sub,
                    "expires_at": exp_at.isoformat(),
                    "ttl_segundos": ttl_sec
                })

            return {
                "items": lineas,
                "subtotal": subtotal_general,
                "total": subtotal_general,
                "total_unidades": total_unidades,
                "ttl_segundos": min_ttl_segundos,
                "datos_despacho": self.datos_despacho
            }

    def capturar_datos_despacho(
        self,
        direccion_envio: str,
        barrio: str,
        ciudad: str,
        telefono: str,
        observaciones: str = "",
        nombre_receptor: str = "",
        email: str = ""
    ) -> Dict[str, str]:
        """
        RF-CRT-003 / RN-CRT-003: Valida y estructura obligatoriamente dirección, barrio, ciudad y teléfono
        antes de remitir el pedido a WhatsApp.
        """
        campos_obligatorios = {
            "direccion_envio": direccion_envio,
            "barrio": barrio,
            "ciudad": ciudad,
            "telefono": telefono
        }
        for campo, valor in campos_obligatorios.items():
            if not valor or not str(valor).strip():
                raise ValueError(f"RN-CRT-003: El campo '{campo}' es obligatorio para los datos de despacho.")

        tel_clean = "".join(ch for ch in str(telefono) if ch.isdigit())
        if len(tel_clean) < 7:
            raise ValueError("RN-CRT-003: El número de teléfono debe contener al menos 7 dígitos válidos.")

        self.datos_despacho = {
            "direccion_envio": str(direccion_envio).strip(),
            "barrio": str(barrio).strip(),
            "ciudad": str(ciudad).strip(),
            "telefono": str(telefono).strip(),
            "observaciones": str(observaciones or "").strip(),
            "nombre_receptor": str(nombre_receptor or "").strip(),
            "email": str(email or "").strip()
        }
        return dict(self.datos_despacho)

    def limpiar_tras_confirmar_pedido(self):
        """
        Marca las reservas como confirmadas y limpia el carrito una vez que PedidosService
        consolida la reserva temporal en descuento definitivo de stock.
        """
        for var_id in list(self.reservas.keys()):
            self.reservas[var_id]["estado"] = "confirmada"
        self.items.clear()
        self.precios_congelados.clear()
        self.timestamps.clear()
        self.reservas.clear()

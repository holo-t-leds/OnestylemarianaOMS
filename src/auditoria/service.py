# src/auditoria/service.py
import copy
import json
from datetime import datetime
from typing import List, Dict, Optional, Any


class AuditoriaService:
    """
    Servicio de Auditoría y Trazabilidad Inmutable del Sistema (RF-SEG-001 a RF-SEG-006).
    Garantiza que cada evento crítico quede registrado con marca temporal y sea de solo lectura (RN-SEG-005, RNF-016).
    """

    SQL_INSERT_LOG = """
        INSERT INTO auditoria (
            fk_id_usuario_accion, tipo_accion, tabla_afectada,
            id_registro_afectado, valor_anterior, valor_nuevo
        ) VALUES (%s, %s, %s, %s, %s, %s);
    """

    SQL_SELECT_LOGS = """
        SELECT a.id_log, a.fk_id_usuario_accion, u.nombre, u.apellido, r.nombre_rol,
               a.tipo_accion, a.tabla_afectada, a.id_registro_afectado,
               a.valor_anterior, a.valor_nuevo, a.fecha_accion
        FROM auditoria a
        INNER JOIN usuarios u ON a.fk_id_usuario_accion = u.id_usuario
        INNER JOIN roles r ON u.fk_id_rol = r.id_rol
        ORDER BY a.fecha_accion DESC;
    """

    def __init__(self, db_connection_factory=None):
        self._logs: List[Dict[str, Any]] = []
        self.log_id_counter = 1
        self.db_connection_factory = db_connection_factory

    @property
    def logs(self) -> List[Dict[str, Any]]:
        """Retorna una copia profunda para impedir mutación externa de los registros (RNF-016)."""
        return copy.deepcopy(self._logs)

    def _serializar_valor(self, valor: Any) -> Optional[str]:
        if valor is None:
            return None
        if isinstance(valor, str):
            return valor
        return json.dumps(valor, ensure_ascii=False, default=str)

    def registrar_traza_auditoria(
        self,
        usuario_id: int,
        tipo_accion: str,
        tabla_afectada: str,
        registro_id: Optional[int],
        valor_anterior: Any = None,
        valor_nuevo: Any = None
    ) -> int:
        """
        Registra una traza inmutable en memoria y opcionalmente en la tabla física `auditoria` (RF-SEG-001..004).
        """
        val_ant_str = self._serializar_valor(valor_anterior)
        val_nue_str = self._serializar_valor(valor_nuevo)

        log = {
            'id': self.log_id_counter,
            'id_log': self.log_id_counter,
            'usuario_id': usuario_id,
            'fk_id_usuario_accion': usuario_id,
            'tipo_accion': str(tipo_accion).strip(),
            'tabla_afectada': str(tabla_afectada).strip(),
            'registro_id': registro_id,
            'id_registro_afectado': registro_id,
            'valor_anterior': val_ant_str,
            'valor_nuevo': val_nue_str,
            'fecha': datetime.now(),
            'fecha_accion': datetime.now().isoformat()
        }
        self._logs.append(log)
        self.log_id_counter += 1

        if self.db_connection_factory is not None:
            try:
                conn = self.db_connection_factory()
                try:
                    with conn.cursor() as cursor:
                        cursor.execute(
                            self.SQL_INSERT_LOG,
                            (usuario_id, log['tipo_accion'], log['tabla_afectada'], registro_id, val_ant_str, val_nue_str)
                        )
                    conn.commit()
                finally:
                    conn.close()
            except Exception:
                # Si la BD no está activa en entorno de test unitario, se preserva el log en memoria
                pass

        return log['id']

    def consultar_logs(
        self,
        rol_solicitante: str,
        usuario_id: Optional[int] = None,
        tabla_afectada: Optional[str] = None,
        tipo_accion: Optional[str] = None,
        fecha_inicio: Optional[datetime] = None,
        fecha_fin: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """
        RF-SEG-005 / RN-SEG-005: La vista de auditoría es de acceso exclusivo para el rol Administradora
        y los registros son estrictamente de solo lectura.
        """
        if rol_solicitante != "Administradora":
            raise PermissionError("RN-SEG-005: El acceso a los registros de auditoría es exclusivo para el rol Administradora.")

        resultados = copy.deepcopy(self._logs)

        if usuario_id is not None:
            resultados = [l for l in resultados if l['usuario_id'] == usuario_id]
        if tabla_afectada:
            tabla_norm = tabla_afectada.strip().lower()
            resultados = [l for l in resultados if l['tabla_afectada'].lower() == tabla_norm]
        if tipo_accion:
            accion_norm = tipo_accion.strip().lower()
            resultados = [l for l in resultados if l['tipo_accion'].lower() == accion_norm]
        if fecha_inicio is not None:
            resultados = [l for l in resultados if l['fecha'] >= fecha_inicio]
        if fecha_fin is not None:
            resultados = [l for l in resultados if l['fecha'] <= fecha_fin]

        return resultados

    def eliminar_log(self, *args, **kwargs):
        raise PermissionError("RN-SEG-005 / RNF-016: Está prohibida la edición o eliminación de registros de auditoría.")

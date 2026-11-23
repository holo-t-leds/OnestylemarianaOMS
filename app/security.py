import html
import re
from functools import wraps
from typing import Dict, Any, Iterable, Optional, Tuple
from flask import request, jsonify


XSS_PATTERN = re.compile(
    r"(<\s*/?\s*(script|iframe|object|embed|svg|link|style|meta)\b|on\w+\s*=|javascript\s*:)",
    re.IGNORECASE
)


def api_response(status: str, message: str, data: Any = None, http_code: int = 200):
    """
    Respuesta HTTP JSON estandarizada sin exponer trazas internas del servidor (OWASP A05).
    """
    payload = {
        "status": status,
        "message": message,
        "data": data
    }
    return jsonify(payload), http_code


def validate_whitelist_payload(
    payload: Any,
    allowed_fields: Iterable[str],
    required_fields: Iterable[str] = ()
) -> Dict[str, Any]:
    """
    Valida y sanitiza estrictamente por lista blanca (whitelist) cualquier carga útil entrante (OWASP A03 / RNF-007).
    - Rechaza campos no autorizados (previene Mass Assignment como inyección de `fk_id_rol`).
    - Detecta y rechaza vectores XSS (`<script>`, `javascript:`, `onerror=`, etc.).
    - Escapa caracteres especiales HTML en cadenas de texto (excepto contraseñas crudas).
    """
    if not isinstance(payload, dict):
        raise ValueError("El cuerpo de la solicitud debe ser un objeto JSON válido.")

    allowed_set = set(allowed_fields)
    required_set = set(required_fields)

    unexpected = set(payload.keys()) - allowed_set
    if unexpected:
        campos_no_permitidos = ", ".join(sorted(unexpected))
        raise ValueError(f"Campos no permitidos en la solicitud (lista blanca): {campos_no_permitidos}")

    for req_field in required_set:
        val = payload.get(req_field)
        if val is None or (isinstance(val, str) and not val.strip()):
            raise ValueError(f"El campo '{req_field}' es obligatorio.")

    sanitized: Dict[str, Any] = {}
    password_fields = {"contrasena", "nueva_password", "confirmar_contrasena"}

    for key, value in payload.items():
        if isinstance(value, str):
            if XSS_PATTERN.search(value) or ("<" in value and ">" in value):
                raise ValueError(f"El campo '{key}' contiene caracteres o etiquetas no permitidas por seguridad.")
            if key in password_fields:
                sanitized[key] = value
            else:
                sanitized[key] = html.escape(value.strip(), quote=True)
        else:
            sanitized[key] = value

    return sanitized


def extract_bearer_token() -> Optional[str]:
    """
    Extrae el token de sesión del encabezado HTTP Authorization: Bearer <token>.
    """
    auth_header = request.headers.get("Authorization", "").strip()
    if auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return None

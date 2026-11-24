"""
Visor de Usuarios Registrados — OneStyleMariana
================================================
Ejecuta este script para ver en tabla todos los usuarios guardados
en la base de datos (`database/onestyle_local.db` o MySQL).
"""

from pathlib import Path
import sys

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.database import get_db_connection, SQLITE_PATH  # noqa: E402


def mostrar_usuarios() -> None:
    ROLES = {1: "Administradora", 2: "Vendedora", 3: "Clienta"}
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Limpiar correos efímeros de pruebas unitarias si existieran
            cur.execute(
                "DELETE FROM usuarios WHERE email IN (%s, %s);",
                ("natalia.test@onestyle.com", "dash.clienta@test.co"),
            )
            conn.commit()

            cur.execute(
                """
                SELECT id_usuario, fk_id_rol, nombre, apellido, email,
                       telefono, estado_usuario
                FROM usuarios
                ORDER BY id_usuario ASC;
                """
            )
            filas = cur.fetchall() or []

        motor = f"SQLite ({SQLITE_PATH})" if hasattr(conn, "_conn") else "MySQL"
        print("=" * 98)
        print(f"USUARIOS EN BASE DE DATOS [{motor}] — Total: {len(filas)}")
        print("=" * 98)
        print(f"{'ID':<4} | {'ROL':<15} | {'NOMBRE COMPLETO':<24} | {'EMAIL':<32} | {'TELÉFONO':<12}")
        print("-" * 98)
        for u in filas:
            rol_txt = ROLES.get(int(u.get("fk_id_rol") or 3), "Clienta")
            nombre_completo = f"{u.get('nombre') or ''} {u.get('apellido') or ''}".strip()
            tel = str(u.get("telefono") or "—")
            print(
                f"{str(u.get('id_usuario')):<4} | {rol_txt:<15} | {nombre_completo[:24]:<24} | "
                f"{str(u.get('email') or ''):<32} | {tel:<12}"
            )
        print("=" * 98)
    finally:
        conn.close()


if __name__ == "__main__":
    mostrar_usuarios()

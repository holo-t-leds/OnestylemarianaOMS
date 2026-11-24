"""
Script de Migración Idempotente — Grupo 4: Cumplimiento Técnico y Seguridad (RF-SEG-006, 007, 010, 011).

Agrega de forma segura e idempotente (sin pérdida de datos existentes):
- En `usuarios`: `tipo_documento`, `documento`, `direccion` (y `google_id` en SQLite si faltara).
- En `auditoria`: `ip_address`, `user_agent`.

Soporta MySQL/MariaDB (consultando `INFORMATION_SCHEMA.COLUMNS`) y SQLite local (`database/onestyle_local.db`
consultando `PRAGMA table_info`), pudiendo ejecutarse múltiples veces sin fallar ni duplicar columnas.
"""
import os
import sqlite3
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

SQLITE_DEFAULT_PATH = os.path.join(ROOT_DIR, "database", "onestyle_local.db")

MYSQL_MIGRATIONS = {
    "usuarios": (
        ("tipo_documento", "VARCHAR(20) NULL"),
        ("documento", "VARCHAR(30) NULL"),
        ("direccion", "VARCHAR(255) NULL"),
    ),
    "auditoria": (
        ("ip_address", "VARCHAR(45) NULL"),
        ("user_agent", "VARCHAR(255) NULL"),
    ),
}

SQLITE_MIGRATIONS = {
    "usuarios": (
        ("google_id", "TEXT"),
        ("tipo_documento", "TEXT"),
        ("documento", "TEXT"),
        ("direccion", "TEXT"),
    ),
    "auditoria": (
        ("ip_address", "TEXT"),
        ("user_agent", "TEXT"),
    ),
}


def _load_env():
    env_path = os.path.join(ROOT_DIR, ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())


def migrate_sqlite(db_path: str = SQLITE_DEFAULT_PATH) -> dict:
    """Aplica migraciones idempotentes sobre una base de datos SQLite existente o nueva."""
    summary = {"engine": "sqlite", "path": db_path, "added": [], "existing": []}
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        # Asegurar tabla usuarios/auditoria mínima si no existía aún
        tables = {
            r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        if "usuarios" not in tables:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS usuarios (
                    id_usuario INTEGER PRIMARY KEY,
                    fk_id_rol INTEGER NOT NULL,
                    nombre TEXT NOT NULL,
                    apellido TEXT NOT NULL,
                    email TEXT NOT NULL UNIQUE,
                    contrasena TEXT NOT NULL,
                    telefono TEXT,
                    google_id TEXT,
                    tipo_documento TEXT,
                    documento TEXT,
                    direccion TEXT,
                    estado_usuario INTEGER NOT NULL DEFAULT 1
                );
            """)
        if "auditoria" not in tables:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS auditoria (
                    id_log INTEGER PRIMARY KEY AUTOINCREMENT,
                    fk_id_usuario_accion INTEGER NOT NULL,
                    tipo_accion TEXT NOT NULL,
                    tabla_afectada TEXT NOT NULL,
                    id_registro_afectado INTEGER,
                    valor_anterior TEXT,
                    valor_nuevo TEXT,
                    ip_address TEXT,
                    user_agent TEXT,
                    fecha_accion TEXT DEFAULT CURRENT_TIMESTAMP
                );
            """)

        for table, cols in SQLITE_MIGRATIONS.items():
            existing_cols = {row[1] for row in cur.execute(f"PRAGMA table_info({table})").fetchall()}
            for col_name, col_def in cols:
                target = f"{table}.{col_name}"
                if col_name in existing_cols:
                    summary["existing"].append(target)
                else:
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_def};")
                    summary["added"].append(target)
        conn.commit()
    finally:
        conn.close()
    return summary


def migrate_mysql() -> dict:
    """Aplica migraciones idempotentes sobre MySQL/MariaDB si el servidor está disponible."""
    import pymysql

    db_host = os.getenv("DB_HOST", "localhost")
    db_port = int(os.getenv("DB_PORT", 3306))
    db_user = os.getenv("DB_USER", "root")
    db_password = os.getenv("DB_PASSWORD", "")
    db_name = os.getenv("DB_NAME", "onestyle_db")

    summary = {"engine": "mysql", "database": db_name, "added": [], "existing": []}
    conn = pymysql.connect(
        host=db_host,
        port=db_port,
        user=db_user,
        password=db_password,
        database=db_name,
        connect_timeout=3,
    )
    try:
        with conn.cursor() as cur:
            for table, cols in MYSQL_MIGRATIONS.items():
                for col_name, col_def in cols:
                    cur.execute(
                        """
                        SELECT COUNT(*)
                        FROM INFORMATION_SCHEMA.COLUMNS
                        WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND COLUMN_NAME = %s;
                        """,
                        (db_name, table, col_name),
                    )
                    exists = cur.fetchone()[0] > 0
                    target = f"{table}.{col_name}"
                    if exists:
                        summary["existing"].append(target)
                    else:
                        cur.execute(f"ALTER TABLE `{table}` ADD COLUMN `{col_name}` {col_def};")
                        summary["added"].append(target)
        conn.commit()
    finally:
        conn.close()
    return summary


def run_migrations(sqlite_path: str = SQLITE_DEFAULT_PATH) -> list:
    """Ejecuta la migración idempotente sobre los motores configurados/disponibles."""
    _load_env()
    results = []

    if os.getenv("DB_ENGINE", "").strip().lower() != "sqlite":
        try:
            results.append(migrate_mysql())
        except Exception as exc:
            results.append({"engine": "mysql", "skipped": True, "reason": str(exc)})

    if os.path.exists(sqlite_path) or os.getenv("DB_ENGINE", "").strip().lower() == "sqlite":
        results.append(migrate_sqlite(sqlite_path))

    return results


def main():
    results = run_migrations()
    for res in results:
        if res.get("skipped"):
            print(f"[SKIP] {res['engine']}: {res.get('reason')}")
        else:
            print(
                f"[OK] {res['engine']}: agregadas={res['added']} | ya_existentes={res['existing']}"
            )


if __name__ == "__main__":
    main()

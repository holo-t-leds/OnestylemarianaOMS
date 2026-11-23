"""
Script de Migración y Seeding Automático para MySQL / MariaDB — G.C.L. OneStyle Mariana (OMS).
Crea la base de datos `onestyle_db` si no existe, aplica el esquema relacional (`database/schema.sql`)
y carga los datos de prueba (`database/seeds.sql`).
"""
import os
import sys
import pymysql

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT_DIR)

# Cargar variables de .env si existe
env_path = os.path.join(ROOT_DIR, ".env")
if os.path.exists(env_path):
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", 3306))
DB_USER = os.getenv("DB_USER", "root")
DB_PASSWORD = os.getenv("DB_PASSWORD", "")
DB_NAME = os.getenv("DB_NAME", "onestyle_db")


def run_sql_file(cursor, filepath: str):
    with open(filepath, "r", encoding="utf-8") as f:
        content = f.read()

    # Eliminar comentarios de línea y dividir por punto y coma
    lines = [
        line for line in content.splitlines()
        if not line.strip().startswith("--")
    ]
    clean_sql = "\n".join(lines)
    statements = [s.strip() for s in clean_sql.split(";") if s.strip()]
    for stmt in statements:
        cursor.execute(stmt)


def main():
    print(f"[1/3] Conectando a MySQL/MariaDB en {DB_HOST}:{DB_PORT} (usuario: {DB_USER})...")
    conn = pymysql.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        autocommit=True
    )
    try:
        with conn.cursor() as cursor:
            print(f"[2/3] Creando base de datos `{DB_NAME}` si no existe y aplicando `database/schema.sql`...")
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{DB_NAME}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;")
            cursor.execute(f"USE `{DB_NAME}`;")
            run_sql_file(cursor, os.path.join(ROOT_DIR, "database", "schema.sql"))

            print(f"[3/3] Poblando datos de prueba desde `database/seeds.sql`...")
            run_sql_file(cursor, os.path.join(ROOT_DIR, "database", "seeds.sql"))

        print(f"¡Migración y seeders aplicados exitosamente en `{DB_NAME}`!")
    finally:
        conn.close()


if __name__ == "__main__":
    main()

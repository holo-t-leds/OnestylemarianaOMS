import os
import pymysql

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # Carga segura de .env sin dependencia externa si python-dotenv no está instalado
    env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
    if os.path.exists(env_path):
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip())


def get_db_connection():
    return pymysql.connect(
        host=os.getenv("DB_HOST", "localhost"),
        user=os.getenv("DB_USER", "onestyle_user"),
        password=os.getenv("DB_PASSWORD", "onestyle_pass123"),
        database=os.getenv("DB_NAME", "onestyle_db"),
        port=int(os.getenv("DB_PORT", 3306)),
        cursorclass=pymysql.cursors.DictCursor
    )


def execute_parameterized_query(conn, sql: str, params: tuple = (), commit: bool = False):
    """
    Ejecuta consultas SQL exclusivamente de forma parametrizada (%s) para mitigar Inyección SQL (OWASP A03).
    """
    if not isinstance(params, (tuple, list)):
        raise ValueError("Los parámetros SQL deben pasarse como tupla o lista parametrizada.")
    with conn.cursor() as cursor:
        cursor.execute(sql, tuple(params))
        if commit:
            conn.commit()
        return cursor

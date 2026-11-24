import os
import sqlite3
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

SQLITE_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "database", "onestyle_local.db")


class SQLiteDictCursorWrapper:
    """Adapta sqlite3 para aceptar placeholders %s de PyMySQL y devolver diccionarios."""
    def __init__(self, conn):
        self._conn = conn
        self._cursor = conn.cursor()

    def execute(self, sql: str, params: tuple = ()):
        sql_sqlite = sql.replace("%s", "?").replace("FOR UPDATE", "")
        self._cursor.execute(sql_sqlite, tuple(params))
        return self

    def fetchall(self):
        return [dict(row) for row in self._cursor.fetchall()]

    def fetchone(self):
        row = self._cursor.fetchone()
        return dict(row) if row else None

    @property
    def rowcount(self):
        return self._cursor.rowcount

    def close(self):
        self._cursor.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._cursor.close()


class SQLiteConnectionWrapper:
    """
    Conexión SQLite local (database/onestyle_local.db) compatible con la interfaz de PyMySQL.
    Se activa automáticamente cuando MySQL no está corriendo o cuando DB_ENGINE=sqlite.
    """
    def __init__(self, db_path: str = SQLITE_PATH):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.db_path = db_path
        self._conn = sqlite3.connect(db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema_and_seeds()

    def _init_schema_and_seeds(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS roles (
                id_rol INTEGER PRIMARY KEY,
                nombre_rol TEXT NOT NULL UNIQUE
            );
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
            CREATE TABLE IF NOT EXISTS categorias (
                id_categoria INTEGER PRIMARY KEY,
                nombre_categoria TEXT NOT NULL UNIQUE,
                descripcion_categoria TEXT,
                estado INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS tallas (
                id_talla INTEGER PRIMARY KEY,
                nombre_talla TEXT NOT NULL UNIQUE,
                estado INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS colores (
                id_color INTEGER PRIMARY KEY,
                nombre_color TEXT NOT NULL UNIQUE,
                codigo_hex TEXT NOT NULL,
                estado INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS producto (
                id_producto INTEGER PRIMARY KEY,
                fk_id_categoria INTEGER NOT NULL,
                nombre_producto TEXT NOT NULL,
                descripcion_producto TEXT,
                precio_detallista REAL NOT NULL CHECK (precio_detallista > 0),
                url_imagen_principal TEXT,
                estado_visibilidad INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS producto_atributo (
                id_variante INTEGER PRIMARY KEY,
                fk_id_producto INTEGER NOT NULL,
                fk_id_talla INTEGER NOT NULL,
                fk_id_color INTEGER NOT NULL,
                codigo_sku TEXT NOT NULL UNIQUE,
                precio_variante REAL,
                estado INTEGER NOT NULL DEFAULT 1
            );
            CREATE TABLE IF NOT EXISTS inventario (
                id_inventario INTEGER PRIMARY KEY,
                fk_id_variante INTEGER NOT NULL UNIQUE,
                stock_real INTEGER NOT NULL DEFAULT 0 CHECK (stock_real >= 0),
                stock_reservado INTEGER NOT NULL DEFAULT 0 CHECK (stock_reservado >= 0),
                punto_reposicion INTEGER NOT NULL DEFAULT 3 CHECK (punto_reposicion >= 0)
            );

            INSERT OR IGNORE INTO roles VALUES (1, 'Administradora'), (2, 'Vendedora'), (3, 'Clienta');

            INSERT OR IGNORE INTO categorias VALUES
                (1, 'Corsets', 'Corsets arquitectónicos y lencería de autor', 1),
                (2, 'Blusas', 'Blusas y crop tops americanos de confección importada', 1),
                (3, 'Bodies', 'Bodies y enterizos nocturnos en malla y encaje francés', 1),
                (4, 'Pantalones', 'Pantalones en cuerina y denim wide leg exclusivo', 1),
                (5, 'Vestidos', 'Vestidos americanos importados de temporada', 1),
                (6, 'Conjuntos', 'Conjuntos de sastrería y chalecos de edición limitada', 1);

            INSERT OR IGNORE INTO tallas VALUES (1, 'XS', 1), (2, 'S', 1), (3, 'M', 1), (4, 'L', 1), (5, 'XL', 1);

            INSERT OR IGNORE INTO colores VALUES
                (1, 'Negro', '#17140F', 1),
                (2, 'Marfil', '#EFE7D5', 1),
                (3, 'Canela', '#8B5A34', 1),
                (4, 'Rojo', '#A31F2D', 1),
                (5, 'Azul', '#4E6484', 1),
                (6, 'Blanco', '#F8F6F0', 1),
                (7, 'Rosado', '#E8A5B8', 1);

            INSERT OR IGNORE INTO producto VALUES
                (1,  1, 'Corset Encaje Marfil', 'Encaje francés, varillaje arquitectónico', 120000.00, 'img/corset34-47.jpg', 1),
                (2,  1, 'Corset Canela de Lujo', 'Detalles de encaje premium importado', 145000.00, 'img/corset-canela.jpg', 1),
                (3,  3, 'Body Americano Nocturno', 'Manga larga y silueta minimalista (bodysamericanosB-N-ROS-C)', 128000.00, 'img/body-nocturno.jpg', 1),
                (4,  1, 'Corset Encaje Noir', 'Diseño floral contrastante en encaje negro', 160000.00, 'img/corset-noir.jpg', 1),
                (5,  2, 'Top Escote Profundo', 'Silueta fluida, cuello halter importado', 135000.00, 'img/top-escote.jpg', 1),
                (6,  4, 'Pantalón Cuerina & Denim', 'Detalle frontal ajustable de tiro alto', 120000.00, 'img/pantaloncuerina.jpg', 1),
                (7,  2, 'Top Esencial Carmesí', 'Ajuste perfecto, manga corta', 115000.00, 'img/top-carmesi.jpg', 1),
                (8,  1, 'Corset Lencería Blanc', 'Botones frontales decorativos en blanco puro', 180000.00, 'img/corset-blanc.jpg', 1),
                (9,  4, 'Jeans Wide Leg Premium', 'Denim importado, corte relajado', 165000.00, 'img/jeans-wide.jpg', 1),
                (10, 5, 'Vestido Americano Importado', 'Colección americana en Blanco (B), Negro (N) y Rojo (R)', 210000.00, 'img/vestidoamericanoB.jpg', 1),
                (11, 2, 'Crop Top Americano', 'Diseño versátil importado en Blanco (croptopB) y Negro (croptopN)', 118000.00, 'img/croptopB.jpg', 1),
                (12, 2, 'Blusa Americana Importada', 'Tejido suave en Rosado (ROS), Blanco (B) y Negro (N)', 132000.00, 'img/blusaamericana.jpg', 1),
                (13, 3, 'Enterizo Nocturno Manga Larga', 'Silueta esculpida de manga larga en Negro Obsidiana (N)', 195000.00, 'img/ENTERIZONEGROMANGALARGA.jpg', 1),
                (14, 6, 'Conjunto Sastre Supreme', 'Dos piezas estructuradas y chaleco sastre (Negro, Blanco, Canela)', 225000.00, 'img/conjuntosupreme.jpg', 1);

            INSERT OR IGNORE INTO producto_atributo VALUES
                (1,  1,  2, 2, 'OSM-COR-MAR-S',     120000.00, 1),
                (2,  2,  2, 3, 'OSM-COR-CAN-S',     145000.00, 1),
                (3,  3,  2, 1, 'OSM-BOD-NOC-N-S',   128000.00, 1),
                (4,  10, 2, 6, 'OSM-VES-AME-B-S',   210000.00, 1),
                (5,  10, 2, 1, 'OSM-VES-AME-N-S',   210000.00, 1),
                (6,  10, 2, 4, 'OSM-VES-AME-R-S',   210000.00, 1),
                (7,  11, 2, 6, 'OSM-CRP-AME-B-S',   118000.00, 1),
                (8,  11, 2, 1, 'OSM-CRP-AME-N-S',   118000.00, 1);

            INSERT OR IGNORE INTO inventario VALUES
                (1, 1, 8, 0, 3),
                (2, 2, 7, 0, 3),
                (3, 3, 6, 0, 3),
                (4, 4, 6, 0, 3),
                (5, 5, 6, 0, 3),
                (6, 6, 6, 0, 3),
                (7, 7, 7, 0, 3),
                (8, 8, 7, 0, 3);
        """)
        self._apply_idempotent_migrations()
        self._conn.commit()

    def _apply_idempotent_migrations(self):
        """Agrega columnas nuevas de seguridad y perfil sin afectar filas existentes en SQLite."""
        migrations = {
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
        cur = self._conn.cursor()
        try:
            for table, cols in migrations.items():
                existing = {
                    row[1] if isinstance(row, sqlite3.Row) else row["name"]
                    for row in cur.execute(f"PRAGMA table_info({table})").fetchall()
                }
                for col_name, col_type in cols:
                    if col_name not in existing:
                        cur.execute(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}")
        finally:
            cur.close()

    def cursor(self, *args, **kwargs):
        return SQLiteDictCursorWrapper(self._conn)

    def begin(self):
        pass

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()


def get_db_connection():
    """
    Intenta conectarse a MySQL/MariaDB según .env. Si DB_ENGINE=sqlite o MySQL no está corriendo
    en el equipo, usa de forma transparente la base de datos SQLite local (database/onestyle_local.db).
    """
    if os.getenv("DB_ENGINE", "").lower() == "sqlite":
        return SQLiteConnectionWrapper(SQLITE_PATH)

    try:
        return pymysql.connect(
            host=os.getenv("DB_HOST", "localhost"),
            user=os.getenv("DB_USER", "root"),
            password=os.getenv("DB_PASSWORD", ""),
            database=os.getenv("DB_NAME", "onestyle_db"),
            port=int(os.getenv("DB_PORT", 3306)),
            cursorclass=pymysql.cursors.DictCursor,
            connect_timeout=2
        )
    except Exception:
        return SQLiteConnectionWrapper(SQLITE_PATH)


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

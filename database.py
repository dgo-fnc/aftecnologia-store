"""
Base de datos SQLite para la tienda Aftecnología.
Tablas: categories, products, settings
"""
import sqlite3
import os
import hashlib

# En Render.com el disco persistente se monta en /data
# Localmente usa la misma carpeta del script
_data_dir = os.environ.get("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(_data_dir, "aftecnologia.db")

# Categorías con su código, nombre visible, ícono y margen por defecto
DEFAULT_CATEGORIES = [
    ("CEL",    "Celulares",        "📱", 150000),
    ("PORT",   "Portátiles",       "💻", 300000),
    ("AIO",    "Todo en Uno",      "🖥️", 300000),
    ("CORP",   "Corporativos",     "🏢", 300000),
    ("CLONE",  "Clones / Desktop", "🖥️", 300000),
    ("TAB",    "Tablets",          "📲", 100000),
    ("TV",     "Televisores",      "📺", 100000),
    ("WEAR",   "Wearables",        "🎧", 100000),
    ("IMP",    "Impresoras",       "🖨️", 100000),
    ("MON",    "Monitores",        "🖥️", 100000),
    ("PERF",   "Periféricos",      "🖱️", 100000),
    ("DISCO",  "Almacenamiento",   "💾", 100000),
    ("LIC",    "Licencias",        "🔑", 100000),
    ("CONECT", "Conectividad",     "🌐", 100000),
    ("UPS",    "UPS / Reguladores","⚡", 100000),
    ("VB",     "Video Beam",       "📽️", 100000),
    ("PROMO",  "Promociones",      "🎁", 100000),
]


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()

    # Tabla de categorías
    c.execute("""
        CREATE TABLE IF NOT EXISTS categories (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            code    TEXT    UNIQUE NOT NULL,
            name    TEXT    NOT NULL,
            icon    TEXT    DEFAULT '📦',
            markup  INTEGER DEFAULT 100000
        )
    """)

    # Tabla de productos
    c.execute("""
        CREATE TABLE IF NOT EXISTS products (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            code            TEXT    UNIQUE NOT NULL,
            name            TEXT    NOT NULL,
            brand           TEXT    DEFAULT '',
            subcategory     TEXT    DEFAULT '',
            category_code   TEXT    NOT NULL,
            supplier_price  INTEGER NOT NULL,
            price_override  INTEGER DEFAULT NULL,
            image_url       TEXT    DEFAULT NULL,
            description     TEXT    DEFAULT NULL,
            is_active       INTEGER DEFAULT 1,
            created_at      TEXT    DEFAULT (datetime('now','localtime')),
            updated_at      TEXT    DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (category_code) REFERENCES categories(code)
        )
    """)

    # Tabla de configuración (clave-valor)
    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # Historial de productos — registra cada evento relevante
    c.execute("""
        CREATE TABLE IF NOT EXISTS product_history (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            code       TEXT    NOT NULL,
            evento     TEXT    NOT NULL,
            valor_old  TEXT,
            valor_new  TEXT,
            nota       TEXT,
            fecha      TEXT    DEFAULT (datetime('now','localtime'))
        )
    """)
    c.execute("CREATE INDEX IF NOT EXISTS idx_hist_code ON product_history(code)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_hist_fecha ON product_history(fecha DESC)")

    # Migraciones: agregar columnas nuevas si no existen (compatibilidad con BD existentes)
    existing = [r[1] for r in c.execute("PRAGMA table_info(products)").fetchall()]
    if "description" not in existing:
        c.execute("ALTER TABLE products ADD COLUMN description TEXT DEFAULT NULL")
    if "is_portada" not in existing:
        c.execute("ALTER TABLE products ADD COLUMN is_p
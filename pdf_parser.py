"""
Parser de lista de precios PDF — Aftecnología
Lee el PDF del proveedor y carga/actualiza los productos en SQLite.

Uso:
    python pdf_parser.py                          # busca PDF en la carpeta padre
    python pdf_parser.py ruta/al/archivo.pdf
"""
import re, sys, os, sqlite3

# ─── Mapeo sección del PDF → código de categoría ────────────────────────────
SECTION_TO_CATEGORY = {
    "CELULARES": "CEL",   "PROMOCIONES": "PROMO",  "TELEVISORES": "TV",
    "WEARABLES": "WEAR",  "TABLETS": "TAB",         "PORTATILES": "PORT",
    "TODO EN UNO": "AIO", "EQUIPOS CORPORATIVOS": "CORP",
    "EQUIPOS CLONES": "CLONE",  "IMPRESORAS": "IMP", "ESCANER": "IMP",
    "VIDEO BEAM": "VB",   "MONITORES": "MON",        "PERIFERICOS": "PERF",
    "TINTAS": "PROMO",    "DISCOS EXTERNOS": "DISCO","MEMORIAS": "DISCO",
    "UPS": "UPS",         "REGULADORES": "UPS",      "POWER BANK": "UPS",
    "LICENCIAMIENTO KASPERSKY": "LIC", "SUSCRIPCIONES": "LIC",
    "LICENCIAMIENTO MICROSOFT": "LIC", "CONECTIVIDAD": "CONECT",
    "LICENCIAMIENTO ESET": "LIC",
}

# Encabezado de sección: "COD CELULARES / PERSONA NATURAL ..."
RE_SECTION = re.compile(r"^COD\s+(.+?)\s*/\s*PERSONA\s+NATURAL", re.IGNORECASE)
# Línea de producto: CODE  descripción  $  precio
RE_PRODUCT = re.compile(r"^(7[A-Z]{1,4}\d{1,5}[A-Z]?)\s+(.+?)\s+\$\s*([\d.,]+)\s*$")

# Patrones de ruido a ignorar (NO incluye "COD" — eso lo maneja RE_SECTION)
NOISE = [
    re.compile(r"^Fecha:",            re.I),
    re.compile(r"^CAT\s+LC",         re.I),
    re.compile(r"^\*\*Disponibilidad"),
    re.compile(r"^www\.",             re.I),
    re.compile(r"^info@",            re.I),
    re.compile(r"LISTA DE PRECIOS",  re.I),
    re.compile(r"TECHNOLOGY\s+STORE",re.I),
    re.compile(r"TECHNO\s+ANIVERSARIO",re.I),
    re.compile(r"^\d{3}\s+\d{3}"),
]


def _det_cat(header: str) -> str:
    h = header.upper()
    for key, code in SECTION_TO_CATEGORY.items():
        if key in h:
            return code
    return "PROMO"


def _parse_price(raw: str) -> int:
    clean = re.sub(r"[.$\s]", "", raw).replace(",", "")
    return int(clean) if clean.isdigit() else 0


def parse_pdf(pdf_path: str) -> list:
    """Extrae productos del PDF. Devuelve lista de dicts."""
    try:
        import pdfplumber
    except ImportError:
        raise ImportError(
            "pdfplumber no esta instalado. Ejecuta en la consola: pip install pdfplumber"
        )

    products = []
    current_cat = "PROMO"
    current_sub = ""

    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if not text:
                continue
            for line in text.split("\n"):
                line = line.strip()
                if not line:
                    continue
                # 1) Sección — SIEMPRE primero
                ms = RE_SECTION.match(line)
                if ms:
                    current_cat = _det_cat(ms.group(1))
                    current_sub = ""
                    continue
                # 2) Ruido
                if any(p.search(line) for p in NOISE):
                    continue
                # 3) Producto
                mp = RE_PRODUCT.match(line)
                if mp:
                    price = _parse_price(mp.group(3))
                    if price > 0:
                        products.append({
                            "code":          mp.group(1).strip(),
                            "name":          mp.group(2).strip(),
                            "category_code": current_cat,
                            "subcategory":   current_sub,
                            "supplier_price": price,
                        })
                    continue
                # 4) Sub-categoría (todo mayúsculas, sin dígitos al inicio)
                if line.isupper() and 3 <= len(line) <= 65:
                    current_sub = line

    return products


def _hist(conn, code: str, evento: str, old=None, new=None, nota=None):
    """Inserta un registro en product_history."""
    conn.execute(
        "INSERT INTO product_history(code, evento, valor_old, valor_new, nota) VALUES(?,?,?,?,?)",
        (code, evento, str(old) if old is not None else None,
         str(new) if new is not None else None, nota)
    )


def load_to_db(products: list, db_conn=None) -> dict:
    """
    Inserta/actualiza productos, sincroniza activos/inactivos y registra historial.
    Eventos registrados:
      - 'ingreso'       : producto nuevo en el PDF
      - 'precio'        : cambio de precio del proveedor
      - 'reactivacion'  : vuelve al PDF tras estar inactivo
      - 'inactivacion'  : desaparece del PDF (foto se conserva)
    Devuelve {new, updated, unchanged, reactivated, deactivated}
    """
    from database import get_db
    close = db_conn is None
    conn  = db_conn or get_db()
    stats = {"new": 0, "updated": 0, "unchanged": 0, "reactivated": 0, "deactivated": 0}

    # Códigos presentes en el PDF nuevo
    pdf_codes = {p["code"] for p in products}

    for p in products:
        row = conn.execute(
            "SELECT supplier_price, is_active FROM products WHERE code=?", (p["code"],)
        ).fetchone()

        if row is None:
            # Producto nuevo — registrar ingreso
            conn.execute("""
                INSERT INTO products(code, name, subcategory, category_code, supplier_price, is_active)
                VALUES(?, ?, ?, ?, ?, 1)
            """, (p["code"], p["name"], p["subcategory"],
                  p["category_code"], p["supplier_price"]))
            _hist(conn, p["code"], "ingreso",
                  new=p["supplier_price"],
                  nota=f"Precio inicial: ${p['supplier_price']:,}")
            stats["new"] += 1

        else:
            price_changed = row[0] != p["supplier_price"]
            was_inactive  = row[1] == 0

            if was_inactive:
                # Vuelve al catálogo
                conn.execute("""
                    UPDATE products
                    SET supplier_price=?, name=?, category_code=?, is_active=1,
                        updated_at=datetime('now','localtime')
                    WHERE code=?
                """, (p["supplier_price"], p["name"], p["category_code"], p["code"]))
                nota = f"Precio al regresar: ${p['supplier_price']:,}"
                if price_changed:
                    nota += f" (antes: ${row[0]:,})"
                _hist(conn, p["code"], "reactivacion",
                      old=row[0], new=p["supplier_price"], nota=nota)
                stats["reactivated"] += 1

            elif price_changed:
                # Solo cambió el precio
                conn.execute("""
                    UPDATE products
                    SET supplier_price=?,
                        updated_at=datetime('now','localtime')
                    WHERE code=?
                """, (p["supplier_price"], p["code"]))
                diferencia = p["supplier_price"] - row[0]
                signo = "+" if diferencia > 0 else ""
                _hist(conn, p["code"], "precio",
                      old=row[0], new=p["supplier_price"],
                      nota=f"Cambio: {signo}${diferencia:,}")
                stats["updated"] += 1

            else:
                stats["unchanged"] += 1

    # Inactivar productos que ya no están en el PDF (conserva fotos e historial)
    if pdf_codes:
        placeholders = ",".join("?" * len(pdf_codes))
        to_deactivate = conn.execute(
            f"SELECT code FROM products WHERE code NOT IN ({placeholders}) AND is_active=1",
            list(pdf_codes)
        ).fetchall()

        for row in to_deactivate:
            code = row["code"]
            conn.execute(
                "UPDATE products SET is_active=0, updated_at=datetime('now','localtime') WHERE code=?",
                (code,)
            )
            _hist(conn, code, "inactivacion", nota="No aparece en la lista de precios")
            stats["deactivated"] += 1

    conn.commit()
    if close:
        conn.close()
    return stats


def run(pdf_path: str):
    from database import init_db
    if not os.path.exists(pdf_path):
        print(f"❌ No se encontró: {pdf_path}")
        sys.exit(1)
    print(f"📄 Procesando: {os.path.basename(pdf_path)}")
    init_db()
    products = parse_pdf(pdf_path)
    print(f"  → Extraídos: {len(products)} productos")
    stats = load_to_db(products)
    print(f"\n✅ Listo — Nuevos: {stats['new']} | "
          f"Actualizados: {stats['updated']} | "
          f"Sin cambios: {stats['unchanged']}")


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        pdf_path = sys.argv[1]
    else:
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        pdfs = [f for f in os.listdir(base) if f.lower().endswith(".pdf")]
        if not pdfs:
            print("Uso: python pdf_parser.py ruta/al/archivo.pdf")
            sys.exit(1)
        pdf_path = os.path.join(base, sorted(pdfs)[-1])
        print(f"📂 PDF encontrado automáticamente: {os.path.basename(pdf_path)}")
    run(pdf_path)
                                                                                                                                                                                                                                                                                                                                                                    
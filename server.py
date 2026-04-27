"""
Servidor Aftecnología — Tornado
Sirve la tienda y el panel de administración.

Uso:
    python server.py          # Puerto 8080 por defecto
    python server.py 3000     # Puerto personalizado
"""
import tornado.web
import tornado.ioloop
import tornado.httpserver
import json
import os
import sys
import hashlib
import math
from concurrent.futures import ThreadPoolExecutor

BASE_DIR    = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR  = os.path.join(BASE_DIR, "static")
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
PAGE_SIZE   = 24  # productos por pagina

# Crear directorio de uploads si no existe
os.makedirs(UPLOADS_DIR, exist_ok=True)

# Pool de hilos para operaciones lentas (parseo PDF, busqueda de fotos)
_executor = ThreadPoolExecutor(max_workers=2)


# --- Utilidades --------------------------------------------------------------

def _json(data):
    return json.dumps(data, ensure_ascii=False)

def _hash(pw: str) -> str:
    return hashlib.sha256(pw.encode()).hexdigest()

def _check_admin(handler) -> bool:
    """True si la sesion actual es admin valido."""
    return handler.get_secure_cookie("admin_logged") == b"yes"


# --- Base Handler ------------------------------------------------------------

class BaseHandler(tornado.web.RequestHandler):
    def set_default_headers(self):
        self.set_header("Content-Type", "application/json; charset=utf-8")
        self.set_header("Access-Control-Allow-Origin", "*")

    def get_db(self):
        from database import get_db
        return get_db()

    def write_json(self, data, status=200):
        self.set_status(status)
        self.write(_json(data))

    def error(self, msg, status=400):
        self.write_json({"error": msg}, status)


# --- Tienda publica ----------------------------------------------------------

class IndexHandler(tornado.web.RequestHandler):
    def get(self):
        self.set_header("Content-Type", "text/html; charset=utf-8")
        with open(os.path.join(STATIC_DIR, "index.html"), "rb") as f:
            self.write(f.read())


class ProductsHandler(BaseHandler):
    """GET /api/products?cat=PORT&q=lenovo&page=1&featured=1&portada=1&offers=1"""
    def get(self):
        cat      = self.get_argument("cat",      "").strip().upper()
        q        = self.get_argument("q",        "").strip()
        page     = max(1, int(self.get_argument("page", 1)))
        featured = self.get_argument("featured", "")
        portada  = self.get_argument("portada",  "")
        offers   = self.get_argument("offers",   "")
        limit_ov = self.get_argument("limit",    "")

        conn = self.get_db()
        where_clauses = ["p.is_active = 1"]
        params = []

        if cat:
            where_clauses.append("p.category_code = ?")
            params.append(cat)
        if q:
            where_clauses.append("(p.name LIKE ? OR p.code LIKE ?)")
            params += [f"%{q}%", f"%{q}%"]
        if portada:
            where_clauses.append("p.is_portada = 1")
        elif featured:
            # Preferir is_featured=1; si no hay, caer en categorias populares
            feat_count = conn.execute(
                "SELECT COUNT(*) FROM products WHERE is_featured=1 AND is_active=1"
            ).fetchone()[0]
            if feat_count > 0:
                where_clauses.append("p.is_featured = 1")
            else:
                where_clauses.append("p.category_code IN ('PORT','CEL','AIO','TAB')")
        if offers:
            where_clauses.append("p.discount_price IS NOT NULL")

        where = " AND ".join(where_clauses)

        total = conn.execute(
            f"SELECT COUNT(*) FROM products p WHERE {where}", params
        ).fetchone()[0]

        page_size = int(limit_ov) if limit_ov and limit_ov.isdigit() else PAGE_SIZE
        offset = (page - 1) * page_size
        rows = conn.execute(f"""
            SELECT p.code, p.name, p.subcategory, p.category_code,
                   p.supplier_price, p.price_override, p.image_url, p.description,
                   p.discount_price, p.is_portada, p.is_featured,
                   c.markup, c.name as cat_name, c.icon as cat_icon,
                   COALESCE(p.price_override, p.supplier_price + c.markup) as final_price
            FROM products p
            JOIN categories c ON c.code = p.category_code
            WHERE {where}
            ORDER BY p.category_code, p.name
            LIMIT ? OFFSET ?
        """, params + [page_size, offset]).fetchall()

        conn.close()

        products = []
        for r in rows:
            products.append({
                "code":           r["code"],
                "name":           r["name"],
                "subcategory":    r["subcategory"],
                "category_code":  r["category_code"],
                "category_name":  r["cat_name"],
                "category_icon":  r["cat_icon"],
                "supplier_price": r["supplier_price"],
                "final_price":    r["final_price"],
                "discount_price": r["discount_price"],
                "is_portada":     r["is_portada"] or 0,
                "is_featured":    r["is_featured"] or 0,
                "has_override":   r["price_override"] is not None,
                "image_url":      r["image_url"] or "",
                "description":    r["description"] or "",
            })

        self.write_json({
            "products": products,
            "total":    total,
            "page":     page,
            "pages":    math.ceil(total / page_size) if total else 1,
        })


class CategoriesHandler(BaseHandler):
    """GET /api/categories -- lista de categorias con conteo de productos"""
    def get(self):
        conn = self.get_db()
        rows = conn.execute("""
            SELECT c.code, c.name, c.icon, c.markup,
                   COUNT(p.id) as product_count
            FROM categories c
            LEFT JOIN products p ON p.category_code = c.code AND p.is_active = 1
            GROUP BY c.code
            ORDER BY product_count DESC
        """).fetchall()
        conn.close()
        cats = [dict(r) for r in rows if r["product_count"] > 0]
        self.write_json(cats)


# --- Panel de administracion -------------------------------------------------

class AdminPageHandler(tornado.web.RequestHandler):
    def get(self):
        self.set_header("Content-Type", "text/html; charset=utf-8")
        with open(os.path.join(STATIC_DIR, "admin.html"), "rb") as f:
            self.write(f.read())


class AdminLoginHandler(BaseHandler):
    """POST /api/admin/login  {password: "..."}"""
    def post(self):
        try:
            body = json.loads(self.request.body)
            password = body.get("password", "")
        except Exception:
            return self.error("JSON invalido")

        conn = self.get_db()
        row = conn.execute(
            "SELECT value FROM settings WHERE key='admin_password'"
        ).fetchone()
        conn.close()

        stored_hash = row["value"] if row else _hash("aftec2024")
        if _hash(password) == stored_hash:
            self.set_secure_cookie("admin_logged", "yes", expires_days=1)
            self.write_json({"ok": True})
        else:
            self.error("Contrasena incorrecta", 401)

    def options(self):
        self.set_status(204)


class AdminLogoutHandler(BaseHandler):
    def post(self):
        self.clear_cookie("admin_logged")
        self.write_json({"ok": True})


class AdminCheckHandler(BaseHandler):
    """GET /api/admin/check -- verifica si la sesion es valida"""
    def get(self):
        self.write_json({"logged": _check_admin(self)})


class AdminCategoriesHandler(BaseHandler):
    """GET  /api/admin/categories"""
    def get(self):
        if not _check_admin(self):
            return self.error("No autorizado", 401)
        conn = self.get_db()
        rows = conn.execute("""
            SELECT c.code, c.name, c.icon, c.markup,
                   COUNT(p.id) as product_count
            FROM categories c
            LEFT JOIN products p ON p.category_code = c.code
            GROUP BY c.code ORDER BY c.name
        """).fetchall()
        conn.close()
        self.write_json([dict(r) for r in rows])


class AdminCategoryUpdateHandler(BaseHandler):
    """PUT /api/admin/categories/<code>  {markup: 200000}"""
    def put(self, code):
        if not _check_admin(self):
            return self.error("No autorizado", 401)
        try:
            body   = json.loads(self.request.body)
            markup = int(body.get("markup", 0))
        except Exception:
            return self.error("Datos invalidos")
        if markup < 0:
            return self.error("El margen no puede ser negativo")

        conn = self.get_db()
        conn.execute("UPDATE categories SET markup=? WHERE code=?", (markup, code.upper()))
        conn.commit()
        conn.close()
        self.write_json({"ok": True, "code": code.upper(), "markup": markup})

    def options(self, code):
        self.set_status(204)


class AdminProductsHandler(BaseHandler):
    """GET /api/admin/products?q=&cat=&page=&no_image=1"""
    def get(self):
        if not _check_admin(self):
            return self.error("No autorizado", 401)

        q        = self.get_argument("q",        "").strip()
        cat      = self.get_argument("cat",      "").strip().upper()
        page     = max(1, int(self.get_argument("page", 1)))
        no_image   = self.get_argument("no_image",   "")
        no_desc    = self.get_argument("no_desc",    "")
        portada_f  = self.get_argument("portada_f",  "")
        featured_f = self.get_argument("featured_f", "")
        discount_f = self.get_argument("discount_f", "")

        conn = self.get_db()
        where_clauses = ["1=1"]
        params = []

        if q:
            where_clauses.append("(p.name LIKE ? OR p.code LIKE ?)")
            params += [f"%{q}%", f"%{q}%"]
        if cat:
            where_clauses.append("p.category_code = ?")
            params.append(cat)
        if no_image:
            where_clauses.append("(p.image_url IS NULL OR p.image_url = '')")
        if no_desc:
            where_clauses.append("(p.description IS NULL OR p.description = '')")
        if portada_f:
            where_clauses.append("p.is_portada = 1")
        if featured_f:
            where_clauses.append("p.is_featured = 1")
        if discount_f:
            where_clauses.append("p.discount_price IS NOT NULL")

        where = " AND ".join(where_clauses)
        total = conn.execute(
            f"SELECT COUNT(*) FROM products p WHERE {where}", params
        ).fetchone()[0]

        offset = (page - 1) * PAGE_SIZE
        rows = conn.execute(f"""
            SELECT p.code, p.name, p.category_code, p.supplier_price,
                   p.price_override, p.image_url, p.is_active,
                   p.description, p.discount_price, p.is_portada, p.is_featured,
                   c.markup, c.name as cat_name,
                   COALESCE(p.price_override, p.supplier_price + c.markup) as final_price
            FROM products p
            JOIN categories c ON c.code = p.category_code
            WHERE {where}
            ORDER BY p.category_code, p.name
            LIMIT ? OFFSET ?
        """, params + [PAGE_SIZE, offset]).fetchall()
        conn.close()

        self.write_json({
            "products": [dict(r) for r in rows],
            "total": total,
            "page": page,
            "pages": math.ceil(total / PAGE_SIZE) if total else 1,
        })


    def post(self):
        if not _check_admin(self):
            return self.error("No autorizado", 401)
        try:
            body = json.loads(self.request.body)
        except Exception:
            return self.error("JSON invalido")

        code  = (body.get("code") or "").strip().upper()
        name  = (body.get("name") or "").strip()
        cat   = (body.get("category_code") or "").strip().upper()
        price = body.get("supplier_price")

        if not code or not name or not cat or price is None:
            return self.error("Faltan campos obligatorios: code, name, category_code, supplier_price")

        try:
            price = int(price)
        except (ValueError, TypeError):
            return self.error("supplier_price debe ser un número")

        conn = self.get_db()
        try:
            conn.execute("""
                INSERT INTO products (code, name, category_code, supplier_price, image_url, description)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (code, name, cat, price,
                  body.get("image_url") or None,
                  body.get("description") or None))
            conn.commit()
            row = conn.execute("""
                SELECT p.*, c.markup,
                       COALESCE(p.price_override, p.supplier_price + c.markup) as final_price
                FROM products p JOIN categories c ON c.code=p.category_code
                WHERE p.code=?
            """, (code,)).fetchone()
            conn.close()
            self.write_json(dict(row) if row else {"ok": True})
        except Exception as e:
            conn.close()
            self.error(f"Error al crear producto: {e}", 400)


class AdminProductUpdateHandler(BaseHandler):
    """PUT /api/admin/products/<code>"""
    def put(self, code):
        if not _check_admin(self):
            return self.error("No autorizado", 401)
        try:
            body = json.loads(self.request.body)
        except Exception:
            return self.error("JSON invalido")

        conn = self.get_db()
        updates = []
        params  = []

        if "price_override" in body:
            val = body["price_override"]
            updates.append("price_override = ?")
            params.append(int(val) if val is not None and val != "" else None)

        if "is_active" in body:
            updates.append("is_active = ?")
            params.append(1 if body["is_active"] else 0)

        if "image_url" in body:
            updates.append("image_url = ?")
            params.append(body["image_url"] or None)

        if "description" in body:
            updates.append("description = ?")
            params.append(body["description"] or None)

        if "name" in body and body["name"].strip():
            updates.append("name = ?")
            params.append(body["name"].strip())

        if "category_code" in body and body["category_code"].strip():
            updates.append("category_code = ?")
            params.append(body["category_code"].strip().upper())

        if "discount_price" in body:
            val = body["discount_price"]
            updates.append("discount_price = ?")
            params.append(int(val) if val is not None and str(val).strip() not in ("", "0", "null") else None)

        if "is_portada" in body:
            updates.append("is_portada = ?")
            params.append(1 if body["is_portada"] else 0)

        if "is_featured" in body:
            updates.append("is_featured = ?")
            params.append(1 if body["is_featured"] else 0)

        if not updates:
            conn.close()
            return self.error("Nada que actualizar")

        updates.append("updated_at = datetime('now','localtime')")
        params.append(code.upper())
        conn.execute(
            f"UPDATE products SET {', '.join(updates)} WHERE code = ?", params
        )
        conn.commit()

        row = conn.execute("""
            SELECT p.*, c.markup,
                   COALESCE(p.price_override, p.supplier_price + c.markup) as final_price
            FROM products p JOIN categories c ON c.code=p.category_code
            WHERE p.code=?
        """, (code.upper(),)).fetchone()
        conn.close()
        self.write_json(dict(row) if row else {"ok": True})

    def options(self, code):
        self.set_status(204)


class AdminUploadPDFHandler(BaseHandler):
    """POST /api/admin/upload-pdf  (multipart form, campo: pdf_file)"""
    def post(self):
        if not _check_admin(self):
            return self.error("No autorizado", 401)

        if "pdf_file" not in self.request.files:
            return self.error("No se recibio ningun archivo")

        file_info = self.request.files["pdf_file"][0]
        filename  = file_info["filename"]
        if not filename.lower().endswith(".pdf"):
            return self.error("Solo se aceptan archivos PDF")

        save_path = os.path.join(UPLOADS_DIR, filename)
        with open(save_path, "wb") as f:
            f.write(file_info["body"])

        try:
            from pdf_parser import parse_pdf, load_to_db
            products = parse_pdf(save_path)
            stats    = load_to_db(products)
            self.write_json({
                "ok":          True,
                "extracted":   len(products),
                "new":         stats["new"],
                "updated":     stats["updated"],
                "unchanged":   stats["unchanged"],
                "reactivated": stats.get("reactivated", 0),
                "deactivated": stats.get("deactivated", 0),
            })
        except BaseException as e:
            self.error(f"Error al procesar el PDF: {e}", 500)


class AdminFetchPhotosHandler(BaseHandler):
    """POST /api/admin/fetch-photos"""
    async def post(self):
        if not _check_admin(self):
            return self.error("No autorizado", 401)
        try:
            loop = tornado.ioloop.IOLoop.current()
            result = await loop.run_in_executor(
                _executor,
                lambda: __import__("photo_fetcher").fetch_batch(limit=100)
            )
            self.write_json(result)
        except Exception as e:
            self.error(f"Error al buscar fotos: {e}", 500)


class AdminChangePasswordHandler(BaseHandler):
    """POST /api/admin/change-password  {current: "...", new: "..."}"""
    def post(self):
        if not _check_admin(self):
            return self.error("No autorizado", 401)
        try:
            body = json.loads(self.request.body)
        except Exception:
            return self.error("JSON invalido")

        current = body.get("current", "")
        new_pw  = body.get("new", "")

        if len(new_pw) < 6:
            return self.error("La contrasena debe tener al menos 6 caracteres")

        conn = self.get_db()
        row  = conn.execute("SELECT value FROM settings WHERE key='admin_password'").fetchone()
        stored = row["value"] if row else _hash("aftec2024")

        if _hash(current) != stored:
            conn.close()
            return self.error("Contrasena actual incorrecta", 401)

        conn.execute("UPDATE settings SET value=? WHERE key='admin_password'", (_hash(new_pw),))
        conn.commit()
        conn.close()
        self.write_json({"ok": True})


class AdminStatsHandler(BaseHandler):
    """GET /api/admin/stats"""
    def get(self):
        if not _check_admin(self):
            return self.error("No autorizado", 401)
        conn = self.get_db()
        total    = conn.execute("SELECT COUNT(*) FROM products").fetchone()[0]
        active   = conn.execute("SELECT COUNT(*) FROM products WHERE is_active=1").fetchone()[0]
        inactive = conn.execute("SELECT COUNT(*) FROM products WHERE is_active=0").fetchone()[0]
        with_image    = conn.execute("SELECT COUNT(*) FROM products WHERE image_url IS NOT NULL AND image_url != ''").fetchone()[0]
        without_image = conn.execute("SELECT COUNT(*) FROM products WHERE (image_url IS NULL OR image_url = '')").fetchone()[0]
        with_override = conn.execute("SELECT COUNT(*) FROM products WHERE price_override IS NOT NULL").fetchone()[0]
        categories    = conn.execute("SELECT COUNT(*) FROM categories").fetchone()[0]
        history_events = conn.execute("SELECT COUNT(*) FROM product_history").fetchone()[0]
        conn.close()
        self.write_json({
            "total_products": total,
            "active":         active,
            "inactive":       inactive,
            "with_image":     with_image,
            "without_image":  without_image,
            "with_override":  with_override,
            "categories":     categories,
            "history_events": history_events,
        })


class AdminExportHandler(BaseHandler):
    """GET /api/admin/export — descarga CSV con todos los productos"""
    def get(self):
        if not _check_admin(self):
            return self.error("No autorizado", 401)
        import csv, io
        conn = self.get_db()
        rows = conn.execute("""
            SELECT p.code, p.name, p.brand, p.subcategory, p.category_code,
                   c.name as category_name, p.supplier_price,
                   COALESCE(p.price_override, p.supplier_price + c.markup) as final_price,
                   p.discount_price, p.image_url, p.description,
                   p.is_active, p.is_portada, p.is_featured,
                   p.created_at, p.updated_at
            FROM products p
            JOIN categories c ON c.code = p.category_code
            ORDER BY p.category_code, p.name
        """).fetchall()
        conn.close()

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            "Codigo", "Nombre", "Marca", "Subcategoria", "Cat_Code", "Categoria",
            "Precio_Costo", "Precio_Venta", "Precio_Oferta", "Imagen",
            "Descripcion", "Activo", "Portada", "Destacado", "Creado", "Actualizado"
        ])
        for r in rows:
            writer.writerow(list(r))

        self.set_header("Content-Type", "text/csv; charset=utf-8")
        self.set_header("Content-Disposition", "attachment; filename=aftecnologia_productos.csv")
        self.write(output.getvalue())




class AdminHistoryHandler(BaseHandler):
    """GET /api/admin/history?q=&evento=&page=1&limit=50"""
    def get(self):
        if not _check_admin(self):
            return self.error("No autorizado", 401)
        q      = self.get_argument("q",      "").strip()
        evento = self.get_argument("evento", "").strip()
        page   = max(1, int(self.get_argument("page",  1)))
        limit  = min(100, max(10, int(self.get_argument("limit", 50))))

        conn = self.get_db()
        where = ["1=1"]
        params = []
        if q:
            where.append("(h.code LIKE ? OR h.nota LIKE ?)")
            params += [f"%{q}%", f"%{q}%"]
        if evento:
            where.append("h.evento LIKE ?")
            params.append(f"%{evento}%")

        w = " AND ".join(where)
        total = conn.execute(f"SELECT COUNT(*) FROM product_history h WHERE {w}", params).fetchone()[0]
        offset = (page - 1) * limit
        rows = conn.execute(
            f"SELECT * FROM product_history h WHERE {w} ORDER BY h.fecha DESC LIMIT ? OFFSET ?",
            params + [limit, offset]
        ).fetchall()
        conn.close()
        self.write_json({
            "rows":  [dict(r) for r in rows],
            "total": total,
            "page":  page,
            "pages": math.ceil(total / limit) if total else 1,
        })


class AdminBackfillHistoryHandler(BaseHandler):
    """POST /api/admin/backfill-history — crea eventos 'ingreso' para productos sin historial"""
    def post(self):
        if not _check_admin(self):
            return self.error("No autorizado", 401)
        conn = self.get_db()
        products = conn.execute("""
            SELECT p.code, p.name, p.supplier_price, p.created_at
            FROM products p
            WHERE p.code NOT IN (SELECT DISTINCT code FROM product_history WHERE evento='ingreso')
        """).fetchall()
        added = 0
        for p in products:
            conn.execute("""
                INSERT INTO product_history (code, evento, valor_new, nota, fecha)
                VALUES (?, 'ingreso', ?, ?, ?)
            """, (p["code"], str(p["supplier_price"]), p["name"], p["created_at"]))
            added += 1
        conn.commit()
        conn.close()
        self.write_json({"ok": True, "added": added})


# --- Routing -----------------------------------------------------------------

def make_app():
    cookie_secret = os.environ.get("SECRET_KEY", "aftec_dev_secret_2024")
    return tornado.web.Application(
        [
            (r"/",                              IndexHandler),
            (r"/admin",                         AdminPageHandler),
            (r"/api/products",                  ProductsHandler),
            (r"/api/categories",                CategoriesHandler),
            # Admin auth
            (r"/api/admin/login",               AdminLoginHandler),
            (r"/api/admin/logout",              AdminLogoutHandler),
            (r"/api/admin/check",               AdminCheckHandler),
            # Admin data
            (r"/api/admin/stats",               AdminStatsHandler),
            (r"/api/admin/export",              AdminExportHandler),
            (r"/api/admin/categories",          AdminCategoriesHandler),
            (r"/api/admin/categories/([^/]+)",  AdminCategoryUpdateHandler),
            (r"/api/admin/products",            AdminProductsHandler),
            (r"/api/admin/history",             AdminHistoryHandler),
            (r"/api/admin/backfill-history",    AdminBackfillHistoryHandler),
            (r"/api/admin/products/([^/]+)",    AdminProductUpdateHandler),
            (r"/api/admin/upload-pdf",          AdminUploadPDFHandler),
            (r"/api/admin/fetch-photos",        AdminFetchPhotosHandler),
            (r"/api/admin/change-password",     AdminChangePasswordHandler),
            # Archivos estaticos
            (r"/static/(.*)",  tornado.web.StaticFileHandler, {"path": STATIC_DIR}),
            (r"/uploads/(.*)", tornado.web.StaticFileHandler, {"path": UPLOADS_DIR}),
        ],
        cookie_secret=cookie_secret,
        xsrf_cookies=False,
        debug=False,
    )


if __name__ == "__main__":
    from database import init_db
    init_db()

    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8080
    app  = make_app()
    server = tornado.httpserver.HTTPServer(app)
    server.listen(port)
    print(f"✅ Servidor Aftecnología corriendo en http://localhost:{port}")
    tornado.ioloop.IOLoop.current().start()

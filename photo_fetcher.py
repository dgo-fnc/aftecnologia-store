"""
Buscador de fotos automático — Aftecnología
Busca imágenes en DuckDuckGo para los productos que aún no tienen foto.
No requiere API key.

Uso:
    python photo_fetcher.py          # 100 productos
    python photo_fetcher.py 50       # personalizar cantidad
"""
import re, sys, json, time, urllib.request, urllib.parse, urllib.error

# Número de productos a procesar por ejecución (para controlar el límite)
DEFAULT_LIMIT = 100

# User-Agent de navegador real para evitar bloqueos
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/javascript, */*; q=0.01",
}

# Dominios de imágenes genéricas o logotipos que queremos evitar
BAD_DOMAINS = ["logo", "icon", "banner", "flag", "badge", "brand",
               "favicon", "avatar", "placeholder", "noimage"]


def _clean_name(name: str) -> str:
    """
    Extrae los términos clave del nombre del producto para la búsqueda.
    Elimina especificaciones técnicas secundarias.
    """
    # Tomar solo hasta el segundo " - " para quedarnos con modelo+pantalla
    parts = name.split(" - ")
    query = " ".join(parts[:2])
    # Eliminar textos no útiles para la búsqueda de imagen
    for noise in ["PANTALLA", "OCTA CORE", "DUAL SIM", "ANDROID",
                  "FREEDOS", "LINUX", "NO DVD", "WINDOWS"]:
        query = query.replace(noise, "")
    return " ".join(query.split()).strip()


def _search_image_ddg(query: str) -> str | None:
    """
    Busca una imagen en DuckDuckGo Image Search.
    Devuelve la URL de la primera imagen encontrada, o None.
    """
    try:
        # Paso 1: obtener token vqd
        safe_q = urllib.parse.quote_plus(query)
        url1 = f"https://duckduckgo.com/?q={safe_q}&iax=images&ia=images"
        req1 = urllib.request.Request(url1, headers=HEADERS)
        with urllib.request.urlopen(req1, timeout=8) as r:
            html = r.read().decode("utf-8", errors="ignore")

        vqd_match = re.search(r'vqd=(["\'])([^"\']+)\1', html)
        if not vqd_match:
            vqd_match = re.search(r'vqd=([\d-]+)', html)
            vqd = vqd_match.group(1) if vqd_match else None
        else:
            vqd = vqd_match.group(2)

        if not vqd:
            return None

        # Paso 2: resultados JSON de imágenes
        params = urllib.parse.urlencode({
            "q": query, "vqd": vqd, "iax": "images", "ia": "images",
            "o": "json", "p": "1", "f": ",,,,,",
        })
        url2 = f"https://duckduckgo.com/i.js?{params}"
        req2 = urllib.request.Request(url2, headers={
            **HEADERS, "Referer": url1
        })
        with urllib.request.urlopen(req2, timeout=8) as r:
            data = json.loads(r.read().decode("utf-8", errors="ignore"))

        results = data.get("results", [])
        for item in results[:5]:
            img_url = item.get("image", "")
            if not img_url:
                continue
            # Filtrar imágenes de baja calidad o dominios sospechosos
            if any(bad in img_url.lower() for bad in BAD_DOMAINS):
                continue
            # Preferir imágenes con dimensiones razonables
            w = item.get("width", 0)
            h = item.get("height", 0)
            if w > 0 and h > 0 and (w < 80 or h < 80):
                continue
            return img_url

        # Si ninguna pasó el filtro, devolver la primera disponible
        if results:
            return results[0].get("image")

    except Exception as e:
        print(f"    ⚠ Error buscando '{query}': {e}")

    return None


def fetch_batch(limit: int = DEFAULT_LIMIT) -> dict:
    """
    Procesa los primeros `limit` productos sin imagen.
    Devuelve estadísticas: {processed, found, not_found, errors}
    """
    from database import get_db
    conn = get_db()

    # Tomar productos sin imagen, priorizando celulares y portátiles
    rows = conn.execute("""
        SELECT p.code, p.name, p.category_code
        FROM products p
        WHERE (p.image_url IS NULL OR p.image_url = '') AND p.is_active = 1
        ORDER BY
            CASE p.category_code
                WHEN 'CEL'  THEN 1 WHEN 'PORT' THEN 2 WHEN 'AIO'  THEN 3
                WHEN 'TAB'  THEN 4 WHEN 'TV'   THEN 5 ELSE 9
            END,
            p.name
        LIMIT ?
    """, (limit,)).fetchall()

    stats = {"processed": 0, "found": 0, "not_found": 0, "errors": 0}
    total = len(rows)

    print(f"🖼  Buscando fotos para {total} productos...\n")

    for i, row in enumerate(rows, 1):
        code  = row["code"]
        name  = row["name"]
        cat   = row["category_code"]
        query = _clean_name(name) + " producto"

        print(f"  [{i:>3}/{total}] {code} — {name[:50]}")
        print(f"         Búsqueda: «{query}»")

        img_url = _search_image_ddg(query)
        stats["processed"] += 1

        if img_url:
            conn.execute(
                "UPDATE products SET image_url=?, updated_at=datetime('now') WHERE code=?",
                (img_url, code)
            )
            conn.commit()
            stats["found"] += 1
            print(f"         ✅ Encontrada\n")
        else:
            stats["not_found"] += 1
            print(f"         ❌ No encontrada\n")

        # Pausa entre solicitudes para no sobrecargar DuckDuckGo
        if i < total:
            time.sleep(1.2)

    conn.close()
    print(f"\n📊 Resultado: {stats['found']} con foto | "
          f"{stats['not_found']} sin foto | de {stats['processed']} procesados")
    return stats


if __name__ == "__main__":
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_LIMIT
    fetch_batch(limit)

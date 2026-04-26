# Aftecnología Store — Instrucciones de uso

## Usar en tu computador (pruebas locales)

### Primera vez

1. Instala **Python** si no lo tienes: https://www.python.org/downloads/  
   (marca la casilla "Add Python to PATH" durante la instalación)

2. Haz doble clic en **`iniciar.bat`**  
   → Instala dependencias automáticamente  
   → Crea la base de datos  
   → Abre el servidor en http://localhost:8080

3. Abre tu navegador en:
   - **Tienda:** http://localhost:8080
   - **Panel admin:** http://localhost:8080/admin.html  
     (contraseña: `aftec2024`)

### Cargar la lista de precios

1. Entra al panel admin → pestaña **"Lista de precios"**
2. Arrastra el PDF del proveedor o haz clic para seleccionarlo
3. Espera unos segundos; verás cuántos productos se cargaron

### Buscar fotos de productos

1. Panel admin → pestaña **"Fotos"**
2. Haz clic en **"Buscar fotos automáticamente"**
3. Busca hasta 100 fotos por día (para no sobrecargar DuckDuckGo)

### Cambiar márgenes por categoría

1. Panel admin → pestaña **"Categorías"**
2. Edita el margen de la categoría que quieras y guarda

### Cambiar precio de un producto específico

1. Panel admin → pestaña **"Productos"**
2. Busca el producto por nombre o código
3. Escribe el precio de venta en el campo "Precio venta" y guarda

---

## Publicar en internet (Render.com — gratis)

### Preparar el repositorio

1. Crea una cuenta gratuita en https://github.com
2. Crea un repositorio nuevo llamado `aftecnologia-store`
3. Sube todos los archivos de esta carpeta al repositorio

### Desplegar en Render

1. Crea cuenta en https://render.com (con tu cuenta de GitHub)
2. Haz clic en **"New +"** → **"Web Service"**
3. Selecciona tu repositorio `aftecnologia-store`
4. Render detectará el `render.yaml` automáticamente
5. Haz clic en **"Create Web Service"**
6. Espera ~3 minutos mientras construye el sitio

### Después del despliegue

- Render te dará una URL como `https://aftecnologia-store.onrender.com`
- Entra a esa URL + `/admin.html` para el panel de administración
- **Cambia la contraseña** desde el panel admin → "Ajustes"
- Sube la lista de precios por el panel admin (pestaña "Lista de precios")

### Conectar tu dominio aftecnologia.com.co

1. En Render → tu servicio → **"Settings"** → **"Custom Domains"**
2. Agrega `aftecnologia.com.co` y `www.aftecnologia.com.co`
3. Render te mostrará unos registros DNS (tipo CNAME o A)
4. Ve al panel de tu registrador de dominio y agrega esos registros
5. En ~24 horas el dominio apuntará al nuevo sitio

---

## Contraseñas

| Qué          | Valor inicial |
|--------------|---------------|
| Admin panel  | `aftec2024`   |

⚠️ **Cambia la contraseña por el panel admin antes de publicar el sitio.**

---

## Estructura de archivos

```
aftecnologia-store/
├── database.py        Base de datos SQLite
├── server.py          Servidor web
├── pdf_parser.py      Lector de lista de precios PDF
├── photo_fetcher.py   Buscador automático de fotos
├── iniciar.bat        Arranque rápido (Windows)
├── requirements.txt   Dependencias Python
├── render.yaml        Configuración para Render.com
└── static/
    ├── index.html     Tienda (frontend)
    └── admin.html     Panel de administración
```

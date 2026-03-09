# Guía de Despliegue en Servidor — Pipeline de Migración de Audios a Dropbox

## ¿Qué hace este proyecto?

Toma los audios de llamadas telefónicas almacenados en el servidor (área Psychology),
identifica la carpeta del cliente correspondiente en Dropbox y sube el audio
a la subcarpeta `Recordings` dentro de esa carpeta.

---

## Requisitos del servidor

- Docker Engine >= 24
- Docker Compose >= 2.20
- Acceso a internet (para conectar con la API de Dropbox y Cloud Run)
- El directorio de audios montable como volumen (lectura suficiente)

---

## Archivos que NO se deben modificar

Todo el código fuente. Solo se ajustan variables de entorno y el `docker-compose.yaml`.

---

## Cambios necesarios para producción

### 1. Archivo `.env`

Copiar `.env` y ajustar los siguientes valores:

```env
# ── Credenciales para los contenedores PostgreSQL ─────────────────────────────
DB_USER=user
DB_PASS=pass

# ── Base de datos 1: índice de Dropbox (PostgreSQL) ───────────────────────────
# Cambiar host al servidor donde corra la DB de Dropbox
DB_URL=postgresql+psycopg2://user:pass@db_dropbox:5432/dropbox_index

# ── Base de datos 2: registros de audios (MySQL 8.4 del servidor de IT) ───────
# Apuntar directamente al MySQL del servidor — ya NO se levanta contenedor
AUDIOS_DB_URL=mysql+pymysql://<usuario>:<contraseña>@<host_mysql_IT>:3306/mendoza_box

# ── Autenticación Dropbox ──────────────────────────────────────────────────────
TOKEN_SERVICE_URL=https://accesstokendropbox-223080314602.us-central1.run.app
API_SECRET_KEY=930xY0dJ0pD

# ── Rutas de audios en el servidor ────────────────────────────────────────────
# Ruta real en el host donde están los audios
AUDIOS_HOST_PREFIX=/var/www/html/FILES/descarga_audios
# Punto de montaje dentro del contenedor (no cambiar)
AUDIOS_MOUNT=/audios

# ── Pipeline ──────────────────────────────────────────────────────────────────
OUTPUT_DIR=/app/output
LIMIT=500          # Audios a procesar por ejecución. Aumentar según capacidad.
REPEAT_THRESHOLD=3
```

---

### 2. Archivo `docker-compose.yaml`

En producción, la DB de IT ya existe en el servidor de IT — **no levantar ese contenedor**.
Solo se necesitan: `db_dropbox` y `app`.

Versión simplificada para producción:

```yaml
version: '3.8'

services:

  # Índice de Dropbox — solo si no tienen ya una instancia corriendo
  db_dropbox:
    image: postgres:15-alpine
    environment:
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASS}
      POSTGRES_DB: dropbox_index
    volumes:
      - ./db_dropbox_init:/docker-entrypoint-initdb.d/
    ports:
      - "5433:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -h 127.0.0.1 -U ${DB_USER} -d dropbox_index"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 90s

  app:
    build:
      context: .
      dockerfile: Dockerfile
    depends_on:
      db_dropbox:
        condition: service_healthy
    env_file:
      - .env
    volumes:
      - /var/www/html/FILES/descarga_audios:/audios:ro   # <-- ruta real del servidor
      - ./output:/app/output
```

> **Nota:** Si la DB de Dropbox ya está corriendo en otro servidor,
> eliminar el servicio `db_dropbox` del yaml y actualizar `DB_URL` en `.env`
> para apuntar a esa instancia.

---

## Ejecución

### Primera vez (inicializa todo)

```bash
# Desde la carpeta del proyecto
docker-compose up --build
```

### Ejecuciones posteriores (DBs ya inicializadas)

```bash
docker-compose up app
```

### Solo reconstruir la app (si se hizo algún cambio en código)

```bash
docker-compose up --build app
```

---

## Salidas del pipeline

Todos los archivos se generan en la carpeta `output/` accesible desde el host:

| Archivo | Contenido |
|---|---|
| `audios_sql.csv` | Audios extraídos de la DB de IT (universo total) |
| `01_clean_items.csv` – `06_grouped_counts.csv` | Pasos intermedios del análisis de carpetas Dropbox |
| `07_filtered_names.csv` | Nombres de clientes candidatos (depurados) |
| `08_final_output.csv` | Mapa nombre_estandarizado → carpeta Dropbox |
| `mapeo_audios.csv` | Resultado del cruce audio ↔ cliente (3 fases) |
| `mapeo_audios_con_urls.csv` | Mismo cruce + ruta completa en Dropbox |
| `resultado_migracion_audios.csv` | Estado final de cada audio (subido / error / sin path) |
| `dismatch_clientes_message.csv` | Audios que no encontraron carpeta de destino |

### Estados posibles en `resultado_migracion_audios.csv`

| estado | Significado |
|---|---|
| `subido` | Audio subido exitosamente a Dropbox |
| `sin_path_display` | No se encontró carpeta del cliente en el índice de Dropbox |
| `no_encontrado_local` | El archivo no existe en la ruta del servidor |
| `sin_subcarpeta_recordings` | La carpeta del cliente no tiene subcarpeta `Recordings` |
| `error_red` | Fallo de conexión con la API de Dropbox (reintentable) |
| `error_dropbox_*` | Error HTTP de Dropbox (revisar código de estado) |

---

## Resultados de prueba (datos de muestra)

Ejecutado con 10 audios de prueba del colaborador ARTURO RODRIGUEZ ISLAS:

- **Tasa de match:** 90% (9/10)
- **Subidos exitosamente:** 9/9
- **Sin match:** 1 audio con `nombre_cliente` vacío en la base de datos
- **Fases de matching:** 0 exactos / 6 por sets / 3 por fuzzy
- **Namespace Dropbox detectado:** Team Space `11983096259`

---

## Consideraciones importantes

1. **El `LIMIT` en producción** — Ajustar según la ventana de tiempo disponible. Cada audio toma ~2 segundos en subirse. Con `LIMIT=500` → ~17 minutos por ejecución.

2. **Re-ejecuciones** — El pipeline no tiene control de duplicados incorporado en esta versión. Si se corre dos veces con los mismos audios, Dropbox los renombrará automáticamente (`archivo (1).mp3`) porque el modo de subida es `autorename: True`.

3. **El 10% sin match** — Corresponde a audios sin `nombre_cliente` registrado en la DB o con nombre que no tiene carpeta en Dropbox. Revisar `dismatch_clientes_message.csv` después de cada ejecución.

4. **Variaciones en el nombre de la carpeta Recordings** — El algoritmo busca cualquier subcarpeta que contenga la palabra `recording` (insensible a mayúsculas). Funciona con `10 Recordings`, `10. Recording`, `Recordings`, etc.

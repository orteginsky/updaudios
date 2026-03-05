# updaudios — Pipeline de Migración de Audios a Dropbox

Automatiza la subida de grabaciones de llamadas telefónicas (área Psychology)
al expediente digital del cliente en Dropbox Business.

El sistema identifica la carpeta del cliente en el índice de Dropbox mediante
un cruce inteligente de nombres en 3 fases (exacto → sets → fuzzy), y deposita
cada audio en la subcarpeta `Recordings/PSYCHOLOGY` del expediente correspondiente.

---

## Arquitectura

```
┌─────────────────────────────────────────────────────────────┐
│  Servidor IT                  Docker (este proyecto)        │
│                                                             │
│  MySQL 8.4                    db_dropbox (PostgreSQL 15)    │
│  ├── RH.usuarios    ──────►   ├── dropbox_items             │
│  └── mendoza_box              │   (índice de 50 TB)         │
│      └── audios_descargados   └─────────────────────────    │
│                                                             │
│  /FILES/descarga_audios/ ──►  app (Python 3.11)             │
│  (audios mp3)                 └── pipeline de 6 pasos       │
│                                        │                    │
│                                        ▼                    │
│                               Dropbox Business API          │
│                               /Open Cases/<cliente>/        │
│                               └── Recordings/PSYCHOLOGY/    │
└─────────────────────────────────────────────────────────────┘
```

### Estructura del proyecto

```
updaudios/
├── docker-compose.yaml          # Orquesta los 3 servicios
├── Dockerfile                   # Imagen de la app Python
├── .env                         # Variables de entorno (no commitear)
├── .env.example                 # Plantilla de variables
├── sentencia_sql.txt            # Query SQL para extraer audios de IT
├── requirements.docker.txt      # Dependencias del contenedor
│
├── app/
│   ├── auth_service.py          # Cliente del microservicio de tokens Dropbox
│   ├── config.py                # Configuración centralizada (pydantic-settings)
│   └── database.py              # Modelos y motor async (SQLAlchemy) para db_dropbox
│
├── pipeline/
│   ├── step0_audios.py          # Extrae audios de la DB de IT
│   ├── step1_dropbox.py         # Analiza y limpia carpetas de Dropbox
│   ├── step2_cruce.py           # Cruza nombres audio ↔ cliente (3 fases)
│   ├── step3_paths.py           # Resuelve path_display en Dropbox
│   ├── step4_upload.py          # Sube audios a Dropbox
│   └── step5_audit.py           # Genera reporte de faltantes
│
├── main.py                      # Orquestador del pipeline
│
├── db_dropbox_init/
│   ├── 00_prereq.sql            # Crea roles de Cloud SQL para compatibilidad local
│   └── backup_dropbox.sql       # Volcado del índice de Dropbox (PostgreSQL)
│
├── db_it_init/                  # Solo para pruebas locales
│   ├── 01_CREACION_DE_TABLAS.sql
│   ├── 02_user_sql.sql
│   └── 03_audios.sql
│
└── audios_de_prueba/            # Audios ficticios para pruebas locales
```

---

## Pipeline — 6 pasos

| Step | Archivo | Entrada | Salida |
|------|---------|---------|--------|
| 0 | `step0_audios.py` | DB MySQL IT | `audios_sql.csv` |
| 1 | `step1_dropbox.py` | DB PostgreSQL Dropbox | `08_final_output.csv` |
| 2 | `step2_cruce.py` | CSVs steps 0 y 1 | `mapeo_audios.csv` |
| 3 | `step3_paths.py` | Mapeo + DB Dropbox | `mapeo_audios_con_urls.csv` |
| 4 | `step4_upload.py` | Mapeo con URLs + archivos locales | `resultado_migracion_audios.csv` |
| 5 | `step5_audit.py` | CSVs steps 0 y 2 | `dismatch_clientes_message.csv` |

### Cruce de nombres (Step 2) — 3 fases

1. **Exacto** — nombre normalizado del audio = nombre normalizado en Dropbox
2. **Sets** — todas las palabras del audio están contenidas en el nombre de Dropbox (tolera orden distinto y nombres compuestos)
3. **Fuzzy** — combinación de coincidencia exacta de palabras + similitud fonética para capturar errores tipográficos

### Destino en Dropbox (Step 4)

```
Carpeta del cliente
└── <subcarpeta con "recording" en el nombre>
    └── <subcarpeta con "psy"/"pys"/"psi" en el nombre>   ← destino
         Si no existe → se crea como "PSYCHOLOGY"
```

---

## Configuración

### Variables de entorno (`.env`)

| Variable | Descripción | Ejemplo |
|---|---|---|
| `DB_USER` | Usuario compartido para PostgreSQL | `user` |
| `DB_PASS` | Contraseña compartida para PostgreSQL | `pass` |
| `DB_URL` | Conexión a la DB de índice Dropbox | `postgresql+psycopg2://user:pass@db_dropbox:5432/dropbox_index` |
| `AUDIOS_DB_URL` | Conexión a la DB MySQL de IT | `mysql+pymysql://user:pass@db_it:3306/mendoza_box` |
| `TOKEN_SERVICE_URL` | URL del microservicio de tokens Dropbox | `https://accesstokendropbox-...run.app` |
| `API_SECRET_KEY` | Clave del microservicio de tokens | `930xY0dJ0pD` |
| `AUDIOS_HOST_PREFIX` | Prefijo de ruta del servidor a sustituir | `/FILES/descarga_audios` |
| `AUDIOS_MOUNT` | Punto de montaje dentro del contenedor | `/audios` |
| `OUTPUT_DIR` | Directorio de salida de CSVs | `/app/output` |
| `LIMIT` | Máximo de audios por ejecución | `500` |
| `REPEAT_THRESHOLD` | Umbral de carpetas repetidas (step 1) | `3` |

Copiar `.env.example` como punto de partida:
```bash
cp .env.example .env
```

---

## Ejecución local (pruebas)

### Requisitos
- Docker Engine >= 24
- Docker Compose >= 2.20

### Primera vez
```bash
# Genera archivos mp3 vacíos para probar el pipeline
bash create_test_audios.sh

# Levanta todo: db_dropbox (PostgreSQL) + db_it (MySQL) + app
docker-compose up --build
```

> La primera vez `db_dropbox` tarda ~45 segundos en cargar el backup completo.
> El `start_period: 90s` del healthcheck evita que la app arranque antes de que termine.

### Ejecuciones siguientes (DBs ya inicializadas)
```bash
docker-compose up app
```

### Si se modificó código Python
```bash
docker-compose up --build app
```

### Reiniciar desde cero (borra datos de las DBs)
```bash
docker-compose down -v
docker-compose up --build
```

---

## Outputs

Todos los archivos se generan en `output/` (accesible desde el host):

| Archivo | Contenido |
|---|---|
| `audios_sql.csv` | Audios extraídos de la DB de IT |
| `01_clean_items.csv` | Carpetas Dropbox con nombre limpio |
| `08_final_output.csv` | Mapa nombre_estandarizado → carpeta cliente |
| `mapeo_audios.csv` | Cruce audio ↔ cliente con fase de match |
| `mapeo_audios_con_urls.csv` | Mismo cruce + ruta completa en Dropbox |
| `resultado_migracion_audios.csv` | Estado de cada audio (subido / error / sin ruta) |
| `dismatch_clientes_message.csv` | Audios sin carpeta destino para revisión manual |

### Estados posibles (`resultado_migracion_audios.csv`)

| Estado | Significado |
|---|---|
| `subido` | Audio subido exitosamente |
| `sin_path_display` | Cliente no encontrado en el índice de Dropbox |
| `no_encontrado_local` | Archivo no existe en la ruta del servidor |
| `sin_subcarpeta_recordings` | La carpeta del cliente no tiene subcarpeta Recordings |
| `error_red` | Fallo de conexión con la API de Dropbox |
| `error_dropbox_*` | Error HTTP de Dropbox (ver código) |

---

## Resultados de la prueba de concepto

Ejecutado con 10 audios de muestra del colaborador ARTURO RODRIGUEZ ISLAS:

- **Match de clientes:** 9/10 (90%) — 0 exactos · 6 por sets · 3 por fuzzy
- **Subidos exitosamente:** 9/9 (100% de los matcheados)
- **Sin match:** 1 audio con `nombre_cliente` vacío en la DB
- **Team Space Dropbox:** namespace `11983096259` detectado automáticamente

---

## Despliegue en producción

Ver `DEPLOY_IT.md` para la guía completa dirigida al equipo de IT, incluyendo:
- Cambios necesarios en `.env` y `docker-compose.yaml`
- Query SQL de producción (sin `LIMIT`)
- Consideraciones sobre re-ejecuciones y duplicados

---

## Dependencias principales

| Librería | Uso |
|---|---|
| `polars` | Procesamiento de datos en el pipeline |
| `sqlalchemy` + `psycopg2` | Conexión a PostgreSQL (índice Dropbox) |
| `pymysql` + `cryptography` | Conexión a MySQL 8.4 (DB de IT) |
| `httpx` | Llamadas a la API de Dropbox y al microservicio de tokens |
| `thefuzz` + `rapidfuzz` | Matching fuzzy en step 2 |
| `unidecode` | Normalización de caracteres para el matching |
| `legal-data-cleaner` | Estandarización de nombres legales |
| `pydantic-settings` | Gestión de configuración desde variables de entorno |

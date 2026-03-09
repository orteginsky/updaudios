# Guía de Pruebas en Local — Pipeline de Migración de Audios a Dropbox

Esta guía está pensada para correr el pipeline completo en tu máquina usando datos de prueba,
sin necesidad de acceso al servidor de IT ni al Dropbox real de producción.

---

## Requisitos previos

- [Docker Engine >= 24](https://docs.docker.com/engine/install/)
- [Docker Compose >= 2.20](https://docs.docker.com/compose/install/) (incluido en Docker Desktop)
- [Git](https://git-scm.com/)
- Acceso a internet (para conectar con el microservicio de tokens de Dropbox)
- La clave `API_SECRET_KEY` del microservicio — pedirla al responsable del proyecto

---

## 1. Clonar el repositorio

```bash
git clone https://github.com/lortegamendozafirm/updaudios.git
cd updaudios
```

---

## 2. Obtener los archivos SQL desde Drive

Los archivos SQL **no están en el repositorio** porque contienen datos reales.
Descargarlos desde el Drive compartido y colocarlos en las siguientes rutas:

| Archivo descargado | Ruta donde colocarlo |
|---|---|
| `backup_dropbox.sql` | `db_dropbox_init/backup_dropbox.sql` |
| `01_CREACION_DE_TABLAS.sql` | `db_it_init/01_CREACION_DE_TABLAS.sql` |
| `02_user_sql.sql` | `db_it_init/02_user_sql.sql` |
| `03_audios.sql` | `db_it_init/03_audios.sql` |

La estructura debería quedar así:

```
updaudios/
├── db_dropbox_init/
│   ├── 00_prereq.sql          ← ya está en el repo
│   └── backup_dropbox.sql     ← descargar de Drive
│
└── db_it_init/
    ├── 01_CREACION_DE_TABLAS.sql   ← descargar de Drive
    ├── 02_user_sql.sql             ← descargar de Drive
    └── 03_audios.sql               ← descargar de Drive
```

> **Nota:** `backup_dropbox.sql` es grande (~varios cientos de MB).
> La primera vez que levantes los contenedores puede tardar entre 1 y 5 minutos en importarse.

---

## 3. Configurar el archivo `.env`

Copiar la plantilla e ingresar los valores correspondientes:

```bash
cp .env.example .env
```

Editar `.env` y ajustar:

```env
# Credenciales para los contenedores de DB (pueden ser cualquier valor para local)
DB_USER=user
DB_PASS=pass

# Conexión a la DB de Dropbox (el host "db_dropbox" es el nombre del servicio Docker)
DB_URL=postgresql+psycopg2://user:pass@db_dropbox:5432/dropbox_index

# Conexión a la DB de IT (el host "db_it" es el nombre del servicio Docker)
AUDIOS_DB_URL=mysql+pymysql://user:pass@db_it:3306/mendoza_box

# Microservicio de tokens Dropbox — pedir la clave al responsable del proyecto
TOKEN_SERVICE_URL=https://accesstokendropbox-223080314602.us-central1.run.app
API_SECRET_KEY=<pedir_al_responsable>

# Rutas de audios — para pruebas locales usa la carpeta audios_de_prueba/
AUDIOS_HOST_PREFIX=/FILES/descarga_audios
AUDIOS_MOUNT=/audios

# Pipeline
OUTPUT_DIR=/app/output
LIMIT=50
REPEAT_THRESHOLD=3
```

> Los valores de `DB_USER` y `DB_PASS` pueden ser cualquier string para pruebas locales,
> siempre que sean iguales en `DB_URL` y `AUDIOS_DB_URL`.

---

## 4. Levantar todo

```bash
docker-compose up --build
```

Docker levantará 3 contenedores en orden:

1. `db_dropbox` — PostgreSQL con el índice de carpetas de Dropbox
2. `db_it` — MySQL con los registros de audios de prueba
3. `app` — Pipeline Python (arranca automáticamente cuando ambas DBs estén listas)

> La primera vez `db_dropbox` tarda ~1-5 minutos en cargar el backup completo.
> El healthcheck tiene un `start_period: 90s` para que la app no arranque antes de que termine.

---

## 5. Ver resultados

Una vez que el pipeline termina, los archivos de salida quedan en la carpeta `output/`
del proyecto (accesible directamente desde tu máquina):

| Archivo | Contenido |
|---|---|
| `audios_sql.csv` | Audios extraídos de la DB de prueba |
| `01_clean_items.csv` – `08_final_output.csv` | Pasos del análisis de carpetas Dropbox |
| `mapeo_audios.csv` | Cruce audio ↔ cliente (fase exacto / sets / fuzzy) |
| `mapeo_audios_con_urls.csv` | Cruce + ruta completa en Dropbox |
| `resultado_migracion_audios.csv` | Estado final de cada audio |
| `dismatch_clientes_message.csv` | Audios sin carpeta destino encontrada |

---

## Ejecuciones siguientes

### Re-correr el pipeline sin reconstruir la imagen

```bash
docker-compose up app
```

### Reconstruir la imagen (si modificaste código en `app/`)

```bash
docker-compose up --build app
```

### Reiniciar desde cero (borra las DBs y vuelve a importar los SQL)

```bash
docker-compose down -v
docker-compose up --build
```

---

## Resolución de problemas frecuentes

| Síntoma | Causa probable | Solución |
|---|---|---|
| `app` termina antes de que la DB esté lista | `backup_dropbox.sql` tarda más de 90 s | Correr `docker-compose up app` una vez que los otros servicios estén healthy |
| `Error: AUDIOS_DB_URL connection refused` | `db_it` no terminó de inicializarse | Esperar y correr `docker-compose up app` |
| `401 Unauthorized` en paso 4 | `API_SECRET_KEY` incorrecta | Verificar el valor con el responsable del proyecto |
| `no_encontrado_local` en todos los audios | Rutas del CSV no coinciden con el mount | Verificar `AUDIOS_HOST_PREFIX` en `.env` |
| Puerto 5433 o 5434 ya en uso | Otra DB local corriendo en esos puertos | Cambiar los `ports` en `docker-compose.yaml` |

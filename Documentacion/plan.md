El objetivo es transformar un conjunto de scripts dispersos en una aplicación modular y contenida.

* **Infraestructura:** Usaremos `docker-compose` para levantar dos instancias de bases de datos que representen el índice de Dropbox y los datos de IT.
* **Refactorización:** Eliminaremos la dependencia de archivos CSV intermedios. Cada "Step" del pipeline consultará la base de datos, procesará y actualizará estados en tablas de control.
* **Modularidad:** Separaremos la lógica de conexión (Services) de la lógica de transformación (Pipeline).

---

## 2. Configuración del Entorno (Docker)

Para que el proyecto sea transportable, definiremos el archivo `docker-compose.yaml` para inicializar las bases de datos con los archivos `.sql`.

```yaml
version: '3.8'

services:
  # Base de Datos de Dropbox (Indexación de los 50TB)
  db_dropbox:
    image: postgres:15-alpine
    environment:
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASS}
      POSTGRES_DB: dropbox_index
    volumes:
      - ./db_dropbox_init/backup_dropbox.sql:/docker-entrypoint-initdb.d/init.sql
    ports:
      - "5433:5432"

  # Base de Datos de IT (Rutas de audios y colaboradores)
  db_it:
    image: postgres:15-alpine
    environment:
      POSTGRES_USER: ${DB_USER}
      POSTGRES_PASSWORD: ${DB_PASS}
      POSTGRES_DB: it_records
    volumes:
      - ./db_it_init:/docker-entrypoint-initdb.d/
    ports:
      - "5434:5432"

  # Aplicación Python
  app:
    build: ./app
    depends_on:
      - db_dropbox
      - db_it
    env_file:
      - .env.local
    volumes:
      - ./audios_de_prueba:/mnt/audios_local  # Simulación de la ruta del servidor

```

---

## 3. Plan de Refactorización del Código

### Paso A: Capa de Conexión (`database.py`)

En lugar de cargar CSVs, crearemos un motor de conexión usando **SQLAlchemy** o **psycopg2**. Esto permitirá que `step0`, `step1`, etc., realicen queries directas.

### Paso B: Reescritura del Pipeline

Debes migrar la lógica de tus scripts antiguos a la nueva estructura de carpetas:

1. **`step0_audios.py`**: Lee la tabla de la base de datos `db_it` (procedente de `audios.sql`) y filtra solo los del área "Psychology" usando el cruce con `user_sql.sql`.
2. **`step1_dropbox.py`**: Utiliza tu algoritmo de búsqueda de carpetas de clientes en la base de datos `db_dropbox`.
3. **`step2_cruce.py`**: **Aquí está la clave.** En lugar de unir dos CSVs, harás un `JOIN` lógico (o vía código) entre el ID del cliente del audio y el path encontrado en Dropbox.
4. **`step3_paths.py`**: Valida que la subcarpeta específica dentro del cliente (donde debe ir el audio) exista o deba ser creada.
5. **`step4_upload.py`**: Ejecuta la subida a Dropbox usando el `auth_service.py`.

---

## 4. Implementación del Pipeline (Ejemplo de Estructura)

Para dejar de usar CSVs, tu `main.py` debería coordinar los servicios:

```python
# app/main.py
from database import get_it_db_session, get_dropbox_db_session
from pipeline import step0_audios, step1_dropbox, step2_cruce

def run_migration():
    print("Iniciando proceso de migración...")
    
    # 1. Obtener audios pendientes de IT
    audios_pendientes = step0_audios.get_psychology_audios()
    
    # 2. Localizar rutas en Dropbox para esos clientes
    mapping_rutas = step1_dropbox.match_clients_to_paths(audios_pendientes)
    
    # 3. Proceder con la carga...
    # ... resto de la lógica

```

**Tabla de Auditoría**: Crea una tabla `migration_status` en la DB de IT para marcar qué audios ya fueron subidos con éxito y evitar duplicados.

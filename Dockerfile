# ── Base ─────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

# Metadatos
LABEL maintainer="firma-legal"
LABEL description="Pipeline de migración de audios de llamadas a Dropbox"

# ── Dependencias del sistema ──────────────────────────────────────────────────
# gcc + libpq-dev: necesarios para psycopg2 (driver PostgreSQL)
# git: necesario para instalar legal-data-cleaner desde GitHub
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
        git \
    && rm -rf /var/lib/apt/lists/*

# ── Directorio de trabajo ─────────────────────────────────────────────────────
WORKDIR /app

# ── Dependencias Python ───────────────────────────────────────────────────────
# Se copia primero solo requirements.txt para aprovechar la caché de capas:
# si el código cambia pero las dependencias no, esta capa no se rebuildeará.
COPY requirements.docker.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# ── Código fuente ─────────────────────────────────────────────────────────────
COPY app/          ./app/

# ── Directorios de volúmenes ──────────────────────────────────────────────────
# /app/output → CSVs intermedios y reportes finales  (volumen de salida)
# /audios     → archivos de audio del servidor       (volumen de solo lectura)
RUN mkdir -p /app/output /audios

# ── Entrypoint ────────────────────────────────────────────────────────────────
ENTRYPOINT ["python", "app/main.py"]

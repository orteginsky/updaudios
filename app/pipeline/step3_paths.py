"""
Step 3: Enriquece el mapeo con la ruta completa de la carpeta en Dropbox (path_display).

Lee el mapeo de audios y busca en DB1 (dropbox_items) la ruta completa
de cada carpeta de cliente para saber exactamente dónde subir el audio.

Entradas:
  - output/mapeo_audios.csv   (file_name, path, nombre_limpio_audio, parent_name)
  - DB1: tabla dropbox_items

Salida: output/mapeo_audios_con_urls.csv
  (path_display, file_name, path, nombre_limpio_audio, parent_name)
"""
import os

import polars as pl
from sqlalchemy import create_engine, text

OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")
DB_URL = os.getenv("DB_URL", "postgresql+psycopg2://user:pass@localhost:5433/dropbox_index")

PATH_INPUT = os.path.join(OUTPUT_DIR, "mapeo_audios.csv")
PATH_OUTPUT = os.path.join(OUTPUT_DIR, "mapeo_audios_con_urls.csv")


def run() -> None:
    print("[Step 3] Obteniendo rutas Dropbox desde la base de datos...")

    # 1. Cargar mapeo de audios
    df_mapeo = pl.read_csv(PATH_INPUT)

    # 2. Consultar carpetas en DB1
    query = "SELECT name, path_display FROM dropbox_items WHERE type = 'folder'"
    engine = create_engine(DB_URL)
    with engine.connect() as conn:
        result = conn.execute(text(query))
        df_db = pl.DataFrame([dict(row) for row in result.mappings()])

    # 3. Limpiar nombres para un join limpio
    df_db = df_db.with_columns(pl.col("name").str.strip_chars())
    df_mapeo = df_mapeo.with_columns(pl.col("parent_name").str.strip_chars())

    # 4. Join: parent_name (mapeo) ↔ name (dropbox_items) → trae path_display
    df_resultado = df_mapeo.join(
        df_db,
        left_on="parent_name",
        right_on="name",
        how="left"
    )

    # 5. Seleccionar columnas finales
    df_final = df_resultado.select([
        "path_display",
        "file_name",
        "path",
        "nombre_limpio_audio",
        "parent_name",
    ])

    df_final.write_csv(PATH_OUTPUT)

    sin_path = df_final.filter(pl.col("path_display").is_null()).height
    print(f"     Total registros:     {df_final.height:,}")
    print(f"     Sin path_display:    {sin_path:,} (carpeta no encontrada en DB)")
    print(f"[Step 3] Completado → {PATH_OUTPUT}")


if __name__ == "__main__":
    run()

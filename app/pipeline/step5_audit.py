"""
Step 5: Auditoría — identifica audios que no encontraron carpeta de destino.

Compara el total de audios extraídos de DB2 contra los que sí hicieron match,
y genera un reporte de los que quedaron sin asignar.

Entradas:
  - output/audios_sql.csv   (path, file_name, name)   ← universo total
  - output/mapeo_audios.csv (file_name, path, ...)    ← los que hicieron match

Salida: output/dismatch_clientes_message.csv
"""
import os

import polars as pl
from legal_data_cleaner import standardize_name

OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")

PATH_TOTAL = os.path.join(OUTPUT_DIR, "audios_sql.csv")
PATH_MAPEO = os.path.join(OUTPUT_DIR, "mapeo_audios.csv")
PATH_OUTPUT = os.path.join(OUTPUT_DIR, "dismatch_clientes_message.csv")


def run() -> None:
    print("[Step 5] Iniciando auditoría de faltantes...")

    df_total = pl.read_csv(PATH_TOTAL)
    df_exitosos = pl.read_csv(PATH_MAPEO)

    # Anti-join: audios del universo que NO están en el mapeo exitoso
    df_restante = df_total.join(df_exitosos, on="file_name", how="anti")

    # Enriquecer con nombre limpio del cliente para facilitar la revisión
    print("     Estandarizando nombres de clientes sin match...")
    df_restante = df_restante.with_columns(
        pl.col("name")
        .map_elements(standardize_name, return_dtype=pl.String)
        .alias("nombre_limpio_para_revisar")
    )

    df_restante.write_csv(PATH_OUTPUT)

    print(f"\n     Total sin destino: {df_restante.height:,}")
    print(f"     Con match:         {df_exitosos.height:,}")
    print(f"     Universo total:    {df_total.height:,}")
    print(f"     Tasa de éxito:     {(df_exitosos.height / df_total.height * 100):.2f}%")

    if df_restante.height > 0:
        print("\n     Muestra de registros sin match:")
        print(df_restante.select(["file_name", "nombre_limpio_para_revisar"]).head(10))

    print(f"[Step 5] Completado → {PATH_OUTPUT}")


if __name__ == "__main__":
    run()

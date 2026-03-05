"""
Step 1: Analiza y limpia carpetas de Dropbox para identificar carpetas raíz de clientes.

Lee desde DB1 (dropbox_items).
Salida: output/08_final_output.csv  (columnas: parent_name, name_clean)
"""
import os
import re
import sys

import polars as pl
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from unidecode import unidecode

load_dotenv()

try:
    from legal_data_cleaner import standardize_name
except ImportError as exc:
    sys.exit(
        f"[ERROR] No se encontró 'legal-data-cleaner'.\n"
        f"  Instálala con: pip install git+https://github.com/lortegamendozafirm/legal-data-cleaner.git\n"
        f"  Detalle: {exc}"
    )

DB_URL = os.getenv("DB_URL", "postgresql+psycopg2://user:pass@localhost:5433/dropbox_index")
OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")
REPEAT_THRESHOLD = int(os.getenv("REPEAT_THRESHOLD", "3"))


def _save_csv(df: pl.DataFrame, step: int, name: str) -> None:
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, f"{step:02d}_{name}.csv")
    df.write_csv(path)
    print(f"  [CSV {step:02d}] {path}  ({df.height:,} filas)")


def _basic_clean(name: str) -> str:
    if not isinstance(name, str):
        return ""
    name = name.replace(".", "")
    name = unidecode(name)
    name = re.sub(r"\s+", " ", name)
    return name.strip().upper()


def _extract_parent_name(path_display: str) -> str:
    if not isinstance(path_display, str):
        return ""
    match = re.search(r"/([^/]+)/[^/]+$", path_display)
    return match.group(1) if match else ""


def run() -> None:
    print("[Step 1] Conectando a la base de datos Dropbox...")
    engine = create_engine(DB_URL)

    query = text(
        "SELECT id, name, path_display, path_lower, parent_path_lower, size "
        "FROM dropbox_items WHERE type = 'folder'"
    )
    with engine.connect() as conn:
        result = conn.execute(query)
        raw_df = pl.DataFrame([dict(row) for row in result.mappings()])

    print(f"     Carpetas cargadas: {raw_df.height:,}")

    # Paso 1 – Limpieza básica
    clean_df = raw_df.with_columns(
        pl.col("name").map_elements(_basic_clean, return_dtype=pl.String).alias("name_clean")
    )
    _save_csv(clean_df.select(["name", "name_clean"]), 1, "clean_items")

    # Paso 2 – Top 50 más repetidas
    top_50 = (
        clean_df.group_by("name_clean")
        .agg(pl.len().alias("count"))
        .sort("count", descending=True)
        .head(50)
    )
    _save_csv(top_50, 2, "top_50")

    # Paso 3 – Del top 50, las que inician con dígito
    numeric_top50 = top_50.filter(pl.col("name_clean").str.contains(r"^\d"))
    _save_csv(numeric_top50, 3, "numeric_top50")
    print(f"     Carpetas numéricas en top 50: {numeric_top50.height}")

    if numeric_top50.is_empty():
        print("  [AVISO] No se encontraron carpetas numéricas. Verifica los datos.")
        sys.exit(0)

    # Paso 4 – Extraer carpetas padre
    numeric_names = set(numeric_top50["name_clean"].to_list())
    parents_raw = (
        clean_df.filter(pl.col("name_clean").is_in(numeric_names))
        .with_columns(
            pl.col("path_display")
            .map_elements(_extract_parent_name, return_dtype=pl.String)
            .alias("parent_name")
        )
        .select(["path_display", "name_clean", "parent_name"])
        .filter(pl.col("parent_name").is_not_null() & (pl.col("parent_name") != ""))
        .unique(subset=["parent_name"])
    )
    _save_csv(parents_raw, 4, "parents_raw")
    print(f"     Carpetas padre únicas: {parents_raw.height}")

    # Paso 5 – Estandarización
    standardized = parents_raw.with_columns(
        pl.col("parent_name")
        .map_elements(standardize_name, return_dtype=pl.String)
        .alias("name_clean")
    ).filter(pl.col("name_clean") != "")
    _save_csv(standardized.select(["parent_name", "name_clean"]), 5, "parents_standardized")

    # Paso 6 – Agrupación por name_clean
    grouped = (
        standardized.group_by("name_clean")
        .agg(pl.len().alias("count"))
        .sort("count", descending=True)
    )
    _save_csv(grouped, 6, "grouped_counts")
    vc = grouped["count"].alias("n").value_counts().sort("count")
    print(f"     Distribución de conteos:\n{vc}")

    # Paso 7 – Filtrado por umbral
    filtered_names = grouped.filter(pl.col("count") <= REPEAT_THRESHOLD)
    _save_csv(filtered_names, 7, "filtered_names")
    print(f"     Nombres conservados: {filtered_names.height:,} / {grouped.height:,}")

    # Paso 8 – Tabla final
    valid_names = set(filtered_names["name_clean"].to_list())
    final_df = (
        standardized.filter(pl.col("name_clean").is_in(valid_names))
        .select(["parent_name", "name_clean"])
        .unique(subset=["parent_name"])
        .sort("name_clean")
    )
    _save_csv(final_df, 8, "final_output")

    print(f"[Step 1] Completado. CSVs en: {os.path.abspath(OUTPUT_DIR)}/")


if __name__ == "__main__":
    run()

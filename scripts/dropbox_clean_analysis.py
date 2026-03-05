"""
dropbox_clean_analysis.py
=========================
Análisis y limpieza de carpetas de Dropbox para identificar carpetas raíz de clientes.

Flujo:
  1. Carga carpetas desde la BD (type = 'folder').
  2. Limpieza básica de nombres  → 01_clean_items.csv
  3. Top 50 carpetas más repetidas  → 02_top_50.csv
  4. Top 50 que inician con número  → 03_numeric_top50.csv
  5. Carpetas del catálogo que coinciden con el top numérico
     + extracción del nombre del padre  → 04_parents_raw.csv
  6. Estandarización con legal-data-cleaner (standardize_name)  → 05_parents_standardized.csv
  7. Agrupación por name_clean + conteo  → 06_grouped_counts.csv  ← revisar umbral
  8. Filtrado (count <= THRESHOLD)  → 07_filtered_names.csv
  9. Cruce final: parent_name + name_clean  → 08_final_output.csv
"""

import os
import re
import sys

import polars as pl
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from unidecode import unidecode

# ---------------------------------------------------------------------------
# Intentamos importar standardize_name; si falla, avisamos con claridad.
# ---------------------------------------------------------------------------
try:
    from legal_data_cleaner import standardize_name
except ImportError as exc:
    sys.exit(
        f"[ERROR] No se encontró 'legal-data-cleaner'.\n"
        f"  Instálala con: pip install git+https://github.com/lortegamendozafirm/legal-data-cleaner.git\n"
        f"  Detalle: {exc}"
    )

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------
load_dotenv()

DB_NAME = os.getenv("DB_NAME", "dropbox_index")
DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5433")
DB_USER = os.getenv("DB_USER", "user")
DB_PASS = os.getenv("DB_PASS", "pass")

OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")

# Umbral: se descartan nombres que aparecen MÁS de este número de veces.
# Se exporta el conteo completo (step 7) para que puedas ajustarlo.
REPEAT_THRESHOLD = int(os.getenv("REPEAT_THRESHOLD", "3"))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_engine():
    url = f"postgresql+psycopg2://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"
    return create_engine(url)


def save_csv(df: pl.DataFrame, step: int, name: str) -> None:
    """Guarda un DataFrame como CSV numerado dentro de OUTPUT_DIR."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, f"{step:02d}_{name}.csv")
    df.write_csv(path)
    print(f"  [CSV {step:02d}] {path}  ({df.height:,} filas)")


def basic_clean(name: str) -> str:
    """
    Limpieza básica del nombre de carpeta (NO usa standardize_name):
      1. Quitar puntos.
      2. Transliterar a ASCII (acentos, ñ, caracteres especiales).
      3. Colapsar espacios múltiples a uno solo.
      4. Eliminar espacios al inicio y al final.
      5. Convertir a mayúsculas.
    """
    if not isinstance(name, str):
        return ""
    name = name.replace(".", "")           # 1. Quitar puntos
    name = unidecode(name)                 # 2. Unicode → ASCII
    name = re.sub(r"\s+", " ", name)       # 3. Espacios múltiples
    name = name.strip()                    # 4. Trim
    name = name.upper()                    # 5. Upper
    return name


def extract_parent_name(path_display: str) -> str:
    """
    Extrae el nombre de la carpeta padre inmediata del path_display.

    Ejemplo:
      "/Clientes/JOSE PENA/documentos" → "JOSE PENA"
      "/Clientes/JOSE PENA"            → "Clientes"
      "/JOSE PENA"                     → ""   (raíz, sin padre relevante)
    """
    if not isinstance(path_display, str):
        return ""
    # Regex equivalente al de R: substring(path_display from '/([^/]+)/[^/]+$')
    match = re.search(r"/([^/]+)/[^/]+$", path_display)
    return match.group(1) if match else ""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    print("=" * 60)
    print("  Análisis de carpetas Dropbox")
    print("=" * 60)

    # -----------------------------------------------------------------------
    # PASO 0 – Conexión y carga de datos
    # -----------------------------------------------------------------------
    print("\n[0] Conectando a la base de datos...")
    engine = make_engine()

    query = text(
        "SELECT id, name, path_display, path_lower, parent_path_lower, size "
        "FROM dropbox_items "
        "WHERE type = 'folder'"
    )
    with engine.connect() as conn:
        result = conn.execute(query)
        raw_df = pl.DataFrame([dict(row) for row in result.mappings()])

    print(f"     Carpetas cargadas: {raw_df.height:,}")

    # -----------------------------------------------------------------------
    # PASO 1 – Limpieza básica de nombres  →  01_clean_items.csv
    # -----------------------------------------------------------------------
    print("\n[1] Limpieza básica de nombres de carpetas...")
    clean_df = raw_df.with_columns(
        pl.col("name").map_elements(basic_clean, return_dtype=pl.String).alias("name_clean")
    )
    save_csv(clean_df.select(["name", "name_clean"]), 1, "clean_items")

    # -----------------------------------------------------------------------
    # PASO 2 – Top 50 carpetas más repetidas  →  02_top_50.csv
    # -----------------------------------------------------------------------
    print("\n[2] Calculando top 50 carpetas por frecuencia...")
    top_50 = (
        clean_df.group_by("name_clean")
        .agg(pl.len().alias("count"))
        .sort("count", descending=True)
        .head(50)
    )
    save_csv(top_50, 2, "top_50")

    # -----------------------------------------------------------------------
    # PASO 3 – Del Top 50, las que inician con número  →  03_numeric_top50.csv
    # -----------------------------------------------------------------------
    print("\n[3] Filtrando top 50 que inician con dígito...")
    numeric_top50 = top_50.filter(pl.col("name_clean").str.contains(r"^\d"))
    save_csv(numeric_top50, 3, "numeric_top50")
    print(f"     Carpetas numéricas en top 50: {numeric_top50.height}")

    if numeric_top50.is_empty():
        print("\n  [AVISO] No se encontraron carpetas numéricas en el top 50.")
        print("          Verifica los datos y ajusta el criterio si es necesario.")
        sys.exit(0)

    # -----------------------------------------------------------------------
    # PASO 4 – Carpetas del catálogo que coinciden + extracción del padre
    #           →  04_parents_raw.csv
    # -----------------------------------------------------------------------
    print("\n[4] Extrayendo carpetas padre de los ítems numéricos...")
    numeric_names = set(numeric_top50["name_clean"].to_list())

    parents_raw = (
        clean_df.filter(pl.col("name_clean").is_in(numeric_names))
        .with_columns(
            pl.col("path_display").map_elements(extract_parent_name, return_dtype=pl.String).alias("parent_name")
        )
        .select(["path_display", "name_clean", "parent_name"])
        .filter(pl.col("parent_name").is_not_null() & (pl.col("parent_name") != ""))
        .unique(subset=["parent_name"])
    )
    save_csv(parents_raw, 4, "parents_raw")
    print(f"     Carpetas padre únicas: {parents_raw.height}")

    # -----------------------------------------------------------------------
    # PASO 5 – Estandarización con legal-data-cleaner  →  05_parents_standardized.csv
    # -----------------------------------------------------------------------
    print("\n[5] Aplicando standardize_name() a los nombres de carpetas padre...")
    standardized = parents_raw.with_columns(
        pl.col("parent_name").map_elements(standardize_name, return_dtype=pl.String).alias("name_clean")
    )

    # Descartamos los que quedaron vacíos tras la estandarización
    standardized = standardized.filter(pl.col("name_clean") != "")
    save_csv(standardized.select(["parent_name", "name_clean"]), 5, "parents_standardized")

    # -----------------------------------------------------------------------
    # PASO 6 – Agrupación por name_clean + conteo  →  06_grouped_counts.csv
    #          (usa este CSV para decidir si REPEAT_THRESHOLD=3 es correcto)
    # -----------------------------------------------------------------------
    print("\n[6] Agrupando por name_clean y contando repeticiones...")
    grouped = (
        standardized.group_by("name_clean")
        .agg(pl.len().alias("count"))
        .sort("count", descending=True)
    )
    save_csv(grouped, 6, "grouped_counts")
    vc = grouped["count"].value_counts().sort("count")
    print(f"     Distribución de conteos:\n{vc}")

    # -----------------------------------------------------------------------
    # PASO 7 – Filtrado: descartar los que superen el umbral  →  07_filtered_names.csv
    # -----------------------------------------------------------------------
    print(f"\n[7] Filtrando: conservando name_clean con count <= {REPEAT_THRESHOLD}...")
    filtered_names = grouped.filter(pl.col("count") <= REPEAT_THRESHOLD)
    save_csv(filtered_names, 7, "filtered_names")
    print(f"     Nombres conservados: {filtered_names.height:,} / {grouped.height:,}")

    # -----------------------------------------------------------------------
    # PASO 8 – Cruce final: parent_name + name_clean  →  08_final_output.csv
    #
    # Partimos de `standardized` (parent_name → name_clean) y nos quedamos
    # solo con los name_clean que pasaron el filtro.  Cada parent_name es único
    # por construcción (se deduplicó en el paso 4), así que no hay duplicados.
    # -----------------------------------------------------------------------
    print("\n[8] Generando tabla final (parent_name + name_clean)...")

    valid_names = set(filtered_names["name_clean"].to_list())

    final_df = (
        standardized.filter(pl.col("name_clean").is_in(valid_names))
        .select(["parent_name", "name_clean"])
        .unique(subset=["parent_name"])
        .sort("name_clean")
    )

    save_csv(final_df, 8, "final_output")

    # -----------------------------------------------------------------------
    # Resumen
    # -----------------------------------------------------------------------
    print("\n" + "=" * 60)
    print("  Proceso finalizado.")
    print(f"  CSVs guardados en: {os.path.abspath(OUTPUT_DIR)}/")
    print("=" * 60)
    print("\n  01_clean_items.csv          → Carpetas con nombre básico limpio")
    print("  02_top_50.csv               → Top 50 más repetidas")
    print("  03_numeric_top50.csv        → Del top 50, las que inician con dígito")
    print("  04_parents_raw.csv          → Carpetas padre (antes de estandarizar)")
    print("  05_parents_standardized.csv → Carpetas padre con standardize_name()")
    print("  06_grouped_counts.csv       → Agrupación completa (revisa el umbral aquí)")
    print(f"  07_filtered_names.csv       → Filtrado (count <= {REPEAT_THRESHOLD})")
    print("  08_final_output.csv         → Tabla final: parent_name + name_clean")


if __name__ == "__main__":
    main()

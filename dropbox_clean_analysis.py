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

import pandas as pd
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


def save_csv(df: pd.DataFrame, step: int, name: str) -> None:
    """Guarda un DataFrame como CSV numerado dentro de OUTPUT_DIR."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, f"{step:02d}_{name}.csv")
    df.to_csv(path, index=False, encoding="utf-8")
    print(f"  [CSV {step:02d}] {path}  ({len(df):,} filas)")


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
        raw_df = pd.read_sql(query, conn)

    print(f"     Carpetas cargadas: {len(raw_df):,}")

    # -----------------------------------------------------------------------
    # PASO 1 – Limpieza básica de nombres  →  01_clean_items.csv
    # -----------------------------------------------------------------------
    print("\n[1] Limpieza básica de nombres de carpetas...")
    clean_df = raw_df.copy()
    clean_df["name_clean"] = clean_df["name"].apply(basic_clean)
    save_csv(clean_df[["name", "name_clean"]], 1, "clean_items")

    # -----------------------------------------------------------------------
    # PASO 2 – Top 50 carpetas más repetidas  →  02_top_50.csv
    # -----------------------------------------------------------------------
    print("\n[2] Calculando top 50 carpetas por frecuencia...")
    top_50 = (
        clean_df.groupby("name_clean", dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
        .head(50)
        .reset_index(drop=True)
    )
    save_csv(top_50, 2, "top_50")

    # -----------------------------------------------------------------------
    # PASO 3 – Del Top 50, las que inician con número  →  03_numeric_top50.csv
    # -----------------------------------------------------------------------
    print("\n[3] Filtrando top 50 que inician con dígito...")
    numeric_top50 = top_50[top_50["name_clean"].str.match(r"^\d", na=False)].reset_index(drop=True)
    save_csv(numeric_top50, 3, "numeric_top50")
    print(f"     Carpetas numéricas en top 50: {len(numeric_top50)}")

    if numeric_top50.empty:
        print("\n  [AVISO] No se encontraron carpetas numéricas en el top 50.")
        print("          Verifica los datos y ajusta el criterio si es necesario.")
        sys.exit(0)

    # -----------------------------------------------------------------------
    # PASO 4 – Carpetas del catálogo que coinciden + extracción del padre
    #           →  04_parents_raw.csv
    # -----------------------------------------------------------------------
    print("\n[4] Extrayendo carpetas padre de los ítems numéricos...")
    numeric_names = set(numeric_top50["name_clean"])

    numeric_items = clean_df[clean_df["name_clean"].isin(numeric_names)].copy()

    numeric_items["parent_name"] = numeric_items["path_display"].apply(extract_parent_name)

    parents_raw = (
        numeric_items[["path_display", "name_clean", "parent_name"]]
        .copy()
        .dropna(subset=["parent_name"])
        .query("parent_name != ''")
        .drop_duplicates(subset=["parent_name"])
        .reset_index(drop=True)
    )
    save_csv(parents_raw, 4, "parents_raw")
    print(f"     Carpetas padre únicas: {len(parents_raw)}")

    # -----------------------------------------------------------------------
    # PASO 5 – Estandarización con legal-data-cleaner  →  05_parents_standardized.csv
    # -----------------------------------------------------------------------
    print("\n[5] Aplicando standardize_name() a los nombres de carpetas padre...")
    standardized = parents_raw.copy()
    standardized["name_clean"] = standardized["parent_name"].apply(standardize_name)

    # Descartamos los que quedaron vacíos tras la estandarización
    standardized = standardized[standardized["name_clean"] != ""].reset_index(drop=True)
    save_csv(standardized[["parent_name", "name_clean"]], 5, "parents_standardized")

    # -----------------------------------------------------------------------
    # PASO 6 – Agrupación por name_clean + conteo  →  06_grouped_counts.csv
    #          (usa este CSV para decidir si REPEAT_THRESHOLD=3 es correcto)
    # -----------------------------------------------------------------------
    print("\n[6] Agrupando por name_clean y contando repeticiones...")
    grouped = (
        standardized.groupby("name_clean", dropna=False)
        .size()
        .reset_index(name="count")
        .sort_values("count", ascending=False)
        .reset_index(drop=True)
    )
    save_csv(grouped, 6, "grouped_counts")
    print(f"     Distribución de conteos:\n{grouped['count'].value_counts().sort_index().to_string()}")

    # -----------------------------------------------------------------------
    # PASO 7 – Filtrado: descartar los que superen el umbral  →  07_filtered_names.csv
    # -----------------------------------------------------------------------
    print(f"\n[7] Filtrando: conservando name_clean con count <= {REPEAT_THRESHOLD}...")
    filtered_names = grouped[grouped["count"] <= REPEAT_THRESHOLD].reset_index(drop=True)
    save_csv(filtered_names, 7, "filtered_names")
    print(f"     Nombres conservados: {len(filtered_names):,} / {len(grouped):,}")

    # -----------------------------------------------------------------------
    # PASO 8 – Cruce final: parent_name + name_clean  →  08_final_output.csv
    #
    # Partimos de `standardized` (parent_name → name_clean) y nos quedamos
    # solo con los name_clean que pasaron el filtro.  Cada parent_name es único
    # por construcción (se deduplicó en el paso 4), así que no hay duplicados.
    # -----------------------------------------------------------------------
    print("\n[8] Generando tabla final (parent_name + name_clean)...")

    valid_names = set(filtered_names["name_clean"])

    final_df = (
        standardized[standardized["name_clean"].isin(valid_names)]
        [["parent_name", "name_clean"]]
        .drop_duplicates(subset=["parent_name"])
        .sort_values("name_clean")
        .reset_index(drop=True)
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

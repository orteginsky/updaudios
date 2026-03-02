"""
Step 0: Extrae la lista de audios desde DB2 (base de datos de llamadas).

Usa la consulta definida en sentencia_sql.txt.
Salida: output/audios_sql.csv  (columnas: path, file_name, name)
"""
import os
import sys
from pathlib import Path

import polars as pl
from sqlalchemy import create_engine, text

OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")
AUDIOS_DB_URL = os.getenv("AUDIOS_DB_URL")
SQL_FILE = Path(__file__).parent.parent / "sentencia_sql.txt"


def run() -> int:
    if not AUDIOS_DB_URL:
        sys.exit("[Step 0] ERROR: La variable AUDIOS_DB_URL no está configurada.")

    if not SQL_FILE.exists():
        sys.exit(f"[Step 0] ERROR: No se encontró {SQL_FILE}")

    sql = SQL_FILE.read_text(encoding="utf-8")

    print("[Step 0] Conectando a la base de datos de audios...")
    engine = create_engine(AUDIOS_DB_URL)

    with engine.connect() as conn:
        result = conn.execute(text(sql))
        df = pl.DataFrame([dict(row) for row in result.mappings()])

    os.makedirs(OUTPUT_DIR, exist_ok=True)
    out = os.path.join(OUTPUT_DIR, "audios_sql.csv")
    df.write_csv(out)

    print(f"[Step 0] {df.height:,} audios extraídos → {out}")
    return df.height


if __name__ == "__main__":
    run()

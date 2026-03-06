"""
Step 2: Cruce inteligente de audios con carpetas de Dropbox (3 fases).

Entradas:
  - output/08_final_output.csv  (parent_name, name_clean)
  - output/audios_sql.csv       (path, file_name, name)

El campo 'name' del CSV de audios es el nombre del cliente (usado para el match).
El campo 'file_name' es el nombre del archivo mp3.
El campo 'path' es el directorio local donde reside el archivo.

Salida: output/mapeo_audios.csv  (file_name, path, nombre_limpio_audio, parent_name)
"""
import os

import polars as pl
from legal_data_cleaner import standardize_name
from thefuzz import fuzz

OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")

PATH_DROPBOX_CSV = os.path.join(OUTPUT_DIR, "08_final_output.csv")
PATH_AUDIOS_CSV = os.path.join(OUTPUT_DIR, "audios_sql.csv")
PATH_OUTPUT = os.path.join(OUTPUT_DIR, "mapeo_audios.csv")

COLS_FINAL = ["file_name", "path", "nombre_limpio_audio", "parent_name"]


def solve_fuzzy_intersection(name_audio, name_dropbox, word_match_threshold=0.5, fuzzy_threshold=80):
    """Fase 3: Match híbrido (Intersección + Fuzzy)."""
    if not name_audio or not name_dropbox:
        return False

    words_audio = name_audio.split()
    words_dropbox = name_dropbox.split()

    exact_matches = [w for w in words_audio if w in words_dropbox]

    if len(exact_matches) / len(words_audio) >= word_match_threshold:
        remaining_audio = [w for w in words_audio if w not in words_dropbox]
        remaining_dropbox = [w for w in words_dropbox if w not in exact_matches]

        matches_found = 0
        for w_a in remaining_audio:
            for w_d in remaining_dropbox:
                if fuzz.ratio(w_a, w_d) >= fuzzy_threshold:
                    matches_found += 1
                    remaining_dropbox.remove(w_d)
                    break

        if (len(exact_matches) + matches_found) == len(words_audio):
            return True

    return False


def solve_unordered_match(name_audio, name_dropbox):
    """Fase 2: Match por sets (ignora orden, soporta nombres compuestos)."""
    if not name_audio or not name_dropbox:
        return False
    return set(name_audio.split()).issubset(set(name_dropbox.split()))


def run() -> None:
    print("[Step 2] Iniciando cruce inteligente de nombres...")

    # 1. Carga de datos
    df_dropbox = pl.read_csv(PATH_DROPBOX_CSV)
    df_audios = pl.read_csv(PATH_AUDIOS_CSV, null_values="#N/A")

    # Normalización: usamos 'name' (nombre del cliente) para el match
    print("     Normalizando nombres de clientes...")
    df_audios = df_audios.with_columns(
        pl.col("name")
        .map_elements(standardize_name, return_dtype=pl.String)
        .alias("nombre_limpio_audio")
    )

    # --- FASE 1: Match Exacto ---
    print("     Ejecutando Fase 1: Match Exacto...")
    df_match_f1 = df_audios.join(
        df_dropbox,
        left_on="nombre_limpio_audio",
        right_on="name_clean",
        how="inner"
    ).select(COLS_FINAL)

    # --- FASE 2: Intersección de Palabras ---
    df_faltantes_f1 = df_audios.join(df_match_f1, on="file_name", how="anti")
    print(f"     Fase 2: Procesando {df_faltantes_f1.height} registros pendientes...")

    db_list = df_dropbox.select(["name_clean", "parent_name"]).to_dicts()
    resultados_f2 = []

    for row in df_faltantes_f1.to_dicts():
        audio_limpio = row["nombre_limpio_audio"]
        for db_row in db_list:
            if solve_unordered_match(audio_limpio, db_row["name_clean"]):
                row["parent_name"] = db_row["parent_name"]
                resultados_f2.append(row)
                break

    df_match_f2 = (
        pl.DataFrame(resultados_f2).select(COLS_FINAL)
        if resultados_f2
        else pl.DataFrame(schema=df_match_f1.schema)
    )

    # --- FASE 3: Match Híbrido (Fuzzy) ---
    df_temp_total = pl.concat([df_match_f1, df_match_f2])
    df_faltantes_f2 = df_audios.join(df_temp_total, on="file_name", how="anti")

    print(f"     Fase 3: Procesando {df_faltantes_f2.height} registros con lógica Fuzzy...")

    resultados_f3 = []
    for row in df_faltantes_f2.to_dicts():
        audio_limpio = row["nombre_limpio_audio"]
        for db_row in db_list:
            if solve_fuzzy_intersection(audio_limpio, db_row["name_clean"]):
                row["parent_name"] = db_row["parent_name"]
                resultados_f3.append(row)
                break

    df_match_f3 = (
        pl.DataFrame(resultados_f3).select(COLS_FINAL)
        if resultados_f3
        else pl.DataFrame(schema=df_match_f1.schema)
    )

    # --- Ensamblaje final ---
    df_final = pl.concat([df_match_f1, df_match_f2, df_match_f3])
    df_final.write_csv(PATH_OUTPUT)

    print(f"\n     Fase 1 (Exacto):  {df_match_f1.height}")
    print(f"     Fase 2 (Sets):    {df_match_f2.height}")
    print(f"     Fase 3 (Fuzzy):   {df_match_f3.height}")
    print(f"     --------------------------------")
    print(f"     Total recuperado: {df_final.height} de {df_audios.height}")
    print(f"     Tasa final:       {(df_final.height / df_audios.height * 100):.2f}%")
    print(f"[Step 2] Completado → {PATH_OUTPUT}")


if __name__ == "__main__":
    run()

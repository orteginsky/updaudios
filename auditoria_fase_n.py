import polars as pl
import os

def auditoria_fase_2():
    # 1. Configuración de rutas
    PATH_INPUT = "lista_audios_gcs.csv"
    PATH_MAPEO_FINAL = "mapeo_audios.csv"
    PATH_DEBUG_RESTANTE = "dismatch_clientes_message.csv"

    print("--- Iniciando Auditoría de Faltantes (Post-Fase 2) ---")

    if not os.path.exists(PATH_MAPEO_FINAL):
        print(f"❌ No se encontró {PATH_MAPEO_FINAL}. Asegúrate de correr el script de Cruce v2 primero.")
        return

    try:
        # 2. Cargar los datos
        df_total = pl.read_csv(PATH_INPUT)
        df_exitosos = pl.read_csv(PATH_MAPEO_FINAL)

        # 3. Anti-Join
        # Buscamos los registros en 'df_total' que NO están en 'df_exitosos'
        # Usamos 'name' como llave única
        df_restante = df_total.join(
            df_exitosos,
            on="name",
            how="anti"
        )

        # 4. Enriquecer con el nombre limpio para facilitar tu lectura
        from legal_data_cleaner import standardize_name
        
        print("Limpiando nombres restantes para análisis visual...")
        df_restante = df_restante.with_columns(
            pl.col("name")
            .map_elements(standardize_name, return_dtype=pl.String)
            .alias("nombre_limpio_para_revisar")
        )

        # 5. Exportar
        df_restante.write_csv(PATH_DEBUG_RESTANTE)

        print("\n--- Resultados de la Auditoría ---")
        print(f"📋 Total de registros sin destino: {df_restante.height}")
        print(f"📂 Archivo para revisión manual: {PATH_DEBUG_RESTANTE}")

        if df_restante.height > 0:
            print("\n🧐 Muestra de los rebeldes:")
            print(df_restante.select(["nombre_limpio_para_revisar"]).head(10))

    except Exception as e:
        print(f"❌ Error en la auditoría: {e}")

if __name__ == "__main__":
    auditoria_fase_2()
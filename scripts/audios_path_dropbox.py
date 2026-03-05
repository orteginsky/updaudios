import asyncio
import polars as pl
import httpx
from sqlalchemy import create_engine, text
from app.auth_service import auth_service

# 1. Configuración de conexión
DATABASE_URL = "postgresql://user:pass@localhost:5433/dropbox_index"
engine = create_engine(DATABASE_URL)

DROPBOX_CREATE_LINK_URL = "https://api.dropboxapi.com/2/sharing/create_shared_link_with_settings"


DROPBOX_LIST_LINKS_URL = "https://api.dropboxapi.com/2/sharing/list_shared_links"


def get_shared_link(client: httpx.Client, token: str, folder_id: str):
    """
    Obtiene o crea un enlace compartible público para un folder de Dropbox.
    - 200: link creado, lo devuelve directo.
    - 409 con metadata inline: lo extrae del error.
    - 409 sin metadata: llama a list_shared_links como fallback.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    response = client.post(
        DROPBOX_CREATE_LINK_URL,
        headers=headers,
        json={"path": folder_id, "settings": {"requested_visibility": "public"}},
    )

    if response.status_code == 200:
        return response.json().get("url")

    if response.status_code == 409:
        # A veces Dropbox incluye la metadata del link existente en el error
        meta = (
            response.json()
            .get("error", {})
            .get("shared_link_already_exists", {})
            .get("metadata", {})
        )
        if meta.get("url"):
            return meta["url"]

        # Fallback: consultamos el link existente directamente
        r2 = client.post(
            DROPBOX_LIST_LINKS_URL,
            headers=headers,
            json={"path": folder_id, "direct_only": True},
        )
        if r2.status_code == 200:
            links = r2.json().get("links", [])
            if links:
                return links[0].get("url")

    return None


def generar_csv_con_urls(csv_input, csv_output):
    # 2. Extraer datos de la DB (incluimos id para usar en la API)
    query = "SELECT id, path_display, name FROM dropbox_items WHERE type = 'folder'"

    with engine.connect() as conn:
        result = conn.execute(text(query))
        df_db = pl.DataFrame([dict(row) for row in result.mappings()])

    # 3. Cargar el CSV original y Limpieza
    df_csv = pl.read_csv(csv_input)
    df_db = df_db.with_columns(pl.col("name").str.strip_chars())
    df_csv = df_csv.with_columns(pl.col("parent_name").str.strip_chars())

    # 4. Cruce de datos (Left Join)
    df_resultado = df_csv.join(
        df_db,
        left_on="parent_name",
        right_on="name",
        how="left"
    )

    # 5. Generar enlaces compartibles via Dropbox API usando el id del folder
    # (el path_display falla en cuentas Business por namespace; el id funciona directo)
    print("Generando enlaces compartibles de Dropbox...")
    token = asyncio.run(auth_service.get_valid_token())

    # Deduplicamos por id para no llamar a la API más de una vez por carpeta
    unique_ids = df_resultado["id"].drop_nulls().unique().to_list()
    shared_links = {}

    with httpx.Client(timeout=30.0) as client:
        for i, folder_id in enumerate(unique_ids, 1):
            shared_links[folder_id] = get_shared_link(client, token, folder_id)
            print(f"  {i}/{len(unique_ids)}", end="\r")

    print()
    df_resultado = df_resultado.with_columns(
        pl.col("id").map_elements(lambda x: shared_links.get(x), return_dtype=pl.String).alias("dropbox_url")
    )

    # 6. Selección de columnas finales
    # En polars el join descarta la columna "name" del lado derecho (join key),
    # por lo que "name" del csv (nombre del audio) queda sin sufijo.
    df_final = df_resultado.select([
        "path_display",
        "name",
        "nombre_limpio_audio",
        "parent_name",
        "dropbox_url"
    ])

    # 7. Exportar
    df_final.write_csv(csv_output)
    print(f"✅ Archivo generado exitosamente: {csv_output}")


if __name__ == "__main__":
    generar_csv_con_urls("mapeo_audios.csv", "mapeo_audios_con_urls.csv")

"""
Step 4: Sube los audios locales a la subcarpeta 'Recordings' del cliente en Dropbox.

Lee los archivos de audio desde el sistema de archivos local (montado como volumen
en Docker). La ruta física proviene de las columnas 'path' y 'file_name' del CSV.

Entradas:
  - output/mapeo_audios_con_urls.csv  (path_display, file_name, path, ...)
  - Archivos de audio en el volumen montado

Variables de entorno para el mapeo de rutas:
  AUDIOS_HOST_PREFIX  Prefijo de ruta en el host a sustituir (ej: /var/www/html/FILES/descarga_audios)
  AUDIOS_MOUNT        Punto de montaje en el contenedor          (ej: /audios)

Salida: output/resultado_migracion_audios.csv
"""
import asyncio
import json
import os

import httpx
import polars as pl
from app.auth_service import auth_service

OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")
AUDIOS_HOST_PREFIX = os.getenv("AUDIOS_HOST_PREFIX", "")
AUDIOS_MOUNT = os.getenv("AUDIOS_MOUNT", "/audios")
LIMIT = int(os.getenv("LIMIT", "50"))
MAX_REINTENTOS = 3
ESPERA_REINTENTO = 5

PATH_INPUT = os.path.join(OUTPUT_DIR, "mapeo_audios_con_urls.csv")
PATH_OUTPUT = os.path.join(OUTPUT_DIR, "resultado_migracion_audios.csv")


def get_local_audio_path(directory: str, file_name: str) -> str:
    """Construye la ruta del archivo dentro del contenedor."""
    if AUDIOS_HOST_PREFIX and directory.startswith(AUDIOS_HOST_PREFIX):
        relative = directory[len(AUDIOS_HOST_PREFIX):].lstrip("/")
        directory = os.path.join(AUDIOS_MOUNT, relative)
    return os.path.join(directory, file_name)


async def _dropbox_post(url: str, **kwargs) -> httpx.Response:
    """POST a la API de Dropbox con reintentos ante fallos de red."""
    ultimo_error = None
    for intento in range(1, MAX_REINTENTOS + 1):
        try:
            async with httpx.AsyncClient(timeout=kwargs.pop("timeout", 30.0)) as client:
                return await client.post(url, **kwargs)
        except httpx.ConnectError as e:
            ultimo_error = e
            if intento < MAX_REINTENTOS:
                print(f"  ⚠️  Error de red (intento {intento}/{MAX_REINTENTOS}), reintentando en {ESPERA_REINTENTO}s...")
                await asyncio.sleep(ESPERA_REINTENTO)
    raise httpx.ConnectError(f"Sin conexión tras {MAX_REINTENTOS} intentos: {ultimo_error}")


async def obtener_namespace(token: str) -> str | None:
    """Detecta el root_namespace_id del Team Space (Dropbox Business)."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            "https://api.dropboxapi.com/2/users/get_current_account",
            headers={"Authorization": f"Bearer {token}"},
            content=b"null",
        )
        resp.raise_for_status()
        root_info = resp.json().get("root_info", {})
        root_ns = root_info.get("root_namespace_id")
        home_ns = root_info.get("home_namespace_id")
        if root_ns and root_ns != home_ns:
            print(f"  Team Space detectado. Namespace: {root_ns}")
            return root_ns
        return None


def _build_headers(token: str, namespace_id: str | None, extra: dict | None = None) -> dict:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    if namespace_id:
        headers["Dropbox-API-Path-Root"] = json.dumps(
            {".tag": "namespace_id", "namespace_id": namespace_id}
        )
    if extra:
        headers.update(extra)
    return headers


async def obtener_subcarpeta_con_recordings(token: str, path_display: str, namespace_id: str | None) -> str | None:
    """Busca la primera subcarpeta con 'recording' en el nombre (case-insensitive)."""
    endpoint_list = "https://api.dropboxapi.com/2/files/list_folder"
    endpoint_continue = "https://api.dropboxapi.com/2/files/list_folder/continue"
    headers = _build_headers(token, namespace_id)

    target = path_display.strip().rstrip("/")
    response = await _dropbox_post(endpoint_list, json={"path": target, "recursive": False}, headers=headers)

    if response.status_code == 409:
        error_info = response.json().get("error", {})
        error_tag = error_info.get(".tag", "unknown")
        sub_tag = error_info.get(error_tag, {}).get(".tag", "")
        detalle = f"{error_tag}/{sub_tag}" if sub_tag else error_tag
        print(f"  ⚠️  Dropbox 409 ({detalle}): {target}")
        return None

    response.raise_for_status()
    data = response.json()

    while True:
        for entry in data.get("entries", []):
            if entry.get(".tag") == "folder" and "recording" in entry.get("name", "").lower():
                return entry.get("path_display")

        if not data.get("has_more"):
            break

        cursor = data["cursor"]
        response = await _dropbox_post(endpoint_continue, json={"cursor": cursor}, headers=headers)
        response.raise_for_status()
        data = response.json()

    return None


async def subir_a_dropbox(token: str, destino_path: str, nombre_archivo: str, contenido: bytes, namespace_id: str | None) -> dict:
    """Sube un archivo a Dropbox vía la API de contenido."""
    endpoint = "https://content.dropboxapi.com/2/files/upload"
    dropbox_path = f"{destino_path.rstrip('/')}/{nombre_archivo}"

    headers = _build_headers(token, namespace_id, extra={
        "Content-Type": "application/octet-stream",
        "Dropbox-API-Arg": json.dumps({
            "path": dropbox_path,
            "mode": "add",
            "autorename": True,
            "mute": False,
        }),
    })

    response = await _dropbox_post(endpoint, content=contenido, headers=headers, timeout=120.0)
    response.raise_for_status()
    return response.json()


async def _main():
    print("[Step 4] Cargando CSV de mapeo...")
    df = pl.read_csv(PATH_INPUT)
    df_lote = df.head(LIMIT)
    total = df_lote.height
    print(f"     Procesando {total} audios.\n")

    # Obtener token y namespace de Dropbox
    print("     Obteniendo token Dropbox...")
    token = await auth_service.get_valid_token()
    print("     Detectando namespace de Dropbox...")
    namespace_id = await obtener_namespace(token)
    print()

    cache_subcarpetas: dict[str, str | None] = {}
    resultados = []

    for i, row in enumerate(df_lote.to_dicts(), start=1):
        nombre_audio = row["file_name"]
        path_display = row["path_display"]

        print(f"[{i}/{total}] {nombre_audio}")

        # Validar que path_display exista
        if not path_display:
            print("  ⚠️  path_display vacío, saltando.")
            resultados.append({**row, "estado": "sin_path_display", "destino_dropbox": None})
            continue

        # Verificar existencia del archivo local
        local_path = get_local_audio_path(row["path"], nombre_audio)
        if not os.path.exists(local_path):
            print(f"  ⚠️  Archivo no encontrado en: {local_path}")
            resultados.append({**row, "estado": "no_encontrado_local", "destino_dropbox": None})
            continue

        # Obtener subcarpeta destino en Dropbox (con caché por path_display)
        if path_display not in cache_subcarpetas:
            try:
                subcarpeta = await obtener_subcarpeta_con_recordings(token, path_display, namespace_id)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401:
                    token = await auth_service.get_valid_token(force_refresh=True)
                    subcarpeta = await obtener_subcarpeta_con_recordings(token, path_display, namespace_id)
                else:
                    raise
            except httpx.ConnectError as e:
                print(f"  ❌ Sin conexión al listar carpeta: {e}")
                resultados.append({**row, "estado": "error_red", "destino_dropbox": None})
                continue
            cache_subcarpetas[path_display] = subcarpeta

        subcarpeta = cache_subcarpetas[path_display]

        if not subcarpeta:
            print(f"  ⚠️  Sin subcarpeta 'Recordings' en: {path_display}")
            resultados.append({**row, "estado": "sin_subcarpeta_recordings", "destino_dropbox": None})
            continue

        # Leer audio desde el sistema de archivos local
        print(f"  📂  Leyendo archivo local: {local_path}")
        with open(local_path, "rb") as f:
            contenido = f.read()

        # Subir a Dropbox
        print(f"  ⬆️  Subiendo a Dropbox: {subcarpeta}")
        try:
            resultado_upload = await subir_a_dropbox(token, subcarpeta, nombre_audio, contenido, namespace_id)
            destino = resultado_upload.get("path_display")
            print(f"  ✅ Subido: {destino}")
            resultados.append({**row, "estado": "subido", "destino_dropbox": destino})

        except httpx.ConnectError as e:
            print(f"  ❌ Sin conexión al subir archivo: {e}")
            resultados.append({**row, "estado": "error_red", "destino_dropbox": None})
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                token = await auth_service.get_valid_token(force_refresh=True)
                resultado_upload = await subir_a_dropbox(token, subcarpeta, nombre_audio, contenido, namespace_id)
                destino = resultado_upload.get("path_display")
                print(f"  ✅ Subido (token renovado): {destino}")
                resultados.append({**row, "estado": "subido", "destino_dropbox": destino})
            else:
                print(f"  ❌ Error Dropbox HTTP {e.response.status_code}: {e.response.text}")
                resultados.append({**row, "estado": f"error_dropbox_{e.response.status_code}", "destino_dropbox": None})

    df_resultado = pl.DataFrame(resultados) if resultados else pl.DataFrame()
    df_resultado.write_csv(PATH_OUTPUT)

    subidos = df_resultado.filter(pl.col("estado") == "subido").height if resultados else 0
    print(f"\n[Step 4] Proceso completado: {subidos}/{total} audios subidos.")
    print(f"         Resultado → {PATH_OUTPUT}")


def run() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    run()

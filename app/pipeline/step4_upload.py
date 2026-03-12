"""
Step 4: Sube los audios locales a la subcarpeta 'Psychology' (dentro de 'Recordings')
        del cliente en Dropbox.

Flujo de destino por audio:
  1. Carpeta del cliente  (path_display de step 3)
  2. → subcarpeta con 'recording' en el nombre
  3. → subcarpeta con 'psy', 'pys' o 'psi' en el nombre (psychology)
       Si no existe, se crea como 'PSYCHOLOGY'

Entradas:
  - output/mapeo_audios_con_urls.csv  (path_display, file_name, path, ...)
  - Archivos de audio en el volumen montado


Salida: output/resultado_migracion_audios.csv
"""
import asyncio
import json
import os

import httpx
import polars as pl
from app.auth_service import auth_service

OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")
LIMIT = int(os.getenv("LIMIT", "0"))  # 0 = sin límite
MAX_REINTENTOS = 5
ESPERA_REINTENTO = 5

PATH_INPUT = os.path.join(OUTPUT_DIR, "mapeo_audios_con_urls.csv")
PATH_OUTPUT = os.path.join(OUTPUT_DIR, "resultado_migracion_audios.csv")


def get_local_audio_path(directory: str, file_name: str) -> str:
    """Construye la ruta del archivo usando la ruta provista por la base de datos de IT."""
    return os.path.join(directory, file_name)


async def _dropbox_post(url: str, **kwargs) -> httpx.Response:
    """POST a la API de Dropbox con reintentos ante fallos de red y rate limiting (429)."""
    timeout = kwargs.pop("timeout", 30.0)
    ultimo_error = None
    ultima_resp = None
    for intento in range(1, MAX_REINTENTOS + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, **kwargs)
                if resp.status_code == 429:
                    ultima_resp = resp
                    retry_after = int(resp.headers.get("Retry-After", 0))
                    wait = retry_after if retry_after > 0 else min(2 ** intento * ESPERA_REINTENTO, 300)
                    print(f"  ⏳  Rate limit 429, esperando {wait}s (intento {intento}/{MAX_REINTENTOS})...")
                    await asyncio.sleep(wait)
                    continue
                return resp
        except httpx.ConnectError as e:
            ultimo_error = e
            if intento < MAX_REINTENTOS:
                print(f"  ⚠️  Error de red (intento {intento}/{MAX_REINTENTOS}), reintentando en {ESPERA_REINTENTO}s...")
                await asyncio.sleep(ESPERA_REINTENTO)
    if ultimo_error:
        raise httpx.ConnectError(f"Sin conexión tras {MAX_REINTENTOS} intentos: {ultimo_error}")
    # 429 persistente tras todos los reintentos
    ultima_resp.raise_for_status()


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


_PSY_KEYWORDS = ("psy", "pys", "psi")


async def obtener_o_crear_carpeta_psychology(token: str, recordings_path: str, namespace_id: str | None) -> str:
    """Busca dentro de 'recordings' una subcarpeta que contenga psy/pys/psi.
    Si no existe la crea como 'PSYCHOLOGY' y devuelve su path_display."""
    endpoint_list = "https://api.dropboxapi.com/2/files/list_folder"
    endpoint_continue = "https://api.dropboxapi.com/2/files/list_folder/continue"
    headers = _build_headers(token, namespace_id)

    target = recordings_path.strip().rstrip("/")
    response = await _dropbox_post(endpoint_list, json={"path": target, "recursive": False}, headers=headers)
    response.raise_for_status()
    data = response.json()

    while True:
        for entry in data.get("entries", []):
            if entry.get(".tag") == "folder":
                if any(kw in entry.get("name", "").lower() for kw in _PSY_KEYWORDS):
                    found = entry.get("path_display")
                    print(f"  🔍  Carpeta Psychology encontrada: {found}")
                    return found

        if not data.get("has_more"):
            break

        cursor = data["cursor"]
        response = await _dropbox_post(endpoint_continue, json={"cursor": cursor}, headers=headers)
        response.raise_for_status()
        data = response.json()

    # No existe: crear PSYCHOLOGY
    nueva_path = f"{target}/PSYCHOLOGY"
    print(f"  📁  Carpeta Psychology no encontrada. Creando: {nueva_path}")
    resp = await _dropbox_post(
        "https://api.dropboxapi.com/2/files/create_folder_v2",
        json={"path": nueva_path, "autorename": False},
        headers=_build_headers(token, namespace_id),
    )
    resp.raise_for_status()
    return resp.json().get("metadata", {}).get("path_display", nueva_path)


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
    total = df.height
    print(f"     Total de audios en mapeo: {total}")

    # Cargar checkpoint previo para reanudar sin re-subir lo ya procesado
    ya_subidos: set[str] = set()
    if os.path.exists(PATH_OUTPUT):
        df_prev = pl.read_csv(PATH_OUTPUT)
        ya_subidos = set(df_prev.filter(pl.col("estado") == "subido")["file_name"].to_list())
        resultados = df_prev.to_dicts()
        print(f"     Checkpoint encontrado: {len(ya_subidos)} audios ya subidos, retomando...")
    else:
        resultados = []

    pendientes = total - len(ya_subidos)
    print(f"     Pendientes de subir: {pendientes}\n")

    # Obtener token y namespace de Dropbox
    print("     Obteniendo token Dropbox...")
    token = await auth_service.get_valid_token()
    print("     Detectando namespace de Dropbox...")
    namespace_id = await obtener_namespace(token)
    print()

    # Cache: path_display del cliente → path_display de la carpeta PSYCHOLOGY final
    cache_destino: dict[str, str | None] = {}

    for i, row in enumerate(df.to_dicts(), start=1):
        nombre_audio = row["file_name"]
        path_display = row["path_display"]

        if nombre_audio in ya_subidos:
            continue

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

        # Resolver carpeta destino final (Recordings → Psychology) con caché
        if path_display not in cache_destino:
            try:
                recordings = await obtener_subcarpeta_con_recordings(token, path_display, namespace_id)
                if recordings:
                    destino_final = await obtener_o_crear_carpeta_psychology(token, recordings, namespace_id)
                else:
                    destino_final = None
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401:
                    token = await auth_service.get_valid_token(force_refresh=True)
                    recordings = await obtener_subcarpeta_con_recordings(token, path_display, namespace_id)
                    destino_final = await obtener_o_crear_carpeta_psychology(token, recordings, namespace_id) if recordings else None
                else:
                    raise
            except httpx.ConnectError as e:
                print(f"  ❌ Sin conexión al listar carpeta: {e}")
                resultados.append({**row, "estado": "error_red", "destino_dropbox": None})
                continue
            cache_destino[path_display] = destino_final

        destino_final = cache_destino[path_display]

        if not destino_final:
            print(f"  ⚠️  Sin subcarpeta 'Recordings' en: {path_display}")
            resultados.append({**row, "estado": "sin_subcarpeta_recordings", "destino_dropbox": None})
            continue

        # Leer audio desde el sistema de archivos local
        print(f"  📂  Leyendo archivo local: {local_path}")
        with open(local_path, "rb") as f:
            contenido = f.read()

        # Subir a la carpeta Psychology
        print(f"  ⬆️  Subiendo a Dropbox: {destino_final}")
        try:
            resultado_upload = await subir_a_dropbox(token, destino_final, nombre_audio, contenido, namespace_id)
            destino = resultado_upload.get("path_display")
            print(f"  ✅ Subido: {destino}")
            resultados.append({**row, "estado": "subido", "destino_dropbox": destino})

        except httpx.ConnectError as e:
            print(f"  ❌ Sin conexión al subir archivo: {e}")
            resultados.append({**row, "estado": "error_red", "destino_dropbox": None})
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                token = await auth_service.get_valid_token(force_refresh=True)
                resultado_upload = await subir_a_dropbox(token, destino_final, nombre_audio, contenido, namespace_id)
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

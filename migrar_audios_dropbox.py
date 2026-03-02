import asyncio
import sys
import os
import json
import pandas as pd
import httpx
from google.cloud import storage
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# Importar auth_service del proyecto
sys.path.insert(0, '/home/ortega/test')
from app.auth_service import auth_service

# GCS config (tomada de audios_nombres.py)
BUCKET_NAME = "audiospsych_it"
PREFIX = "audios_test/"
SCOPES = ['https://www.googleapis.com/auth/devstorage.read_only']

INPUT_CSV = "/home/ortega/updaudios/mapeo_audios_con_urls.csv"
OUTPUT_CSV = "resultado_migracion_audios.csv"
LIMIT = 50
MAX_REINTENTOS = 3
ESPERA_REINTENTO = 5


async def _dropbox_post(url: str, **kwargs) -> httpx.Response:
    """Ejecuta un POST a la API de Dropbox con reintentos ante fallos de red."""
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
    """
    Detecta el root_namespace_id del Team Space (Dropbox Business).
    Retorna None si la cuenta es personal y no requiere namespace especial.
    """
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
        # Si root != home es una cuenta Business/Team con namespace propio
        if root_ns and root_ns != home_ns:
            print(f"  Team Space detectado. Namespace: {root_ns}")
            return root_ns
        return None


def _build_headers(token: str, namespace_id: str | None, extra: dict | None = None) -> dict:
    """Construye los headers base de Dropbox, añadiendo el namespace si aplica."""
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


def obtener_credenciales_gcs():
    """Gestiona la autenticación OAuth para GCS (igual que audios_nombres.py)."""
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token_file:
            token_file.write(creds.to_json())
    return creds



async def obtener_subcarpeta_con_recordings(token: str, path_display: str, namespace_id: str | None) -> str | None:
    """
    Lista el contenido de path_display en Dropbox (con paginación completa) y retorna
    el path_display de la primera subcarpeta cuyo nombre contiene 'recordings'
    (sin importar mayúsculas ni posición). Devuelve None si no encuentra ninguna.
    """
    endpoint_list     = "https://api.dropboxapi.com/2/files/list_folder"
    endpoint_continue = "https://api.dropboxapi.com/2/files/list_folder/continue"
    headers = _build_headers(token, namespace_id)

    target = path_display.strip().rstrip('/')
    response = await _dropbox_post(endpoint_list, json={"path": target, "recursive": False}, headers=headers)

    if response.status_code == 409:
        error_info = response.json().get("error", {})
        error_tag  = error_info.get(".tag", "unknown")
        sub_tag    = error_info.get(error_tag, {}).get(".tag", "")
        detalle    = f"{error_tag}/{sub_tag}" if sub_tag else error_tag
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
    """Sube un archivo a Dropbox via la API de contenido."""
    endpoint    = "https://content.dropboxapi.com/2/files/upload"
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


async def main():
    # 1. Cargar CSV y tomar los primeros 50
    print("Cargando CSV...")
    df = pd.read_csv(INPUT_CSV)
    df_50 = df.head(LIMIT)
    total = len(df_50)
    print(f"Procesando {total} audios.\n")

    # 2. Autenticar GCS
    print("--- Autenticando GCS ---")
    creds = obtener_credenciales_gcs()
    storage_client = storage.Client(credentials=creds)
    bucket = storage_client.bucket(BUCKET_NAME)

    # 3. Obtener token Dropbox y namespace del Team Space
    print("--- Obteniendo token Dropbox ---")
    token = await auth_service.get_valid_token()
    print("--- Detectando namespace de Dropbox ---")
    namespace_id = await obtener_namespace(token)
    print()

    # Caché de subcarpetas: evita consultar Dropbox varias veces por el mismo path_display
    cache_subcarpetas: dict[str, str | None] = {}

    resultados = []

    for i, (_, row) in enumerate(df_50.iterrows(), start=1):
        nombre_audio = row['name']
        path_display = row['path_display']

        print(f"[{i}/{total}] {nombre_audio}")

        # Validar que path_display exista
        if pd.isna(path_display):
            print("  ⚠️  path_display vacío, saltando.")
            resultados.append({**row, 'estado': 'sin_path_display', 'destino_dropbox': None})
            continue

        # 4. Verificar existencia en GCS
        blob_name = f"{PREFIX}{nombre_audio}"
        blob = bucket.blob(blob_name)
        if not blob.exists():
            print(f"  ⚠️  No encontrado en GCS: gs://{BUCKET_NAME}/{blob_name}")
            resultados.append({**row, 'estado': 'no_encontrado_gcs', 'destino_dropbox': None})
            continue

        # 5. Obtener subcarpeta destino en Dropbox (con caché por path_display)
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
                resultados.append({**row, 'estado': 'error_red', 'destino_dropbox': None})
                continue
            cache_subcarpetas[path_display] = subcarpeta

        subcarpeta = cache_subcarpetas[path_display]

        if not subcarpeta:
            print(f"  ⚠️  Sin subcarpeta con 'Recordings' en: {path_display}")
            resultados.append({**row, 'estado': 'sin_subcarpeta_recordings', 'destino_dropbox': None})
            continue

        # 6. Descargar audio de GCS
        print(f"  ⬇️  Descargando de GCS...")
        contenido = blob.download_as_bytes()

        # 7. Subir a Dropbox
        print(f"  ⬆️  Subiendo a Dropbox: {subcarpeta}")
        try:
            resultado_upload = await subir_a_dropbox(token, subcarpeta, nombre_audio, contenido, namespace_id)
            destino = resultado_upload.get("path_display")
            print(f"  ✅ Subido: {destino}")
            resultados.append({**row, 'estado': 'subido', 'destino_dropbox': destino})

        except httpx.ConnectError as e:
            print(f"  ❌ Sin conexión al subir archivo: {e}")
            resultados.append({**row, 'estado': 'error_red', 'destino_dropbox': None})
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                # Token expirado: renovar y reintentar una vez
                token = await auth_service.get_valid_token(force_refresh=True)
                resultado_upload = await subir_a_dropbox(token, subcarpeta, nombre_audio, contenido, namespace_id)
                destino = resultado_upload.get("path_display")
                print(f"  ✅ Subido (token renovado): {destino}")
                resultados.append({**row, 'estado': 'subido', 'destino_dropbox': destino})
            else:
                print(f"  ❌ Error Dropbox HTTP {e.response.status_code}: {e.response.text}")
                resultados.append({**row, 'estado': f'error_dropbox_{e.response.status_code}', 'destino_dropbox': None})

    # 8. Guardar resultados
    df_resultado = pd.DataFrame(resultados)
    df_resultado.to_csv(OUTPUT_CSV, index=False, encoding='utf-8-sig')

    subidos = df_resultado[df_resultado['estado'] == 'subido'].shape[0]
    print(f"\nProceso completado: {subidos}/{total} audios subidos.")
    print(f"Resultado guardado en: {OUTPUT_CSV}")


if __name__ == "__main__":
    asyncio.run(main())

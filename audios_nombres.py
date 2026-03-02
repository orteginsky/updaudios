import os
import csv
from google.cloud import storage
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

# Definimos los SCOPES necesarios para leer GCS
SCOPES = ['https://www.googleapis.com/auth/devstorage.read_only']
CREDENTIALS_FOLDER_PATH = os.path.join(os.getcwd(),"credentials")
CREDENTIALS_PATH = os.path.join(CREDENTIALS_FOLDER_PATH,"credentials.json")
TOKEN_PATH = os.path.join(CREDENTIALS_FOLDER_PATH,"token.json")

def obtener_credenciales_oauth():
    """Gestiona la autenticación OAuth y devuelve las credenciales."""
    creds = None
    # El archivo token.json almacena los tokens de acceso y actualización del usuario
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
    
    # Si no hay credenciales válidas, pedimos al usuario que inicie sesión
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Asegúrate de que 'credentials.json' sea el archivo de OAuth Client ID
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
        
        # Guardamos las credenciales para la próxima ejecución
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    
    return creds

def extraer_nombres_audios():
    # 1. Configuración del Bucket
    BUCKET_NAME = "audiospsych_it"
    PREFIX = "audios_test/"
    OUTPUT_CSV = "lista_audios_gcs.csv"

    print("--- Autenticando mediante OAuth 2.0 ---")
    creds = obtener_credenciales_oauth()

    try:
        # 2. Inicializar el cliente de Storage con las credenciales OAuth
        storage_client = storage.Client(credentials=creds)
        bucket = storage_client.bucket(BUCKET_NAME)
        
        print(f"--- Extrayendo nombres desde gs://{BUCKET_NAME}/{PREFIX} ---")
        blobs = bucket.list_blobs(prefix=PREFIX)

        nombres_extraidos = []

        for blob in blobs:
            # Validamos que no sea el nombre de la carpeta misma
            if not blob.name.endswith('/'):
                # Quitamos el prefijo para obtener solo el nombre del archivo
                nombre_limpio = blob.name.replace(PREFIX, "")
                nombres_extraidos.append(nombre_limpio)

        # 3. Escritura del CSV
        with open(OUTPUT_CSV, mode='w', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(['name'])
            for nombre in nombres_extraidos:
                writer.writerow([nombre])

        print(f"✅ Proceso completado. Se encontraron {len(nombres_extraidos)} audios.")
        print(f"📂 Archivo generado: {OUTPUT_CSV}")

    except Exception as e:
        print(f"❌ Error al acceder a GCS: {e}")

if __name__ == "__main__":
    extraer_nombres_audios()
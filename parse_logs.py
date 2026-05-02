"""
parse_logs.py — Reconstruye resultado_migracion_audios.csv a partir de logs.txt

Uso:
    python parse_logs.py [--logs logs.txt] [--mapeo output/mapeo_audios_con_urls.csv] [--out resultado_reconstruido.csv]

Lógica:
- Si un archivo aparece en múltiples intentos del step, se prioriza "subido" sobre
  cualquier otro estado (un upload exitoso en cualquier intento cuenta).
- Se cruza con el CSV de mapeo para recuperar path_display, path, etc.
"""

import argparse
import csv
import re
import sys

# ── Patrones ────────────────────────────────────────────────────────────────
RE_AUDIO    = re.compile(r'\[(\d+)/(\d+)\] (.+\.mp3)')
RE_LOCAL    = re.compile(r'📂\s+Leyendo archivo local: (.+)')
RE_SUBIDO   = re.compile(r'✅ Subido(?:\s+\(token renovado\))?: (.+)')
RE_NO_LOCAL = re.compile(r'⚠️\s+Archivo no encontrado en: (.+)')
RE_SIN_PATH = re.compile(r'⚠️\s+path_display vacío')
RE_SIN_REC  = re.compile(r'⚠️\s+Sin subcarpeta .Recordings. en: (.+)')
RE_ERR_RED  = re.compile(r'❌ Error de transporte al (?:subir|listar carpeta)')
RE_ERR_HTTP = re.compile(r'❌ Error Dropbox HTTP (\d+)')
RE_DRY_RUN  = re.compile(r'🧪\s+\[DRY_RUN\] Simularía subida → (.+)')

# Quita el prefijo "app-1  | " que pone docker-compose logs
RE_PREFIX   = re.compile(r'^[^\|]+\|\s*')


def strip_prefix(line: str) -> str:
    return RE_PREFIX.sub('', line).rstrip()


def parse_logs(logs_path: str) -> dict[str, dict]:
    """
    Devuelve un dict {file_name: {estado, destino_dropbox, path_local}}
    Prioridad: "subido" > cualquier otro estado (conserva el primer subido).
    """
    resultados: dict[str, dict] = {}

    current_file = None
    current_local = None
    current_estado = None
    current_destino = None

    def commit():
        """Guarda el estado del archivo actual en resultados."""
        nonlocal current_file, current_local, current_estado, current_destino
        if current_file is None:
            return
        prev = resultados.get(current_file)
        # Prioridad: si ya está como "subido", no sobreescribir
        if prev and prev['estado'] == 'subido':
            current_file = current_local = current_estado = current_destino = None
            return
        if current_estado:
            resultados[current_file] = {
                'estado': current_estado,
                'destino_dropbox': current_destino or '',
                'path_local': current_local or '',
            }
        current_file = current_local = current_estado = current_destino = None

    with open(logs_path, encoding='utf-8', errors='replace') as f:
        for raw in f:
            line = strip_prefix(raw)

            m = RE_AUDIO.search(line)
            if m:
                commit()
                current_file = m.group(3)
                current_local = None
                current_estado = None
                current_destino = None
                continue

            if current_file is None:
                continue

            m = RE_LOCAL.search(line)
            if m:
                current_local = m.group(1).strip()
                continue

            m = RE_SUBIDO.search(line)
            if m:
                current_estado = 'subido'
                current_destino = m.group(1).strip()
                continue

            m = RE_DRY_RUN.search(line)
            if m:
                current_estado = 'dry_run'
                current_destino = m.group(1).strip()
                continue

            if RE_NO_LOCAL.search(line):
                if current_estado != 'subido':
                    current_estado = 'no_encontrado_local'
                continue

            if RE_SIN_PATH.search(line):
                if current_estado != 'subido':
                    current_estado = 'sin_path_display'
                continue

            if RE_SIN_REC.search(line):
                if current_estado != 'subido':
                    current_estado = 'sin_subcarpeta_recordings'
                continue

            if RE_ERR_RED.search(line):
                if current_estado != 'subido':
                    current_estado = 'error_red'
                continue

            m = RE_ERR_HTTP.search(line)
            if m:
                if current_estado != 'subido':
                    current_estado = f'error_dropbox_{m.group(1)}'
                continue

    commit()  # último archivo
    return resultados


def load_mapeo(mapeo_path: str) -> dict[str, dict]:
    """Carga mapeo_audios_con_urls.csv indexado por file_name."""
    mapeo: dict[str, dict] = {}
    try:
        with open(mapeo_path, encoding='utf-8') as f:
            for row in csv.DictReader(f):
                mapeo[row['file_name']] = row
    except FileNotFoundError:
        print(f"⚠️  Mapeo no encontrado: {mapeo_path} — el CSV saldrá sin columnas de mapeo",
              file=sys.stderr)
    return mapeo


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--logs',  default='logs.txt')
    ap.add_argument('--mapeo', default='output/mapeo_audios_con_urls.csv')
    ap.add_argument('--out',   default='resultado_reconstruido.csv')
    args = ap.parse_args()

    print(f"Parseando {args.logs}...")
    resultados = parse_logs(args.logs)

    print(f"Cruzando con mapeo {args.mapeo}...")
    mapeo = load_mapeo(args.mapeo)

    # Construir filas del CSV de salida
    CAMPOS_MAPEO = ['path_display', 'file_name', 'path', 'nombre_limpio_audio', 'parent_name']
    CAMPOS_OUT   = CAMPOS_MAPEO + ['estado', 'destino_dropbox']

    filas = []
    sin_mapeo = 0
    for file_name, res in resultados.items():
        base = mapeo.get(file_name)
        if base:
            fila = {c: base.get(c, '') for c in CAMPOS_MAPEO}
        else:
            sin_mapeo += 1
            fila = {c: '' for c in CAMPOS_MAPEO}
            fila['file_name'] = file_name

        fila['estado']          = res['estado']
        fila['destino_dropbox'] = res['destino_dropbox']
        filas.append(fila)

    # Ordenar: primero subidos, luego el resto
    filas.sort(key=lambda r: (0 if r['estado'] == 'subido' else 1, r['file_name']))

    with open(args.out, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=CAMPOS_OUT)
        writer.writeheader()
        writer.writerows(filas)

    # Resumen
    from collections import Counter
    estados = Counter(r['estado'] for r in filas)
    total = len(filas)
    print(f"\n✅ CSV generado: {args.out}  ({total} registros)")
    print(f"{'Estado':<35} {'Count':>7}")
    print('-' * 44)
    for estado, n in estados.most_common():
        print(f"  {estado:<33} {n:>7}")
    if sin_mapeo:
        print(f"\n⚠️  {sin_mapeo} archivos sin fila en el mapeo (solo file_name disponible)")


if __name__ == '__main__':
    main()

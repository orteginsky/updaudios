"""
merge_resultados.py — Complementa resultado_reconstruido.csv con las columnas
faltantes (path_display, path, nombre_limpio_audio, parent_name) usando
resultado_migracion_audios.csv como fuente de referencia.

Lógica de merge por file_name:
  - Estado final: se prioriza "subido" > cualquier otro.
    Si ambas fuentes tienen estado distinto, gana "subido".
  - Columnas de mapeo (path_display, path, etc.): se toman de resultado_migracion_audios.csv
    cuando el reconstruido no las tiene (están vacías).

Uso:
    python merge_resultados.py \
        [--reconstruido resultado_reconstruido.csv] \
        [--referencia  resultado_migracion_audios.csv] \
        [--out         resultado_final.csv]
"""

import argparse
import csv
from collections import Counter

CAMPOS = ['path_display', 'file_name', 'path', 'nombre_limpio_audio', 'parent_name',
          'estado', 'destino_dropbox']

CAMPOS_MAPEO = ['path_display', 'path', 'nombre_limpio_audio', 'parent_name']


def load_csv(path: str) -> dict[str, dict]:
    rows = {}
    with open(path, encoding='utf-8') as f:
        for row in csv.DictReader(f):
            rows[row['file_name']] = row
    return rows


def prioridad(estado: str) -> int:
    """Menor número = mayor prioridad."""
    if estado == 'subido':
        return 0
    if estado.startswith('error_dropbox'):
        return 2
    if estado == 'error_red':
        return 3
    return 4  # no_encontrado_local, sin_path_display, sin_subcarpeta_recordings


def merge(rec: dict, ref: dict) -> dict:
    """
    rec  = fila de resultado_reconstruido (tiene estado/destino, puede tener mapeo vacío)
    ref  = fila de resultado_migracion    (tiene mapeo completo, estado puede ser viejo)
    """
    fila = {c: rec.get(c, '') for c in CAMPOS}

    # Completar columnas de mapeo vacías con la referencia
    for col in CAMPOS_MAPEO:
        if not fila[col] and ref.get(col):
            fila[col] = ref[col]

    # Elegir mejor estado entre las dos fuentes
    estado_ref = ref.get('estado', '')
    if estado_ref and prioridad(estado_ref) < prioridad(fila['estado']):
        fila['estado'] = estado_ref
        fila['destino_dropbox'] = ref.get('destino_dropbox', '')

    return fila


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--reconstruido', default='resultado_reconstruido.csv')
    ap.add_argument('--referencia',   default='resultado_migracion_audios.csv')
    ap.add_argument('--out',          default='resultado_final.csv')
    args = ap.parse_args()

    print(f"Cargando reconstruido: {args.reconstruido}")
    reconstruido = load_csv(args.reconstruido)
    print(f"  {len(reconstruido)} registros")

    print(f"Cargando referencia:   {args.referencia}")
    referencia = load_csv(args.referencia)
    print(f"  {len(referencia)} registros")

    # Universo = unión de ambas fuentes
    todos = set(reconstruido) | set(referencia)
    print(f"Universo total (unión): {len(todos)} archivos\n")

    filas = []
    for file_name in todos:
        rec = reconstruido.get(file_name)
        ref = referencia.get(file_name)

        if rec and ref:
            fila = merge(rec, ref)
        elif rec:
            # Solo en reconstruido (no estaba en el CSV viejo)
            fila = {c: rec.get(c, '') for c in CAMPOS}
        else:
            # Solo en referencia (no apareció en los logs)
            fila = {c: ref.get(c, '') for c in CAMPOS}

        filas.append(fila)

    # Ordenar: subidos primero, luego por file_name
    filas.sort(key=lambda r: (prioridad(r['estado']), r['file_name']))

    with open(args.out, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=CAMPOS)
        writer.writeheader()
        writer.writerows(filas)

    # Resumen
    estados = Counter(r['estado'] for r in filas)
    sin_mapeo = sum(1 for r in filas if not r['path_display'])

    print(f"✅ CSV generado: {args.out}  ({len(filas)} registros)")
    print(f"\n{'Estado':<35} {'Count':>7}")
    print('-' * 44)
    for estado, n in estados.most_common():
        print(f"  {estado:<33} {n:>7}")
    if sin_mapeo:
        print(f"\n⚠️  {sin_mapeo} archivos sin path_display (no encontrados en ninguna fuente de mapeo)")


if __name__ == '__main__':
    main()

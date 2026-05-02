"""
reporte_migracion.py — Análisis estadístico completo de la migración de audios.

Genera:
  reporte_migracion/
    00_resumen_general.csv
    01_cobertura_por_cliente.csv
    02_clientes_sin_subida_completa.csv
    03_sin_subcarpeta_recordings.csv
    04_distribucion_temporal.csv
    05_dismatch_frecuencia.csv
    06_carpetas_dropbox_top.csv
    reporte.txt  ← resumen legible

Uso:
    python reporte_migracion.py \
        [--resultado  output/resultado_final.csv] \
        [--mapeo      output/mapeo_audios.csv] \
        [--dismatch   output/dismatch_clientes_message.csv] \
        [--out        reporte_migracion/]
"""

import argparse
import csv
import os
import re
from collections import Counter, defaultdict
from datetime import datetime

# ── Helpers ─────────────────────────────────────────────────────────────────

def load(path: str) -> list[dict]:
    with open(path, encoding='utf-8') as f:
        return list(csv.DictReader(f))

def write_csv(path: str, fieldnames: list[str], rows: list[dict]):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

def pct(n, total):
    return f"{n/total*100:.1f}%" if total else "0%"

RE_FECHA = re.compile(r'_(\d{4})_(\d{2})_(\d{2})_')

def extraer_anio_mes(file_name: str):
    m = RE_FECHA.search(file_name)
    if m:
        return int(m.group(1)), int(m.group(2))
    return None, None

# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--resultado', default='output/resultado_final.csv')
    ap.add_argument('--mapeo',     default='output/mapeo_audios.csv')
    ap.add_argument('--dismatch',  default='output/dismatch_clientes_message.csv')
    ap.add_argument('--out',       default='reporte_migracion')
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    lineas = []  # para reporte.txt

    def titulo(t):
        sep = '=' * 60
        lineas.append(f"\n{sep}\n  {t}\n{sep}")
        print(f"\n{'='*60}\n  {t}\n{'='*60}")

    def log(msg=''):
        lineas.append(msg)
        print(msg)

    # ── Carga de datos ───────────────────────────────────────────────────────
    log("Cargando archivos...")
    resultado  = load(args.resultado)
    mapeo      = load(args.mapeo)
    dismatch   = load(args.dismatch)

    total_resultado = len(resultado)
    total_mapeo     = len(mapeo)
    total_dismatch  = len(dismatch)

    subidos            = [r for r in resultado if r['estado'] == 'subido']
    sin_recordings     = [r for r in resultado if r['estado'] == 'sin_subcarpeta_recordings']
    sin_path           = [r for r in resultado if r['estado'] == 'sin_path_display']
    no_local           = [r for r in resultado if r['estado'] == 'no_encontrado_local']
    otros_errores      = [r for r in resultado
                          if r['estado'] not in ('subido','sin_subcarpeta_recordings',
                                                  'sin_path_display','no_encontrado_local')]

    en_resultado  = {r['file_name'] for r in resultado}
    en_mapeo      = {r['file_name'] for r in mapeo}
    perdidos       = en_mapeo - en_resultado   # estaban en mapeo pero no en resultado

    # ════════════════════════════════════════════════════════════════════════
    titulo("0. RESUMEN GENERAL")
    # ════════════════════════════════════════════════════════════════════════
    universo = total_mapeo + total_dismatch   # audios totales en el sistema

    resumen = [
        {'metrica': 'Audios totales en el sistema (mapeo + dismatch)',  'valor': universo},
        {'metrica': 'Audios en mapeo_audios.csv',                       'valor': total_mapeo},
        {'metrica': 'Audios sin match (dismatch)',                      'valor': total_dismatch},
        {'metrica': 'Audios en resultado_final.csv',                    'valor': total_resultado},
        {'metrica': 'Audios perdidos entre runs (mapeo → resultado)',   'valor': len(perdidos)},
        {'metrica': '',                                                  'valor': ''},
        {'metrica': 'Subidos exitosamente',                             'valor': len(subidos)},
        {'metrica': 'Tasa de éxito (subidos / resultado)',              'valor': pct(len(subidos), total_resultado)},
        {'metrica': 'Tasa de éxito (subidos / mapeo)',                  'valor': pct(len(subidos), total_mapeo)},
        {'metrica': '',                                                  'valor': ''},
        {'metrica': 'Sin subcarpeta Recordings',                        'valor': len(sin_recordings)},
        {'metrica': 'Sin path_display',                                 'valor': len(sin_path)},
        {'metrica': 'No encontrado local',                              'valor': len(no_local)},
        {'metrica': 'Otros errores',                                    'valor': len(otros_errores)},
        {'metrica': '',                                                  'valor': ''},
        {'metrica': 'Clientes únicos en resultado',                     'valor': len({r['parent_name'] for r in resultado if r['parent_name']})},
        {'metrica': 'Clientes con al menos 1 subido',                  'valor': len({r['parent_name'] for r in subidos if r['parent_name']})},
        {'metrica': 'Carpetas destino únicas en Dropbox',              'valor': len({r['destino_dropbox'].rsplit('/',1)[0] for r in subidos if r['destino_dropbox']})},
    ]

    for row in resumen:
        if row['metrica']:
            log(f"  {row['metrica']:<52} {row['valor']}")
    write_csv(f"{args.out}/00_resumen_general.csv", ['metrica','valor'], resumen)

    # ════════════════════════════════════════════════════════════════════════
    titulo("1. COBERTURA POR CLIENTE")
    # ════════════════════════════════════════════════════════════════════════
    por_cliente: dict[str, dict] = defaultdict(lambda: {
        'total': 0, 'subidos': 0, 'sin_recordings': 0,
        'sin_path': 0, 'no_local': 0, 'otros_errores': 0
    })

    for r in resultado:
        c = r['parent_name'] or '(sin_nombre)'
        por_cliente[c]['total'] += 1
        estado = r['estado']
        if estado == 'subido':
            por_cliente[c]['subidos'] += 1
        elif estado == 'sin_subcarpeta_recordings':
            por_cliente[c]['sin_recordings'] += 1
        elif estado == 'sin_path_display':
            por_cliente[c]['sin_path'] += 1
        elif estado == 'no_encontrado_local':
            por_cliente[c]['no_local'] += 1
        else:
            por_cliente[c]['otros_errores'] += 1

    cobertura_rows = []
    for cliente, d in sorted(por_cliente.items()):
        pct_sub = d['subidos'] / d['total'] * 100 if d['total'] else 0
        if d['subidos'] == d['total']:
            cobertura = 'completa'
        elif d['subidos'] == 0:
            cobertura = 'ninguno'
        else:
            cobertura = 'parcial'
        cobertura_rows.append({
            'cliente': cliente,
            'total': d['total'],
            'subidos': d['subidos'],
            'pct_subidos': f"{pct_sub:.1f}%",
            'sin_recordings': d['sin_recordings'],
            'sin_path': d['sin_path'],
            'no_local': d['no_local'],
            'otros_errores': d['otros_errores'],
            'cobertura': cobertura,
        })

    cobertura_rows.sort(key=lambda r: (-int(r['total']), r['cliente']))

    completos = sum(1 for r in cobertura_rows if r['cobertura'] == 'completa')
    parciales = sum(1 for r in cobertura_rows if r['cobertura'] == 'parcial')
    ninguno   = sum(1 for r in cobertura_rows if r['cobertura'] == 'ninguno')

    log(f"  Clientes con subida completa : {completos} ({pct(completos, len(cobertura_rows))})")
    log(f"  Clientes con subida parcial  : {parciales} ({pct(parciales, len(cobertura_rows))})")
    log(f"  Clientes sin ningún subido   : {ninguno}   ({pct(ninguno,   len(cobertura_rows))})")
    write_csv(f"{args.out}/01_cobertura_por_cliente.csv",
              ['cliente','total','subidos','pct_subidos','sin_recordings',
               'sin_path','no_local','otros_errores','cobertura'],
              cobertura_rows)

    # ════════════════════════════════════════════════════════════════════════
    titulo("2. CLIENTES SIN SUBIDA COMPLETA (parcial o ninguno)")
    # ════════════════════════════════════════════════════════════════════════
    incompletos = [r for r in cobertura_rows if r['cobertura'] != 'completa']
    incompletos.sort(key=lambda r: (-int(r['total']), r['cliente']))

    log(f"  Total clientes incompletos: {len(incompletos)}")
    log(f"  Top 10 por audios pendientes:")
    for r in incompletos[:10]:
        pendientes = int(r['total']) - int(r['subidos'])
        log(f"    {r['cliente'][:45]:<45}  {pendientes:>5} pendientes  ({r['pct_subidos']} subidos)")

    write_csv(f"{args.out}/02_clientes_sin_subida_completa.csv",
              ['cliente','total','subidos','pct_subidos','sin_recordings',
               'sin_path','no_local','otros_errores','cobertura'],
              incompletos)

    # ════════════════════════════════════════════════════════════════════════
    titulo("3. SIN SUBCARPETA RECORDINGS")
    # ════════════════════════════════════════════════════════════════════════
    por_cliente_rec = Counter(r['parent_name'] or '(sin_nombre)' for r in sin_recordings)
    rec_rows = [{'cliente': c, 'audios_afectados': n}
                for c, n in por_cliente_rec.most_common()]

    log(f"  Total audios sin Recordings : {len(sin_recordings)}")
    log(f"  Clientes afectados          : {len(rec_rows)}")
    log(f"  Top 10 clientes afectados:")
    for r in rec_rows[:10]:
        log(f"    {r['cliente'][:50]:<50}  {r['audios_afectados']:>4} audios")

    write_csv(f"{args.out}/03_sin_subcarpeta_recordings.csv",
              ['cliente','audios_afectados'], rec_rows)

    # ════════════════════════════════════════════════════════════════════════
    titulo("4. DISTRIBUCIÓN TEMPORAL")
    # ════════════════════════════════════════════════════════════════════════
    temporal: dict[tuple, dict] = defaultdict(lambda: {'total': 0, 'subidos': 0, 'fallidos': 0})

    for r in resultado:
        anio, mes = extraer_anio_mes(r['file_name'])
        if anio is None:
            continue
        key = (anio, mes)
        temporal[key]['total'] += 1
        if r['estado'] == 'subido':
            temporal[key]['subidos'] += 1
        else:
            temporal[key]['fallidos'] += 1

    temporal_rows = []
    for (anio, mes), d in sorted(temporal.items()):
        temporal_rows.append({
            'anio': anio,
            'mes': mes,
            'periodo': f"{anio}-{mes:02d}",
            'total': d['total'],
            'subidos': d['subidos'],
            'fallidos': d['fallidos'],
            'pct_subidos': pct(d['subidos'], d['total']),
        })

    log(f"  Periodos con registros: {len(temporal_rows)}")
    if temporal_rows:
        log(f"  Desde: {temporal_rows[0]['periodo']}  Hasta: {temporal_rows[-1]['periodo']}")
        top_periodo = max(temporal_rows, key=lambda r: r['total'])
        log(f"  Periodo con más audios: {top_periodo['periodo']} ({top_periodo['total']} audios)")
        anios = Counter(r['anio'] for r in temporal_rows for _ in range(
            next(x['total'] for x in temporal_rows if x['anio']==r['anio'] and x['mes']==r['mes'])))
        log(f"  Audios por año:")
        anio_totales = defaultdict(int)
        for r in temporal_rows:
            anio_totales[r['anio']] += r['total']
        for anio, total in sorted(anio_totales.items()):
            log(f"    {anio}: {total:>6} audios")

    write_csv(f"{args.out}/04_distribucion_temporal.csv",
              ['periodo','anio','mes','total','subidos','fallidos','pct_subidos'],
              temporal_rows)

    # ════════════════════════════════════════════════════════════════════════
    titulo("5. DISMATCH — CLIENTES SIN MATCH")
    # ════════════════════════════════════════════════════════════════════════
    dm_por_cliente = Counter(r.get('nombre_limpio_para_revisar') or r.get('name','(vacío)')
                              for r in dismatch)
    dm_rows = [{'nombre_para_revisar': n, 'audios': c}
               for n, c in dm_por_cliente.most_common()]

    log(f"  Total audios sin match: {total_dismatch}")
    log(f"  Clientes únicos sin match: {len(dm_rows)}")
    log(f"  Top 10 clientes con más audios sin match:")
    for r in dm_rows[:10]:
        log(f"    {r['nombre_para_revisar'][:50]:<50}  {r['audios']:>4} audios")

    write_csv(f"{args.out}/05_dismatch_frecuencia.csv",
              ['nombre_para_revisar','audios'], dm_rows)

    # ════════════════════════════════════════════════════════════════════════
    titulo("6. CARPETAS DROPBOX — DISTRIBUCIÓN DE AUDIOS")
    # ════════════════════════════════════════════════════════════════════════
    carpetas = Counter(r['destino_dropbox'].rsplit('/', 1)[0]
                       for r in subidos if r['destino_dropbox'])

    carpeta_rows = [{'carpeta_dropbox': c, 'audios_subidos': n}
                    for c, n in carpetas.most_common()]

    un_audio   = sum(1 for n in carpetas.values() if n == 1)
    cinco_mas  = sum(1 for n in carpetas.values() if n >= 5)
    diez_mas   = sum(1 for n in carpetas.values() if n >= 10)

    log(f"  Carpetas destino únicas          : {len(carpetas)}")
    log(f"  Carpetas con solo 1 audio        : {un_audio}  ({pct(un_audio, len(carpetas))})")
    log(f"  Carpetas con 5 o más audios      : {cinco_mas}")
    log(f"  Carpetas con 10 o más audios     : {diez_mas}")
    log(f"\n  Top 15 carpetas con más audios:")
    for r in carpeta_rows[:15]:
        log(f"    {r['audios_subidos']:>4}  {r['carpeta_dropbox']}")

    write_csv(f"{args.out}/06_carpetas_dropbox_top.csv",
              ['carpeta_dropbox','audios_subidos'], carpeta_rows)

    # ════════════════════════════════════════════════════════════════════════
    # Guardar reporte.txt
    # ════════════════════════════════════════════════════════════════════════
    reporte_path = f"{args.out}/reporte.txt"
    with open(reporte_path, 'w', encoding='utf-8') as f:
        f.write(f"Reporte generado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write('\n'.join(lineas))

    print(f"\n{'='*60}")
    print(f"  Archivos generados en: {args.out}/")
    print(f"{'='*60}")
    for fn in sorted(os.listdir(args.out)):
        print(f"  {fn}")


if __name__ == '__main__':
    main()

"""
main.py — Orquestador del pipeline de migración de audios a Dropbox.

Ejecuta los 6 pasos de forma secuencial, validando que cada paso
haya generado su archivo de salida antes de iniciar el siguiente.
Ante cualquier fallo detiene el proceso y reporta el error.

Uso dentro del contenedor:
    python main.py

Uso local (con .env):
    python main.py
"""
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

OUTPUT_DIR = os.getenv("OUTPUT_DIR", "output")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _banner(msg: str) -> None:
    logger.info("=" * 55)
    logger.info(f"  {msg}")
    logger.info("=" * 55)


def _check_output(filename: str) -> Path:
    """Verifica que el CSV de salida de un paso exista y no esté vacío."""
    path = Path(OUTPUT_DIR) / filename
    if not path.exists():
        raise FileNotFoundError(
            f"El archivo esperado no fue generado: {path}\n"
            f"Revisa los logs del paso anterior."
        )
    if path.stat().st_size == 0:
        raise ValueError(f"El archivo existe pero está vacío: {path}")
    return path


def _run_step(label: str, func, *args, **kwargs):
    """Ejecuta un paso del pipeline con manejo de errores uniforme."""
    _banner(label)
    try:
        result = func(*args, **kwargs)
        logger.info(f"✅  {label} — OK\n")
        return result
    except SystemExit:
        raise
    except Exception as exc:
        logger.error(f"❌  {label} — FALLÓ")
        logger.error(f"    {exc}")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def main() -> None:
    _banner("PIPELINE DE MIGRACIÓN DE AUDIOS A DROPBOX")

    # Importaciones aquí para que los errores de módulo sean claros
    from pipeline import (
        step0_audios,
        step1_dropbox,
        step2_cruce,
        step3_paths,
        step4_upload,
        step5_audit,
    )

    # ── Paso 0: Extraer audios desde DB2 ─────────────────────────────────
    _run_step("Step 0 | Extracción de audios desde DB", step0_audios.run)
    _check_output("audios_sql.csv")

    # ── Paso 1: Analizar carpetas Dropbox desde DB1 ───────────────────────
    _run_step("Step 1 | Análisis de carpetas Dropbox", step1_dropbox.run)
    _check_output("08_final_output.csv")

    # ── Paso 2: Cruce inteligente audios ↔ carpetas ───────────────────────
    _run_step("Step 2 | Cruce de nombres (3 fases)", step2_cruce.run)
    _check_output("mapeo_audios.csv")

    # ── Paso 3: Obtener path_display de Dropbox ───────────────────────────
    _run_step("Step 3 | Obtención de rutas Dropbox", step3_paths.run)
    _check_output("mapeo_audios_con_urls.csv")

    # ── Paso 4: Subir audios a Dropbox ────────────────────────────────────
    _run_step("Step 4 | Subida de audios a Dropbox", step4_upload.run)
    _check_output("resultado_migracion_audios.csv")

    # ── Paso 5: Auditoría de faltantes ────────────────────────────────────
    _run_step("Step 5 | Auditoría de resultados", step5_audit.run)
    _check_output("dismatch_clientes_message.csv")

    _banner("PIPELINE COMPLETADO EXITOSAMENTE")
    logger.info(f"Todos los CSVs están en: {os.path.abspath(OUTPUT_DIR)}/")


if __name__ == "__main__":
    main()

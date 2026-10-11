"""Command line entry point.

    python3 -m explorer capture [--visible] [--only LABEL ...] [--scheduled]
    python3 -m explorer analyze
    python3 -m explorer export-viewer
    python3 -m explorer notify-test
"""
from __future__ import annotations

import argparse
import sys
import traceback

from .config import ANALYSIS_DIR, VIEWER_DATA_JS, load_listings, load_settings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="explorer",
                                     description="Seguimiento diario del calendario de anuncios de Airbnb.")
    sub = parser.add_subparsers(dest="command", required=True)

    cap = sub.add_parser("capture", help="captura el calendario de los anuncios de listings.json")
    cap.add_argument("--visible", action="store_true", help="muestra el navegador mientras captura")
    cap.add_argument("--only", nargs="+", metavar="LABEL", help="captura solo estas etiquetas")
    cap.add_argument("--scheduled", action="store_true",
                     help="corrida programada: espera un tiempo aleatorio antes de empezar")

    sub.add_parser("analyze", help="detecta reservas y genera data/analysis/")
    sub.add_parser("export-viewer", help="regenera viewer/data.js sin capturar")
    sub.add_parser("notify-test", help="envía una notificación de prueba al canal de ntfy")

    args = parser.parse_args(argv)
    settings = load_settings()

    if args.command == "capture":
        from . import notify
        from .capture import run_capture
        listings = load_listings()
        if args.only:
            listings = [l for l in listings if l.label in set(args.only)]
            if not listings:
                raise SystemExit("Ninguna etiqueta de --only está en listings.json.")
        try:
            failures = run_capture(listings, settings, visible=args.visible, scheduled=args.scheduled)
        except Exception as exc:
            notify.send(settings, "Airbnb explorer · la captura falló",
                        f"{type(exc).__name__}: {exc}"[:500], priority=5, tags=["rotating_light"])
            traceback.print_exc()
            return 2
        return 1 if failures else 0

    if args.command == "analyze":
        import pandas as pd
        from .analysis import run_analysis
        events, summary = run_analysis()
        pd.set_option("display.width", 200, "display.max_columns", 30)
        print(summary.set_index("label").T.to_string())
        print(f"\n{len(events)} eventos. Detalle en {ANALYSIS_DIR}/")
        return 0

    if args.command == "export-viewer":
        from .viewer_data import export_viewer_data
        export_viewer_data()
        print(f"Listo: {VIEWER_DATA_JS}")
        return 0

    if args.command == "notify-test":
        from . import notify
        if not settings.get("ntfy_topic"):
            raise SystemExit("Falta ntfy_topic en settings.json.")
        sent = notify.send(settings, "Airbnb explorer · prueba",
                           "Si ves esto, las notificaciones funcionan.", tags=["tada"])
        print(f"Enviada al canal '{settings['ntfy_topic']}'." if sent else "No se pudo enviar; revisa data/capture.log.")
        return 0 if sent else 1
    return 1


if __name__ == "__main__":
    sys.exit(main())

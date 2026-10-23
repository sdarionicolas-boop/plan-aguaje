# -*- coding: utf-8 -*-
"""Orquestador del proyecto "El Territorio de la UNAJ".

Corre las 14 fases del analisis en orden, de punta a punta: desde la
descarga de OSM hasta el informe final en reports/informe_hueco_educativo.md.
Cada fase es una funcion en scripts/*.py; este script solo las invoca en el
orden correcto y con las dependencias resueltas.

Uso:
    python run_all.py                # corre todo, de punta a punta
    python run_all.py <fase>         # corre desde <fase> hasta el final
    python run_all.py --list         # lista las fases disponibles

Ejemplo: si ya se bajaron los edificios y la red vial y solo se quiere
regenerar el informe tras un cambio de redaccion:
    python run_all.py reporte

Idempotencia: la mayoria de las fases son seguras de re-correr.
  - fase1 no vuelve a descargar si data/input/edificios_osm_raw.gpkg existe.
  - censo no vuelve a descargar el GeoPackage de CONICET si ya esta en disco.
  - isocronas cachea la red vial en work/red_vial_osm.pkl.
  - El resto son recalculos deterministas y rapidos (segundos).
Para forzar una redescarga completa, borrar el archivo cacheado
correspondiente antes de correr.
"""
from __future__ import annotations

import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "scripts"))


def _fase1():
    import analisis_educativo as ae
    ae.asegurar_directorios()
    ae.fase1_descarga()


def _inspector():
    import gis_inspector as gi
    import analisis_educativo as ae
    rep = gi.inspeccionar(ae.DIR_INPUT / "edificios_osm_raw.gpkg", "edificios")
    gi.imprimir(rep)


def _fase2():
    import analisis_educativo as ae
    ae.fase2_preparacion()


def _fase3():
    import analisis_educativo as ae
    ae.fase3_buffers()


def _fase4():
    import analisis_educativo as ae
    ae.fase4_hueco()


def _fase5():
    import analisis_educativo as ae
    ae.fase5_cruce()


def _fase6():
    import analisis_educativo as ae
    ae.fase6_distancias()


def _fase7():
    import analisis_educativo as ae
    ae.generar_mapas()


def _calibracion():
    import calibracion_poblacion as cp
    cp.main()


def _censo():
    import cruce_censo as cc
    cc.main()


def _sensibilidad():
    import sensibilidad_radio as sr
    sr.main()


def _isocronas():
    import isocronas as iso
    iso.main()


def _universo():
    import universo_educativo as ue
    ue.main()


def _renabap():
    import cruce_renabap as cr
    cr.main()


def _validacion():
    import validacion_externa as ve
    ve.main()


def _auditor():
    import gis_auditor as ga
    codigo = ga.main()
    if codigo != 0:
        print("\n*** El auditor RECHAZO el analisis (errores criticos). ***")
        print("*** Revisar reports/auditoria.json antes de confiar en el "
              "informe final. ***\n")


def _reporte():
    import gis_reporter as gr
    gr.main()


# Orden de ejecucion. Cada fase depende de que las anteriores hayan corrido
# al menos una vez (los productos quedan en disco entre corridas).
FASES = [
    ("fase1", "Descarga de edificios OSM (area de estudio completa)", _fase1),
    ("inspector", "Inspeccion de calidad de la capa cruda", _inspector),
    ("fase2", "Reproyeccion a EPSG:32721", _fase2),
    ("fase3", "Buffers de 5 km para las 6 universidades", _fase3),
    ("fase4", "Resta topologica: hueco exclusivo UNAJ", _fase4),
    ("fase5", "Cruce con edificios OSM (proxy, luego descartado)", _fase5),
    ("fase6", "Distancias del hueco a cada universidad", _fase6),
    ("fase7", "Mapas 1-3 (buffers, hueco, proxy OSM)", _fase7),
    ("calibracion", "Contraste de plausibilidad del proxy OSM", _calibracion),
    ("censo", "Cruce con radios censales INDEC 2022 (resultado principal)",
     _censo),
    ("sensibilidad", "Sensibilidad al radio de influencia (1-10 km)",
     _sensibilidad),
    ("isocronas", "Areas de servicio sobre la red vial (accesibilidad real)",
     _isocronas),
    ("universo", "Universo completo de universidades nacionales del AMBA",
     _universo),
    ("renabap", "Cruce con barrios populares (RENABAP) - equidad", _renabap),
    ("validacion", "Validacion externa (INDEC, RENABAP vigente, matricula UNAJ)",
     _validacion),
    ("auditor", "Auditoria independiente de todos los productos", _auditor),
    ("reporte", "Informe final en reports/", _reporte),
]


def main() -> int:
    args = sys.argv[1:]
    if args and args[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if args and args[0] == "--list":
        for k, desc, _ in FASES:
            print("  {:<14} {}".format(k, desc))
        return 0

    claves = [k for k, _, _ in FASES]
    inicio = 0
    if args:
        if args[0] not in claves:
            print("Fase desconocida: '{}'. Usar --list para ver las "
                  "disponibles.".format(args[0]))
            return 2
        inicio = claves.index(args[0])

    a_correr = FASES[inicio:]
    print("=" * 78)
    print("EL TERRITORIO DE LA UNAJ - pipeline completo")
    print("Corriendo {} de {} fases, desde '{}'".format(
        len(a_correr), len(FASES), a_correr[0][0]))
    print("=" * 78)

    t_total = time.time()
    for k, desc, fn in a_correr:
        print("\n" + "-" * 78)
        print(">>> [{}] {}".format(k, desc))
        print("-" * 78)
        t0 = time.time()
        try:
            fn()
        except Exception:  # noqa: BLE001
            print("\n*** FASE '{}' FALLO tras {:.1f}s ***\n".format(
                k, time.time() - t0))
            traceback.print_exc()
            return 1
        print(">>> [{}] OK ({:.1f}s)".format(k, time.time() - t0))

    print("\n" + "=" * 78)
    print("PIPELINE COMPLETO en {:.1f} min".format((time.time() - t_total) / 60))
    print("Informe final: " + str(ROOT / "reports" / "informe_hueco_educativo.md"))
    print("=" * 78)
    return 0


if __name__ == "__main__":
    sys.exit(main())

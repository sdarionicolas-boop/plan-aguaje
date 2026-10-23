# -*- coding: utf-8 -*-
"""Contraste de plausibilidad de la estimacion poblacional.

El proxy "edificios OSM x factor" es el metodo pedido, pero su resultado
depende por completo de cuan completo este OSM en la zona. Este modulo NO
reemplaza la estimacion oficial del analisis: la acompana con un contraste
de orden de magnitud para que el informe sea honesto sobre el sesgo.

Uso:
    python scripts/calibracion_poblacion.py
"""
from __future__ import annotations

import json
from pathlib import Path

import geopandas as gpd

ROOT = Path(__file__).resolve().parent.parent
DIR_OUT = ROOT / "outputs"
META = DIR_OUT / "metadatos_analisis.json"

# Densidad de edificios esperable en tejido urbano consolidado del Conurbano
# bonaerense (lotes de 8-12 m de frente, manzanas de 100 x 100 m).
# Es un supuesto declarado, no un dato medido en campo.
DENSIDAD_EDIFICIOS_ESPERADA = (600, 1200)   # edificios/km2
# Densidad poblacional de referencia para partidos del sur del Conurbano.
DENSIDAD_POBLACION_REFERENCIA = (2000, 7000)  # hab/km2


def main() -> None:
    meta = json.loads(META.read_text(encoding="utf-8"))
    hueco = gpd.read_file(DIR_OUT / "hueco_exclusivo_UNAJ.gpkg", layer="hueco")
    area = float(hueco.area.iloc[0] / 1e6)

    n_dentro = meta["edificios_en_hueco_total"]
    dens_osm = n_dentro / area
    pob_osm = meta["poblacion_estimada"]
    dens_pob_osm = pob_osm / area

    # Completitud implicita de OSM: que fraccion del parque construido esperable
    # esta efectivamente mapeada.
    compl = tuple(round(100 * dens_osm / d, 1)
                  for d in DENSIDAD_EDIFICIOS_ESPERADA)
    # Poblacion que resultaria de las densidades de referencia.
    pob_ref = tuple(int(round(d * area, -3))
                    for d in DENSIDAD_POBLACION_REFERENCIA)
    factor_subestimacion = tuple(round(p / pob_osm, 1) for p in pob_ref)

    print("=" * 74)
    print("CONTRASTE DE PLAUSIBILIDAD POBLACIONAL")
    print("=" * 74)
    print("Area del hueco                     : {:.2f} km2".format(area))
    print("Edificios OSM en el hueco          : {:,}".format(n_dentro))
    print("Densidad de edificios OSM          : {:.0f} edif/km2".format(dens_osm))
    print("Densidad esperable en tejido urbano: {}-{} edif/km2".format(
        *DENSIDAD_EDIFICIOS_ESPERADA))
    print("=> completitud implicita de OSM    : {}% a {}%".format(compl[1], compl[0]))
    print()
    print("Estimacion del analisis (metodo pedido): {:,.0f} hab "
          "({:.0f} hab/km2)".format(pob_osm, dens_pob_osm))
    print("Contraste con densidad de referencia   : {:,} a {:,} hab "
          "({}-{} hab/km2)".format(pob_ref[0], pob_ref[1],
                                   *DENSIDAD_POBLACION_REFERENCIA))
    print("=> la estimacion OSM subestimaria en   : x{} a x{}".format(
        *factor_subestimacion))

    meta.update({
        "contraste_densidad": {
            "densidad_edificios_osm_km2": round(dens_osm, 1),
            "densidad_edificios_esperada_km2": list(DENSIDAD_EDIFICIOS_ESPERADA),
            "completitud_osm_pct": list(compl),
            "densidad_poblacion_referencia_km2": list(DENSIDAD_POBLACION_REFERENCIA),
            "poblacion_contraste": list(pob_ref),
            "factor_subestimacion": list(factor_subestimacion),
            "nota": ("Las densidades de referencia son supuestos declarados "
                     "para tejido urbano consolidado del Conurbano sur, no "
                     "mediciones. El contraste sirve para acotar el orden de "
                     "magnitud, no para reemplazar la estimacion del proxy."),
        }
    })
    META.write_text(json.dumps(meta, indent=2, ensure_ascii=False),
                    encoding="utf-8")
    print("\nMetadatos actualizados: " + str(META))


if __name__ == "__main__":
    main()

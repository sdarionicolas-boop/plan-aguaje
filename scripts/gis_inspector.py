# -*- coding: utf-8 -*-
"""Agente gis-inspector + gis-quality.

Inspecciona una capa vectorial y reporta: conteo, CRS, tipos de geometria,
campos disponibles y chequeos de calidad (nulos, invalidas, duplicadas).

Uso:
    python scripts/gis_inspector.py <ruta.gpkg> [capa]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import geopandas as gpd

ROOT = Path(__file__).resolve().parent.parent


def inspeccionar(ruta: Path, capa: str | None = None) -> dict:
    gdf = gpd.read_file(ruta, layer=capa) if capa else gpd.read_file(ruta)

    crs = gdf.crs
    tipos = gdf.geometry.geom_type.value_counts().to_dict()

    campos = {}
    for c in gdf.columns:
        if c == gdf.geometry.name:
            continue
        no_nulos = int(gdf[c].notna().sum())
        if no_nulos:
            campos[c] = {"dtype": str(gdf[c].dtype), "no_nulos": no_nulos,
                         "pct_lleno": round(100 * no_nulos / len(gdf), 1)}

    nulas = int(gdf.geometry.isna().sum())
    vacias = int(gdf.geometry.is_empty.sum())
    invalidas = int((~gdf.geometry.is_valid).sum())
    dup = int(gdf.geometry.duplicated().sum())

    rep = {
        "archivo": str(ruta.relative_to(ROOT)) if ruta.is_relative_to(ROOT) else str(ruta),
        "capa": capa,
        "n_features": int(len(gdf)),
        "crs": crs.to_string() if crs else None,
        "crs_nombre": crs.name if crs else None,
        "crs_proyectado": bool(crs.is_projected) if crs else None,
        "unidades": crs.axis_info[0].unit_name if crs else None,
        "tipos_geometria": tipos,
        "bbox": [round(v, 6) for v in gdf.total_bounds.tolist()],
        "n_campos": len(campos),
        "campos_top20": dict(sorted(campos.items(),
                                    key=lambda kv: -kv[1]["no_nulos"])[:20]),
        "calidad": {
            "geometrias_nulas": nulas,
            "geometrias_vacias": vacias,
            "geometrias_invalidas": invalidas,
            "geometrias_duplicadas": dup,
        },
    }
    return rep


def imprimir(rep: dict) -> None:
    print("=" * 74)
    print("GIS-INSPECTOR  ->  " + str(rep["archivo"]) +
          ("  [capa: " + str(rep["capa"]) + "]" if rep["capa"] else ""))
    print("=" * 74)
    print("Features        : {:,}".format(rep["n_features"]))
    print("CRS             : {} ({})".format(rep["crs"], rep["crs_nombre"]))
    print("Proyectado      : {}  | unidades: {}".format(
        rep["crs_proyectado"], rep["unidades"]))
    print("Tipos geometria : " + ", ".join(
        "{}={:,}".format(k, v) for k, v in rep["tipos_geometria"].items()))
    print("BBOX            : {}".format(rep["bbox"]))
    print("Campos con datos: {}".format(rep["n_campos"]))
    for k, v in rep["campos_top20"].items():
        print("   - {:<24} {:<10} {:>7,} no nulos ({}%)".format(
            k[:24], v["dtype"], v["no_nulos"], v["pct_lleno"]))
    print("GIS-QUALITY     :")
    for k, v in rep["calidad"].items():
        marca = "OK " if v == 0 else "!! "
        print("   {}{:<26} {:,}".format(marca, k, v))
    print()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python scripts/gis_inspector.py <ruta.gpkg> [capa]")
        sys.exit(2)
    ruta = Path(sys.argv[1])
    capa = sys.argv[2] if len(sys.argv) > 2 else None
    r = inspeccionar(ruta, capa)
    imprimir(r)
    destino = ROOT / "reports" / ("inspeccion_" + ruta.stem + ".json")
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps(r, indent=2, ensure_ascii=False),
                       encoding="utf-8")
    print("Reporte JSON: " + str(destino))

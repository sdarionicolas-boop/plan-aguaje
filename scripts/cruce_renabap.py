# -*- coding: utf-8 -*-
"""FASE 15 - Cruce con el RENABAP (Registro Nacional de Barrios Populares).

Agrega la dimension de equidad que falta en el analisis: de la poblacion del
hueco exclusivo de la UNAJ, cuanta vive en barrios populares -- asentamientos
informales sin acceso pleno a servicios basicos, relevados casa por casa por
el Estado nacional. Es el argumento que mas moviliza: la UNAJ no solo es la
unica universidad de proximidad, sino que buena parte de esa proximidad es
para la poblacion con menos alternativas.

Fuente: geoportal SISU (Sistema de Identificacion de Sectores Urbanos),
Ministerio de Obras Publicas / RENABAP, GeoServer institucional (WFS),
capa `renabap2020_smz` (relevamiento 2020, ultima actualizacion oficial
disponible via este servicio). El campo `familias_e` es la cantidad de
familias estimadas por el relevamiento; se convierte a poblacion con el
mismo criterio de INDEC de tamano medio de hogar (Censo 2022, PBA: ~3
personas por hogar), documentado y ajustable.

Uso:
    python scripts/cruce_renabap.py
"""
from __future__ import annotations

import io
import json
import sys
import time
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import requests
from matplotlib.lines import Line2D
from matplotlib.patches import Patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from analisis_educativo import (CRS_GEO, CRS_UTM, DIR_MAPS, DIR_OUT, DIR_WORK,
                                UNIV_OBJETIVO, _decorar, log)

WFS_URL = "https://geoportal.obraspublicas.gob.ar/geoserver/ows"
CAPA_WFS = "geonode:renabap2020_smz"
USER_AGENT = "gis-agent-unaj/1.0 (analisis academico UNAJ)"
GPKG_RENABAP = ROOT / "data" / "censo" / "renabap_amba.gpkg"

# Mismo factor que el resto del proyecto (Censo 2022, tamano medio de hogar
# en la Provincia de Buenos Aires), aplicado sobre "familias" en vez de
# "edificios": aqui el dato de entrada ya es un conteo de hogares releva
# casa por casa, no un proxy de construcciones.
FACTOR_PERSONAS_POR_FAMILIA = 3.0

# Caja que cubre el area de estudio completa (union de los 6 buffers) con
# margen; evita traer el RENABAP de todo el pais.
BBOX_ESTUDIO = (-35.00, -58.55, -34.60, -57.80)  # sur, oeste, norte, este


def descargar_renabap() -> gpd.GeoDataFrame:
    if GPKG_RENABAP.exists():
        log("RENABAP leido del cache: " + str(GPKG_RENABAP))
        return gpd.read_file(GPKG_RENABAP, layer="barrios")

    sur, oeste, norte, este = BBOX_ESTUDIO
    params = {
        "service": "WFS", "version": "1.0.0", "request": "GetFeature",
        "typeName": CAPA_WFS, "outputFormat": "application/json",
        "srsName": "EPSG:4326",
        "bbox": "{},{},{},{}".format(oeste, sur, este, norte),
    }
    r = requests.get(WFS_URL, params=params,
                     headers={"User-Agent": USER_AGENT}, timeout=240)
    r.raise_for_status()
    g = gpd.read_file(io.BytesIO(r.content))
    log("RENABAP descargado: {} barrios populares en el area de estudio"
        .format(len(g)))

    GPKG_RENABAP.parent.mkdir(parents=True, exist_ok=True)
    g.to_file(GPKG_RENABAP, layer="barrios", driver="GPKG")
    log("Guardado: " + str(GPKG_RENABAP))
    return g


def cruzar_con_hueco(renabap: gpd.GeoDataFrame) -> tuple[gpd.GeoDataFrame, dict]:
    hueco = gpd.read_file(DIR_OUT / "hueco_exclusivo_UNAJ.gpkg", layer="hueco")
    if hueco.crs.to_string().upper() != CRS_UTM:
        raise ValueError("El hueco no esta en " + CRS_UTM)
    geom_hueco = hueco.geometry.iloc[0]

    r = renabap.to_crs(CRS_UTM).copy()
    r = r[r.geometry.is_valid & ~r.geometry.is_empty]
    r["area_barrio_m2"] = r.geometry.area

    tocan = r[r.intersects(geom_hueco)].copy()
    log("Barrios populares que intersecan el hueco: {}".format(len(tocan)))

    if not len(tocan):
        vacio = gpd.GeoDataFrame(
            columns=["Barrio", "familias_e", "familias_en_hueco",
                     "poblacion_en_hueco", "fraccion_en_hueco"],
            geometry=[], crs=CRS_UTM)
        return vacio, {
            "n_barrios_en_hueco": 0, "n_familias_en_hueco": 0,
            "poblacion_renabap_en_hueco": 0,
            "pct_poblacion_censal_en_renabap": 0.0,
        }

    tocan["geom_int"] = tocan.geometry.intersection(geom_hueco)
    tocan["area_int_m2"] = tocan["geom_int"].area
    tocan = tocan[tocan["area_int_m2"] > 1].copy()
    tocan["fraccion_en_hueco"] = (tocan["area_int_m2"] /
                                  tocan["area_barrio_m2"]).clip(upper=1.0)
    tocan["familias_en_hueco"] = (tocan["familias_e"].fillna(0) *
                                  tocan["fraccion_en_hueco"])
    tocan["poblacion_en_hueco"] = (tocan["familias_en_hueco"] *
                                   FACTOR_PERSONAS_POR_FAMILIA)

    salida = tocan.set_geometry("geom_int").drop(columns=["geometry"])
    salida = salida.rename_geometry("geometry")
    cols = ["Barrio", "Departamen", "Localidad", "ano_de_cre", "Electricid",
           "Cloaca", "Agua", "familias_e", "fraccion_en_hueco",
           "familias_en_hueco", "poblacion_en_hueco", "geometry"]
    cols = [c for c in cols if c in salida.columns]
    salida = gpd.GeoDataFrame(salida[cols], geometry="geometry", crs=CRS_UTM)
    salida.to_file(DIR_OUT / "renabap_en_hueco.gpkg", layer="barrios",
                   driver="GPKG")
    log("Guardado: " + str(DIR_OUT / "renabap_en_hueco.gpkg"))

    meta_path = DIR_OUT / "metadatos_analisis.json"
    pob_censal = json.loads(meta_path.read_text(encoding="utf-8")
                            )["censo_2022"]["poblacion_censo_2022_total_estimada"]
    pob_renabap = float(salida["poblacion_en_hueco"].sum())

    resumen = {
        "n_barrios_en_hueco": int(len(salida)),
        "n_barrios_integros": int((salida["fraccion_en_hueco"] > 0.999).sum()),
        "n_familias_en_hueco": round(float(salida["familias_en_hueco"].sum())),
        "poblacion_renabap_en_hueco": round(pob_renabap),
        "factor_personas_por_familia": FACTOR_PERSONAS_POR_FAMILIA,
        "pct_poblacion_censal_en_renabap": round(
            100 * pob_renabap / pob_censal, 1),
        "area_renabap_en_hueco_km2": round(
            float(salida.geometry.area.sum()) / 1e6, 2),
        "electricidad_formal_pct": _pct_servicio(salida, "Electricid"),
        "agua_formal_pct": _pct_servicio(salida, "Agua"),
        "cloaca_formal_pct": _pct_servicio(salida, "Cloaca"),
        "partidos": sorted(salida["Departamen"].dropna().unique().tolist())
        if "Departamen" in salida.columns else [],
    }
    return salida, resumen


def _pct_servicio(gdf: gpd.GeoDataFrame, col: str) -> dict | None:
    """% de barrios -y % de familias- con conexion FORMAL al servicio.

    El campo del RENABAP no es si/no: es una descripcion categorica del tipo
    de conexion (p.ej. "Conexion formal a la red publica con medidores
    domiciliarios" vs "Conexion irregular a la red publica" o "Desague solo
    a pozo negro/ciego"). Se clasifica como formal todo valor que contenga
    la palabra "formal"; el resto (irregular, precaria, pozo, etc.) cuenta
    como no formal. Se reportan dos versiones: por cantidad de barrios (cada
    asentamiento pesa igual, sin importar su tamano) y ponderada por
    familias (la que importa para dimensionar cuanta gente esta afectada).
    """
    if col not in gdf.columns or not len(gdf):
        return None
    sub = gdf[[col, "familias_en_hueco"]].dropna(subset=[col])
    if not len(sub):
        return None
    formal = sub[col].astype(str).str.contains("formal", case=False, na=False)
    fam_total = float(sub["familias_en_hueco"].sum())
    return {
        "pct_barrios": round(100 * float(formal.sum()) / len(sub), 1),
        "pct_familias": round(100 * float(sub.loc[formal, "familias_en_hueco"].sum())
                              / fam_total, 1) if fam_total else None,
    }


def mapa(salida: gpd.GeoDataFrame, resumen: dict) -> Path:
    hueco = gpd.read_file(DIR_OUT / "hueco_exclusivo_UNAJ.gpkg", layer="hueco")
    univ = gpd.read_file(DIR_WORK / "universidades_utm.gpkg",
                         layer="universidades")

    fig, ax = plt.subplots(figsize=(11, 11))
    hueco.plot(ax=ax, facecolor="#f2f2f2", edgecolor="#7f0000", linewidth=2.0,
               zorder=1)
    if len(salida):
        salida.plot(ax=ax, facecolor="#e66101", alpha=0.85,
                   edgecolor="#7f3d00", linewidth=0.8, zorder=3)
    hueco.boundary.plot(ax=ax, color="#7f0000", linewidth=2.0, zorder=4)
    u = univ[univ.nombre == UNIV_OBJETIVO]
    u.plot(ax=ax, color="#1b7837", markersize=150, marker="*", zorder=5,
          edgecolor="black", linewidth=0.6)
    ax.annotate("UNAJ", (u.geometry.iloc[0].x, u.geometry.iloc[0].y),
                xytext=(9, 9), textcoords="offset points", fontsize=11,
                fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.25", fc="white", alpha=0.88),
                zorder=6)
    ax.legend(handles=[
        Patch(facecolor="#e66101", alpha=0.85, edgecolor="#7f3d00",
              label="Barrios populares (RENABAP) -- {} barrios, {:,} hab"
              .format(resumen["n_barrios_en_hueco"],
                      resumen["poblacion_renabap_en_hueco"])),
        Line2D([0], [0], color="#7f0000", lw=2.0,
               label="Hueco exclusivo UNAJ"),
        Line2D([0], [0], marker="*", color="w", markerfacecolor="#1b7837",
               markersize=13, label="UNAJ"),
    ], loc="upper left", fontsize=8, framealpha=0.93)
    _decorar(ax, "Barrios populares (RENABAP) en el hueco exclusivo UNAJ",
             "{:.1f}% de la población censal del hueco vive en barrios "
             "populares".format(resumen["pct_poblacion_censal_en_renabap"]),
             fuente="RENABAP / SISU, Ministerio de Obras Públicas | INDEC "
                    "Censo 2022")
    p = DIR_MAPS / "mapa_renabap.png"
    fig.savefig(p, dpi=200, bbox_inches="tight")
    plt.close(fig)
    log("Mapa: " + str(p))
    return p


def main() -> None:
    renabap = descargar_renabap()
    salida, resumen = cruzar_con_hueco(renabap)
    if len(salida):
        mapa(salida, resumen)

    meta_path = DIR_OUT / "metadatos_analisis.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["renabap"] = resumen
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False),
                         encoding="utf-8")

    print("\n" + "=" * 78)
    print("BARRIOS POPULARES (RENABAP) EN EL HUECO EXCLUSIVO UNAJ")
    print("=" * 78)
    for k, v in resumen.items():
        print("  {:<32} {}".format(k, v))


if __name__ == "__main__":
    main()

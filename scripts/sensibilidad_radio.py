# -*- coding: utf-8 -*-
"""FASE 12 - Analisis de sensibilidad al radio de influencia.

El radio de 5 km es un parametro arbitrario. Este modulo repite todo el
analisis (resta topologica + poblacion censal) para un rango de radios y
muestra como varian el area exclusiva y la poblacion, para que el resultado
no dependa de una eleccion unica.

Uso:
    python scripts/sensibilidad_radio.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from analisis_educativo import (CRS_UTM, UNIV_OBJETIVO, DIR_OUT, DIR_MAPS,
                                DIR_WORK, PALETA, _decorar, log)
from cruce_censo import radios_con_poblacion, poblacion_censal_de

RADIOS_KM = [1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5, 6, 7, 8, 9, 10]
RADIO_BASE = 5.0


def analizar(radios_km=RADIOS_KM) -> pd.DataFrame:
    univ = gpd.read_file(DIR_WORK / "universidades_utm.gpkg",
                         layer="universidades")
    if univ.crs.to_string().upper() != CRS_UTM:
        raise ValueError("universidades no estan en " + CRS_UTM)

    p_unaj = univ.loc[univ.nombre == UNIV_OBJETIVO, "geometry"].iloc[0]
    p_comp = list(univ.loc[univ.nombre != UNIV_OBJETIVO, "geometry"])

    censo = radios_con_poblacion()
    log("Radios censales cargados: {}".format(len(censo)))

    filas, geoms = [], {}
    for r_km in radios_km:
        r = r_km * 1000.0
        b_unaj = p_unaj.buffer(r)
        union_comp = unary_union([p.buffer(r) for p in p_comp])
        hueco = b_unaj.difference(union_comp)

        area_buf = b_unaj.area / 1e6
        area_hueco = hueco.area / 1e6
        pc_hueco = poblacion_censal_de(hueco, censo) if area_hueco > 0 else \
            {"poblacion": 0.0, "n_radios": 0, "area_sin_dato_km2": 0.0,
             "cota_faltantes": 0.0}
        pc_buf = poblacion_censal_de(b_unaj, censo)

        geoms[r_km] = hueco
        filas.append({
            "radio_km": r_km,
            "area_buffer_km2": round(area_buf, 2),
            "area_hueco_km2": round(area_hueco, 2),
            "pct_exclusivo": round(100 * area_hueco / area_buf, 1),
            "poblacion_hueco": round(pc_hueco["poblacion"]),
            "poblacion_buffer": round(pc_buf["poblacion"]),
            "pct_poblacion_exclusiva": round(
                100 * pc_hueco["poblacion"] / pc_buf["poblacion"], 1)
            if pc_buf["poblacion"] else 0.0,
            "n_radios_censales": pc_hueco["n_radios"],
            "densidad_hab_km2": round(pc_hueco["poblacion"] / area_hueco)
            if area_hueco > 0 else 0,
            "area_sin_cobertura_censal_km2": pc_hueco["area_sin_dato_km2"],
        })
        log("r={:>4} km -> hueco {:>6.2f} km2 ({:>5.1f}%) | {:>7,.0f} hab".format(
            r_km, area_hueco, filas[-1]["pct_exclusivo"],
            pc_hueco["poblacion"]))

    df = pd.DataFrame(filas)
    df.to_csv(DIR_OUT / "sensibilidad_radio.csv", index=False)
    log("Guardado: " + str(DIR_OUT / "sensibilidad_radio.csv"))

    gpd.GeoDataFrame(
        {"radio_km": list(geoms), "area_km2": [g.area / 1e6 for g in geoms.values()]},
        geometry=list(geoms.values()), crs=CRS_UTM).to_file(
        DIR_OUT / "huecos_por_radio.gpkg", layer="huecos", driver="GPKG")
    log("Guardado: " + str(DIR_OUT / "huecos_por_radio.gpkg"))
    return df, geoms


def grafico(df: pd.DataFrame) -> Path:
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5.5))

    ax1.plot(df.radio_km, df.area_hueco_km2, "o-", color="#d7191c", lw=2,
             label="Area exclusiva UNAJ")
    ax1.plot(df.radio_km, df.area_buffer_km2, "s--", color="#999999", lw=1.4,
             label="Area total del buffer")
    ax1.axvline(RADIO_BASE, color="#1b7837", ls=":", lw=1.8)
    ax1.annotate("radio del\nanalisis (5 km)", (RADIO_BASE, ax1.get_ylim()[1] * 0.72),
                 xytext=(6, 0), textcoords="offset points", fontsize=8,
                 color="#1b7837")
    ax1.set_xlabel("Radio de influencia (km)")
    ax1.set_ylabel("Superficie (km2)")
    ax1.set_title("Superficie exclusiva vs radio", fontsize=11,
                  fontweight="bold")
    ax1.legend(fontsize=8)
    ax1.grid(alpha=0.25)

    ax2.plot(df.radio_km, df.poblacion_hueco / 1000, "o-", color="#d7191c",
             lw=2, label="Poblacion en area exclusiva")
    ax2.plot(df.radio_km, df.poblacion_buffer / 1000, "s--", color="#999999",
             lw=1.4, label="Poblacion en el buffer completo")
    ax2.axvline(RADIO_BASE, color="#1b7837", ls=":", lw=1.8)
    ax2.set_xlabel("Radio de influencia (km)")
    ax2.set_ylabel("Poblacion (miles de habitantes)")
    ax2.set_title("Poblacion exclusiva vs radio (Censo 2022)", fontsize=11,
                  fontweight="bold")
    ax2.legend(fontsize=8)
    ax2.grid(alpha=0.25)

    ax3 = ax2.twinx()
    ax3.plot(df.radio_km, df.pct_poblacion_exclusiva, "^-", color="#4575b4",
             lw=1.2, ms=4, alpha=0.75)
    ax3.set_ylabel("% de la poblacion del buffer que es exclusiva",
                   color="#4575b4", fontsize=9)
    ax3.tick_params(axis="y", labelcolor="#4575b4")
    ax3.set_ylim(0, 105)

    fig.suptitle("Sensibilidad del hueco educativo UNAJ al radio de influencia",
                 fontsize=13, fontweight="bold")
    fig.tight_layout()
    p = DIR_MAPS / "grafico_sensibilidad_radio.png"
    fig.savefig(p, dpi=200, bbox_inches="tight")
    plt.close(fig)
    log("Grafico: " + str(p))
    return p


def mapa(geoms: dict, df: pd.DataFrame) -> Path:
    univ = gpd.read_file(DIR_WORK / "universidades_utm.gpkg",
                         layer="universidades")
    mostrar = [r for r in (2.5, 5, 7.5, 10) if r in geoms] or \
        sorted(geoms)[::max(1, len(geoms) // 4)]
    colores = ["#fdae61", "#d7191c", "#7b3294", "#2c7bb6"]

    fig, ax = plt.subplots(figsize=(11, 11))
    for col, r_km in zip(colores, sorted(mostrar, reverse=True)):
        g = geoms[r_km]
        if g.is_empty:
            continue
        gpd.GeoSeries([g], crs=CRS_UTM).plot(
            ax=ax, facecolor=col, alpha=0.45, edgecolor=col, linewidth=1.8,
            zorder=2, label="r = {} km  ({:.0f} km2, {:,.0f} hab)".format(
                r_km, g.area / 1e6,
                df.loc[df.radio_km == r_km, "poblacion_hueco"].iloc[0]))
    univ.plot(ax=ax, color="black", markersize=45, zorder=5)
    for _, r in univ.iterrows():
        ax.annotate(r["nombre"], (r.geometry.x, r.geometry.y),
                    xytext=(6, 6), textcoords="offset points", fontsize=9,
                    fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", alpha=0.85,
                              ec=PALETA.get(r["nombre"], "#666666")), zorder=6)
    ax.legend(loc="upper left", fontsize=8, framealpha=0.93,
              title="Area exclusiva de la UNAJ", title_fontsize=9)
    _decorar(ax, "El hueco exclusivo de la UNAJ segun el radio de influencia",
             "A mayor radio, mas superficie propia pero mas solape con las "
             "universidades vecinas",
             fuente="INDEC - Censo 2022 | elaboracion propia")
    p = DIR_MAPS / "mapa_sensibilidad_radio.png"
    fig.savefig(p, dpi=200, bbox_inches="tight")
    plt.close(fig)
    log("Mapa: " + str(p))
    return p


def main() -> None:
    df, geoms = analizar()
    grafico(df)
    mapa(geoms, df)

    base = df[df.radio_km == RADIO_BASE].iloc[0]
    pico_area = df.loc[df.area_hueco_km2.idxmax()]
    pico_pob = df.loc[df.poblacion_hueco.idxmax()]
    # radio a partir del cual deja de ser 100% exclusivo
    no_exc = df[df.pct_exclusivo < 99.9]
    r_solape = float(no_exc.radio_km.iloc[0]) if len(no_exc) else None

    meta_path = DIR_OUT / "metadatos_analisis.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["sensibilidad_radio"] = {
        "radios_evaluados_km": RADIOS_KM,
        "radio_base_km": RADIO_BASE,
        "primer_radio_con_solape_km": r_solape,
        "radio_de_maxima_area_km": float(pico_area.radio_km),
        "max_area_km2": float(pico_area.area_hueco_km2),
        "radio_de_maxima_poblacion_km": float(pico_pob.radio_km),
        "max_poblacion": int(pico_pob.poblacion_hueco),
        "tabla": df.to_dict("records"),
        "nota": ("La poblacion sale del cruce con radios censales 2022 por "
                 "interpolacion areal, el mismo metodo de la fase 11."),
    }
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False),
                         encoding="utf-8")

    print("\n" + "=" * 78)
    print("SENSIBILIDAD AL RADIO DE INFLUENCIA")
    print("=" * 78)
    print(df.to_string(index=False))
    print("-" * 78)
    print("Hasta r = {} km el area de la UNAJ es 100% exclusiva "
          "(no toca ninguna otra).".format(
              r_solape - 0.5 if r_solape else "n/d"))
    print("En el radio base de {} km: {:.2f} km2 y {:,} habitantes "
          "exclusivos.".format(RADIO_BASE, base.area_hueco_km2,
                               int(base.poblacion_hueco)))
    print("Maximo de poblacion exclusiva: {:,} hab en r = {} km.".format(
        int(pico_pob.poblacion_hueco), pico_pob.radio_km))


if __name__ == "__main__":
    main()

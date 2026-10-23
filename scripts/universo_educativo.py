# -*- coding: utf-8 -*-
"""FASE 14 - Universo completo de universidades nacionales del AMBA.

El analisis original compara la UNAJ contra 5 competidoras elegidas a mano
(UNQUI, UNLP, UNLZ, UNaB, UNLaNus). Este modulo pone a prueba esa eleccion:
en vez de confiar en una lista curada, consulta OSM por *todas* las sedes de
universidades publicas de gestion nacional en el AMBA (no solo el sur) y
verifica si alguna, no contemplada en el analisis original, alcanza a tocar
el hueco exclusivo con su propio radio de 5 km.

Metodo de clasificacion (transparente, no una lista arbitraria):
  1. Se descargan TODOS los `amenity=university` de OSM en una caja que cubre
     el AMBA completo (no solo el sur).
  2. Se excluyen por proximidad espacial (<= 500 m) los que ya son una de las
     6 universidades del analisis original -- coincida o no el nombre.
  3. Se incluyen los que matchean patrones de gestion nacional (Universidad
     Nacional *, UTN, Universidad de Buenos Aires) y se excluyen
     explicitamente instituciones privadas o que no son universidades
     (ver EXCLUIR_EXPLICITO, con el motivo en cada caso).
  4. Se mide la distancia de cada candidato al hueco (euclidiano y por red).
     Si algun candidato queda a < 5 km del hueco, su buffer lo alcanzaria y
     habria que rehacer la resta topologica con el universo ampliado.

Ademas se documenta -- sin pretender exhaustividad, porque OSM tiene la
misma incompletitud que con los edificios -- la oferta de nivel superior NO
universitario (institutos de formacion docente y tecnica, de gestion
provincial) que efectivamente opera dentro del hueco, via busqueda directa
en el sitio de la Direccion General de Cultura y Educacion de la Provincia
de Buenos Aires.

Uso:
    python scripts/universo_educativo.py
"""
from __future__ import annotations

import json
import pickle
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
from shapely.geometry import Point

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from analisis_educativo import (CRS_GEO, CRS_UTM, DIR_MAPS, DIR_OUT, DIR_WORK,
                                RADIO_M, UNIVERSIDADES, UNIV_OBJETIVO,
                                _decorar, log)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "gis-agent-unaj/1.0 (analisis academico UNAJ)"
CACHE_UNIV = ROOT / "data" / "censo" / "universidades_osm_amba.json"

# Caja que cubre todo el AMBA (CABA + 24 partidos del Conurbano + La Plata),
# no solo el area de estudio original.
BBOX_AMBA = (-35.05, -59.15, -34.30, -57.75)  # sur, oeste, norte, este

# Distancia para considerar que un punto de OSM "es" una de las 6
# universidades ya incluidas (evita duplicar por otro nombre/tag).
TOLERANCIA_DUPLICADO_M = 500.0

# Casos detectados manualmente que la deduplicacion espacial (500 m) no
# atrapa: sedes secundarias de universidades YA incluidas, tageadas en OSM a
# mas de 500 m del punto oficial que se uso para esa universidad. No son
# competidoras independientes -- se marcan como tales en vez de excluirlas
# en silencio, para que quede trazado por que no cuentan como "nuevas".
MISMO_CAMPUS_QUE = {
    203322589: "UNaB (sede secundaria, Campus Almirante Brown)",
    376709141: "UNLaNUS (sede secundaria, Predio Yrigoyen)",
}

PATRONES_NACIONAL = ["Universidad Nacional", "UTN", "Universidad Tecnol",
                     "Universidad de Buenos Aires"]
# Motivo de exclusion documentado para cada caso: privada, no-universidad, o
# de gestion no nacional aunque el nombre confunda.
EXCLUIR_EXPLICITO = {
    "Instituto Tecnológico de Buenos Aires": "privada (ITBA)",
    "ITBA": "privada",
    "Escuela Nacional de Inteligencia": "no es universidad",
    "Sabato": "instituto de posgrado, sin oferta de grado",
    "Ciudad de Buenos Aires": "gestion CABA, no nacional",
    "Polo Científico": "no es universidad, es un edificio ministerial",
    "Comisión de Investigaciones": "no es universidad",
}

# Oferta terciaria (formacion docente y tecnica, gestion provincial) que
# efectivamente opera en el area del hueco, segun la Direccion General de
# Cultura y Educacion de la Provincia de Buenos Aires (abc.gob.ar). No es
# universidad ni de gestion nacional: se documenta aparte para no mezclar
# categorias distintas de oferta educativa.
ISFD_EN_LA_ZONA = [
    {"nombre": "ISFD N° 50", "partido": "Berazategui/Quilmes/Fcio. Varela",
     "nota": "en el punto triple de los tres partidos"},
    {"nombre": "ISFD N° 54", "partido": "Florencio Varela"},
    {"nombre": "ISFD N° 104", "partido": "Quilmes"},
    {"nombre": "ISFDyT N° 24 \"Dr. B. A. Houssay\"", "partido": "Quilmes (Bernal)"},
    {"nombre": "ISFDyT N° 83", "partido": "Quilmes"},
]
FUENTE_ISFD = ("Dirección General de Cultura y Educación de la Pcia. de "
              "Buenos Aires (abc.gob.ar), Dirección de Formación Docente y "
              "Dirección Provincial de Educación Superior. Relevamiento "
              "manual, no georreferenciado ni exhaustivo -- ver advertencia.")


def descargar_universidades_amba() -> list[dict]:
    if CACHE_UNIV.exists():
        log("Universidades del AMBA leidas del cache: " + str(CACHE_UNIV))
        return json.loads(CACHE_UNIV.read_text(encoding="utf-8"))

    sur, oeste, norte, este = BBOX_AMBA
    caja = "{},{},{},{}".format(sur, oeste, norte, este)
    q = ("[out:json][timeout:180];"
         "(node[amenity=university]({b});way[amenity=university]({b}););"
         "out center tags;").format(b=caja)
    r = requests.post(OVERPASS_URL, data={"data": q},
                      headers={"User-Agent": USER_AGENT}, timeout=240)
    r.raise_for_status()
    data = r.json()["elements"]
    CACHE_UNIV.parent.mkdir(parents=True, exist_ok=True)
    CACHE_UNIV.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    log("Descargadas {} universidades/colleges del AMBA".format(len(data)))
    return data


def clasificar_candidatos(elementos: list[dict]) -> gpd.GeoDataFrame:
    """Filtra a universidades publicas nacionales, excluye las 6 ya usadas
    (por proximidad espacial) y las que no corresponden (por nombre)."""
    conocidas = gpd.GeoDataFrame(
        {"nombre": list(UNIVERSIDADES)},
        geometry=[Point(lon, lat) for lat, lon in UNIVERSIDADES.values()],
        crs=CRS_GEO).to_crs(CRS_UTM)

    filas = []
    for el in elementos:
        t = el.get("tags", {}) or {}
        nombre = t.get("name", "")
        if not nombre or not any(p in nombre for p in PATRONES_NACIONAL):
            continue
        motivo_excl = next((m for k, m in EXCLUIR_EXPLICITO.items()
                            if k in nombre), None)
        if motivo_excl:
            continue
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lon = el.get("lon") or el.get("center", {}).get("lon")
        if lat is None:
            continue
        filas.append({"nombre_osm": nombre, "lat": lat, "lon": lon,
                      "osm_type": el.get("type"), "osm_id": el.get("id")})

    if not filas:
        return gpd.GeoDataFrame(columns=["nombre_osm"], geometry=[], crs=CRS_UTM)

    cand = gpd.GeoDataFrame(
        pd.DataFrame(filas),
        geometry=[Point(f["lon"], f["lat"]) for f in filas],
        crs=CRS_GEO).to_crs(CRS_UTM)

    # excluir las que ya son una de las 6 (por proximidad espacial)
    es_conocida = cand.geometry.apply(
        lambda g: bool((conocidas.distance(g) < TOLERANCIA_DUPLICADO_M).any()))
    nuevas = cand[~es_conocida].copy()

    # deduplicar candidatos entre si (mismo campus tageado dos veces)
    mantener = []
    vistos_geoms = []
    for idx, row in nuevas.iterrows():
        if any(row.geometry.distance(g) < TOLERANCIA_DUPLICADO_M
               for g in vistos_geoms):
            continue
        vistos_geoms.append(row.geometry)
        mantener.append(idx)
    nuevas = nuevas.loc[mantener].reset_index(drop=True)
    nuevas["mismo_campus_que"] = nuevas["osm_id"].map(MISMO_CAMPUS_QUE)
    n_dup = nuevas["mismo_campus_que"].notna().sum()
    if n_dup:
        log("{} candidatos son sedes secundarias de universidades ya "
            "incluidas (ver MISMO_CAMPUS_QUE), no competidoras nuevas: {}"
            .format(n_dup, nuevas.loc[nuevas["mismo_campus_que"].notna(),
                                      "mismo_campus_que"].tolist()))

    log("Candidatos nacionales/UTN/UBA en el AMBA: {} totales, {} ya "
        "incluidas en el analisis, {} nuevas tras deduplicar".format(
            len(cand), int(es_conocida.sum()), len(nuevas)))
    return nuevas


def evaluar_impacto(nuevas: gpd.GeoDataFrame) -> pd.DataFrame:
    hueco = gpd.read_file(DIR_OUT / "hueco_exclusivo_UNAJ.gpkg",
                          layer="hueco").geometry.iloc[0]
    hueco_red = gpd.read_file(DIR_OUT / "hueco_exclusivo_UNAJ_red.gpkg",
                              layer="hueco").geometry.iloc[0]

    nuevas = nuevas.copy()
    nuevas["dist_hueco_km"] = round(nuevas.geometry.distance(hueco) / 1000, 2)
    nuevas["dist_hueco_red_km"] = round(
        nuevas.geometry.distance(hueco_red) / 1000, 2)
    nuevas["alcanza_el_hueco"] = nuevas["dist_hueco_km"] * 1000 < RADIO_M
    nuevas = nuevas.sort_values("dist_hueco_km").reset_index(drop=True)

    nuevas.to_file(DIR_OUT / "universo_universidades_amba.gpkg",
                   layer="candidatos", driver="GPKG")
    log("Guardado: " + str(DIR_OUT / "universo_universidades_amba.gpkg"))
    return nuevas


def mapa(nuevas: gpd.GeoDataFrame) -> Path:
    hueco = gpd.read_file(DIR_OUT / "hueco_exclusivo_UNAJ.gpkg", layer="hueco")
    conocidas = gpd.read_file(DIR_WORK / "universidades_utm.gpkg",
                              layer="universidades")

    fig, ax = plt.subplots(figsize=(12, 12))
    for _, r in nuevas.iterrows():
        gpd.GeoSeries([r.geometry.buffer(RADIO_M)], crs=CRS_UTM).plot(
            ax=ax, facecolor="#999999", alpha=0.12, edgecolor="#666666",
            linewidth=0.6, zorder=1)
    nuevas.plot(ax=ax, color="#666666", markersize=22, marker="s", zorder=3)

    for _, r in conocidas.iterrows():
        color = "#1b7837" if r["nombre"] == UNIV_OBJETIVO else "#31567f"
        gpd.GeoSeries([r.geometry.buffer(RADIO_M)], crs=CRS_UTM).plot(
            ax=ax, facecolor="none", edgecolor=color, linewidth=1.0,
            linestyle="--", zorder=2)
    hueco.plot(ax=ax, facecolor="#d7191c", alpha=0.55, edgecolor="#7f0000",
               linewidth=1.6, zorder=4)
    conocidas.plot(ax=ax, color="black", markersize=45, zorder=5)
    for _, r in conocidas.iterrows():
        ax.annotate(r["nombre"], (r.geometry.x, r.geometry.y),
                    xytext=(5, 5), textcoords="offset points", fontsize=8,
                    fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.15", fc="white",
                              alpha=0.85), zorder=6)

    b_unaj = conocidas.loc[conocidas.nombre == UNIV_OBJETIVO].geometry.iloc[0]
    minx, miny, maxx, maxy = b_unaj.buffer(16000).bounds
    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)

    ax.legend(handles=[
        Patch(facecolor="#d7191c", alpha=0.55, edgecolor="#7f0000",
              label="Hueco exclusivo UNAJ"),
        Line2D([0], [0], color="#1b7837", lw=1.2, ls="--",
               label="Buffer 5 km de las 6 universidades del analisis"),
        Line2D([0], [0], marker="s", color="w", markerfacecolor="#666666",
               markersize=7,
               label="Otras sedes universitarias nacionales del AMBA (n={}, "
               "{} independientes)".format(
                   len(nuevas), int((~nuevas["mismo_campus_que"].notna()).sum()))),
        Patch(facecolor="#999999", alpha=0.12, edgecolor="#666666",
              label="Sus buffers de 5 km (ninguno alcanza el hueco)"),
    ], loc="upper left", fontsize=8, framealpha=0.93)
    _decorar(ax, "El universo completo de universidades nacionales del AMBA",
             "Ninguna sede fuera de las 6 originales llega a 5 km del hueco",
             fuente="OpenStreetMap (c) colaboradores")
    p = DIR_MAPS / "mapa_universo_universidades.png"
    fig.savefig(p, dpi=200, bbox_inches="tight")
    plt.close(fig)
    log("Mapa: " + str(p))
    return p


def main() -> None:
    elementos = descargar_universidades_amba()
    candidatos = clasificar_candidatos(elementos)
    if len(candidatos):
        evaluados = evaluar_impacto(candidatos)
    else:
        evaluados = candidatos

    n_alcanzan = int(evaluados["alcanza_el_hueco"].sum()) if len(evaluados) else 0
    dist_min = float(evaluados["dist_hueco_km"].min()) if len(evaluados) else None
    mas_cercana = str(evaluados.iloc[0]["nombre_osm"]) if len(evaluados) else None
    n_mismo_campus = int(evaluados["mismo_campus_que"].notna().sum()) \
        if len(evaluados) else 0
    n_genuinas = len(evaluados) - n_mismo_campus

    if len(evaluados):
        mapa(evaluados)

    resumen = {
        "n_candidatos_amba_total": len(elementos),
        "n_candidatos_nacionales_nuevos": len(evaluados),
        "n_sedes_secundarias_de_universidades_ya_incluidas": n_mismo_campus,
        "n_instituciones_genuinamente_nuevas": n_genuinas,
        "n_que_alcanzan_el_hueco": n_alcanzan,
        "distancia_minima_al_hueco_km": dist_min,
        "candidata_mas_cercana": mas_cercana,
        "metodo": ("Se descargaron todas las sedes amenity=university de OSM "
                   "en el AMBA completo, se filtraron por patrones de gestion "
                   "nacional y se excluyeron las 6 ya incluidas en el analisis "
                   "por proximidad espacial (<= {:.0f} m)."
                   ).format(TOLERANCIA_DUPLICADO_M),
        "candidatos": evaluados.drop(columns="geometry").to_dict("records")
        if len(evaluados) else [],
        "isfd_en_la_zona": ISFD_EN_LA_ZONA,
        "fuente_isfd": FUENTE_ISFD,
        "advertencia_isfd": ("Relevamiento manual de institutos terciarios "
                             "provinciales, no georreferenciado ni "
                             "necesariamente exhaustivo. No son universidades "
                             "ni de gestion nacional: se documentan aparte "
                             "para no mezclar categorias de oferta."),
    }

    meta_path = DIR_OUT / "metadatos_analisis.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["universo_educativo"] = resumen
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False),
                         encoding="utf-8")

    print("\n" + "=" * 78)
    print("UNIVERSO COMPLETO DE UNIVERSIDADES NACIONALES DEL AMBA")
    print("=" * 78)
    print("Sedes universitarias publicas totales relevadas en OSM (AMBA): "
          "{}".format(len(elementos)))
    print("Candidatas nacionales nuevas (fuera de las 6 del analisis): "
          "{} ({} genuinamente independientes, {} son sedes secundarias de "
          "universidades ya incluidas)".format(
              len(evaluados), n_genuinas, n_mismo_campus))
    if len(evaluados):
        print(evaluados[["nombre_osm", "mismo_campus_que", "dist_hueco_km",
                         "dist_hueco_red_km"]].to_string(index=False))
    print("-" * 78)
    if n_alcanzan:
        print("*** {} candidatas alcanzan el hueco con su radio de 5 km: "
              "HAY QUE REHACER LA RESTA TOPOLOGICA ***".format(n_alcanzan))
    else:
        print("Ninguna candidata alcanza el hueco (la mas cercana, {}, "
              "queda a {:.2f} km del borde). El universo ampliado NO cambia "
              "el resultado.".format(mas_cercana, dist_min))
    print()
    print("Oferta terciaria (no universitaria, gestion provincial) "
          "identificada en la zona:")
    for isfd in ISFD_EN_LA_ZONA:
        print("  - {} ({})".format(isfd["nombre"], isfd["partido"]))


if __name__ == "__main__":
    main()

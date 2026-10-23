# -*- coding: utf-8 -*-
"""FASE 13 - Areas de servicio sobre la red vial (isocronas de distancia).

El buffer euclidiano de 5 km supone que se puede ir en linea recta en
cualquier direccion. La realidad del sur del Conurbano son barreras: el
ferrocarril Roca, la Autopista Buenos Aires-La Plata, arroyos y trazados
irregulares. Este modulo reemplaza el circulo por el area realmente
alcanzable recorriendo 5 km de calle, y rehace la resta topologica.

Justificacion del area de descarga: si un punto es alcanzable con un
recorrido de <= R metros desde el origen, todos los puntos de ese recorrido
estan a <= R metros euclidianos del origen. Por lo tanto la red contenida en
el buffer euclidiano de radio R es suficiente para calcular el area de
servicio de R metros; no hace falta descargar mas.

Uso:
    python scripts/isocronas.py
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
import networkx as nx
import numpy as np
import pandas as pd
import requests
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from scipy.spatial import cKDTree
from shapely.geometry import LineString, MultiLineString, box
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from analisis_educativo import (CRS_GEO, CRS_UTM, DIR_MAPS, DIR_OUT, DIR_WORK,
                                PALETA, RADIO_M, UNIV_OBJETIVO, _decorar, log)
from cruce_censo import poblacion_censal_de, radios_con_poblacion

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "gis-agent-unaj/1.0 (analisis academico UNAJ)"
CACHE_RED = DIR_WORK / "red_vial_osm.pkl"

# Tipos de via excluidos: no son transitables a pie ni sirven de acceso local.
HIGHWAY_EXCLUIDOS = {
    "motorway", "motorway_link", "trunk", "trunk_link", "construction",
    "proposed", "raceway", "bus_guideway", "escape", "planned",
}
# Distancia de acceso desde el eje de calle hasta la parcela. Media manzana
# tipica del Conurbano (manzanas de ~100 x 100 m).
ACCESO_M = 150.0


def _descargar_tile(bbox, intento_max=3) -> dict:
    sur, oeste, norte, este = bbox
    caja = "{},{},{},{}".format(sur, oeste, norte, este)
    q = ("[out:json][timeout:180];"
         "way[highway]({});out body;>;out skel qt;").format(caja)
    for intento in range(1, intento_max + 1):
        try:
            r = requests.post(OVERPASS_URL, data={"data": q},
                              headers={"User-Agent": USER_AGENT}, timeout=300)
            if r.status_code != 200:
                raise RuntimeError("HTTP " + str(r.status_code))
            return r.json()
        except Exception as exc:  # noqa: BLE001
            log("Tile {} intento {} fallo: {}".format(
                caja[:30], intento, str(exc)[:80]), "WARNING")
            time.sleep(8 * intento)
    raise RuntimeError("Tile agotado: " + caja)


def descargar_red(n_tiles: int = 6):
    """Descarga la red vial dentro del area de estudio. Devuelve nodos y vias.

    El resultado se cachea en disco: la descarga completa tarda ~8 minutos y
    no cambia entre corridas.
    """
    if CACHE_RED.exists():
        with open(CACHE_RED, "rb") as fh:
            nodos, vias = pickle.load(fh)
        log("Red vial leida del cache: {} vias, {} nodos".format(
            len(vias), len(nodos)))
        return nodos, vias

    area = gpd.read_file(DIR_WORK / "area_descarga.gpkg", layer="area")
    poligono = area.union_all()
    minx, miny, maxx, maxy = poligono.bounds
    xs = np.linspace(minx, maxx, n_tiles + 1)
    ys = np.linspace(miny, maxy, n_tiles + 1)

    nodos: dict[int, tuple[float, float]] = {}
    vias: dict[int, dict] = {}
    for i in range(n_tiles):
        for j in range(n_tiles):
            if not box(xs[i], ys[j], xs[i + 1], ys[j + 1]).intersects(poligono):
                continue
            t0 = time.time()
            data = _descargar_tile((ys[j], xs[i], ys[j + 1], xs[i + 1]))
            n_v = 0
            for el in data.get("elements", []):
                if el.get("type") == "node":
                    nodos[el["id"]] = (el["lon"], el["lat"])
                elif el.get("type") == "way" and el["id"] not in vias:
                    tags = el.get("tags", {}) or {}
                    if tags.get("highway") in HIGHWAY_EXCLUIDOS:
                        continue
                    vias[el["id"]] = {"nodes": el.get("nodes", []),
                                      "highway": tags.get("highway")}
                    n_v += 1
            log("Tile [{},{}]: +{} vias (total {} vias / {} nodos) {:.0f}s".format(
                i, j, n_v, len(vias), len(nodos), time.time() - t0))
    log("Red descargada: {} vias, {} nodos".format(len(vias), len(nodos)))
    CACHE_RED.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_RED, "wb") as fh:
        pickle.dump((nodos, vias), fh, protocol=pickle.HIGHEST_PROTOCOL)
    log("Cache guardado: " + str(CACHE_RED))
    return nodos, vias


def construir_grafo(nodos: dict, vias: dict) -> tuple[nx.Graph, dict, np.ndarray, list]:
    """Grafo no dirigido con pesos en metros (coordenadas proyectadas a UTM)."""
    ids = list(nodos)
    lon = np.array([nodos[i][0] for i in ids])
    lat = np.array([nodos[i][1] for i in ids])
    pts = gpd.GeoSeries(gpd.points_from_xy(lon, lat), crs=CRS_GEO).to_crs(CRS_UTM)
    xy = np.column_stack([pts.x.values, pts.y.values])
    pos = {nid: (xy[k, 0], xy[k, 1]) for k, nid in enumerate(ids)}

    G = nx.Graph()
    for w in vias.values():
        ns = [n for n in w["nodes"] if n in pos]
        for a, b in zip(ns[:-1], ns[1:]):
            if a == b:
                continue
            (xa, ya), (xb, yb) = pos[a], pos[b]
            d = float(np.hypot(xb - xa, yb - ya))
            if G.has_edge(a, b):
                if d < G[a][b]["length"]:
                    G[a][b]["length"] = d
            else:
                G.add_edge(a, b, length=d)
    log("Grafo: {:,} nodos, {:,} aristas".format(
        G.number_of_nodes(), G.number_of_edges()))
    return G, pos, xy, ids


def area_de_servicio(G, pos, arbol, ids, origen_xy, radio_m: float):
    """Poligono alcanzable recorriendo <= radio_m sobre la red desde el origen."""
    _, k = arbol.query(origen_xy)
    nodo = ids[int(k)]
    dist = nx.single_source_dijkstra_path_length(G, nodo, cutoff=radio_m,
                                                 weight="length")
    alcanzables = set(dist)
    lineas = [LineString([pos[a], pos[b]])
              for a, b in G.edges(alcanzables)
              if a in alcanzables and b in alcanzables]
    if not lineas:
        raise RuntimeError("Sin aristas alcanzables desde el origen")
    # Buffer directo sobre la MultiLineString: GEOS disuelve los solapes
    # internamente, mucho mas rapido que unary_union() sobre 15k lineas.
    poly = MultiLineString(lineas).buffer(ACCESO_M)
    if not poly.is_valid:
        poly = poly.buffer(0)
    return poly, len(alcanzables), float(np.hypot(*(np.array(pos[nodo]) - origen_xy)))


def main() -> None:
    nodos, vias = descargar_red()
    G, pos, xy, ids = construir_grafo(nodos, vias)
    arbol = cKDTree(xy)

    univ = gpd.read_file(DIR_WORK / "universidades_utm.gpkg",
                         layer="universidades")
    censo = radios_con_poblacion()

    areas, filas = {}, []
    for _, r in univ.iterrows():
        origen = np.array([r.geometry.x, r.geometry.y])
        poly, n_nodos, snap = area_de_servicio(G, pos, arbol, ids, origen,
                                               RADIO_M)
        areas[r["nombre"]] = poly
        buf = r.geometry.buffer(RADIO_M)
        filas.append({
            "universidad": r["nombre"],
            "area_red_km2": round(poly.area / 1e6, 2),
            "area_euclidiana_km2": round(buf.area / 1e6, 2),
            "cobertura_pct": round(100 * poly.area / buf.area, 1),
            "nodos_alcanzables": n_nodos,
            "snap_m": round(snap, 1),
        })
        log("{}: area de servicio {:.2f} km2 ({:.1f}% del circulo), "
            "{} nodos, snap {:.0f} m".format(
                r["nombre"], poly.area / 1e6,
                100 * poly.area / buf.area, n_nodos, snap))

    df = pd.DataFrame(filas)
    gpd.GeoDataFrame({"nombre": list(areas),
                      "area_km2": [g.area / 1e6 for g in areas.values()]},
                     geometry=list(areas.values()), crs=CRS_UTM).to_file(
        DIR_OUT / "areas_servicio_red.gpkg", layer="areas", driver="GPKG")
    log("Guardado: " + str(DIR_OUT / "areas_servicio_red.gpkg"))

    # --- resta topologica sobre la red ------------------------------------
    sa_unaj = areas[UNIV_OBJETIVO]
    union_comp = unary_union([g for k, g in areas.items() if k != UNIV_OBJETIVO])
    hueco_red = sa_unaj.difference(union_comp)

    pc = poblacion_censal_de(hueco_red, censo)
    area_red = hueco_red.area / 1e6

    gpd.GeoDataFrame({"nombre": ["hueco_exclusivo_UNAJ_red"],
                      "area_km2": [area_red],
                      "poblacion_censo_2022": [round(pc["poblacion"])]},
                     geometry=[hueco_red], crs=CRS_UTM).to_file(
        DIR_OUT / "hueco_exclusivo_UNAJ_red.gpkg", layer="hueco",
        driver="GPKG")
    log("Guardado: " + str(DIR_OUT / "hueco_exclusivo_UNAJ_red.gpkg"))

    meta_path = DIR_OUT / "metadatos_analisis.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    area_euc = meta["hueco_area_km2"]
    pob_euc = meta["censo_2022"]["poblacion_censo_2022_total_estimada"]
    resumen = {
        "radio_m": RADIO_M,
        "acceso_desde_eje_m": ACCESO_M,
        "highway_excluidos": sorted(HIGHWAY_EXCLUIDOS),
        "n_nodos_grafo": G.number_of_nodes(),
        "n_aristas_grafo": G.number_of_edges(),
        "areas_de_servicio": df.to_dict("records"),
        "hueco_red_area_km2": round(area_red, 2),
        "hueco_red_poblacion": round(pc["poblacion"]),
        "hueco_red_n_radios": pc["n_radios"],
        "hueco_red_densidad_hab_km2": round(pc["poblacion"] / area_red),
        "hueco_euclidiano_area_km2": area_euc,
        "hueco_euclidiano_poblacion": pob_euc,
        "ratio_area_red_vs_euclidiano": round(area_red / area_euc, 3),
        "ratio_poblacion_red_vs_euclidiano": round(pc["poblacion"] / pob_euc, 3),
        "metodo": ("Area de servicio = union de las aristas alcanzables con "
                   "recorrido <= 5.000 m sobre la red vial de OSM, con un "
                   "buffer de acceso de {} m desde el eje de calle. Grafo no "
                   "dirigido (no se aplican sentidos unicos: el analisis "
                   "representa acceso peatonal y de transporte publico)."
                   ).format(int(ACCESO_M)),
    }
    meta["isocronas_red"] = resumen
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False),
                         encoding="utf-8")

    mapa(areas, hueco_red, univ, resumen)

    print("\n" + "=" * 78)
    print("AREAS DE SERVICIO SOBRE RED VIAL (5 km de recorrido)")
    print("=" * 78)
    print(df.to_string(index=False))
    print("-" * 78)
    print("Hueco exclusivo euclidiano : {:>8.2f} km2 | {:>9,} hab".format(
        area_euc, pob_euc))
    print("Hueco exclusivo por red    : {:>8.2f} km2 | {:>9,} hab".format(
        area_red, round(pc["poblacion"])))
    print("Ratio red/euclidiano       : area {:.1%} | poblacion {:.1%}".format(
        resumen["ratio_area_red_vs_euclidiano"],
        resumen["ratio_poblacion_red_vs_euclidiano"]))


def mapa(areas: dict, hueco_red, univ, resumen: dict) -> Path:
    buffers = gpd.read_file(DIR_WORK / "buffers" / "todos_los_buffers.gpkg",
                            layer="buffers")
    hueco_euc = gpd.read_file(DIR_OUT / "hueco_exclusivo_UNAJ.gpkg",
                              layer="hueco")

    fig, ax = plt.subplots(figsize=(11.5, 11.5))
    b_unaj = buffers.loc[buffers.nombre == UNIV_OBJETIVO].geometry.iloc[0]
    hueco_euc.plot(ax=ax, facecolor="none", edgecolor="#7f0000", linewidth=1.6,
                   linestyle="--", zorder=3)
    for nombre, g in areas.items():
        if nombre == UNIV_OBJETIVO:
            continue
        gpd.GeoSeries([g], crs=CRS_UTM).plot(
            ax=ax, facecolor="#8fa8c8", alpha=0.35, edgecolor="#31567f",
            linewidth=0.8, zorder=2)
    gpd.GeoSeries([hueco_red], crs=CRS_UTM).plot(
        ax=ax, facecolor="#d7191c", alpha=0.60, edgecolor="#7f0000",
        linewidth=1.4, zorder=4)
    univ.plot(ax=ax, color="black", markersize=42, zorder=5)
    for _, r in univ.iterrows():
        ax.annotate(r["nombre"], (r.geometry.x, r.geometry.y),
                    xytext=(6, 6), textcoords="offset points", fontsize=9,
                    fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", alpha=0.85,
                              ec=PALETA.get(r["nombre"], "#666")), zorder=6)
    minx, miny, maxx, maxy = b_unaj.buffer(3000).bounds
    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)
    ax.legend(handles=[
        Patch(facecolor="#d7191c", alpha=0.60, edgecolor="#7f0000",
              label="Hueco exclusivo por RED ({:.1f} km2, {:,} hab)".format(
                  resumen["hueco_red_area_km2"],
                  resumen["hueco_red_poblacion"])),
        Line2D([0], [0], color="#7f0000", lw=1.6, ls="--",
               label="Hueco exclusivo EUCLIDIANO ({:.1f} km2)".format(
                   resumen["hueco_euclidiano_area_km2"])),
        Patch(facecolor="#8fa8c8", alpha=0.35, edgecolor="#31567f",
              label="Areas de servicio de las otras universidades"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="black",
               markersize=7, label="Universidad"),
    ], loc="upper left", fontsize=8, framealpha=0.93)
    _decorar(ax, "Area realmente alcanzable: 5 km por la red vial",
             "Comparacion con el buffer euclidiano de 5 km",
             fuente="OpenStreetMap (c) colaboradores | INDEC Censo 2022")
    p = DIR_MAPS / "mapa_isocronas_red.png"
    fig.savefig(p, dpi=200, bbox_inches="tight")
    plt.close(fig)
    log("Mapa: " + str(p))
    return p


if __name__ == "__main__":
    main()

# -*- coding: utf-8 -*-
"""
Proyecto: "El Territorio de la UNAJ"
Analisis geoespacial del area de cobertura exclusiva de la Universidad Nacional
Arturo Jauretche (UNAJ) frente a las 5 universidades nacionales mas cercanas
del sur del AMBA.

Script modular. Cada fase se ejecuta desde el coordinador:
    python scripts/analisis_educativo.py fase1
    python scripts/analisis_educativo.py fase2
    ...
o bien `python scripts/analisis_educativo.py main` para correr todo.
"""
from __future__ import annotations

import json
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.lines import Line2D
from matplotlib.patches import Patch
from shapely.geometry import Point, box
from shapely.ops import unary_union

warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)

# ----------------------------------------------------------------------------
# CONSTANTES DEL PROYECTO
# ----------------------------------------------------------------------------
ROOT = Path(__file__).resolve().parent.parent

DIR_INPUT = ROOT / "data" / "input"        # INMUTABLE despues de FASE 1
DIR_WORK = ROOT / "work"
DIR_BUFFERS = DIR_WORK / "buffers"
DIR_OUT = ROOT / "outputs"
DIR_MAPS = DIR_OUT / "maps"
DIR_REPORTS = ROOT / "reports"
DIR_LOGS = ROOT / "logs"

CRS_GEO = "EPSG:4326"      # WGS84 geografico (OSM)
CRS_UTM = "EPSG:32721"     # UTM 21S -> CRS proyectado para el AMBA
RADIO_M = 5000             # radio de cobertura en metros

# Coordenadas WGS84 (lat, lon)
UNIVERSIDADES = {
    "UNAJ":    (-34.774735904720146, -58.26757897123207),
    "UNQUI":   (-34.70643956377978,  -58.27840363776498),
    "UNLP":    (-34.90938705840227,  -57.92847003137114),
    "UNLZ":    (-34.77460201316454,  -58.45266596247028),
    "UNaB":    (-34.796025303594845, -58.38931368617012),
    "UNLANUS": (-34.73543259582245,  -58.39080175327837),
}
UNIV_OBJETIVO = "UNAJ"
COMPETIDORAS = [k for k in UNIVERSIDADES if k != UNIV_OBJETIVO]

NOMBRES_LARGOS = {
    "UNAJ": "Univ. Nacional Arturo Jauretche (Florencio Varela)",
    "UNQUI": "Univ. Nacional de Quilmes",
    "UNLP": "Univ. Nacional de La Plata",
    "UNLZ": "Univ. Nacional de Lomas de Zamora",
    "UNaB": "Univ. Nacional Guillermo Brown",
    "UNLANUS": "Univ. Nacional de Lanus",
}

FACTOR_POBLACION = 3.0     # habitantes por edificio residencial (ver informe)

TAGS_RESIDENCIALES = {
    "house", "residential", "apartments", "detached", "semidetached_house",
    "terrace", "bungalow", "dormitory", "hut", "cabin", "static_caravan",
    "farm", "houseboat",
}
TAGS_NO_RESIDENCIALES = {
    "commercial", "industrial", "retail", "warehouse", "school", "university",
    "college", "kindergarten", "church", "chapel", "cathedral", "mosque",
    "temple", "hospital", "clinic", "garage", "garages", "carport", "shed",
    "roof", "construction", "ruins", "greenhouse", "farm_auxiliary", "barn",
    "silo", "stable", "service", "kiosk", "public", "civic", "government",
    "office", "hangar", "train_station", "transportation", "sports_centre",
    "sports_hall", "stadium", "pavilion", "toilets", "parking", "bunker",
    "water_tower", "storage_tank", "fire_station", "military", "hotel",
    "supermarket", "container",
}

METADATA_PATH = DIR_OUT / "metadatos_analisis.json"

# Mirrors de Overpass: el endpoint principal sufre cortes frecuentes, se rotan
# El primero debe ser overpass-api.de: la clave de cache de osmnx incluye el
# endpoint, y las celdas ya descargadas quedaron cacheadas contra ese host.
# Solo el endpoint principal: los mirrors publicos (kumi, private.coffee,
# osm.jp) devolvieron 500/502 de forma sistematica al probarlos. Ademas la
# clave de cache de osmnx incluye el endpoint, asi que cambiarlo invalida
# todo lo ya descargado.
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "gis-agent-unaj/1.0 (analisis academico UNAJ)"
REINTENTOS_POR_CELDA = 3

PALETA = {
    "UNAJ": "#1b7837", "UNQUI": "#4575b4", "UNLP": "#984ea3",
    "UNLZ": "#ff7f00", "UNaB": "#a6761d", "UNLANUS": "#e7298a",
}


# ----------------------------------------------------------------------------
# UTILIDADES
# ----------------------------------------------------------------------------
def log(msg: str, nivel: str = "INFO") -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    linea = "[" + ts + "] [" + nivel + "] " + str(msg)
    print(linea, flush=True)
    DIR_LOGS.mkdir(parents=True, exist_ok=True)
    with open(DIR_LOGS / "ejecucion.log", "a", encoding="utf-8") as fh:
        fh.write(linea + "\n")


def asegurar_directorios() -> None:
    for d in (DIR_INPUT, DIR_WORK, DIR_BUFFERS, DIR_OUT, DIR_MAPS,
              DIR_REPORTS, DIR_LOGS):
        d.mkdir(parents=True, exist_ok=True)


def leer_metadatos() -> dict:
    if METADATA_PATH.exists():
        return json.loads(METADATA_PATH.read_text(encoding="utf-8"))
    return {}


def guardar_metadatos(nuevos: dict) -> dict:
    meta = leer_metadatos()
    meta.update(nuevos)
    DIR_OUT.mkdir(parents=True, exist_ok=True)
    METADATA_PATH.write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    return meta


def verificar_crs_proyectado(gdf: gpd.GeoDataFrame, etiqueta: str) -> None:
    """Regla constitucional: nunca medir areas/distancias en grados."""
    if gdf.crs is None:
        raise ValueError(etiqueta + ": CRS indefinido")
    if not gdf.crs.is_projected:
        raise ValueError(etiqueta + ": CRS " + gdf.crs.to_string() +
                         " NO es proyectado")
    if gdf.crs.to_string().upper() != CRS_UTM:
        raise ValueError(etiqueta + ": se esperaba " + CRS_UTM +
                         ", hay " + gdf.crs.to_string())


def sanitizar_para_gpkg(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """OSM trae columnas con listas/dicts que GPKG no soporta."""
    out = gdf.copy()
    for col in out.columns:
        if col == out.geometry.name:
            continue
        if out[col].dtype == object:
            muestra = out[col].dropna()
            if len(muestra) and isinstance(muestra.iloc[0],
                                           (list, dict, set, tuple)):
                out[col] = out[col].astype(str)
    return out


# ----------------------------------------------------------------------------
# FUNCIONES MODULARES PRINCIPALES
# ----------------------------------------------------------------------------
def gdf_universidades() -> gpd.GeoDataFrame:
    """GeoDataFrame de las 6 universidades en WGS84."""
    filas = [{"nombre": k, "nombre_largo": NOMBRES_LARGOS[k],
              "lat": v[0], "lon": v[1],
              "rol": "objetivo" if k == UNIV_OBJETIVO else "competidora"}
             for k, v in UNIVERSIDADES.items()]
    df = pd.DataFrame(filas)
    return gpd.GeoDataFrame(
        df, geometry=[Point(xy) for xy in zip(df.lon, df.lat)], crs=CRS_GEO)


def reproyectar_a_utm(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Reproyecta cualquier capa a EPSG:32721 (UTM 21S)."""
    if gdf.crs is None:
        raise ValueError("La capa no tiene CRS definido; no se puede reproyectar")
    out = gdf.to_crs(CRS_UTM)
    verificar_crs_proyectado(out, "capa reproyectada")
    return out


def crear_buffer(punto, radio: float = RADIO_M):
    """Buffer de `radio` metros. El punto DEBE estar en CRS proyectado."""
    return punto.buffer(radio)


def area_descarga() -> gpd.GeoDataFrame:
    """Union de los 6 buffers de 5 km, devuelta en WGS84 para consultar OSM."""
    univ_utm = reproyectar_a_utm(gdf_universidades())
    union = unary_union([crear_buffer(g) for g in univ_utm.geometry])
    gdf = gpd.GeoDataFrame({"tipo": ["area_descarga"]},
                           geometry=[union], crs=CRS_UTM)
    log("Area de descarga (union de 6 buffers): {:.2f} km2".format(union.area / 1e6))
    return gdf.to_crs(CRS_GEO)


def _consulta_overpass(bbox, modo: str = "geom", timeout_s: int = 180) -> list:
    """Cliente Overpass propio (requests). osmnx fallaba de forma sistematica
    contra este endpoint desde esta red; una consulta POST directa con
    User-Agent explicito si responde de forma estable."""
    import requests
    sur, oeste, norte, este = bbox
    caja = "{},{},{},{}".format(sur, oeste, norte, este)
    q = ("[out:json][timeout:{t}];"
         "(way[building]({b});relation[building]({b}););"
         "out {m};").format(t=timeout_s, b=caja, m=modo)
    r = requests.post(OVERPASS_URL, data={"data": q},
                      headers={"User-Agent": USER_AGENT},
                      timeout=timeout_s + 60)
    if r.status_code != 200:
        raise RuntimeError("HTTP " + str(r.status_code) + " " + r.text[:80])
    return r.json().get("elements", [])


def _elemento_a_geometria(el):
    """Convierte un elemento Overpass (out geom) en una geometria shapely."""
    from shapely.geometry import LineString, Polygon
    if el.get("type") == "way":
        coords = [(n["lon"], n["lat"]) for n in el.get("geometry", []) or []]
        if len(coords) < 3:
            return None
        if coords[0] != coords[-1]:
            coords.append(coords[0])
        try:
            g = Polygon(coords)
            return g if g.is_valid else g.buffer(0)
        except Exception:  # noqa: BLE001
            return None
    if el.get("type") == "relation":
        anillos = []
        for m in el.get("members", []) or []:
            if m.get("role") not in ("outer", "", None):
                continue
            coords = [(n["lon"], n["lat"]) for n in m.get("geometry", []) or []]
            if len(coords) < 3:
                continue
            if coords[0] != coords[-1]:
                coords.append(coords[0])
            try:
                anillos.append(Polygon(coords).buffer(0))
            except Exception:  # noqa: BLE001
                continue
        if not anillos:
            return None
        g = unary_union(anillos)
        return g if not g.is_empty else None
    return None


def _descargar_celda(bbox, prof: int, maxprof: int, ruta: str,
                     acumulado: dict, fallidos: list) -> None:
    """Descarga una celda bbox; ante fallo la subdivide en 4 cuadrantes."""
    for intento in range(1, REINTENTOS_POR_CELDA + 1):
        try:
            t0 = time.time()
            els = _consulta_overpass(bbox)
            n_nuevos = 0
            for el in els:
                clave = (el.get("type"), el.get("id"))
                if clave in acumulado:
                    continue
                g = _elemento_a_geometria(el)
                if g is None or g.is_empty:
                    continue
                tags = el.get("tags", {}) or {}
                acumulado[clave] = {
                    "element_type": el.get("type"), "osmid": el.get("id"),
                    "building": tags.get("building"),
                    "name": tags.get("name"),
                    "building_levels": tags.get("building:levels"),
                    "addr_street": tags.get("addr:street"),
                    "amenity": tags.get("amenity"),
                    "geometry": g,
                }
                n_nuevos += 1
            log("Celda {}: {} elementos ({} nuevos, total {}) en {:.0f}s".format(
                ruta, len(els), n_nuevos, len(acumulado), time.time() - t0))
            return
        except Exception as exc:  # noqa: BLE001
            log("Celda {} intento {} fallo: {}".format(
                ruta, intento, str(exc)[:100]), "WARNING")
            time.sleep(8 * intento)

    if prof >= maxprof:
        log("Celda {}: agotados reintentos y profundidad".format(ruta), "ERROR")
        fallidos.append(ruta)
        return
    log("Celda {}: se subdivide en 4 (profundidad {})".format(ruta, prof + 1))
    sur, oeste, norte, este = bbox
    my, mx = (sur + norte) / 2, (oeste + este) / 2
    for n, sub in enumerate([(sur, oeste, my, mx), (sur, mx, my, este),
                             (my, oeste, norte, mx), (my, mx, norte, este)],
                            start=1):
        _descargar_celda(sub, prof + 1, maxprof, ruta + "." + str(n),
                         acumulado, fallidos)


def descargar_osm(area_gdf: gpd.GeoDataFrame, destino: Path,
                  n_tiles: int = 8, maxprof: int = 3) -> gpd.GeoDataFrame:
    """FASE 1. Descarga todos los edificios de OSM dentro del area de estudio.

    El bbox del area se recorre con una grilla de n_tiles x n_tiles; se omiten
    las celdas que no intersecan el poligono. Cada celda que Overpass no puede
    resolver se subdivide recursivamente en cuadrantes.
    """
    poligono = area_gdf.union_all()
    minx, miny, maxx, maxy = poligono.bounds
    xs = np.linspace(minx, maxx, n_tiles + 1)
    ys = np.linspace(miny, maxy, n_tiles + 1)

    acumulado: dict = {}
    fallidos: list = []
    k = 0
    for i in range(n_tiles):
        for j in range(n_tiles):
            k += 1
            celda = box(xs[i], ys[j], xs[i + 1], ys[j + 1])
            if not celda.intersects(poligono):
                continue
            # bbox de Overpass: (sur, oeste, norte, este)
            _descargar_celda((ys[j], xs[i], ys[j + 1], xs[i + 1]),
                             0, maxprof, str(k), acumulado, fallidos)

    if not acumulado:
        raise RuntimeError("OSM no devolvio edificios en ninguna celda")

    registros = list(acumulado.values())
    geoms = [r.pop("geometry") for r in registros]
    edificios = gpd.GeoDataFrame(pd.DataFrame(registros), geometry=geoms,
                                 crs=CRS_GEO)
    # recortar al area de estudio real (la grilla es rectangular)
    antes = len(edificios)
    edificios = edificios[edificios.geometry.representative_point().within(
        poligono)].reset_index(drop=True)
    log("Recorte al area de estudio: {} -> {} edificios".format(
        antes, len(edificios)))

    destino.parent.mkdir(parents=True, exist_ok=True)
    sanitizar_para_gpkg(edificios).to_file(destino, layer="edificios",
                                           driver="GPKG")
    log("Guardado crudo: {} ({} edificios)".format(destino, len(edificios)))

    guardar_metadatos({
        "osm_fecha_descarga": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "osm_total_edificios_crudos": int(len(edificios)),
        "osm_celdas_fallidas": fallidos,
        "osm_crs_origen": CRS_GEO,
        "osm_endpoint": OVERPASS_URL,
        "fuente_edificios": "OpenStreetMap via Overpass API (cliente propio)",
    })
    if fallidos:
        log("Celdas fallidas: {}".format(fallidos), "WARNING")
    return edificios


def edificios_sinteticos(area_gdf: gpd.GeoDataFrame,
                         paso_m: int = 120) -> gpd.GeoDataFrame:
    """Plan B (solo si OSM falla): grilla sintetica de edificios."""
    area_utm = area_gdf.to_crs(CRS_UTM)
    poly = area_utm.union_all()
    minx, miny, maxx, maxy = poly.bounds
    pts = [Point(x, y)
           for x in np.arange(minx, maxx, paso_m)
           for y in np.arange(miny, maxy, paso_m)]
    g = gpd.GeoDataFrame({"building": ["house"] * len(pts)},
                         geometry=pts, crs=CRS_UTM)
    g = g[g.within(poly)].reset_index(drop=True)
    log("CAPA SINTETICA generada: {} edificios ficticios".format(len(g)), "WARNING")
    return g.to_crs(CRS_GEO)


def fase2_preparacion():
    """FASE 2. Reproyeccion de edificios y universidades a UTM 21S."""
    raw = gpd.read_file(DIR_INPUT / "edificios_osm_raw.gpkg", layer="edificios")
    log("Leidos {} edificios crudos (CRS {})".format(len(raw), raw.crs.to_string()))
    edif_utm = reproyectar_a_utm(raw)
    sanitizar_para_gpkg(edif_utm).to_file(
        DIR_WORK / "edificios_utm.gpkg", layer="edificios", driver="GPKG")
    log("Guardado: " + str(DIR_WORK / "edificios_utm.gpkg"))

    univ_utm = reproyectar_a_utm(gdf_universidades())
    univ_utm.to_file(DIR_WORK / "universidades_utm.gpkg",
                     layer="universidades", driver="GPKG")
    log("Guardado: " + str(DIR_WORK / "universidades_utm.gpkg") + " (6 puntos)")
    guardar_metadatos({"crs_trabajo": CRS_UTM,
                       "edificios_reproyectados": int(len(edif_utm))})
    return edif_utm, univ_utm


def fase3_buffers() -> gpd.GeoDataFrame:
    """FASE 3. Buffers de 5000 m para las 6 universidades."""
    univ_utm = gpd.read_file(DIR_WORK / "universidades_utm.gpkg",
                             layer="universidades")
    verificar_crs_proyectado(univ_utm, "universidades")
    DIR_BUFFERS.mkdir(parents=True, exist_ok=True)

    filas = []
    for _, r in univ_utm.iterrows():
        geom = crear_buffer(r.geometry, RADIO_M)
        uno = gpd.GeoDataFrame(
            {"nombre": [r["nombre"]], "nombre_largo": [r["nombre_largo"]],
             "rol": [r["rol"]], "radio_m": [RADIO_M],
             "area_km2": [geom.area / 1e6]},
            geometry=[geom], crs=CRS_UTM)
        uno.to_file(DIR_BUFFERS / ("buffer_" + r["nombre"] + ".gpkg"),
                    layer="buffer", driver="GPKG")
        filas.append(uno)
        log("Buffer {}: {:.2f} km2".format(r["nombre"], geom.area / 1e6))

    todos = gpd.GeoDataFrame(pd.concat(filas, ignore_index=True), crs=CRS_UTM)
    todos.to_file(DIR_BUFFERS / "todos_los_buffers.gpkg",
                  layer="buffers", driver="GPKG")
    log("Guardado: " + str(DIR_BUFFERS / "todos_los_buffers.gpkg"))
    return todos


def calcular_hueco(buffer_unaj, union_competidoras):
    """FASE 4. Resta topologica: buffer UNAJ - union de competidoras."""
    return buffer_unaj.difference(union_competidoras)


def fase4_hueco() -> gpd.GeoDataFrame:
    todos = gpd.read_file(DIR_BUFFERS / "todos_los_buffers.gpkg", layer="buffers")
    verificar_crs_proyectado(todos, "buffers")

    b_unaj = todos.loc[todos.nombre == UNIV_OBJETIVO, "geometry"].iloc[0]
    comp = todos.loc[todos.nombre != UNIV_OBJETIVO, "geometry"]
    union_comp = unary_union(list(comp))
    log("Union de {} buffers competidores: {:.2f} km2".format(
        len(comp), union_comp.area / 1e6))

    hueco = calcular_hueco(b_unaj, union_comp)
    area_km2 = hueco.area / 1e6
    pct = 100 * area_km2 / (b_unaj.area / 1e6)
    n_partes = len(hueco.geoms) if hueco.geom_type == "MultiPolygon" else 1

    gdf = gpd.GeoDataFrame(
        {"nombre": ["hueco_exclusivo_UNAJ"], "area_km2": [area_km2],
         "pct_del_buffer_unaj": [pct], "radio_m": [RADIO_M],
         "n_partes": [n_partes]},
        geometry=[hueco], crs=CRS_UTM)
    DIR_OUT.mkdir(parents=True, exist_ok=True)
    gdf.to_file(DIR_OUT / "hueco_exclusivo_UNAJ.gpkg", layer="hueco",
                driver="GPKG")

    gpd.GeoDataFrame({"nombre": ["union_competidoras"]},
                     geometry=[union_comp], crs=CRS_UTM).to_file(
        DIR_WORK / "union_competidoras.gpkg", layer="union", driver="GPKG")

    log("HUECO EXCLUSIVO UNAJ: {:.2f} km2 ({:.1f}% del buffer UNAJ)".format(
        area_km2, pct))
    guardar_metadatos({
        "hueco_area_km2": round(area_km2, 4),
        "hueco_pct_buffer_unaj": round(pct, 2),
        "hueco_n_partes": int(n_partes),
        "buffer_unaj_area_km2": round(b_unaj.area / 1e6, 4),
        "union_competidoras_area_km2": round(union_comp.area / 1e6, 4),
        "hueco_geom_type": hueco.geom_type,
    })
    return gdf


def clasificar_edificios(edif: gpd.GeoDataFrame):
    """Separa edificios residenciales segun el tag OSM `building`."""
    if "building" in edif.columns:
        tags = edif["building"].astype(str).str.lower()
    else:
        tags = pd.Series(["yes"] * len(edif), index=edif.index)
    es_res = tags.isin(TAGS_RESIDENCIALES)
    es_nores = tags.isin(TAGS_NO_RESIDENCIALES)
    n_tot, n_res = len(edif), int(es_res.sum())
    share = n_res / n_tot if n_tot else 0.0

    info = {"n_total": n_tot, "n_residencial_estricto": n_res,
            "share_residencial": round(share, 4),
            "n_no_residencial": int(es_nores.sum())}

    if share >= 0.30:
        sel, criterio, aviso = edif[es_res], "tag_residencial_estricto", None
    else:
        sel = edif[~es_nores]
        criterio = "todos_menos_no_residenciales"
        aviso = ("Solo el {:.1f}% de los edificios del hueco tiene un tag "
                 "residencial explicito (predomina building=yes). Se usan todos "
                 "los edificios excepto los tageados explicitamente como no "
                 "residenciales.").format(share * 100)
        log(aviso, "WARNING")
    info["criterio_seleccion"] = criterio
    info["advertencia"] = aviso
    info["n_seleccionados"] = len(sel)
    return sel, info


def estimar_poblacion(edificios: gpd.GeoDataFrame,
                      factor: float = FACTOR_POBLACION) -> float:
    """Poblacion estimada = n edificios residenciales * factor hab/edificio."""
    return float(len(edificios)) * factor


def fase5_cruce() -> gpd.GeoDataFrame:
    """FASE 5. Spatial join edificios x hueco + estimacion poblacional."""
    hueco = gpd.read_file(DIR_OUT / "hueco_exclusivo_UNAJ.gpkg", layer="hueco")
    edif = gpd.read_file(DIR_WORK / "edificios_utm.gpkg", layer="edificios")
    verificar_crs_proyectado(hueco, "hueco")
    verificar_crs_proyectado(edif, "edificios")

    # un edificio pertenece al hueco si su centroide cae dentro
    puntos = edif.copy()
    puntos["geometry"] = puntos.geometry.centroid
    dentro = gpd.sjoin(puntos, hueco[["geometry"]], predicate="within",
                       how="inner").drop(columns=["index_right"])
    log("Edificios dentro del hueco: {} de {} descargados".format(
        len(dentro), len(edif)))

    sel, info = clasificar_edificios(dentro)
    poblacion = estimar_poblacion(sel, FACTOR_POBLACION)
    area_km2 = float(hueco.area.iloc[0] / 1e6)

    sel = sel.copy()
    sel["hab_estimados"] = FACTOR_POBLACION
    sanitizar_para_gpkg(sel).to_file(DIR_OUT / "edificios_en_hueco.gpkg",
                                     layer="edificios", driver="GPKG")
    log("POBLACION ESTIMADA: {:,.0f} hab ({} edificios x {})".format(
        poblacion, len(sel), FACTOR_POBLACION))

    guardar_metadatos({
        "edificios_en_hueco_total": int(len(dentro)),
        "edificios_en_hueco_seleccionados": int(len(sel)),
        "criterio_residencial": info["criterio_seleccion"],
        "share_residencial_estricto": info["share_residencial"],
        "advertencia_residencial": info["advertencia"],
        "factor_hab_por_edificio": FACTOR_POBLACION,
        "poblacion_estimada": round(poblacion, 0),
        "densidad_edificios_por_km2": round(len(dentro) / area_km2, 1),
        "densidad_poblacion_hab_km2": round(poblacion / area_km2, 1),
    })
    return sel


def fase6_distancias() -> pd.DataFrame:
    """FASE 6. Distancia del centroide del hueco a cada universidad."""
    hueco = gpd.read_file(DIR_OUT / "hueco_exclusivo_UNAJ.gpkg", layer="hueco")
    univ = gpd.read_file(DIR_WORK / "universidades_utm.gpkg",
                         layer="universidades")
    verificar_crs_proyectado(hueco, "hueco")
    verificar_crs_proyectado(univ, "universidades")

    centroide = hueco.geometry.iloc[0].representative_point()
    filas = []
    for _, r in univ.iterrows():
        filas.append({
            "universidad": r["nombre"],
            "rol": r["rol"],
            "dist_centroide_km": round(centroide.distance(r.geometry) / 1000, 2),
            "dist_min_al_hueco_km": round(
                hueco.geometry.iloc[0].distance(r.geometry) / 1000, 2),
        })
    df = pd.DataFrame(filas).sort_values("dist_centroide_km").reset_index(drop=True)
    df.to_csv(DIR_OUT / "distancias_universidades.csv", index=False)
    log("Distancias:\n" + df.to_string(index=False))

    gpd.GeoDataFrame({"nombre": ["centroide_hueco"]}, geometry=[centroide],
                     crs=CRS_UTM).to_file(DIR_WORK / "centroide_hueco.gpkg",
                                          layer="centroide", driver="GPKG")
    comp = df[df.rol == "competidora"]
    guardar_metadatos({
        "distancias_km": df.to_dict("records"),
        "dist_min_competidora_km": float(comp.dist_centroide_km.min()),
        "competidora_mas_cercana": str(
            comp.loc[comp.dist_centroide_km.idxmin(), "universidad"]),
        "dist_unaj_km": float(df.loc[df.rol == "objetivo",
                                     "dist_centroide_km"].iloc[0]),
    })
    return df


# ----------------------------------------------------------------------------
# FASE 7 - CARTOGRAFIA
# ----------------------------------------------------------------------------
def _barra_escala(ax, largo_m=5000, etiqueta="5 km"):
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    bx = x0 + 0.06 * (x1 - x0)
    by = y0 + 0.06 * (y1 - y0)
    alto = 0.008 * (y1 - y0)
    ax.add_patch(plt.Rectangle((bx, by), largo_m / 2, alto, fc="black",
                               ec="black", zorder=12))
    ax.add_patch(plt.Rectangle((bx + largo_m / 2, by), largo_m / 2, alto,
                               fc="white", ec="black", zorder=12))
    ax.text(bx, by + alto * 2.0, "0", ha="center", fontsize=7, zorder=12)
    ax.text(bx + largo_m, by + alto * 2.0, etiqueta, ha="center", fontsize=7,
            zorder=12)


def _norte(ax):
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    x = x0 + 0.94 * (x1 - x0)
    y = y0 + 0.85 * (y1 - y0)
    d = 0.055 * (y1 - y0)
    ax.annotate("", xy=(x, y + d), xytext=(x, y),
                arrowprops=dict(facecolor="black", width=2.5, headwidth=9),
                zorder=12)
    ax.text(x, y + d * 1.15, "N", ha="center", fontsize=11, fontweight="bold",
            zorder=12)


def _decorar(ax, titulo, subtitulo="",
             fuente="OpenStreetMap (c) colaboradores"):
    ax.set_title(titulo, fontsize=13, fontweight="bold", pad=16)
    if subtitulo:
        ax.text(0.5, 1.008, subtitulo, transform=ax.transAxes, ha="center",
                fontsize=9, color="#444444")
    ax.set_xticks([])
    ax.set_yticks([])
    for s in ax.spines.values():
        s.set_edgecolor("#888888")
    ax.text(0.995, -0.025,
            "CRS: " + CRS_UTM + " (UTM 21S)  |  Fuente: " + fuente +
            "  |  " + datetime.now().strftime("%Y-%m-%d"),
            transform=ax.transAxes, ha="right", fontsize=7, color="#555555")
    _barra_escala(ax)
    _norte(ax)


def generar_mapas():
    """FASE 7. Los tres mapas del proyecto."""
    DIR_MAPS.mkdir(parents=True, exist_ok=True)
    buffers = gpd.read_file(DIR_BUFFERS / "todos_los_buffers.gpkg",
                            layer="buffers")
    univ = gpd.read_file(DIR_WORK / "universidades_utm.gpkg",
                         layer="universidades")
    hueco = gpd.read_file(DIR_OUT / "hueco_exclusivo_UNAJ.gpkg", layer="hueco")
    edif_hueco = gpd.read_file(DIR_OUT / "edificios_en_hueco.gpkg",
                               layer="edificios")
    meta = leer_metadatos()
    salidas = []

    # ---- MAPA 1: buffers comparativos ----
    fig, ax = plt.subplots(figsize=(11, 11))
    for _, r in buffers.iterrows():
        es_unaj = r["nombre"] == UNIV_OBJETIVO
        gpd.GeoSeries([r.geometry], crs=CRS_UTM).plot(
            ax=ax, facecolor=PALETA[r["nombre"]],
            alpha=0.45 if es_unaj else 0.20,
            edgecolor=PALETA[r["nombre"]], linewidth=2.6 if es_unaj else 1.2,
            zorder=3 if es_unaj else 2)
    univ.plot(ax=ax, color="black", markersize=45, zorder=5)
    for _, r in univ.iterrows():
        ax.annotate(r["nombre"], (r.geometry.x, r.geometry.y),
                    xytext=(6, 6), textcoords="offset points",
                    fontsize=10, fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.25", fc="white",
                              ec=PALETA[r["nombre"]], alpha=0.85), zorder=6)
    handles = [Patch(facecolor=PALETA[n],
                     alpha=0.45 if n == UNIV_OBJETIVO else 0.2,
                     edgecolor=PALETA[n],
                     label=n + " - " + NOMBRES_LARGOS[n][:40])
               for n in buffers.nombre]
    ax.legend(handles=handles, loc="upper left", fontsize=8,
              bbox_to_anchor=(0.0, -0.02), ncol=2,
              title="Areas de influencia (r = 5 km)", title_fontsize=9,
              framealpha=0.95)
    _decorar(ax, "Areas de influencia de 5 km - Universidades nacionales "
                 "del sur del AMBA", "UNAJ resaltada en verde")
    p = DIR_MAPS / "mapa_buffers_comparativos.png"
    fig.savefig(p, dpi=200, bbox_inches="tight")
    plt.close(fig)
    salidas.append(p)
    log("Mapa 1: " + str(p))

    # ---- MAPA 2: hueco exclusivo ----
    fig, ax = plt.subplots(figsize=(11, 11))
    edif = gpd.read_file(DIR_WORK / "edificios_utm.gpkg", layer="edificios")
    b_unaj = buffers.loc[buffers.nombre == UNIV_OBJETIVO].geometry.iloc[0]
    ctx = edif[edif.geometry.centroid.within(b_unaj.buffer(3000))]
    ctx.plot(ax=ax, color="#c9c9c9", linewidth=0.15, edgecolor="#bfbfbf",
             zorder=1)
    for _, r in buffers.iterrows():
        if r["nombre"] == UNIV_OBJETIVO:
            continue
        gpd.GeoSeries([r.geometry], crs=CRS_UTM).plot(
            ax=ax, facecolor="#8fa8c8", alpha=0.30, edgecolor="#31567f",
            linewidth=1.0, zorder=2)
    gpd.GeoSeries([b_unaj], crs=CRS_UTM).plot(
        ax=ax, facecolor="none", edgecolor="#1b7837", linewidth=2.6,
        linestyle="--", zorder=3)
    hueco.plot(ax=ax, facecolor="#d7191c", alpha=0.32, edgecolor="#7f0000",
               linewidth=2.2, zorder=4)
    # los edificios se repiten encima del relleno para que se lea el tejido
    ctx.plot(ax=ax, color="#5a5a5a", linewidth=0.15, edgecolor="#4a4a4a",
             zorder=4.5)
    univ.plot(ax=ax, color="black", markersize=42, zorder=5)
    for _, r in univ.iterrows():
        ax.annotate(r["nombre"], (r.geometry.x, r.geometry.y),
                    xytext=(6, 6), textcoords="offset points", fontsize=9,
                    fontweight="bold",
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", alpha=0.8),
                    zorder=6)
    minx, miny, maxx, maxy = b_unaj.buffer(3500).bounds
    ax.set_xlim(minx, maxx)
    ax.set_ylim(miny, maxy)
    ax.legend(handles=[
        Patch(facecolor="#d7191c", alpha=0.45, edgecolor="#7f0000",
              label="Hueco exclusivo UNAJ ({:.1f} km2)".format(
                  meta.get("hueco_area_km2", 0))),
        Line2D([0], [0], color="#1b7837", lw=2.6, ls="--",
               label="Buffer UNAJ (5 km)"),
        Patch(facecolor="#8fa8c8", alpha=0.30, edgecolor="#31567f",
              label="Buffers de otras universidades"),
        Patch(facecolor="#c9c9c9", edgecolor="#bfbfbf",
              label="Edificios OSM (contexto)"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="black",
               markersize=7, label="Universidad"),
    ], loc="upper left", fontsize=8, framealpha=0.92)
    _decorar(ax, "Hueco educativo exclusivo de la UNAJ",
             "Superficie cubierta solo por la UNAJ dentro de su radio de 5 km")
    p = DIR_MAPS / "mapa_hueco_exclusivo.png"
    fig.savefig(p, dpi=200, bbox_inches="tight")
    plt.close(fig)
    salidas.append(p)
    log("Mapa 2: " + str(p))

    # ---- MAPA 3: edificios / poblacion ----
    fig, ax = plt.subplots(figsize=(11, 11))
    hueco.plot(ax=ax, facecolor="#fff2f0", edgecolor="#7f0000", linewidth=2.0,
               zorder=1)
    pts = edif_hueco.copy()
    pts["geometry"] = pts.geometry.centroid
    paso = 250
    minx, miny, maxx, maxy = hueco.total_bounds
    gx = ((pts.geometry.x - minx) // paso).astype(int)
    gy = ((pts.geometry.y - miny) // paso).astype(int)
    dens = pd.DataFrame({"gx": gx, "gy": gy}).groupby(["gx", "gy"]).size()
    celdas = gpd.GeoDataFrame(
        {"n_edificios": dens.values,
         "poblacion": dens.values * FACTOR_POBLACION},
        geometry=[box(minx + i * paso, miny + j * paso,
                      minx + (i + 1) * paso, miny + (j + 1) * paso)
                  for i, j in dens.index],
        crs=CRS_UTM)
    celdas = celdas[celdas.intersects(hueco.geometry.iloc[0])]
    celdas.to_file(DIR_OUT / "grilla_densidad_hueco.gpkg", layer="grilla",
                   driver="GPKG")
    celdas.plot(ax=ax, column="poblacion", cmap="YlOrRd", scheme="quantiles",
                k=5, legend=True, edgecolor="none", alpha=0.9, zorder=2,
                legend_kwds={"title": "Poblacion estimada\npor celda de "
                                      "250 x 250 m",
                             "loc": "lower right", "fontsize": 8,
                             "title_fontsize": 8, "framealpha": 0.92})
    hueco.boundary.plot(ax=ax, color="#7f0000", linewidth=2.0, zorder=3)
    u = univ[univ.nombre == UNIV_OBJETIVO]
    u.plot(ax=ax, color="#1b7837", markersize=130, marker="*", zorder=5)
    ax.annotate("UNAJ", (u.geometry.iloc[0].x, u.geometry.iloc[0].y),
                xytext=(8, 8), textcoords="offset points", fontsize=10,
                fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.25", fc="white", alpha=0.85),
                zorder=6)
    _decorar(ax, "Distribucion de poblacion estimada en el hueco exclusivo UNAJ",
             "{:,} edificios residenciales x {} hab = {:,.0f} habitantes".format(
                 meta.get("edificios_en_hueco_seleccionados", 0),
                 FACTOR_POBLACION, meta.get("poblacion_estimada", 0)))
    p = DIR_MAPS / "mapa_edificios_poblacion.png"
    fig.savefig(p, dpi=200, bbox_inches="tight")
    plt.close(fig)
    salidas.append(p)
    log("Mapa 3: " + str(p))
    return salidas


# ----------------------------------------------------------------------------
# ORQUESTACION
# ----------------------------------------------------------------------------
def fase1_descarga(n_tiles: int = 6) -> gpd.GeoDataFrame:
    asegurar_directorios()
    destino = DIR_INPUT / "edificios_osm_raw.gpkg"
    if destino.exists():
        log(str(destino) + " ya existe; se respeta como original inmutable")
        return gpd.read_file(destino, layer="edificios")
    area = area_descarga()
    area.to_file(DIR_WORK / "area_descarga.gpkg", layer="area", driver="GPKG")
    try:
        return descargar_osm(area, destino, n_tiles=n_tiles)
    except Exception as exc:  # noqa: BLE001
        log("Fallo la descarga OSM ({}); se usa capa SINTETICA".format(exc),
            "ERROR")
        g = edificios_sinteticos(area)
        g.to_file(destino, layer="edificios", driver="GPKG")
        guardar_metadatos({"fuente_edificios": "SINTETICA (fallback)",
                           "osm_total_edificios_crudos": int(len(g))})
        return g


def main() -> None:
    asegurar_directorios()
    log("=== INICIO ANALISIS EL TERRITORIO DE LA UNAJ ===")
    fase1_descarga()
    fase2_preparacion()
    fase3_buffers()
    fase4_hueco()
    fase5_cruce()
    fase6_distancias()
    generar_mapas()
    log("=== FIN ===")


FASES = {
    "fase1": fase1_descarga, "fase2": fase2_preparacion,
    "fase3": fase3_buffers, "fase4": fase4_hueco,
    "fase5": fase5_cruce, "fase6": fase6_distancias,
    "fase7": generar_mapas, "main": main,
}

if __name__ == "__main__":
    cual = sys.argv[1] if len(sys.argv) > 1 else "main"
    if cual not in FASES:
        print("Fase desconocida: " + cual + ". Opciones: " + str(list(FASES)))
        sys.exit(2)
    FASES[cual]()

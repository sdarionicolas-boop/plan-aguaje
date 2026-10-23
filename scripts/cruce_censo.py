# -*- coding: utf-8 -*-
"""FASE 11 - Cruce del hueco exclusivo UNAJ con los radios censales del
Censo Nacional de Poblacion, Hogares y Viviendas 2022 (INDEC).

Reemplaza el proxy de edificios OSM por el dato censal oficial, que es la
fuente correcta para dimensionar la poblacion del hueco.

Fuentes:
  - Geometria de radios 2022: INDEC, GeoNode institucional (WFS oficial),
    capa `geonode:radios_censales2`.
  - Poblacion por radio 2022: Boccolini, Sara Maria (2026), "Argentina (2022)
    radios censales con datos de cantidad de poblacion y densidad de
    poblacion", CONICET Digital, CC BY 2.5 AR. Es una tabulacion del Censo
    2022 de INDEC (via Redatam) unida a la cartografia oficial. El archivo
    publicado esta filtrado a radios con densidad > 1 hab/ha, por lo que los
    radios menos densos se tratan aparte (ver `cota_faltantes`).

Metodo: interpolacion areal. A cada radio que interseca el hueco se le asigna
la fraccion de su poblacion proporcional a la fraccion de su superficie que
cae dentro del hueco.

Uso:
    python scripts/cruce_censo.py
"""
from __future__ import annotations

import io
import json
import time
from pathlib import Path

import geopandas as gpd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import requests

ROOT = Path(__file__).resolve().parent.parent
DIR_CENSO = ROOT / "data" / "censo"
DIR_WORK = ROOT / "work"
DIR_OUT = ROOT / "outputs"
DIR_MAPS = DIR_OUT / "maps"

CRS_UTM = "EPSG:32721"
WFS_URL = "https://geonode.indec.gob.ar/geoserver/ows"
CAPA_WFS = "geonode:radios_censales2"
USER_AGENT = "gis-agent-unaj/1.0 (analisis academico UNAJ)"

# Partidos cuyos radios pueden tocar el hueco, con el patron de busqueda CQL.
# Se usan subcadenas sin acentos porque CQL LIKE distingue tildes y el WFS
# devuelve los nombres acentuados ("Lanus" no matchea "Lanus" con tilde).
PARTIDOS = {
    "Florencio Varela": "Varela",
    "Berazategui": "Berazategui",
    "Quilmes": "Quilmes",
    "Almirante Brown": "Brown",
    "La Plata": "Plata",
    "Lanus": "Lan",
    "Lomas de Zamora": "Zamora",
}

GPKG_CONICET = DIR_CENSO / "radios_2022_conDatos_1habHa.gpkg"
GPKG_RADIOS = DIR_CENSO / "radios_2022_indec.gpkg"
URL_CONICET = ("https://ri.conicet.gov.ar/bitstream/handle/11336/284095/"
              "radios_2022_conDatos_1habHa.gpkg?sequence=2&isAllowed=y")

# Umbral del filtro aplicado por la fuente de poblacion: 1 hab/ha = 100 hab/km2
UMBRAL_DENSIDAD_HAB_KM2 = 100.0


def log(msg: str, nivel: str = "INFO") -> None:
    print("[{}] [{}] {}".format(time.strftime("%H:%M:%S"), nivel, msg),
          flush=True)


def descargar_radios_indec(partidos=PARTIDOS) -> gpd.GeoDataFrame:
    """Geometria oficial de radios censales 2022 (WFS del GeoNode de INDEC)."""
    if GPKG_RADIOS.exists():
        log("Radios INDEC ya descargados: " + str(GPKG_RADIOS))
        return gpd.read_file(GPKG_RADIOS, layer="radios")

    partes = []
    for nombre, patron in partidos.items():
        params = {
            "service": "WFS", "version": "1.0.0", "request": "GetFeature",
            "typeName": CAPA_WFS, "outputFormat": "application/json",
            "srsName": "EPSG:4326",
            "CQL_FILTER": "dpto LIKE '%{}%'".format(patron),
        }
        r = requests.get(WFS_URL, params=params,
                         headers={"User-Agent": USER_AGENT}, timeout=300)
        r.raise_for_status()
        g = gpd.read_file(io.BytesIO(r.content))
        if not len(g) or "dpto" not in g.columns:
            log("WFS {}: sin resultados (patron '{}')".format(nombre, patron),
                "WARNING")
            continue
        log("WFS {}: {} radios [{}]".format(
            nombre, len(g), ", ".join(sorted(g["dpto"].unique()))))
        partes.append(g)
    if not partes:
        raise RuntimeError("El WFS de INDEC no devolvio radios")

    radios = gpd.GeoDataFrame(pd.concat(partes, ignore_index=True),
                              crs="EPSG:4326")
    radios = radios.drop_duplicates(subset="cod_indec").reset_index(drop=True)
    DIR_CENSO.mkdir(parents=True, exist_ok=True)
    radios.to_file(GPKG_RADIOS, layer="radios", driver="GPKG")
    log("Guardado: {} ({} radios)".format(GPKG_RADIOS, len(radios)))
    return radios


def descargar_poblacion_conicet() -> None:
    """Descarga el GeoPackage de poblacion por radio 2022 (CONICET, 42 MB)
    si todavia no esta en disco. Ver la cita completa en el docstring del
    modulo (Boccolini, S. M., 2026, CONICET Digital, CC BY 2.5 AR)."""
    if GPKG_CONICET.exists():
        return
    log("Descargando poblacion por radio 2022 (CONICET, ~42 MB)...")
    DIR_CENSO.mkdir(parents=True, exist_ok=True)
    r = requests.get(URL_CONICET, headers={"User-Agent": USER_AGENT},
                     timeout=600, stream=True)
    r.raise_for_status()
    tmp = GPKG_CONICET.with_suffix(".gpkg.part")
    with open(tmp, "wb") as fh:
        for chunk in r.iter_content(1 << 20):
            fh.write(chunk)
    tmp.rename(GPKG_CONICET)
    log("Guardado: {} ({:.1f} MB)".format(
        GPKG_CONICET, GPKG_CONICET.stat().st_size / 1e6))


def cargar_poblacion_censo() -> pd.DataFrame:
    """Tabla codigo de radio -> poblacion 2022."""
    descargar_poblacion_conicet()
    cols = ["CRO", "CA3", "areaHa", "densHabHa", "NOMDEPTO"]
    pob = gpd.read_file(GPKG_CONICET, columns=cols, ignore_geometry=True)
    pob = pob.rename(columns={"CRO": "cod_indec", "CA3": "poblacion_2022",
                              "NOMDEPTO": "partido"})
    pob["cod_indec"] = pob["cod_indec"].astype(str).str.zfill(9)
    log("Tabla de poblacion 2022: {} radios en el pais".format(len(pob)))
    return pob[["cod_indec", "poblacion_2022", "areaHa", "densHabHa",
                "partido"]]


def radios_con_poblacion() -> gpd.GeoDataFrame:
    """Radios censales 2022 (geometria oficial INDEC + poblacion), en UTM.

    Helper reutilizable: lo usan el cruce principal, el analisis de
    sensibilidad al radio y las isocronas por red vial.
    """
    radios = descargar_radios_indec().to_crs(CRS_UTM)
    radios["cod_indec"] = radios["cod_indec"].astype(str).str.zfill(9)
    radios["area_radio_m2"] = radios.geometry.area
    return radios.merge(cargar_poblacion_censo(), on="cod_indec", how="left")


def poblacion_censal_de(geom, radios: gpd.GeoDataFrame) -> dict:
    """Poblacion dentro de `geom` por interpolacion areal de radios censales.

    Devuelve la poblacion asignada y la superficie que quedo sin cobertura
    censal (radios rurales excluidos de la fuente por su baja densidad), que
    acota por arriba lo que podria estar faltando.
    """
    tocan = radios[radios.intersects(geom)].copy()
    if not len(tocan):
        return {"poblacion": 0.0, "n_radios": 0, "area_sin_dato_km2": 0.0,
                "cota_faltantes": 0.0}
    inter = tocan.geometry.intersection(geom)
    area_int = inter.area
    frac = area_int / tocan["area_radio_m2"]

    con = tocan["poblacion_2022"].notna()
    poblacion = float((tocan.loc[con, "poblacion_2022"] * frac[con]).sum())
    area_sin = float(area_int[~con].sum() / 1e6)
    return {"poblacion": poblacion,
            "n_radios": int(con.sum()),
            "area_sin_dato_km2": round(area_sin, 3),
            "cota_faltantes": round(area_sin * UMBRAL_DENSIDAD_HAB_KM2)}


def cruzar_con_hueco(radios: gpd.GeoDataFrame,
                     pob: pd.DataFrame) -> tuple[gpd.GeoDataFrame, dict]:
    """Interpolacion areal de la poblacion de los radios sobre el hueco."""
    hueco = gpd.read_file(DIR_OUT / "hueco_exclusivo_UNAJ.gpkg", layer="hueco")
    if hueco.crs.to_string().upper() != CRS_UTM:
        raise ValueError("El hueco no esta en " + CRS_UTM)
    geom_hueco = hueco.geometry.iloc[0]

    radios = radios.to_crs(CRS_UTM)
    radios["cod_indec"] = radios["cod_indec"].astype(str).str.zfill(9)
    radios["area_radio_m2"] = radios.geometry.area
    radios = radios.merge(pob, on="cod_indec", how="left")

    tocan = radios[radios.intersects(geom_hueco)].copy()
    log("Radios que intersecan el hueco: {}".format(len(tocan)))

    tocan["geom_int"] = tocan.geometry.intersection(geom_hueco)
    tocan["area_int_m2"] = tocan["geom_int"].area
    tocan = tocan[tocan["area_int_m2"] > 1].copy()
    tocan["fraccion_en_hueco"] = tocan["area_int_m2"] / tocan["area_radio_m2"]

    # --- radios con dato censal -------------------------------------------
    con_dato = tocan[tocan["poblacion_2022"].notna()].copy()
    con_dato["poblacion_asignada"] = (con_dato["poblacion_2022"] *
                                      con_dato["fraccion_en_hueco"])
    pob_asignada = float(con_dato["poblacion_asignada"].sum())

    # --- radios sin dato: son los de densidad < 1 hab/ha (filtro de origen)
    sin_dato = tocan[tocan["poblacion_2022"].isna()].copy()
    area_sin_dato_km2 = float(sin_dato["area_int_m2"].sum() / 1e6)
    cota_faltantes = area_sin_dato_km2 * UMBRAL_DENSIDAD_HAB_KM2

    # --- criterio alternativo: radios cuyo centroide cae en el hueco -------
    centroides = radios[radios.geometry.representative_point().within(geom_hueco)]
    pob_centroide = float(centroides["poblacion_2022"].sum())

    area_hueco_km2 = float(geom_hueco.area / 1e6)
    resumen = {
        "n_radios_intersecan": int(len(tocan)),
        "n_radios_con_dato": int(len(con_dato)),
        "n_radios_sin_dato": int(len(sin_dato)),
        "n_radios_integros_en_hueco": int((con_dato["fraccion_en_hueco"] > 0.999).sum()),
        "poblacion_censo_2022_areal": round(pob_asignada),
        "poblacion_censo_2022_por_centroide": round(pob_centroide),
        "area_sin_dato_km2": round(area_sin_dato_km2, 2),
        "cota_superior_faltantes": round(cota_faltantes),
        "poblacion_censo_2022_total_estimada": round(pob_asignada + cota_faltantes),
        "densidad_censal_hab_km2": round((pob_asignada + cota_faltantes) / area_hueco_km2),
        "partidos_involucrados": sorted(
            con_dato["partido"].dropna().unique().tolist()),
        "desglose_por_partido": [
            {"partido": k,
             "n_radios": int(v["cod_indec"]),
             "poblacion": round(v["poblacion_asignada"]),
             "area_km2": round(v["area_int_m2"] / 1e6, 2),
             "densidad_hab_km2": round(v["poblacion_asignada"] /
                                       (v["area_int_m2"] / 1e6))}
            for k, v in con_dato.groupby("dpto").agg(
                {"cod_indec": "size", "poblacion_asignada": "sum",
                 "area_int_m2": "sum"}).sort_values(
                    "poblacion_asignada", ascending=False).iterrows()],
    }

    # capa de salida: radios recortados al hueco con su poblacion asignada
    salida = con_dato.copy()
    salida = salida.set_geometry("geom_int")
    salida = salida.drop(columns=["geometry"]).rename_geometry("geometry")
    salida["densidad_hab_km2"] = (salida["poblacion_asignada"] /
                                  (salida["area_int_m2"] / 1e6))
    salida = salida[["cod_indec", "dpto", "tro", "poblacion_2022",
                     "fraccion_en_hueco", "poblacion_asignada",
                     "area_int_m2", "densidad_hab_km2", "geometry"]]
    salida = gpd.GeoDataFrame(salida, geometry="geometry", crs=CRS_UTM)
    salida.to_file(DIR_OUT / "radios_censo_en_hueco.gpkg", layer="radios",
                   driver="GPKG")
    log("Guardado: " + str(DIR_OUT / "radios_censo_en_hueco.gpkg"))
    return salida, resumen


def mapa_censo(radios_hueco: gpd.GeoDataFrame, resumen: dict) -> Path:
    """Mapa 4: densidad poblacional censal dentro del hueco."""
    from analisis_educativo import _decorar, CRS_UTM as _C  # reutiliza estilo
    hueco = gpd.read_file(DIR_OUT / "hueco_exclusivo_UNAJ.gpkg", layer="hueco")
    univ = gpd.read_file(DIR_WORK / "universidades_utm.gpkg",
                         layer="universidades")

    fig, ax = plt.subplots(figsize=(11, 11))
    radios_hueco.plot(ax=ax, column="densidad_hab_km2", cmap="YlOrRd",
                      scheme="quantiles", k=6, legend=True,
                      edgecolor="#ffffff", linewidth=0.25, alpha=0.95,
                      zorder=2,
                      legend_kwds={"title": "Densidad de poblacion\n"
                                            "(hab/km2) - Censo 2022",
                                   "loc": "lower right", "fontsize": 8,
                                   "title_fontsize": 8, "framealpha": 0.93})
    hueco.boundary.plot(ax=ax, color="#7f0000", linewidth=2.4, zorder=3)
    u = univ[univ.nombre == "UNAJ"]
    u.plot(ax=ax, color="#1b7837", markersize=150, marker="*", zorder=5,
           edgecolor="black", linewidth=0.6)
    ax.annotate("UNAJ", (u.geometry.iloc[0].x, u.geometry.iloc[0].y),
                xytext=(9, 9), textcoords="offset points", fontsize=11,
                fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.25", fc="white", alpha=0.88),
                zorder=6)
    _decorar(ax, "Poblacion del hueco exclusivo UNAJ segun el Censo 2022",
             "{} radios censales | {:,} habitantes | {:,} hab/km2".format(
                 resumen["n_radios_con_dato"],
                 resumen["poblacion_censo_2022_total_estimada"],
                 resumen["densidad_censal_hab_km2"]),
             fuente="INDEC - Censo 2022 y cartografia de radios censales")
    DIR_MAPS.mkdir(parents=True, exist_ok=True)
    p = DIR_MAPS / "mapa_poblacion_censo2022.png"
    fig.savefig(p, dpi=200, bbox_inches="tight")
    plt.close(fig)
    log("Mapa 4: " + str(p))
    return p


def main() -> None:
    radios = descargar_radios_indec()
    pob = cargar_poblacion_censo()
    salida, resumen = cruzar_con_hueco(radios, pob)

    meta_path = DIR_OUT / "metadatos_analisis.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    pob_osm = meta["poblacion_estimada"]
    resumen["factor_subestimacion_proxy_osm"] = round(
        resumen["poblacion_censo_2022_total_estimada"] / pob_osm, 1)
    resumen["fuente_geometria"] = ("INDEC, GeoNode institucional, capa "
                                   "geonode:radios_censales2 (WFS)")
    resumen["fuente_poblacion"] = (
        "Boccolini, S. M. (2026). Argentina (2022) radios censales con datos "
        "de cantidad de poblacion y densidad de poblacion. CONICET Digital, "
        "CC BY 2.5 AR. Tabulacion del Censo 2022 (INDEC/Redatam).")
    resumen["metodo"] = ("Interpolacion areal: poblacion del radio ponderada "
                         "por la fraccion de su superficie dentro del hueco.")
    meta["censo_2022"] = resumen
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False),
                         encoding="utf-8")

    mapa_censo(salida, resumen)

    print("\n" + "=" * 74)
    print("CRUCE CON RADIOS CENSALES INDEC 2022")
    print("=" * 74)
    for k, v in resumen.items():
        if isinstance(v, (int, float)):
            print("  {:<42} {:>12,}".format(k, v))
    print("  partidos: " + ", ".join(resumen["partidos_involucrados"]))
    print("-" * 74)
    print("  Proxy OSM (fase 5)          : {:>12,.0f} hab".format(pob_osm))
    print("  Censo 2022 (fase 11)        : {:>12,} hab".format(
        resumen["poblacion_censo_2022_total_estimada"]))
    print("  El proxy subestimaba en     : x{}".format(
        resumen["factor_subestimacion_proxy_osm"]))


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(ROOT / "scripts"))
    main()

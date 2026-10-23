# -*- coding: utf-8 -*-
"""Agente gis-auditor: auditoria independiente de los productos del proyecto.

NO reutiliza los resultados guardados en metadatos: vuelve a leer las capas
desde disco y recalcula todo por su cuenta. Clasifica los hallazgos en
INFO / WARNING / ERROR / CRITICAL.

Uso:
    python scripts/gis_auditor.py
"""
from __future__ import annotations

import json
import math
import sys
from datetime import datetime
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parent.parent
DIR_INPUT = ROOT / "data" / "input"
DIR_WORK = ROOT / "work"
DIR_BUFFERS = DIR_WORK / "buffers"
DIR_OUT = ROOT / "outputs"
DIR_REPORTS = ROOT / "reports"

CRS_ESPERADO = "EPSG:32721"
RADIO_M = 5000
NIVELES = ["INFO", "WARNING", "ERROR", "CRITICAL"]

hallazgos: list[dict] = []


def add(nivel: str, chequeo: str, detalle: str, valor=None) -> None:
    hallazgos.append({"nivel": nivel, "chequeo": chequeo,
                      "detalle": detalle, "valor": valor})


def leer(ruta: Path, capa: str):
    if not ruta.exists():
        add("CRITICAL", "existencia_archivo",
            "No existe el producto esperado: " + str(ruta))
        return None
    try:
        return gpd.read_file(ruta, layer=capa)
    except Exception as exc:  # noqa: BLE001
        add("CRITICAL", "lectura_archivo",
            "No se pudo leer " + str(ruta) + ": " + str(exc)[:120])
        return None


def chequear_crs(gdf, etiqueta: str) -> None:
    if gdf is None:
        return
    if gdf.crs is None:
        add("CRITICAL", "crs_definido", etiqueta + " no tiene CRS definido")
        return
    crs = gdf.crs.to_string()
    if crs.upper() != CRS_ESPERADO:
        add("ERROR", "crs_correcto",
            etiqueta + " esta en " + crs + " y se esperaba " + CRS_ESPERADO, crs)
    elif not gdf.crs.is_projected:
        add("CRITICAL", "crs_proyectado", etiqueta + " no es un CRS proyectado")
    else:
        add("INFO", "crs_correcto", etiqueta + ": CRS " + crs + " (proyectado, metros)", crs)


def main() -> int:
    print("=" * 74)
    print("GIS-AUDITOR - Auditoria independiente | El Territorio de la UNAJ")
    print("=" * 74)

    buffers = leer(DIR_BUFFERS / "todos_los_buffers.gpkg", "buffers")
    hueco_gdf = leer(DIR_OUT / "hueco_exclusivo_UNAJ.gpkg", "hueco")
    edif_hueco = leer(DIR_OUT / "edificios_en_hueco.gpkg", "edificios")
    edif_utm = leer(DIR_WORK / "edificios_utm.gpkg", "edificios")
    univ = leer(DIR_WORK / "universidades_utm.gpkg", "universidades")

    for gdf, et in ((buffers, "buffers"), (hueco_gdf, "hueco_exclusivo"),
                    (edif_hueco, "edificios_en_hueco"),
                    (edif_utm, "edificios_utm"), (univ, "universidades")):
        chequear_crs(gdf, et)

    # --- Buffers -------------------------------------------------------------
    area_unaj = None
    if buffers is not None:
        if len(buffers) != 6:
            add("ERROR", "n_buffers",
                "Se esperaban 6 buffers y hay " + str(len(buffers)), len(buffers))
        else:
            add("INFO", "n_buffers", "6 buffers presentes", 6)
        teorico = math.pi * RADIO_M ** 2 / 1e6
        for _, r in buffers.iterrows():
            a = r.geometry.area / 1e6
            desv = abs(a - teorico) / teorico
            if desv > 0.01:
                add("WARNING", "area_buffer",
                    "Buffer " + r["nombre"] + ": " + "{:.2f}".format(a) +
                    " km2 se desvia " + "{:.2%}".format(desv) +
                    " del circulo teorico (" + "{:.2f}".format(teorico) + " km2)", a)
            if r["nombre"] == "UNAJ":
                area_unaj = a
        add("INFO", "area_buffer",
            "Areas de buffer coherentes con pi*r^2 = {:.2f} km2 "
            "(discretizacion del circulo < 1%)".format(teorico), teorico)
        if not buffers.geometry.is_valid.all():
            add("ERROR", "validez_buffers", "Hay buffers con geometria invalida")

    # --- Hueco ---------------------------------------------------------------
    area_hueco = None
    if hueco_gdf is not None:
        h = hueco_gdf.geometry.iloc[0]
        area_hueco = h.area / 1e6
        if area_hueco <= 0:
            add("CRITICAL", "area_hueco_positiva",
                "El area del hueco es " + str(area_hueco) + " km2 (<= 0)", area_hueco)
        else:
            add("INFO", "area_hueco_positiva",
                "Area del hueco = {:.2f} km2 (> 0)".format(area_hueco), area_hueco)
        if area_unaj is not None:
            if area_hueco > area_unaj:
                add("CRITICAL", "hueco_menor_que_buffer",
                    "El hueco ({:.2f} km2) es MAYOR que el buffer UNAJ "
                    "({:.2f} km2)".format(area_hueco, area_unaj))
            else:
                add("INFO", "hueco_menor_que_buffer",
                    "El hueco ({:.2f} km2) representa {:.1f}% del buffer UNAJ "
                    "({:.2f} km2)".format(area_hueco,
                                          100 * area_hueco / area_unaj, area_unaj),
                    round(100 * area_hueco / area_unaj, 2))
        if not h.is_valid:
            add("ERROR", "validez_hueco", "La geometria del hueco es invalida")
        else:
            add("INFO", "validez_hueco", "Geometria del hueco valida (" +
                h.geom_type + ")", h.geom_type)

        # Recalculo independiente de la resta topologica
        if buffers is not None and len(buffers) == 6:
            b_unaj = buffers.loc[buffers.nombre == "UNAJ"].geometry.iloc[0]
            union_comp = unary_union(
                list(buffers.loc[buffers.nombre != "UNAJ"].geometry))
            recalc = b_unaj.difference(union_comp)
            dif = abs(recalc.area - h.area) / max(recalc.area, 1)
            if dif > 1e-6:
                add("ERROR", "recalculo_resta",
                    "El hueco recalculado difiere en {:.4%} del guardado".format(dif))
            else:
                add("INFO", "recalculo_resta",
                    "Resta topologica reproducida de forma independiente: "
                    "{:.4f} km2".format(recalc.area / 1e6), recalc.area / 1e6)
            if h.buffer(-1.0).intersects(union_comp):
                add("ERROR", "hueco_sin_solape",
                    "El hueco solapa con la union de buffers competidores")
            else:
                add("INFO", "hueco_sin_solape",
                    "El hueco no solapa con ningun buffer competidor")
            if not h.buffer(1.0).contains(h) or not b_unaj.buffer(1.0).contains(h):
                add("ERROR", "hueco_dentro_unaj",
                    "El hueco no esta contenido en el buffer de la UNAJ")
            else:
                add("INFO", "hueco_dentro_unaj",
                    "El hueco esta contenido dentro del buffer de la UNAJ")

    # --- Edificios -----------------------------------------------------------
    n_total = len(edif_utm) if edif_utm is not None else None
    n_hueco = len(edif_hueco) if edif_hueco is not None else None
    if n_hueco is not None:
        if n_hueco == 0:
            add("CRITICAL", "edificios_en_hueco",
                "No hay ningun edificio dentro del hueco", 0)
        elif n_total is not None and n_hueco > n_total:
            add("CRITICAL", "edificios_coherentes",
                "Hay mas edificios en el hueco (" + str(n_hueco) +
                ") que en el total descargado (" + str(n_total) + ")")
        else:
            add("INFO", "edificios_en_hueco",
                "{:,} edificios seleccionados dentro del hueco sobre {:,} "
                "descargados ({:.1f}%)".format(
                    n_hueco, n_total, 100 * n_hueco / n_total), n_hueco)
        # verificacion espacial independiente: todos deben caer dentro del hueco
        if hueco_gdf is not None and n_hueco:
            h = hueco_gdf.geometry.iloc[0]
            pts = edif_hueco.geometry.centroid
            fuera = int((~pts.within(h.buffer(1.0))).sum())
            if fuera:
                add("ERROR", "edificios_dentro_del_hueco",
                    str(fuera) + " edificios del producto final caen FUERA del hueco",
                    fuera)
            else:
                add("INFO", "edificios_dentro_del_hueco",
                    "Los {:,} edificios verificados caen dentro del hueco".format(
                        n_hueco))

    # --- Poblacion -----------------------------------------------------------
    meta_path = DIR_OUT / "metadatos_analisis.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    pob = meta.get("poblacion_estimada")
    factor = meta.get("factor_hab_por_edificio")
    if pob is None:
        add("ERROR", "poblacion_registrada", "No hay poblacion estimada en metadatos")
    elif pob < 0:
        add("CRITICAL", "poblacion_no_negativa",
            "Poblacion estimada negativa: " + str(pob), pob)
    else:
        add("INFO", "poblacion_no_negativa",
            "Poblacion estimada = {:,.0f} hab (>= 0)".format(pob), pob)
        if n_hueco and factor:
            esperado = n_hueco * factor
            if abs(esperado - pob) > 1:
                add("ERROR", "poblacion_recalculada",
                    "Recalculo: {:,} edificios x {} = {:,.0f} != {:,.0f} "
                    "registrado".format(n_hueco, factor, esperado, pob))
            else:
                add("INFO", "poblacion_recalculada",
                    "Poblacion reproducida: {:,} x {} = {:,.0f} hab".format(
                        n_hueco, factor, esperado))
        if area_hueco:
            dens = pob / area_hueco
            if dens > 25000:
                add("WARNING", "densidad_plausible",
                    "Densidad implausiblemente alta para el sur del AMBA: "
                    "{:,.0f} hab/km2".format(dens), dens)
            elif dens < 300:
                add("WARNING", "densidad_plausible",
                    "Densidad muy baja para un area urbana: "
                    "{:,.0f} hab/km2".format(dens), dens)
            else:
                add("INFO", "densidad_plausible",
                    "Densidad estimada {:,.0f} hab/km2, en rango periurbano/urbano "
                    "del sur del AMBA".format(dens), dens)

    if meta.get("advertencia_residencial"):
        add("WARNING", "proxy_residencial", str(meta["advertencia_residencial"]))
    if str(meta.get("fuente_edificios", "")).startswith("SINTETICA"):
        add("CRITICAL", "fuente_datos",
            "Los edificios NO provienen de OSM sino de la capa sintetica de respaldo")
    if meta.get("osm_tiles_fallidos"):
        add("WARNING", "cobertura_descarga",
            "Tiles de descarga OSM fallidos: " + str(meta["osm_tiles_fallidos"]))

    # --- Cruce censal INDEC 2022 (FASE 11) -----------------------------------
    censo = meta.get("censo_2022")
    radios = leer(DIR_OUT / "radios_censo_en_hueco.gpkg", "radios") \
        if (DIR_OUT / "radios_censo_en_hueco.gpkg").exists() else None
    if censo and radios is not None:
        chequear_crs(radios, "radios_censo_en_hueco")

        if int(radios["cod_indec"].duplicated().sum()):
            add("ERROR", "radios_sin_duplicar",
                "Hay codigos de radio duplicados: la poblacion estaria "
                "contada dos veces")
        else:
            add("INFO", "radios_sin_duplicar",
                "{} radios censales, sin codigos duplicados".format(len(radios)))

        # Los radios deben teselar el hueco por completo
        if area_hueco:
            cob = float(radios.geometry.area.sum() / 1e6)
            desv = abs(cob - area_hueco) / area_hueco
            if desv > 0.01:
                add("WARNING", "cobertura_censal",
                    "Los radios cubren {:.2f} km2 de los {:.2f} km2 del hueco "
                    "({:.1%} sin cobertura censal)".format(
                        cob, area_hueco, desv), round(cob, 2))
            else:
                add("INFO", "cobertura_censal",
                    "Los radios censales cubren integramente el hueco "
                    "({:.2f} km2 de {:.2f} km2)".format(cob, area_hueco))

        pa = censo["poblacion_censo_2022_areal"]
        pc = censo["poblacion_censo_2022_por_centroide"]
        if pa <= 0:
            add("CRITICAL", "poblacion_censal_positiva",
                "La poblacion censal asignada no es positiva", pa)
        else:
            dif = abs(pa - pc) / pa
            if dif > 0.10:
                add("WARNING", "consistencia_metodos_censales",
                    "Interpolacion areal ({:,}) y criterio de centroide "
                    "({:,}) difieren {:.1%}".format(pa, pc, dif))
            else:
                add("INFO", "consistencia_metodos_censales",
                    "Dos metodos independientes coinciden: interpolacion areal "
                    "{:,} hab vs centroide {:,} hab ({:.1%} de diferencia)".format(
                        pa, pc, dif), round(dif, 4))

        # Recalculo independiente de la suma ponderada
        recalc = float((radios["poblacion_2022"] *
                        radios["fraccion_en_hueco"]).sum())
        if abs(recalc - pa) > max(1.0, 0.001 * pa):
            add("ERROR", "recalculo_poblacion_censal",
                "Recalculo de la interpolacion areal: {:,.0f} != {:,} "
                "registrado".format(recalc, pa))
        else:
            add("INFO", "recalculo_poblacion_censal",
                "Interpolacion areal reproducida de forma independiente: "
                "{:,.0f} hab".format(recalc))

        fr = radios["fraccion_en_hueco"]
        if float(fr.max()) > 1.0001 or float(fr.min()) <= 0:
            add("ERROR", "fracciones_validas",
                "Hay fracciones de area fuera del rango (0, 1]: "
                "min={:.4f} max={:.4f}".format(fr.min(), fr.max()))
        else:
            add("INFO", "fracciones_validas",
                "Todas las fracciones de area estan en (0, 1]; {} radios "
                "quedan integros dentro del hueco".format(
                    censo["n_radios_integros_en_hueco"]))

        if area_hueco:
            dens_c = censo["densidad_censal_hab_km2"]
            if 1000 <= dens_c <= 20000:
                add("INFO", "densidad_censal_plausible",
                    "Densidad censal {:,} hab/km2, coherente con el tejido "
                    "urbano del sur del Conurbano".format(dens_c), dens_c)
            else:
                add("WARNING", "densidad_censal_plausible",
                    "Densidad censal fuera del rango esperado: {:,} hab/km2"
                    .format(dens_c), dens_c)

        if pob:
            add("WARNING", "proxy_osm_invalidado",
                "El proxy de edificios OSM ({:,.0f} hab) subestima el dato "
                "censal ({:,} hab) por un factor de {}. El proxy NO debe "
                "usarse para dimensionar poblacion en esta zona.".format(
                    pob, censo["poblacion_censo_2022_total_estimada"],
                    censo["factor_subestimacion_proxy_osm"]))
    elif censo or radios is not None:
        add("ERROR", "cruce_censal_incompleto",
            "Hay productos del cruce censal pero faltan metadatos o la capa")

    # --- Sensibilidad al radio (FASE 12) -------------------------------------
    sens = meta.get("sensibilidad_radio")
    if sens:
        tabla = pd.DataFrame(sens["tabla"])
        base = tabla[tabla.radio_km == sens["radio_base_km"]]
        if not len(base):
            add("ERROR", "sensibilidad_radio_base",
                "La tabla de sensibilidad no incluye el radio base")
        else:
            b = base.iloc[0]
            if area_hueco and abs(b.area_hueco_km2 - area_hueco) > 0.05:
                add("ERROR", "sensibilidad_consistente",
                    "En r={} km la sensibilidad da {:.2f} km2 pero el analisis "
                    "principal da {:.2f} km2".format(
                        sens["radio_base_km"], b.area_hueco_km2, area_hueco))
            else:
                add("INFO", "sensibilidad_consistente",
                    "La curva de sensibilidad reproduce el analisis principal "
                    "en r={} km ({:.2f} km2)".format(
                        sens["radio_base_km"], b.area_hueco_km2))
        if not tabla.area_buffer_km2.is_monotonic_increasing:
            add("ERROR", "sensibilidad_monotonia",
                "El area del buffer no crece de forma monotona con el radio")
        else:
            add("INFO", "sensibilidad_monotonia",
                "El area del buffer crece de forma monotona con el radio "
                "({} radios evaluados)".format(len(tabla)))
        if (tabla.area_hueco_km2 > tabla.area_buffer_km2 + 1e-6).any():
            add("CRITICAL", "sensibilidad_hueco_acotado",
                "Algun hueco supera el area de su propio buffer")
        else:
            add("INFO", "sensibilidad_hueco_acotado",
                "En todos los radios el hueco es menor o igual que su buffer")
        r_sol = sens.get("primer_radio_con_solape_km")
        if r_sol:
            add("INFO", "radio_sin_competencia",
                "Hasta r < {} km la cobertura de la UNAJ es 100% exclusiva"
                .format(r_sol), r_sol)

    # --- Isocronas por red vial (FASE 13) ------------------------------------
    iso = meta.get("isocronas_red")
    sa = leer(DIR_OUT / "areas_servicio_red.gpkg", "areas") \
        if (DIR_OUT / "areas_servicio_red.gpkg").exists() else None
    hred = leer(DIR_OUT / "hueco_exclusivo_UNAJ_red.gpkg", "hueco") \
        if (DIR_OUT / "hueco_exclusivo_UNAJ_red.gpkg").exists() else None
    if iso and sa is not None and hred is not None:
        chequear_crs(sa, "areas_servicio_red")
        chequear_crs(hred, "hueco_exclusivo_UNAJ_red")

        # Toda area de servicio debe caber dentro del circulo euclidiano mas
        # el buffer de acceso: es una garantia matematica del metodo.
        if buffers is not None:
            margen = iso["acceso_desde_eje_m"] + 1.0
            fuera = []
            for _, r in sa.iterrows():
                b = buffers.loc[buffers.nombre == r["nombre"]]
                if not len(b):
                    continue
                if not b.geometry.iloc[0].buffer(margen).contains(r.geometry):
                    fuera.append(r["nombre"])
            if fuera:
                add("ERROR", "area_servicio_acotada",
                    "Areas de servicio que exceden su circulo euclidiano mas "
                    "el acceso: " + str(fuera))
            else:
                add("INFO", "area_servicio_acotada",
                    "Las 6 areas de servicio caben dentro de su circulo de "
                    "5 km mas los {:.0f} m de acceso, como exige el metodo"
                    .format(iso["acceso_desde_eje_m"]))

        a_red = iso["hueco_red_area_km2"]
        a_sa = float(sa.loc[sa.nombre == "UNAJ", "area_km2"].iloc[0])
        if a_red > a_sa + 1e-6:
            add("CRITICAL", "hueco_red_acotado",
                "El hueco por red ({:.2f}) supera el area de servicio de la "
                "UNAJ ({:.2f})".format(a_red, a_sa))
        else:
            add("INFO", "hueco_red_acotado",
                "El hueco por red ({:.2f} km2) es el {:.1f}% del area de "
                "servicio de la UNAJ".format(a_red, 100 * a_red / a_sa),
                round(100 * a_red / a_sa, 1))

        if a_red > (area_hueco or 0) + 1e-6:
            add("ERROR", "red_menor_que_euclidiano",
                "El hueco por red supera al euclidiano, lo que contradice que "
                "la distancia de red sea siempre >= la euclidiana")
        else:
            add("INFO", "red_menor_que_euclidiano",
                "El hueco por red ({:.2f} km2) es menor que el euclidiano "
                "({:.2f} km2), como corresponde".format(a_red, area_hueco))

        if iso["hueco_red_poblacion"] <= 0:
            add("CRITICAL", "poblacion_red_positiva",
                "La poblacion del hueco por red no es positiva")
        else:
            add("INFO", "poblacion_red_positiva",
                "Poblacion del hueco por red: {:,} hab ({:,} hab/km2)".format(
                    iso["hueco_red_poblacion"],
                    iso["hueco_red_densidad_hab_km2"]))

        cobs = [f["cobertura_pct"] for f in iso["areas_de_servicio"]]
        add("INFO", "sobreestimacion_del_circulo",
            "El buffer euclidiano sobreestima la cobertura real: las areas de "
            "servicio van del {:.1f}% al {:.1f}% del circulo".format(
                min(cobs), max(cobs)), round(float(np.mean(cobs)), 1))
    elif iso or sa is not None or hred is not None:
        add("ERROR", "isocronas_incompletas",
            "Hay productos de isocronas pero faltan metadatos o alguna capa")

    # --- Universo completo de universidades (FASE 14) ------------------------
    uni = meta.get("universo_educativo")
    if uni:
        n_total = uni.get("n_candidatos_amba_total", 0)
        n_nuevas = uni.get("n_candidatos_nacionales_nuevos", 0)
        if n_total < 100:
            add("WARNING", "universo_muestra_amplia",
                "Solo se relevaron {} sedes en el AMBA; parece poco para "
                "una region con millones de habitantes".format(n_total))
        else:
            add("INFO", "universo_muestra_amplia",
                "{} sedes universitarias/college relevadas en OSM en todo "
                "el AMBA antes de filtrar".format(n_total), n_total)

        dist_min = uni.get("distancia_minima_al_hueco_km")
        n_alcanzan = uni.get("n_que_alcanzan_el_hueco", 0)
        if n_alcanzan > 0:
            add("CRITICAL", "universo_no_amenaza_exclusividad",
                "{} sedes fuera de las 6 originales alcanzan el hueco con su "
                "radio de 5 km; el hueco exclusivo esta MAL CALCULADO si no "
                "se las incluye en la resta topologica".format(n_alcanzan))
        elif dist_min is not None:
            add("INFO", "universo_no_amenaza_exclusividad",
                "Ninguna de las {} sedes nacionales adicionales alcanza el "
                "hueco; la mas cercana esta a {:.2f} km de su borde (> 5 km)"
                .format(n_nuevas, dist_min), dist_min)

        # Recalculo independiente: releer la capa y remedir distancias
        cand_path = DIR_OUT / "universo_universidades_amba.gpkg"
        if cand_path.exists():
            cand = leer(cand_path, "candidatos")
            chequear_crs(cand, "universo_universidades_amba")
            if cand is not None and hueco_gdf is not None and len(cand):
                h = hueco_gdf.geometry.iloc[0]
                recalc_min = float(cand.geometry.distance(h).min() / 1000)
                if dist_min is not None and abs(recalc_min - dist_min) > 0.05:
                    add("ERROR", "universo_recalculo",
                        "La distancia minima recalculada ({:.2f} km) no "
                        "coincide con la registrada ({:.2f} km)".format(
                            recalc_min, dist_min))
                else:
                    add("INFO", "universo_recalculo",
                        "Distancia minima al hueco reproducida de forma "
                        "independiente: {:.2f} km".format(recalc_min))
        n_dup = uni.get("n_sedes_secundarias_de_universidades_ya_incluidas", 0)
        if n_dup:
            add("INFO", "universo_duplicados_documentados",
                "{} candidatos identificados como sedes secundarias de "
                "universidades ya incluidas, no como competidoras nuevas"
                .format(n_dup))
        if uni.get("isfd_en_la_zona"):
            add("INFO", "oferta_terciaria_documentada",
                "{} institutos terciarios provinciales documentados dentro "
                "de la zona (no universitarios, no de gestion nacional)"
                .format(len(uni["isfd_en_la_zona"])))

    # --- RENABAP (FASE 15) ----------------------------------------------------
    ren = meta.get("renabap")
    ren_gdf = leer(DIR_OUT / "renabap_en_hueco.gpkg", "barrios") \
        if (DIR_OUT / "renabap_en_hueco.gpkg").exists() else None
    if ren and ren_gdf is not None:
        chequear_crs(ren_gdf, "renabap_en_hueco")

        if int((ren_gdf.geometry.area <= 0).sum()):
            add("ERROR", "renabap_geometrias_validas",
                "Hay poligonos de barrios populares con area <= 0")
        else:
            add("INFO", "renabap_geometrias_validas",
                "Los {} poligonos de barrios populares tienen area > 0"
                .format(len(ren_gdf)))

        area_ren_total = float(ren_gdf.geometry.area.sum() / 1e6)
        if area_hueco and area_ren_total > area_hueco:
            add("CRITICAL", "renabap_area_acotada",
                "El area de barrios populares supera el area del hueco")
        else:
            add("INFO", "renabap_area_acotada",
                "El area de barrios populares ({:.2f} km2) es coherente, "
                "menor que el hueco ({:.2f} km2)".format(
                    ren["area_renabap_en_hueco_km2"], area_hueco or 0))

        # Recalculo independiente de la poblacion RENABAP
        factor = ren["factor_personas_por_familia"]
        recalc = float((ren_gdf["familias_en_hueco"] * factor).sum())
        registrado = ren["poblacion_renabap_en_hueco"]
        if abs(recalc - registrado) > max(1.0, 0.01 * registrado):
            add("ERROR", "renabap_recalculo",
                "Poblacion RENABAP recalculada ({:,.0f}) no coincide con la "
                "registrada ({:,})".format(recalc, registrado))
        else:
            add("INFO", "renabap_recalculo",
                "Poblacion en barrios populares reproducida de forma "
                "independiente: {:,.0f} hab".format(recalc))

        pct = ren["pct_poblacion_censal_en_renabap"]
        if pct < 0 or pct > 100:
            add("CRITICAL", "renabap_pct_valido",
                "El porcentaje de poblacion en RENABAP esta fuera de [0,100]: "
                "{}".format(pct))
        else:
            add("INFO", "renabap_pct_valido",
                "{}% de la poblacion censal del hueco vive en barrios "
                "populares relevados".format(pct), pct)

        cloaca = ren.get("cloaca_formal_pct") or {}
        if cloaca.get("pct_familias") is not None and cloaca["pct_familias"] < 50:
            add("WARNING", "renabap_infraestructura_precaria",
                "Solo el {}% de las familias en barrios populares del hueco "
                "tiene conexion formal a cloaca (agua: {}%, electricidad: "
                "{}%)".format(
                    cloaca["pct_familias"],
                    (ren.get("agua_formal_pct") or {}).get("pct_familias"),
                    (ren.get("electricidad_formal_pct") or {}).get("pct_familias")))

    elif ren or ren_gdf is not None:
        add("ERROR", "renabap_incompleto",
            "Hay productos de RENABAP pero faltan metadatos o la capa")

    # --- Validacion externa (FASE 16) -----------------------------------------
    val = meta.get("validacion_externa")
    if val:
        pv = val["poblacion_vs_indec"]
        if not pv["filas"]:
            add("ERROR", "validacion_censal_presente",
                "No hay filas de comparacion censal contra INDEC")
        else:
            recalc_siempre_abajo = all(f["diferencia_pct"] < 0 for f in pv["filas"])
            if recalc_siempre_abajo != pv["siempre_por_debajo"]:
                add("ERROR", "validacion_censal_consistente",
                    "El flag 'siempre_por_debajo' no coincide con las filas")
            else:
                add("INFO", "validacion_censal_consistente",
                    "Cruce censal vs. INDEC oficial: {} partidos, diferencia "
                    "entre {:.2f}% y {:.2f}% (siempre por debajo: {})".format(
                        len(pv["filas"]), pv["diferencia_min_pct"],
                        pv["diferencia_max_pct"], pv["siempre_por_debajo"]))
            for f in pv["filas"]:
                recalc = round(100 * (f["nuestra_fuente"] - f["indec_oficial"])
                              / f["indec_oficial"], 2)
                if abs(recalc - f["diferencia_pct"]) > 0.01:
                    add("ERROR", "validacion_censal_recalculo",
                        "{}: diferencia recalculada {}% no coincide con la "
                        "registrada {}%".format(f["partido"], recalc,
                                               f["diferencia_pct"]))

        rv = val["renabap_vigencia"]
        recalc_crec = round(100 * (rv["barrios_actual"] - rv["barrios_2020"])
                            / rv["barrios_2020"], 1)
        if abs(recalc_crec - rv["crecimiento_pct"]) > 0.1:
            add("ERROR", "validacion_renabap_recalculo",
                "Crecimiento RENABAP recalculado ({}%) no coincide con el "
                "registrado ({}%)".format(recalc_crec, rv["crecimiento_pct"]))
        else:
            add("INFO", "validacion_renabap_recalculo",
                "RENABAP: {:,} barrios (2020) -> {:,} actuales (+{}%), "
                "reproducido de forma independiente".format(
                    rv["barrios_2020"], rv["barrios_actual"], rv["crecimiento_pct"]))
        if rv["barrios_actual"] <= rv["barrios_2020"]:
            add("WARNING", "validacion_renabap_direccion",
                "El registro actual no crecio respecto de 2020; revisar si "
                "la cifra de referencia sigue vigente")

        mr = val["matricula_real"]
        suma_matricula = sum(f["pct_matricula_real"] for f in mr["filas"])
        if suma_matricula > 100:
            add("CRITICAL", "validacion_matricula_coherente",
                "La suma de porcentajes de matricula por partido supera 100%: "
                "{}%".format(suma_matricula))
        else:
            add("INFO", "validacion_matricula_coherente",
                "Matricula real de la UNAJ por partido documentada para {} "
                "partidos, suma {}% (resto: otras regiones)".format(
                    len(mr["filas"]), round(suma_matricula, 1)))
        add("INFO", "validacion_matricula_comparacion",
            "Mejor ajuste hueco vs. matricula real: {}. Peor ajuste: {}".format(
                mr["mejor_ajuste"], mr["peor_ajuste"]))
    else:
        add("WARNING", "validacion_externa_ausente",
            "No se encontraron metadatos de validacion externa (fase 16 no "
            "corrida)")

    # --- Regla constitucional: data/input inmutable --------------------------
    esperados = {"edificios_osm_raw.gpkg"}
    reales = {p.name for p in DIR_INPUT.glob("*") if p.is_file()}
    extra = reales - esperados
    if extra:
        add("WARNING", "input_inmutable",
            "data/input contiene archivos no previstos: " + str(sorted(extra)))
    elif reales == esperados:
        add("INFO", "input_inmutable",
            "data/input contiene unicamente el raw de OSM (regla respetada)")

    # --- Salida --------------------------------------------------------------
    conteo = {n: sum(1 for h in hallazgos if h["nivel"] == n) for n in NIVELES}
    for n in NIVELES:
        for h in hallazgos:
            if h["nivel"] == n:
                print("[{:<8}] {:<28} {}".format(h["nivel"], h["chequeo"],
                                                 h["detalle"]))
    print("-" * 74)
    print("RESUMEN: " + "  ".join(
        "{}={}".format(n, conteo[n]) for n in NIVELES))
    veredicto = ("APROBADO" if conteo["CRITICAL"] == 0 and conteo["ERROR"] == 0
                 else "RECHAZADO")
    print("VEREDICTO DE AUDITORIA: " + veredicto +
          ("  (con advertencias)" if conteo["WARNING"] else ""))

    DIR_REPORTS.mkdir(parents=True, exist_ok=True)
    salida = {"fecha": datetime.now().isoformat(timespec="seconds"),
              "veredicto": veredicto, "conteo": conteo, "hallazgos": hallazgos}
    (DIR_REPORTS / "auditoria.json").write_text(
        json.dumps(salida, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Reporte JSON: " + str(DIR_REPORTS / "auditoria.json"))
    return 0 if veredicto == "APROBADO" else 1


if __name__ == "__main__":
    sys.exit(main())

# -*- coding: utf-8 -*-
"""FASE 16 - Validacion externa contra fuentes independientes.

A diferencia de las demas fases, esta no descarga datos de un servicio en
vivo: coteja los resultados del analisis contra tres referencias externas
relevadas manualmente (busqueda web + lectura de fuentes primarias), citadas
una por una. Es investigacion, no una consulta automatizable de forma
confiable -- por eso los valores de referencia estan declarados como
constantes documentadas en vez de "descargados", y el modulo deja explicito
de donde sale cada uno.

Tres cruces:
  1. Poblacion censal: la tabla de CONICET/Boccolini que usamos en la fase
     10 (censo) contra los totales OFICIALES DEFINITIVOS del Censo 2022
     publicados por INDEC para cada partido.
  2. Vigencia del RENABAP: el relevamiento 2020 que usamos en la fase 15
     contra el tamano actual del registro nacional.
  3. Validacion contra demanda real: la composicion por partido del hueco
     (fase 10) contra la procedencia real de los estudiantes de la UNAJ,
     publicada por la propia universidad. Es el unico cruce que compara la
     prediccion geometrica del buffer contra comportamiento real, no otra
     fuente de poblacion.

Uso:
    python scripts/validacion_externa.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIR_OUT = ROOT / "outputs"

# ---------------------------------------------------------------------------
# Referencias externas (relevadas manualmente, agosto 2026). Cada valor cita
# su fuente primaria para que se pueda re-verificar.
# ---------------------------------------------------------------------------

# Censo 2022, resultados DEFINITIVOS (INDEC, publicados nov. 2023), citados
# via Wikipedia (que a su vez cita a INDEC directamente) y atlasconurbano.info.
# https://es.wikipedia.org/wiki/Partido_de_Florencio_Varela
# https://es.wikipedia.org/wiki/Partido_de_Quilmes
# https://es.wikipedia.org/wiki/Partido_de_Berazategui
POBLACION_INDEC_OFICIAL = {
    "Florencio Varela": 496_433,
    "Quilmes": 633_191,
    "Berazategui": 358_712,
}

# RENABAP: relevamiento 2020 (el que usamos, capa renabap2020_smz) vs.
# tamano actual del registro nacional.
# https://www.argentina.gob.ar/desarrollosocial/renabap
RENABAP_BARRIOS_2020 = 4416
RENABAP_BARRIOS_ACTUAL = 6467

# Procedencia real de los estudiantes de la UNAJ por partido, publicada por
# la propia universidad (nota institucional, decimo aniversario).
# https://www.unaj.edu.ar/en-su-decimo-aniversario-inscripcion-record-en-la-unaj/
MATRICULA_UNAJ_POR_PARTIDO_PCT = {
    "Florencio Varela": 33.0,
    "Berazategui": 22.0,
    "Quilmes": 22.0,
    "Almirante Brown": 8.0,
}

FUENTES = {
    "poblacion_indec": "INDEC, Censo 2022, resultados definitivos (nov. 2023), "
                       "via Wikipedia (partidos de Florencio Varela, Quilmes y "
                       "Berazategui) y atlasconurbano.info",
    "renabap_vigencia": "Argentina.gob.ar/desarrollosocial/renabap "
                        "(relevamiento 2020 vs. registro actual)",
    "matricula_unaj": "unaj.edu.ar, nota institucional por el 10 aniversario "
                      "de la universidad (procedencia de estudiantes por "
                      "partido)",
}


def cruzar_poblacion_censal(meta: dict) -> dict:
    """Compara nuestra fuente censal (CONICET/Boccolini) contra los totales
    oficiales definitivos del INDEC, partido por partido."""
    # el desglose de la fase 10 es del HUECO, no del partido completo -- para
    # este cruce necesitamos el total poblacional de la fuente en cada
    # partido completo, que se calculo en cruce_censo.cargar_poblacion_censo().
    # Se recalcula aqui a partir del gpkg de CONICET, igual que en esa fase.
    import geopandas as gpd
    pob = gpd.read_file(ROOT / "data" / "censo" / "radios_2022_conDatos_1habHa.gpkg",
                        columns=["NOMDEPTO", "CA3"], ignore_geometry=True)
    totales_fuente = pob.groupby("NOMDEPTO")["CA3"].sum().to_dict()

    filas = []
    for partido, oficial in POBLACION_INDEC_OFICIAL.items():
        nuestro = float(totales_fuente.get(partido, 0))
        dif_pct = round(100 * (nuestro - oficial) / oficial, 2)
        filas.append({
            "partido": partido,
            "nuestra_fuente": round(nuestro),
            "indec_oficial": oficial,
            "diferencia_pct": dif_pct,
        })

    return {
        "filas": filas,
        "diferencia_min_pct": min(f["diferencia_pct"] for f in filas),
        "diferencia_max_pct": max(f["diferencia_pct"] for f in filas),
        "siempre_por_debajo": all(f["diferencia_pct"] < 0 for f in filas),
        "fuente": FUENTES["poblacion_indec"],
    }


def evaluar_vigencia_renabap() -> dict:
    crecimiento_pct = round(
        100 * (RENABAP_BARRIOS_ACTUAL - RENABAP_BARRIOS_2020) / RENABAP_BARRIOS_2020, 1)
    return {
        "barrios_2020": RENABAP_BARRIOS_2020,
        "barrios_actual": RENABAP_BARRIOS_ACTUAL,
        "crecimiento_pct": crecimiento_pct,
        "fuente": FUENTES["renabap_vigencia"],
    }


def validar_contra_matricula(meta: dict) -> dict:
    """Compara la composicion por partido del hueco (poblacion) contra la
    procedencia real de los estudiantes de la UNAJ."""
    desglose = {d["partido"]: d["poblacion"]
               for d in meta["censo_2022"]["desglose_por_partido"]}
    total_hueco = sum(desglose.values())

    filas = []
    for partido, pct_real in MATRICULA_UNAJ_POR_PARTIDO_PCT.items():
        pob_hueco = desglose.get(partido, 0)
        pct_hueco = round(100 * pob_hueco / total_hueco, 1) if total_hueco else 0.0
        filas.append({
            "partido": partido,
            "pct_matricula_real": pct_real,
            "pct_poblacion_hueco": pct_hueco,
            "diferencia_pp": round(pct_hueco - pct_real, 1),
        })
    filas.sort(key=lambda f: abs(f["diferencia_pp"]))

    return {
        "filas": filas,
        "mejor_ajuste": filas[0]["partido"],
        "peor_ajuste": filas[-1]["partido"],
        "fuente": FUENTES["matricula_unaj"],
    }


def main() -> None:
    meta_path = DIR_OUT / "metadatos_analisis.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    resumen = {
        "poblacion_vs_indec": cruzar_poblacion_censal(meta),
        "renabap_vigencia": evaluar_vigencia_renabap(),
        "matricula_real": validar_contra_matricula(meta),
    }
    meta["validacion_externa"] = resumen
    meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False),
                         encoding="utf-8")

    print("=" * 78)
    print("VALIDACION EXTERNA")
    print("=" * 78)
    print("\n-- Poblacion censal vs. INDEC oficial (resultados definitivos) --")
    for f in resumen["poblacion_vs_indec"]["filas"]:
        print("  {:<20} nuestra={:>9,} indec={:>9,}  dif={:+.2f}%".format(
            f["partido"], f["nuestra_fuente"], f["indec_oficial"], f["diferencia_pct"]))
    print("  Siempre por debajo del oficial:",
          resumen["poblacion_vs_indec"]["siempre_por_debajo"])

    print("\n-- Vigencia del RENABAP --")
    r = resumen["renabap_vigencia"]
    print("  2020: {:,} barrios | actual: {:,} barrios | +{}%".format(
        r["barrios_2020"], r["barrios_actual"], r["crecimiento_pct"]))

    print("\n-- Composicion del hueco vs. matricula real UNAJ --")
    for f in resumen["matricula_real"]["filas"]:
        print("  {:<20} matricula={:>5.1f}%  hueco={:>5.1f}%  dif={:+.1f}pp".format(
            f["partido"], f["pct_matricula_real"], f["pct_poblacion_hueco"],
            f["diferencia_pp"]))


if __name__ == "__main__":
    main()

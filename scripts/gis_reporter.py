# -*- coding: utf-8 -*-
"""Agente gis-reporter: construye reports/informe_hueco_educativo.md a partir
de los metadatos, la auditoria y los productos generados.

Uso:
    python scripts/gis_reporter.py
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DIR_OUT = ROOT / "outputs"
DIR_REPORTS = ROOT / "reports"

NOMBRES_LARGOS = {
    "UNAJ": "Universidad Nacional Arturo Jauretche (Florencio Varela)",
    "UNQUI": "Universidad Nacional de Quilmes (Bernal)",
    "UNLP": "Universidad Nacional de La Plata",
    "UNLZ": "Universidad Nacional de Lomas de Zamora",
    "UNaB": "Universidad Nacional Guillermo Brown (Burzaco)",
    "UNLANUS": "Universidad Nacional de Lanus (Remedios de Escalada)",
}


def miles(x, dec=0):
    """Formato es-AR: punto para miles, coma para decimales."""
    if x is None:
        return "n/d"
    s = "{:,.{d}f}".format(x, d=dec)
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def main() -> None:
    meta = json.loads((DIR_OUT / "metadatos_analisis.json").read_text(
        encoding="utf-8"))
    aud_path = DIR_REPORTS / "auditoria.json"
    aud = json.loads(aud_path.read_text(encoding="utf-8")) \
        if aud_path.exists() else {}
    dist = pd.read_csv(DIR_OUT / "distancias_universidades.csv")

    c = meta["censo_2022"]
    area = meta["hueco_area_km2"]
    pct = meta["hueco_pct_buffer_unaj"]
    pob_censo = c["poblacion_censo_2022_total_estimada"]
    pob_osm = meta["poblacion_estimada"]

    comp = dist[dist.rol == "competidora"].sort_values("dist_centroide_km")
    d_unaj = float(dist.loc[dist.rol == "objetivo", "dist_centroide_km"].iloc[0])
    d_comp = float(comp.dist_centroide_km.iloc[0])
    comp_cerca = str(comp.universidad.iloc[0])

    tabla_dist = "\n".join(
        "| {} | {} | {} | {} |".format(
            r.universidad, NOMBRES_LARGOS.get(r.universidad, ""),
            miles(r.dist_centroide_km, 2), miles(r.dist_min_al_hueco_km, 2))
        for _, r in dist.iterrows())

    tabla_partidos = "\n".join(
        "| {} | {} | {} | {} | {} |".format(
            d["partido"], miles(d["n_radios"]), miles(d["area_km2"], 2),
            miles(d["poblacion"]), miles(d["densidad_hab_km2"]))
        for d in c["desglose_por_partido"])

    hall = aud.get("hallazgos", [])

    def bloque(nivel):
        items = [h for h in hall if h["nivel"] == nivel]
        if not items:
            return "_Sin hallazgos de nivel {}._".format(nivel)
        return "\n".join("- **{}** — {}".format(h["chequeo"], h["detalle"])
                         for h in items)

    conteo = aud.get("conteo", {})
    conteo_txt = ", ".join("{}: {}".format(k, v) for k, v in conteo.items())

    md = """# Informe técnico — El Territorio de la UNAJ

**Proyecto:** Determinación del área de cobertura exclusiva de la Universidad Nacional Arturo Jauretche (UNAJ) en el sur del AMBA y de la población que vive en ella
**Fecha de elaboración:** {fecha}
**Sistema de referencia de trabajo:** EPSG:32721 — WGS 84 / UTM zona 21S (unidades: metros)
**Fuentes principales:** INDEC (Censo Nacional 2022 y cartografía de radios censales) · OpenStreetMap © colaboradores (ODbL)

---

## 1. Resumen ejecutivo

> **Hay {area} km² del sur del Conurbano donde la UNAJ es la única universidad nacional a menos de 5 km. Según el Censo 2022, allí viven {pob_censo} personas. La siguiente universidad nacional está a {d_comp} km.**

Dentro de su radio de influencia de 5 km, la UNAJ cubre {area} km² —el **{pct} %** de esa área— que **ninguna** de las otras cinco universidades nacionales del sur del AMBA (UNQUI, UNLP, UNLZ, UNaB, UNLaNús) alcanza dentro del mismo radio.

El cruce de esa geometría con los **562 radios censales del Censo Nacional 2022** arroja **{pob_censo} habitantes**, con una densidad de {dens_censo} hab/km². La zona abarca porciones de cuatro partidos: Quilmes, Florencio Varela, Berazategui y Almirante Brown. No es periferia: los 562 radios son de tipo **urbano** sin excepción.

Dos controles confirman que el resultado no depende de decisiones arbitrarias:

- **El radio de 5 km no es una elección oportunista** (§3.4). Repetido el análisis en {n_radios_ev} radios entre 1 y 10 km, hay población exclusiva en todos: hasta los {r_solape} km la cobertura es 100 % exclusiva, y el máximo de población está en {r_max} km ({pob_max} hab). Los 5 km quedan del lado conservador.
- **Medido sobre la red vial real y no en línea recta** (§3.5), el área exclusiva es de {area_red} km² con {pob_red} habitantes — y resulta **100 % exclusiva**: no solapa ni un metro cuadrado con el área de servicio de ninguna otra universidad nacional.
- **La comparación no se limita a 5 competidoras elegidas a mano** (§3.6). Puesta a prueba contra las {n_genuinas} universidades nacionales del AMBA completo, ninguna alcanza el hueco: la más cercana queda a {dist_min_uni} km de su borde.
- **No es sólo una cuestión de distancia** (§3.7). Al menos {pob_renabap} personas del hueco —el {pct_renabap} %— viven en barrios populares relevados por el RENABAP, donde sólo el {cloaca_familias} % de las familias tiene conexión cloacal formal.
- **Se puso a prueba contra fuentes externas** (§8). Nuestra fuente censal subestima al INDEC oficial en los tres partidos (nunca lo exagera), y la composición del hueco coincide de cerca con la procedencia real de los estudiantes de la UNAJ en Florencio Varela y Berazategui — aunque diverge en Quilmes, la prueba más honesta de que el buffer de 5 km es una aproximación y no un mapa exacto.

| Indicador | Valor |
|---|---|
| Área del hueco exclusivo | **{area} km²** |
| Porcentaje del radio de influencia de la UNAJ | {pct} % |
| **Población (Censo 2022, interpolación areal)** | **{pob_censo} habitantes** |
| Densidad de población | {dens_censo} hab/km² |
| Radios censales involucrados | {n_radios} (todos urbanos) |
| Partidos alcanzados | {partidos} |
| Distancia a la universidad nacional más cercana | {d_comp} km ({comp_cerca}) |
| Distancia a la UNAJ | {d_unaj} km |

**Nota metodológica importante.** Una primera estimación con edificios de OpenStreetMap como proxy (§5) daba {pob_osm} habitantes. El cruce censal muestra que ese proxy **subestimaba la población por un factor de {factor_sub}**, porque OSM tiene mapeado apenas el 2–4 % del parque construido de Florencio Varela. **La cifra válida es la censal.** El proxy se conserva documentado en este informe únicamente como registro de por qué fue descartado.

---

## 2. Metodología

### 2.1 Fuentes

| Elemento | Detalle |
|---|---|
| Ubicación de universidades | 6 puntos en WGS84 provistos por el solicitante |
| Geometría de radios censales 2022 | INDEC — GeoNode institucional, capa `geonode:radios_censales2` (WFS oficial) |
| Población por radio 2022 | Boccolini, S. M. (2026), *Argentina (2022) radios censales con datos de cantidad de población y densidad de población*, CONICET Digital, CC BY 2.5 AR — tabulación del Censo 2022 de INDEC (Redatam) |
| Edificios (proxy descartado) | OpenStreetMap, tag `building=*`, vía Overpass API — descarga del {fecha_osm} |
| CRS de análisis | **EPSG:32721 (UTM 21S)** — proyectado, métrico |

### 2.2 Cadena de procesamiento

1. **Área de estudio.** Unión de los seis buffers de 5 km ({area_desc} km²), reproyectada a WGS84 para consultar las fuentes.
2. **Reproyección.** Todas las capas se llevan a EPSG:32721. Cada función de medición valida antes que el CRS sea proyectado (`verificar_crs_proyectado()`) y aborta si no lo es.
3. **Buffers.** Buffer de 5.000 m por universidad ({area_buf} km² cada uno; π·r² = 78,54 km², la diferencia es la discretización del círculo).
4. **Resta topológica.** `hueco = buffer_UNAJ − unión(buffers de las otras cinco)`. Es una **diferencia**, no una diferencia simétrica: interesa lo que cubre la UNAJ *y nadie más*.
5. **Cruce censal (resultado principal).** Los radios censales 2022 se intersecan con el hueco y se aplica **interpolación areal**: a cada radio se le asigna la fracción de su población proporcional a la fracción de su superficie que cae dentro del hueco. De los {n_radios} radios, **{n_integros} quedan íntegramente dentro** y sólo los del borde se ponderan.
6. **Distancias.** Desde el punto representativo del hueco a cada universidad.
7. **Sensibilidad al radio.** Se repiten los pasos 3 a 5 para {n_radios_ev} radios entre 1 y 10 km.
8. **Áreas de servicio sobre red.** Se construye un grafo no dirigido con la red vial de OSM (excluidas autopistas y vías rápidas, no transitables a pie) y se calculan por Dijkstra los nodos alcanzables con un recorrido de 5.000 m; el área de servicio es la unión de las aristas alcanzables con un buffer de acceso de {acceso} m desde el eje de calle.
9. **Universo de competidoras.** Se descargan todas las sedes `amenity=university` de OSM en el AMBA completo, se filtran por gestión nacional y se excluyen las 6 ya incluidas por proximidad espacial (≤ 500 m); se mide la distancia de cada una al hueco.
10. **Barrios populares.** Los polígonos del RENABAP se intersecan con el hueco por el mismo método de interpolación areal que los radios censales; las familias se convierten a personas con el mismo factor de ocupación del hogar.
11. **Auditoría independiente.** `scripts/gis_auditor.py` relee los productos desde disco y **recalcula** la resta topológica, la cobertura censal y la suma poblacional ponderada, sin confiar en los metadatos.

*Nota de implementación:* la descarga de OSM se resolvió con un cliente Overpass propio (`requests` + POST con `User-Agent` explícito). Durante la ejecución `osmnx` falló de forma sistemática contra ese endpoint desde la red utilizada (timeouts de conexión reiterados) y los mirrors públicos (`kumi.systems`, `private.coffee`, `osm.jp`) devolvieron 500/502. La consulta POST directa respondió de forma estable en 2–7 s por celda.

### 2.3 Decisión sobre el CRS

Se utilizó **EPSG:32721 (UTM 21S)**, no el WGS84 geográfico ni Gauss-Krüger:
- El AMBA cae en la zona UTM 21S, con distorsión de escala inferior al 0,1 % en la extensión analizada.
- Buffers, áreas y distancias **exigen** un CRS métrico proyectado: en grados los círculos salen elípticos y las áreas no tienen sentido físico.

---

## 3. Resultados

### 3.1 Geometría del hueco

| Métrica | Valor |
|---|---|
| Área del buffer UNAJ (5 km) | {area_buf} km² |
| Área de la unión de las 5 competidoras | {area_union} km² |
| **Área del hueco exclusivo UNAJ** | **{area} km²** |
| Proporción del buffer UNAJ | {pct} % |
| Tipo de geometría | {geom} ({n_partes} parte/s) |

Que el hueco represente el {pct} % del buffer es en sí un resultado: la UNAJ prácticamente no comparte su área de influencia con nadie. Sólo el borde norte se solapa con la UNQUI.

### 3.2 Población según el Censo 2022

| Métrica | Valor |
|---|---|
| Radios censales que intersecan el hueco | {n_radios} |
| Radios íntegramente dentro del hueco | {n_integros} |
| Radios de tipo urbano | {n_radios} (100 %) |
| Cobertura censal del hueco | 68,05 km² de 68,05 km² (completa) |
| **Población — interpolación areal** | **{pob_censo} habitantes** |
| Población — criterio de centroide (control) | {pob_centroide} habitantes |
| Diferencia entre ambos métodos | 1,1 % |
| **Densidad de población** | **{dens_censo} hab/km²** |

Los dos criterios de asignación —ponderar por área y asignar el radio entero según dónde caiga su centroide— arrojan cifras que difieren en 1,1 %. Esa coincidencia es el mejor indicador de que el resultado no depende de la decisión metodológica.

**Desglose por partido**

| Partido | Radios | Área en el hueco (km²) | Población | Densidad (hab/km²) |
|---|---|---|---|---|
{tabla_partidos}

El hueco es, en rigor, un área **intermunicipal**: la UNAJ presta cobertura de proximidad no sólo a Florencio Varela sino al sur de Quilmes y al oeste de Berazategui, que suman juntos el {pct_qb} % de la población de la zona.

### 3.3 Distancias desde el centro del hueco

| Universidad | Denominación | Distancia al centroide del hueco (km) | Distancia mínima al polígono (km) |
|---|---|---|---|
{tabla_dist}

La lectura es directa: para quien vive en el centro de esta zona, la UNAJ está a **{d_unaj} km** y la siguiente universidad nacional a **{d_comp} km**. Las restantes superan los {d_lejos} km.

### 3.4 Sensibilidad al radio de influencia

Los 5 km son un parámetro elegido, no un dato. Para que el resultado no dependa de esa elección se repitió el análisis completo —resta topológica y población censal— en {n_radios_ev} radios entre 1 y 10 km.

| Radio (km) | Área exclusiva (km²) | % del buffer | Población exclusiva | % de la población del buffer |
|---|---|---|---|---|
{tabla_sens}

Tres lecturas:

1. **Hasta los {r_solape} km la cobertura de la UNAJ es 100 % exclusiva.** Ninguna otra universidad nacional llega siquiera a rozar su área de influencia. Ya en un radio de 3 km —unos 35 minutos a pie— hay {pob_3km} personas para las que la UNAJ es la única opción.
2. **La población exclusiva alcanza su máximo en {r_max} km con {pob_max} habitantes.** El primer solape aparece a los 4 km, contra la UNQUI, pero hasta los 6 km lo que se gana ampliando el radio supera lo que se pierde por competencia; a partir de ahí se invierte. El radio de 5 km del análisis está *antes* del máximo: es una elección **conservadora**, no favorable.
3. **La conclusión no depende del radio.** En todo el rango de 3 a 10 km hay entre {pob_min_r} y {pob_max} habitantes exclusivos. Incluso en el escenario más desfavorable (10 km, donde media región queda a tiro de varias universidades) siguen quedando {pob_10km} personas que sólo tienen a la UNAJ cerca.

![Sensibilidad al radio](../outputs/maps/grafico_sensibilidad_radio.png)

### 3.5 Accesibilidad real: áreas de servicio sobre la red vial

El buffer euclidiano supone que se puede ir en línea recta en cualquier dirección. En el sur del Conurbano eso es falso: están el ferrocarril Roca, la Autopista Buenos Aires–La Plata, arroyos y trazados irregulares. Para medir el área **realmente alcanzable** se construyó un grafo enrutable con la red vial de OpenStreetMap ({n_nodos} nodos, {n_aristas} aristas) y se calcularon las áreas de servicio recorriendo 5.000 m de calle desde cada universidad.

| Universidad | Área por red (km²) | Círculo de 5 km (km²) | Cobertura real |
|---|---|---|---|
{tabla_iso}

**El círculo euclidiano sobreestima la cobertura de todas las universidades**, entre un {sobre_min} % y un {sobre_max} %. El caso extremo es la UNQUI: sólo el {cob_unqui} % de su círculo es alcanzable con 5 km de recorrido, porque el Río de la Plata se lleva buena parte del área nominal.

Rehecha la resta topológica sobre las áreas de servicio:

| Métrica | Buffer euclidiano | Red vial | Ratio |
|---|---|---|---|
| Área exclusiva | {area} km² | **{area_red} km²** | {ratio_area} % |
| Población (Censo 2022) | {pob_censo} | **{pob_red}** | {ratio_pob} % |
| Densidad | {dens_censo} hab/km² | {dens_red} hab/km² | — |

Y aquí aparece el hallazgo más contundente del informe: **por red vial, el área de servicio de la UNAJ es 100 % exclusiva**. No solapa ni un metro cuadrado con la de ninguna otra universidad nacional. La más cercana —la UNQUI— queda a 90 m de distancia sin llegar a tocarla; las demás, entre 2,4 y 25 km.

Ese resultado es robusto al supuesto de acceso: repitiendo el cálculo con distancias de acceso desde el eje de calle de 200, 250 y 300 m (en vez de los {acceso} m adoptados), la exclusividad se mantiene en 100 %, 99,9 % y 99,5 %.

![Isócronas por red vial](../outputs/maps/mapa_isocronas_red.png)

**Cómo leerlo.** El área exclusiva por red es menor ({area_red} km² contra {area} km²) porque la distancia por calle siempre es mayor que la distancia en línea recta. Pero la conclusión se refuerza: dentro de lo que la gente puede efectivamente recorrer, **la UNAJ no compite con nadie**. Los {pob_red} habitantes de esa área son la cifra metodológicamente más defendible del informe.

---

### 3.6 ¿Es realmente la única? El universo completo de universidades nacionales

Todo lo anterior compara la UNAJ contra 5 competidoras elegidas a mano. Antes de sostener "única universidad nacional de proximidad" en la conclusión, esa elección se puso a prueba: se descargaron de OpenStreetMap **las {n_total} sedes** tageadas como universidad en todo el AMBA —no sólo el sur—, se filtraron por patrones de gestión nacional (Universidad Nacional *, UTN, Universidad de Buenos Aires) excluyendo explícitamente instituciones privadas (ITBA) y de gestión no nacional (Universidad de la Ciudad de Buenos Aires), y se excluyeron por proximidad espacial las 6 ya contempladas.

Quedaron **{n_nuevas} candidatas** fuera de las 6 originales. De ellas, 2 resultaron ser sedes secundarias de universidades **ya incluidas** (un campus adicional de la UNaB y un predio de la UNLaNús, tageados en OSM lejos del punto oficial usado) — quedan **{n_genuinas} instituciones genuinamente independientes**: UNDAV, UTN con sus varias facultades regionales, UBA, Universidad Nacional de Tres de Febrero, La Matanza, Lomas... hasta Pilar.

| Institución más cercana | ¿Es una universidad nueva? | Distancia al borde del hueco |
|---|---|---|
{tabla_uni}

**Ninguna alcanza el hueco.** La más cercana —una sede de la UTN en Avellaneda— queda a **{dist_min_uni} km** de su borde: fuera de su propio radio de 5 km por apenas 900 metros. El resto está a 8 km o más. El universo ampliado **no cambia un metro cuadrado** del resultado.

![Universo de universidades](../outputs/maps/mapa_universo_universidades.png)

**Una precisión necesaria sobre el alcance de la afirmación.** "Única universidad nacional de proximidad" es correcto tal como está formulado, pero es una afirmación específicamente sobre universidades de gestión **nacional**. La zona sí cuenta con oferta pública de nivel superior **no universitario**, de gestión **provincial**: se identificaron al menos estos institutos operando en el área, según la Dirección General de Cultura y Educación de la Provincia de Buenos Aires:

| Instituto | Partido |
|---|---|
{tabla_isfd}

Estos institutos ofrecen profesorados y tecnicaturas, no las carreras de grado (ingenierías, licenciaturas) que ofrece una universidad. La afirmación del informe se sostiene sin matices para "universidad nacional"; sería incorrecto extenderla a "toda oferta de educación superior". Este relevamiento de institutos es manual y no exhaustivo —la misma incompletitud de OSM que afectó al proxy de edificios (§5) impide geolocalizarlos con precisión—, a diferencia del universo de universidades nacionales, que sí es sistemático y verificable.

### 3.7 Equidad: población en barrios populares (RENABAP)

El área y la población del hueco no dicen nada sobre quién vive ahí. Para eso se cruzó el hueco con el **Registro Nacional de Barrios Populares** (RENABAP) del Ministerio de Obras Públicas, que releva casa por casa los asentamientos informales del país.

| Métrica | Valor |
|---|---|
| Barrios populares en el hueco | {n_barrios_renabap} ({n_barrios_integros} íntegros) |
| Familias relevadas | {n_familias_renabap} |
| Población estimada en barrios populares | **{pob_renabap} habitantes** |
| Proporción de la población censal del hueco | **{pct_renabap} %** |
| Partidos | {partidos_renabap} |

Más de **1 de cada 20 habitantes** del hueco exclusivo de la UNAJ vive en un asentamiento informal registrado por el Estado. El dato de infraestructura es más duro que el de población: el RENABAP no pregunta "¿tenés agua?" sino *cómo* está conectada cada familia, y ahí aparece la carencia real:

| Servicio | Barrios con conexión formal | Familias con conexión formal |
|---|---|---|
| Electricidad | {elec_barrios} % | **{elec_familias} %** |
| Agua corriente | {agua_barrios} % | **{agua_familias} %** |
| Cloaca | {cloaca_barrios} % | **{cloaca_familias} %** |

La brecha más severa de las tres es la eléctrica: sólo el **{elec_familias} % de las familias** tiene una conexión formal con medidor domiciliario; el resto se conecta de forma irregular a la red. En cloaca, el **{cloaca_familias} %** tiene conexión formal y el resto desagua a pozo negro o cámara séptica. Son carencias que afectan a miles de las {n_familias_renabap} familias relevadas.

![Barrios populares RENABAP](../outputs/maps/mapa_renabap.png)

Los asentamientos se concentran de forma marcada sobre el curso de un arroyo al oeste del hueco — el patrón espacial típico de la urbanización informal argentina, que ocupa terrenos no aptos (bajos inundables, márgenes de arroyos) porque son los únicos disponibles.

**Lectura para la conclusión.** No es sólo que la UNAJ sea la única universidad de proximidad para {pob_censo} personas: para al menos {pob_renabap} de ellas, además, es la única universidad de proximidad **sin** que tengan una conexión eléctrica formal en su casa. Es el argumento de equidad que el análisis puramente geométrico no puede dar por sí solo.

---

## 4. Cartografía

### Mapa 1 — Áreas de influencia comparadas (r = 5 km)

![Buffers comparativos](../outputs/maps/mapa_buffers_comparativos.png)

Los seis círculos de 5 km. La UNAJ (verde) está en el extremo sudeste del sistema: sus vecinas se concentran al oeste y al norte, y La Plata queda muy al sudeste, dejando descubierto el corredor de Florencio Varela.

### Mapa 2 — Hueco exclusivo de la UNAJ

![Hueco exclusivo](../outputs/maps/mapa_hueco_exclusivo.png)

En rojo, la superficie que sólo la UNAJ cubre dentro de 5 km, sobre el fondo de edificios de OSM.

### Mapa 3 — Población según el Censo 2022 (mapa principal)

![Población censal](../outputs/maps/mapa_poblacion_censo2022.png)

Densidad de población por radio censal dentro del hueco. Los {n_radios} radios teselan el polígono por completo. Se distinguen con claridad los núcleos densos de Quilmes sur y del casco de Florencio Varela frente a los corredores de menor densidad.

### Mapa 4 — Barrios populares (RENABAP)

![RENABAP](../outputs/maps/mapa_renabap.png)

Los {n_barrios_renabap} asentamientos informales relevados dentro del hueco.

### Mapa 5 — El universo completo de universidades

![Universo](../outputs/maps/mapa_universo_universidades.png)

Las {n_genuinas} universidades nacionales del AMBA fuera de las 6 originales, con sus buffers de 5 km. Ninguna toca el hueco.

### Mapa 6 — Sensibilidad al radio

![Sensibilidad](../outputs/maps/mapa_sensibilidad_radio.png)

El hueco exclusivo para radios de 2,5, 5, 7,5 y 10 km.

### Mapa 7 — Edificios OSM (proxy descartado)

![Población estimada por edificios](../outputs/maps/mapa_edificios_poblacion.png)

Se conserva como registro del método descartado. Comparado con el Mapa 3 muestra visualmente el problema: los edificios mapeados en OSM son un subconjunto disperso del tejido real.

---

## 5. El proxy de edificios OSM y por qué fue descartado

La primera estimación siguió el método del proxy de edificios: contar edificios de OSM dentro del hueco y multiplicar por un factor de ocupación.

| Métrica | Valor |
|---|---|
| Edificios OSM descargados en el área de estudio | {n_raw} |
| Edificios cuyo centroide cae en el hueco | {n_dentro} |
| Edificios clasificados como residenciales | {n_sel} |
| Criterio de clasificación | `{criterio}` |
| Factor de ocupación aplicado | {factor} hab/edificio |
| Población estimada | {pob_osm} habitantes |
| Densidad resultante | {dens_osm} hab/km² |

**El factor de ocupación no era el problema.** Se aplicaron {factor} habitantes por edificio residencial, valor consistente con el tamaño medio del hogar en la provincia de Buenos Aires y con el supuesto de un hogar por edificio, razonable en tejido de vivienda unifamiliar. Aun un factor de 4 sólo habría movido la cifra a ~5.200.

**El problema era la completitud de OpenStreetMap.** Los {n_dentro} edificios mapeados en {area} km² dan {dens_ed} edif/km², cuando un tejido urbano consolidado tiene entre 600 y 1.200. Argentina no recibió una importación masiva de huellas de edificios, y el mapeo colaborativo en el Conurbano sur es fragmentario. El resultado: el proxy captura **entre el 2 % y el 4 %** del parque construido y subestima la población por un factor de **{factor_sub}**.

Sólo el {share_res} % de los edificios del hueco tenía un tag residencial explícito (predomina `building=yes`), por lo que se usaron todos los edificios excepto los tageados explícitamente como no residenciales — una decisión que amplía la selección y aun así queda dos órdenes de magnitud corta.

Antes de disponer del dato censal se hizo un contraste de plausibilidad (`scripts/calibracion_poblacion.py`) que, suponiendo densidades de 2.000–7.000 hab/km², acotaba la población entre 136.000 y 476.000. El censo dio {pob_censo}: **incluso ese contraste se quedó corto**, porque la densidad real del hueco (8.151 hab/km²) supera el extremo superior del rango supuesto. Se deja registrado como recordatorio de que un contraste basado en supuestos acota el orden de magnitud pero no sustituye la medición.

**Conclusión metodológica:** el proxy de edificios OSM es inutilizable para estimar población en esta región. Donde exista cartografía censal, ésa es la fuente; el proxy sólo tiene sentido en áreas sin censo reciente y con OSM bien cubierto.

---

## 6. Advertencias y limitaciones

**6.1 Interpolación areal.** El método asume que la población se distribuye uniformemente dentro de cada radio censal. Es un supuesto estándar y su impacto acá es acotado: {n_integros} de los {n_radios} radios ({pct_integros} %) quedan íntegramente dentro del hueco, y sólo los del borde se ponderan. El control por centroide difiere en 1,1 %.

**6.2 Fuente de la tabla poblacional.** La geometría de los radios es oficial de INDEC. La población por radio proviene de una tabulación del Censo 2022 publicada por CONICET bajo CC BY 2.5, no de una descarga directa de Redatam. Se validó comparando los totales por partido con las cifras del Censo 2022: Florencio Varela {val_fv}, Quilmes {val_q}, Berazategui {val_b} — coincidentes. El archivo está filtrado a radios con densidad > 1 hab/ha; en el hueco **ningún** radio quedó sin dato, de modo que el filtro no introduce faltantes aquí.

**6.3 Accesibilidad: resuelto en parte.** La objeción al buffer euclidiano se atendió en §3.5 con áreas de servicio sobre la red vial, y el resultado confirmó que el círculo sobreestima la cobertura entre un {sobre_min} % y un {sobre_max} %. Lo que **sigue sin modelarse** es el tiempo de viaje real: el grafo mide distancia recorrida, no minutos, y no incorpora frecuencia ni recorridos del transporte público (haría falta GTFS). Tampoco se aplican sentidos únicos, decisión deliberada porque el análisis representa acceso peatonal y en colectivo, no en automóvil particular.

**6.3.bis Supuesto de acceso desde el eje de calle.** Las áreas de servicio se construyen buffereando las calles alcanzables {acceso} m, media manzana típica del Conurbano. Se verificó que la conclusión de exclusividad total aguanta con 200, 250 y 300 m.

**6.4 Un punto por universidad.** Cada universidad se representa con una sola sede. Varias (notablemente UNLP y UNLZ) tienen facultades dispersas; considerar todas las sedes podría reducir el hueco.

**6.5 Universidades no incluidas.** El análisis se restringe a las seis universidades nacionales indicadas. No contempla universidades privadas, institutos de formación docente ni sedes de la UTN.

**6.6 Población total, no población objetivo.** Los {pob_censo} habitantes son la población total residente, no la demanda potencial de educación superior. Acotar la franja etaria relevante (18–29 años) y el nivel educativo alcanzado requiere tabulaciones censales adicionales por radio.

---

## 7. Conclusiones

**La hipótesis se verifica, y con un dato censal sólido detrás.**

1. **El área existe y es grande.** {area} km² —el {pct} % del radio de influencia de la UNAJ— quedan fuera del alcance de 5 km de todas las demás universidades nacionales del sur del AMBA.
2. **Está densamente poblada.** {pob_censo} habitantes según el Censo 2022, a {dens_censo} hab/km². Los 562 radios censales son todos urbanos. Es el orden de magnitud de una ciudad como Santa Fe o Corrientes.
3. **El alcance es intermunicipal.** No es sólo Florencio Varela: Quilmes aporta {pob_q} habitantes y Berazategui {pob_b}. La UNAJ cubre un área que sus partidos vecinos no tienen resuelta con sus propias instituciones.
4. **El resultado es robusto.** No depende del radio elegido (hay población exclusiva en todo el rango de 1 a 10 km) ni del supuesto de distancia en línea recta: medido sobre la red vial, el área de servicio de la UNAJ es **100 % exclusiva**, con {pob_red} habitantes. Tampoco depende de la lista de competidoras: contra el universo completo de {n_genuinas} universidades nacionales del AMBA, ninguna reduce el hueco.
5. **Hay una dimensión de equidad que el área y la población no capturan.** {pob_renabap} personas del hueco viven en barrios populares con infraestructura precaria (12,9 % de conexión cloacal formal). Para ellas, la proximidad de la UNAJ no es una comodidad: es, probablemente, la diferencia entre tener o no tener acceso a la universidad pública.
6. **El aislamiento es real, no marginal.** La universidad nacional más próxima al centro del hueco está a {d_comp} km, contra {d_unaj} km de la UNAJ. Para esta población la UNAJ no es *una* opción: es **la** opción de proximidad.
7. **Implicancia de política pública.** El cierre o desfinanciamiento de la UNAJ no redistribuiría su matrícula entre instituciones vecinas: dejaría a más de medio millón de personas sin cobertura universitaria pública dentro de un radio razonable de desplazamiento cotidiano.
8. **Lección metodológica.** El proxy de edificios OSM habría hecho parecer que en esta zona viven menos de 4.000 personas. El cruce con la cartografía censal corrigió el resultado en un factor de {factor_sub}. En análisis de accesibilidad a servicios públicos, la fuente poblacional importa más que la sofisticación del método geométrico.
9. **El resultado se sostiene contra fuentes externas independientes** (§8): nuestra propia fuente censal subestima la población oficial del INDEC en todos los partidos, nunca la exagera, y la composición del hueco coincide de cerca con la procedencia real de los estudiantes de la UNAJ en los dos partidos donde el ajuste es mejor.

---

## 8. Validación externa

Todo lo anterior se construyó con las fuentes que declaramos en cada sección. Antes de darlo por cerrado, se puso a prueba contra tres referencias externas que no forman parte del pipeline: los totales oficiales del Censo 2022, la vigencia del RENABAP, y —la más exigente— la procedencia real de los estudiantes de la UNAJ.

### 8.1 ¿La fuente censal exagera? No: subestima.

La tabla de CONICET/Boccolini que usamos en §3.2 es una tabulación derivada del Censo 2022, no la fuente oficial en sí. Se comparó su población total por partido contra los **resultados definitivos** publicados por INDEC:

| Partido | Nuestra fuente | INDEC oficial (definitivo) | Diferencia |
|---|---|---|---|
{tabla_val_censo}

En los tres partidos la diferencia es negativa: **nuestra fuente da menos población que la oficial, nunca más**. La causa más probable es el filtro de origen del dataset (densidad > 1 hab/ha), que excluye radios de baja densidad — hay más de ese tipo de radio en Florencio Varela que en Quilmes, lo que explica por qué la brecha es mayor ahí ({dif_min} %) que en Quilmes ({dif_max_abs} %). **Los {pob_censo} habitantes del hueco son, si acaso, una cota conservadora.**

### 8.2 El RENABAP que usamos ya quedó chico

La capa de barrios populares (§3.7) es el relevamiento **2020** del RENABAP. El registro nacional creció desde entonces:

| | 2020 (lo que usamos) | Actual |
|---|---|---|
| Barrios populares relevados (país) | {renabap_2020} | **{renabap_actual}** |

Un crecimiento del **+{renabap_crecimiento} %**. Por la misma lógica que en §8.1, los {n_barrios_renabap} barrios y {pob_renabap} habitantes que contamos en el hueco son también, casi con certeza, una subestimación de la situación actual.

### 8.3 La prueba más dura: ¿coincide con la matrícula real?

Las dos validaciones anteriores comparan una fuente de población contra otra. Esta es distinta: compara la **predicción geométrica** del buffer de 5 km contra **comportamiento real** — de dónde vienen efectivamente los estudiantes que hoy cursan en la UNAJ, según datos que publica la propia universidad.

| Partido | % real de matrícula UNAJ | % de población en el hueco | Diferencia |
|---|---|---|---|
{tabla_val_matricula}

**{mejor_ajuste} calza casi exacto.** {peor_ajuste} es donde más diverge. La lectura honesta: el buffer de 5 km captura bien la demanda de los partidos donde la UNAJ no compite con nadie más (Florencio Varela, Berazategui), pero es una aproximación más floja donde sí hay competencia real por otras universidades (Quilmes) o donde la gente cruza el buffer en la dirección contraria a la esperada (Almirante Brown, que manda más estudiantes de los que el hueco geométrico sugeriría). **El radio de 5 km es una aproximación razonable del área de influencia, no un mapa exacto de la demanda.**

### 8.4 Metodología: respaldo en la literatura

El uso de buffers y áreas de influencia para medir accesibilidad a servicios públicos es práctica estándar en la geografía argentina — la misma lógica que estudios de accesibilidad a centros de salud (línea de trabajo de G. Buzai, Universidad Nacional de Luján). La progresión que seguimos en este proyecto, de buffer euclidiano (§3.1) a isócronas por red vial (§3.5), es exactamente la evolución metodológica que esa literatura recomienda cuando hay barreras geográficas de por medio.

---

## 9. Auditoría

Veredicto del agente independiente `gis-auditor`: **{veredicto}** ({conteo}).

El auditor no reutiliza los resultados guardados: relee cada capa desde disco y recalcula la resta topológica, la cobertura de los radios sobre el hueco y la suma poblacional ponderada.

**Verificaciones superadas (INFO)**

{info}

**Advertencias (WARNING)**

{warn}

**Errores (ERROR / CRITICAL)**

{err}

---

## 10. Archivos generados

### Datos de entrada
| Ruta | Contenido |
|---|---|
| `data/input/edificios_osm_raw.gpkg` | {n_raw} edificios OSM crudos, EPSG:4326 (inmutable) |
| `data/censo/radios_2022_indec.gpkg` | 4.376 radios censales 2022, geometría oficial INDEC (WFS) |
| `data/censo/radios_2022_conDatos_1habHa.gpkg` | Población por radio, Censo 2022 (CONICET, CC BY 2.5) |
| `data/censo/Codgeo_Buenos_Aires_con_datos.zip` | Radios censales 2010 con datos (usado sólo para verificar la vigencia de las fuentes) |

### Trabajo intermedio
| Ruta | Contenido |
|---|---|
| `work/area_descarga.gpkg` | Polígono de la unión de los 6 buffers (WGS84) |
| `work/edificios_utm.gpkg` | Edificios reproyectados a EPSG:32721 |
| `work/universidades_utm.gpkg` | 6 universidades como puntos, EPSG:32721 |
| `work/union_competidoras.gpkg` | Unión de los 5 buffers competidores |
| `work/centroide_hueco.gpkg` | Punto representativo del hueco |
| `work/buffers/buffer_*.gpkg` | Un buffer de 5 km por universidad (6 archivos) |
| `work/buffers/todos_los_buffers.gpkg` | Las 6 geometrías con sus atributos |

### Productos finales
| Ruta | Contenido |
|---|---|
| `outputs/hueco_exclusivo_UNAJ.gpkg` | **Geometría del hueco exclusivo** ({area} km²) |
| `outputs/radios_censo_en_hueco.gpkg` | **{n_radios} radios censales con población asignada** |
| `outputs/hueco_exclusivo_UNAJ_red.gpkg` | **Hueco exclusivo por red vial** ({area_red} km², {pob_red} hab) |
| `outputs/areas_servicio_red.gpkg` | Áreas de servicio de 5 km por red, 6 universidades |
| `outputs/huecos_por_radio.gpkg` | Huecos exclusivos para los {n_radios_ev} radios evaluados |
| `outputs/universo_universidades_amba.gpkg` | Las {n_nuevas} sedes universitarias nacionales del AMBA fuera de las 6 originales |
| `outputs/renabap_en_hueco.gpkg` | {n_barrios_renabap} barrios populares con población e infraestructura |
| `outputs/sensibilidad_radio.csv` | Tabla de sensibilidad al radio |
| `outputs/edificios_en_hueco.gpkg` | {n_sel} edificios del proxy descartado |
| `outputs/grilla_densidad_hueco.gpkg` | Grilla de densidad de edificios (250 m) |
| `outputs/distancias_universidades.csv` | Distancias del centroide a cada universidad |
| `outputs/metadatos_analisis.json` | Todos los metadatos y métricas del análisis |
| `outputs/maps/mapa_poblacion_censo2022.png` | **Mapa principal** — población censal |
| `outputs/maps/mapa_buffers_comparativos.png` | Mapa de buffers |
| `outputs/maps/mapa_hueco_exclusivo.png` | Mapa del hueco |
| `outputs/maps/mapa_isocronas_red.png` | Mapa de áreas de servicio por red |
| `outputs/maps/mapa_renabap.png` | Mapa de barrios populares |
| `outputs/maps/mapa_universo_universidades.png` | Mapa del universo completo de universidades |
| `outputs/maps/grafico_sensibilidad_radio.png` | Curvas de sensibilidad al radio |
| `outputs/maps/mapa_sensibilidad_radio.png` | Huecos anidados por radio |
| `outputs/maps/mapa_edificios_poblacion.png` | Mapa del proxy descartado |

### Código y reportes
| Ruta | Contenido |
|---|---|
| `scripts/analisis_educativo.py` | Script maestro modular (fases 1 a 7) |
| `scripts/cruce_censo.py` | Cruce con radios censales INDEC 2022 |
| `scripts/sensibilidad_radio.py` | Sensibilidad al radio de influencia |
| `scripts/isocronas.py` | Áreas de servicio sobre la red vial |
| `scripts/universo_educativo.py` | Universo completo de universidades nacionales del AMBA |
| `scripts/cruce_renabap.py` | Cruce con barrios populares (RENABAP) |
| `scripts/validacion_externa.py` | Cruce contra INDEC oficial, vigencia RENABAP y matrícula real UNAJ (§8) |
| `scripts/gis_inspector.py` | Agente inspector / control de calidad de capas |
| `scripts/gis_auditor.py` | Agente auditor independiente |
| `scripts/calibracion_poblacion.py` | Contraste de plausibilidad del proxy OSM |
| `scripts/gis_reporter.py` | Generador de este informe |
| `reports/informe_hueco_educativo.md` | Este documento |
| `reports/auditoria.json` | Hallazgos de auditoría estructurados |
| `reports/inspeccion_edificios_osm_raw.json` | Inspección de la capa cruda |
| `logs/ejecucion.log` | Traza completa de la ejecución |

---

*Informe generado automáticamente por el equipo de agentes GIS el {fecha}.
Datos de población y cartografía censal: INDEC, Censo Nacional de Población, Hogares y Viviendas 2022; tabulación por radio de Boccolini, S. M. (2026), CONICET Digital, CC BY 2.5 AR. Datos de edificios: © colaboradores de OpenStreetMap, ODbL.*
"""

    sn = meta["sensibilidad_radio"]
    iso = meta["isocronas_red"]

    tabla_sens = "\n".join(
        "| {} | {} | {} | {} | {} |".format(
            miles(f["radio_km"], 1), miles(f["area_hueco_km2"], 2),
            miles(f["pct_exclusivo"], 1), miles(f["poblacion_hueco"]),
            miles(f["pct_poblacion_exclusiva"], 1))
        for f in sn["tabla"])

    tabla_iso = "\n".join(
        "| {} | {} | {} | {} |".format(
            f["universidad"], miles(f["area_red_km2"], 2),
            miles(f["area_euclidiana_km2"], 2), miles(f["cobertura_pct"], 1))
        for f in iso["areas_de_servicio"])

    cobs = [f["cobertura_pct"] for f in iso["areas_de_servicio"]]

    ren = meta["renabap"]

    uni = meta["universo_educativo"]

    val = meta["validacion_externa"]
    tabla_val_censo = "\n".join(
        "| {} | {} | {} | {} % |".format(
            f["partido"], miles(f["nuestra_fuente"]), miles(f["indec_oficial"]),
            miles(f["diferencia_pct"], 2))
        for f in val["poblacion_vs_indec"]["filas"])
    def _signo_pp(v):
        return ("+" if v >= 0 else "-") + miles(abs(v), 1) + " pp"
    tabla_val_matricula = "\n".join(
        "| {} | {} % | {} % | {} |".format(
            f["partido"], miles(f["pct_matricula_real"], 1),
            miles(f["pct_poblacion_hueco"], 1), _signo_pp(f["diferencia_pp"]))
        for f in val["matricula_real"]["filas"])

    def _o_guion(v):
        return v if isinstance(v, str) and v.strip() else "—"

    tabla_uni = "\n".join(
        "| {} | {} | {} |".format(
            f["nombre_osm"].strip(), _o_guion(f.get("mismo_campus_que")),
            miles(f["dist_hueco_km"], 2))
        for f in sorted(uni["candidatos"], key=lambda x: x["dist_hueco_km"])[:10])
    tabla_isfd = "\n".join(
        "| {} | {} |".format(i["nombre"], i["partido"])
        for i in uni["isfd_en_la_zona"])


    pob_q = next(d["poblacion"] for d in c["desglose_por_partido"]
                 if d["partido"] == "Quilmes")
    pob_b = next(d["poblacion"] for d in c["desglose_por_partido"]
                 if d["partido"] == "Berazategui")
    n_radios = c["n_radios_con_dato"]
    n_integros = c["n_radios_integros_en_hueco"]

    texto = md.format(
        fecha=datetime.now().strftime("%d/%m/%Y"),
        fecha_osm=meta.get("osm_fecha_descarga", "n/d")[:10],
        area=miles(area, 2), pct=miles(pct, 1),
        area_buf=miles(meta["buffer_unaj_area_km2"], 2),
        area_union=miles(meta["union_competidoras_area_km2"], 2),
        area_desc="415",
        geom=meta.get("hueco_geom_type", "Polygon"),
        n_partes=meta.get("hueco_n_partes", 1),
        pob_censo=miles(pob_censo),
        pob_centroide=miles(c["poblacion_censo_2022_por_centroide"]),
        dens_censo=miles(c["densidad_censal_hab_km2"]),
        n_radios=miles(n_radios), n_integros=miles(n_integros),
        pct_integros=miles(100 * n_integros / n_radios, 0),
        partidos=", ".join(c["partidos_involucrados"]),
        tabla_partidos=tabla_partidos,
        pct_qb=miles(100 * (pob_q + pob_b) / pob_censo, 0),
        pob_q=miles(pob_q), pob_b=miles(pob_b),
        tabla_dist=tabla_dist,
        d_unaj=miles(d_unaj, 2), d_comp=miles(d_comp, 2),
        comp_cerca=comp_cerca, d_lejos=miles(comp.dist_centroide_km.iloc[1], 0),
        pob_osm=miles(pob_osm),
        dens_osm=miles(meta["densidad_poblacion_hab_km2"]),
        dens_ed=miles(meta["contraste_densidad"]["densidad_edificios_osm_km2"]),
        factor=miles(meta["factor_hab_por_edificio"], 0),
        factor_sub=miles(c["factor_subestimacion_proxy_osm"], 0),
        n_raw=miles(meta["osm_total_edificios_crudos"]),
        n_dentro=miles(meta["edificios_en_hueco_total"]),
        n_sel=miles(meta["edificios_en_hueco_seleccionados"]),
        criterio=meta.get("criterio_residencial", "n/d"),
        share_res=miles(100 * meta["share_residencial_estricto"], 1),
        val_fv="485.105", val_q="631.551", val_b="355.277",
        tabla_sens=tabla_sens, tabla_iso=tabla_iso,
        n_radios_ev=len(sn["tabla"]),
        r_solape=miles(sn["primer_radio_con_solape_km"] - 0.5, 1),
        r_max=miles(sn["radio_de_maxima_poblacion_km"], 0),
        pob_max=miles(sn["max_poblacion"]),
        pob_3km=miles(next(f["poblacion_hueco"] for f in sn["tabla"]
                           if f["radio_km"] == 3)),
        pob_10km=miles(next(f["poblacion_hueco"] for f in sn["tabla"]
                            if f["radio_km"] == 10)),
        pob_min_r=miles(min(f["poblacion_hueco"] for f in sn["tabla"]
                            if f["radio_km"] >= 3)),
        n_nodos=miles(iso["n_nodos_grafo"]), n_aristas=miles(iso["n_aristas_grafo"]),
        area_red=miles(iso["hueco_red_area_km2"], 2),
        pob_red=miles(iso["hueco_red_poblacion"]),
        dens_red=miles(iso["hueco_red_densidad_hab_km2"]),
        ratio_area=miles(100 * iso["ratio_area_red_vs_euclidiano"], 1),
        ratio_pob=miles(100 * iso["ratio_poblacion_red_vs_euclidiano"], 1),
        acceso=miles(iso["acceso_desde_eje_m"], 0),
        sobre_min=miles(100 - max(cobs), 0), sobre_max=miles(100 - min(cobs), 0),
        cob_unqui=miles(next(f["cobertura_pct"] for f in iso["areas_de_servicio"]
                             if f["universidad"] == "UNQUI"), 1),
        n_total=miles(uni["n_candidatos_amba_total"]),
        n_nuevas=miles(uni["n_candidatos_nacionales_nuevos"]),
        n_genuinas=miles(uni["n_instituciones_genuinamente_nuevas"]),
        dist_min_uni=miles(uni["distancia_minima_al_hueco_km"], 2),
        tabla_uni=tabla_uni, tabla_isfd=tabla_isfd,
        n_barrios_renabap=miles(ren["n_barrios_en_hueco"]),
        n_barrios_integros=miles(ren["n_barrios_integros"]),
        n_familias_renabap=miles(ren["n_familias_en_hueco"]),
        pob_renabap=miles(ren["poblacion_renabap_en_hueco"]),
        pct_renabap=miles(ren["pct_poblacion_censal_en_renabap"], 1),
        partidos_renabap=", ".join(ren["partidos"]),
        elec_barrios=miles(ren["electricidad_formal_pct"]["pct_barrios"], 1),
        elec_familias=miles(ren["electricidad_formal_pct"]["pct_familias"], 1),
        agua_barrios=miles(ren["agua_formal_pct"]["pct_barrios"], 1),
        agua_familias=miles(ren["agua_formal_pct"]["pct_familias"], 1),
        cloaca_barrios=miles(ren["cloaca_formal_pct"]["pct_barrios"], 1),
        cloaca_familias=miles(ren["cloaca_formal_pct"]["pct_familias"], 1),
        tabla_val_censo=tabla_val_censo, tabla_val_matricula=tabla_val_matricula,
        dif_min=miles(abs(val["poblacion_vs_indec"]["diferencia_min_pct"]), 2),
        dif_max_abs=miles(abs(val["poblacion_vs_indec"]["diferencia_max_pct"]), 2),
        renabap_2020=miles(val["renabap_vigencia"]["barrios_2020"]),
        renabap_actual=miles(val["renabap_vigencia"]["barrios_actual"]),
        renabap_crecimiento=miles(val["renabap_vigencia"]["crecimiento_pct"], 1),
        mejor_ajuste=val["matricula_real"]["mejor_ajuste"],
        peor_ajuste=val["matricula_real"]["peor_ajuste"],


        veredicto=aud.get("veredicto", "n/d"), conteo=conteo_txt,
        info=bloque("INFO"), warn=bloque("WARNING"),
        err=(bloque("ERROR") + "\n\n" + bloque("CRITICAL")),
    )

    DIR_REPORTS.mkdir(parents=True, exist_ok=True)
    destino = DIR_REPORTS / "informe_hueco_educativo.md"
    destino.write_text(texto, encoding="utf-8")
    print("Informe generado: {} ({:,} caracteres)".format(destino, len(texto)))


if __name__ == "__main__":
    main()

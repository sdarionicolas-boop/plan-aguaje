# El Territorio de la UNAJ

Determina el área de cobertura de 5 km de la Universidad Nacional Arturo
Jauretche (UNAJ) que **ninguna** de las otras cinco universidades nacionales
del sur del AMBA (UNQUI, UNLP, UNLZ, UNaB, UNLaNús) alcanza, y estima cuánta
gente vive ahí a partir de los radios censales del Censo 2022 (INDEC).

Resultado principal: **68,05 km² exclusivos, 554.692 habitantes** (medido en
línea recta); **54,58 km², 444.604 habitantes y 100 % de exclusividad**
medido sobre la red vial real. El resultado se sostiene para radios de
influencia entre 3 y 10 km y contra el universo completo de universidades
nacionales del AMBA (ninguna de 25 instituciones adicionales alcanza el
hueco). Al menos 30.123 personas del hueco viven en barrios populares
(RENABAP), donde sólo el 5,9 % de las familias tiene conexión eléctrica
formal. Ver el informe completo en
[`reports/informe_hueco_educativo.md`](reports/informe_hueco_educativo.md).

## Requisitos

- Python 3.11+ (probado con 3.14.0)
- Conexión a internet (Overpass API, GeoNode de INDEC, CONICET Digital)

```bash
pip install -r requirements.txt
```

## Cómo correr el análisis completo

```bash
python run_all.py
```

Tarda entre 40 minutos y un par de horas la primera vez (la descarga de la
red vial y el cálculo de áreas de servicio por red son lo más lento). Las
corridas siguientes son mucho más rápidas porque casi todo se cachea en
disco — ver **Idempotencia** más abajo.

Para correr sólo una parte del pipeline (por ejemplo, si ya se descargó todo
y sólo se quiere regenerar el informe tras editar el texto):

```bash
python run_all.py --list      # ver las 14 fases disponibles
python run_all.py reporte     # corre solo la fase "reporte" hasta el final
python run_all.py censo       # corre desde "censo" hasta el final
```

## Idempotencia y caché

| Qué se cachea | Dónde | Se vuelve a descargar si... |
|---|---|---|
| Edificios OSM crudos | `data/input/edificios_osm_raw.gpkg` | se borra el archivo |
| Radios censales INDEC 2022 (geometría) | `data/censo/radios_2022_indec.gpkg` | se borra el archivo |
| Población por radio 2022 (CONICET) | `data/censo/radios_2022_conDatos_1habHa.gpkg` | se borra el archivo (~42 MB) |
| Red vial OSM + grafo | `work/red_vial_osm.pkl` | se borra el archivo |
| Universidades del AMBA (universo completo) | `data/censo/universidades_osm_amba.json` | se borra el archivo |
| Barrios populares (RENABAP) | `data/censo/renabap_amba.gpkg` | se borra el archivo |

`data/input/` es **inmutable** una vez completada la fase 1: ningún script
posterior escribe ahí. Es la regla que garantiza que el análisis siempre
pueda repetirse contra los mismos datos crudos.

## Estructura del proyecto

```
data/
  input/     Edificios OSM crudos, WGS84 (inmutable tras fase 1)
  censo/     Radios censales INDEC 2022 + población (CONICET), cacheados
work/
  buffers/   Buffer de 5 km por universidad
  *.gpkg     Capas intermedias reproyectadas a EPSG:32721
  *.pkl      Caché del grafo vial (isócronas)
  cache_osm/ Caché HTTP del cliente Overpass
outputs/
  *.gpkg, *.csv, *.json   Productos finales del análisis
  maps/                   Los 7 mapas y gráficos del proyecto
reports/
  informe_hueco_educativo.md   Informe final
  auditoria.json               Hallazgos de la auditoría independiente
  inspeccion_*.json            Reportes de calidad de capas
scripts/     Todo el código, modular por fase (ver tabla abajo)
logs/        Traza de ejecución
run_all.py   Orquestador: corre todas las fases en orden
```

## Fases del pipeline

| # | Módulo | Qué hace |
|---|---|---|
| 1 | `scripts/analisis_educativo.py::fase1_descarga` | Descarga edificios OSM del área de estudio (cliente Overpass propio) |
| — | `scripts/gis_inspector.py` | Inspección de calidad de la capa cruda (CRS, geometrías inválidas, nulos) |
| 2 | `fase2_preparacion` | Reproyección a EPSG:32721 (UTM 21S) |
| 3 | `fase3_buffers` | Buffer de 5 km para las 6 universidades |
| 4 | `fase4_hueco` | Resta topológica: `hueco = buffer_UNAJ − unión(buffers competidores)` |
| 5 | `fase5_cruce` | Cruce con edificios OSM como proxy poblacional (método descartado, ver informe §5) |
| 6 | `fase6_distancias` | Distancia del hueco a cada universidad |
| 7 | `generar_mapas` | Mapas 1–3 (buffers, hueco, proxy OSM) |
| — | `scripts/calibracion_poblacion.py` | Contraste de plausibilidad del proxy OSM contra densidades urbanas de referencia |
| — | `scripts/cruce_censo.py` | **Cruce con radios censales INDEC 2022 — resultado principal** |
| — | `scripts/sensibilidad_radio.py` | Repite el análisis para radios de 1 a 10 km |
| — | `scripts/isocronas.py` | Áreas de servicio de 5 km sobre la red vial real (no en línea recta) |
| — | `scripts/universo_educativo.py` | Universo completo de universidades nacionales del AMBA (no sólo las 5 competidoras elegidas) |
| — | `scripts/cruce_renabap.py` | Cruce con barrios populares (RENABAP): equidad, no sólo distancia |
| — | `scripts/validacion_externa.py` | Contraste contra INDEC oficial, vigencia del RENABAP y matrícula real de la UNAJ |
| — | `scripts/gis_auditor.py` | Auditoría independiente: relee todo desde disco y recalcula sin confiar en los metadatos |
| — | `scripts/gis_reporter.py` | Genera el informe final en Markdown |

## Fuentes de datos

- **Edificios**: OpenStreetMap © colaboradores, licencia ODbL, vía Overpass API.
- **Red vial**: OpenStreetMap © colaboradores, vía Overpass API.
- **Geometría de radios censales 2022**: INDEC, GeoNode institucional (WFS oficial).
- **Población por radio, Censo 2022**: Boccolini, S. M. (2026), *Argentina
  (2022) radios censales con datos de cantidad de población y densidad de
  población*, CONICET Digital, CC BY 2.5 AR — tabulación del Censo 2022 de
  INDEC vía Redatam.
- **Universo de universidades nacionales**: OpenStreetMap © colaboradores,
  vía Overpass API (`amenity=university` en todo el AMBA).
- **Institutos terciarios (ISFD) de la zona**: relevamiento manual desde el
  sitio de la Dirección General de Cultura y Educación de la Provincia de
  Buenos Aires (abc.gob.ar) — no georreferenciado, ver advertencia en el
  informe §3.6.
- **Barrios populares**: RENABAP / SISU, Ministerio de Obras Públicas,
  GeoServer institucional (WFS), capa `renabap2020_smz` (relevamiento 2020).

## Parámetros del análisis

Editables al inicio de `scripts/analisis_educativo.py`:

- `UNIVERSIDADES`: coordenadas WGS84 de las 6 universidades.
- `RADIO_M`: radio de influencia (5.000 m por defecto; ver
  `scripts/sensibilidad_radio.py` para el análisis de sensibilidad).
- `FACTOR_POBLACION`: habitantes por edificio del proxy OSM (no afecta al
  resultado principal, que usa datos censales).

## Advertencias metodológicas

El informe documenta en detalle por qué el proxy de edificios OSM (fase 5)
fue **descartado** en favor del cruce censal: OpenStreetMap tiene mapeado
apenas el 2–4 % del parque construido de Florencio Varela, y el proxy
subestimaba la población por un factor de ~143. Ver §5 del informe.

## Licencia

El código (`scripts/`, `run_all.py`, `webmap/build.py`, el JS del mapa
interactivo) está bajo licencia [MIT](LICENSE).

Los datos y capas derivadas conservan los términos de sus fuentes
originales (ver **Fuentes de datos** arriba):

- Las capas que incorporan geometría de OpenStreetMap (edificios, red vial,
  universo de universidades — presentes en `outputs/*.gpkg` y
  `webmap/*.json`) están sujetas a la [Open Database License
  (ODbL)](https://opendatacommons.org/licenses/odbl/) de OpenStreetMap
  Foundation: cualquier redistribución de esas capas (no del código) debe
  atribuir a los colaboradores de OSM y mantenerse share-alike bajo ODbL.
- La población por radio censal (Censo 2022) es CC BY 2.5 AR, tabulación de
  Boccolini (2026) vía CONICET Digital.
- La geometría de radios censales y los datos de RENABAP provienen de
  organismos públicos argentinos (INDEC, Ministerio de Obras Públicas) bajo
  sus respectivos términos de datos abiertos institucionales.

El informe (`reports/informe_hueco_educativo.md`) y los mapas estáticos
(`outputs/maps/`) pueden reutilizarse citando la fuente de este repositorio.

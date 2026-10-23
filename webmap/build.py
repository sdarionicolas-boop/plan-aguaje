# -*- coding: utf-8 -*-
"""Ensambla template.html + los *.json/leaflet en el artifact final."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT.parent / "hueco_educativo_mapa.html"

tpl = (ROOT / "template.html").read_text(encoding="utf-8")

def data(name):
    return (ROOT / f"{name}.json").read_text(encoding="utf-8")

repl = {
    "/*LEAFLET_CSS*/": (ROOT / "leaflet.css").read_text(encoding="utf-8"),
    "/*LEAFLET_JS*/": (ROOT / "leaflet.js").read_text(encoding="utf-8"),
    "/*DATA_HUECO*/": data("hueco"),
    "/*DATA_HUECO_RED*/": data("hueco_red"),
    "/*DATA_BUFFERS*/": data("buffers"),
    "/*DATA_UNIVERSIDADES*/": data("universidades"),
    "/*DATA_RADIOS*/": data("radios"),
    "/*DATA_RENABAP*/": data("renabap"),
    "/*DATA_UNIVERSO*/": data("universo"),
    "/*DATA_HUECOS_RADIO*/": data("huecos_radio"),
    "/*DATA_AREAS_SERVICIO_RED*/": data("areas_servicio_red"),
    "/*DATA_COSTA*/": data("costa"),
    "/*DATA_AGUA*/": data("agua"),
    "/*DATA_PARTIDOS*/": data("partidos"),
    "/*DATA_RED_VIAL_BASE*/": data("red_vial_base"),
    "/*DATA_SENSIBILIDAD*/": data("sensibilidad"),
}

for placeholder, content in repl.items():
    if placeholder not in tpl:
        raise SystemExit(f"Placeholder no encontrado: {placeholder}")
    tpl = tpl.replace(placeholder, content, 1)

remaining = [line for line in tpl.splitlines() if "/*DATA_" in line or "/*LEAFLET_" in line]
if remaining:
    raise SystemExit(f"Quedaron placeholders sin reemplazar: {remaining}")

OUT.write_text(tpl, encoding="utf-8")
raw = OUT.read_bytes()
n_replacement = raw.count(b"\xef\xbf\xbd")
print(f"OK -> {OUT} ({len(tpl):,} caracteres, {n_replacement} bytes U+FFFD)")

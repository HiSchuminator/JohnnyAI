#!/usr/bin/env python3
"""
Aktualisiert models.json (Liste der Ollama-Modelle, die der JohnnyAI-Leistungscheck zum Download vorschlagen darf).

Quelle: die Tag-Seiten der Ollama-Bibliothek (https://ollama.com/library/<familie>/tags). Es gibt dafuer keine offizielle
Schnittstelle, deshalb wird die Seite gelesen und streng geprueft. Nur Familien aus tools/families.json werden beruecksichtigt.

Sicherheitsnetz: Aendert Ollama die Seite und der Abruf liefert nichts Sinnvolles, bricht das Skript mit Fehler ab und
laesst models.json unveraendert (die GitHub-Action schlaegt dann fehl und schickt eine Benachrichtigung).

Aufruf:  python tools/update_models.py [--dry-run]
"""
import json
import re
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models.json"
FAMILIES = Path(__file__).resolve().parent / "families.json"

# Grenzen wie in JohnnyAI (Services/ModelCatalog.cs): sonst verwirft das Programm die ganze Datei.
MIN_GB, MAX_GB = 0.5, 80.0
MAX_GB_LISTED = 40.0      # darueber passt ohnehin keine Heim-Grafikkarte; haelt die Liste kurz
MAX_ENTRIES = 60
# Nur "familie:groesse" (z. B. qwen2.5:7b, gemma4:e2b). Keine Varianten wie -it-q4, -mlx, -cloud, -coding.
PLAIN_TAG = re.compile(r"^[a-z0-9][a-z0-9._-]{0,40}:(e?\d+(\.\d+)?[bm])$")
ROW = re.compile(r'<span class="group-hover:underline">([^<]+)</span>(.*?)(?=<span class="group-hover:underline">|$)', re.S)
SIZE = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*(GB|MB)")


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "JohnnyAI-ModelCatalog/1 (+https://github.com/HiSchuminator/JohnnyAI)"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def parse_tags(html: str) -> dict:
    """tag -> GB. Bei Groessenbereichen ('4.6GB - 7.5GB') zaehlt der kleinere Wert."""
    out = {}
    for tag, rest in ROW.findall(html):
        tag = tag.strip().lower()
        if not PLAIN_TAG.match(tag) or tag in out:
            continue
        m = SIZE.search(rest[:600])
        if not m:
            continue
        gb = float(m.group(1)) / (1024 if m.group(2) == "MB" else 1)
        out[tag] = round(gb, 1)
    return out


def main() -> int:
    dry = "--dry-run" in sys.argv
    families = json.loads(FAMILIES.read_text(encoding="utf-8"))["families"]
    old = json.loads(MODELS.read_text(encoding="utf-8"))
    old_map = {m["tag"]: m["gb"] for m in old["models"]}

    new_map = {}
    for fam in families:
        tags = parse_tags(fetch(f"https://ollama.com/library/{fam}/tags"))
        if not tags:
            print(f"FEHLER: keine Tags fuer Familie '{fam}' gelesen - Seitenaufbau geaendert? models.json bleibt unveraendert.")
            return 1
        for tag, gb in tags.items():
            if MIN_GB <= gb <= min(MAX_GB, MAX_GB_LISTED):
                new_map[tag] = gb
        print(f"{fam}: {len(tags)} Tags gelesen")

    if len(new_map) > MAX_ENTRIES or len(new_map) < max(3, len(old_map) // 2):
        print(f"FEHLER: unplausible Listenlaenge ({len(new_map)} statt bisher {len(old_map)}) - models.json bleibt unveraendert.")
        return 1

    models = [{"tag": t, "gb": g} for t, g in sorted(new_map.items(), key=lambda kv: -kv[1])]
    if new_map == old_map:
        print("Keine Aenderung.")
        return 0

    for t in sorted(set(new_map) - set(old_map)):
        print(f"  neu: {t} ({new_map[t]} GB)")
    for t in sorted(set(old_map) - set(new_map)):
        print(f"  entfernt: {t}")
    for t in sorted(set(new_map) & set(old_map)):
        if new_map[t] != old_map[t]:
            print(f"  Groesse geaendert: {t} {old_map[t]} -> {new_map[t]} GB")

    if dry:
        print("(Trockenlauf, nichts geschrieben)")
        return 0
    doc = {"version": 1, "updated": datetime.now(timezone.utc).strftime("%Y-%m-%d"), "models": models}
    lines = ['{', '  "version": 1,', f'  "updated": "{doc["updated"]}",', '  "models": [']
    lines += [f'    {{ "tag": "{m["tag"]}", "gb": {m["gb"]} }}' + ("," if i < len(models) - 1 else "") for i, m in enumerate(models)]
    lines += ['  ]', '}', '']
    MODELS.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    print(f"models.json aktualisiert ({len(models)} Eintraege).")
    return 0


if __name__ == "__main__":
    sys.exit(main())

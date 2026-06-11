# -*- coding: utf-8 -*-
"""
Lee los resultados que el usuario carga a mano en la planilla de Google,
y los convierte en frecuencias de marcador para alimentar el modelo.

Planilla (pestaña 1): Fecha | Equipo 1 | Equipo 2 | Goles 1 | Goles 2

Credenciales por env var GCP_SA_JSON (igual que el bot de billboard).
Si no estan configuradas, degrada con gracia (devuelve vacio).
"""

import os
import json
import time

GSHEET_ID = os.getenv("GSHEET_ID", "")

_cache = {"t": 0, "rows": None}
_CACHE_SEG = 60


def _abrir():
    raw = os.getenv("GCP_SA_JSON")
    if not raw or not GSHEET_ID:
        return None
    try:
        import gspread
        info = json.loads(raw)
        pk = info.get("private_key", "")
        if "\\n" in pk and "\n" not in pk:
            info["private_key"] = pk.replace("\\n", "\n")
        gc = gspread.service_account_from_dict(info)
        return gc.open_by_key(GSHEET_ID).sheet1
    except Exception as e:
        print(f"[ERROR sheets] {e}")
        return None


def leer_resultados():
    """Devuelve lista de {fecha, equipo1, equipo2, g1, g2} con resultado completo."""
    # cache para no pegarle a la API en cada prediccion
    if _cache["rows"] is not None and (time.time() - _cache["t"]) < _CACHE_SEG:
        return _cache["rows"]

    ws = _abrir()
    if ws is None:
        return []

    out = []
    try:
        registros = ws.get_all_records()  # usa fila 1 como headers
    except Exception as e:
        print(f"[ERROR sheets read] {e}")
        return []

    for r in registros:
        g1 = str(r.get("Goles 1", "")).strip()
        g2 = str(r.get("Goles 2", "")).strip()
        if g1 == "" or g2 == "":
            continue
        try:
            g1, g2 = int(g1), int(g2)
        except ValueError:
            continue
        out.append({
            "fecha": str(r.get("Fecha", "")),
            "equipo1": str(r.get("Equipo 1", "")).strip(),
            "equipo2": str(r.get("Equipo 2", "")).strip(),
            "g1": g1, "g2": g2,
        })

    _cache["rows"] = out
    _cache["t"] = time.time()
    return out


def prior_extra():
    """
    Frecuencias de marcador (forma ordenada ganador-perdedor) de los
    resultados cargados a mano. Para sumar al prior del modelo.
    """
    extra_nodraw, extra_draw = {}, {}
    for r in leer_resultados():
        hi, lo = max(r["g1"], r["g2"]), min(r["g1"], r["g2"])
        if hi == lo:
            extra_draw[(hi, lo)] = extra_draw.get((hi, lo), 0) + 1
        else:
            extra_nodraw[(hi, lo)] = extra_nodraw.get((hi, lo), 0) + 1
    return extra_nodraw, extra_draw


def registrar_prediccion(equipo1, equipo2, pred_g1, pred_g2):
    """Escribe la prediccion top-1 en las columnas Pred 1 / Pred 2 del partido."""
    ws = _abrir()
    if ws is None:
        return
    try:
        registros = ws.get_all_records()
        for i, r in enumerate(registros, start=2):  # fila 2 en adelante
            e1 = str(r.get("Equipo 1", "")).strip().lower()
            e2 = str(r.get("Equipo 2", "")).strip().lower()
            if e1 == equipo1.strip().lower() and e2 == equipo2.strip().lower():
                ws.update(values=[[pred_g1, pred_g2]], range_name=f"F{i}:G{i}")
                print(f"[Sheets] Prediccion {pred_g1}-{pred_g2} guardada para {equipo1} vs {equipo2}")
                _cache["rows"] = None  # invalidar cache
                return
        print(f"[Sheets] No encontre la fila de {equipo1} vs {equipo2}")
    except Exception as e:
        print(f"[ERROR sheets pred] {e}")


def disponible():
    """True si las credenciales y la planilla estan configuradas."""
    return bool(os.getenv("GCP_SA_JSON") and GSHEET_ID)

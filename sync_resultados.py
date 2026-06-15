# -*- coding: utf-8 -*-
"""
Sincroniza resultados finales de partidos desde football-data.org
a la planilla de Google Sheets (columnas Goles 1 / Goles 2).

Solo escribe cuando el partido esta FINISHED y la fila no tiene resultado.
Respeta el header Retry-After para no exceder el rate limit (10 llamadas/min).
"""

import os
import time
import requests

FDORG_TOKEN  = os.getenv("FDORG_TOKEN", "")
FDORG_BASE   = "https://api.football-data.org/v4"
_ultimo_sync = {"t": 0}
_SYNC_INTERVALO = 900  # cada 15 minutos en el monitor automatico

# Mapeo de nombres API -> nombre normalizado (igual que en la planilla)
NOMBRE_MAP = {
    "côte d'ivoire":       "ivory coast",
    "cote d'ivoire":       "ivory coast",
    "cote divoire":        "ivory coast",
    "ir iran":             "iran",
    "usa":                 "united states",
    "united states of america": "united states",
    "republic of ireland": "ireland",
    "china pr":            "china",
    "korea republic":      "south korea",
    "dpr korea":           "north korea",
}

def normalizar(nombre):
    n = nombre.lower().strip()
    return NOMBRE_MAP.get(n, n)


def _get(path, params=None):
    """Llama a football-data.org respetando rate limit via Retry-After."""
    headers = {"X-Auth-Token": FDORG_TOKEN}
    r = requests.get(f"{FDORG_BASE}{path}", headers=headers, params=params, timeout=10)
    if r.status_code == 429:
        retry = int(r.headers.get("Retry-After", 60))
        print(f"[sync] Rate limit — esperando {retry}s")
        time.sleep(retry)
        r = requests.get(f"{FDORG_BASE}{path}", headers=headers, params=params, timeout=10)
    return r


def sincronizar(ws, forzar=False):
    """Recibe el worksheet de gspread y actualiza los resultados finales."""
    if not forzar and time.time() - _ultimo_sync["t"] < _SYNC_INTERVALO:
        return 0

    token = FDORG_TOKEN or os.getenv("FDORG_TOKEN", "")
    if not token:
        print("[sync] Sin FDORG_TOKEN configurado")
        return 0

    try:
        r = _get("/competitions/WC/matches", params={"status": "FINISHED"})
        if r.status_code != 200:
            print(f"[sync] API error {r.status_code}: {r.text[:200]}")
            return 0
        data = r.json()
        matches = data.get("matches", [])
    except Exception as e:
        print(f"[sync] Error API: {e}")
        return 0

    # Construir dict de resultados: (home_norm, away_norm) -> (goles1, goles2)
    resultados_api = {}
    for m in matches:
        if m.get("status") != "FINISHED":
            continue
        score = m.get("score", {})
        ft = score.get("fullTime", {})
        home_goals = ft.get("home")
        away_goals = ft.get("away")
        if home_goals is None or away_goals is None:
            continue
        home = normalizar(m["homeTeam"]["name"])
        away = normalizar(m["awayTeam"]["name"])
        resultados_api[(home, away)] = (int(home_goals), int(away_goals))

    try:
        registros = ws.get_all_records(expected_headers=[])
    except Exception as e:
        print(f"[sync] Error sheets: {e}")
        return 0

    actualizados = 0
    for i, row in enumerate(registros, start=2):
        g1 = str(row.get("Goles 1", "")).strip()
        g2 = str(row.get("Goles 2", "")).strip()
        if g1 != "" and g2 != "":
            continue  # ya tiene resultado

        e1 = normalizar(str(row.get("Equipo 1", "")))
        e2 = normalizar(str(row.get("Equipo 2", "")))
        resultado = resultados_api.get((e1, e2))
        if not resultado:
            continue

        goles1, goles2 = resultado
        try:
            ws.update(values=[[goles1, goles2]], range_name=f"D{i}:E{i}")
            print(f"[sync] {row['Equipo 1']} {goles1}-{goles2} {row['Equipo 2']}")
            actualizados += 1
        except Exception as e:
            print(f"[sync] Error escribiendo fila {i}: {e}")

    _ultimo_sync["t"] = time.time()
    if actualizados:
        print(f"[sync] {actualizados} resultado(s) nuevos sincronizados")
    return actualizados

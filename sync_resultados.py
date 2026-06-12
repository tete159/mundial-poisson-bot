# -*- coding: utf-8 -*-
"""
Sincroniza resultados finales de partidos desde the-odds-api
a la planilla de Google Sheets (columnas Goles 1 / Goles 2).

Solo escribe cuando completed=True y la fila todavia no tiene resultado.
"""

import os
import json
import requests
import time

ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
_ultimo_sync = {"t": 0}
_SYNC_INTERVALO = 1800  # cada 30 minutos


def sincronizar(ws):
    """Recibe el worksheet de gspread y actualiza los resultados finales."""
    if time.time() - _ultimo_sync["t"] < _SYNC_INTERVALO:
        return 0

    try:
        r = requests.get(
            "https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup/scores",
            params={"apiKey": ODDS_API_KEY, "daysFrom": 3},
            timeout=10
        )
        if r.status_code != 200:
            print(f"[sync] API error {r.status_code}")
            return 0
        partidos_api = {
            (m["home_team"].lower(), m["away_team"].lower()): m
            for m in r.json()
            if m.get("completed") and m.get("scores")
        }
    except Exception as e:
        print(f"[sync] Error API: {e}")
        return 0

    try:
        registros = ws.get_all_records()
    except Exception as e:
        print(f"[sync] Error sheets: {e}")
        return 0

    actualizados = 0
    for i, row in enumerate(registros, start=2):
        g1 = str(row.get("Goles 1", "")).strip()
        g2 = str(row.get("Goles 2", "")).strip()
        if g1 != "" and g2 != "":
            continue  # ya tiene resultado

        e1 = str(row.get("Equipo 1", "")).strip().lower()
        e2 = str(row.get("Equipo 2", "")).strip().lower()
        partido = partidos_api.get((e1, e2))
        if not partido:
            continue

        scores = {s["name"].lower(): int(s["score"]) for s in partido["scores"]}
        goles1 = scores.get(e1)
        goles2 = scores.get(e2)
        if goles1 is None or goles2 is None:
            continue

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

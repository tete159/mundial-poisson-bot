# -*- coding: utf-8 -*-
"""
Historial de predicciones y resultados reales.

- Guarda cada prediccion que hace el bot.
- Cuando el usuario carga el resultado real, lo registra y mide el acierto.
- Expone prior_extra(): los resultados reales cargados, en forma de frecuencias
  de marcador, para SUMARLOS al prior del modelo (asi cada partido jugado
  mejora las predicciones futuras).

Persistencia: archivo JSON en /data (volumen de Railway) si existe,
sino en la carpeta local (para pruebas).
"""

import os
import json
import threading
import uuid
from datetime import datetime, timedelta
from pytz import timezone

ART = timezone("America/Argentina/Buenos_Aires")

# Carpeta persistente: /data en Railway (volumen), local si no existe
_DATA_DIR = "/data" if os.path.isdir("/data") else os.path.dirname(os.path.abspath(__file__))
_PATH = os.path.join(_DATA_DIR, "historial.json")

_lock = threading.Lock()

# Horas despues del inicio para considerar el partido terminado y preguntar
HORAS_PARA_PREGUNTAR = 2.5


def _load():
    if not os.path.exists(_PATH):
        return {"predicciones": []}
    try:
        with open(_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"predicciones": []}


def _save(data):
    tmp = _PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _PATH)


def registrar_prediccion(equipo1, equipo2, ranking, fecha_partido=None):
    """Guarda una prediccion. ranking = [(marcador, prob), ...]. Devuelve id."""
    if fecha_partido is None:
        fecha_partido = datetime.now(ART)
    pid = uuid.uuid4().hex[:8]
    with _lock:
        data = _load()
        data["predicciones"].append({
            "id": pid,
            "fecha_partido": fecha_partido.isoformat(),
            "equipo1": equipo1,
            "equipo2": equipo2,
            "top3": [s for s, _ in ranking[:3]],
            "top1": ranking[0][0],
            "resultado": None,        # "2-1" cuando se cargue
            "preguntado": False,      # si ya se pregunto por Telegram
        })
        _save(data)
    return pid


def marcar_preguntado(pid):
    with _lock:
        data = _load()
        for p in data["predicciones"]:
            if p["id"] == pid:
                p["preguntado"] = True
        _save(data)


def pendientes_para_preguntar():
    """Predicciones cuyo partido ya termino, sin resultado y sin preguntar aun."""
    ahora = datetime.now(ART)
    out = []
    with _lock:
        data = _load()
        for p in data["predicciones"]:
            if p["resultado"] is not None or p["preguntado"]:
                continue
            try:
                fp = datetime.fromisoformat(p["fecha_partido"])
            except Exception:
                continue
            if ahora >= fp + timedelta(hours=HORAS_PARA_PREGUNTAR):
                out.append(dict(p))
    return out


def registrar_resultado(pid, goles1, goles2):
    """Carga el resultado real de una prediccion. Devuelve el registro actualizado."""
    real = f"{goles1}-{goles2}"
    with _lock:
        data = _load()
        encontrado = None
        for p in data["predicciones"]:
            if p["id"] == pid:
                p["resultado"] = real
                p["preguntado"] = True
                encontrado = dict(p)
        _save(data)
    return encontrado


def registrar_resultado_por_equipos(equipo1, equipo2, goles1, goles2):
    """Carga resultado buscando por nombres (para el partido pendiente mas reciente)."""
    real = f"{goles1}-{goles2}"
    with _lock:
        data = _load()
        encontrado = None
        for p in reversed(data["predicciones"]):
            if (p["equipo1"].lower() == equipo1.lower()
                    and p["equipo2"].lower() == equipo2.lower()
                    and p["resultado"] is None):
                p["resultado"] = real
                p["preguntado"] = True
                encontrado = dict(p)
                break
        _save(data)
    return encontrado


def stats():
    """Estadisticas globales de acierto."""
    with _lock:
        data = _load()
    con_res = [p for p in data["predicciones"] if p["resultado"]]
    total = len(con_res)
    if total == 0:
        return {"total": 0, "top1": 0, "top3": 0, "pct_top1": 0.0, "pct_top3": 0.0}
    top1 = sum(1 for p in con_res if p["resultado"] == p["top1"])
    top3 = sum(1 for p in con_res if p["resultado"] in p["top3"])
    return {
        "total": total,
        "top1": top1,
        "top3": top3,
        "pct_top1": 100 * top1 / total,
        "pct_top3": 100 * top3 / total,
    }


def ultimos(n=10):
    """Ultimos n partidos con resultado, para mostrar."""
    with _lock:
        data = _load()
    con_res = [p for p in data["predicciones"] if p["resultado"]]
    return con_res[-n:]


def prior_extra():
    """
    Devuelve (extra_nodraw, extra_draw): frecuencias de marcador de los
    resultados REALES cargados, en forma ordenada ganador-perdedor.
    Se suman al prior historico del modelo para que aprenda de lo ya jugado.
    """
    extra_nodraw, extra_draw = {}, {}
    with _lock:
        data = _load()
    for p in data["predicciones"]:
        if not p["resultado"]:
            continue
        try:
            a, b = p["resultado"].split("-")
            a, b = int(a), int(b)
        except Exception:
            continue
        hi, lo = max(a, b), min(a, b)
        if hi == lo:
            extra_draw[(hi, lo)] = extra_draw.get((hi, lo), 0) + 1
        else:
            extra_nodraw[(hi, lo)] = extra_nodraw.get((hi, lo), 0) + 1
    return extra_nodraw, extra_draw

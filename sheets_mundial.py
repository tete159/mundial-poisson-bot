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
        registros = ws.get_all_records(expected_headers=[])
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


def leer_resultados_con_pred():
    """Devuelve partidos que tienen resultado real Y prediccion cargada."""
    ws = _abrir()
    if ws is None:
        return []
    try:
        registros = ws.get_all_records(expected_headers=[])
    except Exception as e:
        print(f"[ERROR sheets read] {e}")
        return []

    out = []
    for r in registros:
        g1  = str(r.get("Goles 1", "")).strip()
        g2  = str(r.get("Goles 2", "")).strip()
        p1  = str(r.get("Pred 1", "")).strip()
        p2  = str(r.get("Pred 2", "")).strip()
        if not all([g1, g2, p1, p2]):
            continue
        try:
            out.append({
                "fecha":   str(r.get("Fecha", "")),
                "equipo1": str(r.get("Equipo 1", "")).strip(),
                "equipo2": str(r.get("Equipo 2", "")).strip(),
                "g1": int(g1), "g2": int(g2),
                "pred_g1": int(float(p1)), "pred_g2": int(float(p2)),
            })
        except ValueError:
            continue
    return out


def registrar_prediccion(equipo1, equipo2, pred_g1, pred_g2, pts_lider=None):
    """Escribe la prediccion top-1 en F/G y opcionalmente pts del lider en I."""
    ws = _abrir()
    if ws is None:
        return
    try:
        registros = ws.get_all_records(expected_headers=[])
        for i, r in enumerate(registros, start=2):
            e1 = str(r.get("Equipo 1", "")).strip().lower()
            e2 = str(r.get("Equipo 2", "")).strip().lower()
            if e1 == equipo1.strip().lower() and e2 == equipo2.strip().lower():
                ws.update(values=[[pred_g1, pred_g2]], range_name=f"F{i}:G{i}")
                if pts_lider is not None:
                    ws.update(values=[[pts_lider]], range_name=f"I{i}")
                print(f"[Sheets] Prediccion {pred_g1}-{pred_g2} guardada para {equipo1} vs {equipo2}")
                _cache["rows"] = None
                return
        print(f"[Sheets] No encontre la fila de {equipo1} vs {equipo2}")
    except Exception as e:
        print(f"[ERROR sheets pred] {e}")


def registrar_pts_lider(equipo1, equipo2, pts_lider):
    """Escribe solo pts_lider en columna I para el partido dado."""
    ws = _abrir()
    if ws is None:
        return
    try:
        registros = ws.get_all_records(expected_headers=[])
        for i, r in enumerate(registros, start=2):
            e1 = str(r.get("Equipo 1", "")).strip().lower()
            e2 = str(r.get("Equipo 2", "")).strip().lower()
            if e1 == equipo1.strip().lower() and e2 == equipo2.strip().lower():
                ws.update(values=[[pts_lider]], range_name=f"I{i}")
                print(f"[Sheets] pts_lider={pts_lider} guardado en {equipo1} vs {equipo2}")
                return
    except Exception as e:
        print(f"[ERROR sheets pts_lider] {e}")


def registrar_pts_lider_fila_anterior(equipo_actual1, equipo_actual2, pts_lider):
    """Escribe pts_lider en la fila JUSTO ARRIBA del partido actual.
    El pts del lider al momento de predecir el partido N corresponde al
    acumulado hasta el partido N-1, que en la planilla es la fila de arriba."""
    ws = _abrir()
    if ws is None:
        return
    try:
        registros = ws.get_all_records(expected_headers=[])
        for i, r in enumerate(registros, start=2):
            e1 = str(r.get("Equipo 1", "")).strip().lower()
            e2 = str(r.get("Equipo 2", "")).strip().lower()
            if e1 == equipo_actual1.strip().lower() and e2 == equipo_actual2.strip().lower():
                if i > 2:  # fila 2 = primer partido; si i>2 hay una fila de datos arriba
                    ws.update(values=[[pts_lider]], range_name=f"I{i-1}")
                    print(f"[Sheets] pts_lider={pts_lider} guardado en fila {i-1} (arriba de {equipo_actual1} vs {equipo_actual2})")
                else:
                    print("[Sheets] El partido actual es el primero, no hay fila anterior")
                return
        print(f"[Sheets] No encontre la fila de {equipo_actual1} vs {equipo_actual2}")
    except Exception as e:
        print(f"[ERROR sheets pts_lider anterior] {e}")


def leer_historial_con_lider():
    """Devuelve filas con resultado real, prediccion Y puntos del lider (col I)."""
    ws = _abrir()
    if ws is None:
        return []
    try:
        registros = ws.get_all_records(expected_headers=[])
        col_i = ws.col_values(9)  # columna I (1-indexed)
    except Exception as e:
        print(f"[ERROR sheets historial] {e}")
        return []

    out = []
    for idx, r in enumerate(registros):
        g1 = str(r.get("Goles 1", "")).strip()
        g2 = str(r.get("Goles 2", "")).strip()
        p1 = str(r.get("Pred 1", "")).strip()
        p2 = str(r.get("Pred 2", "")).strip()
        if not all([g1, g2, p1, p2]):
            continue
        try:
            fila_i = col_i[idx + 1] if idx + 1 < len(col_i) else ""
            pts_lider = int(float(fila_i)) if fila_i else None
            out.append({
                "fecha":    str(r.get("Fecha", "")),
                "equipo1":  str(r.get("Equipo 1", "")).strip(),
                "equipo2":  str(r.get("Equipo 2", "")).strip(),
                "g1": int(g1), "g2": int(g2),
                "pred_g1": int(float(p1)), "pred_g2": int(float(p2)),
                "pts_lider": pts_lider,
            })
        except ValueError:
            continue
    return out


def registrar_cuotas(equipo1, equipo2, o1, ox, o2, over, under, btts_si, btts_no):
    """Guarda las 7 cuotas de entrada en columnas O..U, para backtest real.
    Sin las cuotas no se puede recalibrar RHO/W_HIST honestamente."""
    ws = _abrir()
    if ws is None:
        return
    try:
        registros = ws.get_all_records(expected_headers=[])
        # asegurar encabezados de columnas O..U (fila 1) una sola vez
        header = ws.row_values(1)
        if len(header) < 21 or str(header[14:21]) != "['O1', 'OX', 'O2', 'Over', 'Under', 'BTTS Si', 'BTTS No']":
            try:
                ws.update(values=[["O1", "OX", "O2", "Over", "Under", "BTTS Si", "BTTS No"]],
                          range_name="O1:U1")
            except Exception:
                pass
        for i, r in enumerate(registros, start=2):
            e1 = str(r.get("Equipo 1", "")).strip().lower()
            e2 = str(r.get("Equipo 2", "")).strip().lower()
            if e1 == equipo1.strip().lower() and e2 == equipo2.strip().lower():
                fila = [v if v is not None else "" for v in (o1, ox, o2, over, under, btts_si, btts_no)]
                ws.update(values=[fila], range_name=f"O{i}:U{i}")
                print(f"[Sheets] Cuotas guardadas para {equipo1} vs {equipo2}")
                return
    except Exception as e:
        print(f"[ERROR sheets cuotas] {e}")


def registrar_pick_bot(equipo1, equipo2, pick_str):
    """Guarda la recomendacion del bot en columna N, para comparar despues
    contra lo que el usuario realmente jugo (F/G)."""
    ws = _abrir()
    if ws is None:
        return
    try:
        registros = ws.get_all_records(expected_headers=[])
        for i, r in enumerate(registros, start=2):
            e1 = str(r.get("Equipo 1", "")).strip().lower()
            e2 = str(r.get("Equipo 2", "")).strip().lower()
            if e1 == equipo1.strip().lower() and e2 == equipo2.strip().lower():
                ws.update(values=[[pick_str]], range_name=f"N{i}")
                return
    except Exception as e:
        print(f"[ERROR sheets pick_bot] {e}")


def registrar_ganador_penales(equipo1, equipo2, ganador):
    """Guarda el equipo elegido como ganador por penales en columna AA (mata-mata).
    Solo aplica a empates de fase eliminatoria (suma +5 en el Prode si acierta).
    (V-Z las usa el usuario para sus propias notas; por eso va en AA.)"""
    ws = _abrir()
    if ws is None:
        return
    try:
        registros = ws.get_all_records(expected_headers=[])
        # asegurar encabezado de columna AA una sola vez
        header = ws.row_values(1)
        if len(header) < 27 or str(header[26:27]) != "['Ganador penales']":
            try:
                ws.update(values=[["Ganador penales"]], range_name="AA1")
            except Exception:
                pass
        for i, r in enumerate(registros, start=2):
            e1 = str(r.get("Equipo 1", "")).strip().lower()
            e2 = str(r.get("Equipo 2", "")).strip().lower()
            if e1 == equipo1.strip().lower() and e2 == equipo2.strip().lower():
                ws.update(values=[[ganador]], range_name=f"AA{i}")
                print(f"[Sheets] Ganador penales {ganador} guardado para {equipo1} vs {equipo2}")
                return
    except Exception as e:
        print(f"[ERROR sheets penales] {e}")


def registrar_cs_grilla(equipo1, equipo2, grilla_str):
    """Guarda la grilla de Correct Score cargada (string '1-0:7.5 2-0:6 ...') en columna M.
    Sirve para backtestear despues mercado vs modelo."""
    ws = _abrir()
    if ws is None:
        return
    try:
        registros = ws.get_all_records(expected_headers=[])
        for i, r in enumerate(registros, start=2):
            e1 = str(r.get("Equipo 1", "")).strip().lower()
            e2 = str(r.get("Equipo 2", "")).strip().lower()
            if e1 == equipo1.strip().lower() and e2 == equipo2.strip().lower():
                ws.update(values=[[grilla_str]], range_name=f"M{i}")
                return
    except Exception as e:
        print(f"[ERROR sheets cs_grilla] {e}")


def registrar_cs_odds(equipo1, equipo2, cs_top1, cs_top2):
    """Guarda las cuotas de Correct Score en columnas M y N (solo para backtest)."""
    ws = _abrir()
    if ws is None:
        return
    try:
        registros = ws.get_all_records(expected_headers=[])
        for i, r in enumerate(registros, start=2):
            e1 = str(r.get("Equipo 1", "")).strip().lower()
            e2 = str(r.get("Equipo 2", "")).strip().lower()
            if e1 == equipo1.strip().lower() and e2 == equipo2.strip().lower():
                v1 = cs_top1 if cs_top1 is not None else ""
                v2 = cs_top2 if cs_top2 is not None else ""
                ws.update(values=[[v1, v2]], range_name=f"M{i}:N{i}")
                return
    except Exception as e:
        print(f"[ERROR sheets cs_odds] {e}")


def actualizar_resumen():
    """Recalcula y sobreescribe la hoja Resumen con KPIs actualizados."""
    raw = os.getenv("GCP_SA_JSON")
    if not raw or not GSHEET_ID:
        return
    try:
        import gspread as _gs
        info = json.loads(raw)
        pk = info.get("private_key", "")
        if "\\n" in pk and "\n" not in pk:
            info["private_key"] = pk.replace("\\n", "\n")
        gc = _gs.service_account_from_dict(info)
        sh = gc.open_by_key(GSHEET_ID)
        ws1 = sh.sheet1
        wsr = sh.worksheet("Resumen")
    except Exception as e:
        print(f"[ERROR resumen abrir] {e}")
        return

    try:
        rows = ws1.get_all_values()[1:]
        jugados = 0
        pts_yo = 0
        pts_lider_ultimo = 0
        pts_decimo_ultimo = 0
        dist = {0: 0, 2: 0, 5: 0, 7: 0, 12: 0}

        for r in rows:
            g1 = r[3].strip() if len(r) > 3 else ""
            g2 = r[4].strip() if len(r) > 4 else ""
            p1 = r[5].strip() if len(r) > 5 else ""
            p2 = r[6].strip() if len(r) > 6 else ""
            pts = r[7].strip() if len(r) > 7 else ""
            pl  = r[8].strip() if len(r) > 8 else ""
            if g1 and g2 and p1 and p2 and pts:
                jugados += 1
                try:
                    p = int(pts)
                    pts_yo += p
                    dist[p] = dist.get(p, 0) + 1
                except ValueError:
                    pass
            if pl:
                try:
                    pts_lider_ultimo = int(pl)
                except ValueError:
                    pass
            d10 = r[23].strip() if len(r) > 23 else ""   # columna X = puntos 10mo
            if d10:
                try:
                    pts_decimo_ultimo = int(float(d10.replace(",", ".")))
                except ValueError:
                    pass

        TOTAL = 104
        restantes = max(TOTAL - jugados, 1)
        deficit = pts_lider_ultimo - pts_yo
        prom_yo = round(pts_yo / jugados, 2) if jugados else 0
        prom_lider = round(pts_lider_ultimo / jugados, 2) if jugados else 0

        # CORTE TOP-10 (el objetivo real): gap al 10mo y ritmo necesario
        gap_decimo = pts_decimo_ultimo - pts_yo
        prom_decimo = round(pts_decimo_ultimo / jugados, 2) if jugados else 0
        proy_decimo = pts_decimo_ultimo + prom_decimo * restantes  # si el corte mantiene ritmo
        prom_nec_top10 = round((proy_decimo - pts_yo) / restantes, 2) if pts_decimo_ultimo else 0

        kpis = [
            ["RESUMEN DEL PRODE - MUNDIAL 2026", "", ""],
            [""],
            ["Partidos jugados",  jugados,          f"de {TOTAL}",  f"{round(jugados/TOTAL*100)}% del Mundial"],
            ["Mis puntos",        pts_yo,            ""],
            ["Promedio mio",      prom_yo,           "pts/partido"],
            [""],
            ["CORTE TOP-10 (lo que paga)", "", ""],
            ["Puntos 10mo",       pts_decimo_ultimo, ""],
            ["GAP al 10mo",       gap_decimo,        "pts para entrar"],
            ["Promedio 10mo",     prom_decimo,       "pts/partido"],
            ["Prom. necesario top-10", prom_nec_top10, "pts/part restantes (si el 10mo mantiene ritmo)"],
            [""],
            ["Referencia - lider", pts_lider_ultimo, f"(gap {deficit})"],
            [""],
            ["DISTRIBUCION DE PUNTOS", "", ""],
            ["Exacto (12p)", "Result+goles (7p)", "Solo result (5p)", "Un gol (2p)", "Nada (0p)"],
            [dist.get(12,0), dist.get(7,0), dist.get(5,0), dist.get(2,0), dist.get(0,0)],
        ]

        wsr.clear()
        wsr.update(values=kpis, range_name="A1")
        print(f"[resumen] Actualizado: {jugados} partidos, {pts_yo}pts yo, {pts_lider_ultimo}pts lider")
    except Exception as e:
        print(f"[ERROR resumen calcular] {e}")


def disponible():
    """True si las credenciales y la planilla estan configuradas."""
    return bool(os.getenv("GCP_SA_JSON") and GSHEET_ID)

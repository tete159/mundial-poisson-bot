# -*- coding: utf-8 -*-
import os, sys, time, threading, requests
from datetime import datetime
from pytz import timezone
from modelo import predecir, ranking_puntos_esperados, pick_con_boost_11, pick_separacion   # Poisson + DC + prior + boost 1-1 + aviso de separacion

BETA_VAR = 2.5   # intensidad de la capa de diferenciacion (mas alto = mas contrarian)
import historial              # guarda las predicciones (volumen Railway)
import sheets_mundial         # lee resultados que el usuario carga a mano en Google Sheets
import sync_resultados        # sincroniza resultados finales desde the-odds-api


def _prior_combinado():
    """Junta los resultados de la planilla de Google + los cargados por el bot."""
    nd, d = sheets_mundial.prior_extra()           # fuente principal: la planilla
    nd2, d2 = historial.prior_extra()              # por si se cargo algo por Telegram
    for k, v in nd2.items():
        nd[k] = nd.get(k, 0) + v
    for k, v in d2.items():
        d[k] = d.get(k, 0) + v
    return nd, d

TG_BOT_TOKEN = os.getenv("TG_BOT_TOKEN", "")
TG_CHAT_ID   = int(os.getenv("TG_CHAT_ID", "0"))
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")
ART          = timezone("America/Argentina/Buenos_Aires")

estados = {}

PASOS = [
    ("o1",    "Cuota victoria {equipo1} (1)?"),
    ("ox",    "Cuota empate (X)?"),
    ("o2",    "Cuota victoria {equipo2} (2)?"),
    ("over",  "Cuota Over 2.5 goles?"),
    ("under", "Cuota Under 2.5 goles?"),
    ("btts_si", "Cuota 'Ambos equipos anotan - Si'?"),
    ("btts_no", "Cuota 'Ambos equipos anotan - No'?"),
]

# ==================== ANALISIS ====================

def build_resultado(estado):
    team1 = estado["equipo1"]
    team2 = estado["equipo2"]
    o1, ox, o2 = estado["o1"], estado["ox"], estado["o2"]
    over, under = estado["over"], estado["under"]
    btts_si = estado.get("btts_si")
    btts_no = estado.get("btts_no")
    # quitar vig de las cuotas BTTS y calcular prob real de Si
    if btts_si and btts_no and btts_si > 1.01 and btts_no > 1.01:
        p_si = (1/btts_si) / (1/btts_si + 1/btts_no)
        btts_odds = 1 / p_si  # cuota sin vig
    elif btts_si and btts_si > 1.01:
        btts_odds = btts_si
    else:
        btts_odds = None

    # resultados reales ya jugados -> alimentan el prior del modelo
    extra_nd, extra_d = _prior_combinado()
    ranking, (xg1, xg2, total_xg) = predecir(
        o1, ox, o2, over, btts_si_odds=btts_odds, extra_nodraw=extra_nd, extra_draw=extra_d
    )
    # ESTRATEGIA AGRESIVA (posicion 211/244, paga top-10, nada que perder):
    # se juega el marcador EXACTO mas probable -> caza los 12 puntos que trepan.
    # Si el usuario carga la grilla de Correct Score, el pick final sale del
    # mercado (mejor calibrado para este Mundial que el prior historico).
    # pick del modelo, con 1-1 reforzado en partidos parejos (anomalia del torneo)
    pick1 = pick_con_boost_11(ranking, o1, ox, o2)   # = ranking[0][0] salvo en parejos, donde puede dar 1-1
    top6 = [s for s, _ in ranking[:6]]  # candidatos para pedir las cuotas CS
    dist8 = [(s, p / 100.0) for s, p in ranking[:8]]  # distribucion para la capa de varianza

    # registrar la prediccion (para luego preguntar el resultado)
    fecha = estado.get("fecha_partido")
    historial.registrar_prediccion(team1, team2, ranking, fecha_partido=fecha)

    # guardar el pick del modelo como default (se sobreescribe si llega la grilla CS)
    pg1, pg2 = map(int, pick1.split("-"))
    sheets_mundial.registrar_prediccion(team1, team2, pg1, pg2)

    # guardar las 7 cuotas de entrada (cols O..U) para poder backtestear de verdad
    sheets_mundial.registrar_cuotas(
        team1, team2, o1, ox, o2, over, under,
        estado.get("btts_si"), estado.get("btts_no")
    )

    def con_equipos(score):
        g1, g2 = score.split("-")
        return f"{team1} {g1} - {team2} {g2}"

    n_reales = len(sheets_mundial.leer_resultados())
    avisos = []
    if n_reales == 20:
        avisos.append(
            "⚠️ 20 PARTIDOS JUGADOS — momento de hacer el backtest:\n\n"
            "Ya hay suficientes resultados reales del Mundial 2026 para\n"
            "evaluar si W_HIST = 0.45 es el valor óptimo.\n\n"
            "Qué hacer:\n"
            "  1. Correr _backtest_abr_may.py contra los 20 resultados reales\n"
            "  2. Ver qué valor de W_HIST maximiza puntos en esos 20 partidos\n"
            "  3. Si el óptimo difiere mucho de 0.45, ajustarlo en modelo.py\n\n"
            "Confirmá cuando estés listo para hacer el backtest."
        )
    if n_reales == 36:
        avisos.append(
            "📊 MITAD DE GRUPOS — diagnóstico del modelo:\n\n"
            "36 partidos jugados. Momento de ver cómo viene el modelo.\n\n"
            "Qué revisar:\n"
            "  1. /historial → fijate el promedio de puntos por partido\n"
            "  2. Si estás por debajo de 4.5 pts/partido, algo está fallando\n"
            "  3. Si estás por encima de 5.5 pts/partido, el modelo está fino\n"
            "  4. Meta para ganar el Prode: ~5.4 pts/partido (Monte Carlo p99)\n\n"
            "No hace falta cambiar nada todavía — solo diagnosticar."
        )
    if n_reales == 88:
        avisos.append(
            "🔬 FIN DE DIECISEISAVOS — recalibración con datos reales:\n\n"
            "Ya tenés 16 partidos eliminatorios de este Mundial para comparar\n"
            "contra el histórico de 9 mundiales.\n\n"
            "Qué revisar:\n"
            "  1. ¿Cuántos fueron a penales? Histórico: ~22% (3-4 de 16)\n"
            "  2. ¿Muchos 0-0 y 1-1? → subir más el RHO negativo\n"
            "  3. ¿Muchos goles? → bajar W_HIST, confiar más en las cuotas\n"
            "  4. Quedan octavos + cuartos + semis + final = 15 partidos clave\n\n"
            "Confirmá para hacer el ajuste fino antes de octavos."
        )
    if n_reales == 72:
        avisos.append(
            "⚠️ FASE ELIMINATORIA — momento de ajustar el modelo:\n\n"
            "Análisis de 9 mundiales (144 partidos eliminatorios) muestra:\n"
            "• 2-1 y 1-0 = 43% de todos los resultados (igual que grupos)\n"
            "• Empates son más frecuentes: 22% van a penales vs 18% en grupos\n"
            "• 0-0 aparece mucho más (8% de partidos) — juego más defensivo\n"
            "• Cuartos y la Final son las fases con más penales (~31-33%)\n\n"
            "Ajustes sugeridos en modelo.py:\n"
            "  RHO = -0.12  (más negativo → más empates bajos)\n"
            "  W_HIST = 0.50  (subir prior → más peso a la historia)\n\n"
            "Confirmá cuando estés listo para hacer el cambio."
        )

    return "\n".join(avisos) if avisos else "", pick1, top6, con_equipos, pg1, pg2, dist8


def parse_marcador(text):
    """Acepta '2-1', '2:1', '2 1' -> (2, 1). Devuelve None si no se entiende."""
    t = text.replace(":", "-").replace(",", "-").replace(" ", "-")
    partes = [x for x in t.split("-") if x != ""]
    if len(partes) != 2:
        return None
    try:
        return int(partes[0]), int(partes[1])
    except ValueError:
        return None

# ==================== TELEGRAM ====================

def send(chat_id, text):
    try:
        requests.post(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            data={"chat_id": chat_id, "text": text},
            timeout=10
        )
    except Exception as e:
        print(f"[ERROR send] {e}")

def get_updates(offset=None):
    try:
        r = requests.get(
            f"https://api.telegram.org/bot{TG_BOT_TOKEN}/getUpdates",
            params={"timeout": 5, "offset": offset},
            timeout=10
        )
        return r.json().get("result", [])
    except Exception as e:
        print(f"[ERROR getUpdates] {e}")
        return []

# ==================== FLUJO CONVERSACIONAL ====================

def iniciar_partido(chat_id, equipo1, equipo2, fecha_partido=None):
    estados[chat_id] = {"step": 0, "equipo1": equipo1, "equipo2": equipo2,
                        "fecha_partido": fecha_partido}
    send(chat_id, f"Partido: {equipo1} vs {equipo2}\n\nCuota victoria {equipo1} (1)?")


def preguntar_resultado(chat_id, pred):
    """Le pregunta al usuario como salio un partido ya jugado."""
    estados[chat_id] = {
        "step": "esperar_resultado",
        "pred_id": pred["id"],
        "equipo1": pred["equipo1"],
        "equipo2": pred["equipo2"],
    }
    historial.marcar_preguntado(pred["id"])
    send(chat_id,
         f"Como salio {pred['equipo1']} vs {pred['equipo2']}?\n"
         f"Respondeme el marcador (ej: 2-1)")


def texto_historial():
    resultados = sheets_mundial.leer_resultados_con_pred()
    if not resultados:
        return "Todavia no hay resultados cargados.\nCarga los resultados en la planilla de Google Sheets cuando terminen los partidos."

    def calcular_puntos(r):
        p1, p2, g1, g2 = r["pred_g1"], r["pred_g2"], r["g1"], r["g2"]
        if p1 == g1 and p2 == g2:
            return 12
        res_real = 1 if g1 > g2 else (2 if g1 < g2 else 0)
        res_pred = 1 if p1 > p2 else (2 if p1 < p2 else 0)
        pts = 5 if res_real == res_pred else 0
        if (p1 == g1) != (p2 == g2):
            pts += 2
        return pts

    total = len(resultados)
    exactos   = sum(1 for r in resultados if calcular_puntos(r) == 12)
    result_ok = sum(1 for r in resultados if calcular_puntos(r) >= 5)
    pts_total = sum(calcular_puntos(r) for r in resultados)

    lineas = [
        "HISTORIAL DE ACIERTOS",
        "",
        f"Partidos jugados:      {total}",
        f"Puntos acumulados:     {pts_total}",
        f"Marcador exacto (12p): {exactos}/{total}  ({exactos/total*100:.0f}%)",
        f"Resultado correcto:    {result_ok}/{total}  ({result_ok/total*100:.0f}%)",
        "",
        "Ultimos partidos:",
    ]
    for r in resultados[-8:]:
        pred = f"{r['pred_g1']}-{r['pred_g2']}"
        real = f"{r['g1']}-{r['g2']}"
        pts  = calcular_puntos(r)
        lineas.append(f"  {pts}p  {r['equipo1']} vs {r['equipo2']}: real {real}  predije {pred}")
    return "\n".join(lineas)

def procesar_mensaje(chat_id, text):
    text = text.strip()

    if text == "/partido":
        proximos = get_calendario(5)
        if proximos:
            estados[chat_id] = {"step": "elegir_partido", "opciones": proximos}
            lineas = ["Que partido queres analizar?\n"]
            for i, p in enumerate(proximos, 1):
                cuando = p["commence"].strftime("%d/%m %H:%M")
                lineas.append(f"{i}. {p['equipo1']} vs {p['equipo2']}  ({cuando})")
            lineas.append("\nEscribi el numero o /cancelar")
            send(chat_id, "\n".join(lineas))
        else:
            estados[chat_id] = {"step": "esperar_equipo1"}
            send(chat_id, "Nombre del equipo local?")
        return

    if text == "/synclog":
        try:
            import requests as _req
            r = _req.get(
                "https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup/scores",
                params={"apiKey": os.getenv("ODDS_API_KEY",""), "daysFrom": 3},
                timeout=10
            )
            data = r.json()
            if not isinstance(data, list):
                send(chat_id, f"API error ({r.status_code}): {data}")
                return
            completados = [m for m in data if isinstance(m, dict) and m.get("completed") and m.get("scores")]
            if not completados:
                send(chat_id, "API: no hay partidos completados en los ultimos 3 dias.")
            else:
                lineas = [f"Partidos completados en API ({len(completados)}):"]
                for m in completados:
                    lineas.append(f"  {m['home_team']} vs {m['away_team']}")
                send(chat_id, "\n".join(lineas))
        except Exception as e:
            send(chat_id, f"Error: {e}")
        return

    if text == "/sync":
        if sheets_mundial.disponible():
            ws = sheets_mundial._abrir()
            if ws:
                try:
                    n = sync_resultados.sincronizar(ws, forzar=True)
                    send(chat_id, f"Sync completado. {n} resultado(s) nuevos cargados.")
                except Exception as e:
                    send(chat_id, f"Error en sync: {e}")
            else:
                send(chat_id, "No pude abrir la planilla.")
        else:
            send(chat_id, "Credenciales no configuradas.")
        return

    if text in ("/cancelar", "/cancel"):
        estados.pop(chat_id, None)
        send(chat_id, "Cancelado.")
        return

    if text in ("/proximos", "/calendario"):
        send(chat_id, texto_calendario())
        return

    if text in ("/historial", "/stats"):
        send(chat_id, texto_historial())
        return

    if text == "/limpiar":
        estados[chat_id] = {"step": "confirmar_limpiar"}
        send(chat_id, "Esto borra TODO el historial (predicciones y resultados).\n"
                      "Escribi SI para confirmar, o /cancelar.")
        return

    if text in ("/ayuda", "/help", "/start"):
        send(chat_id,
            "Comandos:\n"
            "/partido   - analizar un partido manualmente\n"
            "/proximos  - ver el calendario de partidos\n"
            "/historial - ver mis aciertos hasta ahora\n"
            "/limpiar   - borrar todo el historial\n"
            "/cancelar  - cancelar operacion\n"
            "/ayuda     - este mensaje\n\n"
            "El bot te avisa 30 min antes de cada partido del Mundial,\n"
            "y despues te pregunta como salio para ir aprendiendo."
        )
        return

    estado = estados.get(chat_id)

    if not estado:
        send(chat_id, "Escribi /partido para analizar un partido.")
        return

    # ---- confirmacion de /limpiar ----
    if estado.get("step") == "confirmar_limpiar":
        estados.pop(chat_id, None)
        if text.strip().lower() in ("si", "sí", "yes"):
            n = historial.limpiar()
            send(chat_id, f"Listo. Borre {n} registros. El historial arranca de cero.")
        else:
            send(chat_id, "Cancelado, no borre nada.")
        return

    # ---- esperando que el usuario cargue el resultado real de un partido ----
    if estado.get("step") == "esperar_resultado":
        marcador = parse_marcador(text)
        if not marcador:
            send(chat_id, "No entendi el marcador. Mandalo asi: 2-1")
            return
        g1, g2 = marcador
        pred = historial.registrar_resultado(estado["pred_id"], g1, g2)
        estados.pop(chat_id, None)
        if pred:
            acierto = (pred["resultado"] == pred["top1"])
            en_top3 = (pred["resultado"] in pred["top3"])
            if acierto:
                msg = f"Excelente! Habia predicho {pred['top1']} y salio {pred['resultado']}. Acierto!"
            elif en_top3:
                msg = f"Cerca: salio {pred['resultado']}, lo tenia en mi top3 (predije {pred['top1']})."
            else:
                msg = f"Esta vez no: salio {pred['resultado']}, yo predije {pred['top1']}."
            send(chat_id, msg + "\nGuardado. Esto mejora las proximas predicciones.")
        else:
            send(chat_id, "No encontre ese partido, pero gracias igual.")
        return

    if estado.get("step") == "esperar_cs_grilla":
        candidatos = estado["top6"]
        con_equipos = estado["con_equipos"]
        model_pick = estado["pick1"]
        eq1 = estado.get("equipo1", "")
        eq2 = estado.get("equipo2", "")

        if text.lower() in ("saltar", "s", "-", "skip"):
            # sin grilla -> usar la distribucion del modelo
            dist = estado.get("dist8", [])
            chalk = model_pick
            fuente = "modelo"
        else:
            # parsear los numeros de la linea y mapearlos a los candidatos en orden
            crudos = text.replace(",", " ").split()
            cuotas = []
            for c in crudos:
                try:
                    cuotas.append(float(c))
                except ValueError:
                    cuotas.append(None)
            pares = [(candidatos[i], cuotas[i]) for i in range(min(len(candidatos), len(cuotas)))
                     if cuotas[i] is not None and cuotas[i] > 1.0]
            if not pares:
                send(chat_id, f"No entendi las cuotas. Mandame {len(candidatos)} numeros separados por espacio, en el orden:\n{'  '.join(candidatos)}\n(o 'saltar')")
                return
            # distribucion del mercado: prob ~ 1/cuota (normalizada entre las cargadas)
            inv = [(m, 1.0 / c) for m, c in pares]
            Z = sum(v for _, v in inv) or 1.0
            dist = [(m, v / Z) for m, v in inv]
            chalk = min(pares, key=lambda x: x[1])[0]   # mas probable del mercado (menor cuota)
            grilla_str = " ".join(f"{m}:{c}" for m, c in pares)
            sheets_mundial.registrar_cs_grilla(eq1, eq2, grilla_str)
            fuente = "mercado"

        # AVISO DE SEPARACION: si el mercado deja dos marcadores casi empatados,
        # avisa y sugiere el menos obvio (mas goles) -> diferenciacion casi gratis.
        sep_pick, hay_sep = pick_separacion(dist)

        # guardar el pick principal del bot (el mas probable) en columna N
        sheets_mundial.registrar_pick_bot(eq1, eq2, chalk)

        pdict = dict(dist)
        if hay_sep:
            pc = pdict.get(chalk, 0) * 100
            ps = pdict.get(sep_pick, 0) * 100
            cuerpo = (f"⚡ SPOT DE SEPARACIÓN — {chalk} y {sep_pick} casi empatados ({pc:.0f}% vs {ps:.0f}%)\n\n"
                      f"Más probable ({fuente}): {con_equipos(chalk)}   <- 'ok'\n"
                      f"Separarte (mismo precio, menos jugado): {con_equipos(sep_pick)}   <- mandá '{sep_pick}'\n"
                      f"La manada se amontona en {chalk}; el {sep_pick} te separa casi gratis.")
            var_pick = sep_pick
        else:
            cuerpo = (f"Más probable ({fuente}): {con_equipos(chalk)}   <- 'ok'\n"
                      f"(no hay spot de separación: el chalk se despega del resto)")
            var_pick = chalk

        estado["recomendacion"] = chalk          # 'ok' juega la mas probable
        estado["var_pick"] = var_pick
        estado["step"] = "esperar_jugada"
        send(chat_id,
             f"{cuerpo}\n\n"
             f"¿Qué jugás vos? Mandá tu marcador o 'ok'.")
        return

    if estado.get("step") == "esperar_jugada":
        con_equipos = estado["con_equipos"]
        recom = estado["recomendacion"]
        eq1 = estado.get("equipo1", "")
        eq2 = estado.get("equipo2", "")
        if text.lower() in ("ok", "si", "sí", "dale", "acepto", "listo", "="):
            jugada = recom
        else:
            m = parse_marcador(text)
            if not m:
                send(chat_id, f"No entendi. Mandá tu marcador (ej: 2-0) o 'ok' para aceptar {recom}.")
                return
            jugada = f"{m[0]}-{m[1]}"
        # lo que REALMENTE jugas va a F/G (es lo que mide tu tracking)
        jg1, jg2 = map(int, jugada.split("-"))
        sheets_mundial.registrar_prediccion(eq1, eq2, jg1, jg2)

        estado["step"] = "esperar_pts_lider"
        pts_mios = estado["pts_mios"]
        extra = "" if jugada == recom else f" (distinto a la recomendación {recom})"
        send(chat_id,
             f"Anotado: jugás {con_equipos(jugada)}{extra}\n\n"
             f"Tus puntos (de la planilla): {pts_mios}\nCuantos tiene el primero?")
        return

    if estado.get("step") == "esperar_pts_lider":
        try:
            pts_lider = int(float(text.strip()))
        except ValueError:
            send(chat_id, "Manda solo un numero.")
            return
        estados.pop(chat_id, None)

        pts_mios   = estado["pts_mios"]
        jugados    = len(sheets_mundial.leer_resultados())
        prom_mio   = pts_mios / jugados if jugados else 0
        prom_lider = pts_lider / jugados if jugados else 0

        # Guardar pts_lider en la fila de arriba del partido actual
        # (el puntaje del lider al predecir el partido N = acumulado hasta N-1)
        eq1 = estado.get("equipo1", "")
        eq2 = estado.get("equipo2", "")
        if eq1 and eq2:
            sheets_mundial.registrar_pts_lider_fila_anterior(eq1, eq2, pts_lider)
            sheets_mundial.actualizar_resumen()

        send(chat_id,
             f"Guardado.\n\n"
             f"Vos:   {pts_mios}p  ({prom_mio:.1f}/partido)\n"
             f"Lider: {pts_lider}p  ({prom_lider:.1f}/partido)\n"
             f"Jugados: {jugados}")
        return

    if estado.get("step") == "elegir_partido":
        opciones = estado["opciones"]
        try:
            idx = int(text.strip()) - 1
            if not (0 <= idx < len(opciones)):
                raise ValueError
        except ValueError:
            send(chat_id, f"Escribi un numero del 1 al {len(opciones)}.")
            return
        p = opciones[idx]
        iniciar_partido(chat_id, p["equipo1"], p["equipo2"], fecha_partido=p["commence"])
        return

    if estado.get("step") == "esperar_equipo1":
        estado["equipo1"] = text
        estado["step"] = "esperar_equipo2"
        send(chat_id, "Nombre del equipo visitante?")
        return

    if estado.get("step") == "esperar_equipo2":
        estado["equipo2"] = text
        estado["step"] = 0
        send(chat_id, f"Partido: {estado['equipo1']} vs {estado['equipo2']}\n\nCuota victoria {estado['equipo1']} (1)?")
        return

    step = estado.get("step", 0)

    try:
        valor = float(text.replace(",", "."))
        if valor < 1.01:
            send(chat_id, "La cuota debe ser mayor a 1.01. Intenta de nuevo:")
            return
    except:
        send(chat_id, "Ingresa solo un numero. Ej: 1.14")
        return

    clave = PASOS[step][0]
    estado[clave] = valor
    step += 1
    estado["step"] = step

    if step < len(PASOS):
        pregunta = PASOS[step][1].format(equipo1=estado["equipo1"], equipo2=estado["equipo2"])
        send(chat_id, pregunta)
    else:
        avisos, pick1, top6, con_equipos, pred_g1, pred_g2, dist8 = build_resultado(estado)
        if avisos:
            send(chat_id, avisos)
        # calcular mis puntos desde la planilla
        def _calc_pts(r):
            p1, p2, g1, g2 = r["pred_g1"], r["pred_g2"], r["g1"], r["g2"]
            if p1 == g1 and p2 == g2: return 12
            res_pred = 1 if p1>p2 else (2 if p1<p2 else 0)
            res_real = 1 if g1>g2 else (2 if g1<g2 else 0)
            pts = 5 if res_pred == res_real else 0
            if (p1==g1) != (p2==g2): pts += 2
            return pts
        resultados_con_pred = sheets_mundial.leer_resultados_con_pred()
        pts_mios = sum(_calc_pts(r) for r in resultados_con_pred)

        eq1 = estado.get("equipo1", "")
        eq2 = estado.get("equipo2", "")

        estados[chat_id] = {
            "step": "esperar_cs_grilla",
            "pick1": pick1,
            "top6": top6,
            "dist8": dist8,
            "con_equipos": con_equipos,
            "pts_mios": pts_mios,
            "equipo1": eq1,
            "equipo2": eq2,
            "pred_g1": pred_g1,
            "pred_g2": pred_g2,
        }
        send(chat_id,
             f"Modelo (referencia): {con_equipos(pick1)}\n\n"
             f"Pasame las cuotas Correct Score de Bet365 de estos {len(top6)} marcadores, "
             f"en este orden y separadas por espacio (o 'saltar'):\n\n"
             f"{'   '.join(top6)}\n\n"
             f"Ej: 7.5 6 9 7 11 12")
        print(f"[OK] Pidiendo grilla CS: {estado['equipo1']} vs {estado['equipo2']} (modelo {pick1})")

# ==================== MONITOR AUTOMATICO ====================

def get_proximos_partidos():
    try:
        r = requests.get(
            "https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup/events",
            params={"apiKey": ODDS_API_KEY, "regions": "ar", "oddsFormat": "decimal"},
            timeout=10
        )
        if r.status_code != 200:
            return []
        ahora = datetime.now(ART)
        partidos = []
        for m in r.json():
            commence = datetime.fromisoformat(m["commence_time"].replace("Z", "+00:00")).astimezone(ART)
            diff_min = (commence - ahora).total_seconds() / 60
            if 25 <= diff_min <= 35:
                partidos.append({"equipo1": m["home_team"], "equipo2": m["away_team"], "commence": commence})
        return partidos
    except Exception as e:
        print(f"[ERROR partidos] {e}")
        return []

def get_calendario(n=12):
    """Devuelve los proximos n partidos del Mundial (los que aun no empezaron)."""
    try:
        r = requests.get(
            "https://api.the-odds-api.com/v4/sports/soccer_fifa_world_cup/events",
            params={"apiKey": ODDS_API_KEY, "regions": "ar", "oddsFormat": "decimal"},
            timeout=10
        )
        if r.status_code != 200:
            return []
        ahora = datetime.now(ART)
        partidos = []
        for m in r.json():
            commence = datetime.fromisoformat(m["commence_time"].replace("Z", "+00:00")).astimezone(ART)
            if commence > ahora:
                partidos.append({"equipo1": m["home_team"], "equipo2": m["away_team"], "commence": commence})
        partidos.sort(key=lambda p: p["commence"])
        return partidos[:n]
    except Exception as e:
        print(f"[ERROR calendario] {e}")
        return []


def texto_calendario():
    partidos = get_calendario()
    if not partidos:
        return "No pude traer el calendario ahora. Proba de nuevo en un rato."
    lineas = ["PROXIMOS PARTIDOS", ""]
    for p in partidos:
        cuando = p["commence"].strftime("%d/%m %H:%M")
        lineas.append(f"  {cuando}  {p['equipo1']} vs {p['equipo2']}")
    lineas += ["", "(horarios de Argentina)"]
    return "\n".join(lineas)


def monitor_partidos():
    notificados = set()
    while True:
        try:
            # 1) avisar 30 min antes de cada partido y pedir cuotas
            for p in get_proximos_partidos():
                key = f"{p['equipo1']}_{p['equipo2']}_{p['commence'].date()}"
                if key not in notificados:
                    notificados.add(key)
                    hora = p["commence"].strftime("%H:%M")
                    print(f"[AUTO] Partido en 30 min: {p['equipo1']} vs {p['equipo2']}")
                    send(TG_CHAT_ID, f"Partido en 30 min! ({hora} hs)\nVoy a pedirte las cuotas de Bet365:")
                    time.sleep(2)
                    iniciar_partido(TG_CHAT_ID, p["equipo1"], p["equipo2"],
                                    fecha_partido=p["commence"])

            # sincronizar resultados finales desde the-odds-api a la planilla
            if sheets_mundial.disponible():
                ws = sheets_mundial._abrir()
                if ws:
                    n = sync_resultados.sincronizar(ws)
                    if n > 0:
                        sheets_mundial.actualizar_resumen()
        except Exception as e:
            print(f"[ERROR monitor] {e}")
        time.sleep(60)

# ==================== MAIN ====================

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print("Bot Mundial 2026 iniciado")
    print("Escuchando en @billboardtopbot...")
    if historial._DATA_DIR == "/data":
        print("[OK] Volumen persistente activo (/data) - el historial NO se borra")
    else:
        print("[AVISO] SIN volumen persistente - el historial se borrara en cada deploy")
        print(f"        guardando en: {historial._DATA_DIR}")

    threading.Thread(target=monitor_partidos, daemon=True).start()

    offset = None
    while True:
        updates = get_updates(offset)
        for update in updates:
            offset = update["update_id"] + 1
            msg = update.get("message") or update.get("edited_message")
            if not msg:
                continue
            chat_id = msg["chat"]["id"]
            text = msg.get("text", "").strip()
            if text:
                print(f"[MSG] {chat_id}: {text}")
                procesar_mensaje(chat_id, text)
        time.sleep(1)

if __name__ == "__main__":
    main()

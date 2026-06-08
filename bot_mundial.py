# -*- coding: utf-8 -*-
import os, sys, time, threading, requests
from datetime import datetime
from pytz import timezone
from modelo import predecir   # Poisson + Dixon-Coles + prior historico del Mundial
import historial              # guarda predicciones/resultados y retroalimenta el modelo

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
]

# ==================== ANALISIS ====================

def build_resultado(estado):
    team1 = estado["equipo1"]
    team2 = estado["equipo2"]
    o1, ox, o2 = estado["o1"], estado["ox"], estado["o2"]
    over, under = estado["over"], estado["under"]

    # resultados reales ya jugados -> alimentan el prior del modelo
    extra_nd, extra_d = historial.prior_extra()
    ranking, (xg1, xg2, total_xg) = predecir(
        o1, ox, o2, over, extra_nodraw=extra_nd, extra_draw=extra_d
    )
    picks = ranking[:5]

    # registrar la prediccion (para luego preguntar el resultado)
    fecha = estado.get("fecha_partido")
    historial.registrar_prediccion(team1, team2, ranking, fecha_partido=fecha)

    aprendidos = sum(extra_nd.values()) + sum(extra_d.values())
    nota_aprendizaje = f"  (ajustado con {aprendidos} resultados reales)" if aprendidos else ""

    lineas = [
        "MUNDIAL 2026 - Prediccion de marcador",
        "(Poisson + Dixon-Coles + historico Mundial)" + nota_aprendizaje,
        "",
        f"{team1} vs {team2}",
        "",
        f"Cuotas Bet365:",
        f"  {team1}: {o1}",
        f"  Empate: {ox}",
        f"  {team2}: {o2}",
        f"  Over 2.5: {over}  Under 2.5: {under}",
        "",
        f"Goles esperados:",
        f"  {team1}: {xg1:.2f}  |  {team2}: {xg2:.2f}",
        "",
        "Top resultados:",
    ]
    for i, (score, prob) in enumerate(picks, 1):
        marca = ">>>" if i == 1 else "   "
        lineas.append(f"{marca} {i}. {score}   ({prob}%)")

    lineas += ["", f"ELEGIR: {picks[0][0]}", f"CONTRARIAN: {picks[2][0]}"]
    return "\n".join(lineas)


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
    s = historial.stats()
    if s["total"] == 0:
        return "Todavia no hay resultados cargados.\nCuando se jueguen partidos te voy a preguntar como salieron."
    lineas = [
        "HISTORIAL DE ACIERTOS",
        "",
        f"Partidos con resultado: {s['total']}",
        f"Acerto el marcador exacto (top1): {s['top1']}/{s['total']}  ({s['pct_top1']:.0f}%)",
        f"El real estaba en mi top3:        {s['top3']}/{s['total']}  ({s['pct_top3']:.0f}%)",
        "",
        "Ultimos partidos:",
    ]
    for p in historial.ultimos(8):
        ok = "OK " if p["resultado"] == p["top1"] else ("~  " if p["resultado"] in p["top3"] else "X  ")
        lineas.append(f"  {ok}{p['equipo1']} vs {p['equipo2']}: real {p['resultado']} (predije {p['top1']})")
    return "\n".join(lineas)

def procesar_mensaje(chat_id, text):
    text = text.strip()

    if text == "/partido":
        estados[chat_id] = {"step": "esperar_equipo1"}
        send(chat_id, "Nombre del equipo local?")
        return

    if text in ("/cancelar", "/cancel"):
        estados.pop(chat_id, None)
        send(chat_id, "Cancelado.")
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
        resultado = build_resultado(estado)
        send(chat_id, resultado)
        estados.pop(chat_id, None)
        print(f"[OK] Analisis enviado: {estado['equipo1']} vs {estado['equipo2']}")

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

            # 2) preguntar el resultado de partidos ya jugados (si el chat esta libre)
            if TG_CHAT_ID not in estados:
                pendientes = historial.pendientes_para_preguntar()
                if pendientes:
                    print(f"[AUTO] Preguntando resultado: {pendientes[0]['equipo1']} vs {pendientes[0]['equipo2']}")
                    preguntar_resultado(TG_CHAT_ID, pendientes[0])
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

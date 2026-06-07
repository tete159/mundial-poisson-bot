# -*- coding: utf-8 -*-
import os, sys, time, threading, requests
from datetime import datetime
from scipy.stats import poisson
from scipy.optimize import fminbound
from pytz import timezone

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

# ==================== POISSON ====================

def estimate_xg(over_odds):
    target = 1 / over_odds
    def err(xg): return abs((1 - poisson.cdf(2, xg)) - target)
    return round(fminbound(err, 0.5, 5.0), 2)

def team_xgs(total, o1, o2):
    p1, p2 = 1/o1, 1/o2
    return round(total * p1 / (p1+p2), 2), round(total * p2 / (p1+p2), 2)

def top_scorelines(xg1, xg2, n=5):
    sc = {}
    for g1 in range(7):
        for g2 in range(7):
            sc[f"{g1}-{g2}"] = round(poisson.pmf(g1, xg1) * poisson.pmf(g2, xg2) * 100, 1)
    return sorted(sc.items(), key=lambda x: x[1], reverse=True)[:n]

def build_resultado(estado):
    team1 = estado["equipo1"]
    team2 = estado["equipo2"]
    o1, ox, o2 = estado["o1"], estado["ox"], estado["o2"]
    over, under = estado["over"], estado["under"]

    total_xg = estimate_xg(over)
    xg1, xg2 = team_xgs(total_xg, o1, o2)
    picks = top_scorelines(xg1, xg2)

    lineas = [
        "MUNDIAL 2026 - Analisis Poisson",
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
        f"  {team1}: {xg1}  |  {team2}: {xg2}",
        "",
        "Top resultados:",
    ]
    for i, (score, prob) in enumerate(picks, 1):
        marca = ">>>" if i == 1 else "   "
        lineas.append(f"{marca} {i}. {score}   ({prob}%)")

    lineas += ["", f"ELEGIR: {picks[0][0]}", f"CONTRARIAN: {picks[2][0]}"]
    return "\n".join(lineas)

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
            params={"timeout": 20, "offset": offset},
            timeout=25
        )
        return r.json().get("result", [])
    except:
        return []

# ==================== FLUJO CONVERSACIONAL ====================

def iniciar_partido(chat_id, equipo1, equipo2):
    estados[chat_id] = {"step": 0, "equipo1": equipo1, "equipo2": equipo2}
    send(chat_id, f"Partido: {equipo1} vs {equipo2}\n\nCuota victoria {equipo1} (1)?")

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

    if text in ("/ayuda", "/help", "/start"):
        send(chat_id,
            "Comandos:\n"
            "/partido  - analizar un partido manualmente\n"
            "/cancelar - cancelar operacion\n"
            "/ayuda    - este mensaje\n\n"
            "El bot te avisa automaticamente 30 min antes de cada partido del Mundial."
        )
        return

    estado = estados.get(chat_id)

    if not estado:
        send(chat_id, "Escribi /partido para analizar un partido.")
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
            for p in get_proximos_partidos():
                key = f"{p['equipo1']}_{p['equipo2']}_{p['commence'].date()}"
                if key not in notificados:
                    notificados.add(key)
                    hora = p["commence"].strftime("%H:%M")
                    print(f"[AUTO] Partido en 30 min: {p['equipo1']} vs {p['equipo2']}")
                    send(TG_CHAT_ID, f"Partido en 30 min! ({hora} hs)\nVoy a pedirte las cuotas de Bet365:")
                    time.sleep(2)
                    iniciar_partido(TG_CHAT_ID, p["equipo1"], p["equipo2"])
        except Exception as e:
            print(f"[ERROR monitor] {e}")
        time.sleep(60)

# ==================== MAIN ====================

def main():
    sys.stdout.reconfigure(encoding="utf-8")
    print("Bot Mundial 2026 iniciado")
    print("Escuchando en @billboardtopbot...")

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

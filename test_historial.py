# -*- coding: utf-8 -*-
"""Prueba el ciclo completo: predecir -> registrar -> cargar resultado -> aprender"""
import sys, os
sys.stdout.reconfigure(encoding="utf-8")

# usar un archivo de prueba aparte
import historial
historial._PATH = os.path.join(os.path.dirname(__file__), "historial_TEST.json")
if os.path.exists(historial._PATH):
    os.remove(historial._PATH)

import bot_mundial

# 1) Simular una prediccion (Mexico vs Sudafrica)
estado = {"equipo1": "Mexico", "equipo2": "Sudafrica",
          "o1": 2.10, "ox": 3.20, "o2": 3.50, "over": 1.95, "under": 1.85}
print("--- Prediccion 1 (sin historial) ---")
print(bot_mundial.build_resultado(estado))

# 2) Cargar varios resultados reales 2-1 y ver como cambia el prior
print("\n--- Cargando 3 resultados reales 2-1 ---")
for _ in range(3):
    e = {"equipo1": "A", "equipo2": "B", "o1": 2.0, "ox": 3.2, "o2": 3.5, "over": 1.9, "under": 1.9}
    bot_mundial.build_resultado(e)  # registra prediccion
# cargar resultados por equipos
for p in historial._load()["predicciones"]:
    if p["equipo1"] == "A":
        historial.registrar_resultado(p["id"], 2, 1)

# 3) Nueva prediccion: el prior ahora tiene mas peso en 2-1
print("\n--- Prediccion 2 (despues de aprender 2-1) ---")
print(bot_mundial.build_resultado(estado))

# 4) Stats
print("\n--- /historial ---")
# marcar el resultado de la primera prediccion
preds = historial._load()["predicciones"]
historial.registrar_resultado(preds[0]["id"], 2, 1)
print(bot_mundial.texto_historial())

# 5) parse_marcador
print("\n--- parse_marcador ---")
for t in ["2-1", "2:1", "2 1", "3-0", "hola"]:
    print(f"  '{t}' -> {bot_mundial.parse_marcador(t)}")

os.remove(historial._PATH)
print("\nOK - test completo")

# -*- coding: utf-8 -*-
"""
Backtest honesto: que distribucion de marcadores explica mejor Qatar 2022?
Compara (en forma ordenada ganador-perdedor, sin usar info de cada partido):
  A) Poisson puro (partido promedio)
  B) Prior historico del Mundial
  C) Blend 65/35
Metrica: log-loss promedio del marcador real (mas bajo = mejor).
"""
import sys, math
sys.stdout.reconfigure(encoding="utf-8")
from scipy.stats import poisson

HIST = {
    (1,0):182,(2,1):152,(2,0):111,(1,1):92,(0,0):78,(3,1):68,(3,0):57,
    (3,2):43,(2,2):35,(4,1):31,(4,0):24,(4,2):17,(6,1):11,(5,2):9,
    (5,0):7,(3,3):7,(5,1):7,(6,0):5,(7,0):5,(4,3):3,(7,1):3,(8,1):3,
    (4,4):2,(6,3):2,(9,0):2,(5,3):1,(6,2):1,(7,2):1,(7,3):1,(6,5):1,
    (8,3):1,(10,1):1,(7,5):1,
}
QATAR = {
    (1,0):10,(2,0):12,(2,1):11,(1,1):5,(0,0):7,(3,0):3,(3,1):3,(3,2):3,
    (4,1):3,(4,2):1,(2,2):1,(3,3):2,(6,2):1,(7,0):1,(6,1):1,
}

def ordenar(i, j):
    """marcador en forma ganador-perdedor"""
    return (max(i, j), min(i, j))

def dist_poisson(xg=1.4):
    """Poisson para partido promedio, plegado a forma ordenada."""
    d = {}
    for i in range(11):
        for j in range(11):
            key = ordenar(i, j)
            d[key] = d.get(key, 0) + poisson.pmf(i, xg) * poisson.pmf(j, xg)
    s = sum(d.values())
    return {k: v/s for k, v in d.items()}

def dist_hist():
    s = sum(HIST.values())
    return {k: v/s for k, v in HIST.items()}

def blend(da, db, w):
    keys = set(da) | set(db)
    return {k: (1-w)*da.get(k, 0) + w*db.get(k, 0) for k in keys}

def logloss(modelo, datos_reales):
    """log-loss promedio: -mean(log P_modelo(marcador_real))"""
    eps = 1e-6
    total_ll = 0.0
    n = 0
    for score, freq in datos_reales.items():
        p = modelo.get(score, eps)
        total_ll += -math.log(max(p, eps)) * freq
        n += freq
    return total_ll / n

A = dist_poisson(1.4)
B = dist_hist()
C = blend(A, B, 0.35)

ll_A = logloss(A, QATAR)
ll_B = logloss(B, QATAR)
ll_C = logloss(C, QATAR)

print("BACKTEST sobre los 64 partidos de Qatar 2022")
print("(log-loss del marcador real, mas BAJO = mejor)\n")
print(f"  A) Poisson puro       : {ll_A:.4f}")
print(f"  B) Prior historico    : {ll_B:.4f}")
print(f"  C) Blend 65/35 (nuevo): {ll_C:.4f}")

mejora = 100 * (ll_A - ll_C) / ll_A
print(f"\n=> El modelo nuevo mejora {mejora:.1f}% sobre Poisson puro")

# Buscar el mejor peso w
print("\nBarrido del peso historico W:")
best_w, best_ll = 0, 999
for wi in range(0, 101, 5):
    w = wi/100
    ll = logloss(blend(A, B, w), QATAR)
    if ll < best_ll:
        best_ll, best_w = ll, w
    if wi % 10 == 0:
        print(f"  W={w:.2f}  log-loss={ll:.4f}")
print(f"\n=> Mejor peso: W={best_w:.2f} (log-loss {best_ll:.4f})")

# -*- coding: utf-8 -*-
"""Validacion: prior historico del Mundial vs lo que realmente paso en Qatar 2022"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

# Prior historico (marcador ordenado ganador-perdedor), 964 partidos de Mundiales
HIST = {
    (1,0):182,(2,1):152,(2,0):111,(1,1):92,(0,0):78,(3,1):68,(3,0):57,
    (3,2):43,(2,2):35,(4,1):31,(4,0):24,(4,2):17,(6,1):11,(5,2):9,
    (5,0):7,(3,3):7,(5,1):7,(6,0):5,(7,0):5,(4,3):3,(7,1):3,(8,1):3,
    (4,4):2,(6,3):2,(9,0):2,(5,3):1,(6,2):1,(7,2):1,(7,3):1,(6,5):1,
    (8,3):1,(10,1):1,(7,5):1,
}
total_hist = sum(HIST.values())

# Qatar 2022 - los 64 partidos (tiempo reglamentario), marcador ordenado
QATAR = {
    (1,0):10,(2,0):12,(2,1):11,(1,1):5,(0,0):7,(3,0):3,(3,1):3,(3,2):3,
    (4,1):3,(4,2):1,(2,2):1,(3,3):2,(6,2):1,(7,0):1,(6,1):1,
}
total_qatar = sum(QATAR.values())

print(f"Prior historico: {total_hist} partidos")
print(f"Qatar 2022:      {total_qatar} partidos\n")

top5 = sorted(HIST.items(), key=lambda x: -x[1])[:5]
print("TOP 5 marcadores historicos vs Qatar:")
hist_acum = qatar_acum = 0
for score, freq in top5:
    hp = 100*freq/total_hist
    qf = QATAR.get(score, 0)
    qp = 100*qf/total_qatar
    hist_acum += hp
    qatar_acum += qp
    print(f"  {score[0]}-{score[1]}:  historico {hp:5.1f}%   |   Qatar {qp:5.1f}%")

print(f"\n  ACUMULADO top5:  historico {hist_acum:.1f}%  |  Qatar {qatar_acum:.1f}%")
print(f"\n=> Los 5 marcadores top concentraron el {qatar_acum:.0f}% de Qatar 2022")

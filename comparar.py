# -*- coding: utf-8 -*-
"""Compara modelo viejo (Poisson puro) vs nuevo (DixonColes + prior historico)"""
import sys
sys.stdout.reconfigure(encoding="utf-8")
from scipy.stats import poisson
from scipy.optimize import fminbound
from modelo import predecir, estimate_total_xg, team_xgs


def poisson_puro(o1, ox, o2, over):
    """El modelo viejo: Poisson independiente, sin nada mas."""
    total = estimate_total_xg(over)
    xg1, xg2 = team_xgs(total, o1, o2)
    sc = {}
    for i in range(7):
        for j in range(7):
            sc[f"{i}-{j}"] = round(poisson.pmf(i, xg1) * poisson.pmf(j, xg2) * 100, 1)
    return sorted(sc.items(), key=lambda x: -x[1])


# Caso real: Mexico vs Sudafrica (cuotas que vimos)
o1, ox, o2, over = 2.10, 3.20, 3.50, 1.95

print("=" * 56)
print("  Mexico vs Sudafrica  (cuotas 2.10 / 3.20 / 3.50, Over 1.95)")
print("=" * 56)

viejo = poisson_puro(o1, ox, o2, over)
nuevo, _ = predecir(o1, ox, o2, over)

print(f"\n{'POISSON PURO (viejo)':<28}{'CON PRIOR MUNDIAL (nuevo)':<28}")
print("-" * 56)
for k in range(6):
    sv, pv = viejo[k]
    sn, pn = nuevo[k]
    print(f"  {k+1}. {sv:<6} {pv:>5}%        {k+1}. {sn:<6} {pn:>5}%")

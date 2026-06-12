# -*- coding: utf-8 -*-
"""
Modelo de prediccion de marcadores para el Mundial.

Combina 3 fuentes de informacion:
  1. Las cuotas del partido (quien gana, cuantos goles se esperan)
  2. Correccion Dixon-Coles (ajusta Poisson para marcadores bajos)
  3. Prior historico de marcadores del Mundial (964 partidos)

P_final(i,j) = (1-W) * Poisson_DixonColes(i,j) + W * Historico(i,j)
"""

from scipy.stats import poisson
from scipy.optimize import fminbound

MAX_GOALS = 8           # rango de goles a considerar por equipo
RHO = -0.08             # parametro Dixon-Coles (negativo: sube empates bajos)
W_HIST = 0.45           # peso del prior historico en el blend
                        # (las cuotas deciden quien/cuantos; el prior corrige la forma.
                        #  el backtest sobre Qatar favorece W alto, pero eso ignora que
                        #  en el bot real las cuotas aportan senal por-partido -> 0.45 equilibra)

# --- Prior historico del Mundial (marcador ordenado ganador-perdedor), 964 partidos ---
HIST_NODRAW = {
    (1,0):182,(2,1):152,(2,0):111,(3,1):68,(3,0):57,(3,2):43,(4,1):31,
    (4,0):24,(4,2):17,(6,1):11,(5,2):9,(5,0):7,(5,1):7,(6,0):5,(7,0):5,
    (4,3):3,(7,1):3,(8,1):3,(6,3):2,(9,0):2,(5,3):1,(6,2):1,(7,2):1,
    (7,3):1,(6,5):1,(8,3):1,(10,1):1,(7,5):1,
}
HIST_DRAW = {(0,0):78,(1,1):92,(2,2):35,(3,3):7,(4,4):2}

_TOT_NODRAW = sum(HIST_NODRAW.values())   # 750
_TOT_DRAW   = sum(HIST_DRAW.values())     # 214


# ==================== CUOTAS -> PROBABILIDADES ====================

def _no_vig(o1, ox, o2):
    """Quita el margen de la casa y devuelve probabilidades 1/X/2 que suman 1."""
    p1, px, p2 = 1/o1, 1/ox, 1/o2
    s = p1 + px + p2
    return p1/s, px/s, p2/s


def estimate_total_xg(over_odds):
    """Goles totales esperados a partir de la cuota Over 2.5."""
    target = 1 / over_odds
    def err(xg):
        return abs((1 - poisson.cdf(2, xg)) - target)
    return round(fminbound(err, 0.5, 5.0), 3)


def team_xgs(total_xg, o1, o2):
    """Reparte el xG total entre local y visitante segun cuotas 1 y 2."""
    p1, p2 = 1/o1, 1/o2
    xg1 = total_xg * p1 / (p1 + p2)
    xg2 = total_xg * p2 / (p1 + p2)
    return xg1, xg2


# ==================== COMPONENTE 1: POISSON + DIXON-COLES ====================

def _dc_tau(i, j, lam, mu, rho):
    """Factor de correccion Dixon-Coles para los 4 marcadores bajos."""
    if i == 0 and j == 0:
        return 1 - lam * mu * rho
    if i == 0 and j == 1:
        return 1 + lam * rho
    if i == 1 and j == 0:
        return 1 + mu * rho
    if i == 1 and j == 1:
        return 1 - rho
    return 1.0


def matriz_poisson_dc(xg1, xg2):
    """Matriz de probabilidad de marcador con correccion Dixon-Coles."""
    M = {}
    total = 0.0
    for i in range(MAX_GOALS + 1):
        for j in range(MAX_GOALS + 1):
            p = poisson.pmf(i, xg1) * poisson.pmf(j, xg2) * _dc_tau(i, j, xg1, xg2, RHO)
            M[(i, j)] = p
            total += p
    # renormalizar (la correccion DC rompe ligeramente la suma=1)
    for k in M:
        M[k] /= total
    return M


# ==================== COMPONENTE 2: PRIOR HISTORICO ====================

PESO_RESULTADO_REAL = 5   # cada resultado real del Mundial pesa como N historicos


def matriz_historica(p1, px, p2, extra_nodraw=None, extra_draw=None):
    """
    Construye matriz de marcador desde el prior historico del Mundial,
    orientada segun quien es favorito (p1 = prob local gana, p2 = visitante).

    extra_nodraw / extra_draw: frecuencias de resultados REALES ya jugados
    (forma ordenada ganador-perdedor). Se suman al prior con mas peso, para
    que el modelo aprenda de lo que paso en este Mundial.
    """
    # combinar prior base + resultados reales (ponderados)
    nodraw = dict(HIST_NODRAW)
    draw = dict(HIST_DRAW)
    if extra_nodraw:
        for k, v in extra_nodraw.items():
            nodraw[k] = nodraw.get(k, 0) + v * PESO_RESULTADO_REAL
    if extra_draw:
        for k, v in extra_draw.items():
            draw[k] = draw.get(k, 0) + v * PESO_RESULTADO_REAL

    tot_nodraw = sum(nodraw.values())
    tot_draw = sum(draw.values())

    M = {}
    for i in range(MAX_GOALS + 1):
        for j in range(MAX_GOALS + 1):
            M[(i, j)] = 0.0

    # No-empates: el prior (a-b, a>b) se reparte entre "gana local" y "gana visitante"
    for (a, b), f in nodraw.items():
        if a > MAX_GOALS or b > MAX_GOALS:
            continue
        cond = f / tot_nodraw            # P(marcador a-b | hubo ganador)
        M[(a, b)] += p1 * cond           # local gana a-b
        M[(b, a)] += p2 * cond           # visitante gana a-b

    # Empates
    for (a, _a2), f in draw.items():
        if a > MAX_GOALS:
            continue
        M[(a, a)] += px * (f / tot_draw)

    return M


# ==================== BLEND FINAL ====================

def ajustar_btts(M, xg1, xg2, btts_si_odds):
    """
    Reescala las probabilidades usando la cuota BTTS Si.
    Sube marcadores donde ambos equipos anotan (i>0 y j>0),
    baja los que tienen un equipo en cero.
    """
    p_btts = min(max(1.0 / btts_si_odds, 0.05), 0.95)

    # probabilidad actual de BTTS segun la matriz
    p_btts_actual = sum(p for (i, j), p in M.items() if i > 0 and j > 0)
    if p_btts_actual <= 0 or p_btts_actual >= 1:
        return M

    # factor de escala: cuanto subir los marcadores BTTS vs los no-BTTS
    scale_btts     = p_btts / p_btts_actual
    scale_no_btts  = (1 - p_btts) / (1 - p_btts_actual)

    M2 = {}
    for (i, j), p in M.items():
        if i > 0 and j > 0:
            M2[(i, j)] = p * scale_btts
        else:
            M2[(i, j)] = p * scale_no_btts

    # renormalizar
    total = sum(M2.values())
    return {k: v / total for k, v in M2.items()}


def predecir(o1, ox, o2, over_odds, btts_si_odds=None, w_hist=W_HIST, extra_nodraw=None, extra_draw=None):
    """
    Devuelve lista [(marcador, prob_%)] ordenada de mayor a menor,
    combinando Poisson+DixonColes con el prior historico del Mundial.

    btts_si_odds: cuota Bet365 "Ambos equipos anotan - Si" (opcional).
    extra_nodraw / extra_draw: resultados reales ya jugados (del historial).
    """
    p1, px, p2 = _no_vig(o1, ox, o2)

    total_xg = estimate_total_xg(over_odds)
    xg1, xg2 = team_xgs(total_xg, o1, o2)

    M_dc   = matriz_poisson_dc(xg1, xg2)
    M_hist = matriz_historica(p1, px, p2, extra_nodraw, extra_draw)

    final = {}
    for k in M_dc:
        final[k] = (1 - w_hist) * M_dc[k] + w_hist * M_hist[k]

    # ajuste BTTS si se provee la cuota
    if btts_si_odds is not None:
        final = ajustar_btts(final, xg1, xg2, btts_si_odds)

    # ordenar y formatear
    ranking = sorted(final.items(), key=lambda x: -x[1])
    return [(f"{i}-{j}", round(p * 100, 1)) for (i, j), p in ranking], (xg1, xg2, total_xg)


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    # Ejemplo: partido parejo
    ranking, (xg1, xg2, txg) = predecir(2.10, 3.20, 3.50, 1.95)
    print(f"xG: local {xg1:.2f} - visitante {xg2:.2f} (total {txg})")
    print("\nTop 8 marcadores:")
    for score, prob in ranking[:8]:
        print(f"  {score}: {prob}%")

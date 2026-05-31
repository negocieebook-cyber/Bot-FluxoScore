from pathlib import Path

import matplotlib.pyplot as plt

from banco import conectar


BASE_DIR = Path(__file__).resolve().parent
SAIDA_RRG = BASE_DIR / "saidas" / "rrg_setorial.png"


def _carregar_scores_setor():
    with conectar() as conn:
        dados = conn.execute(
            """
            SELECT setor, data_semana, rs_ratio, rs_momentum
            FROM scores_setor
            ORDER BY data_semana
            """
        ).fetchall()

    if not dados:
        raise ValueError("scores_setor vazio; calcule os scores setoriais antes do RRG")
    return dados


def gerar_rrg_setorial(semanas_cauda=12):
    dados = _carregar_scores_setor()
    por_setor = {}
    for setor, data_semana, rs_ratio, rs_momentum in dados:
        por_setor.setdefault(setor, []).append((data_semana, rs_ratio, rs_momentum))

    fig, ax = plt.subplots(figsize=(11, 8))
    ax.axvline(100, color="black", linewidth=1)
    ax.axhline(100, color="black", linewidth=1)

    ax.text(100.5, 100.5, "Leading", fontsize=11, weight="bold")
    ax.text(100.5, 99.5, "Weakening", fontsize=11, weight="bold", va="top")
    ax.text(99.5, 100.5, "Improving", fontsize=11, weight="bold", ha="right")
    ax.text(99.5, 99.5, "Lagging", fontsize=11, weight="bold", ha="right", va="top")

    xs = []
    ys = []
    for setor, pontos in por_setor.items():
        cauda = pontos[-semanas_cauda:]
        x = [ponto[1] for ponto in cauda]
        y = [ponto[2] for ponto in cauda]
        xs.extend(x)
        ys.extend(y)
        ax.plot(x, y, marker="o", linewidth=1.8, markersize=4, label=setor)
        ax.annotate(setor, (x[-1], y[-1]), xytext=(4, 4), textcoords="offset points", fontsize=9)

    margem_x = max(2.0, (max(xs) - min(xs)) * 0.15) if xs else 2.0
    margem_y = max(2.0, (max(ys) - min(ys)) * 0.15) if ys else 2.0
    ax.set_xlim(min(min(xs) - margem_x, 96), max(max(xs) + margem_x, 104))
    ax.set_ylim(min(min(ys) - margem_y, 96), max(max(ys) + margem_y, 104))
    ax.set_xlabel("RS-Ratio setorial")
    ax.set_ylabel("RS-Momentum setorial")
    ax.set_title("RRG Setorial B3 vs BOVA11")
    ax.grid(True, alpha=0.25)
    ax.legend(loc="best", fontsize=8)

    SAIDA_RRG.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(SAIDA_RRG, dpi=160)
    plt.close(fig)
    return SAIDA_RRG

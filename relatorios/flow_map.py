import base64
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright

from banco import conectar, criar_tabelas
from config import SETORES
from rrg import SAIDA_RRG, gerar_rrg_setorial
from setor import quadrante_rrg
from relatorios.narrativa import (
    flag_tape,
    leitura_acao,
    qualidade_dados,
    retorno_semanal,
)
from relatorios.narrativa_ia import gerar_leitura_estrategica


BASE_DIR = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = BASE_DIR / "templates"
SAIDAS_DIR = BASE_DIR / "saidas"


# ── Leitura do banco (inalterado) ─────────────────────────────────────────────

def _linha_para_dict(linha):
    return {
        "setor": linha[0],
        "data_semana": linha[1],
        "score": float(linha[2]),
        "cf": float(linha[3]),
        "trend": float(linha[4]),
        "mom": float(linha[5]),
        "rs_ratio": float(linha[6]),
        "rs_momentum": float(linha[7]),
        "volume_relative": float(linha[8]),
        "confirmacao_interna": linha[9],
        "quadrante": quadrante_rrg(float(linha[6]), float(linha[7])),
    }


def _data_mais_recente():
    with conectar() as conn:
        data = conn.execute("SELECT MAX(data_semana) FROM scores_setor").fetchone()[0]
    if not data:
        raise ValueError("scores_setor vazio; gere os scores setoriais antes do PDF")
    return data


def _ranking(data_semana):
    with conectar() as conn:
        linhas = conn.execute(
            """
            SELECT setor, data_semana, score, cf, trend, mom,
                   rs_ratio, rs_momentum, volume_relative, confirmacao_interna
            FROM scores_setor
            WHERE data_semana = ?
            ORDER BY score DESC
            """,
            (data_semana,),
        ).fetchall()

    ranking = [_linha_para_dict(linha) for linha in linhas]
    for item in ranking:
        item["lideranca_estreita"] = (
            item["score"] >= 60 and item["confirmacao_interna"].startswith("Fraca")
        )
    return ranking


def _market_gauge(ranking):
    fortes = sum(1 for item in ranking if item["score"] >= 60)
    if fortes >= 6:
        nome = "Verde"
        classe = "verde"
    elif fortes >= 4:
        nome = "Amarelo"
        classe = "amarelo"
    else:
        nome = "Vermelho"
        classe = "vermelho"
    return {"nome": nome, "classe": classe, "setores_fortes": fortes}


def _movers(data_semana):
    with conectar() as conn:
        anterior = conn.execute(
            "SELECT MAX(data_semana) FROM scores_setor WHERE data_semana < ?",
            (data_semana,),
        ).fetchone()[0]

        if not anterior:
            return {"historico_insuficiente": True}

        linhas = conn.execute(
            """
            SELECT atual.setor, atual.score - anterior.score AS delta
            FROM scores_setor atual
            JOIN scores_setor anterior
              ON anterior.setor = atual.setor
             AND anterior.data_semana = ?
            WHERE atual.data_semana = ?
            """,
            (anterior, data_semana),
        ).fetchall()

    deltas = [{"setor": setor, "delta": float(delta)} for setor, delta in linhas]
    altas = sorted(deltas, key=lambda item: item["delta"], reverse=True)[:3]
    quedas = sorted(deltas, key=lambda item: item["delta"])[:3]
    return {
        "historico_insuficiente": False,
        "altas": altas,
        "quedas": quedas,
        "linhas": max(len(altas), len(quedas)),
    }


def _rrg_base64():
    if not SAIDA_RRG.exists():
        gerar_rrg_setorial()
    encoded = base64.b64encode(SAIDA_RRG.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


# ── Seção 2: Ações que explicam os setores líderes ───────────────────────────

def _acoes_setores_lideres(data_semana, ranking):
    """
    Para cada setor com score>=60, retorna dados das ações do setor
    com leitura interpretativa por regra. Lê apenas o banco.
    """
    resultado = []

    for setor_item in ranking:
        if setor_item["score"] < 60:
            continue

        setor = setor_item["setor"]
        tickers = list(SETORES.get(setor, []))
        if not tickers:
            continue

        placeholders = ",".join("?" * len(tickers))
        with conectar() as conn:
            linhas = conn.execute(
                f"""
                SELECT ticker, score, rs_ratio, rs_momentum,
                       volume_relative, UDVR, DDVR
                FROM scores
                WHERE data_semana = ? AND ticker IN ({placeholders})
                ORDER BY score DESC
                """,
                [data_semana] + tickers,
            ).fetchall()

        acoes = []
        for row in linhas:
            ticker = row[0]
            score = float(row[1])
            rs_r = float(row[2] or 100)
            rs_m = float(row[3] or 100)
            vol = float(row[4] or 1)
            udvr = float(row[5] or 0)
            ddvr = float(row[6] or 0)

            ret = retorno_semanal(ticker, data_semana)
            ret_fmt = f"{ret:+.1f}%" if ret is not None else "N/D"
            ret_rel_val = rs_r - 100
            ret_rel = f"{ret_rel_val:+.1f}%"

            acoes.append({
                "ticker": ticker,
                "ret_sem": ret_fmt,
                "ret_rel": ret_rel,
                "rs_ratio": round(rs_r, 1),
                "rs_mom": round(rs_m, 1),
                "vol_rel": round(vol, 1),
                "score": round(score, 1),
                "tape": flag_tape(udvr, ddvr, score),
                "leitura": leitura_acao(score, rs_r, rs_m),
            })

        n_confirma = sum(1 for a in acoes if a["leitura"] == "Confirma o setor")
        n_total = len(acoes) or 1

        resultado.append({
            "setor": setor,
            "score": setor_item["score"],
            "confirmacao": setor_item["confirmacao_interna"],
            "n_confirma": n_confirma,
            "n_total": n_total,
            "acoes": acoes,
        })

    return resultado


# ── Seção 1: Leitura Estratégica ──────────────────────────────────────────────

def _leitura_estrategica(ranking, acoes_por_setor):
    """
    3 blocos interpretativos (Acionável / No Radar / Evitar)
    montados por regras a partir dos dados já calculados pelo motor.
    """
    acoes_mapa = {a["setor"]: a for a in acoes_por_setor}
    acionavel, no_radar, evitar = [], [], []

    for item in ranking:
        setor = item["setor"]
        score = item["score"]
        q = item["quadrante"]
        rs_mom = item["rs_momentum"]
        vol = item["volume_relative"]
        estreita = item["lideranca_estreita"]
        confirmacao = item["confirmacao_interna"]

        if score >= 60:
            acao_destaque = None
            if setor in acoes_mapa and acoes_mapa[setor]["acoes"]:
                top = acoes_mapa[setor]["acoes"][0]
                if top["score"] >= 60:
                    acao_destaque = top["ticker"]

            frase = (
                f"{setor} lidera com score {score:.0f}, "
                f"{confirmacao.lower()} das ações internas e volume {vol:.1f}x."
            )
            if acao_destaque:
                frase += f" {acao_destaque} puxa o movimento."

            acionavel.append({
                "setor": setor,
                "score": score,
                "frase": frase,
                "estreita": estreita,
            })

        elif q == "Improving" and rs_mom >= 100:
            falta = round(60 - score, 1)
            frase = (
                f"{setor} em transição (Improving, RS-Mom {rs_mom:.0f}). "
                f"Score {score:.0f} — faltam {falta} pts para o corte. "
                "Gatilho: cruzar 60 com confirmação ampla."
            )
            no_radar.append({"setor": setor, "score": score, "rs_mom": rs_mom, "frase": frase})

        if q == "Lagging":
            frase = (
                f"{setor} (Lagging, score {score:.0f}): fraqueza estrutural. "
                "Aguardar mudança de quadrante antes de reavaliar."
            )
            evitar.append({"setor": setor, "score": score, "frase": frase})

    return {"acionavel": acionavel, "no_radar": no_radar, "evitar": evitar}


def _fallback_texto_regras(leitura):
    partes = []
    if leitura["acionavel"]:
        setores = ", ".join(
            f"{item['setor']} ({item['score']:.1f})"
            for item in leitura["acionavel"][:2]
        )
        partes.append(f"A liderança da semana ficou concentrada em {setores}.")
    else:
        partes.append("A semana não mostrou liderança setorial clara acima do corte de score.")
    if leitura["no_radar"]:
        radar = ", ".join(item["setor"] for item in leitura["no_radar"][:3])
        partes.append(f"No radar, {radar} aparecem em transição e ainda precisam confirmar score.")
    if leitura["evitar"]:
        evitar = ", ".join(item["setor"] for item in leitura["evitar"][:3])
        partes.append(f"Na ponta fraca, {evitar} seguem sem confirmação relativa.")
    partes.append("A leitura é baseada apenas nos scores, quadrantes RRG, volume relativo e confirmação interna já calculados.")
    return " ".join(partes)


def _macro_disponivel():
    return {}


def _dados_para_ia(ranking, acoes_lideres, movers, leitura_regras):
    acoes_por_setor = {item["setor"]: item["acoes"][:3] for item in acoes_lideres}
    setores = [
        {
            "setor": item["setor"],
            "score": round(item["score"], 2),
            "quadrante": item["quadrante"],
            "confirmacao_interna": item["confirmacao_interna"],
            "volume_relative": round(item["volume_relative"], 2),
        }
        for item in ranking
    ]
    top_setores = []
    for setor in setores[:2]:
        top_setores.append(
            {
                **setor,
                "acoes_chave": [
                    {
                        "ticker": acao["ticker"],
                        "score": acao["score"],
                        "retorno_relativo": acao["ret_rel"],
                        "rs_momentum": acao["rs_mom"],
                    }
                    for acao in acoes_por_setor.get(setor["setor"], [])[:3]
                ],
            }
        )

    return {
        "setores": setores,
        "top_2_setores": top_setores,
        "biggest_movers": movers,
        "macro": _macro_disponivel(),
        "fallback_texto": _fallback_texto_regras(leitura_regras),
    }


# ── Seção 4: Lista de Observação ─────────────────────────────────────────────

def _lista_observacao(ranking):
    """
    Bullets de observação para a próxima semana — derivados do ranking setorial.
    """
    lideres, no_radar, evitar = [], [], []

    for item in ranking:
        score = item["score"]
        q = item["quadrante"]
        rs_mom = item["rs_momentum"]
        setor = item["setor"]
        vol = item["volume_relative"]

        if score >= 60:
            if item["lideranca_estreita"]:
                obs = (
                    f"{setor} (score {score:.0f}): liderança estreita — "
                    "verificar se confirmação interna amplia. "
                    "Se score cair abaixo de 60, reclassificar."
                )
            else:
                obs = (
                    f"{setor} (score {score:.0f}): monitorar volume relativo "
                    f"({vol:.1f}x) e confirmação interna. "
                    "Queda abaixo de 60 sinaliza saída da liderança."
                )
            lideres.append(obs)

        elif q == "Improving" and rs_mom >= 100:
            falta = round(60 - score, 1)
            obs = (
                f"{setor} (Improving, RS-Mom {rs_mom:.0f}, score {score:.0f}): "
                f"faltam {falta} pts. Gatilho: cruzar 60 com volume acima de 1x."
            )
            no_radar.append(obs)

        if q == "Lagging":
            obs = (
                f"{setor} (Lagging, score {score:.0f}): sem ação sugerida. "
                "Monitorar apenas se quadrante mudar para Weakening ou Improving."
            )
            evitar.append(obs)

    return {"lideres": lideres, "no_radar": no_radar, "evitar": evitar}


# ── Renderização e geração de PDF (inalterado) ────────────────────────────────

def _renderizar_html(contexto):
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("flow_map.html")
    return template.render(**contexto)


def _gerar_resumo(ranking, market_gauge):
    top3 = ", ".join(
        f"{item['setor']} {item['score']:.1f}" for item in ranking[:3]
    )
    alertas = [item["setor"] for item in ranking if item["lideranca_estreita"]]
    alerta_txt = (
        "Lideranca estreita: " + ", ".join(alertas)
        if alertas
        else "Sem alertas de lideranca estreita."
    )
    return "\n".join(
        [
            f"Top 3 setores: {top3}.",
            f"Market Gauge: {market_gauge['nome']} ({market_gauge['setores_fortes']} setores >=60).",
            alerta_txt,
        ]
    )


def gerar_flow_map_pdf():
    criar_tabelas()
    data_semana = _data_mais_recente()
    ranking = _ranking(data_semana)
    market_gauge = _market_gauge(ranking)
    movers = _movers(data_semana)

    # Novas seções (leitura do banco, sem tocar no motor)
    acoes_lideres = _acoes_setores_lideres(data_semana, ranking)
    leitura_estrategica = _leitura_estrategica(ranking, acoes_lideres)
    leitura_estrategica["paragrafo"] = gerar_leitura_estrategica(
        _dados_para_ia(ranking, acoes_lideres, movers, leitura_estrategica)
    )
    observacao = _lista_observacao(ranking)
    qualidade = qualidade_dados(data_semana)

    contexto = {
        "data_semana": data_semana,
        "ranking": ranking,
        "market_gauge": market_gauge,
        "movers": movers,
        "leitura_estrategica": leitura_estrategica,
        "acoes_lideres": acoes_lideres,
        "observacao": observacao,
        "qualidade": qualidade,
        "rrg_src": _rrg_base64(),
    }
    html = _renderizar_html(contexto)

    data_nome = datetime.strptime(data_semana, "%Y-%m-%d").strftime("%Y%m%d")
    SAIDAS_DIR.mkdir(parents=True, exist_ok=True)
    caminho_pdf = SAIDAS_DIR / f"flow_map_{data_nome}.pdf"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html, wait_until="networkidle")
        page.pdf(path=str(caminho_pdf), format="A4", print_background=True)
        browser.close()

    return caminho_pdf, _gerar_resumo(ranking, market_gauge)


if __name__ == "__main__":
    pdf, resumo = gerar_flow_map_pdf()
    print(f"PDF gerado: {pdf}")
    print(resumo)

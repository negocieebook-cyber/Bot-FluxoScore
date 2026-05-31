from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright

from banco import carregar_fundamentos, conectar, criar_tabelas
from config import SETORES
from relatorios.capital_flow_leaders import _formatar_dinheiro, _preco_e_adv
from relatorios.narrativa import qualidade_dados


BASE_DIR = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = BASE_DIR / "templates"
SAIDAS_DIR = BASE_DIR / "saidas"


# ── Helpers existentes (inalterados) ──────────────────────────────────────────

def _ticker_setor():
    return {
        ticker: setor
        for setor, tickers in SETORES.items()
        for ticker in tickers
    }


def _datas_scores():
    with conectar() as conn:
        return [
            linha[0]
            for linha in conn.execute(
                "SELECT DISTINCT data_semana FROM scores ORDER BY data_semana"
            ).fetchall()
        ]


def _scores(data_semana):
    with conectar() as conn:
        linhas = conn.execute(
            """
            SELECT ticker, score, cf, trend, mom, DDVR, up_day_vol_pct
            FROM scores
            WHERE data_semana = ?
            """,
            (data_semana,),
        ).fetchall()
    return {
        linha[0]: {
            "ticker": linha[0],
            "score": float(linha[1]),
            "cf": float(linha[2]),
            "trend": float(linha[3]),
            "mom": float(linha[4]),
            "DDVR": float(linha[5] or 0),
            "up_day_vol_pct": float(linha[6] or 0),
        }
        for linha in linhas
    }


def _flags_e_narrativa(item):
    flags = []
    if item["DDVR"] >= 1.5:
        flags.append("DISTRIBUTION PATTERN")

    flags_txt = " | ".join(flags) if flags else "sem flags ativas"
    if flags:
        leitura = "Distribuição: DDVR alto indica pressão relevante nos dias de queda."
    else:
        leitura = "Sem DDVR alto; a leitura parece mais perda de momentum do que venda institucional agressiva."
    narrativa = (
        f"Era {item['score_anterior']:.1f}, agora {item['score']:.1f}, "
        f"queda de {item['queda_score']:.1f} pontos. {leitura}"
    )
    return flags, flags_txt, narrativa


def _saidas(data_atual, data_anterior):
    setor_por_ticker = _ticker_setor()
    atual = _scores(data_atual)
    anterior = _scores(data_anterior)
    saidas = []

    for ticker, item in atual.items():
        if ticker not in setor_por_ticker or ticker not in anterior:
            continue
        score_anterior = anterior[ticker]["score"]
        queda_score = score_anterior - item["score"]
        queda_forte = queda_score >= 8
        cruzou_abaixo = score_anterior >= 60 and item["score"] < 60
        if not queda_forte and not cruzou_abaixo:
            continue

        preco, adv = _preco_e_adv(ticker)
        fundamentos = carregar_fundamentos(ticker) or {}
        item["setor"] = setor_por_ticker[ticker]
        item["score_anterior"] = score_anterior
        item["queda_score"] = queda_score
        item["preco_fmt"] = f"R$ {preco:.2f}" if preco is not None else "N/D"
        item["market_cap_fmt"] = _formatar_dinheiro(fundamentos.get("market_cap"))
        item["adv_fmt"] = _formatar_dinheiro(adv)
        item["down_day_vol_pct"] = max(0.0, 100.0 - item["up_day_vol_pct"])
        flags, flags_txt, narrativa = _flags_e_narrativa(item)
        item["flags"] = flags
        item["flags_txt"] = flags_txt
        item["narrativa"] = narrativa
        saidas.append(item)

    return sorted(saidas, key=lambda item: item["queda_score"], reverse=True)


# ── Seção 4: Lista de Observação ─────────────────────────────────────────────

def _lista_observacao_sme(saidas):
    """
    Bullets de observação derivados das saídas detectadas.
    Montado por regras — nenhuma IA.
    """
    if not saidas:
        return {"acoes": [], "setores": []}

    obs_acoes = []
    for item in saidas:
        ddvr = item["DDVR"]
        queda = item["queda_score"]
        if "DISTRIBUTION PATTERN" in item["flags"]:
            obs = (
                f"{item['ticker']} ({item['setor']}, queda {queda:.0f} pts): "
                f"DDVR {ddvr:.1f}x indica distribuição ativa. "
                "Aguardar normalização de volume antes de reavaliar."
            )
        else:
            obs = (
                f"{item['ticker']} ({item['setor']}, queda {queda:.0f} pts): "
                "deterioração de momentum/tendência sem distribuição confirmada. "
                "Monitorar se score se estabiliza ou continua caindo."
            )
        obs_acoes.append(obs)

    # Contexto setorial: setores com 2+ saídas
    contagem_setor = {}
    for item in saidas:
        contagem_setor[item["setor"]] = contagem_setor.get(item["setor"], 0) + 1

    obs_setores = []
    for setor, n in sorted(contagem_setor.items(), key=lambda x: -x[1]):
        if n >= 2:
            obs_setores.append(
                f"{setor}: {n} ações em saída — possível fraqueza setorial."
                " Verificar score do setor no Flow Map."
            )

    return {"acoes": obs_acoes, "setores": obs_setores}


# ── Renderização e geração de PDF ─────────────────────────────────────────────

def _renderizar_html(contexto):
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(["html"]),
    )
    return env.get_template("smart_money_exits.html").render(**contexto)


def _resumo(saidas, historico_insuficiente):
    if historico_insuficiente:
        return "Smart Money Exits: histórico insuficiente para detectar saídas — necessário 2+ semanas de dados."
    if not saidas:
        return "Smart Money Exits: 0 ações acionaram critério de saída nesta semana."

    top3 = ", ".join(f"{item['ticker']} -{item['queda_score']:.1f}" for item in saidas[:3])
    distribuicao = [item["ticker"] for item in saidas if "DISTRIBUTION PATTERN" in item["flags"]]
    linhas = [
        f"Smart Money Exits: {len(saidas)} ações acionaram critério de saída.",
        f"Maiores quedas: {top3}.",
    ]
    if distribuicao:
        linhas.append("Distribuição: " + ", ".join(distribuicao[:5]) + ".")
    else:
        linhas.append("Sem flags de distribuição; deterioração parece mais momentum/trend.")
    return "\n".join(linhas)


def gerar_smart_money_exits_pdf():
    criar_tabelas()
    datas = _datas_scores()
    if not datas:
        raise ValueError("scores vazio; calcule os scores antes do relatorio")

    data_atual = datas[-1]
    historico_insuficiente = len(datas) < 2
    saidas = [] if historico_insuficiente else _saidas(data_atual, datas[-2])

    observacao = _lista_observacao_sme(saidas)
    qualidade = qualidade_dados(data_atual)

    html = _renderizar_html(
        {
            "data_semana": data_atual,
            "historico_insuficiente": historico_insuficiente,
            "saidas": saidas,
            "observacao": observacao,
            "qualidade": qualidade,
        }
    )
    data_nome = datetime.strptime(data_atual, "%Y-%m-%d").strftime("%Y%m%d")
    SAIDAS_DIR.mkdir(parents=True, exist_ok=True)
    caminho_pdf = SAIDAS_DIR / f"smart_money_exits_{data_nome}.pdf"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html, wait_until="networkidle")
        page.pdf(path=str(caminho_pdf), format="A4", print_background=True)
        browser.close()

    return caminho_pdf, _resumo(saidas, historico_insuficiente)

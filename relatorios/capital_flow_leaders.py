from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright

from banco import conectar, criar_tabelas
from coleta import coletar_fundamentos
from config import (
    MIN_MARKET_CAP,
    MIN_PRECO,
    MIN_VOLUME_DIARIO,
    SETORES,
)
from metricas import calcular_metricas
from tape import calcular_tape
from relatorios.narrativa import checa_negociabilidade, qualidade_dados


BASE_DIR = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = BASE_DIR / "templates"
SAIDAS_DIR = BASE_DIR / "saidas"


# ── Helpers existentes (inalterados) ──────────────────────────────────────────

def _ticker_setor():
    mapa = {}
    for setor, tickers in SETORES.items():
        for ticker in tickers:
            mapa[ticker] = setor
    return mapa


def _data_mais_recente():
    with conectar() as conn:
        data = conn.execute("SELECT MAX(data_semana) FROM scores").fetchone()[0]
    if not data:
        raise ValueError("scores vazio; calcule os scores individuais antes do relatorio")
    return data


def _scores_da_semana(data_semana):
    with conectar() as conn:
        linhas = conn.execute(
            """
            SELECT ticker, score, cf, trend, mom, rs_ratio, rs_momentum,
                   volume_relative, UDVR, DDVR, up_day_vol_pct
            FROM scores
            WHERE data_semana = ?
            """,
            (data_semana,),
        ).fetchall()

    return [
        {
            "ticker": linha[0],
            "score": float(linha[1]),
            "cf": float(linha[2]),
            "trend": float(linha[3]),
            "mom": float(linha[4]),
            "rs_ratio": float(linha[5]),
            "rs_momentum": float(linha[6]),
            "volume_relative": float(linha[7]),
            "UDVR": float(linha[8] or 0),
            "DDVR": float(linha[9] or 0),
            "up_day_vol_pct": float(linha[10] or 0),
        }
        for linha in linhas
    ]


def _score_anterior(ticker, data_semana):
    with conectar() as conn:
        linha = conn.execute(
            """
            SELECT score FROM scores
            WHERE ticker = ? AND data_semana < ?
            ORDER BY data_semana DESC LIMIT 1
            """,
            (ticker, data_semana),
        ).fetchone()
    return float(linha[0]) if linha else None


def _preco_e_adv(ticker):
    with conectar() as conn:
        preco = conn.execute(
            "SELECT fechamento FROM precos WHERE ticker = ?"
            " ORDER BY data DESC LIMIT 1",
            (ticker,),
        ).fetchone()
        volumes = conn.execute(
            "SELECT fechamento, volume FROM precos WHERE ticker = ?"
            " ORDER BY data DESC LIMIT 30",
            (ticker,),
        ).fetchall()

    if not preco or not volumes:
        return None, None
    adv = sum(float(item[0]) * float(item[1]) for item in volumes) / len(volumes)
    return float(preco[0]), adv


def _qtd_pregoes(ticker):
    with conectar() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM precos WHERE ticker = ?",
            (ticker,),
        ).fetchone()[0]


def _formatar_dinheiro(valor):
    if valor is None:
        return "N/D"
    if valor >= 1e9:
        return f"R$ {valor / 1e9:.1f} bi"
    if valor >= 1e6:
        return f"R$ {valor / 1e6:.1f} mi"
    return f"R$ {valor:.2f}"


def _formatar_numero(valor):
    if valor is None:
        return "N/D"
    if valor >= 1e6:
        return f"{valor / 1e6:.1f} mi"
    if valor >= 1e3:
        return f"{valor / 1e3:.1f} mil"
    return f"{valor:.0f}"


def _flags_e_narrativa(item):
    tape = calcular_tape(item["ticker"], data_semana=item["data_semana"], score=item["score"])
    flags = tape["flags"]
    item.update(tape)

    if flags:
        flags_txt = " | ".join(flags)
    else:
        flags_txt = "sem flags ativas"

    partes = [
        f"Fluxo, tendencia e momentum estao alinhados com score {item['score']:.1f}, acima do corte de lideranca.",
        f"A acao bateu o BOVA11 na semana e mantem RS-Momentum em {item['rs_momentum']:.1f}.",
    ]
    if "TAPE DISAGREES" in flags:
        partes.append("Contradicao: score alto, mas o tape discorda por UDVR fraco.")
    elif "ACCUMULATION CONFIRMED" in flags:
        partes.append("Acumulacao confirmada: dias de alta vieram com volume relativo forte.")
    elif "ACCUMULATION PATTERN" in flags:
        partes.append("Ha padrao de acumulacao, mas ainda sem confirmacao maxima.")
    elif item["DDVR"] > item["UDVR"]:
        partes.append("Tape misto: DDVR supera UDVR, entao a lideranca pede acompanhamento.")
    else:
        partes.append("Tape coerente com a leitura de lideranca.")

    return flags_txt, " ".join(partes)


def _passa_filtro(item):
    if item["score"] < 60 or item["rs_momentum"] < 100:
        return False

    semanal, _diario = calcular_metricas(item["ticker"])
    ultima = semanal.dropna(subset=["relative_return"]).iloc[-1]
    item["relative_return"] = float(ultima["relative_return"])
    if item["relative_return"] <= 0:
        return False

    preco, adv = _preco_e_adv(item["ticker"])
    item["preco"] = preco
    item["adv"] = adv
    item["qtd_pregoes"] = _qtd_pregoes(item["ticker"])
    item["sma200_parcial"] = item["qtd_pregoes"] < 200
    if preco is None or adv is None:
        return False
    if preco < MIN_PRECO or adv < MIN_VOLUME_DIARIO:
        return False

    fundamentos = coletar_fundamentos(item["ticker"])
    item["market_cap"] = fundamentos["market_cap"]
    return item["market_cap"] >= MIN_MARKET_CAP


def _lideres(data_semana):
    setor_por_ticker = _ticker_setor()
    candidatos = []

    for item in _scores_da_semana(data_semana):
        if item["ticker"] not in setor_por_ticker:
            continue
        item["data_semana"] = data_semana
        item["setor"] = setor_por_ticker[item["ticker"]]
        try:
            if not _passa_filtro(item):
                continue
        except Exception as erro:
            item["erro_filtro"] = str(erro)
            continue

        anterior = _score_anterior(item["ticker"], data_semana)
        item["score_anterior"] = anterior
        item["delta_score"] = item["score"] - anterior if anterior is not None else 0.0
        flags_txt, narrativa = _flags_e_narrativa(item)
        item["flags_txt"] = flags_txt
        item["narrativa"] = narrativa
        item["preco_fmt"] = f"R$ {item['preco']:.2f}"
        item["market_cap_fmt"] = _formatar_dinheiro(item["market_cap"])
        item["adv_fmt"] = _formatar_dinheiro(item["adv"])
        candidatos.append(item)

    candidatos.sort(key=lambda item: (item["score"], item["delta_score"]), reverse=True)

    por_setor = {}
    filtrados = []
    for item in candidatos:
        qtd = por_setor.get(item["setor"], 0)
        if qtd >= 3:
            continue
        por_setor[item["setor"]] = qtd + 1
        filtrados.append(item)
    return filtrados


# ── Seção 3: Quase Lá ─────────────────────────────────────────────────────────

def _quase_la(data_semana, tickers_lideres):
    """
    Ações que passam 3 dos 4 critérios de liderança — "a um passo".
    Usa apenas dados do banco; não chama o motor de cálculo.
    Os 4 critérios (versão DB-only):
      1. score >= 60
      2. rs_momentum >= 100
      3. rs_ratio > 100  (proxy: retorno relativo positivo)
      4. negociabilidade: preço, ADV e market cap dentro dos limiares
    """
    setor_por_ticker = _ticker_setor()

    with conectar() as conn:
        linhas = conn.execute(
            "SELECT ticker, score, rs_ratio, rs_momentum FROM scores WHERE data_semana = ?",
            (data_semana,),
        ).fetchall()

    candidatos = []

    for row in linhas:
        ticker = row[0]
        if ticker not in setor_por_ticker or ticker in tickers_lideres:
            continue

        score = float(row[1])
        rs_r = float(row[2] or 100)
        rs_m = float(row[3] or 100)

        ok_score = score >= 60
        ok_mom = rs_m >= 100
        ok_rel = rs_r > 100
        ok_trade, motivo_trade = checa_negociabilidade(ticker)

        perto_do_corte = score >= 50 or (60 - score) <= 10
        if not perto_do_corte:
            continue

        n_ok = sum([ok_score, ok_mom, ok_rel, ok_trade])
        if n_ok < 3:
            continue     # muito longe
        if n_ok == 4:
            continue     # passou tudo (deveria estar em lideres; filtro de mercado pode diferir)

        if not ok_score:
            falta = f"score {score:.0f} — faltam {60 - score:.1f} pts para o corte de 60"
            criterio = "score"
        elif not ok_mom:
            falta = f"RS-Momentum {rs_m:.0f} < 100 (momentum ainda acelerando)"
            criterio = "momentum"
        elif not ok_rel:
            falta = f"retorno relativo negativo vs BOVA11 (RS-Ratio {rs_r:.1f} < 100)"
            criterio = "retorno_relativo"
        else:
            falta = motivo_trade
            criterio = "negociabilidade"

        candidatos.append({
            "ticker": ticker,
            "setor": setor_por_ticker[ticker],
            "score": round(score, 1),
            "rs_mom": round(rs_m, 1),
            "rs_ratio": round(rs_r, 1),
            "falta": falta,
            "criterio": criterio,
        })

    # Ordenar: score mais alto primeiro
    candidatos.sort(key=lambda x: x["score"], reverse=True)
    return candidatos[:12]


# ── Seção 4: Lista de Observação ──────────────────────────────────────────────

def _lista_observacao_cfl(lideres, quase_la):
    """
    Bullets de observação para a próxima semana — baseados em regras.
    """
    obs_lideres = []
    for item in lideres:
        flags = " | ".join(item.get("flags", [])) if item.get("flags") else ""
        if flags:
            obs = (
                f"{item['ticker']} (score {item['score']:.0f}, {item['setor']}): "
                f"manter monitoramento. Flags: {flags}."
            )
        else:
            obs = (
                f"{item['ticker']} (score {item['score']:.0f}, {item['setor']}): "
                "verificar tape e retorno relativo na próxima sessão."
            )
        obs_lideres.append(obs)

    return {"lideres": obs_lideres, "quase_la": []}


# ── Renderização e geração de PDF ─────────────────────────────────────────────

def _renderizar_html(contexto):
    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(["html"]),
    )
    return env.get_template("capital_flow_leaders.html").render(**contexto)


def _resumo(lideres):
    if not lideres:
        return "\n".join(
            [
                "Capital Flow Leaders: 0 acoes passaram nos criterios desta semana.",
                "Nenhuma acao cumpre score>=60, retorno relativo positivo, RS-Momentum>=100 e filtros de negociabilidade.",
            ]
        )

    top3 = ", ".join(f"{item['ticker']} {item['score']:.1f}" for item in lideres[:3])
    flags = []
    for item in lideres:
        relevantes = [
            flag
            for flag in item["flags"]
            if flag in ("ACCUMULATION PATTERN", "ACCUMULATION CONFIRMED", "TAPE DISAGREES")
        ]
        if relevantes:
            flags.append(f"{item['ticker']}: {'/'.join(relevantes)}")

    linhas = [
        f"Capital Flow Leaders: {len(lideres)} acoes passaram nos criterios.",
        f"Top 3: {top3}.",
    ]
    if flags:
        linhas.append("Flags relevantes: " + "; ".join(flags[:4]) + ".")
    else:
        linhas.append("Sem flags relevantes de acumulacao ou divergencia no tape.")
    return "\n".join(linhas)


def gerar_capital_flow_leaders_pdf():
    criar_tabelas()
    data_semana = _data_mais_recente()
    lideres = _lideres(data_semana)

    tickers_lideres = {item["ticker"] for item in lideres}
    quase_la = _quase_la(data_semana, tickers_lideres)
    observacao = _lista_observacao_cfl(lideres, quase_la)
    qualidade = qualidade_dados(data_semana)

    html = _renderizar_html({
        "data_semana": data_semana,
        "lideres": lideres,
        "quase_la": quase_la,
        "observacao": observacao,
        "qualidade": qualidade,
    })
    data_nome = datetime.strptime(data_semana, "%Y-%m-%d").strftime("%Y%m%d")
    SAIDAS_DIR.mkdir(parents=True, exist_ok=True)
    caminho_pdf = SAIDAS_DIR / f"capital_flow_leaders_{data_nome}.pdf"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html, wait_until="networkidle")
        page.pdf(path=str(caminho_pdf), format="A4", print_background=True)
        browser.close()

    return caminho_pdf, _resumo(lideres)


if __name__ == "__main__":
    pdf, resumo = gerar_capital_flow_leaders_pdf()
    print(f"PDF gerado: {pdf}")
    print(resumo)

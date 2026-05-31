from banco import conectar, criar_tabelas
from coleta import coletar
try:
    from config import BENCHMARK, SETORES, TODOS_OS_TICKERS
except ModuleNotFoundError:
    from config_base import BENCHMARK, SETORES, TODOS_OS_TICKERS
from metricas import calcular_metricas, calcular_metricas_diarias
from relatorios.alerta_diario import gerar_alerta_diario_pdf
from score import calcular_score


def coletar_tudo():
    sucessos = 0
    falhas = {}
    for ticker in TODOS_OS_TICKERS:
        try:
            coletar(ticker)
            sucessos += 1
        except Exception as erro:
            falhas[ticker] = str(erro)
            print(f"{ticker}: erro na coleta ({erro})")
    return sucessos, falhas


def recalcular_scores():
    sucessos = 0
    falhas = {}
    for ticker in TODOS_OS_TICKERS:
        try:
            calcular_score(ticker, gravar=True)
            sucessos += 1
        except Exception as erro:
            falhas[ticker] = str(erro)
            print(f"{ticker}: erro no score/tape ({erro})")
    return sucessos, falhas


def _ticker_setor():
    return {
        ticker: setor
        for setor, tickers in SETORES.items()
        for ticker in tickers
    }


def _ambiente_bova11():
    try:
        diario = calcular_metricas_diarias(BENCHMARK).dropna(subset=["sma200"])
        ultimo = diario.iloc[-1]
        favoravel = ultimo["fechamento"] > ultimo["sma200"]
        texto = (
            "AMBIENTE FAVORÁVEL — mercado em modo de compra"
            if favoravel
            else "AMBIENTE DESFAVORÁVEL — cautela, evite novos longs"
        )
        return {"favoravel": favoravel, "texto": texto}
    except Exception:
        return {
            "favoravel": False,
            "texto": "AMBIENTE INDEFINIDO — BOVA11 sem SMA200 suficiente",
        }


def _quadrantes_setor():
    with conectar() as conn:
        data = conn.execute("SELECT MAX(data_semana) FROM scores_setor").fetchone()[0]
        if not data:
            return {}
        linhas = conn.execute(
            """
            SELECT setor, rs_ratio, rs_momentum
            FROM scores_setor
            WHERE data_semana = ?
            """,
            (data,),
        ).fetchall()

    quadrantes = {}
    for setor, rs_ratio, rs_momentum in linhas:
        if rs_ratio >= 100 and rs_momentum >= 100:
            quadrantes[setor] = "Leading"
        elif rs_ratio >= 100:
            quadrantes[setor] = "Weakening"
        elif rs_momentum >= 100:
            quadrantes[setor] = "Improving"
        else:
            quadrantes[setor] = "Lagging"
    return quadrantes


def _score_anterior(ticker, data_semana):
    with conectar() as conn:
        linha = conn.execute(
            """
            SELECT score
            FROM scores
            WHERE ticker = ? AND data_semana < ?
            ORDER BY data_semana DESC
            LIMIT 1
            """,
            (ticker, data_semana),
        ).fetchone()
    return float(linha[0]) if linha else None


def _minima_semana(ticker, data_semana):
    with conectar() as conn:
        linha = conn.execute(
            """
            SELECT MIN(minima)
            FROM precos
            WHERE ticker = ?
              AND data >= date(?, '-4 days')
              AND data <= ?
            """,
            (ticker, data_semana, data_semana),
        ).fetchone()
    return linha[0] if linha and linha[0] is not None else None


def _ultimo_dia_alta(ticker):
    with conectar() as conn:
        linhas = conn.execute(
            """
            SELECT fechamento
            FROM precos
            WHERE ticker = ?
            ORDER BY data DESC
            LIMIT 2
            """,
            (ticker,),
        ).fetchall()
    return len(linhas) == 2 and linhas[0][0] > linhas[1][0]


def _significado(item, compra_gatilhos):
    if "Acumulação intra-semana" in compra_gatilhos and item["UDVR"] >= 2 and item["quadrante"] == "Leading":
        return "institucional comprando forte em setor líder"
    if "Volume incomum +" in compra_gatilhos and item["quadrante"] in ("Leading", "Improving"):
        return "volume entrou a favor em setor com rotação positiva"
    if "Burst antecipado" in compra_gatilhos:
        return "score acelerou antes de confirmação semanal completa"
    if item["quadrante"] == "Lagging":
        return "gatilho apareceu, mas setor ainda está atrasado no RRG"
    return "fluxo e momentum melhoraram, acompanhar confirmação"


def montar_dados_alerta_diario(forcar_sem_gatilhos=False):
    ambiente = _ambiente_bova11()
    setor_por_ticker = _ticker_setor()
    quadrantes = _quadrantes_setor()
    oportunidades = []
    distribuicoes = []
    avaliados = 0

    for ticker in TODOS_OS_TICKERS:
        if ticker == BENCHMARK or ticker not in setor_por_ticker:
            continue
        avaliados += 1
        try:
            resultado, breakdown = calcular_score(ticker, gravar=True)
            semanal, _diario = calcular_metricas(ticker)
            ultima = semanal.dropna(
                subset=["weekly_return", "relative_return", "volume_relative"]
            ).iloc[-1]
        except Exception:
            continue

        compra_gatilhos = []
        dist_gatilhos = []
        if (
            float(ultima["volume_relative"]) >= 1.5
            and float(ultima["weekly_return"]) > 0
            and float(ultima["relative_return"]) > 0
        ):
            compra_gatilhos.append("Volume incomum +")
        if resultado["UDVR"] >= 2.0 and _ultimo_dia_alta(ticker):
            compra_gatilhos.append("Acumulação intra-semana")
        anterior = _score_anterior(ticker, resultado["data_semana"])
        if anterior is not None and resultado["score"] - anterior >= 15:
            compra_gatilhos.append("Burst antecipado")
        if resultado["DDVR"] >= 1.5:
            dist_gatilhos.append("Distribuição")

        if forcar_sem_gatilhos:
            compra_gatilhos = []
            dist_gatilhos = []
        if not compra_gatilhos and not dist_gatilhos:
            continue

        setor = setor_por_ticker[ticker]
        quadrante = quadrantes.get(setor, "RRG indisponivel")
        minima = _minima_semana(ticker, resultado["data_semana"])
        inval = f"abaixo de R$ {minima:.2f}" if minima is not None else "sem nivel"
        base = {
            "ticker": ticker,
            "setor": setor,
            "quadrante": quadrante,
            "score": resultado["score"],
            "cf": breakdown["cf"],
            "trend": breakdown["trend"],
            "mom": breakdown["mom"],
            "UDVR": resultado["UDVR"],
            "DDVR": resultado["DDVR"],
            "rs_momentum": resultado["rs_momentum"],
            "invalidacao": inval,
        }
        if compra_gatilhos:
            item = dict(base)
            item["gatilhos"] = compra_gatilhos
            item["maior_conviccao"] = (
                "Acumulação intra-semana" in compra_gatilhos
                and item["UDVR"] >= 2
                and quadrante == "Leading"
            )
            item["significado"] = _significado(item, compra_gatilhos)
            oportunidades.append(item)
        if dist_gatilhos:
            item = dict(base)
            item["gatilhos"] = dist_gatilhos
            distribuicoes.append(item)

    if not oportunidades and not distribuicoes:
        return None
    oportunidades.sort(
        key=lambda item: (not item["maior_conviccao"], -item["score"])
    )
    distribuicoes.sort(key=lambda item: item["DDVR"], reverse=True)
    return {
        "data_dia": _data_mais_recente_precos(),
        "ambiente": ambiente,
        "oportunidades": oportunidades,
        "distribuicoes": distribuicoes,
        "sem_gatilho": max(0, avaliados - len({i["ticker"] for i in oportunidades + distribuicoes})),
    }


def _data_mais_recente_precos():
    with conectar() as conn:
        data = conn.execute("SELECT MAX(data) FROM precos").fetchone()[0]
    return data or "data indisponivel"


def montar_alerta_diario():
    dados = montar_dados_alerta_diario()
    if not dados:
        return None
    linhas = [
        f"Flow Map Diário — {dados['data_dia']}",
        dados["ambiente"]["texto"],
    ]
    for item in dados["oportunidades"]:
        linhas.append(f"{item['ticker']}: {', '.join(item['gatilhos'])}")
    for item in dados["distribuicoes"]:
        linhas.append(f"{item['ticker']}: Distribuição DDVR {item['DDVR']}x")
    return "\n".join(linhas)


def executar_varredura_diaria(coletar_antes=True, forcar_sem_gatilhos=False):
    criar_tabelas()
    if coletar_antes:
        coletar_tudo()
    recalcular_scores()
    dados = montar_dados_alerta_diario(forcar_sem_gatilhos=forcar_sem_gatilhos)
    if not dados:
        return None, None
    return gerar_alerta_diario_pdf(dados)

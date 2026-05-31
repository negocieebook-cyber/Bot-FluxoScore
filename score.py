from banco import gravar_score
try:
    from config import BENCHMARK
except ModuleNotFoundError:
    from config_base import BENCHMARK
from metricas import calcular_metricas
from tape import calcular_tape


def _limitar(valor, minimo, maximo):
    return max(minimo, min(maximo, valor))


def calcular_capital_flow(volume_relative, relative_return):
    if volume_relative is None or volume_relative != volume_relative:
        return 0.0

    # Mapeamento: 0.0x = 0 pontos, 1.0x = 20 pontos, 2.0x ou mais = 40 pontos.
    # Se o retorno relativo da semana for negativo, o volume e considerado fluxo
    # desfavoravel e recebe apenas 45% da pontuacao base.
    base = _limitar(volume_relative, 0.0, 2.0) * 20.0
    if relative_return is not None and relative_return == relative_return and relative_return < 0:
        base *= 0.45
    return _limitar(base, 0.0, 40.0)


def calcular_trend(ultima_diaria):
    close = ultima_diaria["fechamento"]
    sma20 = ultima_diaria["sma20"]
    sma50 = ultima_diaria["sma50"]
    sma200 = ultima_diaria["sma200"]
    sma200_slope = ultima_diaria["sma200_slope"]

    if any(valor != valor for valor in [close, sma20, sma50, sma200, sma200_slope]):
        return 0.0

    pontos = 0.0

    if sma200_slope > 0:
        pontos += 8.0
    if close > sma200:
        pontos += 6.0
    if close > sma50:
        pontos += 6.0
    elif close > sma200:
        pontos += 3.0
    if close > sma20:
        pontos += 5.0
    elif close > sma50:
        pontos += 2.0
    if sma20 > sma50 > sma200:
        pontos += 5.0

    return _limitar(pontos, 0.0, 30.0)


def calcular_momentum(rs_momentum, rsi):
    if any(valor is None or valor != valor for valor in [rs_momentum, rsi]):
        return 0.0

    rs_pontos = _limitar((rs_momentum - 80.0) / 20.0, 0.0, 1.0) * 18.0

    if rsi >= 50:
        rsi_pontos = 6.0 + _limitar((rsi - 50.0) / 20.0, 0.0, 1.0) * 6.0
    else:
        # TTI: RSI abaixo de 50 e watchlist/regime fraco; nao e venda por 70.
        rsi_pontos = _limitar((rsi - 30.0) / 20.0, 0.0, 1.0) * 4.0
        rs_pontos *= 0.55

    return _limitar(rs_pontos + rsi_pontos, 0.0, 30.0)


def calcular_score(ticker, gravar=False):
    semanal, diario = calcular_metricas(ticker, BENCHMARK)

    ultima_semana = semanal.dropna(
        subset=["rs_ratio", "rs_momentum", "volume_relative", "relative_return"]
    ).iloc[-1]
    ultima_diaria = diario.dropna(subset=["rsi14", "sma20", "sma50", "sma200"]).iloc[-1]

    cf = calcular_capital_flow(
        float(ultima_semana["volume_relative"]),
        float(ultima_semana["relative_return"]),
    )
    trend = calcular_trend(ultima_diaria)
    mom = calcular_momentum(
        float(ultima_semana["rs_momentum"]),
        float(ultima_diaria["rsi14"]),
    )
    total = _limitar(cf + trend + mom, 0.0, 100.0)

    resultado = {
        "ticker": ticker,
        "data_semana": ultima_semana.name.date().isoformat(),
        "score": round(total, 2),
        "cf": round(cf, 2),
        "trend": round(trend, 2),
        "mom": round(mom, 2),
        "rs_ratio": round(float(ultima_semana["rs_ratio"]), 2),
        "rs_momentum": round(float(ultima_semana["rs_momentum"]), 2),
        "volume_relative": round(float(ultima_semana["volume_relative"]), 2),
        "fechamento": round(float(ultima_diaria["fechamento"]), 2),
        "sma50": round(float(ultima_diaria["sma50"]), 2),
        "sma200": round(float(ultima_diaria["sma200"]), 2),
        "rsi14": round(float(ultima_diaria["rsi14"]), 2),
    }
    tape = calcular_tape(
        ticker,
        data_semana=resultado["data_semana"],
        score=resultado["score"],
    )
    resultado.update(tape)

    if gravar:
        gravar_score(
            ticker=resultado["ticker"],
            data_semana=resultado["data_semana"],
            score=resultado["score"],
            cf=resultado["cf"],
            trend=resultado["trend"],
            mom=resultado["mom"],
            rs_ratio=resultado["rs_ratio"],
            rs_momentum=resultado["rs_momentum"],
            volume_relative=resultado["volume_relative"],
            UDVR=resultado["UDVR"],
            DDVR=resultado["DDVR"],
            up_day_vol_pct=resultado["up_day_vol_pct"],
        )

    return resultado, {
        "cf": resultado["cf"],
        "trend": resultado["trend"],
        "mom": resultado["mom"],
    }

import pandas as pd

from banco import gravar_score_setor
try:
    from config import BENCHMARK, SCORE_MODERADO, SETORES
except ModuleNotFoundError:
    from config_base import BENCHMARK, SCORE_MODERADO, SETORES
from metricas import calcular_metricas, carregar_precos
from score import (
    _limitar,
    calcular_capital_flow,
    calcular_momentum,
    calcular_score,
    calcular_trend,
)


def _para_semanal(df):
    semanal = pd.DataFrame()
    semanal["close"] = df["fechamento"].resample("W-FRI").last()
    semanal["volume"] = df["volume"].resample("W-FRI").sum()
    semanal = semanal.dropna(subset=["close"])
    semanal["weekly_return"] = semanal["close"].pct_change()
    semanal["financial_volume"] = semanal["close"] * semanal["volume"]
    semanal["volume_relative"] = (
        semanal["financial_volume"] / semanal["financial_volume"].rolling(8).mean()
    )
    return semanal


def _cesta_diaria(tickers):
    series = []
    for ticker in tickers:
        try:
            precos = carregar_precos(ticker)
        except ValueError:
            continue
        normalizado = precos["fechamento"] / precos["fechamento"].iloc[0] * 100.0
        series.append(normalizado.rename(ticker))

    if not series:
        raise ValueError("setor sem tickers com precos no banco")

    return pd.concat(series, axis=1).mean(axis=1).to_frame("fechamento")


def _trend_setorial(cesta_diaria, data_semana):
    diario = cesta_diaria.loc[:data_semana].copy()
    diario["sma20"] = diario["fechamento"].rolling(20).mean()
    diario["sma50"] = diario["fechamento"].rolling(50).mean()
    diario["sma200"] = diario["fechamento"].rolling(200).mean()
    diario["sma200_slope"] = diario["sma200"].diff(20)
    return calcular_trend(diario.dropna().iloc[-1])


def _rsi_setorial(cesta_diaria, data_semana):
    from metricas import calcular_rsi

    diario = cesta_diaria.loc[:data_semana].copy()
    diario["rsi14"] = calcular_rsi(diario["fechamento"], 14)
    return float(diario["rsi14"].dropna().iloc[-1])


def _confirmacao_interna(tickers):
    total = 0
    confirmados = 0
    for ticker in tickers:
        try:
            semanal, _diario = calcular_metricas(ticker, BENCHMARK)
            ultima = semanal.dropna(subset=["relative_return"]).iloc[-1]
            resultado, _breakdown = calcular_score(ticker, gravar=True)
        except Exception:
            continue

        total += 1
        if float(ultima["relative_return"]) > 0 and resultado["score"] >= SCORE_MODERADO:
            confirmados += 1

    pct = (confirmados / total * 100.0) if total else 0.0
    if pct >= 60.0:
        nivel = "Ampla"
    elif pct >= 40.0:
        nivel = "Parcial"
    else:
        nivel = "Fraca"
    return f"{nivel} ({pct:.0f}%)"


def calcular_metricas_setor(setor, tickers):
    benchmark = _para_semanal(carregar_precos(BENCHMARK))
    semanais = []

    for ticker in tickers:
        try:
            semanal = _para_semanal(carregar_precos(ticker))
        except ValueError:
            continue
        semanais.append(
            semanal[["weekly_return", "volume_relative"]].rename(
                columns={
                    "weekly_return": f"{ticker}_return",
                    "volume_relative": f"{ticker}_volume_relative",
                }
            )
        )

    if not semanais:
        raise ValueError(f"setor {setor} sem dados no banco")

    painel = pd.concat(semanais, axis=1)
    retorno_cols = [col for col in painel.columns if col.endswith("_return")]
    volume_cols = [col for col in painel.columns if col.endswith("_volume_relative")]

    df = pd.DataFrame(index=painel.index)
    df["weekly_return"] = painel[retorno_cols].mean(axis=1)
    df["volume_relative"] = painel[volume_cols].mean(axis=1)
    df["close"] = (1.0 + df["weekly_return"].fillna(0.0)).cumprod() * 100.0

    bench = benchmark[["close", "weekly_return"]].rename(
        columns={
            "close": "close_benchmark",
            "weekly_return": "weekly_return_benchmark",
        }
    )
    df = df.join(bench, how="inner")
    df["relative_return"] = df["weekly_return"] - df["weekly_return_benchmark"]
    df["RS"] = df["close"] / (df["close_benchmark"] / df["close_benchmark"].iloc[0] * 100.0)
    df["rs_ratio"] = 100 * df["RS"] / df["RS"].rolling(10).mean()
    df["rs_momentum"] = 100 * df["rs_ratio"] / df["rs_ratio"].shift(4)
    return df


def quadrante_rrg(rs_ratio, rs_momentum):
    if rs_ratio >= 100 and rs_momentum >= 100:
        return "Leading"
    if rs_ratio >= 100 and rs_momentum < 100:
        return "Weakening"
    if rs_ratio < 100 and rs_momentum >= 100:
        return "Improving"
    return "Lagging"


def calcular_score_setor(setor, tickers, gravar=True):
    semanal = calcular_metricas_setor(setor, tickers)
    cesta = _cesta_diaria(tickers)
    confirmacao = _confirmacao_interna(tickers)

    resultados = []
    base = semanal.dropna(
        subset=["rs_ratio", "rs_momentum", "volume_relative", "relative_return"]
    )
    for data_semana, linha in base.iterrows():
        try:
            cf = calcular_capital_flow(
                float(linha["volume_relative"]),
                float(linha["relative_return"]),
            )
            trend = _trend_setorial(cesta, data_semana)
            rsi = _rsi_setorial(cesta, data_semana)
            mom = calcular_momentum(float(linha["rs_momentum"]), rsi)
        except Exception:
            continue

        total = _limitar(cf + trend + mom, 0.0, 100.0)
        resultado = {
            "setor": setor,
            "data_semana": data_semana.date().isoformat(),
            "score": round(total, 2),
            "cf": round(cf, 2),
            "trend": round(trend, 2),
            "mom": round(mom, 2),
            "rs_ratio": round(float(linha["rs_ratio"]), 2),
            "rs_momentum": round(float(linha["rs_momentum"]), 2),
            "volume_relative": round(float(linha["volume_relative"]), 2),
            "confirmacao_interna": confirmacao,
            "quadrante": quadrante_rrg(float(linha["rs_ratio"]), float(linha["rs_momentum"])),
        }
        resultados.append(resultado)

        if gravar:
            gravar_score_setor(
                setor=resultado["setor"],
                data_semana=resultado["data_semana"],
                score=resultado["score"],
                cf=resultado["cf"],
                trend=resultado["trend"],
                mom=resultado["mom"],
                rs_ratio=resultado["rs_ratio"],
                rs_momentum=resultado["rs_momentum"],
                volume_relative=resultado["volume_relative"],
                confirmacao_interna=resultado["confirmacao_interna"],
            )

    if not resultados:
        raise ValueError(f"sem score setorial calculavel para {setor}")
    return resultados[-1]


def calcular_scores_setoriais(gravar=True):
    resultados = []
    for setor, tickers in SETORES.items():
        resultados.append(calcular_score_setor(setor, tickers, gravar=gravar))
    return sorted(resultados, key=lambda item: item["score"], reverse=True)

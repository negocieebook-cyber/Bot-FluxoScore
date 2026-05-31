import pandas as pd

from banco import conectar
from config import BENCHMARK


def carregar_precos(ticker):
    with conectar() as conn:
        df = pd.read_sql_query(
            """
            SELECT data, fechamento, volume
            FROM precos
            WHERE ticker = ?
            ORDER BY data
            """,
            conn,
            params=(ticker,),
            parse_dates=["data"],
        )

    if df.empty:
        raise ValueError(f"sem precos no banco para {ticker}")

    return df.set_index("data")


def calcular_rsi(fechamento, periodo=14):
    delta = fechamento.diff()
    ganhos = delta.clip(lower=0)
    perdas = -delta.clip(upper=0)

    media_ganhos = ganhos.ewm(alpha=1 / periodo, adjust=False).mean()
    media_perdas = perdas.ewm(alpha=1 / periodo, adjust=False).mean()
    rs = media_ganhos / media_perdas
    return 100 - (100 / (1 + rs))


def calcular_metricas_diarias(ticker):
    df = carregar_precos(ticker).copy()
    df["rsi14"] = calcular_rsi(df["fechamento"], 14)
    df["sma20"] = df["fechamento"].rolling(20).mean()
    df["sma50"] = df["fechamento"].rolling(50).mean()
    df["sma200"] = df["fechamento"].rolling(200).mean()
    df["sma200_slope"] = df["sma200"].diff(20)
    return df


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


def calcular_metricas_semanais(ticker, benchmark=BENCHMARK):
    ativo = _para_semanal(carregar_precos(ticker))
    indice = _para_semanal(carregar_precos(benchmark))

    df = ativo.join(
        indice[["close", "weekly_return"]].rename(
            columns={
                "close": "close_benchmark",
                "weekly_return": "weekly_return_benchmark",
            }
        ),
        how="inner",
    )

    if df.empty:
        raise ValueError(f"sem semanas alinhadas entre {ticker} e {benchmark}")

    df["relative_return"] = df["weekly_return"] - df["weekly_return_benchmark"]
    df["RS"] = df["close"] / df["close_benchmark"]
    df["rs_ratio"] = 100 * df["RS"] / df["RS"].rolling(10).mean()
    df["rs_momentum"] = 100 * df["rs_ratio"] / df["rs_ratio"].shift(4)
    return df


def calcular_metricas(ticker, benchmark=BENCHMARK):
    semanal = calcular_metricas_semanais(ticker, benchmark)
    diario = calcular_metricas_diarias(ticker)
    return semanal, diario

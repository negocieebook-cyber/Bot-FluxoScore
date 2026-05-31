import pandas as pd

from banco import conectar
from config import SCORE_MODERADO


def _carregar_precos_diarios(ticker):
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


def _semana_alvo(df, data_semana=None):
    semanal = df["fechamento"].resample("W-FRI").last().dropna()
    if data_semana is None:
        return semanal.index[-1]
    return pd.Timestamp(data_semana)


def _flag_top(ticker, data_semana, score):
    if score is None or score < SCORE_MODERADO:
        return []

    with conectar() as conn:
        semanas = conn.execute(
            """
            SELECT data_semana, score
            FROM scores
            WHERE ticker = ? AND data_semana < ?
            ORDER BY data_semana DESC
            LIMIT 1
            """,
            (ticker, data_semana),
        ).fetchall()

    if not semanas or semanas[0][1] < SCORE_MODERADO:
        return ["NEW THIS WEEK"]
    return ["SUSTAINED LEADER"]


def calcular_tape(ticker, data_semana=None, score=None):
    df = _carregar_precos_diarios(ticker).copy()
    df["fechamento_anterior"] = df["fechamento"].shift(1)

    fim_semana = _semana_alvo(df, data_semana)
    inicio_semana = fim_semana - pd.Timedelta(days=4)
    ate_fim = df.loc[:fim_semana]
    dias_semana = df.loc[inicio_semana:fim_semana]

    if dias_semana.empty:
        raise ValueError(f"sem dados diarios na semana {fim_semana.date()} para {ticker}")
    if len(ate_fim) < 30:
        raise ValueError(f"menos de 30 pregoes para calcular tape de {ticker}")

    vol_medio_30d = float(ate_fim["volume"].tail(30).mean())
    if vol_medio_30d <= 0:
        raise ValueError(f"volume medio 30d invalido para {ticker}")

    dias_alta = dias_semana["fechamento"] > dias_semana["fechamento_anterior"]
    dias_queda = dias_semana["fechamento"] < dias_semana["fechamento_anterior"]
    dias_alta_qtd = int(dias_alta.sum())
    dias_queda_qtd = int(dias_queda.sum())

    vol_dias_alta = float(dias_semana.loc[dias_alta, "volume"].sum())
    vol_dias_queda = float(dias_semana.loc[dias_queda, "volume"].sum())
    vol_total_semana = float(dias_semana["volume"].sum())
    vol_medio_dias_alta = vol_dias_alta / dias_alta_qtd if dias_alta_qtd > 0 else 0.0
    vol_medio_dias_queda = vol_dias_queda / dias_queda_qtd if dias_queda_qtd > 0 else 0.0

    UDVR = vol_medio_dias_alta / vol_medio_30d
    DDVR = vol_medio_dias_queda / vol_medio_30d
    up_day_vol_pct = (
        (vol_dias_alta / vol_total_semana) * 100.0
        if vol_total_semana > 0
        else 0.0
    )

    fechamento_semana = float(dias_semana["fechamento"].iloc[-1])
    fechamento_anterior = float(ate_fim.loc[: inicio_semana - pd.Timedelta(days=1)]["fechamento"].iloc[-1])
    semana_alta = fechamento_semana > fechamento_anterior
    semana_queda = fechamento_semana < fechamento_anterior

    flags = []
    if UDVR >= 1.5 and semana_alta:
        flags.append("ACCUMULATION PATTERN")
    if UDVR >= 2.0 and semana_alta:
        flags.append("ACCUMULATION CONFIRMED")
    if DDVR >= 1.5 and semana_queda:
        flags.append("DISTRIBUTION PATTERN")
    if score is not None and score >= 60 and UDVR <= 0.8:
        flags.append("TAPE DISAGREES")
    flags.extend(_flag_top(ticker, fim_semana.date().isoformat(), score))

    return {
        "UDVR": round(UDVR, 2),
        "DDVR": round(DDVR, 2),
        "up_day_vol_pct": round(up_day_vol_pct, 2),
        "dias_alta": dias_alta_qtd,
        "dias_queda": dias_queda_qtd,
        "flags": flags,
    }


def flag_tape_disagrees(score, UDVR):
    return score >= 60 and UDVR <= 0.8

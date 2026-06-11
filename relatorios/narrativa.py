"""
Funções compartilhadas de narrativa, interpretação e qualidade de dados.
Apenas lê dados existentes do banco — não altera nenhum motor
(score.py / metricas.py / tape.py / setor.py / rrg.py intocados).
"""
from datetime import datetime, timedelta

from banco import conectar, carregar_fundamentos
try:
    from config import MIN_MARKET_CAP, MIN_PRECO, MIN_VOLUME_DIARIO, SETORES, TODOS_OS_TICKERS
except ModuleNotFoundError:
    from config_base import MIN_MARKET_CAP, MIN_PRECO, MIN_VOLUME_DIARIO, SETORES, TODOS_OS_TICKERS


# ── Retorno Semanal (leitura direta da tabela precos) ─────────────────────────

def retorno_semanal(ticker, data_referencia):
    """
    Retorno % entre o fechamento na data_referencia e o fechamento
    ~7 dias antes. Usa apenas a tabela precos — nenhum cálculo do motor.
    """
    data_ant = (
        datetime.strptime(data_referencia, "%Y-%m-%d") - timedelta(days=7)
    ).strftime("%Y-%m-%d")

    with conectar() as conn:
        atual = conn.execute(
            "SELECT fechamento FROM precos WHERE ticker = ? AND data <= ?"
            " ORDER BY data DESC LIMIT 1",
            (ticker, data_referencia),
        ).fetchone()
        anterior = conn.execute(
            "SELECT fechamento FROM precos WHERE ticker = ? AND data <= ?"
            " ORDER BY data DESC LIMIT 1",
            (ticker, data_ant),
        ).fetchone()

    if not atual or not anterior:
        return None
    p_at = float(atual[0])
    p_an = float(anterior[0])
    if p_an == 0:
        return None
    return (p_at - p_an) / p_an * 100


# ── Flag de Tape (a partir dos valores já calculados pelo motor) ───────────────

def flag_tape(udvr, ddvr, score):
    """Rótulo de tape a partir dos UDVR/DDVR já gravados no banco pelo motor."""
    if udvr >= 2.0:
        return "ACCUM. CONF."
    if udvr >= 1.5:
        return "ACUMULAÇÃO"
    if ddvr >= 1.5:
        return "DISTRIBUIÇÃO"
    if score >= 60 and udvr < 0.8:
        return "TAPE ↓"
    return "—"


# ── Leitura de Ação Dentro de um Setor Líder ──────────────────────────────────

def leitura_acao(score, rs_ratio, rs_momentum):
    """
    Regra de leitura de uma ação no contexto de um setor líder.
    Baseia-se nos mesmos critérios do motor sem recalcular nada.
    """
    forte = score >= 60
    bateu = rs_ratio > 100
    mom_ok = rs_momentum >= 100
    if forte and bateu and mom_ok:
        return "Confirma o setor"
    if forte and (not bateu or not mom_ok):
        return "Diverge do setor"
    if not forte and bateu and mom_ok:
        return "Força rel. em melhora"
    return "Perda de força"


# ── ADV calculado direto da tabela precos ─────────────────────────────────────

def adv_do_banco(ticker):
    """ADV (R$) dos últimos 30 pregões disponíveis na tabela precos."""
    with conectar() as conn:
        rows = conn.execute(
            "SELECT fechamento, volume FROM precos"
            " WHERE ticker = ? ORDER BY data DESC LIMIT 30",
            (ticker,),
        ).fetchall()
    rows = [r for r in rows if r[0] is not None and r[1] is not None]
    if not rows:
        return None
    return sum(float(r[0]) * float(r[1]) for r in rows) / len(rows)


# ── Qualidade / Transparência dos Dados ───────────────────────────────────────

def qualidade_dados(data_semana):
    """
    Resumo de qualidade para o rodapé técnico de cada relatório.
    Lê apenas scores e precos — nenhum cálculo do motor.
    """
    todos = [t for t in TODOS_OS_TICKERS if t != "BOVA11"]

    with conectar() as conn:
        com_score = {
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT ticker FROM scores WHERE data_semana = ?",
                (data_semana,),
            ).fetchall()
        }
        contagens = {
            r[0]: int(r[1])
            for r in conn.execute(
                "SELECT ticker, COUNT(*) FROM precos GROUP BY ticker"
            ).fetchall()
        }

    sem_dados = sorted(t for t in todos if contagens.get(t, 0) == 0)
    sma_parcial = sorted(
        (t, contagens[t])
        for t in com_score
        if 0 < contagens.get(t, 0) < 200
    )
    com_dados = sum(1 for t in com_score if contagens.get(t, 0) >= 200)

    return {
        "data_semana": data_semana,
        "total_universo": len(todos),
        "com_score": len(com_score),
        "com_dados_completos": com_dados,
        "sem_dados": sem_dados,
        "sma_parcial": sma_parcial,   # list of (ticker, n_pregoes)
        "benchmark": "BOVA11",
    }


# ── Verificação de Negociabilidade (DB-only, sem chamar o motor) ──────────────

def checa_negociabilidade(ticker):
    """
    Verifica os 3 filtros de negociabilidade usando apenas o banco.
    Retorna (ok: bool, motivo: str).
    """
    fund = carregar_fundamentos(ticker)
    if fund is None:
        return False, "fundamentos não disponíveis"

    preco = fund.get("preco") or 0
    mkt_cap = fund.get("market_cap") or 0
    adv = adv_do_banco(ticker)

    if preco < MIN_PRECO:
        return False, f"preço R$ {preco:.2f} < mínimo R$ {MIN_PRECO:.0f}"
    if adv is None or adv < MIN_VOLUME_DIARIO:
        adv_str = f"R$ {adv/1e6:.1f}mi" if adv else "N/D"
        return False, f"ADV {adv_str} < R$ {MIN_VOLUME_DIARIO/1e6:.0f}mi (liquidez)"
    if mkt_cap < MIN_MARKET_CAP:
        return False, f"market cap < R$ {MIN_MARKET_CAP/1e9:.0f}bi"
    return True, ""

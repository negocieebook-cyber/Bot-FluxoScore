import sqlite3
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "dados" / "flowmap.db"


def conectar():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(DB_PATH)


def criar_tabelas():
    with conectar() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS precos (
                ticker TEXT NOT NULL,
                data TEXT NOT NULL,
                abertura REAL,
                maxima REAL,
                minima REAL,
                fechamento REAL,
                volume INTEGER,
                PRIMARY KEY (ticker, data)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scores (
                ticker TEXT NOT NULL,
                data_semana TEXT NOT NULL,
                score REAL,
                cf REAL,
                trend REAL,
                mom REAL,
                rs_ratio REAL,
                rs_momentum REAL,
                volume_relative REAL,
                UDVR REAL,
                DDVR REAL,
                up_day_vol_pct REAL,
                PRIMARY KEY (ticker, data_semana)
            )
            """
        )
        _garantir_coluna(conn, "scores", "UDVR", "REAL")
        _garantir_coluna(conn, "scores", "DDVR", "REAL")
        _garantir_coluna(conn, "scores", "up_day_vol_pct", "REAL")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS scores_setor (
                setor TEXT NOT NULL,
                data_semana TEXT NOT NULL,
                score REAL,
                cf REAL,
                trend REAL,
                mom REAL,
                rs_ratio REAL,
                rs_momentum REAL,
                volume_relative REAL,
                confirmacao_interna TEXT,
                PRIMARY KEY (setor, data_semana)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS fundamentos (
                ticker TEXT PRIMARY KEY,
                market_cap REAL,
                preco REAL,
                atualizado_em TEXT
            )
            """
        )
        _garantir_coluna(conn, "fundamentos", "preco", "REAL")
        _garantir_coluna(conn, "fundamentos", "atualizado_em", "TEXT")


def _garantir_coluna(conn, tabela, coluna, tipo):
    colunas = {
        linha[1]
        for linha in conn.execute(f"PRAGMA table_info({tabela})").fetchall()
    }
    if coluna not in colunas:
        conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")


def salvar_precos(ticker, linhas):
    with conectar() as conn:
        conn.executemany(
            """
            INSERT OR REPLACE INTO precos (
                ticker, data, abertura, maxima, minima, fechamento, volume
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    ticker,
                    linha["data"],
                    linha["abertura"],
                    linha["maxima"],
                    linha["minima"],
                    linha["fechamento"],
                    linha["volume"],
                )
                for linha in linhas
            ],
        )


def gravar_score(
    ticker,
    data_semana,
    score,
    cf,
    trend,
    mom,
    rs_ratio,
    rs_momentum,
    volume_relative,
    UDVR=None,
    DDVR=None,
    up_day_vol_pct=None,
):
    with conectar() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO scores (
                ticker, data_semana, score, cf, trend, mom,
                rs_ratio, rs_momentum, volume_relative,
                UDVR, DDVR, up_day_vol_pct
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ticker,
                data_semana,
                score,
                cf,
                trend,
                mom,
                rs_ratio,
                rs_momentum,
                volume_relative,
                UDVR,
                DDVR,
                up_day_vol_pct,
            ),
        )


def gravar_score_setor(
    setor,
    data_semana,
    score,
    cf,
    trend,
    mom,
    rs_ratio,
    rs_momentum,
    volume_relative,
    confirmacao_interna,
):
    with conectar() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO scores_setor (
                setor, data_semana, score, cf, trend, mom,
                rs_ratio, rs_momentum, volume_relative, confirmacao_interna
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                setor,
                data_semana,
                score,
                cf,
                trend,
                mom,
                rs_ratio,
                rs_momentum,
                volume_relative,
                confirmacao_interna,
            ),
        )


def salvar_fundamentos(ticker, market_cap, preco=None, atualizado_em=None):
    with conectar() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO fundamentos (
                ticker, market_cap, preco, atualizado_em
            ) VALUES (?, ?, ?, ?)
            """,
            (ticker, market_cap, preco, atualizado_em),
        )


def carregar_fundamentos(ticker):
    with conectar() as conn:
        linha = conn.execute(
            """
            SELECT market_cap, preco, atualizado_em
            FROM fundamentos
            WHERE ticker = ?
            """,
            (ticker,),
        ).fetchone()
    if not linha:
        return None
    return {
        "market_cap": linha[0],
        "preco": linha[1],
        "atualizado_em": linha[2],
    }

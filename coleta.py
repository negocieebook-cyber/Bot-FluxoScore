from datetime import datetime, timezone

import requests
import yfinance as yf

from banco import carregar_fundamentos, salvar_fundamentos, salvar_precos
try:
    from config import TOKEN_BRAPI
except ModuleNotFoundError:
    from config_base import TOKEN_BRAPI


class BrapiHistoricoError(Exception):
    def __init__(self, ticker, status_code, mensagem):
        self.ticker = ticker
        self.status_code = status_code
        self.mensagem = mensagem
        super().__init__(f"brapi {status_code}: {mensagem}")


def _coletar_brapi(ticker):
    url = f"https://brapi.dev/api/quote/{ticker}"
    params = {
        "range": "3mo",
        "interval": "1d",
        "token": TOKEN_BRAPI,
    }
    resposta = requests.get(url, params=params, timeout=30)
    try:
        dados = resposta.json()
    except ValueError:
        dados = {}

    if resposta.status_code != 200:
        mensagem = dados.get("message") or dados.get("error") or resposta.reason
        raise BrapiHistoricoError(ticker, resposta.status_code, mensagem)

    resultados = dados.get("results") or []
    if not resultados:
        raise BrapiHistoricoError(ticker, 200, "sem results")

    historico = resultados[0].get("historicalDataPrice") or []
    if not historico:
        raise BrapiHistoricoError(ticker, 200, "sem historicalDataPrice")

    linhas = []
    for item in historico:
        linhas.append(
            {
                "data": datetime.fromtimestamp(item["date"]).date().isoformat(),
                "abertura": item.get("open"),
                "maxima": item.get("high"),
                "minima": item.get("low"),
                "fechamento": item.get("close"),
                "volume": item.get("volume"),
            }
        )
    return linhas


def _mesclar_historicos(linhas_yfinance, linhas_brapi):
    por_data = {linha["data"]: linha for linha in linhas_yfinance}
    for linha in linhas_brapi:
        por_data[linha["data"]] = linha
    return [por_data[data] for data in sorted(por_data)]


def _coletar_yfinance(ticker):
    ticker_yf = f"{ticker}.SA"
    df = yf.download(
        ticker_yf,
        period="1y",
        interval="1d",
        auto_adjust=False,
        progress=False,
    )

    if df.empty:
        raise ValueError(f"yfinance sem dados para {ticker_yf}")

    if getattr(df.columns, "nlevels", 1) > 1:
        if ticker_yf in df.columns.get_level_values(-1):
            df = df.xs(ticker_yf, axis=1, level=-1)
        else:
            df.columns = df.columns.get_level_values(0)

    linhas = []
    for data, row in df.iterrows():
        linhas.append(
            {
                "data": data.date().isoformat(),
                "abertura": float(row["Open"]),
                "maxima": float(row["High"]),
                "minima": float(row["Low"]),
                "fechamento": float(row["Close"]),
                "volume": int(row["Volume"]),
            }
        )
    return linhas


def coletar(ticker):
    try:
        linhas_brapi = _coletar_brapi(ticker)
        status_fonte = "brapi 200"
        try:
            linhas_yfinance = _coletar_yfinance(ticker)
            linhas = _mesclar_historicos(linhas_yfinance, linhas_brapi)
            fonte = "brapi+yfinance"
            status_fonte = "brapi 200 / yfinance ok"
        except Exception as erro_yfinance:
            linhas = linhas_brapi
            fonte = "brapi"
            status_fonte = f"brapi 200 / yfinance falhou ({erro_yfinance})"
    except Exception as erro_brapi:
        if isinstance(erro_brapi, BrapiHistoricoError):
            status_fonte = f"brapi {erro_brapi.status_code}"
            print(f"{ticker}: {status_fonte} ({erro_brapi.mensagem}); tentando yfinance")
        else:
            status_fonte = "brapi falhou"
            print(f"{ticker}: brapi falhou ({erro_brapi}); tentando yfinance")
        try:
            linhas = _coletar_yfinance(ticker)
            fonte = "yfinance"
            status_fonte = f"{status_fonte} / yfinance ok"
        except Exception as erro_yfinance:
            print(f"{ticker}: {status_fonte} / falhou ({erro_yfinance})")
            raise

    salvar_precos(ticker, linhas)
    try:
        coletar_fundamentos(ticker, forcar=True)
    except Exception as erro_fundamentos:
        print(f"{ticker}: fundamentos falharam ({erro_fundamentos})")
    print(f"{ticker}: fonte usada = {fonte} ({status_fonte})")
    return linhas


def _token_brapi_valido():
    return TOKEN_BRAPI and not TOKEN_BRAPI.startswith("COLOQUE_")


def coletar_fundamentos(tickers, forcar=False):
    if isinstance(tickers, str):
        unico = True
        lista_tickers = [tickers]
    else:
        unico = False
        lista_tickers = list(tickers)

    if unico and not forcar:
        fundamentos = carregar_fundamentos(lista_tickers[0])
        if fundamentos and fundamentos.get("market_cap") and fundamentos.get("preco"):
            return fundamentos

    url = "https://brapi.dev/api/quote/" + ",".join(lista_tickers)
    params = {}
    if _token_brapi_valido():
        params["token"] = TOKEN_BRAPI

    try:
        resposta = requests.get(url, params=params, timeout=30)
        resposta.raise_for_status()
        dados = resposta.json()
        resultados = dados.get("results") or []
        if not resultados:
            raise ValueError(f"brapi sem results para {','.join(lista_tickers)}")

        atualizados = {}
        atualizado_em = datetime.now(timezone.utc).isoformat()
        for item in resultados:
            ticker = item.get("symbol")
            market_cap = item.get("marketCap")
            preco = item.get("regularMarketPrice")
            if not ticker:
                continue
            if market_cap is None:
                raise ValueError(f"brapi sem marketCap para {ticker}")
            salvar_fundamentos(
                ticker=ticker,
                market_cap=float(market_cap),
                preco=float(preco) if preco is not None else None,
                atualizado_em=atualizado_em,
            )
            atualizados[ticker] = {
                "market_cap": float(market_cap),
                "preco": float(preco) if preco is not None else None,
                "atualizado_em": atualizado_em,
            }

        faltantes = [ticker for ticker in lista_tickers if ticker not in atualizados]
        if faltantes:
            raise ValueError(f"brapi nao retornou fundamentos para {', '.join(faltantes)}")

        print(f"{','.join(lista_tickers)}: fundamentos usados = brapi")
    except Exception as erro_brapi:
        print(f"{','.join(lista_tickers)}: brapi fundamentos falhou ({erro_brapi}); tentando yfinance")
        atualizados = {}
        for ticker in lista_tickers:
            atualizados[ticker] = coletar_fundamentos_yfinance(ticker)

    if unico:
        return atualizados[lista_tickers[0]]
    return atualizados


def coletar_fundamentos_yfinance(ticker):
    fundamentos = carregar_fundamentos(ticker)
    if fundamentos and fundamentos.get("market_cap") and fundamentos.get("preco"):
        return fundamentos

    ticker_yf = f"{ticker}.SA"
    info = yf.Ticker(ticker_yf).fast_info
    market_cap = info.get("market_cap")
    preco = info.get("last_price")
    if market_cap is None:
        info_completo = yf.Ticker(ticker_yf).info
        market_cap = info_completo.get("marketCap")
        preco = preco or info_completo.get("regularMarketPrice")
    if market_cap is None:
        raise ValueError(f"market cap indisponivel para {ticker_yf}")

    atualizado_em = datetime.now(timezone.utc).isoformat()
    salvar_fundamentos(
        ticker,
        float(market_cap),
        float(preco) if preco is not None else None,
        atualizado_em,
    )
    print(f"{ticker}: fundamentos usados = yfinance")
    return {
        "market_cap": float(market_cap),
        "preco": float(preco) if preco is not None else None,
        "atualizado_em": atualizado_em,
    }

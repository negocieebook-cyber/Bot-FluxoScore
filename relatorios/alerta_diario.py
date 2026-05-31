from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright


BASE_DIR = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = BASE_DIR / "templates"
SAIDAS_DIR = BASE_DIR / "saidas"


def legenda_alerta(dados):
    return (
        f"Alerta diário — {len(dados['oportunidades'])} oportunidades, "
        f"{len(dados['distribuicoes'])} em distribuição, "
        f"{len(dados.get('tape_mista', []))} tape mista. Abra o PDF."
    )


def _eh_tape_mista(item, esta_nas_duas_listas):
    udvr = float(item.get("UDVR") or 0)
    ddvr = float(item.get("DDVR") or 0)
    diferenca_pequena = abs(udvr - ddvr) <= 0.25 and max(udvr, ddvr) >= 1.2
    return esta_nas_duas_listas or (udvr >= 1.5 and ddvr >= 1.5) or diferenca_pequena


def _normalizar_tape_mista(dados):
    dados = dict(dados)
    oportunidades = list(dados.get("oportunidades", []))
    distribuicoes = list(dados.get("distribuicoes", []))
    tickers_oportunidade = {item["ticker"] for item in oportunidades}
    tickers_distribuicao = {item["ticker"] for item in distribuicoes}
    tickers_ambos = tickers_oportunidade & tickers_distribuicao

    por_ticker = {}
    for item in oportunidades + distribuicoes:
        por_ticker.setdefault(item["ticker"], item)

    mistos = []
    for ticker, item in por_ticker.items():
        if _eh_tape_mista(item, ticker in tickers_ambos):
            mistos.append(
                {
                    "ticker": ticker,
                    "UDVR": float(item.get("UDVR") or 0),
                    "DDVR": float(item.get("DDVR") or 0),
                }
            )

    tickers_mistos = {item["ticker"] for item in mistos}
    dados["oportunidades"] = [
        item for item in oportunidades if item["ticker"] not in tickers_mistos
    ]
    dados["distribuicoes"] = [
        item for item in distribuicoes if item["ticker"] not in tickers_mistos
    ]
    dados["tape_mista"] = sorted(mistos, key=lambda item: item["ticker"])
    return dados


def _glossario(dados):
    termos = []
    gatilhos = {
        gatilho
        for item in dados["oportunidades"]
        for gatilho in item["gatilhos"]
    }
    if "Volume incomum +" in gatilhos:
        termos.append("Volume incomum: volume relativo >= 1.5x com alta contra o BOVA11")
    if "Acumulação intra-semana" in gatilhos:
        termos.append("UDVR: volume médio dos dias de alta contra a média de 30 pregões")
    if "Burst antecipado" in gatilhos:
        termos.append("Burst: salto de score >= 15 pontos")
    if dados["distribuicoes"]:
        termos.append("DDVR: volume médio dos dias de queda contra a média de 30 pregões")
    if any(item["quadrante"] for item in dados["oportunidades"]):
        termos.append("RRG: quadrante de rotação relativa do setor")
    return termos


def gerar_alerta_diario_pdf(dados):
    if not dados:
        return None, None

    dados = _normalizar_tape_mista(dados)
    if (
        not dados["oportunidades"]
        and not dados["distribuicoes"]
        and not dados.get("tape_mista")
    ):
        return None, None

    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(["html"]),
    )
    html = env.get_template("alerta_diario.html").render(
        **dados,
        glossario=_glossario(dados),
    )
    data_nome = datetime.now().strftime("%Y%m%d")
    SAIDAS_DIR.mkdir(parents=True, exist_ok=True)
    caminho_pdf = SAIDAS_DIR / f"alerta_diario_{data_nome}.pdf"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html, wait_until="networkidle")
        page.pdf(path=str(caminho_pdf), format="A4", print_background=True)
        browser.close()

    return caminho_pdf, legenda_alerta(dados)

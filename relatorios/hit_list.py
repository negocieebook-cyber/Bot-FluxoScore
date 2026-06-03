from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright

from banco import conectar, criar_tabelas
try:
    from config import SETORES
except ModuleNotFoundError:
    from config_base import SETORES
from relatorios.narrativa import flag_tape, qualidade_dados


BASE_DIR = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = BASE_DIR / "templates"
SAIDAS_DIR = BASE_DIR / "saidas"


def _ticker_setor():
    return {
        ticker: setor
        for setor, tickers in SETORES.items()
        for ticker in tickers
    }


def _datas_scores():
    with conectar() as conn:
        return [
            row[0]
            for row in conn.execute(
                "SELECT DISTINCT data_semana FROM scores ORDER BY data_semana"
            ).fetchall()
        ]


def _quadrantes():
    with conectar() as conn:
        data = conn.execute("SELECT MAX(data_semana) FROM scores_setor").fetchone()[0]
        if not data:
            return {}
        rows = conn.execute(
            """
            SELECT setor, rs_ratio, rs_momentum
            FROM scores_setor
            WHERE data_semana = ?
            """,
            (data,),
        ).fetchall()

    resultado = {}
    for setor, rs_ratio, rs_momentum in rows:
        if rs_ratio >= 100 and rs_momentum >= 100:
            resultado[setor] = "Leading"
        elif rs_ratio >= 100:
            resultado[setor] = "Weakening"
        elif rs_momentum >= 100:
            resultado[setor] = "Improving"
        else:
            resultado[setor] = "Lagging"
    return resultado


def _scores(data_semana):
    with conectar() as conn:
        rows = conn.execute(
            """
            SELECT ticker, score, cf, trend, mom, rs_momentum, UDVR, DDVR
            FROM scores
            WHERE data_semana = ?
            """,
            (data_semana,),
        ).fetchall()
    return {
        row[0]: {
            "ticker": row[0],
            "score": float(row[1]),
            "cf": float(row[2]),
            "trend": float(row[3]),
            "mom": float(row[4]),
            "rs_momentum": float(row[5]),
            "UDVR": float(row[6] or 0),
            "DDVR": float(row[7] or 0),
        }
        for row in rows
    }


def _minima_semana(ticker, data_semana):
    with conectar() as conn:
        row = conn.execute(
            """
            SELECT MIN(minima)
            FROM precos
            WHERE ticker = ?
              AND data >= date(?, '-4 days')
              AND data <= ?
            """,
            (ticker, data_semana, data_semana),
        ).fetchone()
    return row[0] if row and row[0] is not None else None


def _classificar_tier(score, salto):
    if salto is not None and salto >= 15 and score >= 70:
        return "tier1"
    if salto is not None and 10 <= salto < 15 and score >= 70:
        return "tier2"
    if salto is not None and salto >= 15 and 60 <= score < 70:
        return "tier3"
    if score >= 80:
        return "tier4"
    return None


def _significado(item):
    if item["tier"] == "tier1" and item["UDVR"] >= 1.5:
        return "aceleração súbita com acumulação: burst de alta convicção"
    if item["tier"] == "tier1":
        return "salto forte de score com liderança já acima de 70"
    if item["tier"] == "tier2":
        return "movimento perto de burst, mas ainda abaixo do salto forte"
    if item["tier"] == "tier3":
        return "aceleração relevante, ainda em faixa moderada de score"
    if item["tier"] == "tier4":
        return "alta convicção por score absoluto elevado, mesmo sem histórico de salto"
    return "sinal de aceleração"


def _item_base(item, setor, quadrante, data_semana, salto, tier):
    minima = _minima_semana(item["ticker"], data_semana)
    tape = flag_tape(item["UDVR"], item["DDVR"], item["score"])
    flags = [] if tape == "—" else [tape]
    novo = dict(item)
    novo.update(
        {
            "setor": setor,
            "quadrante": quadrante,
            "salto": salto,
            "tier": tier,
            "tier_curto": {
                "tier1": "TIER 1",
                "tier2": "TIER 2",
                "tier3": "TIER 3",
                "tier4": "TIER 4",
            }[tier],
            "flags": flags,
            "flags_txt": " | ".join(flags) if flags else "sem flags ativas",
            "invalidacao": f"abaixo de R$ {minima:.2f}" if minima is not None else "sem nivel",
        }
    )
    novo["significado"] = _significado(novo)
    return novo


def montar_hit_list():
    datas = _datas_scores()
    if not datas:
        raise ValueError("scores vazio; calcule os scores antes do Hit List")

    data_atual = datas[-1]
    data_anterior = datas[-2] if len(datas) >= 2 else None
    historico_insuficiente = data_anterior is None
    setor_por_ticker = _ticker_setor()
    quadrantes = _quadrantes()
    atual = _scores(data_atual)
    anterior = _scores(data_anterior) if data_anterior else {}

    tiers = {
        "tier1": [],
        "tier2": [],
        "tier3": [],
        "tier4": [],
    }

    for ticker, item in atual.items():
        if ticker not in setor_por_ticker:
            continue
        salto = None
        if ticker in anterior:
            salto = item["score"] - anterior[ticker]["score"]
        tier = _classificar_tier(item["score"], salto)
        if not tier:
            continue
        setor = setor_por_ticker[ticker]
        quadrante = quadrantes.get(setor, "RRG indisponivel")
        tiers[tier].append(_item_base(item, setor, quadrante, data_atual, salto, tier))

    for itens in tiers.values():
        itens.sort(key=lambda item: item["score"], reverse=True)

    observacao = []
    if historico_insuficiente:
        observacao.append("Tiers 1-3 aguardam a segunda semana de scores para medir salto.")
    if tiers["tier4"]:
        observacao.append("Tier 4 já funciona com uma semana porque depende apenas de score >=80.")

    sem_burst_real = (
        not tiers["tier1"]
        and not tiers["tier2"]
        and not tiers["tier3"]
        and bool(tiers["tier4"])
    )

    return {
        "data_semana": data_atual,
        "historico_insuficiente": historico_insuficiente,
        "sem_burst_real": sem_burst_real,
        "tiers": [
            {
                "id": "tier1",
                "nome": "Tier 1 — Burst Forte",
                "descricao": "salto >= 15 pts e score atual >= 70",
                "historico_insuficiente": historico_insuficiente,
                "acoes": tiers["tier1"],
            },
            {
                "id": "tier2",
                "nome": "Tier 2 — Near-Burst",
                "descricao": "salto entre 10 e 14,99 pts e score atual >= 70",
                "historico_insuficiente": historico_insuficiente,
                "acoes": tiers["tier2"],
            },
            {
                "id": "tier3",
                "nome": "Tier 3 — Big Move",
                "descricao": "salto >= 15 pts e score atual entre 60 e 69,99",
                "historico_insuficiente": historico_insuficiente,
                "acoes": tiers["tier3"],
            },
            {
                "id": "tier4",
                "nome": "Tier 4 — Alta Convicção",
                "descricao": "score atual >= 80, independente de salto",
                "historico_insuficiente": False,
                "acoes": tiers["tier4"],
            },
        ],
        "observacao": observacao,
        "qualidade": qualidade_dados(data_atual),
    }


def tem_acoes(dados):
    tiers = dados.get("tiers", [])
    return any(
        tier.get("id") in ("tier1", "tier2", "tier3", "tier4") and tier.get("acoes")
        for tier in tiers
    )


def legenda_hit_list(dados):
    total = sum(len(tier["acoes"]) for tier in dados["tiers"])
    return f"The Hit List — {total} ações em burst/alta convicção. Abra o PDF."


def gerar_hit_list_pdf():
    criar_tabelas()
    dados = montar_hit_list()

    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(["html"]),
    )
    html = env.get_template("hit_list.html").render(**dados)
    data_nome = datetime.strptime(dados["data_semana"], "%Y-%m-%d").strftime("%Y%m%d")
    SAIDAS_DIR.mkdir(parents=True, exist_ok=True)
    caminho_pdf = SAIDAS_DIR / f"hit_list_{data_nome}.pdf"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content(html, wait_until="networkidle")
        page.pdf(path=str(caminho_pdf), format="A4", print_background=True)
        browser.close()

    return caminho_pdf, legenda_hit_list(dados), dados


if __name__ == "__main__":
    pdf, legenda, dados = gerar_hit_list_pdf()
    print(f"PDF gerado: {pdf}")
    print(legenda)
    for tier in dados["tiers"]:
        print(tier["nome"], [item["ticker"] for item in tier["acoes"]])

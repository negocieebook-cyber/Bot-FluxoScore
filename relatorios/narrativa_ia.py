import json

import requests

from config import OPENROUTER_API_KEY, OPENROUTER_MODEL


SYSTEM_PROMPT = (
    "Você é um analista que escreve a abertura de um relatório de fluxo setorial da B3. "
    "Use EXCLUSIVAMENTE os números fornecidos. NUNCA invente dados, preços, percentuais "
    "ou fatos que não estejam no input. NÃO faça previsões. NÃO recomende compra/venda. "
    "Se um dado não foi fornecido, não o mencione. Escreva como um analista experiente "
    "explicando o cenário para um investidor. Conte a HISTÓRIA da rotação de capital: "
    "para onde o dinheiro foi, de onde saiu, e por quê, conectando com o macro apenas "
    "se dados macro forem fornecidos. Use os números com PARCIMÔNIA — cite só os 2-3 "
    "mais relevantes para sustentar a narrativa, não liste todos. Prefira frases que "
    "expliquem o movimento a frases que enumeram dados. Tom profissional mas fluido, "
    "como um comentário de mercado. 4-6 frases. Português."
)


def _openrouter_configurado():
    return (
        OPENROUTER_API_KEY
        and not OPENROUTER_API_KEY.startswith("COLOQUE_")
        and OPENROUTER_MODEL
    )


def _fallback_regras(dados):
    if dados.get("fallback_texto"):
        return dados["fallback_texto"]

    setores = dados.get("setores", [])
    lideres = setores[:2]
    if not lideres:
        return "A semana não mostrou liderança setorial clara acima do corte de score. A leitura por regras aponta mercado seletivo, com rotação ainda indefinida e necessidade de confirmação nos próximos dados. Sem histórico suficiente nos movers, o relatório preserva uma leitura conservadora."

    nomes = ", ".join(f"{s['setor']} ({s['score']:.1f})" for s in lideres)
    frases = [
        f"O fluxo setorial ficou concentrado em {nomes}.",
        "A leitura por regras indica rotação seletiva, com prioridade para setores que combinam score alto, quadrante favorável e confirmação interna.",
    ]
    estreitos = [
        s["setor"]
        for s in lideres
        if str(s.get("confirmacao_interna", "")).startswith("Fraca")
    ]
    if estreitos:
        frases.append(
            "A liderança estreita em " + ", ".join(estreitos) + " reduz a qualidade do sinal, pois poucas ações explicam o movimento."
        )
    if dados.get("biggest_movers", {}).get("historico_insuficiente"):
        frases.append("Os maiores movimentos contra a semana anterior ainda têm histórico insuficiente.")
    return " ".join(frases)


def _validar_texto(texto):
    texto = (texto or "").strip()
    if len(texto) < 100 or len(texto) > 1500:
        return None
    return texto


def gerar_leitura_estrategica(dados):
    if not _openrouter_configurado():
        print("narrativa: regras/fallback")
        return _fallback_regras(dados)

    payload = {
        "model": OPENROUTER_MODEL,
        "temperature": 0.4,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Escreva a leitura estratégica usando somente este JSON:\n"
                    + json.dumps(dados, ensure_ascii=False, indent=2)
                ),
            },
        ],
    }

    try:
        resposta = requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "X-Title": "Flow Map Brasil",
            },
            json=payload,
            timeout=15,
        )
        resposta.raise_for_status()
        data = resposta.json()
        texto = data["choices"][0]["message"]["content"]
        texto = _validar_texto(texto)
        if not texto:
            raise ValueError("texto IA vazio/curto/longo")
        print("narrativa: IA")
        return texto
    except Exception as erro:
        print(f"narrativa: regras/fallback ({erro})")
        return _fallback_regras(dados)

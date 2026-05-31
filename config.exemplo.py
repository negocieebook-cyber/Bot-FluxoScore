# config.exemplo.py
# Modelo de configuração. Copie para config.py e preencha com suas chaves.
# O config.py real está no .gitignore e NUNCA deve ir para o GitHub.

# === CHAVES (preencha as suas) ===
TOKEN_BRAPI = "seu_token_brapi_aqui"
TOKEN_TELEGRAM = "seu_token_telegram_aqui"
CHAT_ID_TELEGRAM = "seu_chat_id_aqui"
OPENROUTER_API_KEY = "sua_key_openrouter_aqui"
OPENROUTER_MODEL = "anthropic/claude-3.5-haiku"

# === SETORES E TICKERS B3 ===
SETORES = {
    "Bancos": ["ITUB4", "BBAS3", "BBDC4", "SANB11", "BPAC11"],
    "Petroleo": ["PETR4", "PETR3", "PRIO3", "RECV3", "BRAV3"],
    "Mineracao": ["VALE3", "GGBR4", "CSNA3", "USIM5", "CMIN3"],
    "Energia": ["AXIA3", "AXIA6", "EGIE3", "TAEE11", "CPFE3", "ENEV3"],
    "Varejo": ["LREN3", "VIVA3", "MGLU3", "ASAI3", "GMAT3", "SOMA3"],
    "Saude": ["RADL3", "HAPV3", "RDOR3", "FLRY3"],
    "Construcao": ["CYRE3", "MRVE3", "DIRR3", "EZTC3", "MULT3", "IGTI11"],
    "Papel": ["SUZB3", "KLBN11"],
    "Agro": ["JBSS32", "BEEF3", "SLCE3", "SMTO3"],
    "Tecnologia": ["TOTS3", "LWSA3", "CASH3"],
}
BENCHMARK = "BOVA11"

TODOS_OS_TICKERS = [BENCHMARK]
for acoes in SETORES.values():
    TODOS_OS_TICKERS += acoes

# === FILTROS (tradability) ===
MIN_MARKET_CAP = 5_000_000_000   # R$ 5 bi
MIN_PRECO = 5.0
MIN_VOLUME_DIARIO = 8_000_000    # R$ 8 mi/dia

# === LIMIARES DE SCORE ===
SCORE_FORTE = 70
SCORE_MODERADO = 60

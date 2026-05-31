import os

TOKEN_BRAPI = os.environ.get("TOKEN_BRAPI", "")
TOKEN_TELEGRAM = os.environ.get("TOKEN_TELEGRAM", "")
CHAT_ID_TELEGRAM = os.environ.get("CHAT_ID_TELEGRAM", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

# Opcoes sugeridas:
# - "google/gemini-2.0-flash-001" (barato, rapido, recomendado)
# - "anthropic/claude-3.5-haiku" (barato, otimo portugues)
# - "openai/gpt-4o-mini" (barato, equilibrado)
OPENROUTER_MODEL = os.environ.get("OPENROUTER_MODEL", "anthropic/claude-3.5-haiku")

SETORES_B3 = {
    "Bancos": ["ITUB4", "BBAS3", "BBDC4", "SANB11", "BPAC11"],
    "Petroleo": ["PETR4", "PETR3", "PRIO3", "RECV3", "BRAV3"],
    "Mineracao": ["VALE3", "GGBR4", "CSNA3", "USIM5", "CMIN3"],
    "Energia": ["AXIA3", "AXIA6", "EGIE3", "TAEE11", "CPFE3", "ENEV3"],
    "Varejo": ["LREN3", "VIVA3", "MGLU3", "ASAI3", "GMAT3", "AZZA3"],
    "Saude": ["RADL3", "HAPV3", "RDOR3", "FLRY3"],
    "Construcao": ["CYRE3", "MRVE3", "DIRR3", "EZTC3", "MULT3", "IGTI11"],
    "Papel": ["SUZB3", "KLBN11"],
    "Agro": ["JBSS32", "BEEF3", "SLCE3", "SMTO3"],
    "Tecnologia": ["TOTS3", "LWSA3", "CASH3"],
}
SETORES = SETORES_B3

BENCHMARK = "BOVA11"

TODOS_OS_TICKERS = [BENCHMARK] + [
    ticker
    for tickers_do_setor in SETORES_B3.values()
    for ticker in tickers_do_setor
]

MIN_MARKET_CAP = 5e9
MIN_PRECO = 5.0
MIN_VOLUME_DIARIO = 8e6
SCORE_FORTE = 70
SCORE_MODERADO = 60

import asyncio
from pathlib import Path

from telegram import Bot

try:
    from config import CHAT_ID_TELEGRAM, TOKEN_TELEGRAM
except ModuleNotFoundError:
    from config_base import CHAT_ID_TELEGRAM, TOKEN_TELEGRAM


def _telegram_configurado():
    token_ok = TOKEN_TELEGRAM and not TOKEN_TELEGRAM.startswith("COLOQUE_")
    chat_ok = CHAT_ID_TELEGRAM and not str(CHAT_ID_TELEGRAM).startswith("COLOQUE_")
    return token_ok and chat_ok


async def _enviar_texto_async(mensagem):
    bot = Bot(token=TOKEN_TELEGRAM)
    await bot.send_message(chat_id=CHAT_ID_TELEGRAM, text=mensagem)


async def _enviar_pdf_async(caminho_pdf, legenda):
    bot = Bot(token=TOKEN_TELEGRAM)
    with Path(caminho_pdf).open("rb") as arquivo:
        await bot.send_document(
            chat_id=CHAT_ID_TELEGRAM,
            document=arquivo,
            caption=legenda[:1024],
        )


def enviar_texto(mensagem):
    if not _telegram_configurado():
        print("Telegram nao configurado: TOKEN_TELEGRAM/CHAT_ID_TELEGRAM ausentes.")
        return False
    try:
        asyncio.run(_enviar_texto_async(mensagem))
        print("Texto enviado ao Telegram.")
        return True
    except Exception as erro:
        print(f"Erro ao enviar texto ao Telegram: {erro}")
        return False


def enviar_pdf(caminho_pdf, legenda):
    if not _telegram_configurado():
        print("Telegram nao configurado: TOKEN_TELEGRAM/CHAT_ID_TELEGRAM ausentes.")
        return False
    try:
        asyncio.run(_enviar_pdf_async(caminho_pdf, legenda))
        print(f"PDF enviado ao Telegram: {caminho_pdf}")
        return True
    except Exception as erro:
        print(f"Erro ao enviar PDF ao Telegram: {erro}")
        return False

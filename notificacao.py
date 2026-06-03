import asyncio
import time
from pathlib import Path

from telegram import Bot

try:
    from config import CHAT_ID_TELEGRAM, TOKEN_TELEGRAM
except ModuleNotFoundError:
    from config_base import CHAT_ID_TELEGRAM, TOKEN_TELEGRAM


PDF_ENVIO_TENTATIVAS = 3
PDF_ENVIO_ESPERA_SEGUNDOS = 5
PDF_ENVIO_TIMEOUT_SEGUNDOS = 60


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
            read_timeout=PDF_ENVIO_TIMEOUT_SEGUNDOS,
            write_timeout=PDF_ENVIO_TIMEOUT_SEGUNDOS,
            connect_timeout=PDF_ENVIO_TIMEOUT_SEGUNDOS,
            pool_timeout=PDF_ENVIO_TIMEOUT_SEGUNDOS,
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

    for tentativa in range(1, PDF_ENVIO_TENTATIVAS + 1):
        try:
            asyncio.run(_enviar_pdf_async(caminho_pdf, legenda))
            print(f"envio {caminho_pdf}: tentativa {tentativa} - sucesso")
            print(f"PDF enviado ao Telegram: {caminho_pdf}")
            return True
        except Exception as erro:
            print(f"envio {caminho_pdf}: tentativa {tentativa} - falha ({erro})")
            if tentativa < PDF_ENVIO_TENTATIVAS:
                time.sleep(PDF_ENVIO_ESPERA_SEGUNDOS)

    print(f"Erro ao enviar PDF ao Telegram apos {PDF_ENVIO_TENTATIVAS} tentativas: {caminho_pdf}")
    return False

import argparse
from datetime import datetime

from banco import criar_tabelas
from diario import coletar_tudo, executar_varredura_diaria, recalcular_scores
from notificacao import enviar_pdf
from relatorios.capital_flow_leaders import gerar_capital_flow_leaders_pdf
from relatorios.flow_map import gerar_flow_map_pdf
from relatorios.hit_list import gerar_hit_list_pdf, tem_acoes
from relatorios.smart_money_exits import gerar_smart_money_exits_pdf
from rrg import gerar_rrg_setorial
from setor import calcular_scores_setoriais


def _eh_sabado(modo):
    if modo == "sabado":
        return True
    if modo in ("dia-comum", "quarta"):
        return False
    return datetime.now().weekday() == 5


def _eh_quarta(modo):
    if modo == "quarta":
        return True
    if modo in ("sabado", "dia-comum"):
        return False
    return datetime.now().weekday() == 2


def _preparar_base():
    criar_tabelas()
    print("Coletando dados...")
    coletados, falhas_coleta = coletar_tudo()
    print(f"Coleta finalizada: {coletados} tickers OK; falhas={falhas_coleta or 'nenhuma'}")
    print("Recalculando scores e tape...")
    scores, falhas_scores = recalcular_scores()
    print(f"Scores finalizados: {scores} tickers OK; falhas={falhas_scores or 'nenhuma'}")


def _rodar_sabado():
    print("Modo sabado: gerando relatórios semanais.")
    calcular_scores_setoriais(gravar=True)
    gerar_rrg_setorial()

    relatorios = [
        ("Flow Map", gerar_flow_map_pdf),
        ("Capital Flow Leaders", gerar_capital_flow_leaders_pdf),
        ("Smart Money Exits", gerar_smart_money_exits_pdf),
    ]
    enviados = []
    for nome, funcao in relatorios:
        caminho, resumo = funcao()
        print(f"{nome}: PDF gerado em {caminho}")
        enviado = enviar_pdf(caminho, resumo)
        enviados.append((nome, enviado))
    print(f"Envios: {enviados}")
    return enviados


def _rodar_dia_comum(forcar_sem_gatilho=False):
    print("Modo dia comum: rodando varredura diária.")
    caminho_pdf, legenda = executar_varredura_diaria(
        coletar_antes=False,
        forcar_sem_gatilhos=forcar_sem_gatilho,
    )
    if not caminho_pdf:
        print("Nenhum gatilho diário disparou. Nada gerado ou enviado.")
        return False
    print(f"Alerta diário: PDF gerado em {caminho_pdf}")
    enviado = enviar_pdf(caminho_pdf, legenda)
    print("Alerta diário enviado." if enviado else "Alerta diário não enviado.")
    return enviado


def _rodar_quarta():
    print("Modo quarta-feira: gerando The Hit List.")
    caminho, legenda, dados = gerar_hit_list_pdf()
    if not tem_acoes(dados):
        print("Hit List sem ações em tiers. Nada enviado.")
        return False
    print(f"The Hit List: PDF gerado em {caminho}")
    enviado = enviar_pdf(caminho, legenda)
    print("Hit List enviado." if enviado else "Hit List não enviado.")
    return enviado


def _rodar_completo():
    print("Modo completo: gerando todos os relatórios.")
    calcular_scores_setoriais(gravar=True)
    gerar_rrg_setorial()

    relatorios = [
        ("Flow Map", gerar_flow_map_pdf),
        ("Capital Flow Leaders", gerar_capital_flow_leaders_pdf),
        ("Smart Money Exits", gerar_smart_money_exits_pdf),
    ]
    enviados = []
    for nome, funcao in relatorios:
        caminho, resumo = funcao()
        print(f"{nome}: PDF gerado em {caminho}")
        enviados.append((nome, enviar_pdf(caminho, resumo)))

    caminho, legenda, dados = gerar_hit_list_pdf()
    print(f"The Hit List: PDF gerado em {caminho}")
    if tem_acoes(dados):
        enviados.append(("The Hit List", enviar_pdf(caminho, legenda)))
    else:
        enviados.append(("The Hit List", "sem ações; não enviado"))

    print(f"Envios: {enviados}")
    return enviados


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--modo",
        choices=["auto", "sabado", "quarta", "dia-comum", "completo"],
        default="auto",
        help="Força o comportamento para teste.",
    )
    parser.add_argument(
        "--forcar-sem-gatilho",
        action="store_true",
        help="Modo de teste: força nenhum gatilho diário.",
    )
    args = parser.parse_args()

    _preparar_base()
    if args.modo == "completo":
        _rodar_completo()
    elif _eh_sabado(args.modo):
        _rodar_sabado()
    elif _eh_quarta(args.modo):
        _rodar_quarta()
    else:
        _rodar_dia_comum(forcar_sem_gatilho=args.forcar_sem_gatilho)


if __name__ == "__main__":
    main()

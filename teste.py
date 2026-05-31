from banco import criar_tabelas
from relatorios.smart_money_exits import gerar_smart_money_exits_pdf


def main():
    criar_tabelas()

    caminho_pdf, resumo = gerar_smart_money_exits_pdf()

    print(f"PDF gerado: {caminho_pdf}")
    print("\nResumo:")
    print(resumo)


if __name__ == "__main__":
    main()

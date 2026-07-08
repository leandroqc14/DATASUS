import sys
from datasus_core import baixar_periodo_datasus

def main():
    print("====================================================")
    print("       📥 PRÉ-CARREGADOR DE DADOS DO DATASUS        ")
    print("====================================================")
    print("Use este script para baixar e cachear grandes volumes de dados")
    print("em segundo plano. Isso deixará as consultas no site instantâneas!\n")
    
    # 1. Select System
    sistemas_validos = {'sinasc': 'DN', 'sim': 'DO', 'sih': 'RD', 'sia': 'PA', 'cnes': 'LT'}
    sistema = input("1. Escolha o Sistema (sinasc / sim / sih / sia / cnes): ").strip().lower()
    if sistema not in sistemas_validos:
        print(f"❌ Sistema '{sistema}' inválido. Escolha entre: {list(sistemas_validos.keys())}")
        return
    sigla = sistemas_validos[sistema]
    
    # 2. Select UF
    uf = input("2. Digite a UF (Estado, ex: AC, SP, RJ ou BR para Brasil todo): ").strip().upper()
    if len(uf) != 2:
        print("❌ UF inválida. Deve conter exatamente 2 letras.")
        return
        
    # 3. Select Years
    try:
        ano_ini = int(input("3. Ano Inicial (ex: 2018): "))
        ano_fim = int(input("4. Ano Final (ex: 2022): "))
    except ValueError:
        print("❌ Ano deve ser um número inteiro.")
        return
        
    if ano_ini > ano_fim:
        print("❌ O ano inicial não pode ser maior que o ano final.")
        return
        
    print(f"\n🚀 Iniciando pré-carregamento de {sistema.upper()} ({uf}) no período {ano_ini} a {ano_fim}...")
    print("Aguarde, os dados serão salvos localmente em formato Parquet de alta performance.")
    
    try:
        df = baixar_periodo_datasus(sistema, sigla, uf, ano_ini, ano_fim)
        print("\n====================================================")
        print(f"✅ PRÉ-CARREGAMENTO CONCLUÍDO COM SUCESSO!")
        print(f"📊 Total de registros salvos em cache: {len(df):,}")
        print("====================================================")
        print("Agora, quando você consultar esse período no site, ele abrirá de forma instantânea!")
    except Exception as e:
        print(f"\n❌ Ocorreu um erro no pré-carregamento: {e}")

if __name__ == "__main__":
    main()

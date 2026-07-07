import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import io
import re
from datasus_core import buscar_dados, baixar_arquivo_datasus, CACHE_DIR

# Set page configuration with premium aesthetics
st.set_page_config(
    page_title="Portal DATASUS - Assistente Científico",
    page_icon="🏥",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Inject custom CSS for premium styling (glassmorphism look, custom gradients, typography)
st.markdown("""
<style>
    /* Gradient Background for headers */
    .main-title-container {
        background: linear-gradient(135deg, #0f2027, #203a43, #2c5364);
        padding: 2rem;
        border-radius: 12px;
        color: white;
        margin-bottom: 2rem;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    }
    
    .main-title-container h1 {
        color: #00f2fe !important;
        font-family: 'Inter', sans-serif;
        font-weight: 800;
        margin: 0;
        padding-bottom: 0.5rem;
    }
    
    .main-title-container p {
        font-size: 1.1rem;
        opacity: 0.9;
        margin: 0;
    }
    
    /* Card design */
    .metric-card {
        background-color: #f8f9fa;
        border-left: 5px solid #00f2fe;
        padding: 1.5rem;
        border-radius: 8px;
        box-shadow: 0 2px 10px rgba(0,0,0,0.05);
        margin-bottom: 1rem;
    }
    
    .metric-title {
        font-size: 0.9rem;
        color: #6c757d;
        text-transform: uppercase;
        font-weight: bold;
    }
    
    .metric-value {
        font-size: 1.8rem;
        color: #2c5364;
        font-weight: bold;
    }
    
    /* Footer styling */
    .footer-text {
        text-align: center;
        padding: 2rem 0;
        color: #6c757d;
        font-size: 0.85rem;
        border-top: 1px solid #dee2e6;
        margin-top: 3rem;
    }
</style>
""", unsafe_allowed_html=True)

# Main Page Header
st.markdown("""
<div class="main-title-container">
    <h1>Assistente Científico DATASUS 🇧🇷🏥</h1>
    <p>Baixe, processe e analise dados públicos de saúde diretamente em formato tabular e gráfico para artigos científicos e trabalhos acadêmicos.</p>
</div>
""", unsafe_allowed_html=True)

# Sidebar - Configurations & Filter Selection
st.sidebar.markdown("### ⚙️ Opções de Pesquisa")
metodo_busca = st.sidebar.radio(
    "Método de Entrada:",
    ["💡 Linguagem Natural (Recomendado)", "🎛️ Filtros Manuais (Formulário)"]
)

# Lists for manual filters
uf_lista = ['SP', 'RJ', 'MG', 'RS', 'PR', 'SC', 'BA', 'PE', 'CE', 'DF', 'ES', 'GO', 'MA', 'MT', 'MS', 'PA', 'PB', 'PI', 'RN', 'RO', 'RR', 'SE', 'TO', 'AC', 'AL', 'AP', 'AM']
uf_lista.sort()

ano_lista = list(range(2025, 1995, -1))

sistemas_lista = {
    "SINASC (Nascimentos)": ("sinasc", "DN"),
    "SIM (Mortalidade/Óbitos)": ("sim", "DO"),
    "SIHSUS (Internações Hospitalares)": ("sih", "RD"),
    "SIASUS (Produção Ambulatorial)": ("sia", "PA"),
    "CNES (Leitos de Saúde)": ("cnes", "LT")
}

# Sidebar settings
uf_selecionada = 'SP'
ano_selecionado = 2022
sistema_selecionado = 'sinasc'
sigla_selecionada = 'DN'
mes_selecionado = None

if metodo_busca == "🎛️ Filtros Manuais (Formulário)":
    sistema_label = st.sidebar.selectbox("Sistema de Saúde:", list(sistemas_lista.keys()))
    sistema_selecionado, sigla_selecionada = sistemas_lista[sistema_label]
    
    uf_selecionada = st.sidebar.selectbox("Unidade Federativa (UF):", uf_lista, index=uf_lista.index('SP'))
    ano_selecionado = st.sidebar.selectbox("Ano de Referência:", ano_lista, index=ano_lista.index(2022))
    
    # Months are only required for monthly databases (SIH, SIA, CNES)
    if sistema_selecionado in ['sih', 'sia', 'cnes']:
        meses_opcoes = {
            "Sem filtro (Janeiro como padrão)": None,
            "Janeiro (01)": 1, "Fevereiro (02)": 2, "Março (03)": 3,
            "Abril (04)": 4, "Maio (05)": 5, "Junho (06)": 6,
            "Julho (07)": 7, "Agosto (08)": 8, "Setembro (09)": 9,
            "Outubro (10)": 10, "Novembro (11)": 11, "Dezembro (12)": 12
        }
        mes_label = st.sidebar.selectbox("Mês:", list(meses_opcoes.keys()))
        mes_selecionado = meses_opcoes[mes_label]

st.sidebar.markdown("---")
st.sidebar.markdown("""
<div style="font-size: 0.85rem; color: #6c757d;">
    <b>Cache ativo:</b> Os dados baixados são convertidos e salvos em formato Apache Parquet localmente. Consultas repetidas serão carregadas instantaneamente!
</div>
""", unsafe_allowed_html=True)

# Application state
df = None
sistema_final = None
uf_final = None
ano_final = None
mes_final = None

# Main section interface based on selected search method
if metodo_busca == "💡 Linguagem Natural (Recomendado)":
    st.markdown("### 💡 O que você gostaria de pesquisar?")
    pergunta_usuario = st.text_input(
        "Digite a sua pergunta:",
        value="Quero analisar os nascimentos ocorridos no Acre em 2022",
        help="Exemplos: 'buscar óbitos em SP em 2023', 'internações em Alagoas em janeiro de 2021', 'nascimentos no Rio de Janeiro em 2020'"
    )
    
    # Process NLP to show preview of interpreted values
    pergunta_clean = pergunta_usuario.lower()
    
    # Extract UF
    uf_detectada = 'SP'
    for uf_item in uf_lista:
        if uf_item.lower() in pergunta_clean or f" {uf_item.lower()}" in pergunta_clean:
            uf_detectada = uf_item
            break
    # Check states by full name
    estados_nomes = {
        'acre': 'AC', 'alagoas': 'AL', 'amapá': 'AP', 'amazonas': 'AM', 'bahia': 'BA',
        'ceará': 'CE', 'distrito federal': 'DF', 'espírito santo': 'ES', 'goiás': 'GO',
        'maranhão': 'MA', 'mato grosso': 'MT', 'mato grosso do sul': 'MS', 'minas gerais': 'MG',
        'pará': 'PA', 'paraíba': 'PB', 'paraná': 'PR', 'pernambuco': 'PE', 'piauí': 'PI',
        'rio de janeiro': 'RJ', 'rio grande do norte': 'RN', 'rio grande do sul': 'RS',
        'rondônia': 'RO', 'roraima': 'RR', 'santa catarina': 'SC', 'são paulo': 'SP',
        'sergipe': 'SE', 'tocantins': 'TO'
    }
    for nome, sigla in estados_nomes.items():
        if nome in pergunta_clean:
            uf_detectada = sigla
            break
            
    # Extract Year
    ano_detectado = 2022
    match_ano = re.search(r'\b(20\d{2}|19\d{2})\b', pergunta_clean)
    if match_ano:
        ano_detectado = int(match_ano.group(1))
        
    # Extract Month
    mes_detectado = None
    meses_nomes = {
        'janeiro': 1, 'fevereiro': 2, 'março': 3, 'abril': 4, 'maio': 5, 'junho': 6,
        'julho': 7, 'agosto': 8, 'setembro': 9, 'outubro': 10, 'novembro': 11, 'dezembro': 12
    }
    for nome, num in meses_nomes.items():
        if nome in pergunta_clean:
            mes_detectado = num
            break
            
    # Extract System
    sistema_detectado = 'sim'
    if any(t in pergunta_clean for t in ['nascimento', 'nascidos', 'sinasc', 'parto', 'maternidade']):
        sistema_detectado = 'sinasc'
    elif any(t in pergunta_clean for t in ['internação', 'internações', 'hospitalização', 'sih', 'aih']):
        sistema_detectado = 'sih'
    elif any(t in pergunta_clean for t in ['ambulatório', 'ambulatorial', 'sia', 'consulta']):
        sistema_detectado = 'sia'
    elif any(t in pergunta_clean for t in ['cnes', 'leitos', 'estabelecimento']):
        sistema_detectado = 'cnes'
        
    st.markdown(f"""
    <div style="background-color: #eef2f3; padding: 0.8rem 1.2rem; border-radius: 8px; border-left: 4px solid #203a43; font-size: 0.9rem; margin-bottom: 1.5rem;">
        <b>🔍 O assistente irá buscar:</b> Sistema: <span style="color:#00f2fe; font-weight:bold;">{sistema_detectado.upper()}</span> | 
        Estado: <b>{uf_detectada}</b> | 
        Ano: <b>{ano_detectado}</b> | 
        Mês: <b>{mes_detectado if mes_detectado else 'Anual'}</b>
    </div>
    """, unsafe_allowed_html=True)
    
    col_btn, _ = st.columns([1, 4])
    with col_btn:
        btn_buscar = st.button("🚀 Buscar no DATASUS", use_container_width=True)
        
    if btn_buscar:
        with st.spinner("Conectando ao FTP do DATASUS e processando os dados (isso pode levar de alguns segundos a 1 minuto dependendo do tamanho)..."):
            try:
                df = buscar_dados(pergunta_usuario)
                st.session_state['df_datasus'] = df
                st.session_state['search_info'] = (sistema_detectado, uf_detectada, ano_detectado, mes_detectado)
            except Exception as e:
                st.error(f"Erro ao buscar os dados: {e}")

else:
    # Manual mode search triggers
    st.markdown("### 🎛️ Buscar com os Filtros da Barra Lateral")
    st.info(f"Filtros selecionados: {sistema_selecionado.upper()} ({sigla_selecionada}) para {uf_selecionada} em {ano_selecionado} " + (f"mês {mes_selecionado}" if mes_selecionado else "(ano completo)"))
    
    col_btn, _ = st.columns([1, 4])
    with col_btn:
        btn_buscar_manual = st.button("🚀 Buscar no DATASUS", use_container_width=True)
        
    if btn_buscar_manual:
        with st.spinner("Conectando e baixando dados..."):
            try:
                df = baixar_arquivo_datasus(sistema_selecionado, sigla_selecionada, uf_selecionada, ano_selecionado, mes_selecionado)
                st.session_state['df_datasus'] = df
                st.session_state['search_info'] = (sistema_selecionado, uf_selecionada, ano_selecionado, mes_selecionado)
            except Exception as e:
                st.error(f"Erro ao buscar os dados: {e}")

# Retrieve from session state if search completed
if 'df_datasus' in st.session_state:
    df = st.session_state['df_datasus']
    sistema_final, uf_final, ano_final, mes_final = st.session_state['search_info']

# Display results if dataset is loaded
if df is not None:
    st.markdown("---")
    st.success("🎉 Dados carregados com sucesso!")
    
    # Metrics display
    col_m1, col_m2, col_m3 = st.columns(3)
    with col_m1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Total de Registros (Linhas)</div>
            <div class="metric-value">{len(df):,}</div>
        </div>
        """, unsafe_allowed_html=True)
    with col_m2:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Quantidade de Variáveis</div>
            <div class="metric-value">{df.shape[1]}</div>
        </div>
        """, unsafe_allowed_html=True)
    with col_m3:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Estado / Ano pesquisado</div>
            <div class="metric-value">{uf_final} / {ano_final}</div>
        </div>
        """, unsafe_allowed_html=True)
        
    # Tabs for navigation (Preview, Visualization, Export)
    tab_dados, tab_graficos, tab_exportar = st.tabs(["📊 Visualizar Tabela", "📈 Análise e Gráficos", "💾 Exportar Dados"])
    
    with tab_dados:
        st.markdown("#### 🔍 Visualização Interativa da Tabela")
        st.write("Filtre, pesquise ou ordene os dados usando o próprio componente abaixo:")
        st.dataframe(df.head(200), use_container_width=True)
        st.caption("Exibindo as primeiras 200 linhas para garantir rapidez no navegador.")
        
    with tab_graficos:
        st.markdown("#### 📊 Análises Gráficas Científicas")
        
        # 1. Custom graphs based on the loaded system
        if 'IDADEMAE' in df.columns:
            # SINASC births data
            st.info("💡 Detectado conjunto de dados de NASCIMENTOS (SINASC). Gerando visualizações recomendadas:")
            
            # Prepare data
            df['IDADEMAE'] = pd.to_numeric(df['IDADEMAE'], errors='coerce')
            
            col_g1, col_g2 = st.columns(2)
            with col_g1:
                st.markdown("##### Distribuição de Idades das Mães")
                fig, ax = plt.subplots(figsize=(8, 4.5))
                sns.histplot(data=df, x='IDADEMAE', kde=True, color='teal', bins=25, ax=ax)
                ax.set_title("Idade das Mães no Nascimento", fontweight='bold')
                ax.set_xlabel("Idade da Mãe (Anos)")
                ax.set_ylabel("Quantidade de Casos")
                st.pyplot(fig)
                
            with col_g2:
                st.markdown("##### Proporção por Tipo de Parto")
                if 'PARTO' in df.columns:
                    parto_labels = {'1': 'Vaginal', '2': 'Cesáreo'}
                    df['Tipo_Parto'] = df['PARTO'].astype(str).map(parto_labels).fillna('Não Informado/Outros')
                    
                    fig, ax = plt.subplots(figsize=(8, 4.5))
                    sns.countplot(data=df, x='Tipo_Parto', palette='Set2', hue='Tipo_Parto', legend=False, ax=ax)
                    ax.set_title("Proporção por Tipo de Parto", fontweight='bold')
                    ax.set_xlabel("Tipo de Parto")
                    ax.set_ylabel("Quantidade")
                    st.pyplot(fig)
                else:
                    st.warning("Variável 'PARTO' não encontrada no banco de dados.")
                    
        elif 'CAUSABAS' in df.columns:
            # SIM mortality data
            st.info("💡 Detectado conjunto de dados de MORTALIDADE (SIM). Gerando visualizações recomendadas:")
            
            col_g1, col_g2 = st.columns(2)
            with col_g1:
                st.markdown("##### Top 10 Causas de Óbitos (CID-10)")
                top10_morte = df['CAUSABAS'].value_counts().head(10).reset_index()
                top10_morte.columns = ['CID-10', 'Óbitos']
                
                fig, ax = plt.subplots(figsize=(8, 4.5))
                sns.barplot(data=top10_morte, x='Óbitos', y='CID-10', palette='Reds_r', hue='CID-10', legend=False, ax=ax)
                ax.set_title("Top 10 Principais CIDs de Óbitos", fontweight='bold')
                ax.set_xlabel("Quantidade de Óbitos")
                ax.set_ylabel("Causa CID-10")
                st.pyplot(fig)
                
            with col_g2:
                st.markdown("##### Distribuição de Óbitos por Sexo")
                if 'SEXO' in df.columns:
                    sexo_labels = {'1': 'Masculino', '2': 'Feminino', '0': 'Ignorado'}
                    df['Sexo_Label'] = df['SEXO'].astype(str).map(sexo_labels).fillna('Não Informado')
                    
                    fig, ax = plt.subplots(figsize=(8, 4.5))
                    sns.countplot(data=df, x='Sexo_Label', palette='coolwarm', hue='Sexo_Label', legend=False, ax=ax)
                    ax.set_title("Óbitos Organizados por Sexo", fontweight='bold')
                    ax.set_xlabel("Sexo")
                    ax.set_ylabel("Óbitos")
                    st.pyplot(fig)
                else:
                    st.warning("Variável 'SEXO' não encontrada no banco de dados.")
                    
        elif 'DIAG_PRINC' in df.columns:
            # SIHSUS hospitalization data
            st.info("💡 Detectado conjunto de dados de INTERNAÇÕES HOSPITALARES (SIHSUS). Gerando visualizações recomendadas:")
            
            st.markdown("##### Top 10 Diagnósticos Principais de Internação (CIDs)")
            top_internacoes = df['DIAG_PRINC'].value_counts().head(10).reset_index()
            top_internacoes.columns = ['Diagnóstico (CID)', 'Internações']
            
            fig, ax = plt.subplots(figsize=(10, 5))
            sns.barplot(data=top_internacoes, x='Internações', y='Diagnóstico (CID)', palette='viridis', hue='Diagnóstico (CID)', legend=False, ax=ax)
            ax.set_title("Top 10 Diagnósticos de Internação (CID Principal)", fontweight='bold')
            ax.set_xlabel("Quantidade de Internações")
            ax.set_ylabel("Diagnóstico Principal (CID)")
            st.pyplot(fig)
            
        else:
            # Fallback for other data structures
            st.info("📊 Dados carregados com sucesso. Selecione variáveis nos eixos abaixo para fazer uma exploração personalizada:")
            
            numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
            categorical_cols = df.select_dtypes(exclude=['number']).columns.tolist()
            
            if len(categorical_cols) > 0 and len(df) > 0:
                col_vars1, col_vars2 = st.columns(2)
                with col_vars1:
                    col_x = st.selectbox("Escolha a Variável Categoria (Eixo Y):", categorical_cols[:10])
                with col_vars2:
                    top_n = st.slider("Quantidade de categorias:", 5, 20, 10)
                    
                top_data = df[col_x].value_counts().head(top_n).reset_index()
                top_data.columns = [col_x, 'Frequência']
                
                fig, ax = plt.subplots(figsize=(8, 4.5))
                sns.barplot(data=top_data, x='Frequência', y=col_x, palette='Blues_r', hue=col_x, legend=False, ax=ax)
                ax.set_title(f"Distribuição de Frequência de '{col_x}'", fontweight='bold')
                st.pyplot(fig)
            else:
                st.warning("Variáveis não estruturadas de forma categórica para plotagem automática.")

    with tab_exportar:
        st.markdown("#### 💾 Exportar e Salvar Base Tratada")
        st.write("Exporte os dados completos tratados localmente para poder abri-los em softwares como Excel, SPSS ou RStudio.")
        
        # Memory buffer to avoid writing file on host disk again (keeps it fast)
        csv_buffer = io.BytesIO()
        df.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
        csv_buffer.seek(0)
        
        nome_arquivo_export = f"datasus_{sistema_final}_{uf_final}_{ano_final}"
        if mes_final:
            nome_arquivo_export += f"_{mes_final:02d}"
        nome_arquivo_export += ".csv"
        
        st.download_button(
            label="📥 Baixar Base Completa em CSV (Excel)",
            data=csv_buffer,
            file_name=nome_arquivo_export,
            mime="text/csv",
            use_container_width=True
        )
        st.success(f"Arquivo pronto para download: `{nome_arquivo_export}`")

# Footer
st.markdown("""
<div class="footer-text">
    Desenvolvido com ❤️ para Pesquisadores Científicos no Brasil. 🇧🇷🏥<br>
    Dados obtidos diretamente do servidor FTP do DATASUS - Ministério da Saúde.
</div>
""", unsafe_allowed_html=True)

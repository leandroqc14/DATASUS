import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
import io
import os
import re
from datasus_core import buscar_dados, baixar_periodo_datasus, CACHE_DIR

def adicionar_rotulos(ax):
    """
    Adiciona rótulos de valores exatos no topo ou ponta das barras dos gráficos.
    Usa ponto como separador de milhar no padrão brasileiro.
    """
    if ax.containers:
        for container in ax.containers:
            try:
                # Formata com separador de milhar brasileiro (ponto)
                labels = [f'{int(x):,}'.replace(',', '.') if x > 0 else '' for x in container.datavalues]
                ax.bar_label(container, labels=labels, padding=3, fontsize=9)
            except:
                try:
                    ax.bar_label(container, padding=3, fontsize=9)
                except:
                    pass

def filtrar_cids(df, col, texto_busca):
    """
    Filtra um DataFrame por códigos CID-10 suportando:
    - CIDs únicos (ex: M80 ou M80.0)
    - Lista de CIDs (ex: M80, M81, M82)
    - Intervalo de CIDs (ex: M80-M85 ou M80 a M85)
    """
    if not texto_busca:
        return df
        
    # Remove pontos e padroniza para maiúsculo
    texto_busca = texto_busca.upper().replace('.', '').strip()
    
    # Divide por vírgula ou ponto e vírgula
    tokens = [t.strip() for t in re.split(r'[,;]+', texto_busca) if t.strip()]
    
    mask = pd.Series(False, index=df.index)
    
    for token in tokens:
        # Verifica se é uma faixa de CIDs (ex: M80-M85 ou M80 A M85)
        match_range = re.match(r'^([A-Z][0-9]{2,3})\s*[-A\s]+\s*([A-Z][0-9]{2,3})$', token)
        if match_range:
            start_cat, end_cat = match_range.groups()
            length = len(start_cat)
            codigos_col = df[col].astype(str).str.upper().str.strip().str.slice(0, length)
            mask = mask | ((codigos_col >= start_cat) & (codigos_col <= end_cat))
        else:
            # Busca padrão por início do código (startswith)
            mask = mask | df[col].astype(str).str.upper().str.strip().str.startswith(token)
            
    return df[mask]

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
""", unsafe_allow_html=True)

# Main Page Header
st.markdown("""
<div class="main-title-container">
    <h1>Assistente Científico DATASUS 🇧🇷🏥</h1>
    <p>Baixe, processe, cruze e analise dados públicos de saúde por períodos e filtros demográficos prontos para artigos acadêmicos.</p>
</div>
""", unsafe_allow_html=True)

# Sidebar - Configurations & Filter Selection
st.sidebar.markdown("### ⚙️ Opções de Pesquisa")
metodo_busca = st.sidebar.radio(
    "Método de Entrada:",
    ["💡 Linguagem Natural (Recomendado)", "🎛️ Filtros Manuais (Formulário)"]
)

# Lists for manual filters
uf_lista = ['SP', 'RJ', 'MG', 'RS', 'PR', 'SC', 'BA', 'PE', 'CE', 'DF', 'ES', 'GO', 'MA', 'MT', 'MS', 'PA', 'PB', 'PI', 'RN', 'RO', 'RR', 'SE', 'TO', 'AC', 'AL', 'AP', 'AM']
uf_lista.sort()
uf_lista.insert(0, 'BR') # Add BR for nationwide search

def formatar_uf(uf_code):
    if uf_code == 'BR':
        return "BR (Brasil - Todos os Estados)"
    return uf_code

sistemas_lista = {
    "SINASC (Nascimentos)": ("sinasc", "DN"),
    "SIM (Mortalidade/Óbitos)": ("sim", "DO"),
    "SIHSUS (Internações Hospitalares)": ("sih", "RD"),
    "SIASUS (Produção Ambulatorial)": ("sia", "PA"),
    "CNES (Leitos de Saúde)": ("cnes", "LT")
}

# Sidebar settings (Manual)
uf_selecionada = 'SP'
ano_inicio_sel = 2022
ano_fim_sel = 2022
sistema_selecionado = 'sinasc'
sigla_selecionada = 'DN'
mes_selecionado = None
cid_manual_input = ""

if metodo_busca == "🎛️ Filtros Manuais (Formulário)":
    sistema_label = st.sidebar.selectbox("Sistema de Saúde:", list(sistemas_lista.keys()))
    sistema_selecionado, sigla_selecionada = sistemas_lista[sistema_label]
    
    uf_selecionada = st.sidebar.selectbox(
        "Unidade Federativa (UF):",
        uf_lista,
        format_func=formatar_uf,
        index=uf_lista.index('SP')
    )
    
    # Year Range selection using a slider
    ano_range = st.sidebar.slider("Período (Anos):", 1996, 2025, (2021, 2022))
    ano_inicio_sel, ano_fim_sel = ano_range
    
    # Months are only required for monthly databases (SIH, SIA, CNES)
    if sistema_selecionado in ['sih', 'sia', 'cnes']:
        meses_opcoes = {
            "Todos os meses (Ano Completo)": None,
            "Janeiro (01)": 1, "Fevereiro (02)": 2, "Março (03)": 3,
            "Abril (04)": 4, "Maio (05)": 5, "Junho (06)": 6,
            "Julho (07)": 7, "Agosto (08)": 8, "Setembro (09)": 9,
            "Outubro (10)": 10, "Novembro (11)": 11, "Dezembro (12)": 12
        }
        mes_label = st.sidebar.selectbox("Mês:", list(meses_opcoes.keys()))
        mes_selecionado = meses_opcoes[mes_label]
        
    # Optional CID-10 Filter in sidebar
    if sistema_selecionado in ['sim', 'sih', 'sia']:
        cid_manual_input = st.sidebar.text_input(
            "Filtrar por CID-10 (Opcional):",
            value="",
            help="Digite o CID (Ex: M80.0 ou M80). Deixe vazio para baixar todos os diagnósticos."
        )

st.sidebar.markdown("---")
st.sidebar.markdown("""
<div style="font-size: 0.85rem; color: #6c757d;">
    <b>Cache ativo:</b> Os dados baixados são convertidos e salvos em formato Apache Parquet localmente. Consultas repetidas serão carregadas instantaneamente!
</div>
""", unsafe_allow_html=True)

# Application state
df_raw = None
sistema_final = None
uf_final = None
ano_inicio_final = None
ano_fim_final = None
mes_final = None

# Main section interface based on selected search method
if metodo_busca == "💡 Linguagem Natural (Recomendado)":
    st.markdown("### 💡 O que você gostaria de pesquisar?")
    pergunta_usuario = st.text_input(
        "Digite a sua pergunta (inclua o período, ex: de 2020 a 2022):",
        value="Quero analisar os nascimentos no Acre de 2021 a 2022",
        help="Exemplos: 'buscar óbitos em SP de 2020 a 2022', 'nascimentos no Rio de Janeiro em 2020', 'internações no Acre em 2021'"
    )
    
    # Process NLP to show preview of interpreted values
    pergunta_clean = pergunta_usuario.lower()
    
    # Extract UF
    uf_detectada = 'SP'
    if 'brasil' in pergunta_clean or ' nacional' in pergunta_clean or ' br' in pergunta_clean or 'todo o brasil' in pergunta_clean:
        uf_detectada = 'BR'
    else:
        for uf_item in uf_lista:
            if uf_item != 'BR' and (uf_item.lower() in pergunta_clean or f" {uf_item.lower()}" in pergunta_clean):
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
            
    # Extract Year Range
    ano_in_det = 2022
    ano_fi_det = 2022
    match_range = re.search(r'\b(20\d{2}|19\d{2})\s*(?:a|e|até|-)\s*(20\d{2}|19\d{2})\b', pergunta_clean)
    if match_range:
        ano_in_det = int(match_range.group(1))
        ano_fi_det = int(match_range.group(2))
        if ano_in_det > ano_fi_det:
            ano_in_det, ano_fi_det = ano_fi_det, ano_in_det
    else:
        match_ano = re.search(r'\b(20\d{2}|19\d{2})\b', pergunta_clean)
        if match_ano:
            ano_in_det = int(match_ano.group(1))
            ano_fi_det = ano_in_det
            
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
        Período: <b>{ano_in_det} a {ano_fi_det}</b> | 
        Mês: <b>{mes_detectado if mes_detectado else 'Anual'}</b>
    </div>
    """, unsafe_allow_html=True)
    
    col_btn, _ = st.columns([1, 4])
    with col_btn:
        btn_buscar = st.button("🚀 Buscar no DATASUS", width="stretch")
        
    if btn_buscar:
        with st.spinner("Buscando dados (lendo do cache local ou conectando ao FTP do DATASUS)..."):
            try:
                df_raw = buscar_dados(pergunta_usuario)
                st.session_state['df_raw'] = df_raw
                st.session_state['search_info'] = (sistema_detectado, uf_detectada, ano_in_det, ano_fi_det, mes_detectado)
                st.session_state['last_query'] = pergunta_usuario
            except Exception as e:
                st.error(f"Erro ao buscar os dados: {e}")

else:
    # Manual mode search triggers
    st.markdown("### 🎛️ Buscar com os Filtros da Barra Lateral")
    st.info(f"Filtros selecionados: {sistema_selecionado.upper()} ({sigla_selecionada}) para {uf_selecionada} no período {ano_inicio_sel} a {ano_fim_sel} " + (f"mês {mes_selecionado}" if mes_selecionado else ""))
    
    col_btn, _ = st.columns([1, 4])
    with col_btn:
        btn_buscar_manual = st.button("🚀 Buscar no DATASUS", width="stretch")
        
    if btn_buscar_manual:
        with st.spinner("Buscando dados (lendo do cache local ou baixando do FTP)..."):
            try:
                df_raw = baixar_periodo_datasus(sistema_selecionado, sigla_selecionada, uf_selecionada, ano_inicio_sel, ano_fim_sel, mes_selecionado)
                st.session_state['df_raw'] = df_raw
                st.session_state['search_info'] = (sistema_selecionado, uf_selecionada, ano_inicio_sel, ano_fim_sel, mes_selecionado)
                st.session_state['last_query_manual'] = (sistema_selecionado, uf_selecionada, ano_inicio_sel, ano_fim_sel, mes_selecionado)
            except Exception as e:
                st.error(f"Erro ao buscar os dados: {e}")

# Retrieve from session state if search completed
if 'df_raw' in st.session_state:
    df_raw = st.session_state['df_raw']
    sistema_final, uf_final, ano_inicio_final, ano_fim_final, mes_final = st.session_state['search_info']
    
    # Check if current input is out-of-sync with the loaded data
    if metodo_busca == "💡 Linguagem Natural (Recomendado)":
        if 'last_query' in st.session_state and st.session_state['last_query'] != pergunta_usuario:
            st.warning("⚠️ **Você alterou a pergunta!** Os gráficos e dados exibidos abaixo ainda são da pesquisa anterior. Clique no botão **'🚀 Buscar no DATASUS'** acima para pesquisar e atualizar os dados.")
    else:
        current_manual = (sistema_selecionado, uf_selecionada, ano_inicio_sel, ano_fim_sel, mes_selecionado)
        if 'last_query_manual' in st.session_state and st.session_state['last_query_manual'] != current_manual:
            st.warning("⚠️ **Você alterou os filtros manuais!** Os gráficos e dados exibidos abaixo ainda são da pesquisa anterior. Clique no botão **'🚀 Buscar no DATASUS'** na tela para atualizar.")

# Display results if dataset is loaded
if df_raw is not None:
    st.markdown("---")
    
    # Check cache vs download status
    cache_count = df_raw.attrs.get('cache_count', 0)
    download_count = df_raw.attrs.get('download_count', 0)
    
    if download_count == 0 and cache_count > 0:
        st.success(f"⚡ **Dados carregados instantaneamente do cache local (Parquet)!** Total bruto: **{len(df_raw):,}** registros.")
    elif download_count > 0 and cache_count == 0:
        st.success(f"📥 **Dados baixados com sucesso do FTP do DATASUS e salvos no cache local!** Total bruto: **{len(df_raw):,}** registros.")
    elif download_count > 0 and cache_count > 0:
        st.success(f"🎉 **Dados carregados!** ({cache_count} arquivos lidos do cache local, {download_count} baixados do FTP). Total bruto: **{len(df_raw):,}** registros.")
    else:
        # Fallback if cache attrs are empty
        st.success(f"🎉 **Dados originais carregados na memória!** Total bruto: **{len(df_raw):,}** registros.")
    
    # ------------------ DYNAMIC FILTERING INTERFACE ------------------
    st.markdown("### 🎛️ Painel de Filtros Acadêmicos (Idade, Município e CID-10)")
    
    # Detect relevant columns
    idade_col = None
    if 'Idade da Mãe' in df_raw.columns:
        idade_col = 'Idade da Mãe'
    elif 'Idade (Anos)' in df_raw.columns:
        idade_col = 'Idade (Anos)'
        
    mun_col = None
    for c in ['CODMUNRES', 'CODMUNNASC', 'CODMUNOCOR', 'MUNIC_RES', 'MUNIC_OP']:
        if c in df_raw.columns:
            mun_col = c
            break
            
    cid_col = None
    for c in ['CAUSABAS', 'DIAG_PRINC', 'AP_CIDPRI']:
        if c in df_raw.columns:
            cid_col = c
            break
            
    col_filt_1, col_filt_2, col_filt_3 = st.columns(3)
    df_filtered = df_raw.copy()
    
    # 1. Age Filtering logic
    with col_filt_1:
        if idade_col:
            df_filtered[idade_col] = pd.to_numeric(df_filtered[idade_col], errors='coerce')
            min_val = int(df_filtered[idade_col].dropna().min()) if df_filtered[idade_col].dropna().any() else 0
            max_val = int(df_filtered[idade_col].dropna().max()) if df_filtered[idade_col].dropna().any() else 100
            
            # Prevent slider crash if values are equal
            if min_val >= max_val:
                min_val = 0
                max_val = 100
                
            idade_range = st.slider(
                f"Filtrar por Faixa Etária ({idade_col}):",
                min_value=0,
                max_value=120,
                value=(max(min_val, 0), min(max_val, 110)),
                help="Filtra a base removendo registros fora da faixa etária escolhida."
            )
            df_filtered = df_filtered[(df_filtered[idade_col] >= idade_range[0]) & (df_filtered[idade_col] <= idade_range[1])]
        else:
            st.info("ℹ️ Nenhuma coluna de idade encontrada neste sistema para filtragem automática.")

    # 2. Municipality Filtering logic
    with col_filt_2:
        if 'Município' in df_raw.columns:
            # Get unique values of decoded municipality names
            mun_names = sorted(df_raw['Município'].dropna().astype(str).unique().tolist())
            mun_selecionados = st.multiselect(
                "Filtrar por Município:",
                options=mun_names,
                default=[],
                help="Selecione um ou mais municípios para filtrar os dados. Deixe vazio para analisar todos."
            )
            if mun_selecionados:
                df_filtered = df_filtered[df_filtered['Município'].astype(str).isin(mun_selecionados)]
        else:
            st.info("ℹ️ Nenhuma coluna de município encontrada neste sistema para filtragem.")
            
    # 3. CID-10 Filtering logic
    with col_filt_3:
        if cid_col:
            cid_input = st.text_input(
                f"Filtrar por CID-10 ({cid_col}):",
                value=cid_manual_input,
                help="Digite códigos (Ex: M80), lista (Ex: M80, M81, M82) ou faixa de CIDs (Ex: M80-M85 ou M80 a M85)."
            )
            if cid_input:
                df_filtered = filtrar_cids(df_filtered, cid_col, cid_input)
        else:
            st.info("ℹ️ Nenhuma coluna de CID-10 encontrada para filtragem de diagnóstico/causa.")
            
    # ------------------ MAIN METRICS ------------------
    st.markdown("---")
    col_m1, col_m2, col_m3 = st.columns(3)
    with col_m1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Registros Filtrados / Total</div>
            <div class="metric-value">{len(df_filtered):,} / {len(df_raw):,}</div>
        </div>
        """, unsafe_allow_html=True)
    with col_m2:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Variáveis Disponíveis</div>
            <div class="metric-value">{df_filtered.shape[1]}</div>
        </div>
        """, unsafe_allow_html=True)
    with col_m3:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-title">Período de Referência</div>
            <div class="metric-value">{ano_inicio_final} - {ano_fim_final} ({uf_final})</div>
        </div>
        """, unsafe_allow_html=True)
        
# Tabs for navigation (Preview, Visualization, Cross-tabulation, CID-10 Dictionary, Gemini Chat, Export)
tab_dados, tab_graficos, tab_cruzamento, tab_cid10, tab_chat, tab_exportar = st.tabs([
    "📊 Tabela de Dados", 
    "📈 Análises Gráficas", 
    "🔗 Cruzamento de Variáveis (Tabela Cruzada)",
    "📖 Dicionário CID-10",
    "💬 Chat IA (Gemini)",
    "💾 Exportar Base"
])

with tab_dados:
    if df_raw is not None:
        st.markdown("#### 🔍 Visualização dos Dados Filtrados")
        st.write("Ordene, pesquise ou inspecione a tabela de dados tratada com nomes legíveis abaixo:")
        st.dataframe(df_filtered.head(200), width="stretch")
        st.caption("Exibindo as primeiras 200 linhas da tabela filtrada para desempenho rápido no navegador.")
    else:
        st.info("💡 Por favor, faça uma busca acima para carregar os dados do DATASUS e visualizar a tabela de dados!")
        
with tab_graficos:
    if df_raw is not None:
        st.markdown("#### 📊 Análises Gráficas Científicas")
        
        # 1. Custom graphs based on the loaded system
        if 'Idade da Mãe' in df_filtered.columns:
            st.info("💡 Detectado conjunto de dados de NASCIMENTOS (SINASC).")
            col_g1, col_g2 = st.columns(2)
            with col_g1:
                st.markdown("##### Distribuição de Idades das Mães")
                fig, ax = plt.subplots(figsize=(8, 4.5))
                sns.histplot(data=df_filtered, x='Idade da Mãe', kde=True, color='teal', bins=20, ax=ax)
                ax.set_title("Idade das Mães no Nascimento", fontweight='bold')
                ax.set_xlabel("Idade da Mãe (Anos)")
                ax.set_ylabel("Casos")
                st.pyplot(fig)
                
            with col_g2:
                st.markdown("##### Proporção por Tipo de Parto")
                if 'Tipo de Parto' in df_filtered.columns:
                    fig, ax = plt.subplots(figsize=(8, 4.5))
                    sns.countplot(data=df_filtered, x='Tipo de Parto', palette='Set2', hue='Tipo de Parto', legend=False, ax=ax)
                    ax.set_title("Proporção por Tipo de Parto", fontweight='bold')
                    ax.set_xlabel("Tipo de Parto")
                    ax.set_ylabel("Quantidade")
                    adicionar_rotulos(ax)
                    st.pyplot(fig)
                    
        elif 'CAUSABAS' in df_filtered.columns:
            st.info("💡 Detectado conjunto de dados de MORTALIDADE (SIM).")
            col_g1, col_g2 = st.columns(2)
            with col_g1:
                st.markdown("##### Top 10 Causas de Óbitos (CID-10)")
                target_col = 'Diagnóstico/Causa' if 'Diagnóstico/Causa' in df_filtered.columns else 'CAUSABAS'
                top10_morte = df_filtered[target_col].value_counts().head(10).reset_index()
                top10_morte.columns = [target_col, 'Óbitos']
                
                st.bar_chart(
                    data=top10_morte,
                    x='Óbitos',
                    y=target_col,
                    color=target_col,
                    width="stretch"
                )
                
            with col_g2:
                st.markdown("##### Distribuição de Óbitos por Sexo")
                if 'Sexo' in df_filtered.columns:
                    fig, ax = plt.subplots(figsize=(8, 4.5))
                    sns.countplot(data=df_filtered, x='Sexo', palette='coolwarm', hue='Sexo', legend=False, ax=ax)
                    ax.set_title("Óbitos Organizados por Sexo", fontweight='bold')
                    ax.set_xlabel("Sexo")
                    ax.set_ylabel("Óbitos")
                    adicionar_rotulos(ax)
                    st.pyplot(fig)
                    
        elif 'DIAG_PRINC' in df_filtered.columns:
            st.info("💡 Detectado conjunto de dados de INTERNAÇÕES HOSPITALARES (SIHSUS).")
            st.markdown("##### Top 10 Diagnósticos Principais de Internação (CIDs)")
            target_col = 'Diagnóstico/Causa' if 'Diagnóstico/Causa' in df_filtered.columns else 'DIAG_PRINC'
            top_internacoes = df_filtered[target_col].value_counts().head(10).reset_index()
            top_internacoes.columns = [target_col, 'Internações']
            
            st.bar_chart(
                data=top_internacoes,
                x='Internações',
                y=target_col,
                color=target_col,
                width="stretch"
            )
            
        # 2. General graphs by Municipality and Age
        st.markdown("---")
        st.markdown("#### 📍 Análises Adicionais por Município e Idade")
        
        col_ad_1, col_ad_2 = st.columns(2)
        
        with col_ad_1:
            if 'Município' in df_filtered.columns:
                st.markdown("##### Top 10 Municípios com Mais Casos")
                top_muns = df_filtered['Município'].value_counts().head(10).reset_index()
                top_muns.columns = ['Município', 'Ocorrências']
                
                st.bar_chart(
                    data=top_muns,
                    x='Ocorrências',
                    y='Município',
                    color='Município',
                    width="stretch"
                )
            else:
                st.info("ℹ️ Sem dados de município para plotagem geográfica.")
                
        with col_ad_2:
            if idade_col:
                st.markdown("##### Distribuição por Faixas Etárias")
                # Group age into custom brackets
                def agrupar_idade(idade):
                    try:
                        idade = float(idade)
                        if pd.isna(idade) or idade < 0:
                            return 'Não Informado'
                        if idade < 1:
                            return 'Menor de 1 ano'
                        elif idade <= 12:
                            return '1 a 12 anos'
                        elif idade <= 19:
                            return '13 a 19 anos (Adolescente)'
                        elif idade <= 34:
                            return '20 a 34 anos'
                        elif idade <= 59:
                            return '35 a 59 anos'
                        else:
                            return '60 anos ou mais'
                    except:
                        return 'Não Informado'
                        
                df_filtered['Faixa Etária'] = df_filtered[idade_col].apply(agrupar_idade)
                faixa_ordem = ['Menor de 1 ano', '1 a 12 anos', '13 a 19 anos (Adolescente)', '20 a 34 anos', '35 a 59 anos', '60 anos ou mais', 'Não Informado']
                
                faixas_contagem = df_filtered['Faixa Etária'].value_counts().reindex(faixa_ordem).dropna()
                
                if not faixas_contagem.empty and faixas_contagem.sum() > 0:
                    df_age_chart = pd.DataFrame({
                        'Faixa Etária': faixas_contagem.index,
                        'Casos': faixas_contagem.values
                    })
                    st.bar_chart(
                        data=df_age_chart,
                        x='Casos',
                        y='Faixa Etária',
                        color='Faixa Etária',
                        width="stretch"
                    )
                else:
                    st.warning("Sem dados numéricos de idade válidos para faixas etárias.")
            else:
                st.info("ℹ️ Sem dados de idade para plotagem por faixas etárias.")
    else:
        st.info("💡 Por favor, faça uma busca acima para carregar os dados do DATASUS e visualizar as análises gráficas!")

with tab_cruzamento:
    if df_raw is not None:
        st.markdown("#### 🔗 Cruzamento de Variáveis Demográficas e Clínicas")
        st.write("Selecione duas variáveis para cruzar os dados. O sistema irá gerar tabelas de contingência absolutas e percentuais, além de gráficos empilhados.")
        
        # Categorical columns list generated in decodificar_dados
        colunas_cruzamento = [c for c in [
            'Sexo', 'Tipo de Parto', 'Raça/Cor', 'Escolaridade da Mãe', 
            'Estado Civil da Mãe', 'Local da Ocorrência', 'ANO_DATA', 'Município', 'Diagnóstico/Causa'
        ] if c in df_filtered.columns]
        
        if len(colunas_cruzamento) >= 2:
            col_cr_1, col_cr_2 = st.columns(2)
            with col_cr_1:
                var_linha = st.selectbox("Variável nas Linhas (Grupo Comparativo):", colunas_cruzamento, index=0)
            with col_cr_2:
                # Exclude the selected row variable from columns dropdown
                colunas_col_opcoes = [c for c in colunas_cruzamento if c != var_linha]
                var_coluna = st.selectbox("Variável nas Colunas (Desfecho):", colunas_col_opcoes, index=0)
                
            st.markdown("##### 1. Tabela Cruzada de Frequência Absoluta (Contagem de Casos)")
            crosstab_abs = pd.crosstab(df_filtered[var_linha], df_filtered[var_coluna], margins=True, margins_name="Total")
            st.dataframe(crosstab_abs, width="stretch")
            
            st.markdown("##### 2. Tabela Cruzada de Proporção Relativa (Porcentagem por Linha)")
            st.write("Ideal para comparar proporções. Exibe a distribuição percentual do desfecho dentro de cada grupo comparativo.")
            crosstab_pct = pd.crosstab(df_filtered[var_linha], df_filtered[var_coluna], normalize='index') * 100
            # Format percentage display
            crosstab_pct_formatted = crosstab_pct.style.format("{:.2f}%")
            st.dataframe(crosstab_pct_formatted, width="stretch")
            
            if not crosstab_pct.empty and crosstab_pct.shape[0] > 0 and crosstab_pct.shape[1] > 0:
                st.markdown("##### 3. Gráfico de Barras Empilhadas de Proporção")
                fig, ax = plt.subplots(figsize=(10, 5))
                crosstab_pct.plot(kind='bar', stacked=True, colormap='viridis', ax=ax)
                ax.set_title(f"Distribuição Relativa de '{var_coluna}' por '{var_linha}'", fontweight='bold', fontsize=12)
                ax.set_ylabel("Proporção (%)")
                ax.set_xlabel(var_linha)
                plt.xticks(rotation=45, ha='right')
                plt.legend(title=var_coluna, bbox_to_anchor=(1.05, 1), loc='upper left')
                
                # Adiciona rótulos de porcentagem dentro das barras empilhadas
                if ax.containers:
                    for c in ax.containers:
                        labels = [f'{x:.1f}%' if x > 2 else '' for x in c.datavalues]
                        ax.bar_label(c, labels=labels, label_type='center', fontsize=8)
                        
                plt.tight_layout()
                st.pyplot(fig)
            else:
                st.warning("⚠️ **Sem dados suficientes para gerar o gráfico cruzado.** Verifique se os filtros aplicados não esvaziaram a base de dados.")
    else:
        st.info("💡 Por favor, faça uma busca acima para carregar os dados do DATASUS e realizar cruzamento de variáveis!")

with tab_cid10:
    if True:
        st.markdown("#### 📖 Navegador e Dicionário de CIDs (CID-10)")
        st.write("Consulte os códigos e descrições oficiais da Classificação Internacional de Doenças (CID-10) em português.")
        
        # Load CID-10 dictionary
        from datasus_core import carregar_cid10_dict
        cid_dict = carregar_cid10_dict()
        
        if cid_dict:
            # Reconstruct list of codes (filtering out duplicates without dots)
            cid_list = []
            for code, name in cid_dict.items():
                if '.' in code or len(code) == 3:
                    cid_list.append({'Código': code, 'Descrição': name})
            
            df_cid = pd.DataFrame(cid_list).drop_duplicates().sort_values('Código')
            
            # Search inputs
            col_search_1, col_search_2 = st.columns([2, 1])
            with col_search_1:
                busca_cid = st.text_input(
                    "Digite um Código ou Termo Clínico (Ex: M80, Osteoporose, Fratura):",
                    value="M80",
                    help="Digite para pesquisar. Ex: 'M80' retornará a categoria de osteoporose com fratura e todas as suas etiologias (M80.0 a M80.9)."
                )
            with col_search_2:
                tipo_filtro = st.selectbox(
                    "Buscar em:",
                    ["Ambos (Código ou Descrição)", "Apenas Código", "Apenas Descrição"]
                )
                
            if busca_cid:
                busca_clean = busca_cid.lower().strip()
                
                # Apply filter based on selected type
                if tipo_filtro == "Apenas Código":
                    df_result = df_cid[df_cid['Código'].str.lower().str.contains(busca_clean)]
                elif tipo_filtro == "Apenas Descrição":
                    df_result = df_cid[df_cid['Descrição'].str.lower().str.contains(busca_clean)]
                else:
                    df_result = df_cid[
                        df_cid['Código'].str.lower().str.contains(busca_clean) | 
                        df_cid['Descrição'].str.lower().str.contains(busca_clean)
                    ]
                    
                st.markdown(f"Encontrados **{len(df_result)}** códigos correspondentes na CID-10:")
                st.dataframe(df_result, width="stretch", hide_index=True)
                
                # Display structural explanation specifically for M80 if search contains M80
                if 'm80' in busca_clean:
                    st.markdown("""
                    > 💡 **Estrutura de Osteoporose com Fratura Patológica (M80):**
                    > *   **M80.0**: Osteoporose pós-menopausa com fratura patológica
                    > *   **M80.1**: Osteoporose pós-ooforectomia com fratura patológica
                    > *   **M80.2**: Osteoporose de desuso com fratura patológica
                    > *   **M80.3**: Osteoporose por má-absorção pós-cirúrgica com fratura patológica
                    > *   **M80.4**: Osteoporose induzida por drogas com fratura patológica
                    > *   **M80.5**: Osteoporose idiopática com fratura patológica
                    > *   **M80.8**: Outra osteoporose com fratura patológica
                    > *   **M80.9**: Osteoporose com fratura patológica, não especificada
                    """)
        else:
            st.warning("⚠️ Não foi possível carregar a base de dados da CID-10.")

with tab_chat:
    if True:
        st.markdown("#### 💬 Chat Inteligente IA (Gemini)")
        st.write("Faça perguntas sobre os dados carregados em linguagem natural. A IA escreverá o código de consulta apropriado e trará as respostas estruturadas.")
        
        # 1. API Key Setup
        gemini_api_key = st.text_input(
            "Chave API do Gemini (obtenha em aistudio.google.com):",
            value=os.environ.get("GEMINI_API_KEY", ""),
            type="password",
            help="Sua chave não é salva no servidor, ela permanece segura apenas em memória durante a sessão."
        )
        
        if not gemini_api_key:
            st.info("🔑 Por favor, insira sua **Chave API do Gemini** no campo acima para começar a conversar com os dados.")
        else:
            # Save manually entered key to environment for global use
            os.environ["GEMINI_API_KEY"] = gemini_api_key
            # Configure API
            from google import genai
            client = genai.Client(api_key=gemini_api_key)
            
            # Initialize chat history in session state
            if 'chat_messages' not in st.session_state:
                st.session_state['chat_messages'] = []
                
            # Display chat messages
            for msg in st.session_state['chat_messages']:
                with st.chat_message(msg['role']):
                    st.markdown(msg['content'])
                    if 'code' in msg and msg['code']:
                        with st.expander("🛠️ Código Executado"):
                            st.code(msg['code'], language="python")
                            st.code(f"Resultado: {msg['result']}", language="text")
                            
            # Accept user input (always visible once key is entered)
            if prompt_user := st.chat_input("Pergunte algo sobre os dados ou tire dúvidas gerais sobre o DATASUS:"):
                # Display user message
                with st.chat_message("user"):
                    st.markdown(prompt_user)
                st.session_state['chat_messages'].append({'role': 'user', 'content': prompt_user})
                
                # Generate response
                with st.chat_message("assistant"):
                    status_placeholder = st.empty()
                    
                    # 1. Classify if the user wants to download/load a new dataset
                    status_placeholder.markdown("🔍 *Analisando sua intenção...*")
                    is_load_request = False
                    intent_params = {}
                    
                    try:
                        from google.genai import types
                        import json
                        
                        system_prompt_intent = f"""
Você é um classificador de intenções para o assistente DATASUS.
Determine se o usuário está pedindo para baixar, pesquisar ou carregar uma base de dados nova (ex: "busque...", "baixe...", "pesquise...", "quero ver dados de...", "analise os nascimentos de...", "carregue óbitos de...").

Sistemas disponíveis:
- 'sinasc': Nascimentos/partos (DN)
- 'sim': Óbitos/mortalidade/mortes/falecimentos (DO)
- 'sih': Internações hospitalares/AIH (RD)
- 'sia': Produção ambulatorial/consultas (PA)
- 'cnes': Estabelecimentos/leitos de saúde (LT)

Regra de Cidades/UFs:
Mapeie o local mencionado para a sigla do estado em maiúsculo (ex: "Salvador" -> "BA"). Se for todo o Brasil/nacional, use "BR". Padrão: "SP" se não especificado.

Retorne APENAS um objeto JSON com as chaves:
- "is_load_request": boolean (true se o usuário estiver pedindo para carregar/baixar/pesquisar um novo período/estado/sistema. false se for apenas uma pergunta analítica sobre a base que já está carregada, ou uma pergunta teórica geral).
- "sistema": string ou null (um dos 5 sistemas acima)
- "uf": string ou null (sigla da UF ou "BR")
- "ano_inicio": número inteiro ou null
- "ano_fim": número inteiro ou null
- "mes": número inteiro (1 a 12) ou null

Pergunta do usuário: "{prompt_user}"
Ano de referência atual: 2026.
"""
                        res_intent = client.models.generate_content(
                            model="gemini-2.5-flash",
                            contents=system_prompt_intent,
                            config=types.GenerateContentConfig(
                                response_mime_type="application/json",
                            )
                        )
                        intent_params = json.loads(res_intent.text.strip())
                        is_load_request = intent_params.get("is_load_request", False)
                    except Exception as intent_err:
                        print(f"[Chat Intent Error] {intent_err}")
                        is_load_request = False
                        
                    if is_load_request:
                        # ---------------- CONVERSATIONAL DATA LOAD MODE ----------------
                        sistema = (intent_params.get('sistema') or 'sim').lower()
                        uf = (intent_params.get('uf') or 'SP').upper()
                        ano_inicio = intent_params.get('ano_inicio') or 2022
                        ano_fim = intent_params.get('ano_fim') or 2022
                        mes = intent_params.get('mes')
                        
                        status_placeholder.markdown(f"📥 *Intenção de busca detectada! Baixando dados para: {sistema.upper()} | UF: {uf} | Período: {ano_inicio}-{ano_fim}...*")
                        try:
                            sistemas_siglas = {
                                'sinasc': 'DN', 'sim': 'DO', 'sih': 'RD', 'sia': 'PA', 'cnes': 'LT'
                            }
                            sigla_arquivo = sistemas_siglas.get(sistema, 'DO')
                            
                            df_raw = baixar_periodo_datasus(sistema, sigla_arquivo, uf, ano_inicio, ano_fim, mes)
                            
                            st.session_state['df_raw'] = df_raw
                            st.session_state['search_info'] = (sistema, uf, ano_inicio, ano_fim, mes)
                            st.session_state['last_query'] = prompt_user
                            st.session_state['last_query_manual'] = (sistema, uf, ano_inicio, ano_fim, mes)
                            
                            cache_count = df_raw.attrs.get('cache_count', 0)
                            download_count = df_raw.attrs.get('download_count', 0)
                            
                            source_msg = "⚡ (carregado do cache local)" if download_count == 0 else "📥 (baixado do FTP do DATASUS)"
                            success_msg = f"⚡ **Base de dados carregada com sucesso diretamente pelo chat!**\n\n*   **Sistema**: {sistema.upper()}\n*   **UF**: {uf}\n*   **Período**: {ano_inicio} a {ano_fim}\n*   **Registros**: {len(df_raw):,}\n*   **Origem**: {source_msg}\n\nO painel de filtros e os gráficos já foram atualizados com essa nova base de dados!"
                            
                            status_placeholder.markdown(success_msg)
                            st.session_state['chat_messages'].append({'role': 'assistant', 'content': success_msg})
                            st.rerun()
                        except Exception as dl_err:
                            err_msg = f"❌ Erro ao baixar dados solicitados pelo chat: {dl_err}"
                            status_placeholder.markdown(err_msg)
                            st.session_state['chat_messages'].append({'role': 'assistant', 'content': err_msg})
                            
                    elif df_raw is not None:
                        # ---------------- DATA ANALYST MODE (Data is loaded) ----------------
                        status_placeholder.markdown("🤔 *Analisando estrutura dos dados e preparando query...*")
                        try:
                            # Prepare data context
                            cols_info = list(df_filtered.columns)
                            dtypes_info = {k: str(v) for k, v in df_filtered.dtypes.items()}
                            sample_info = df_filtered.head(3).to_dict(orient='records')
                            
                            system_prompt_code = f"""
Você é um assistente especialista em análise de dados do DATASUS.
Você tem acesso a um DataFrame do Pandas chamado `df` que contém os dados atualmente selecionados pelo usuário.
O DataFrame possui {len(df_filtered)} linhas e as seguintes colunas:
Colunas: {cols_info}
Tipos de dados: {dtypes_info}
Amostra (3 linhas): {sample_info}

Escreva um código Python seguro usando Pandas para responder à pergunta do usuário: '{prompt_user}'.
O seu código DEVE obrigatoriamente definir uma variável chamada `resposta` contendo o resultado da análise (ex: texto formatado, DataFrame pequeno, número, tabela Markdown, etc.).
REGRAS:
1. Retorne APENAS o código Python puro dentro de um bloco de código markdown (iniciando com ```python e terminando com ```).
2. Não escreva nenhuma introdução ou explicação fora do bloco de código.
3. Não use comandos perigosos. Use apenas agregações, contagens, ordenações e filtros do Pandas.
4. Trate valores nulos ou vazios de forma amigável no código.
"""
                            res_code = client.models.generate_content(
                                model="gemini-2.5-flash",
                                contents=system_prompt_code
                            )
                            code_text = res_code.text
                            
                            # Extract python code block
                            code_match = re.search(r'```python\s*(.*?)\s*```', code_text, re.DOTALL)
                            if code_match:
                                code_to_run = code_match.group(1)
                            else:
                                code_to_run = code_text.strip()
                                if code_to_run.startswith("python"):
                                    code_to_run = code_to_run[6:]
                                    
                            status_placeholder.markdown("⚙️ *Executando query nos dados locais...*")
                            local_vars = {'df': df_filtered, 'pd': pd}
                            try:
                                exec(code_to_run, {}, local_vars)
                                res_exec = local_vars.get('resposta', 'O código foi executado com sucesso, mas a variável "resposta" não foi definida.')
                            except Exception as exec_err:
                                res_exec = f"Erro ao executar o código gerado: {exec_err}"
                                
                            status_placeholder.markdown("✍️ *Interpretando resultados e formulando resposta...*")
                            
                            final_prompt = f"""
O usuário perguntou sobre a base do DATASUS: '{prompt_user}'
Para responder, nós rodamos o seguinte código Pandas no DataFrame `df`:
```python
{code_to_run}
```
O resultado obtido foi:
{res_exec}

Com base nisso, formule a resposta final para o usuário de forma amigável, clara e concisa em português do Brasil.
Escreva a resposta em formato Markdown. Se houver tabelas ou listas, formate-as de forma bonita.
"""
                            res_final = client.models.generate_content(
                                model="gemini-2.5-flash",
                                contents=final_prompt
                            )
                            final_text = res_final.text
                            
                            status_placeholder.markdown(final_text)
                            
                            with st.expander("🛠️ Código Executado"):
                                st.code(code_to_run, language="python")
                                st.code(f"Resultado bruto: {res_exec}", language="text")
                                
                            st.session_state['chat_messages'].append({
                                'role': 'assistant',
                                'content': final_text,
                                'code': code_to_run,
                                'result': str(res_exec)
                            })
                        except Exception as err:
                            err_msg = f"❌ Ocorreu um erro: {err}"
                            status_placeholder.markdown(err_msg)
                            st.session_state['chat_messages'].append({'role': 'assistant', 'content': err_msg})
                    else:
                        # ---------------- GENERAL ASSISTANT MODE (No data loaded) ----------------
                        status_placeholder.markdown("🤔 *Consultando Gemini...*")
                        try:
                            system_prompt_general = f"""
Você é um assistente científico do DATASUS.
Atualmente, nenhuma base de dados do DATASUS foi carregada na memória pelo usuário.
Responda à pergunta do usuário: '{prompt_user}'.
Se ele fizer perguntas que dependam de análise de dados específicos (como contagem de casos, médias, gráficos das bases), explique amigavelmente que ele precisa primeiro fazer uma busca na barra superior ou lateral do site para baixar os dados na memória.
Se for uma dúvida geral teórica sobre saúde, sobre a CID-10, ou sobre o funcionamento do DATASUS (SIM, SIH, SINASC, etc.), responda de forma prestativa, clara e objetiva em português do Brasil usando Markdown.
"""
                            res_general = client.models.generate_content(
                                model="gemini-2.5-flash",
                                contents=system_prompt_general
                            )
                            final_text = res_general.text
                            status_placeholder.markdown(final_text)
                            st.session_state['chat_messages'].append({'role': 'assistant', 'content': final_text})
                        except Exception as api_err:
                            err_msg = f"❌ Ocorreu um erro ao conectar com o Gemini: {api_err}"
                            status_placeholder.markdown(err_msg)
                            st.session_state['chat_messages'].append({'role': 'assistant', 'content': err_msg})

with tab_exportar:
    if df_raw is not None:
        st.markdown("#### 💾 Exportar e Salvar Base Tratada")
        st.write("Faça o download do arquivo CSV completo. Os dados já contêm todas as decodificações de texto e os filtros selecionados acima.")
        
        # Memory buffer to avoid writing file on host disk again (keeps it fast)
        csv_buffer = io.BytesIO()
        df_filtered.to_csv(csv_buffer, index=False, encoding='utf-8-sig')
        csv_buffer.seek(0)
        
        nome_arquivo_export = f"datasus_{sistema_final}_{uf_final}_{ano_inicio_final}_a_{ano_fim_final}.csv"
        
        st.download_button(
            label="📥 Baixar Base Filtrada em CSV (Excel)",
            data=csv_buffer,
            file_name=nome_arquivo_export,
            mime="text/csv",
            width="stretch"
        )
        st.success(f"Arquivo de exportação gerado: `{nome_arquivo_export}`")
    else:
        st.info("💡 Por favor, faça uma busca acima para carregar os dados do DATASUS e exportar a base tratada!")

# Footer
st.markdown("""
<div class="footer-text">
    Desenvolvido com ❤️ para Pesquisadores Científicos no Brasil. 🇧🇷🏥<br>
    Dados obtidos diretamente do servidor FTP do DATASUS - Ministério da Saúde.
</div>
""", unsafe_allow_html=True)

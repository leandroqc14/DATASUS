import os
import re
import ftplib
import tempfile
import json
import urllib.request
import pandas as pd
from dbctodbf import DBCDecompress
from dbfread import DBF
from tqdm import tqdm

# Local directory for caching downloaded files in Parquet format
CACHE_DIR = os.path.join(os.getcwd(), 'datasus_cache')
os.makedirs(CACHE_DIR, exist_ok=True)

def carregar_municipios_dict():
    """
    Downloads the list of all Brazilian municipalities from the official IBGE API,
    maps 6-digit codes to names (e.g. '355030' -> 'São Paulo (SP)'), and caches it in a JSON file.
    """
    caminho_json = os.path.join(CACHE_DIR, 'municipios.json')
    
    # If cache file exists, read it
    if os.path.exists(caminho_json):
        try:
            with open(caminho_json, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[Aviso] Erro ao ler cache de municípios: {e}. Recriando...")
            
    # If not in cache, download from IBGE API
    url = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"
    print("[IBGE] Baixando lista de municipios da API do IBGE...")
    try:
        import requests
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        res.raise_for_status()
        data = res.json()
        
        mapping = {}
        for item in data:
            id_7 = str(item['id'])
            id_6 = id_7[:6] # DATASUS uses 6-digit codes (excluding the 7th verification digit)
            nome = item['nome']
            
            # Safe traversal for UF
            uf = "??"
            try:
                if item.get('microrregiao') and item['microrregiao'].get('mesorregiao') and item['microrregiao']['mesorregiao'].get('UF'):
                    uf = item['microrregiao']['mesorregiao']['UF']['sigla']
                elif item.get('regiao-imediata') and item['regiao-imediata'].get('regiao-intermediaria') and item['regiao-imediata']['regiao-intermediaria'].get('UF'):
                    uf = item['regiao-imediata']['regiao-intermediaria']['UF']['sigla']
            except:
                pass
                
            mapping[id_6] = f"{nome} ({uf})"
            
        # Save to local cache
        with open(caminho_json, 'w', encoding='utf-8') as f:
            json.dump(mapping, f, ensure_ascii=False, indent=1)
            
        print(f"[IBGE] Sucesso ao cachear {len(mapping)} municipios localmente.")
        return mapping
    except Exception as e:
        print(f"[Aviso] Falha ao baixar lista de municipios do IBGE: {e}")
        return {}

def carregar_cid10_dict():
    """
    Downloads the official CID-10 database in Portuguese, maps codes (e.g. 'M80.0' and 'M800')
    to their text descriptions, and caches it in a JSON file.
    """
    caminho_json = os.path.join(CACHE_DIR, 'cid10.json')
    
    # If cache file exists, read it
    if os.path.exists(caminho_json):
        try:
            with open(caminho_json, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f"[Aviso] Erro ao ler cache da CID-10: {e}. Recriando...")
            
    # Download from reliable public raw github source
    url = "https://raw.githubusercontent.com/QualitasGit/static_data/master/cid10.json"
    print("[CID-10] Baixando banco de dados da CID-10...")
    try:
        import requests
        res = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        res.raise_for_status()
        data = res.json()
        
        mapping = {}
        for item in data:
            codigo_raw = item.get('codigo', '')
            nome = item.get('nome', '')
            if codigo_raw:
                codigo_clean = codigo_raw.replace('.', '').strip().upper()
                mapping[codigo_raw.upper()] = nome
                mapping[codigo_clean] = nome
                
        # Save to local cache
        with open(caminho_json, 'w', encoding='utf-8') as f:
            json.dump(mapping, f, ensure_ascii=False, indent=1)
            
        print(f"[CID-10] Sucesso ao cachear {len(mapping)} termos da CID-10.")
        return mapping
    except Exception as e:
        print(f"[Aviso] Falha ao obter banco da CID-10: {e}")
        return {}

def baixar_arquivo_datasus(sistema, sigla_arquivo, uf, ano, mes=None):
    """
    Downloads a single .dbc file from DATASUS FTP, decompresses it to .dbf,
    loads it into a Pandas DataFrame, and saves it as a Parquet file for caching.
    """
    uf = uf.upper()
    
    # Yearly databases (SIM, SINASC) use 4-digit years. Monthly databases (SIH, SIA, CNES) use 2-digit years.
    if sistema.lower() in ['sim', 'sinasc']:
        ano_str = str(ano)        # 4 digits (e.g. 2022)
    else:
        ano_str = str(ano)[-2:]   # 2 digits (e.g. 22)
        
    nome_base = f"{sigla_arquivo}{uf}{ano_str}"
    
    # Monthly systems require a month. If none provided, default to January (01).
    if sistema.lower() in ['sih', 'sia', 'cnes'] and not mes:
        mes = 1
        
    if mes:
        mes_str = f"{mes:02d}"
        nome_base = f"{sigla_arquivo}{uf}{ano_str}{mes_str}"
        
    nome_dbc = f"{nome_base}.dbc"
    nome_dbf = f"{nome_base}.dbf"
    nome_parquet = f"{nome_base}.parquet"
    
    caminho_parquet = os.path.join(CACHE_DIR, nome_parquet)
    
    # 1. Check if already in cache
    if os.path.exists(caminho_parquet):
        print(f"[Cache] Carregando do cache: {nome_parquet}")
        df = pd.read_parquet(caminho_parquet)
        df.attrs['from_cache'] = True
        return df
    
    # FTP directories mapping
    caminhos_ftp = {
        'sim': '/dissemin/publicos/SIM/CID10/DORES/',        # Mortality (General)
        'sinasc': '/dissemin/publicos/SINASC/NOV/DNRES/',     # Live Births
        'sih': '/dissemin/publicos/SIHSUS/200801_/Dados/',    # Hospitalizations
        'sia': '/dissemin/publicos/SIASUS/200801_/Dados/',    # Outpatient
        'cnes': '/dissemin/publicos/CNES/200508_/Dados/LT/'   # Facilities (Beds)
    }
    
    pasta_ftp = caminhos_ftp.get(sistema.lower())
    if not pasta_ftp:
        raise ValueError(f"Sistema '{sistema}' nao suportado. Escolha entre: {list(caminhos_ftp.keys())}")
        
    arquivo_alvo = nome_dbc.upper()
    
    print(f"[FTP] Conectando ao FTP do DATASUS (ftp.datasus.gov.br)...")
    temp_dir = tempfile.gettempdir()
    caminho_local_dbc = os.path.join(temp_dir, nome_dbc)
    caminho_local_dbf = os.path.join(temp_dir, nome_dbf)
    
    try:
        ftp = ftplib.FTP('ftp.datasus.gov.br')
        ftp.login()
        ftp.cwd(pasta_ftp)
        
        # Check files list (with case-insensitivity support)
        lista_arquivos = ftp.nlst()
        arquivo_encontrado = None
        for f in lista_arquivos:
            if f.upper() == arquivo_alvo:
                arquivo_encontrado = f
                break
                
        if not arquivo_encontrado:
            # Try lowercase variation
            for f in lista_arquivos:
                if f.lower() == arquivo_alvo.lower():
                    arquivo_encontrado = f
                    break
                    
        if not arquivo_encontrado:
            ftp.quit()
            raise FileNotFoundError(f"Arquivo {nome_dbc} nao encontrado no FTP na pasta: {pasta_ftp}")
            
        print(f"[FTP] Baixando {arquivo_encontrado}...")
        tamanho_total = ftp.size(arquivo_encontrado)
        
        with open(caminho_local_dbc, 'wb') as f_out, tqdm(
            total=tamanho_total, unit='B', unit_scale=True, desc=nome_dbc
        ) as pbar:
            def cb(data):
                f_out.write(data)
                pbar.update(len(data))
            ftp.retrbinary(f"RETR {arquivo_encontrado}", cb)
            
        ftp.quit()
        
        # 2. Decompress using pure-python library
        print(f"[Conversao] Descompactando arquivo .dbc...")
        decomp = DBCDecompress()
        decomp.decompressFile(caminho_local_dbc, caminho_local_dbf)
        
        # 3. Read DBF using dbfread
        print(f"[Pandas] Carregando arquivo DBF...")
        dbf = DBF(caminho_local_dbf, encoding='iso-8859-1')
        df = pd.DataFrame(iter(dbf))
        
        # Save to parquet cache
        df.to_parquet(caminho_parquet, index=False)
        df.attrs['from_cache'] = False
        print(f"[Sucesso] Processo concluido! Salvo no cache: {nome_parquet} ({len(df):,} linhas)")
        
        # Cleanup temp files
        if os.path.exists(caminho_local_dbc): os.remove(caminho_local_dbc)
        if os.path.exists(caminho_local_dbf): os.remove(caminho_local_dbf)
        
        return df
        
    except Exception as e:
        if os.path.exists(caminho_local_dbc): os.remove(caminho_local_dbc)
        if os.path.exists(caminho_local_dbf): os.remove(caminho_local_dbf)
        raise RuntimeError(f"Erro ao acessar dados do DATASUS: {e}")

def baixar_periodo_datasus(sistema, sigla_arquivo, uf, ano_inicio, ano_fim, mes=None):
    """
    Downloads and concatenates DATASUS data for a range of years [ano_inicio, ano_fim].
    Supports 'BR' to download and concatenate all 27 Brazilian states.
    """
    dfs = []
    anos_range = range(int(ano_inicio), int(ano_fim) + 1)
    
    ufs_para_baixar = [uf.upper()]
    if uf.upper() == 'BR':
        ufs_para_baixar = [
            'AC', 'AL', 'AP', 'AM', 'BA', 'CE', 'DF', 'ES', 'GO', 'MA', 
            'MT', 'MS', 'MG', 'PA', 'PB', 'PR', 'PE', 'PI', 'RJ', 'RN', 
            'RS', 'RO', 'RR', 'SC', 'SP', 'SE', 'TO'
        ]
        
    cache_count = 0
    download_count = 0
    
    for ano in anos_range:
        for estado in ufs_para_baixar:
            try:
                if len(ufs_para_baixar) > 1:
                    print(f"\n--- Processando Estado: {estado} | Ano: {ano} ---")
                else:
                    print(f"\n--- Processando Ano: {ano} ---")
                df_ano = baixar_arquivo_datasus(sistema, sigla_arquivo, estado, ano, mes)
                if df_ano is not None and not df_ano.empty:
                    # Track cache vs download
                    if df_ano.attrs.get('from_cache', False):
                        cache_count += 1
                    else:
                        download_count += 1
                    # Add a year column to identify the record year
                    df_ano['ANO_DATA'] = ano
                    # Add a state column
                    df_ano['UF'] = estado
                    dfs.append(df_ano)
            except Exception as e:
                print(f"[Aviso] Erro ao baixar dados de {estado} no ano {ano}: {e}. Pulando...")
            
    if not dfs:
        raise RuntimeError(f"Nenhum dado pôde ser baixado para o período {ano_inicio} a {ano_fim} na localidade {uf}.")
        
    # Concatenate all datasets
    print("\n[Pandas] Concatenando os dados...")
    df_final = pd.concat(dfs, ignore_index=True)
    
    # Store cache counts
    df_final.attrs['cache_count'] = cache_count
    df_final.attrs['download_count'] = download_count
    
    # Decodificar dados e rótulos
    df_final = decodificar_dados(df_final, sistema)
    
    return df_final

def decodificar_idade_sim(idade_raw):
    """
    Decodes DATASUS SIM age values to actual years.
    SIM age coding:
    - 1st digit: 1=Minutes, 2=Hours, 3=Days, 4=Months, 5=Years.
    - 2nd & 3rd digits: quantity.
    """
    try:
        idade_str = str(idade_raw).strip()
        if not idade_str or pd.isna(idade_raw) or idade_str == '':
            return None
        
        # Keep numeric
        val = float(idade_raw)
        if val >= 500: # 5xx represents years
            return int(val - 500)
        elif val >= 100: # 1xx, 2xx, 3xx, 4xx are under 1 year (minutes, hours, days, months)
            return 0
        return int(val) # fallback if already parsed/raw
    except:
        return None

def limpar_codigo_municipio(val):
    """
    Cleans municipality code values, converting float/int representations
    (like 355030.0) into a standard 6-digit string representation.
    """
    if pd.isna(val) or val == '':
        return None
    val_str = str(val).strip().split('.')[0]
    if len(val_str) > 6:
        val_str = val_str[:6]
    return val_str.zfill(6)

def decodificar_dados(df, sistema):
    """
    Maps cryptic DATASUS codes to clear human-readable Portuguese labels.
    """
    df = df.copy()
    sistema = sistema.lower()
    
    # Load mapping dictionaries
    mun_dict = carregar_municipios_dict()
    cid_dict = carregar_cid10_dict()
    
    # Common mappings
    sexo_map = {'1': 'Masculino', '2': 'Feminino', '0': 'Ignorado', '9': 'Ignorado'}
    raca_map = {'1': 'Branca', '2': 'Preta', '3': 'Amarela', '4': 'Parda', '5': 'Indígena', '9': 'Ignorado'}
    parto_map = {'1': 'Vaginal', '2': 'Cesáreo', '9': 'Ignorado'}
    
    # Auto-decode municipality if a relevant column is present
    mun_col = None
    for c in ['CODMUNRES', 'CODMUNNASC', 'CODMUNOCOR', 'MUNIC_RES', 'MUNIC_OP']:
        if c in df.columns:
            mun_col = c
            break
            
    if mun_col:
        print(f"[Sucesso] Decodificando codigos municipais da coluna: {mun_col}")
        df['Município'] = df[mun_col].apply(limpar_codigo_municipio).map(mun_dict).fillna(df[mun_col].astype(str))
        
    # Auto-decode CID-10 diagnosis/cause if present
    cid_col = None
    for c in ['CAUSABAS', 'DIAG_PRINC', 'AP_CIDPRI']:
        if c in df.columns:
            cid_col = c
            break
            
    if cid_col:
        print(f"[Sucesso] Decodificando códigos CID-10 da coluna: {cid_col}")
        def formatar_cid(val):
            if pd.isna(val) or val == '':
                return val
            val_clean = str(val).strip().upper()
            descricao = cid_dict.get(val_clean)
            if not descricao:
                val_no_dot = val_clean.replace('.', '')
                descricao = cid_dict.get(val_no_dot)
            if descricao:
                return f"{val_clean} - {descricao}"
            return val_clean
            
        df['Diagnóstico/Causa'] = df[cid_col].apply(formatar_cid)
    
    if sistema == 'sinasc':
        # Sex
        if 'SEXO' in df.columns:
            df['Sexo'] = df['SEXO'].astype(str).map(sexo_map).fillna('Não informado')
            
        # Parturition type
        if 'PARTO' in df.columns:
            df['Tipo de Parto'] = df['PARTO'].astype(str).map(parto_map).fillna('Não informado')
            
        # Race/Skin Color
        if 'RACACOR' in df.columns:
            df['Raça/Cor'] = df['RACACOR'].astype(str).map(raca_map).fillna('Não informado')
            
        # Mother's Education level
        if 'ESCMAE' in df.columns:
            esc_map = {
                '1': 'Nenhuma', '2': '1 a 3 anos', '3': '4 a 7 anos',
                '4': '8 a 11 anos', '5': '12 anos ou mais', '9': 'Ignorado'
            }
            df['Escolaridade da Mãe'] = df['ESCMAE'].astype(str).map(esc_map).fillna('Não informado')
            
        # Mother's Marital status
        if 'ESTCIVMAE' in df.columns:
            civil_map = {
                '1': 'Solteira', '2': 'Casada', '3': 'Viúva',
                '4': 'Divorciada/União Estável', '5': 'Outro', '9': 'Ignorado'
            }
            df['Estado Civil da Mãe'] = df['ESTCIVMAE'].astype(str).map(civil_map).fillna('Não informado')
            
        # Clean Mother's Age
        if 'IDADEMAE' in df.columns:
            df['Idade da Mãe'] = pd.to_numeric(df['IDADEMAE'], errors='coerce')
            
        # Birth Weight
        if 'PESO' in df.columns:
            df['Peso ao Nascer (g)'] = pd.to_numeric(df['PESO'], errors='coerce')

    elif sistema == 'sim':
        # Sex
        if 'SEXO' in df.columns:
            df['Sexo'] = df['SEXO'].astype(str).map(sexo_map).fillna('Não informado')
            
        # Race/Skin Color
        if 'RACACOR' in df.columns:
            df['Raça/Cor'] = df['RACACOR'].astype(str).map(raca_map).fillna('Não informado')
            
        # Death Location
        if 'LOCOCOR' in df.columns:
            loc_map = {
                '1': 'Hospital', '2': 'Outro Estab. Saúde', '3': 'Domicílio',
                '4': 'Via Pública', '5': 'Outros', '9': 'Ignorado'
            }
            df['Local da Ocorrência'] = df['LOCOCOR'].astype(str).map(loc_map).fillna('Não informado')
            
        # Death Age Parsing
        if 'IDADE' in df.columns:
            df['Idade (Anos)'] = df['IDADE'].apply(decodificar_idade_sim)

    elif sistema == 'sih':
        # Sex
        if 'SEXO' in df.columns:
            df['Sexo'] = df['SEXO'].astype(str).map(sexo_map).fillna('Não informado')
            
        # Race/Skin Color in SIH uses different coding: '01', '02', '03'
        if 'RACA_COR' in df.columns:
            raca_sih_map = {'01': 'Branca', '02': 'Preta', '03': 'Parda', '04': 'Amarela', '05': 'Indígena', '99': 'Ignorado'}
            df['Raça/Cor'] = df['RACA_COR'].astype(str).str.zfill(2).map(raca_sih_map).fillna('Não informado')
            
        # Age
        if 'IDADE' in df.columns:
            # SIH age is usually parsed directly but can contain unit codes
            df['Idade (Anos)'] = pd.to_numeric(df['IDADE'], errors='coerce')
            
        # Stay length in days
        if 'DIAS_PERM' in df.columns:
            df['Dias de Internação'] = pd.to_numeric(df['DIAS_PERM'], errors='coerce')
            
        # Total cost
        if 'VAL_TOT' in df.columns:
            df['Custo Total (R$)'] = pd.to_numeric(df['VAL_TOT'], errors='coerce')

    return df

def buscar_dados(pergunta):
    """
    Parses a natural language question to extract UF, year range, month, and system,
    then triggers the download and returns the loaded, concatenated DataFrame.
    """
    pergunta_clean = pergunta.lower().strip()
    
    # 1. State Mapping (UF)
    estados_map = {
        'acre': 'AC', 'alagoas': 'AL', 'amapá': 'AP', 'amazonas': 'AM', 'bahia': 'BA',
        'ceará': 'CE', 'distrito federal': 'DF', 'espírito santo': 'ES', 'goiás': 'GO',
        'maranhão': 'MA', 'mato grosso': 'MT', 'mato grosso do sul': 'MS', 'minas gerais': 'MG',
        'pará': 'PA', 'paraíba': 'PB', 'paraná': 'PR', 'pernambuco': 'PE', 'piauí': 'PI',
        'rio de janeiro': 'RJ', 'rio grande do norte': 'RN', 'rio grande do sul': 'RS',
        'rondônia': 'RO', 'roraima': 'RR', 'santa catarina': 'SC', 'são paulo': 'SP',
        'sergipe': 'SE', 'tocantins': 'TO',
        'brasil': 'BR', 'todo o brasil': 'BR', 'nacional': 'BR'
    }
    
    uf = None
    for nome, sigla in estados_map.items():
        if nome in pergunta_clean:
            uf = sigla
            break
            
    if not uf:
        match_uf = re.search(r'\b(AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|SE|TO|BR)\b', pergunta.upper())
        if match_uf:
            uf = match_uf.group(1)
            
    if not uf:
        print("[Aviso] Estado nao detectado. Usando 'SP' como padrao.")
        uf = 'SP'
        
    # 2. Year Range Parsing (e.g. "de 2020 a 2022" or "2019-2021" or "2020 e 2021")
    ano_inicio = None
    ano_fim = None
    
    # Check for range: year1 to/and year2
    match_range = re.search(r'\b(20\d{2}|19\d{2})\s*(?:a|à|e|até|atoc|ou|-)\s*(20\d{2}|19\d{2})\b', pergunta_clean)
    if match_range:
        ano_inicio = int(match_range.group(1))
        ano_fim = int(match_range.group(2))
        # Ensure correct order
        if ano_inicio > ano_fim:
            ano_inicio, ano_fim = ano_fim, ano_inicio
    else:
        # Check for single year
        match_ano = re.search(r'\b(20\d{2}|19\d{2})\b', pergunta_clean)
        if match_ano:
            ano_inicio = int(match_ano.group(1))
            ano_fim = ano_inicio
        else:
            match_ano_2 = re.search(r'\b(\d{2})\b', pergunta_clean)
            if match_ano_2:
                digitos = int(match_ano_2.group(1))
                ano_val = 2000 + digitos if digitos <= 26 else 1900 + digitos
                ano_inicio = ano_val
                ano_fim = ano_val
                
    if not ano_inicio:
        print("[Aviso] Ano nao detectado. Usando 2022 como padrao.")
        ano_inicio = 2022
        ano_fim = 2022
        
    # 3. Month Mapping (useful for monthly databases)
    mes = None
    meses_nomes = {
        'janeiro': 1, 'fevereiro': 2, 'março': 3, 'abril': 4, 'maio': 5, 'junho': 6,
        'julho': 7, 'agosto': 8, 'setembro': 9, 'outubro': 10, 'novembro': 11, 'dezembro': 12
    }
    for nome_mes, num in meses_nomes.items():
        if nome_mes in pergunta_clean:
            mes = num
            break
            
    # 4. System Mapping
    sistema = None
    sigla_arquivo = None
    
    sistemas_termos = {
        'sim': ('sim', 'DO'),             # DO = Declarações de Óbito
        'morte': ('sim', 'DO'),
        'mortes': ('sim', 'DO'),
        'óbito': ('sim', 'DO'),
        'óbitos': ('sim', 'DO'),
        'mortalidade': ('sim', 'DO'),
        'nascimento': ('sinasc', 'DN'),   # DN = Declarações de Nascidos Vivos
        'nascidos': ('sinasc', 'DN'),
        'sinasc': ('sinasc', 'DN'),
        'parto': ('sinasc', 'DN'),
        'internação': ('sih', 'RD'),       # RD = RPD de AIH reduzida
        'internações': ('sih', 'RD'),
        'hospitalização': ('sih', 'RD'),
        'sih': ('sih', 'RD'),
        'ambulatório': ('sia', 'PA'),      # PA = Produção Ambulatorial
        'sia': ('sia', 'PA'),
        'leitos': ('cnes', 'LT'),          # LT = Leitos CNES
        'estabelecimentos': ('cnes', 'LT'),
        'cnes': ('cnes', 'LT')
    }
    
    for termo, (sys, sigla) in sistemas_termos.items():
        if termo in pergunta_clean:
            sistema = sys
            sigla_arquivo = sigla
            break
            
    if not sistema:
        print("[Aviso] Sistema de saude nao reconhecido. Usando 'SIM' (mortalidade) como padrao.")
        sistema = 'sim'
        sigla_arquivo = 'DO'
        
    print(f"[NLP] Parser: Sistema={sistema.upper()} ({sigla_arquivo}), Estado={uf}, Periodo={ano_inicio} a {ano_fim}, Mes={mes}")
    return baixar_periodo_datasus(sistema, sigla_arquivo, uf, ano_inicio, ano_fim, mes)

import os
import re
import ftplib
import tempfile
import pandas as pd
from dbctodbf import DBCDecompress
from dbfread import DBF
from tqdm import tqdm

# Local directory for caching downloaded files in Parquet format
CACHE_DIR = os.path.join(os.getcwd(), 'datasus_cache')
os.makedirs(CACHE_DIR, exist_ok=True)

def baixar_arquivo_datasus(sistema, sigla_arquivo, uf, ano, mes=None):
    """
    Downloads a .dbc file from DATASUS FTP, decompresses it to .dbf,
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
        print(f"🔄 Loading from cache: {nome_parquet}")
        return pd.read_parquet(caminho_parquet)
    
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
        raise ValueError(f"Sistema '{sistema}' não suportado. Escolha entre: {list(caminhos_ftp.keys())}")
        
    arquivo_alvo = nome_dbc.upper()
    
    print(f"🌐 Connecting to DATASUS FTP (ftp.datasus.gov.br)...")
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
            raise FileNotFoundError(f"Arquivo {nome_dbc} não encontrado no FTP na pasta: {pasta_ftp}")
            
        print(f"📥 Downloading {arquivo_encontrado}...")
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
        print(f"📦 Decompressing .dbc file...")
        decomp = DBCDecompress()
        decomp.decompressFile(caminho_local_dbc, caminho_local_dbf)
        
        # 3. Read DBF using dbfread
        print(f"📊 Loading DBF file into Pandas...")
        dbf = DBF(caminho_local_dbf, encoding='iso-8859-1')
        df = pd.DataFrame(iter(dbf))
        
        # Save to parquet cache
        df.to_parquet(caminho_parquet, index=False)
        print(f"✅ Process complete! Cached at {nome_parquet} ({len(df):,} rows)")
        
        # Cleanup temp files
        if os.path.exists(caminho_local_dbc): os.remove(caminho_local_dbc)
        if os.path.exists(caminho_local_dbf): os.remove(caminho_local_dbf)
        
        return df
        
    except Exception as e:
        if os.path.exists(caminho_local_dbc): os.remove(caminho_local_dbc)
        if os.path.exists(caminho_local_dbf): os.remove(caminho_local_dbf)
        raise RuntimeError(f"Erro ao acessar dados do DATASUS: {e}")

def buscar_dados(pergunta):
    """
    Parses a natural language question to extract UF, year, month, and system,
    then triggers the download and returns the loaded DataFrame.
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
        'sergipe': 'SE', 'tocantins': 'TO'
    }
    
    uf = None
    for nome, sigla in estados_map.items():
        if nome in pergunta_clean:
            uf = sigla
            break
            
    if not uf:
        match_uf = re.search(r'\b(AC|AL|AP|AM|BA|CE|DF|ES|GO|MA|MT|MS|MG|PA|PB|PR|PE|PI|RJ|RN|RS|RO|RR|SC|SP|SE|TO)\b', pergunta.upper())
        if match_uf:
            uf = match_uf.group(1)
            
    if not uf:
        print("⚠️ Estado não detectado. Usando 'SP' como padrão.")
        uf = 'SP'
        
    # 2. Year Mapping (4 digits or 2 digits)
    ano = None
    match_ano = re.search(r'\b(20\d{2}|19\d{2})\b', pergunta_clean)
    if match_ano:
        ano = int(match_ano.group(1))
    else:
        match_ano_2 = re.search(r'\b(\d{2})\b', pergunta_clean)
        if match_ano_2:
            digitos = int(match_ano_2.group(1))
            ano = 2000 + digitos if digitos <= 26 else 1900 + digitos
            
    if not ano:
        print("⚠️ Ano não detectado. Usando 2022 como padrão.")
        ano = 2022
        
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
        print("⚠️ Sistema de saúde não reconhecido. Usando 'SIM' (mortalidade) como padrão.")
        sistema = 'sim'
        sigla_arquivo = 'DO'
        
    print(f"🔍 NLP parsed: Sistema={sistema.upper()} ({sigla_arquivo}), Estado={uf}, Ano={ano}, Mês={mes}")
    return baixar_arquivo_datasus(sistema, sigla_arquivo, uf, ano, mes)

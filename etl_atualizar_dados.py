"""
Script de atualização dos dados do ITBI de Belo Horizonte.

Rode este script na SUA máquina (com internet normal, sem restrições de sandbox)
para atualizar/expandir a base usada pelo app (index.html).

Uso básico (padrão: últimos 5 anos, do mês mais recente para o mais antigo):
    python3 etl_atualizar_dados.py

Opções:
    python3 etl_atualizar_dados.py --anos 3
        Limita a busca a 3 anos em vez de 5.

    python3 etl_atualizar_dados.py --incluir-historico-antigo
        Além dos meses individuais, inclui também o CSV consolidado
        "01/2008 a 05/2024" (arquivo grande, ~80 MB) para ter histórico
        mais antigo que o disponível nos arquivos mensais (que começam em 06/2024).

O que o script faz:
    1. Consulta a API do CKAN (package_show) para listar os meses disponíveis.
    2. Percorre os meses do mais recente para o mais antigo, respeitando o
       limite de anos configurado, parando de buscar mais para trás assim que
       o limite é atingido.
    3. Para cada mês, baixa os dados via API de Datastore (JSON, mais leve) ou,
       se não disponível, baixa o CSV do mês diretamente.
    4. Normaliza endereço, datas e valores monetários.
    5. Gera dados_itbi.json + dados_meta.json atualizados.
    6. Regenera o index.html a partir do index_template.html com os dados novos.

Dependência: só usa a biblioteca padrão do Python (urllib), não precisa instalar nada.
"""

import argparse
import json
import re
import time
import unicodedata
import urllib.error
import urllib.request
import urllib.parse
from datetime import datetime, timedelta

API_BASE = "https://ckan.pbh.gov.br/api/3/action/"
DATASET_ID = "itbi-relatorios"
RECURSO_HISTORICO_ANTIGO_ID = "7f8955aa-0b30-4157-bbc2-7dd444941728"  # 01/2008 a 05/2024, ~80MB

ABREV = [
    (r'^AVE\b', 'AVENIDA'),
    (r'^AV\b', 'AVENIDA'),
    (r'^R\b', 'RUA'),
    (r'^TRAV\b', 'TRAVESSA'),
    (r'^AL\b', 'ALAMEDA'),
]


HEADERS = {
    # o servidor da PBH bloqueia com 403 requisições sem um User-Agent de navegador
    'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                   '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'),
    'Accept': 'application/json, text/csv, */*',
}


def _com_retentativa(func, *args, tentativas=6, espera_inicial=2.0, **kwargs):
    """Tenta de novo em caso de 409/429/5xx, com espera crescente entre tentativas.
    O servidor da PBH parece ter um limitador de taxa que responde 409 CONFLICT
    quando recebe requisições demais em pouco tempo."""
    espera = espera_inicial
    ultimo_erro = None
    for tentativa in range(1, tentativas + 1):
        try:
            return func(*args, **kwargs)
        except urllib.error.HTTPError as e:
            ultimo_erro = e
            if e.code in (409, 429, 500, 502, 503, 504) and tentativa < tentativas:
                print(f"    (HTTP {e.code}, tentativa {tentativa}/{tentativas}, aguardando {espera:.0f}s...)")
                time.sleep(espera)
                espera = min(espera * 2, 60)
                continue
            raise
    raise ultimo_erro


def http_get_json(url):
    def _fazer():
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode('utf-8'))
    return _com_retentativa(_fazer)


def http_get_text(url):
    def _fazer():
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read()
        # o CSV vem com BOM UTF-8
        return raw.decode('utf-8-sig')
    return _com_retentativa(_fazer)


def strip_accents(s):
    return ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')


def normalize_endereco(s):
    s = strip_accents(s).upper()
    s = re.sub(r'\s+', ' ', s).strip()
    for pat, rep in ABREV:
        s = re.sub(pat, rep, s)
    return s


def parse_valor(v):
    if v is None or v == '':
        return None
    v = str(v).strip()
    if ',' in v:
        v = v.replace('.', '').replace(',', '.')
    try:
        return round(float(v), 2)
    except ValueError:
        return None


def parse_data(v):
    try:
        d = datetime.strptime(v.strip(), '%d/%m/%Y')
        return d.strftime('%Y-%m-%d'), d.strftime('%d/%m/%Y')
    except Exception:
        return None, v


def listar_recursos():
    data = http_get_json(API_BASE + "package_show?id=" + DATASET_ID)
    return data['result']['resources']


def extrair_mes_do_nome(nome, url):
    # tenta achar AAAAMM no NOME DO ARQUIVO (ultimo pedaco da url), nao na url inteira --
    # a url inteira contem os UUIDs do dataset/resource, que tambem tem sequencias de 6
    # digitos e davam falso positivo (ex: pegava "966413" de dentro de um UUID).
    basename = (url or '').rsplit('/', 1)[-1]
    m = re.search(r'(\d{6})(?=\.csv$)', basename, re.IGNORECASE)
    if not m:
        m = re.search(r'_(\d{6})(?:_|\.csv$)', basename, re.IGNORECASE)
    if not m:
        return None
    s = m.group(1)
    ano, mes_num = s[:4], s[4:]
    if not (2000 <= int(ano) <= 2100 and 1 <= int(mes_num) <= 12):
        return None
    return f"{ano}-{mes_num}"


def buscar_mes_via_datastore(resource_id):
    # Um mes de ITBI raramente passa de poucos milhares de registros, entao pedimos
    # tudo de uma vez (limit bem alto) em vez de paginar em varias chamadas -- o
    # servidor da PBH parece ter um limite de QUANTIDADE de requisicoes numa janela
    # de tempo (nao so de velocidade), entao menos chamadas = menos chance de travar.
    #
    # IMPORTANTE: nao restringimos "fields" aqui de proposito. O nome da coluna de
    # endereco MUDA entre meses na propria fonte de dados -- alguns resources usam
    # "Endereco Completo", outros so "Endereco" (e ate "Zona Uso ITBI" vira so
    # "Zona Uso" em alguns). Pedir um nome fixo faz o mes vir com endereco vazio
    # quando o nome real for outro. Por isso pegamos todas as colunas e tratamos
    # as variacoes na hora de normalizar (normalizar_registros).
    registros = []
    offset = 0
    limit = 5000
    while True:
        url = f"{API_BASE}datastore_search?resource_id={resource_id}&limit={limit}&offset={offset}"
        data = http_get_json(url)
        result = data['result']
        recs = result.get('records', [])
        if not recs:
            break
        registros.extend(recs)
        offset += len(recs)
        total = result.get('total', 0)
        if offset >= total:
            break
        time.sleep(0.5)  # evita disparar o limitador de taxa do servidor
    return registros


def buscar_mes_via_csv(url_csv):
    texto = http_get_text(url_csv)
    linhas = texto.splitlines()
    header = linhas[0].split(';')
    header = [h.strip() for h in header]
    idx = {nome: i for i, nome in enumerate(header)}
    registros = []
    for linha in linhas[1:]:
        if not linha.strip():
            continue
        campos = linha.split(';')
        if len(campos) < len(header):
            continue
        # o nome da coluna de endereco varia entre remessas ("Endereco Completo" ou so "Endereco")
        idx_endereco = idx.get('Endereco Completo', idx.get('Endereco', 0))

        def campo(*nomes, padrao=''):
            for nome in nomes:
                if nome in idx:
                    return campos[idx[nome]]
            return padrao

        registros.append({
            'Endereco Completo': campos[idx_endereco],
            'Valor Declarado': campo(' Valor Declarado ', 'Valor Declarado'),
            'Valor Base Calculo': campo(' Valor Base Calculo ', 'Valor Base Calculo'),
            'Data Quitacao': campos[idx.get('Data Quitacao', len(header) - 1)],
            'Ano de Construcao (Unidade)': campo('Ano de Construcao (Unidade)', 'Ano de Construcao Unidade'),
            'Area Construida Adquirida': campo('Area Construida Adquirida'),
        })
    return registros


def normalizar_registros(registros_brutos):
    out = []
    for r in registros_brutos:
        # idem: o campo pode se chamar "Endereco Completo" ou so "Endereco" dependendo do mes
        endereco = (r.get('Endereco Completo') or r.get('Endereco') or '').strip()
        if not endereco:
            continue
        data_iso, data_exib = parse_data(r.get('Data Quitacao', ''))
        if not data_iso:
            continue
        ano_construcao = (r.get('Ano de Construcao (Unidade)') or '').strip() or None
        out.append({
            'endereco': endereco,
            'endereco_normalizado': normalize_endereco(endereco),
            'data': data_iso,
            'data_exibicao': data_exib,
            'valor_declarado': parse_valor(r.get('Valor Declarado')),
            'valor_base_calculo': parse_valor(r.get('Valor Base Calculo')),
            'ano_construcao': ano_construcao,
            'area_construida': parse_valor(r.get('Area Construida Adquirida')),
        })
    return out


def carregar_estado_existente():
    """Le dados_itbi.json/dados_meta.json ja existentes (se houver) para permitir
    atualizacao incremental: meses ja baixados com sucesso nao sao buscados de novo."""
    registros_existentes = []
    meses_ok = {}
    try:
        with open('dados_itbi.json', encoding='utf-8') as f:
            registros_existentes = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        registros_existentes = []
    try:
        with open('dados_meta.json', encoding='utf-8') as f:
            meta_antigo = json.load(f)
        for mes, valor in meta_antigo.get('meses_incluidos', {}).items():
            if isinstance(valor, int):  # só conta como "ja feito" se nao foi erro
                meses_ok[mes] = valor
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    # protecao: um mes so conta como "ja baixado" se realmente existem registros
    # dele em dados_itbi.json (ou, no caso do historico, registros no intervalo
    # que ele cobre). Sem isso, um dados_meta.json dessincronizado do
    # dados_itbi.json (ex: só o meta foi versionado/cacheado, sem os dados)
    # faria o script achar que tudo já foi buscado e gerar uma base vazia.
    meses_presentes = set(r['data'][:7] for r in registros_existentes)
    historico_presente = any('2008-01' <= m <= '2024-05' for m in meses_presentes)
    meses_ok = {
        mes: qtd for mes, qtd in meses_ok.items()
        if mes in meses_presentes
        or (mes == '2008-01_a_2024-05_consolidado' and historico_presente)
        or qtd == 0  # mes real sem nenhum registro no periodo e, por isso, legitimamente ausente
    }
    return registros_existentes, meses_ok


def atualizar(anos=5, incluir_historico_antigo=False, refazer_tudo=False, log=print):
    """Busca meses novos/faltantes e regenera dados_itbi.json, dados_meta.json e index.html.
    Por padrao é incremental: meses que ja tinham sido baixados com sucesso antes
    NAO sao buscados de novo (só os que faltam, geralmente só o mes mais recente).
    Retorna um dicionario com o resumo do que foi feito."""
    limite_data = datetime.now() - timedelta(days=365 * anos)
    log(f"Buscando meses até {limite_data.strftime('%m/%Y')} (limite de {anos} anos)...")

    if refazer_tudo:
        todos_registros, meses_ok = [], {}
        log("Modo --refazer-tudo: ignorando dados já existentes, buscando tudo de novo.")
    else:
        todos_registros_antigos, meses_ok = carregar_estado_existente()
        # mantem so os registros dos meses que NAO vamos rebuscar.
        # O historico consolidado cobre varios meses reais (2008-01 a 2024-05) sob uma
        # unica chave especial que nao bate com nenhum 'data'[:7] -- por isso precisa
        # de uma checagem a parte, senao esses registros somem numa proxima atualizacao.
        historico_ja_presente = '2008-01_a_2024-05_consolidado' in meses_ok
        todos_registros = [
            r for r in todos_registros_antigos
            if r['data'][:7] in meses_ok
            or (historico_ja_presente and '2008-01' <= r['data'][:7] <= '2024-05')
        ]
        if meses_ok:
            log(f"{len(meses_ok)} mes(es) já presentes serão reaproveitados sem rebuscar: "
                f"{', '.join(sorted(meses_ok))}")

    recursos = listar_recursos()
    meses = []
    for r in recursos:
        if r['id'] == RECURSO_HISTORICO_ANTIGO_ID:
            continue
        if r.get('format', '').upper() != 'CSV':
            continue
        url = r.get('url', '')
        mes = extrair_mes_do_nome(r.get('name', ''), url)
        if not mes:
            continue
        meses.append((mes, r))
    meses.sort(key=lambda x: x[0], reverse=True)

    meses_novos = {}
    meses_com_erro = {}
    for mes, r in meses:
        mes_data = datetime.strptime(mes + "-01", "%Y-%m-%d")
        if mes_data < limite_data.replace(day=1):
            log(f"Parando: {mes} já passa do limite de {anos} anos.")
            break
        if mes in meses_ok:
            continue  # ja temos esse mes, pula (essa é a parte "incremental")
        log(f"Buscando {mes} ...")
        try:
            if r.get('datastore_active'):
                brutos = buscar_mes_via_datastore(r['id'])
            else:
                brutos = buscar_mes_via_csv(r['url'])
            normalizados = normalizar_registros(brutos)
            todos_registros.extend(normalizados)
            meses_novos[mes] = len(normalizados)
            log(f"  OK ({len(normalizados)} registros)")
        except Exception as e:
            log(f"  FALHOU ({e})")
            meses_com_erro[mes] = f"erro: {e}"
            log("  O servidor da PBH parece ter aplicado um limite temporário depois de várias buscas "
                "seguidas. Parando por aqui para não insistir contra o bloqueio -- o que já foi buscado "
                "com sucesso está salvo. Espere alguns minutos e rode de novo: como a atualização é "
                "incremental, ela vai continuar direto de onde parou.")
            break
        time.sleep(1.5)  # pausa entre meses, evita disparar o limitador de taxa do servidor

    if incluir_historico_antigo and '2008-01_a_2024-05_consolidado' not in meses_ok:
        log("Buscando histórico antigo (2008-05/2024, arquivo grande, pode demorar)...")
        historico = next((r for r in recursos if r['id'] == RECURSO_HISTORICO_ANTIGO_ID), None)
        if historico:
            try:
                brutos = buscar_mes_via_csv(historico['url'])
                normalizados = normalizar_registros(brutos)
                todos_registros.extend(normalizados)
                meses_novos['2008-01_a_2024-05_consolidado'] = len(normalizados)
                log(f"  OK ({len(normalizados)} registros do histórico antigo)")
            except Exception as e:
                log(f"  FALHOU ao buscar histórico antigo ({e})")
                meses_com_erro['2008-01_a_2024-05_consolidado'] = f"erro: {e}"

    todos_registros.sort(key=lambda r: r['data'], reverse=True)

    meses_incluidos = {**meses_ok, **meses_novos, **meses_com_erro}

    with open('dados_itbi.json', 'w', encoding='utf-8') as f:
        json.dump(todos_registros, f, ensure_ascii=False)

    meta = {
        'gerado_em': datetime.now().isoformat(),
        'total_registros': len(todos_registros),
        'meses_incluidos': meses_incluidos,
        'data_mais_recente': todos_registros[0]['data_exibicao'] if todos_registros else None,
        'data_mais_antiga': todos_registros[-1]['data_exibicao'] if todos_registros else None,
        'observacao': f'Atualizado por etl_atualizar_dados.py (incremental) com limite de {anos} anos.',
    }
    with open('dados_meta.json', 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    log(f"\nTotal: {len(todos_registros)} registros salvos em dados_itbi.json "
        f"({len(meses_novos)} mes(es) novo(s) buscado(s) agora)")

    try:
        with open('index_template.html', encoding='utf-8') as f:
            tpl = f.read()
        with open('dados_itbi.json', encoding='utf-8') as f:
            dados_json = f.read()
        with open('dados_meta.json', encoding='utf-8') as f:
            meta_json = f.read()
        out = tpl.replace('__DADOS_JSON__', dados_json).replace('__META_JSON__', meta_json)
        with open('index.html', 'w', encoding='utf-8') as f:
            f.write(out)
        log("index.html atualizado com sucesso.")
    except FileNotFoundError:
        log("Aviso: index_template.html não encontrado nesta pasta, index.html não foi regenerado.")

    return {
        'total_registros': len(todos_registros),
        'meses_novos': meses_novos,
        'meses_com_erro': meses_com_erro,
        'meses_reaproveitados': list(meses_ok.keys()),
        'data_mais_recente': meta['data_mais_recente'],
        'data_mais_antiga': meta['data_mais_antiga'],
    }


def main():
    parser = argparse.ArgumentParser(description="Atualiza a base de dados de ITBI usada pelo app.")
    parser.add_argument('--anos', type=int, default=5, help='Quantos anos para trás buscar (padrão: 5)')
    parser.add_argument('--incluir-historico-antigo', action='store_true',
                         help='Inclui também o CSV consolidado 2008-05/2024 (~80MB), além dos meses individuais')
    parser.add_argument('--refazer-tudo', action='store_true',
                         help='Ignora os dados já baixados e busca tudo de novo (por padrão, a atualização '
                                'é incremental: só busca os meses que ainda não temos)')
    args = parser.parse_args()
    atualizar(anos=args.anos, incluir_historico_antigo=args.incluir_historico_antigo,
              refazer_tudo=args.refazer_tudo)


if __name__ == '__main__':
    main()

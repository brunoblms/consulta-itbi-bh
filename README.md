# Consulta ITBI - Belo Horizonte

App para consultar as transações imobiliárias (ITBI) de Belo Horizonte por endereço, mostrando as mais recentes primeiro, com data e valor. Dados vêm do Portal de Dados Abertos da PBH: https://ckan.pbh.gov.br/dataset/itbi-relatorios

## Como testar agora

Basta abrir o arquivo `index.html` (duplo clique) no navegador. Não precisa de internet, servidor nem instalação — os dados já estão embutidos no próprio arquivo.

1. Digite um endereço no campo de busca (ex.: "Afonso Pena", "Rua Alcântara", "Avenida Cristiano Machado 123"). Não precisa digitar o endereço inteiro nem na ordem exata — a busca localiza qualquer transação cujo endereço contenha todas as palavras/números digitados.
2. Defina a quantidade de transações a mostrar (padrão: 10).
3. Clique em Buscar. Os resultados aparecem da transação mais recente para a mais antiga, com endereço completo, data e valores.

## Cobertura atual dos dados

A cobertura muda toda vez que você atualiza a base (veja abaixo), então o número certo de registros/meses é sempre o que aparece no topo da página (`index.html`) ou em `dados_meta.json`, em vez de um número fixo aqui no README.

## Como atualizar/expandir os dados

A atualização é **incremental**: meses que já foram baixados com sucesso antes não são buscados de novo — só os que ainda faltam (na prática, isso significa que você baixa o histórico mais antigo só uma vez, e depois cada atualização busca só o(s) mês(es) novo(s) publicado(s)).

Duas formas de atualizar:

### 1. Pelo botão "Atualizar base" na própria página (recomendado)

Como um arquivo aberto por duplo clique (`file://`) não consegue rodar scripts por conta própria — é uma restrição de segurança do navegador — o botão só funciona se a página estiver sendo servida por um servidorzinho local incluso (`servidor_local.py`). Para usar:

```
python3 servidor_local.py
```

Isso abre automaticamente `http://localhost:8877/index.html` no navegador (não precisa instalar nada, é só biblioteca padrão do Python). A partir daí, o botão "Atualizar base" no topo da página busca os meses novos, atualiza os arquivos e recarrega os resultados na hora, sem precisar reabrir nada.

Se você abrir o `index.html` direto (duplo clique), a página funciona normalmente para busca, mas o botão só vai mostrar um aviso pedindo para rodar o `servidor_local.py`.

### 2. Pelo terminal, direto

Jeito mais fácil: dê **duplo clique em `abrir_terminal_para_atualizar.command`**. Isso abre o Terminal já dentro da pasta certa e deixa o comando de atualização copiado (Cmd+V) e escrito na tela — é só colar e apertar Enter.

Se preferir abrir o Terminal você mesmo, entre na pasta e rode:

```
python3 etl_atualizar_dados.py
```

Por padrão busca os últimos 5 anos (pulando os meses que já temos) e já regenera o `index.html` no final. Opções:

```
python3 etl_atualizar_dados.py --anos 3                    # muda o período padrão de 5 anos
python3 etl_atualizar_dados.py --incluir-historico-antigo  # inclui também 2008-05/2024 (arquivo grande, ~80MB)
python3 etl_atualizar_dados.py --refazer-tudo              # ignora o que já foi baixado e busca tudo de novo
```

O servidor de dados da PBH tem um limitador de requisições (retorna erro 409 se receber pedidos demais rápido demais) — o script já tenta de novo automaticamente com espera crescente quando isso acontece, então uma atualização com muitos meses novos pode demorar alguns minutos.

## Arquivos

- `index.html` — o app em si (abrir no navegador, ou acessar via servidor local).
- `index_template.html` — o template do app, usado para regenerar o `index.html` a cada atualização.
- `dados_itbi.json` / `dados_meta.json` — dados normalizados atuais e metadados de cobertura (mês a mês).
- `etl_atualizar_dados.py` — script de atualização incremental (usado tanto pelo terminal quanto pelo botão).
- `servidor_local.py` — servidor local que serve a página e faz o botão "Atualizar base" funcionar.
- `abrir_terminal_para_atualizar.command` — duplo clique: abre o Terminal na pasta certa com o comando de atualização pronto pra colar.
- `docs/` — versão publicada na web (GitHub Pages). Contém uma cópia enxuta do app que busca `dados_itbi.json.gz` (dados comprimidos) via `fetch` em vez de ter tudo embutido no HTML. Não tem o botão "Atualizar base" (isso só roda localmente).

## Publicar/atualizar a versão web (GitHub Pages)

A pasta `docs/` é o que fica no ar em `https://<seu-usuario>.github.io/<repo>/`.

### Automático (recomendado)

`.github/workflows/atualizar.yml` roda sozinho no GitHub Actions **toda segunda-feira**, sem depender de nada local:
busca meses novos (incremental), regenera `docs/dados_itbi.json.gz` e `docs/dados_meta.json`, e só faz commit/push se algum dado realmente mudou. Gratuito para repositório público.

Para forçar uma atualização na hora (sem esperar a segunda-feira): na aba **Actions** do repositório no GitHub, abra o workflow "Atualizar base ITBI" e clique em **Run workflow**.

O estado incremental (`dados_itbi.json`/`dados_meta.json` da raiz) é mantido entre execuções via cache do Actions — por isso o workflow não rebusca tudo do zero a cada vez.

### Manual (alternativa, feito localmente)

Se preferir atualizar do seu próprio computador em vez de esperar/acionar o Actions:

```
python3 etl_atualizar_dados.py --anos 5 --incluir-historico-antigo
gzip -9 -f -c dados_itbi.json > docs/dados_itbi.json.gz
cp dados_meta.json docs/dados_meta.json
git add docs/dados_itbi.json.gz docs/dados_meta.json
git commit -m "Atualiza dados da versão web"
git push
```

O `index.html` e o `dados_itbi.json` da raiz (versão local, sem compressão) não são versionados no git (ver `.gitignore`) — só a pasta `docs/` (bem menor) vai para o GitHub.

## Limitações importantes

- **Valores**: vêm de declarações feitas para fins de ITBI (campo "Valor Declarado") e do valor base de cálculo do imposto ("Valor Base Cálculo", geralmente o valor venal). Nenhum dos dois é necessariamente o valor real de mercado da transação.
- **Data**: é a data de quitação do imposto de ITBI, que pode ser bem posterior à data real da negociação/escritura do imóvel.
- **Busca por endereço**: é aproximada. A fonte de dados não tem um identificador único de imóvel nem endereço estruturado (rua/número/bairro em campos separados) — é só um texto único por transação. Sempre confira o endereço completo mostrado no resultado para confirmar se é o imóvel certo.

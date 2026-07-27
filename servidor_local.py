"""
Servidor local para o app de consulta de ITBI, com botão de "Atualizar base" funcionando.

Por que isso existe: um arquivo HTML aberto direto (duplo clique, file://) NUNCA
consegue rodar um script Python sozinho — o navegador não deixa, por segurança.
Então, para o botão "Atualizar base" da página funcionar de verdade (rodando o
etl_atualizar_dados.py e recarregando os dados na hora, sem reabrir o arquivo),
é preciso um servidorzinho local: você roda este script, ele abre a página em
http://localhost:8877 e passa a responder aos cliques do botão.

Como usar:
    python3 servidor_local.py

Depois abra no navegador: http://localhost:8877/index.html
(o próprio script imprime esse link ao iniciar)

Não precisa instalar nada — só biblioteca padrão do Python.
"""

import http.server
import io
import json
import socketserver
import sys
import webbrowser
from functools import partial

import etl_atualizar_dados as etl

PORTA_PREFERIDA = 8877


class Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, formato, *args):
        # log mais enxuto no terminal
        sys.stderr.write("[servidor] " + (formato % args) + "\n")

    def do_POST(self):
        if self.path.rstrip('/') != '/atualizar':
            self.send_error(404, "Rota não encontrada")
            return

        tamanho = int(self.headers.get('Content-Length', 0) or 0)
        corpo = self.rfile.read(tamanho) if tamanho else b'{}'
        try:
            opcoes = json.loads(corpo or b'{}')
        except json.JSONDecodeError:
            opcoes = {}
        anos = opcoes.get('anos', 5)
        refazer_tudo = bool(opcoes.get('refazer_tudo', False))

        logs = []

        def log(*partes):
            linha = ' '.join(str(p) for p in partes)
            print(linha)
            logs.append(linha)

        try:
            resumo = etl.atualizar(anos=anos, refazer_tudo=refazer_tudo, log=log)
            resposta = {'ok': True, 'resumo': resumo, 'logs': logs}
            status = 200
        except Exception as e:
            resposta = {'ok': False, 'erro': str(e), 'logs': logs}
            status = 500

        corpo_resp = json.dumps(resposta, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(corpo_resp)))
        self.end_headers()
        self.wfile.write(corpo_resp)


def main():
    porta = PORTA_PREFERIDA
    handler = partial(Handler, directory='.')
    httpd = None
    for tentativa in range(10):
        try:
            httpd = socketserver.ThreadingTCPServer(('127.0.0.1', porta), handler)
            break
        except OSError:
            porta += 1
    if httpd is None:
        print("Não consegui abrir nenhuma porta livre. Feche outros programas usando portas 8877-8886 e tente de novo.")
        sys.exit(1)

    url = f"http://127.0.0.1:{porta}/index.html"
    print(f"Servidor rodando. Abra no navegador: {url}")
    print("(Ctrl+C para parar)")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nEncerrado.")


if __name__ == '__main__':
    main()

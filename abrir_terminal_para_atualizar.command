#!/bin/bash
# Duplo clique nesse arquivo: abre o Terminal já na pasta do app e deixa o
# comando de atualização pronto pra colar.

cd "$(dirname "$0")"

COMANDO='python3 etl_atualizar_dados.py'

# copia o comando pra área de transferência, se o "pbcopy" existir (padrão no macOS)
if command -v pbcopy >/dev/null 2>&1; then
  printf '%s' "$COMANDO" | pbcopy
  COPIADO="(já copiado pra área de transferência -- é só colar com Cmd+V)"
else
  COPIADO=""
fi

clear
echo "================================================================"
echo " Consulta ITBI - Belo Horizonte"
echo "================================================================"
echo ""
echo " Pasta atual:"
echo "   $(pwd)"
echo ""
echo " Comando de atualização $COPIADO:"
echo ""
echo "   $COMANDO"
echo ""
echo " Cole (Cmd+V) e aperte Enter para rodar."
echo ""
echo " Outras opções, se quiser (é só trocar o comando colado por um destes):"
echo "   python3 etl_atualizar_dados.py --anos 3"
echo "   python3 etl_atualizar_dados.py --incluir-historico-antigo"
echo "   python3 servidor_local.py     (abre o app com o botão 'Atualizar base' funcionando)"
echo "================================================================"
echo ""

# mantém o terminal aberto e interativo, já na pasta certa, esperando você colar o comando
exec "${SHELL:-/bin/bash}"

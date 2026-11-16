#!/usr/bin/env bash
# Abre o THANOS para a internet (Tailscale Funnel): qualquer navegador acessa, sem instalar o Tailscale.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
echo "ATENÇÃO: o endereço do THANOS passa a abrir para qualquer pessoa na internet."
echo "A proteção passa a ser o e-mail e a senha de cada usuário (com bloqueio após 5 erros)."
read -r -p "Digite SIM para abrir: " R
[ "$R" = "SIM" ] || { echo "Nada foi alterado."; exit 0; }
touch .publico
if ! sudo tailscale funnel --bg http://127.0.0.1:8000; then
  echo; echo "Se apareceu um link para liberar o Funnel, abra-o, clique em ativar e rode de novo: bash abrir_internet.sh"; exit 1
fi
NOMEDNS="$(tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')"
echo
echo "PRONTO. O THANOS abre pela internet em: https://${NOMEDNS}"
echo "(pode levar até 10 minutos para funcionar fora da rede do escritório)"
echo "Para voltar a ser só do escritório:  bash fechar_internet.sh"

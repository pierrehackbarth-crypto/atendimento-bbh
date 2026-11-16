#!/usr/bin/env bash
# THANOS – Atendimento: instalação no servidor Ubuntu, publicado só na rede Tailscale do escritório.
# Uso (dentro da pasta THANOS-Atendimento):  bash instalar_ubuntu.sh
# Pode rodar de novo sem problema: o que já foi feito é mantido (banco, chave, usuários).
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
PASTA="$(pwd)"
EU="$(id -un)"
passo() { echo; echo "==== $* ===="; }

if [ "$(id -u)" = "0" ] && [ -z "${THANOS_SEM_SISTEMA:-}" ]; then
  echo "Rode sem sudo:  bash instalar_ubuntu.sh   (a senha será pedida quando precisar)"; exit 1
fi

passo "1/7  Programas do Ubuntu (pede a sua senha do Ubuntu)"
if [ -z "${THANOS_SEM_SISTEMA:-}" ]; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq python3 python3-venv python3-pip >/dev/null
fi
python3 -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10 ou mais novo é necessário"'
echo "ok – $(python3 --version)"

passo "2/7  Bibliotecas do sistema (alguns minutos)"
[ -x .venv/bin/python ] || python3 -m venv .venv
.venv/bin/python -m pip install -q --upgrade pip
.venv/bin/python -m pip install -q -r requirements.txt
echo "ok"

passo "3/7  Configuração (.env) e chave de criptografia"
mkdir -p data storage storage_audio_tmp
if [ ! -f .env ]; then
  .venv/bin/python tools/gerar_env.py
fi
# acesso pelo Tailscale é HTTPS: cookie de sessão seguro
sed -i 's/^SESSION_COOKIE_SECURE=.*/SESSION_COOKIE_SECURE=true/' .env
chmod 600 .env
if grep -q '^OPENAI_API_KEY=$' .env; then
  echo "Cole a chave da OpenAI (começa com sk-) e tecle Enter. Ela não aparece na tela."
  echo "Se não tiver agora, só tecle Enter: depois edite o arquivo .env."
  read -r -s CHAVE; echo
  [ -n "$CHAVE" ] && sed -i "s|^OPENAI_API_KEY=.*|OPENAI_API_KEY=${CHAVE}|" .env
  unset CHAVE
fi
if grep -q '^OPENAI_ANALYSIS_MODEL=$' .env; then
  read -r -p "Modelo de análise da OpenAI (o mesmo do .env do Windows; Enter para preencher depois): " MODELO
  [ -n "$MODELO" ] && sed -i "s|^OPENAI_ANALYSIS_MODEL=.*|OPENAI_ANALYSIS_MODEL=${MODELO}|" .env
fi
echo "ok"

passo "4/7  Banco de dados"
.venv/bin/python -m alembic upgrade head >/dev/null
echo "ok – data/atendimento.db"

passo "5/7  Usuário administrador e dados"
if ! .venv/bin/python tools/tem_usuario.py; then
  read -r -p "Seu e-mail (será o login): " EMAIL
  read -r -p "Seu nome completo: " NOME
  echo "Crie uma senha com pelo menos 10 caracteres (não aparece enquanto digita)."
  .venv/bin/python -m app.cli create-user "$EMAIL" "$NOME" admin
else
  echo "Já existe usuário cadastrado – mantido."
fi
IMPORTOU=""
for d in "$PASTA" "$HOME/Downloads" "$HOME/Transferências"; do
  for f in "$d"/base_clientes*.json.gz "$d"/fichas-backup*.json; do
    [ -f "$f" ] || continue
    echo "Importando $(basename "$f")..."
    .venv/bin/python -m app.cli import-ficha "$f" && IMPORTOU=1
  done
done
[ -n "$IMPORTOU" ] || echo "Nenhum arquivo de dados encontrado (base_clientes_ficha.json.gz, fichas-backup-....json) – pode importar depois rodando este script de novo."

passo "6/7  Iniciar sozinho com o computador"
if [ -z "${THANOS_SEM_SISTEMA:-}" ]; then
  sudo tee /etc/systemd/system/thanos.service >/dev/null <<EOF
[Unit]
Description=THANOS - Atendimento (Buss & Hackbarth)
After=network-online.target
Wants=network-online.target

[Service]
User=${EU}
WorkingDirectory=${PASTA}
ExecStart=${PASTA}/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --log-level warning
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  sudo systemctl daemon-reload
  sudo systemctl enable --now thanos.service >/dev/null 2>&1
  sudo systemctl restart thanos.service
  # cópia de segurança diária às 23h (banco, documentos criptografados e .env), guarda 14 dias
  sudo tee /etc/cron.d/thanos-backup >/dev/null <<EOF
0 23 * * * ${EU} mkdir -p "${HOME}/thanos-backups" && tar -czf "${HOME}/thanos-backups/thanos-\$(date +\%F).tar.gz" -C "${PASTA}" data storage .env && find "${HOME}/thanos-backups" -name 'thanos-*.tar.gz' -mtime +14 -delete
EOF
  sleep 4
  if curl -fsS -o /dev/null http://127.0.0.1:8000/; then echo "ok – o sistema está rodando"; else
    echo "ATENÇÃO: o sistema não respondeu. Veja o erro com:  journalctl -u thanos -n 30"; exit 1; fi
fi

passo "7/7  Publicar na rede Tailscale do escritório (só para quem está na rede)"
if [ -z "${THANOS_SEM_SISTEMA:-}" ]; then
  if ! command -v tailscale >/dev/null; then echo "Tailscale não encontrado. Instale em https://tailscale.com/download/linux e rode de novo."; exit 1; fi
  if ! tailscale status >/dev/null 2>&1; then
    echo "Conectando este computador à sua conta Tailscale: abra o link que aparecer e entre na conta do escritório."
    sudo tailscale up
  fi
  if [ -f .publico ]; then MODO=funnel; echo "Acesso pela internet LIGADO (Funnel)."; else MODO=serve; fi
  if ! sudo tailscale "$MODO" --bg http://127.0.0.1:8000; then
    echo
    echo "Se apareceu um link para ativar HTTPS, abra-o, clique em ativar e rode este script de novo."; exit 1
  fi
  NOMEDNS="$(tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')"
  echo
  echo "=============================================================="
  echo " PRONTO. Endereço do THANOS:"
  echo "   https://${NOMEDNS}"
  if [ -f .publico ]; then
  echo " Abre em qualquer navegador, pela internet (sem Tailscale)."
  else
  echo " Abre em computadores e celulares com o Tailscale ligado na"
  echo " conta do escritório."
  fi
  echo " Entre com o e-mail e a senha que criou."
  echo " Cópia de segurança diária: pasta ~/thanos-backups"
  echo " Guarde também uma cópia do arquivo .env fora deste computador."
  echo "=============================================================="
fi

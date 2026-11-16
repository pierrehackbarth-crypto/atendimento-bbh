#!/usr/bin/env bash
# Fecha o THANOS para a internet: volta a abrir só para quem tem o Tailscale do escritório.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
rm -f .publico
sudo tailscale funnel reset || true
sudo tailscale serve --bg http://127.0.0.1:8000
echo "Pronto: o THANOS voltou a abrir só para aparelhos com o Tailscale do escritório."

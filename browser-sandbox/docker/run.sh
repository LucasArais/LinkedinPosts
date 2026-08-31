#!/usr/bin/env bash
# Sobe o container do browser sandbox com as flags de isolamento:
#
#   --read-only              filesystem do container e somente leitura
#   --tmpfs /tmp              Chromium precisa de um /tmp gravavel; tmpfs
#                              nao persiste em disco e some ao parar o container
#   -v workspace:ro            bind mount do host, somente leitura
#   -v downloads:rw            unico diretorio com escrita, so para downloads
#   --cap-drop=ALL              remove todas as capabilities do kernel
#   --security-opt no-new-privileges  processo dentro do container nunca
#                              ganha privilegio além do que ja tem
#   (nenhum -e)                nenhuma variavel de ambiente do host e propagada
#
# Uso:
#   ./docker/run.sh <allowed_domains_csv> [max_pages] [max_duration_seconds]
#
# Exemplo:
#   ./docker/run.sh "docs.python.org,example.com" 20 180

set -euo pipefail
cd "$(dirname "$0")/.."

ALLOWED_DOMAINS="${1:?uso: run.sh <dominios_permitidos_csv> [max_pages] [max_duration_seconds]}"
MAX_PAGES="${2:-20}"
MAX_DURATION="${3:-300}"
SESSION_ID="sandbox-$(date +%s)"

mkdir -p workspace downloads logs
chmod 777 workspace downloads logs

docker run --rm \
  --name browser-sandbox \
  -p 8088:8088 \
  --read-only \
  --tmpfs /tmp:rw,size=256m \
  -v "$(pwd)/workspace:/workspace:ro" \
  -v "$(pwd)/downloads:/downloads:rw" \
  -v "$(pwd)/logs:/logs:rw" \
  --cap-drop=ALL \
  --security-opt no-new-privileges:true \
  --memory=1g \
  --cpus=1 \
  -e SANDBOX_ALLOWED_DOMAINS="$ALLOWED_DOMAINS" \
  -e SANDBOX_MAX_PAGES="$MAX_PAGES" \
  -e SANDBOX_MAX_DURATION_SECONDS="$MAX_DURATION" \
  -e SANDBOX_SESSION_ID="$SESSION_ID" \
  browser-sandbox:latest

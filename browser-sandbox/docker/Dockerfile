# Container isolado que hospeda o browser sandboxed. Roda com --read-only no
# filesystem do container (ver docker/run.sh), sem variaveis de ambiente do
# host, e sem acesso a nada do host alem dos bind mounts explicitos de
# workspace (somente leitura) e downloads (leitura/escrita).

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
        wget ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Caminho fixo para os browsers do Playwright, independente de $HOME - sem
# isso, `playwright install` (rodado como root, unico jeito de puxar as
# dependencias de sistema via --with-deps) guarda os binarios em
# /root/.cache, invisiveis para o usuario nao-root que roda o servidor.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY guardrails/ ./guardrails/
COPY audit/ ./audit/
COPY core/ ./core/
COPY tools/ ./tools/

# Diretorios que os bind mounts vao cobrir em runtime; existem aqui so para
# que o container funcione mesmo se subir sem nenhum mount (ex: nos testes
# de guardrail que nao precisam de workspace real).
RUN mkdir -p /workspace /downloads /logs

# Usuario nao-root: mesmo com --read-only e sem acesso ao host, evita que um
# processo comprometido dentro do container tenha privilegios de root.
RUN useradd --create-home --uid 1000 sandbox \
    && chown -R sandbox:sandbox /app /downloads /logs /ms-playwright
USER sandbox

EXPOSE 8088

CMD ["python", "-m", "core.browser_server"]

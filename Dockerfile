# Preparation only; the image contains public source and built assets, no state.
FROM node:22-bookworm-slim@sha256:4b150b48b4116e2a22f2c39cc27025fbf4f153e2078fd3b14d159fdb5c7279da AS browser
WORKDIR /build/web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/index.html web/tsconfig.json ./
COPY web/src ./src
RUN npm run build

FROM postgres:16-bookworm@sha256:cf5d353f55240ecc2f811827a15c7d1f2d562f08019b49dca12b5a59f4ab5962 AS pgclient

FROM python:3.11-slim-bookworm@sha256:94a8fee35252d06ab75856f15f12c7bae67b10e8a6da93c7fded82b2610926cd
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OPENBLAS_NUM_THREADS=2
ENV PATH="/usr/lib/postgresql/16/bin:${PATH}"
WORKDIR /opt/kat
COPY m2/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt pyswisseph==2.10.3.2
COPY --from=pgclient /usr/lib/postgresql/16/bin/pg_dump /usr/lib/postgresql/16/bin/pg_dump
COPY --from=pgclient /usr/lib/postgresql/16/bin/pg_restore /usr/lib/postgresql/16/bin/pg_restore
COPY --from=pgclient /usr/lib/x86_64-linux-gnu/libpq.so* /usr/lib/x86_64-linux-gnu/
COPY m2/*.py ./m2/
COPY m2/migrations ./m2/migrations
COPY m2/data ./m2/data
COPY probes/*.py ./probes/
COPY --from=browser /build/web/dist ./web/dist
RUN pg_dump --version && pg_restore --version
RUN groupadd --gid 10001 kat && useradd --uid 10001 --gid kat --home-dir /opt/kat --no-create-home kat && \
    mkdir -p /opt/kat/.local/ephe /var/lib/kat && chown -R kat:kat /var/lib/kat /opt/kat/.local
USER 10001:10001
EXPOSE 8765
CMD ["python", "-m", "m2.web_server", "serve"]

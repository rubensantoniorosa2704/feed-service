# feed-service

Gerador de feeds Atom para perfis do TikTok (e futuras fontes).

## O que faz

Raspa vídeos de perfis do TikTok em intervalos configuráveis e expõe um feed Atom (RSS moderno) que leitores de feed (Feedly, Apple Podcasts, etc) conseguem consumir.

```
TikTok @profile → yt-dlp → SQLite → Atom feed (via HTTP)
```

## Setup

### Requisitos

- Python 3.11+
- `uv` (package manager e resolver de dependências)

Para instalar `uv`:

```bash
pip install uv
# ou no Windows via Chocolatey/scoop/etc
```

### Instalação

1. Clone o repo:
```bash
git clone <repo>
cd feed-service
```

2. Crie um venv e instale deps:
```bash
uv venv
uv sync
```

3. Configure o serviço:
```bash
cp config.example.toml config.toml
# edite config.toml com seus perfis do TikTok
```

4. Rode:
```bash
# Modo debug (Flask dev server)
uv run feed-service --debug

# Modo produção (Waitress WSGI)
uv run feed-service
```

Servidor fica em `http://127.0.0.1:8080`.

## Endpoints

- **GET `/healthz`** — Health check
- **GET `/status`** — Estado de todos os perfis (tentativas, erros, total de vídeos)
- **GET `/feed/<profile>.xml`** — Feed Atom do perfil
- **POST `/force/<profile>`** — Força raspagem imediata (debug)

## Configuração

`config.toml`:

```toml
[server]
host = "127.0.0.1"  # Exposição: 0.0.0.0 requer auth/proxy na frente
port = 8080

[storage]
db_path = "./data/feed-service.db"

[defaults]
interval_minutes = 15      # Intervalos entre raspagens
jitter_seconds = 90        # Aleatoriedade para espalhar requisições
fetch_limit = 5            # Vídeos por raspagem
feed_max_entries = 20      # Vídeos no feed

[[profiles]]
name = "lalann_r"          # Slug do feed: /feed/lalann_r.xml
channel_id = "MS4w..."     # ID interno do TikTok
# interval_minutes = 60    # (opcional) override por perfil
```

Para descobrir o `channel_id` de um perfil:

```bash
yt-dlp --flat-playlist --playlist-end 1 -J "https://www.tiktok.com/@usuario" \
  | python -c "import json,sys; print(json.load(sys.stdin)['entries'][0]['channel_id'])"
```

## Arquitetura

- **`clock.py`** — Centralização de timestamps (UTC, segundo-precisão, canonical format)
- **`db.py`** — Journal SQLite thread-safe (entries + profile state)
- **`sources/tiktok.py`** — Extração via yt-dlp
- **`worker.py`** — Scheduler em background thread
- **`web.py`** — API HTTP (Flask)
- **`atom.py`** — Renderizador de feed Atom (RFC 4287 + Media RSS)

## Dev

```bash
# Rodar testes
uv run pytest

# Lint
uv run ruff check feed_service
uv run black --check feed_service

# Format
uv run black feed_service
uv run ruff check --fix feed_service
```

## Deployment

### Docker

Build:

```bash
docker build -t feed-service .
```

Run (lembre de setar `host = "0.0.0.0"` no `config.toml` para o container conseguir receber tráfego):

```bash
docker run -d \
  --name feed-service \
  -p 127.0.0.1:8080:8080 \
  -v $(pwd)/config.toml:/app/config.toml:ro \
  -v $(pwd)/data:/app/data \
  --restart unless-stopped \
  --log-driver json-file \
  --log-opt max-size=10m \
  --log-opt max-file=3 \
  feed-service
```

Notas:
- `-p 127.0.0.1:8080:8080` restringe o acesso à própria máquina. Sem auth nas rotas, é o mais seguro. Troque para `-p 8080:8080` só quando tiver um proxy com auth na frente.
- `--log-opt max-size=10m --log-opt max-file=3` limita o journal do Docker a 30MB por container (evita encher disco em execução longa).
- Healthcheck em `/healthz` a cada 30s; container marcado unhealthy dispara restart pelo `--restart unless-stopped`.
- SQLite persistido em `./data` no host via volume.

### Docker Compose

Alternativa mais limpa que o `docker run`, usa o `docker-compose.yml` do repo:

```bash
docker compose up -d --build
docker compose logs -f
docker compose down
```

### Consumo de fora do servidor via SSH tunnel

O bind em `127.0.0.1` deixa a porta acessível só de dentro do servidor (sem auth, é o mais seguro). Para consumir o feed do seu notebook sem expor a porta:

```bash
ssh -L 8080:127.0.0.1:8080 usuario@servidor
```

E abra `http://127.0.0.1:8080/feed/<perfil>.xml` no navegador local enquanto o SSH estiver aberto.

### Systemd (Linux)

```ini
[Unit]
Description=feed-service
After=network.target

[Service]
Type=simple
User=feed-service
WorkingDirectory=/opt/feed-service
ExecStart=/opt/feed-service/.venv/bin/python -m feed_service
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

## Roadmap

- [ ] Suporte para YouTube/Instagram/outros
- [ ] Persistência de estado de worker (recovery de crashes)
- [ ] Retry com backoff exponencial
- [ ] Dashboard UI
- [ ] Logs estruturados (JSON)
- [ ] Testes automatizados
- [ ] Métricas Prometheus

## Licença

MIT

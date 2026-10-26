# AARI Educational Suite

Flask app for robotics and data-center cohort courses.

## Local infrastructure (Docker)

Start **Redis and MinIO** (recommended if you already run MySQL locally on port 3306):

```bash
cp .env.example .env
# Edit .env — set MYSQL_PASSWORD to match your existing MySQL Workbench / host mysqld login.

docker compose up -d
```

This project expects **MySQL on the host** at `localhost:3306` by default (`MYSQL_HOST=localhost` in `.env`). You do **not** need Docker MySQL unless you want an isolated DB container.

| Service | URL / port | Notes |
|---------|------------|--------|
| MySQL (host) | `localhost:3306` | Your existing `mysqld` / Workbench — **not** started by compose |
| MySQL (Docker, optional) | `localhost:3306` or `3307` | `docker compose --profile docker-mysql up -d` |
| Redis | `localhost:6379` | Started by compose |
| MinIO API | `http://localhost:9000` | Started by compose |
| MinIO Console | `http://localhost:9001` | Default login `admin` / `password` (see `.env`) |

**Port 3306 already in use?** That usually means host MySQL is running — keep it, use `docker compose up -d` without the mysql profile, and point `.env` at `MYSQL_HOST=localhost`. Only use `--profile docker-mysql` if you want a separate MySQL in Docker (stop host mysqld first, or set `MYSQL_PORT=3307` in `.env`).

Import course schemas after MySQL is up:

```bash
mysql -u root -p < bootcamp.sql
mysql -u root -p < highschool.sql
python3 make_test_login.py --suite dc --reset-all
```

### ffmpeg (transcode worker)

Transcoding shells out to the system `ffmpeg` binary (not a pip package).

- **macOS:** `brew install ffmpeg`
- **Ubuntu/Debian:** `sudo apt-get install ffmpeg`
- **Docker app image:** already included in the `Dockerfile`

## Python app

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app app run --debug
```

## Deploying to Railway

The `Dockerfile` builds only the Flask app. On start, `docker-entrypoint.sh`:
1. runs `init_db.py`, which loads `bootcamp.sql` / `highschool.sql` only if those databases don't exist yet;
2. starts the `dc-transcode` RQ worker in the background (it must share the container with the web process, because uploads are handed over through a local temp folder);
3. serves the app with gunicorn on `$PORT`.

MySQL, Redis and MinIO run as separate Railway services.

### 1. Create the services

In one Railway project, add:

| Service | How |
|---------|-----|
| **MySQL** | New → Database → MySQL |
| **Redis** | New → Database → Redis |
| **MinIO** | New → Template → search "MinIO" (attach a volume), then generate a **public domain** for its API port (9000) |
| **App** | New → GitHub repo (this repo). `railway.toml` tells Railway to build the `Dockerfile`. Generate a public domain for it. |

MinIO needs a public domain because browsers load videos, PDFs, and submissions directly from presigned MinIO URLs.

### 2. App service variables

Use Railway reference variables so credentials stay in sync (service names must match yours):

```bash
MYSQL_HOST=${{MySQL.MYSQLHOST}}
MYSQL_PORT=${{MySQL.MYSQLPORT}}
MYSQL_USER=${{MySQL.MYSQLUSER}}
MYSQL_PASSWORD=${{MySQL.MYSQLPASSWORD}}

REDIS_URL=${{Redis.REDIS_URL}}

MINIO_ENDPOINT=<minio-public-domain>.up.railway.app   # host only, no https://
MINIO_SECURE=true
MINIO_ACCESS_KEY=${{MinIO.MINIO_ROOT_USER}}
MINIO_SECRET_KEY=${{MinIO.MINIO_ROOT_PASSWORD}}
MINIO_BUCKET=aari-videos
MINIO_CORS_ORIGINS=https://<app-public-domain>.up.railway.app

FLASK_SECRET_KEY=<long random string>   # python -c "import secrets; print(secrets.token_hex(32))"
BEHIND_PROXY=true
TEST_PASSWORD=<strong password for the seeded demo accounts>

# Optional
Eleven_Labs_Key=...
Voice_Id=...
```

`TEST_PASSWORD` is applied to every seeded account the first time the databases are created. Change it before the first deploy; it is not written to the logs.

### 3. Deploy

Push to the connected branch (or `railway up`). The first boot logs `MySQL: applied bootcamp.sql` and `MySQL: applied highschool.sql`; later boots log `already exists, leaving it alone`.

To wipe everything and reload the seed data later, open a shell in the app service (`railway ssh`) and run `python reset_local.py --yes`. **This deletes all MinIO objects and both databases.**

### Optional settings

| Variable | Default | Purpose |
|----------|---------|---------|
| `AUTO_INIT_DB` | `true` | Load missing databases on start |
| `RUN_WORKER` | `true` | Run the transcode worker in the app container |
| `WEB_CONCURRENCY` | `2` | gunicorn worker processes |
| `GUNICORN_TIMEOUT` | `600` | Seconds before a slow request (large upload) is killed |

### Run the image locally

```bash
docker build -t aari-suite .
docker run --rm -p 8000:8000 --env-file .env \
  -e MYSQL_HOST=host.docker.internal \
  -e REDIS_URL=redis://host.docker.internal:6379/0 \
  -e MINIO_ENDPOINT=host.docker.internal:9000 \
  aari-suite
```

## Video upload → transcode → playback (data center)

Modules: `miniIO.py` (MinIO client), `redis_conn.py` (RQ queue), `streaming.py` (upload/transcode/playback).

### 1. Start the RQ worker

In a separate terminal (with `.venv` active and infrastructure running):

```bash
rq worker --url redis://localhost:6379/0 dc-transcode
```

### 2. Admin upload (enqueues transcode)

```bash
curl -X POST -b cookies.txt \
  -F "video=@/path/to/lesson-source.mov" \
  http://localhost:5000/dc/admin/video/1/upload
```

Returns `202` with `{"status": "processing", "job_id": "...", "videoid": 1}`.

Poll status:

```bash
curl -b cookies.txt http://localhost:5000/dc/admin/video/1/transcode-status
```

States: `idle`, `processing`, `ready`, `failed`.

On success the worker uploads `videos/dc/{videoid}.mp4` to MinIO and updates `video.miniokey` via `dcqueries.update_video_miniokey`.

### 3. Student playback (presigned URL)

```bash
curl -b cookies.txt http://localhost:5000/dc/video/1/stream
```

Returns `{"url": "<presigned MinIO URL>", "expires_in": 3600}`.

Flask only issues the URL; MinIO serves bytes and HTTP range requests. The frontend `<video>` tag should use this URL (see TODO in `Templates/dc/video.html`).

### API routes

| Method | Path | Auth | Purpose |
|--------|------|------|---------|
| POST | `/dc/admin/video/<videoid>/upload` | DC admin | Upload source file in one request, enqueue transcode (small files only behind proxies) |
| POST | `/dc/admin/video/<videoid>/upload/start` | DC admin | Open a chunked upload: JSON `{filename, size}` → `{upload_id, chunk_size}` |
| POST | `/dc/admin/video/<videoid>/upload/<upload_id>/chunk?offset=N` | DC admin | Raw bytes of one chunk; re-sending a chunk overwrites from `offset` |
| POST | `/dc/admin/video/<videoid>/upload/<upload_id>/finish` | DC admin | Verify the file is complete and enqueue transcode |
| POST | `/dc/admin/video/<videoid>/upload/<upload_id>/abort` | DC admin | Discard a partial upload |
| GET | `/dc/admin/video/<videoid>/transcode-status` | DC admin | Job status |
| GET | `/dc/video/<videoid>/stream` | DC student/admin | Presigned playback URL |

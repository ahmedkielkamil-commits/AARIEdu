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
mysql -u root -p < dccourse.sql
mysql -u root -p < robotcourse.sql
python3 make_test_login.py --suite dc --reset-all
```

### ffmpeg (transcode worker)

Transcoding shells out to the system `ffmpeg` binary (not a pip package).

- **macOS:** `brew install ffmpeg`
- **Ubuntu/Debian:** `sudo apt-get install ffmpeg`
- **Docker app image:** add `RUN apt-get update && apt-get install -y ffmpeg` to your Dockerfile

## Python app

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app app run --debug
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
| POST | `/dc/admin/video/<videoid>/upload` | DC admin | Upload source file, enqueue transcode |
| GET | `/dc/admin/video/<videoid>/transcode-status` | DC admin | Job status |
| GET | `/dc/video/<videoid>/stream` | DC student/admin | Presigned playback URL |

# CivCheck Private Beta Deployment

## Goal

Deploy CivCheck as a private beta, zero-retention web application.

---

## Production Assumptions

- App runs behind Cloudflare Tunnel or another reverse proxy.
- Public users do not access the server directly.
- Uploaded PDFs and generated artifacts are temporary.
- Raw JSON/debug files are never exposed to users.
- FastAPI documentation is disabled in production.
- Access is protected by Cloudflare Access and/or CivCheck beta authentication.

---

## Required Environment Variables

See `.env.example`.

Minimum production settings:

```env
CIVCHECK_BETA_USERNAME=beta
CIVCHECK_BETA_PASSWORD=use-a-strong-password
CIVCHECK_EPHEMERAL_ROOT=/tmp/civcheck_ephemeral
CIVCHECK_RUN_TTL_SECONDS=1800
CIVCHECK_MAX_UPLOAD_BYTES=26214400
CIVCHECK_MAX_UPLOAD_PAGES=25
CIVCHECK_DISABLE_DOCS=1
CIVCHECK_FEEDBACK_DIR=feedback
```

---

## Local Production Test

```bash
cp .env.example .env
nano .env

docker compose -f docker-compose.prod.yml up --build
```

Open:

```
http://127.0.0.1:8000
```

---

## Start the Production Server

```bash
docker compose -f docker-compose.prod.yml up --build -d
```

---

## View Logs

```bash
docker compose -f docker-compose.prod.yml logs -f
```

---

## Stop the Server

```bash
docker compose -f docker-compose.prod.yml down
```

---

## Privacy Verification Checklist

Verify the following before release:

- [ ] No `web_uploads/` or `web_jobs/` directories are used.
- [ ] Temporary files are stored under `/tmp/civcheck_ephemeral`.
- [ ] Raw JSON download routes are blocked.
- [ ] Download packages contain only:
  - Reviewed PDF(s)
  - Privacy notice
- [ ] Temporary job data is deleted after package download.
- [ ] Expired results display a clean error page.


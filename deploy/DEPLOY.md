# Deploying MarksVision to Portainer (build from GitHub)

The app is pushed to **https://github.com/abiralmahdi/MVC.git**
(branch `fix/security-stability-overhaul`). Portainer will clone that repo and
build the image on the Portainer PC.

## 1. Create the stack in Portainer

1. Portainer → **Stacks** → **Add stack**.
2. **Name:** `marksvision`  (keep this name — the data loader uses it).
3. **Build method:** **Repository**.
4. Fill in:
   - **Repository URL:** `https://github.com/abiralmahdi/MVC.git`
   - **Repository reference:** `refs/heads/fix/security-stability-overhaul`
   - **Compose path:** `deploy/portainer-stack.yml`
   - *(repo is public, so no authentication is needed)*
5. In **Environment variables**, set:
   - `DJANGO_SECRET_KEY` = a long random string
   - `DJANGO_ALLOWED_HOSTS` = the Portainer PC's IP (e.g. `192.168.1.50`)
   - `DJANGO_CSRF_TRUSTED_ORIGINS` = `http://192.168.1.50:8000` (same IP)
6. **Deploy the stack.** First build takes a few minutes (installs Python deps).

Open **http://<that-PC-IP>:8000** — the app should load.

## 2. Load your existing data

Your database, profile pictures, reports and trained ML models come in
`marksvision-data-bundle.zip` (kept out of GitHub on purpose).

1. Copy `marksvision-data-bundle.zip` to the Portainer PC and unzip it.
2. In Portainer, **stop** the `marksvision` stack (so nothing is writing to the DB).
3. From inside the unzipped folder, run:
   ```sh
   sh load_data.sh
   ```
   (On Windows PowerShell, run the three `docker run` commands inside `load_data.sh` by hand.)
4. **Start** the `marksvision` stack again.

Now log in with your existing account (e.g. `admin` / `asd123`).

> Skipping this step is fine too — the app then starts with an empty database.
> Create an admin with:  Portainer → Containers → `marksvision-web-1` → Console →
> `python manage.py createsuperuser`  (or `python manage.py seed_demo_data` for demo data).

## Notes

- **Updating later:** push new commits, then in Portainer open the stack → **Pull and redeploy**.
- **Data is safe across rebuilds** — it lives in the `mvc_db`, `mvc_media`, `mvc_ml` volumes.
- **Meter poller** is optional (off by default). Enable the `poller` service in the
  compose only if the meters are reachable from the Portainer PC.
- **Profile pictures** may not display while `DJANGO_DEBUG=0` (Django doesn't serve media
  in production). Everything else works. Ask if you want media serving wired up.

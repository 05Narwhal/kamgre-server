# Deploying Prestop on Oracle Cloud (Always Free)

The web app is hosted on Vercel (free Hobby plan) at the domain; one free Ampere A1 instance runs
the API at `api.<domain>`, which Cloudflare puts on the internet over HTTPS through a tunnel.

```text
visitor ──HTTPS──> kamgre.si      ──> Vercel (static React app, built from GitHub on every push)
visitor ──HTTPS──> api.kamgre.si  ──> Cloudflare ──tunnel──> cloudflared ──> Caddy :80 (localhost only)
                                                           ├─ /api/v1/*  → gunicorn :8066 (Django, prestop-web)
                                                           ├─ /static/*  → /var/lib/prestop/static
                                                           └─ everything else → 404
prestop-collector (delay statistics)   prestop-ingest (LPP history, nightly GTFS refresh)
PostgreSQL 18 + PostGIS   Redis (cache)   prestop-floor (keeps the instance from looking idle)
```

No ports are open to the internet except SSH. Native packages, not Docker: the `postgis/postgis` images in `docker-compose.yml` have no reliable arm64 builds, and this matches the local WSL setup (PG 18 + PostGIS 3.6, Python 3.12).

## Cost safety

The account is (or is being) upgraded to **Pay As You Go**: Oracle serves A1 capacity to paying accounts first, Always Free resources stay free, and idle reclamation does not apply to them. The flip side is that the card *can* be charged for anything outside the Always Free allowance, so the account is locked down in three layers:

1. **Quotas (hard block).** `oci/guardrails.sh` sets quota policies so Oracle refuses to create anything billable: compute is zeroed except `VM.Standard.A1.Flex` at **2 OCPU / 12 GB**, disks are capped at **200 GB** with **5 backups** and no replication, object storage at **20 GB**, no reserved public IPs, and every other quota-capable service (databases, load balancers, GPUs, firewalls, Kubernetes, ...) is zeroed. This also applies to clicks in the console.
2. **Budget alert.** A 1 USD monthly budget on the whole account e-mails you at **0.01 USD actual** or **1 USD forecast** spend. It only alerts; with the quotas in place it should never fire.
3. **Audit before every action.** `oci/audit.sh` (read-only) checks shapes, OCPU/memory totals, disk size and performance, backups, buckets, load balancers, unknown resource types, the spend reported by the Usage API, and that the quotas and budget exist. `push.sh` and `launch-retry.sh` run it first and stop on any `FAIL`.

On the server, outbound traffic (the only usage-based charge left: Oracle bills above **10 TB/month**) is limited in layers that act on their own, without waiting for anyone to read an alert:

- **Per request** (`prestop_api/traffic.py`, always on in production): a visitor sending more than 300 requests a minute gets 429. When more than 3000 visitors were active in 15 minutes, or the API sent more than 30 GB in the last hour, **new visitors** get a 503 "very busy" message while people already using the app (signed `kg_admit` cookie) keep working.
- **Every 5 minutes** (`prestop-egress.timer`): this month's outbound data is the larger of vnstat's count and the guard's own count of the kernel counter. Above `EGRESS_BUSY_GB` (6000), or when the month runs ahead of its pace, the API turns away new visitors with a JSON 503 the app shows as "very busy". At `EGRESS_LIMIT_GB` (8000, capped at 9000) the tunnel and Caddy stop, the API answers 503 to everyone, and a systemd drop-in keeps Caddy and cloudflared from starting again, even after a reboot, until the next month (UTC).

```sh
# in WSL, from the repository root
bash backend/deploy/oracle/oci/guardrails.sh --dry-run   # show the quotas and alerts it would set
bash backend/deploy/oracle/oci/guardrails.sh             # apply (free, safe to re-run)
bash backend/deploy/oracle/oci/audit.sh                  # anytime: "Audit passed" = nothing billable
```

Rules:

- Change limits only by editing `guardrails.sh` and re-running it, never in the console. Quotas block new resources; they never stop or delete running ones.
- In the console, create only resources marked **Always Free-eligible**, in the home region (`eu-milan-1`). Leave boot volume performance at **10 VPU** (Balanced), auto-tune off, and no backup policy.
- If the budget e-mail ever arrives: run `audit.sh`, then terminate or shrink what it lists.
- Log in to the Oracle console at least once every 60 days.

## Idle reclamation and the utilization floor

Oracle may reclaim an Always Free instance when, over 7 days, the 95th-percentile CPU, the network **and** (A1) the memory utilization all stay under 20%. `prestop-floor` keeps CPU and memory at **25%** whatever the traffic:

- **CPU:** one burner per core at `SCHED_IDLE` priority fills the gap between what Prestop uses and 25%. Any real work (requests, Postgres, the collector) preempts it instantly, and when real use is above 25% the burners stop.
- **Memory:** a ballast of resident memory tops usage up to 25%. It shrinks as Prestop needs more, is released at once if free memory drops below 15%, and the kernel kills the floor first if memory ever runs out (the service then restarts).

Tested in WSL: idle → CPU 24–25%; with a real 50% load added → filler 0% within one interval; back to 25% afterwards. Tune it in `/etc/prestop/floor.env` (see `floor/floor.env.example`). Check it with `sudo prestop-status`, and in the console under **Instance → Metrics** (needs the Oracle Cloud Agent, which Ubuntu images include).

## First deploy

### 1. Oracle: create the instance

Console → **Compute → Instances → Create instance**:

- **Image:** Canonical Ubuntu 24.04. **Shape:** Ampere `VM.Standard.A1.Flex`, **2 OCPU, 12 GB**. Check that it shows *Always Free-eligible*.
- **SSH keys:** *Generate a key pair for me* and **save the private key**.
- **Boot volume:** default (about 50 GB) or up to 100 GB.
- "Out of host capacity" means a temporary shortage of free A1 machines: try another availability domain, or try again later.

When it is running, copy the **public IP** from the instance page.

#### "Out of host capacity": let a script retry

Free A1 capacity is handed out as it frees up, so creating the instance often fails for hours or longer on free-only accounts; Pay As You Go accounts usually get it quickly. `oci/launch-retry.sh` retries every minute with the same settings (2 OCPU, 12 GB, Ubuntu 24.04, 100 GB, the public subnet) until it works. It never creates a second instance or exceeds the free allowance, and it refuses to start until `audit.sh` passes, so run `oci/guardrails.sh` once first.

1. **API key** (once): Console → profile icon (top right) → **My profile** → **API keys** → **Add API key** → *Generate API key pair* → **Download private key** → **Add**. Copy the configuration preview it shows.
2. In WSL (the OCI CLI is installed with `pipx install oci-cli`, plus `sudo apt install jq`):

   ```sh
   mkdir -p ~/.oci && nano ~/.oci/config        # paste the preview; set key_file=~/.oci/oci_api_key.pem
   cp "/mnt/c/Users/<you>/Downloads/<the-downloaded>.pem" ~/.oci/oci_api_key.pem && chmod 600 ~/.oci/oci_api_key.pem ~/.oci/config
   oci iam region list --output table           # works = configured
   ssh-keygen -y -f ~/.ssh/oracle_prestop > ~/.ssh/oracle_prestop.pub
   SSH_PUBLIC_KEY=~/.ssh/oracle_prestop.pub bash backend/deploy/oracle/oci/launch-retry.sh
   ```

Leave the window open; it prints the public IP when the instance is created.

### 2. Cloudflare: create the tunnel

Your domain must be active on Cloudflare.

1. **Zero Trust → Networks → Tunnels → Create a tunnel → Cloudflared**, name it `prestop`.
2. On the install page, copy the long **token** after `cloudflared service install`. You don't run that command; the deploy does.
3. **Public hostname:** subdomain `api`, domain `kamgre.si` → Service `HTTP`, URL `localhost:80`. Cloudflare creates the DNS record. The domain itself and `www` point to Vercel (see "Web app on Vercel").
4. **SSL/TLS → Edge Certificates → Always Use HTTPS:** on.

### 3. Your computer: configure the deploy

In WSL (`kali-linux`), copy the private key from step 1:

```sh
mkdir -p ~/.ssh && cp "/mnt/c/Users/<you>/Downloads/ssh-key-XXXX.key" ~/.ssh/oracle_prestop && chmod 600 ~/.ssh/oracle_prestop
```

Then copy `config.local.example` to `config.local` (git-ignored) and fill in the IP, key path, domain and tunnel token.

### 4. Deploy

From the repository root in PowerShell:

```powershell
powershell -File backend/deploy/oracle/push.ps1
```

The first run takes 10–20 minutes. It copies the backend, then installs PostgreSQL/PostGIS, Redis, Caddy and cloudflared, generates a secret key, creates the database, installs Python packages and runs migrations. It also imports the GTFS timetables, connects the tunnel, starts every service, and finishes with a health check (`https://api.<domain>/api/v1/health` then answers). Afterwards it publishes `backend/` to the public AGPL repository (`scripts/publish-backend.ps1`).

### 5. Web app on Vercel

The app is built by Vercel from the private GitHub repository on every push to `main`; `vercel.json` holds the build, routing, cache and security headers, and `.env.production` points the build at `https://api.kamgre.si/api/v1`.

1. <https://vercel.com/new> → sign in with GitHub (Hobby plan, no card) → **Import** `05Narwhal/kamgre` → keep the detected settings → **Deploy**.
2. Project → **Settings → Domains** → add `kamgre.si` and `www.kamgre.si`. Vercel shows the DNS records; add them in Cloudflare **DNS** with the proxy **off** (grey cloud, "DNS only").
3. Project → **Settings → Deployment Protection**: Vercel Authentication on for preview deployments (default).

## Updating

Web app: commit and `git push`; Vercel deploys it. Backend: commit, then the same command as the first deploy. Only changed files are copied. Python packages are reinstalled only when `Pipfile.lock` changes, then migrations run and services restart.

The delay statistics (line reliability, typical travel times) live only in this database and build up from months of observations, so every deploy keeps them: `server/keep-stats.sh` copies all rows to `/var/backups/prestop-stats/` before the migrations (copies of the last five deploys are kept) and counts them again afterwards. If any went missing, it puts them back and stops the deploy with a message. Deploys never recreate the database; only `prestop-restore` replaces it, and only after you type `restore`.

```powershell
powershell -File backend/deploy/oracle/push.ps1
```

## What runs by itself

| What | How |
| --- | --- |
| API, collector, push sender, ingestion, Caddy, tunnel, database, cache | systemd services: start at boot, restart on crash |
| API hangs | `prestop-watchdog.timer` checks `/api/v1/health` every 2 min, restarts the API after 3 failures |
| Idle reclamation | `prestop-floor` keeps CPU and memory at 25% (only needed while the account is free-only) |
| Outbound data | API load shedding; `prestop-egress.timer` refuses new visitors at 6000 GB or ahead of pace and stops public traffic at 8000 GB/month, before Oracle bills above 10 TB |
| Timetables | `prestop-ingest` refreshes GTFS nightly at 04:30 |
| Backups | `prestop-backup.timer` at 03:00: `pg_dump` to `/var/backups/prestop`, 7 days kept, optional off-server copy |
| Security updates | unattended-upgrades, with a reboot at 03:30 when needed (services come back on their own) |

## Day to day

From Windows, `yarn server:top` (optionally `yarn server:top 5` for every 5 s) opens the live view in your own terminal over SSH, using `config.local`. It sends the local `server/top.sh`, so it works before the next deploy.

`yarn server:ssh` opens a shell on the server in your own terminal (`exit` or Ctrl+D leaves), for admin commands such as `sudo prestop-manage leg_detours --legs --delete` or `sudo prestop-status`.

```sh
ssh -i ~/.ssh/oracle_prestop ubuntu@<ip>
sudo prestop-status                          # services, floor, health, last backup, disk
sudo prestop-top                             # live view: per-service CPU/memory, network, API latency (q quits)
journalctl -u prestop-web -f                 # API log (also prestop-collector, prestop-push, prestop-ingest, prestop-floor)
sudo prestop-manage <command>                # any manage.py command, e.g. createsuperuser, import_gtfs
sudo systemctl start prestop-backup          # back up now
sudo prestop-restore /var/backups/prestop/prestop-YYYY-MM-DD.dump
sudoedit /etc/prestop/prestop.env            # settings; then restart prestop-web prestop-collector prestop-push prestop-ingest
```

The OJPP admin and pages are not public. Open them through an SSH tunnel: `ssh -i ~/.ssh/oracle_prestop -L 8066:127.0.0.1:8066 ubuntu@<ip>`, then <http://localhost:8066/admin/>.

### Push notifications

Reminders and live changes of watched trips reach phones as Web Push, even when KamGre is closed. No paid service is involved: the server signs each message with its VAPID key and sends it straight to the browser's push service (Apple, Google, Mozilla).

- `prestop-push` (`manage.py run_push`) checks the watches every 20 s: it sends due reminders and, from 30 min before a reminder until the vehicle leaves, a cancellation at once or a delay change of 2+ min at most every 3 min. Each update replaces the earlier notification (same tag).
- Keys: the first deploy runs `prestop-manage vapid_keys` and appends `PRESTOP_VAPID_PUBLIC_KEY` / `PRESTOP_VAPID_PRIVATE_KEY` to `/etc/prestop/prestop.env`. Only the public key reaches the app (`/api/v1/capabilities` → `push: true, pushKey`). Keep the private key there and nowhere else; replacing it silently unsubscribes every phone. `PRESTOP_VAPID_SUBJECT` is the contact the push services see (`mailto:` or `https:`).
- Dependencies: `pywebpush` and friends come from `ojpp-django/requirements-prestop.txt`, installed with the upstream lock as constraints.
- Check it works: `systemctl status prestop-push` and `journalctl -u prestop-push -f` (a `tick: sent N` line every 20 s). In the app, Settings → Notifications → "Send test notification" calls `POST /api/v1/push/test`. From the shell: `sudo prestop-manage shell -c "from prestop_push.models import PushSubscription as S; from prestop_push import sender; print([sender.send(s, {'title': 'KamGre', 'body': 'Test', 'url': '/', 'tag': 'test'}) for s in S.objects.all()])"`.
- iPhone: push works only in the installed app (iOS 16.4+, added to the home screen), not in a Safari tab.

### Off-server backups (optional, free)

Cloudflare R2 gives 10 GB free. Create a bucket `prestop-backups` and an R2 API token (Object Read & Write), then on the server:

```sh
sudo tee /etc/prestop/rclone.conf >/dev/null <<'EOF'
[r2]
type = s3
provider = Cloudflare
access_key_id = <key id>
secret_access_key = <secret>
endpoint = https://<account id>.r2.cloudflarestorage.com
EOF
sudo chown root:prestop /etc/prestop/rclone.conf && sudo chmod 640 /etc/prestop/rclone.conf
sudoedit /etc/prestop/prestop.env            # BACKUP_RCLONE_REMOTE=r2:prestop-backups
sudo systemctl start prestop-backup && journalctl -u prestop-backup -n 5
```

## Files

| Path | Purpose |
| --- | --- |
| `push.ps1`, `push.sh` | Deploy the backend from Windows (runs push.sh in WSL, then publishes backend/) |
| `config.local.example` | Server address, SSH key, domain, tunnel token |
| `server/bootstrap.sh` | One-time machine setup (run by update.sh on the first deploy) |
| `server/update.sh` | Applies each deploy on the server |
| `server/keep-stats.sh` | Keeps the delay statistics through each deploy (copy before migrations, put back what went missing) |
| `server/{manage,status,backup,restore,watchdog,egress-guard}.sh` | `prestop-manage`, `prestop-status`, backups, restore, health watchdog, outbound-data cap |
| `oci/guardrails.sh`, `oci/audit.sh` | Quotas + budget alert on the Oracle account; read-only check that nothing is billable |
| `oci/launch-retry.sh`, `oci/lib.sh` | Create the A1 instance when capacity frees up; shared settings (the free limits) |
| `server/prestop.env.template` | Becomes `/etc/prestop/prestop.env` |
| `django/prestop_production.py` | Production settings on top of `ojpp_core.settings_prestop` |
| `systemd/` | Services and timers |
| `caddy/Caddyfile`, `postgres/prestop.conf` | Web server; PostgreSQL tuning (3 GB buffer cache, prewarm) |
| `floor/` | Utilization floor and its settings |

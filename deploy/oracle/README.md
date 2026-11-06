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
PostgreSQL 18 + PostGIS   Redis (cache)
```

No ports are open to the internet except SSH. Native packages, not Docker: the `postgis/postgis` images in `docker-compose.yml` have no reliable arm64 builds, and this matches the local WSL setup (PG 18 + PostGIS 3.6, Python 3.12).

## Cost safety

The account is upgraded to **Pay As You Go** (since 2026-10-15): Oracle serves A1 capacity to paying accounts first, Always Free resources stay free, and idle reclamation does not apply to them. The flip side is that the card *can* be charged for anything outside the Always Free allowance, so the account is locked down in three layers:

1. **Quotas (hard block).** `oci/guardrails.sh` sets quota policies so Oracle refuses to create anything billable: compute is zeroed except `VM.Standard.A1.Flex` at **2 OCPU / 12 GB**, disks are capped at **200 GB** with **5 backups** and no replication, object storage at **20 GB**, no reserved public IPs, and every other quota-capable service (databases, load balancers, GPUs, firewalls, Kubernetes, ...) is zeroed. This also applies to clicks in the console.
2. **Budget alert.** A 1 USD monthly budget on the whole account e-mails you at **0.01 USD actual** or **1 USD forecast** spend. It only alerts; with the quotas in place it should never fire.
3. **Audit before every action.** `oci/audit.sh` (read-only) checks shapes, OCPU/memory totals, disk size and performance, backups, buckets, load balancers, unknown resource types, the spend reported by the Usage API, and that the quotas and budget exist. `push.sh` and `launch-retry.sh` run it first and stop on any `FAIL`.

On the server, outbound traffic (the only usage-based charge left: Oracle bills above **10 TB/month**) is limited in layers that act on their own, without waiting for anyone to read an alert:

- **Per request** (`prestop_api/traffic.py`, always on in production): a visitor (one IP address) sending more than 1200 requests a minute gets 429: a whole household, school or mobile network behind one address stays well under it. When more than 3000 visitors were active in 15 minutes, or the API sent more than 30 GB in the last hour, **new visitors** get a 503 "very busy" message while people already using the app (signed `kg_admit` cookie) keep working.
- **Every 5 minutes** (`prestop-egress.timer`): this month's outbound data is the larger of vnstat's count and the guard's own count of the kernel counter. Above `EGRESS_BUSY_GB` (6000), or when the month runs ahead of its pace, the API turns away new visitors with a JSON 503 the app shows as "very busy". At `EGRESS_LIMIT_GB` (8000, capped at 9000) the tunnel and Caddy stop, the API answers 503 to everyone, and a systemd drop-in keeps Caddy and cloudflared from starting again, even after a reboot, until the next month (UTC).

```sh
# in WSL, from the repository root
bash backend/deploy/oracle/oci/guardrails.sh --dry-run   # show the quotas and alerts it would set
bash backend/deploy/oracle/oci/guardrails.sh             # apply (free, safe to re-run)
yarn server:audit                                        # anytime: "Audit passed" = nothing billable (runs oci/audit.sh; plain `yarn audit` is Yarn's own package check)
```

Rules:

- Change limits only by editing `guardrails.sh` and re-running it, never in the console. Quotas block new resources; they never stop or delete running ones.
- In the console, create only resources marked **Always Free-eligible**, in the home region (`eu-milan-1`). Leave boot volume performance at **10 VPU** (Balanced), auto-tune off, and no backup policy.
- If the budget e-mail ever arrives: run `audit.sh`, then terminate or shrink what it lists.
- Log in to the Oracle console at least once every 60 days.

## Idle reclamation

Oracle may reclaim an idle Always Free instance (95th-percentile CPU, network and memory all under 20% for 7 days), but only on free-only accounts. The account is Pay As You Go since 2026-10-15, so idle reclamation does not apply. The utilization floor (`prestop-floor`) that kept CPU and memory at 25% until then is removed, and `update.sh` disables it on a server that still has it. Should the account ever be free-only again, it is in git history (`backend/deploy/oracle/floor/`).

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
powershell -NoProfile -ExecutionPolicy Bypass -File backend/deploy/oracle/push.ps1
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

About a minute before the restart, `push.sh` turns on the maintenance flag (`server/maintenance.sh on`): `/api/v1/health` then reports `maintenance: {message, until}` so open apps can say the server is updating. The flag goes again when the deploy ends, and the API ignores one older than ten minutes past its `until`.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File backend/deploy/oracle/push.ps1
```

## What runs by itself

| What | How |
| --- | --- |
| API, collector, push sender, ingestion, Caddy, tunnel, database, cache | systemd services: start at boot, restart on crash |
| API hangs | `prestop-watchdog.timer` checks `/api/v1/health` every 2 min, restarts the API after 3 failures |
| Outbound data | API load shedding; `prestop-egress.timer` refuses new visitors at 6000 GB or ahead of pace and stops public traffic at 8000 GB/month, before Oracle bills above 10 TB |
| Timetables | `prestop-ingest` refreshes GTFS nightly at 04:30 |
| SŽ replacement timetables | `prestop-szpdf.timer` every 30 min (3 min after boot, and once after each deploy): `prestop-manage szpdf_sync` reads the PDFs SŽ's notices link into `/var/lib/prestop/sz-timetables` (one JSON per PDF plus `index.json`, which the API reads). A PDF is downloaded when its link is new (a link it has is re-checked once a day with a conditional request) and parsed when its checksum or the parser version is new, so most runs take a second or two. A one-shot service with `Nice=10`, `CPUQuota=50%`, `MemoryMax=400M`; a screenshot pasted over a table is read with `tesseract-ocr`, which `update.sh` installs. Files of notices gone for 7 days are deleted. `sudo prestop-manage szpdf_sync --report` shows one line per notice (status ok / unsure / failed / missing) |
| Night window | `prestop-nightly.timer` at 02:05 (+ up to 5 min, `Persistent=false`: a missed night is skipped, never caught up at rush hour): `server/nightly.sh` runs `rollup_stats` (yesterday's SŽ train and station rollups, then earlier days without rows until 02:50, 90 days back) and on Sundays `sz_tracks --days 90` into `/var/lib/prestop/sz_tracks.json` (each train's usual track; the app's checked-in copy until then). `Nice=10`, `CPUQuota=60%`, `MemoryMax=600M`, `TimeoutStartSec=45min`: done before the 03:00 backup. Live polls are not part of it. `journalctl -u prestop-nightly` shows each night's JSON line |
| City timetable check | `prestop-citytt-check.timer` at 02:15 (+ up to 2 min, `Persistent=true`; once after each deploy): `prestop-manage citytt_check` looks at the 8 hand-kept city feeds (see "City timetables" below) and writes `/var/lib/prestop/citytt-check.json`, which `/health` serves as `cityTimetables`. A few small requests to the operators' list pages, no PDF downloads. `Nice=10`, `CPUQuota=25%`, `MemoryMax=200M` |
| Backups | `prestop-backup.timer` at 03:00: `pg_dump` to `/var/backups/prestop`, 7 days kept, optional off-server copy |
| Security updates | unattended-upgrades, with a reboot at 03:30 when needed (services come back on their own) |

## Day to day

From Windows, `yarn server:top` (optionally `yarn server:top 5` for every 5 s, or `yarn server:top logs` to open on a tab) opens the live view in your own terminal over SSH, using `config.local`. It sends the local `server/top.py` (Python standard library, run by the server's own `python3`), so it works before the next deploy; on the server it is `sudo prestop-top`, and `sudo prestop-top --once` prints one frame of every tab. The mouse works throughout: hover any graph for the numbers behind it, click tabs, panel titles marked ›, alerts and the footer, and scroll with the wheel. To select text, hold Shift. A terminal that does not report mouse moves still shows a graph's numbers when you click it.

It has seven tabs, switched with ←/→, Tab, 1–7 or a click (`?` lists the keys, `p` pauses, `+`/`-` change the speed): **Overview** (what needs a look, resources, traffic, services, health), **System** (CPU, memory, network and disk graphs, top processes), **Services** (state, uptime, restarts, CPU history, the timers' last and next runs, backups), **Traffic** (visitors per minute, API connections and hourly bytes, this month's outbound data with its pace and per-day/per-hour graphs from vnstat), **Data** (`/health`, coverage, every source, PostgreSQL and Redis), **Learning** and **Logs** (warnings and errors of the KamGre units in the last 24 h). It is read-only: the month's outbound data is worked out from the egress guard's counter file and vnstat the way `egress-guard.sh` does, without running the guard.

Its **Learning** tab (refreshed once a minute) follows the stay-on learning (`prestop_statistics/stays.py`). It shows how much of today the collector has recorded and how many of the 72 allowed minutes of downtime are used. A day counts only at 95 % or more, and 7 counted days in a row open a feed. It also lists each feed's streak with the day it will open, the feeds already open with their `sure`/`likely` counts, and the last 14 days of the nightly check. It turns red when today will not count, or when a feed is open but the 04:30 nightly learning has not run.

`yarn server:update` refreshes Arriva's notices without a deploy (`yarn server:update --check` only reads them and says how many). arriva.si has blocked networks outside Slovenia, this server's among them, so `notices-remote.sh` reads the posts on your PC and sends them over SSH to `prestop-manage arriva_notices --import`, which checks them and writes `/var/lib/prestop/arriva-posts.json`; a bad answer leaves the old notices in place. The API's workers notice the file by themselves, with no restart. `yarn server:push` does the same at the end of every deploy, and a failure there does not fail the deploy. While the server can read the site itself, the newer read wins. `/health` lists `operator-site:arriva`, with `stale` once the last read is more than an hour old from the site or three days old from an upload. `sudo prestop-manage arriva_notices` shows what the server holds.

`yarn server:update --sz <file>` also uploads SŽ's list of disruptions (`potniski.sz.si/ovire-in-izredne-spremembe`), which is in no open feed and answers a bot check, so nothing reads it automatically: open the page in your own browser, save it (Ctrl+S, or copy the list's outer HTML into a file), and pass that file. `prestop-manage sz_notices --import` checks it and writes `/var/lib/prestop/sz-list.json`; a file with no notices leaves the old list in place. Then `szpdf_sync` runs at once, so the replacement buses of a timetable it reads well reach the planner right away; the rest stay text notices for their days. SŽ can change a notice after your upload, so run this about twice a week: `/health` lists `sz:list`, `stale` after three days, and the notices still show. `sudo prestop-manage sz_notices` shows what the server holds.

The **Usage** tab (`yarn server:top usage`, or `usage week`, `month`, `all`) shows users and new users per day, all users so far, requests per day and hour, features and endpoints with error rate and p95, Hop, and the platform split, with the change from the period before. It reads the tables and Redis directly (`prestop_api/analytics.py` does the counting). The API counts requests per hour, route and status class in Redis; the collector moves them to Postgres every minute (kept 400 days). Visitors are a HyperLogLog per day of salted hashes whose salt is deleted when the day ends; the nightly save keeps only those (kept forever), never an IP. Because each day has its own salt, the same person on two days counts twice, so a longer period shows users a day, not distinct people.

`yarn server:ssh` opens a shell on the server in your own terminal (`exit` or Ctrl+D leaves), for admin commands such as `sudo prestop-manage leg_detours --legs --delete` or `sudo prestop-status`.

```sh
ssh -i ~/.ssh/oracle_prestop ubuntu@<ip>
sudo prestop-status                          # services, health, last backup, disk
sudo prestop-top                             # live view: per-service CPU/memory, network, API latency (q quits)
journalctl -u prestop-web -f                 # API log (also prestop-collector, prestop-push, prestop-ingest)
sudo prestop-manage <command>                # any manage.py command, e.g. createsuperuser, import_gtfs
sudo systemctl start prestop-backup          # back up now
sudo prestop-restore /var/backups/prestop/prestop-YYYY-MM-DD.dump
sudoedit /etc/prestop/prestop.env            # settings; then restart prestop-web prestop-collector prestop-push prestop-ingest
```

The OJPP admin and pages are not public. Open them through an SSH tunnel: `ssh -i ~/.ssh/oracle_prestop -L 8066:127.0.0.1:8066 ubuntu@<ip>`, then <http://localhost:8066/admin/>.

### City timetables

Nobody publishes GTFS for Celje, Ptuj, Koper, Postojna, Brežice, Piran, Jesenice and Maribor, so their timetables are built on your PC from the operators' own pages (`yarn city-timetables`) into `backend/ojpp-django/prestop_api/data/gtfs/<feed>/` and committed; the server never fetches them. Two things go stale without anyone seeing it: a timetable ends (Piran 2027-03-31, Jesenice 2027-06-24, the rest 2027-08-31) or the operator publishes a new one. The server watches for both; it changes nothing by itself.

- **The check.** `prestop-citytt-check.timer` runs `prestop-manage citytt_check` every night at 02:15. Per feed it reads the folder's `status.json` (end date, last build, which files it was built from), the operator's list page (are the timetable links still the files the build read?) and the headers of those files (Last-Modified, Content-Length), never the PDFs. States, most urgent first: **expired**, **new** (a timetable was published or replaced), **expires** (14 days or fewer left), **failed** (the last build failed), **unreachable** (the site did not answer: said, never an alarm), ok. `/api/v1/health` lists them as `cityTimetables`; `yarn server:top` shows one warning line on the Overview ("City timetables: Piran expires in 12 days · Celje has a new timetable"). `sudo prestop-manage citytt_check` runs it by hand. It costs a handful of small requests a night and $0.
- **On your PC.** `yarn live` / `yarn backend` runs the same check at start (`--no-save`) and prints its summary in the log (a `city` line). Your PC reaches arriva.si, which blocks this server's network, so it sees changes at Jesenice, Piran, Ptuj and Koper that the server can only report as unreachable. `yarn city-timetables --status` prints the full table at any time.
- **Updating.** `yarn city-timetables --update` rebuilds only the feeds the check calls **new** or **failed** (a feed that is merely expiring: add `--city Piran`, which looks again and rebuilds only if the operator changed something), runs the `test_citytt*` tests, commits the changed folders locally (`City timetables: Piran rebuilt (date)`) and uploads them with `yarn server:update --city Piran` (`--no-upload` stops after the commit). A feed whose build fails keeps its last good folder, says why, and is neither committed nor uploaded; failing tests stop the run before any commit. Marprom takes about 35 minutes (one request a second to vozniredi.marprom.si).
- **The upload.** `yarn server:update --city [feed…]` (its own run: no Arriva, no SŽ) copies the folders that differ with the same `rsync` options as `push.sh` (root-owned, nothing else touched), then makes the API swap its workers (`systemctl kill -s HUP`, nobody is dropped) and runs the check once so the warning clears. The collector is not restarted: it picks the folders up with its own cache of at most 6 hours, and a restart would drop its delay memory. It warns about folders with uncommitted changes. Uploading never replaces `yarn server:push`; the next deploy carries the same folders.
- **Limit.** Marprom's line pages are templated, so the check sees a change only in `gtfs.zip`; a change on the line pages shows up at the next build.

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
| `server/maintenance.sh` | Maintenance flag for `/api/v1/health` during a deploy |
| `server/keep-stats.sh` | Keeps the delay statistics through each deploy (copy before migrations, put back what went missing) |
| `server/{manage,status,backup,restore,watchdog,egress-guard}.sh` | `prestop-manage`, `prestop-status`, backups, restore, health watchdog, outbound-data cap |
| `oci/guardrails.sh`, `oci/audit.sh` | Quotas + budget alert on the Oracle account; read-only check that nothing is billable |
| `oci/launch-retry.sh`, `oci/lib.sh` | Create the A1 instance when capacity frees up; shared settings (the free limits) |
| `server/prestop.env.template` | Becomes `/etc/prestop/prestop.env` |
| `django/prestop_production.py` | Production settings on top of `ojpp_core.settings_prestop` |
| `systemd/` | Services and timers |
| `caddy/Caddyfile`, `postgres/prestop.conf` | Web server; PostgreSQL tuning (3 GB buffer cache, prewarm) |

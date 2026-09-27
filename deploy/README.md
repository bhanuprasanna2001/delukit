# Deploy DELU without a paid server

This deployment keeps the existing Parquet files, MLflow registry, Dagster state, and app SQLite database on one persistent VM. Use an Oracle Cloud Always Free Ampere A1 VM with 2 OCPUs and 12 GB RAM in your home region. Oracle currently includes 200 GB of combined boot and block storage. Capacity is not guaranteed, and Oracle can reclaim an idle instance. Check the [current Always Free limits](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm) before creating it.

Oracle says most signups require a card for identity verification, with no charge unless you upgrade the account. Do not create a paid resource using trial credits if the service must survive the trial on a zero-cost account. See the [Free Tier account terms](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier.htm).

The public address can be a free [DuckDNS](https://www.duckdns.org/about.jsp) name. Caddy obtains HTTPS certificates when the name points to the VM and ports 80 and 443 are reachable. The Dagster UI binds to the VM's loopback address; only DELU is public.

## Prepare the VM

1. Create an Always Free A1 VM in your Oracle home region. Select 2 OCPUs, 12 GB RAM, and a 100 GB Always Free eligible boot volume if the rest of your free block-storage allowance is unused. Keep the account on its free tier.
2. Assign a public IPv4 address. Allow inbound TCP 22 from your IP and TCP 80 and 443 from the internet in the OCI network rules and the host firewall. Do not open 3000 or 8000.
3. Create a DuckDNS name pointing to that address. Set `DELU_DOMAIN` to the complete name, such as `forecast.duckdns.org`.
4. Install [Docker Engine and the Compose plugin](https://docs.docker.com/engine/install/ubuntu/) on the VM. Use an Arm64 Ubuntu image. Check that `docker compose version` works.
5. Clone this repository on the VM. Copy `.env.example` to `.env`, set `ENTSOE_API_KEY`, `DELU_DOMAIN`, and working SMTP credentials. A [Brevo Free account](https://help.brevo.com/hc/en-us/articles/208580669-FAQs-What-are-the-limits-of-the-Free-plan) currently includes transactional mail under a daily quota. With a sender approved by Brevo, use `SMTP_HOST=smtp-relay.brevo.com`, `SMTP_PORT=587`, your Brevo SMTP login in `SMTP_USER`, its generated SMTP key in `SMTP_PASS`, and the approved address in `SMTP_FROM`. An existing Resend account with an approved sending domain also works through `RESEND_API_KEY` and `RESEND_FROM`. Set `DELUKIT_ALERT_WEBHOOK` if you want Slack notices. Keep `.env` private with `chmod 600 .env`.

The public web app refuses to start without configured mail. This prevents verification links from appearing in container logs. A free DuckDNS name supplies the web hostname, but it does not by itself approve an email sender. Test delivery to an external inbox before sharing the URL; a configured SMTP host can still reject mail at runtime.

The model registry copied from a Docker run contains container paths such as `/app/data/mlflow`. Keep the `data/` bind mount at `/app/data` on the VM. A gate checks for a usable registered XGBoost model. If it cannot load one, it can fit an unregistered gate-local XGBoost model or use a simpler fallback, and records an alert. No scheduled gate promotes a model. Allow extra time and CPU for this case. Automatic retraining and promotion are deliberately absent until source revisions and forward holdout evidence support a safe comparison.

## Move the current state

On the VM, create the writable bind mounts for the containers' UID 1000.

```bash
mkdir -p data/.dagster delu/data
sudo chown -R 1000:1000 data delu/data
```

Copy the current `data/` and `delu/data/` from your laptop to those directories with `rsync -a --partial`. Stop the laptop's Compose stack before copying SQLite files. From the repository root on the laptop, with your actual SSH host and repo path:

```bash
rsync -a --partial data/ ubuntu@YOUR_VM_IP:/path/to/delukit/data/
rsync -a --partial delu/data/ ubuntu@YOUR_VM_IP:/path/to/delukit/delu/data/
```

Do not copy `docs/` or commit credentials. The current data directory is about 3.6 GB, so allow time for the first transfer. Run `sudo chown -R 1000:1000 data delu/data` again on the VM after the copy.

Start the stack from the repository root.

```bash
docker compose -f compose.prod.yaml config --quiet
docker compose -f compose.prod.yaml up -d --build
docker compose -f compose.prod.yaml ps
deploy/smoke.sh forecast.duckdns.org
```

When migrating an existing Dagster instance, saved STOPPED states can override code defaults. Start and inspect the two schedules and two sensors explicitly:

```bash
docker compose -f compose.prod.yaml exec -T delukit-daemon dagster schedule start -m delukit.dagster_app.definitions gate_schedule
docker compose -f compose.prod.yaml exec -T delukit-daemon dagster schedule start -m delukit.dagster_app.definitions scores_schedule
docker compose -f compose.prod.yaml exec -T delukit-daemon dagster sensor start -m delukit.dagster_app.definitions ops_failure_alert
docker compose -f compose.prod.yaml exec -T delukit-daemon dagster sensor start -m delukit.dagster_app.definitions gate_health
docker compose -f compose.prod.yaml exec -T delukit-daemon dagster schedule list -m delukit.dagster_app.definitions
docker compose -f compose.prod.yaml exec -T delukit-daemon dagster sensor list -m delukit.dagster_app.definitions
```

The health endpoint confirms that the API process responds. Check `/api/options` for the available forecast dates and inspect `data/forecasts/YYYY-MM-DD/0530.json` or `1130.json` after the next scheduled gate. A manifest appears only after all 12 products pass validation. The first gate may take longer on 2 OCPUs; measure the run duration on the VM before relying on the scheduled issue times.

To open Dagster privately, forward its loopback port over SSH and visit `http://localhost:3000`.

```bash
ssh -L 3000:127.0.0.1:3000 ubuntu@YOUR_VM_IP
```

## Back up off the VM

OCI Always Free currently includes 20 GB of Object Storage. Configure an [rclone crypt remote](https://rclone.org/crypt/) backed by an OCI Object Storage bucket. The crypt remote keeps the archive encrypted before upload. Install `rclone` on the VM and pass the crypt remote path to the backup script.

```bash
deploy/backup.sh oci-crypt:delukit
```

The script stops the writers, archives `data/` and `delu/data/`, restarts the services, and uploads one of three rotating slots. It rejects an archive over 6 GiB so three slots remain within the 20 GB storage allowance. Run it weekly with a host timer or cron. It records a backup failure in the alert store and retries Slack delivery through the pipeline container.

For example, add this to the VM user's crontab after testing one manual backup, replacing the repo path and remote:

```cron
30 1 * * 0 /path/to/delukit/deploy/backup.sh oci-crypt:delukit >> /path/to/delukit/backups/backup.log 2>&1
```

To check a backup, download the archive and its `.sha256` file to an empty directory, run `sha256sum -c slot-N.tar.gz.sha256`, and list the archive with `tar -tzf`. Test a full restore into a separate directory before trusting the backup. Keep a private copy of `.env` and the rclone crypt configuration elsewhere; the archive contains runtime state only. The three slots replace the oldest copy; keep an independent copy if you need a longer retention period.

## Limits of this free deployment

The VM, disk, DNS, and email provider all have availability and quota limits. This is a remotely hosted service with no infrastructure bill while it stays inside the free allowances, not a guaranteed uptime service. Oracle account creation and DNS setup require your own account access, so running these repository commands alone cannot provision the VM.

The current historical ENTSO-E and SMARD files retain the latest fetched revision. Historical replay before immutable receipts exist cannot prove which value was visible at an old issue cutoff. Do not use those backtests as strict point-in-time model-promotion evidence. Score drift uses a provisional 1.5× threshold and currently measures only error drift, not feature-distribution drift. Open-Meteo's [free API terms](https://open-meteo.com/en/terms) cover non-commercial use; confirm your public use fits them before enabling a commercial product.

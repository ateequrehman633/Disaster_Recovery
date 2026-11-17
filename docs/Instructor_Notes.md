# Instructor Notes — Correctness and Risk Controls

## Teach the difference between five mechanisms

**1. Backup** — A restorable data copy (point-in-time logical app snapshot in this lab). The snapshot must be stored off-host to survive host loss. The lab app's gzip JSON backup is intentionally limited to three demo tables and does not include PostgreSQL roles, extensions, physical WAL or managed PITR.

**2. HA** — Huawei RDS primary/standby instances are a *single managed HA deployment*. The standby is created as part of the HA product and is managed by RDS. Separate independent RDS connection strings alone do not provide synchronous replication.

**3. Read replica** — A replica scales reads; do not assume it is a safe writeable failover target. Its replay delay can be unknown if the database has not recently replayed a transaction.

**4. Disaster recovery** — Independent destination may be synchronized by DRS after verifying supported engine topology and privileges. DRS is not a synonym for backup and cannot be safely “promoted” from this classroom GUI.

**5. Application failover** — The GUI changes its active database connection **after** backup verification (local) or manual cloud cutover confirmation (external). This does not change DNS, cloud database HA role, or network routing.

## What fails during an ECS loss?

On one ECS, the frontend, web backend, Prometheus, Redis and local databases all fail together. No single-host Docker stack can truthfully demonstrate ECS high availability. Use a second ECS, shared/replicated durable storage, proper load balancer/health checks and infrastructure automation for the next advanced exercise.

## Local outage controls

The “Simulate outage” button *only prevents store access through the web app's primary connection* and starts a recovery clock. PostgreSQL is still running. “Enable local auto-failover” begins guarded endpoint switching on the background loop, at roughly 20-second polling intervals, only if a verified local restore exists. Failure to verify means no switch.

## Metric interpretation

- `cloudlab_last_rto_seconds`: measured wall-clock from simulation start to successful app target switch.
- `cloudlab_last_backup_age_at_failure_seconds`: elapsed time between snapshot creation and incident; an **exposure-window indicator**, not exact transaction loss.
- `cloudlab_recovery_verified`: 1 match, 0 mismatch, -1 unknown. It covers only the demo products/orders/items tables and should not be used as a generic DRS assurance.
- `cloudlab_db_up{target=...}`: app connection status. Exporter `pg_up` is for local PostgreSQL only.
- `redis_up` and `node_*` are from local Redis and host exporters; these do not magically monitor Huawei Cloud managed resources.

## Suggested 80-minute pacing

- 0–10 min: architecture, deploy, identify roles
- 10–25 min: SQL store demo; baseline dashboard
- 25–40 min: snapshot, intentional RPO mismatch
- 40–60 min: verified restore, simulate outage, guarded switch
- 60–70 min: Grafana dashboard evidence
- 70–80 min: group discussion and 80-mark evaluation

## Common failure cases

- No outbound registry access: Docker/PyPI image builds fail; cannot be fixed by changing the app source. Enable appropriate outbound Internet and DNS.
- 1/2 GB ECS: memory exhaustion pulling Grafana/Prometheus/Postgres concurrently. Upgrade or stop optional exporters.
- Cloud RDS timeout: check VPC/subnet/security groups/DNS and PG TLS requirements.
- `permission denied to create database`: RDS role lacks `CREATEDB`; instructor creates the DB in RDS console and students run table initialization.
- PostgreSQL replica read-only: expected; never run CREATE/INSERT there.
- DRS appears `Not verified`: by design. Check DRS task state in provider console manually.
- Different fingerprints after restore: new writes after snapshot, altered row values, wrong database target, or mismatched backup.

## Security

Generate separate secrets for each student ECS. Do not reuse `.env` across cohorts or use any production credentials. ECS Security Group inbound 22/8080/3000 **only from class IP ranges**. Use HTTPS reverse proxy for persistent internet-accessible deployments. Rotate credentials after the exercise.

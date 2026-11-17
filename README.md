# CloudLab Recovery · Day 48 · Lab 20

**Backup and Recovery Planning for Critical Systems** — A hands-on Ubuntu/Huawei ECS Docker practical with a secure web lab, a working PostgreSQL-backed e-commerce storefront, two local PostgreSQL servers, Redis, Prometheus, Grafana, exporters, logical backup/restore, data-integrity verification, and guarded local application-level failover.

## 1. What the instructor is deploying

| Component | Docker service | Function |
| --- | --- | --- |
| Recovery Mission Control | `app` | Dark-mode GUI, guided steps, mini store, integration settings, backup/restore, failure drills, Prometheus metrics |
| Local primary PostgreSQL 16 | `pg-primary` | Active test database, seeded store |
| Local recovery PostgreSQL 16 | `pg-recovery` | **Independent restore destination**; not a streaming standby |
| Local Redis 7.4 | `redis` | Store catalog caching; optional external DCS integration |
| Prometheus 3 | `prometheus` | Real metrics, 15-second scrapes, lab alert rules |
| Grafana 11 | `grafana` | 4 automatically provisioned dashboards, app/DB/Redis/ECS host graphs |
| Postgres exporter × 2 | `pg-exporter-*` | Observability for bundled local Postgres engines |
| Redis exporter | `redis-exporter` | Observability for bundled local Redis |
| Node exporter | `node-exporter` | ECS Docker host CPU, memory, filesystem/network metrics |

> **Reality check:** Two separate PostgreSQL endpoints do **not** automatically have streaming replication. Locally we demonstrate recovery through a logical backup, restore, checksum validation and guarded **application endpoint switch**, not native RDS automatic failover. Huawei RDS primary/standby HA and DRS sync tasks must be provisioned and operated within Huawei Cloud. A failed ECS cannot automatically recover this single-host stack; actual ECS HA requires another ECS, image/config replication, load balancer and independent storage.

## 2. Ubuntu ECS prerequisites

- Ubuntu **22.04 or 24.04**, 64-bit x86/ARM, **4 vCPU and 8 GB RAM recommended**, 25 GB+ free disk. A 2 vCPU/4 GB ECS may run with slower image pulls and Grafana/DB memory pressure.
- Sudo privileges, stable public outbound HTTPS access to Docker/Ubuntu registries and Python package repository, correct DNS.
- Huawei ECS Security Group inbound: **TCP 22 from your IP; TCP 8080 and TCP 3000 only from your IP or lab network**. Do not open PostgreSQL 5432, Redis 6379, exporters, or Prometheus to the public.
- Optional RDS PostgreSQL (primary/DR/read-only endpoint) and DCS Redis accessible over approved VPC peering/routes and security groups. These services cost money when provisioned on Huawei Cloud.

### Windows PowerShell: upload

```powershell
scp .\Day48_CloudRecovery_Lab.zip ubuntu@YOUR_ECS_PUBLIC_IP:~/
ssh ubuntu@YOUR_ECS_PUBLIC_IP
```

### Ubuntu: extract and deploy

```bash
sudo apt-get update && sudo apt-get install -y unzip
unzip Day48_CloudRecovery_Lab.zip
cd Day48_CloudRecovery_Lab
sudo bash deploy.sh
```

**`sudo bash deploy.sh` is the one-command application deployment.** It installs Docker Engine and the Compose plugin if missing, creates unique passwords, pulls/builds 10 services, starts them, checks the web app, and prints login credentials. Re-running it is idempotent; it preserves `.env` and named-volume data.

### Open the GUI

- Student GUI: `http://YOUR_ECS_PUBLIC_IP:8080`
- Grafana: `http://YOUR_ECS_PUBLIC_IP:3000`
- Credentials: printed on completion and in `.lab-credentials` (mode 600, root-readable).
- Prometheus: bound to ECS **localhost:9090**, access via an SSH port forward if desired.

This lab intentionally uses HTTP on 8080/3000 to minimize setup. **Do not expose credential entry to the public internet.** For a shared long-lived deployment, add an HTTPS reverse proxy with an approved certificate and strict network restrictions.

## 3. Student lab exercises (ordered)

1. Sign in to Mission Control. Check availability, query latency, current active DB, Grafana accessibility.
2. Visit **RDS & Databases**. Explore built-in primary and recovery PostgreSQL. `Create tables + seed` is idempotent.
3. Visit **E-Commerce Store** and create **at least three** transactions. Confirm stock decreases, order IDs increment, order totals persist in SQL.
4. Visit **Backup & Restore**, create a logical backup, and record the timestamp, byte size and 16-character checksum prefix.
5. Create one additional order, then restore the earlier backup into the **inactive** local PostgreSQL database. Click **Verify DB consistency**. The digests will differ: intentional point-in-time data loss/RPO lesson.
6. Create a **new** backup of the current active primary and restore it to inactive recovery. Click **Verify** again. Both protected datasets should now match.
7. Optionally enable **Local guarded auto-failover** under Failover. It checks for the simulated outage in the background; it can only switch to a previously restored/verified local target.
8. Use **Simulate outage** to block this application's normal access to local primary (no real ECS or PostgreSQL resource is stopped). Either wait for guarded auto-switch or use manual **Switch route** with confirmation `SWITCH`.
9. Place a purchase order against the recovered database; inspect metrics in Grafana. RTO measures simulated outage → application route recovery. RPO exposure is the age of the last backup when the outage was triggered.
10. For cloud extension, configure a private **Huawei RDS PostgreSQL main** endpoint; create lab database with `CREATE` if the account has `CREATEDB` privilege; then initialize lab tables with `INIT`. Optionally provide a **different independently provisioned DR RDS** endpoint, plus a read-replica endpoint.
11. Configure optional **Huawei DCS Redis** host, authentication, TLS and CA filename; test connection and generate store cache hits. Never paste production secrets into a classroom VM.
12. Configure **Huawei DRS** replication **in Huawei Cloud Console**, attach only a DRS task reference in the app, validate the managed synchronization task in the cloud UI, and perform provider-side promotion before any application cutover. Huawei-managed RDS HA is a separate architecture/operation.

## 4. Cloud integration boundaries

**RDS Primary:** App connects with TLS, and can test SQL, optionally create a database, create app tables/seed, write orders (when active), and take limited app-level logical snapshots. This does **not** enable RDS automatic backups or native failover.

**DR RDS:** App tests connectivity, reports `pg_is_in_recovery()` / read-only mode and can compare protected app-table SHA-256 digests. **It will never restore over external RDS.** For a manual app endpoint switch to external DR, verify the target is writable, refresh both digests within two minutes, perform provider-side DRS cutover first, and explicitly type `DRS CUTOVER`. No claim is made that this validates every DRS data object or guarantees zero loss; table-level digests only cover the demo store's three tables.

**Read replica:** Optional separate endpoint used for SELECT-only operations. Grafana receives app-level replica connection/latency metrics when configured; a replay timestamp may be absent on idle PostgreSQL replicas. The app cannot create a managed read replica or read its cloud configuration.

**DCS Redis:** Optional external encrypted/private cache; internal Redis is available by default. DCS TLS options depend on instance/version. Check official documentation before enabling TLS settings or exposing an instance.

**DRS:** The lab **does not** create, change, stop or promote a Huawei DRS task, or fetch task status via Huawei IAM API. DRS is operator-managed in the cloud console; app's task reference is informational only. Cloud DRS supports specific PG-to-PG synchronization topologies/versions; verify your region/engine combination before purchasing or deploying.

## 5. Grafana dashboards

| Dashboard name | UID | Metrics illustrated |
| --- | --- | --- |
| CloudLab \| Recovery Mission Control | `cloudlab-command` | Active DB, primary/DR connectivity, RTO, RPO exposure, backup age, simulated outage, recovery checks |
| CloudLab \| PostgreSQL & Recovery | `cloudlab-postgres` | Local exporters, orders/products/item rows, connection count, transaction commits, deadlocks, query latency |
| CloudLab \| E-Commerce & Redis | `cloudlab-store` | Store orders/revenue, HTTP throughput/p95, 5xx, app cache hit/miss, local Redis memory/clients/commands |
| CloudLab \| ECS Host Telemetry | `cloudlab-host` | ECS CPU cores, memory, disk, network, exporter scrape health |

**No fabricated time series.** Some graphs remain blank until enough samples exist, an optional integration is configured, or relevant events occur. Host dashboards measure the **Docker host** using node exporter. PostgreSQL/Redis exporters observe **bundled local** services only; external Huawei RDS/DCS CPU/RAM/IOPS require Cloud Eye or additional authenticated collectors.

## 6. Troubleshooting/operations

```bash
sudo docker compose ps
sudo docker compose logs --tail=100 app
sudo docker compose logs --tail=100 grafana
sudo docker compose logs --tail=100 pg-primary
sudo docker compose restart app
sudo docker compose down                    # stops containers, keeps volumes
sudo docker compose up -d                   # restarts all persisted services
curl -fsS http://localhost:8080/healthz
sudo cat .lab-credentials                   # deployment secrets
```

**DO NOT execute `docker compose down -v`** unless intentionally destroying all demonstration databases, Grafana state, audit history and backups.

For critical-system protection, place lab backups on an external independently retained storage target (e.g., OBS with an appropriate backup policy) instead of trusting the same ECS disk; this app saves its logical backups in the local Docker volume solely for teaching.

## 7. Documentation and diagrams

- `docs/Student_Lab_Guide.md`: guided steps, learning outcomes, assignment/rubric
- `docs/Instructor_Notes.md`: RTO/RPO evaluation, cloud vs simulation, safety checks
- `docs/Cloud_Integration_Worksheet.md`: RDS/DCS/DRS fields, connectivity validation
- `docs/images/*.png`: three **conceptual** visuals (some generated mockup labels/metrics are illustrative, not measured from the software)
- `monitoring/grafana/dashboards/`: four pre-provisioned dashboard JSON files

## 8. Authoritative vendor references (checked November 2026)

- [Huawei RDS PostgreSQL primary/standby HA](https://support.huaweicloud.com/intl/en-us/productdesc-rds-pg/rds_01_0036.html)
- [Huawei DRS PostgreSQL to PostgreSQL real-time synchronization](https://support.huaweicloud.com/intl/en-us/realtimesyn-drs/drs_04_0107.html)
- [Huawei DRS overview](https://support.huaweicloud.com/intl/en-us/productdesc-drs/drs_01_0302.html)
- [Huawei DCS Redis TLS support](https://support.huaweicloud.com/intl/en-us/usermanual-dcs/dcs-ug-023129.html)
- [Huawei DCS connectivity requirements](https://support.huaweicloud.com/eu/usermanual-dcs/dcs-ug-0312007.html)

## 9. Validation limitations

Source code, JavaScript syntax, YAML structure, and dashboard JSON were statically checked during packaging. This creation environment does **not** have a Docker engine or access to Docker Hub/PyPI; a complete ECS container build and live Huawei Cloud integration test could **not** be performed here. Review logs and test with a non-production ECS before delivering an assessed session. No guarantee of error-free deployment on every region/network configuration is made.

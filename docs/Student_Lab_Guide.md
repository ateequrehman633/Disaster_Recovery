# Student Lab 20 — Backup, Restore & Failover

**Day 48** · Backup and Recovery Planning for Critical Systems  
**Recommended duration:** 80–100 minutes · **Marks:** 80

## Objectives

- Design a backup policy (frequency, RPO, RTO, retention, restore validation).
- Understand recovery testing, controlled application connection switching, and the difference between redundancy and recoverability.
- Configure demo e-commerce PostgreSQL, create real orders, and verify inventory changes.
- Generate, restore, and SHA-256 verify consistent logical backup snapshots.
- Create a software-only failure condition and measure application RTO and backup-age RPO exposure.
- Observe application, database, cache, and ECS host metrics with Prometheus + Grafana.
- Know the responsibilities of Huawei Cloud RDS HA, DRS sync, RDS read replicas, and DCS Redis.

## Lab context

A **single Ubuntu ECS** hosts the practical. You get two independent local PostgreSQL databases. You will intentionally restore snapshots to a secondary local DB; this is a **recovery site**, not a native RDS HA standby. The e-commerce application changes its SQL destination only after safety checks.

## Activities with evidence

| # | Activity | Evidence |
|---|---|---|
| 1 | Deploy the ZIP with `sudo bash deploy.sh` | `docker compose ps` shows 10 services |
| 2 | Open web console and Grafana | Both pages load, login works |
| 3 | Initialize 3 tables / seed 8 products | Database page row counts |
| 4 | Create 3+ orders | Order IDs and stock decrement |
| 5 | Capture snapshot A | Backup filename, timestamp, SHA-256 prefix |
| 6 | Create another order and restore snapshot A to inactive local target | Mismatched order counts and fingerprint demonstrate possible RPO loss |
| 7 | Capture snapshot B and restore to inactive target | SHA-256 comparison matches |
| 8 | Set RTO target=120 sec and RPO target=300 sec (exercise thresholds) | Written plan |
| 9 | Simulate primary outage and recover through manual or guarded auto switch | Audit trail + actual measured app RTO |
| 10 | Place an order on recovered target | New order stored under recovered database |
| 11 | Observe 4 Grafana dashboards | Screenshots of real app/database/cache/host metrics |
| 12 | Complete conclusion | Whether RTO/RPO targets were met and what remains a single point of failure |

### Required operating commands

```bash
# On your Windows computer
scp Day48_CloudRecovery_Lab.zip ubuntu@YOUR_ECS_IP:~/
ssh ubuntu@YOUR_ECS_IP

# On ECS Ubuntu
sudo apt-get update && sudo apt-get install -y unzip
unzip Day48_CloudRecovery_Lab.zip
cd Day48_CloudRecovery_Lab
sudo bash deploy.sh
sudo docker compose ps
```

Visit `http://ECS_IP:8080` and `http://ECS_IP:3000`, using separate passwords printed by installer. Restrict ECS Security Group TCP 8080/3000 to your own IP.

### Guided demo A: data-loss window

1. Record order count before snapshot. Create backup A.
2. Place one more order on the primary database.
3. Restore backup A to inactive local DR.
4. Click **Verify DB consistency**. It should **NOT** match if orders/stock differ.
5. Compare the order count from each database in the dashboard. Note the new order would be missing if cut over to this old restore.
6. Explain why taking backups is not the same as testing recovery.

### Guided demo B: recovery with a verified checkpoint

1. Create backup B after all intended transactions and restore it to the inactive DB.
2. Verify checksums match. Optionally turn on **Local guarded auto-failover**.
3. Simulate the primary outage. Auto mode checks every 20 seconds; manual mode requires a route switch.
4. Confirm active target becomes `dr`, then place another order.
5. In Grafana Mission Control, record `cloudlab_last_rto_seconds`, outage flag history and backup exposure at failure.

### Written questions

1. Can a backup on the same ECS disk protect against the loss of that ECS? Explain.
2. How do two *independent* RDS instances differ from a managed RDS primary/standby HA instance?
3. What is the difference between a read replica and a DRS recovery destination?
4. Why does a perfect SQL connection test not prove the DR database is synchronized?
5. What is the measured RTO and the backup-age exposure window? What actual data was lost when restoring snapshot A?
6. How would you redesign this lab for a true ECS outage using two ECS instances, independent shared storage, and load balancing?

## Assessment (80 marks)

| Category | Marks |
|---|---:|
| ECS deployment, service health, network hygiene | 10 |
| PostgreSQL tables and working store transactions | 15 |
| Validated backups, restore safety, snapshot consistency | 20 |
| Failover drill, RTO/RPO analysis and accurate conclusions | 20 |
| Grafana screenshots, Prometheus metrics and explanation | 15 |
| **Total** | **80** |

**Important:** Do not stop or delete real Huawei RDS/ECS resources as part of a classroom drill. Actual cloud HA, read replica provisioning, DRS and point-in-time restore are instructor-managed optional extensions, with separate costs.

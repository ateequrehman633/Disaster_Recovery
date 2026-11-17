# Cloud Integration Worksheet · Huawei Cloud

## RDS PostgreSQL (primary)

- Instance ID, region, VPC/subnet, availability zone:
- Private hostname/IP and port 5432:
- Database username (dedicated classroom DB account; grant only needed database privileges):
- TLS mode (`require` minimum; CA certificate + `verify-full` preferred):
- Lab database name (example: `cloudlab`):
- Network test result / connectivity latency:
- Native RDS automatic backups enabled? Check **RDS Backups & Restorations** in console (app backup does not configure this).

## RDS HA and recovery topology

- Main RDS: Single or Primary/Standby HA instance?
- Secondary DR RDS: A second independent DB or part of managed HA?
- If DRS enabled, task type and supported engine/version pair:
- DRS source/target connectivity + permissions checks passed?
- Full+Incremental sync configured where supported?
- DRS task status and lag manually inspected in Huawei Console?
- Planned external cutover strategy, write freeze/consistency validation and rollback plan?

## Read replica

- Replica private hostname/IP:
- Read-only check:
- SELECT of products in web UI succeeded?
- Replay delay may be unknown for idle PostgreSQL; do not turn a missing metric into zero.

## Huawei DCS Redis

- Instance version and supported TLS mode:
- Private IP/port and required whitelist:
- Redis username, auth and DB number:
- CA certificate filename (copy to package `certs/` before deployment):
- Cache test from web app:

## Cloud documentation

- RDS HA: https://support.huaweicloud.com/intl/en-us/productdesc-rds-pg/rds_01_0036.html
- PostgreSQL DRS: https://support.huaweicloud.com/intl/en-us/realtimesyn-drs/drs_04_0107.html
- DCS TLS: https://support.huaweicloud.com/intl/en-us/usermanual-dcs/dcs-ug-023129.html
- DCS connectivity: https://support.huaweicloud.com/eu/usermanual-dcs/dcs-ug-0312007.html

**Reminder:** The web app's external DR connection/switch is *not* an RDS HA or DRS control-plane API. Configure and test the cloud-side failover workflow separately. Never restore over production database data in a classroom exercise.

#!/usr/bin/env python3
"""Creates provisioned Grafana dashboards, using actual recorded metrics only."""
import json
from pathlib import Path
OUTPUT=Path(__file__).resolve().parent/'grafana/dashboards'
OUTPUT.mkdir(parents=True, exist_ok=True)
DS={'type':'prometheus','uid':'cloudlab-prom'}

def thresholds(unit):
    return {'mode':'absolute','steps':[{'color':'green','value':None}]}

def panel(title,q,x,y,w=6,h=8,kind='timeseries',unit='short',legend='{{target}}',description=''):
    idx=panel.counter
    panel.counter+=1
    body={
      'id':idx,'type':kind,'title':title,'description':description,'gridPos':{'x':x,'y':y,'w':w,'h':h},
      'datasource':DS,'targets':[{'expr':q,'legendFormat':legend,'refId':'A'}],
      'fieldConfig':{'defaults':{'unit':unit,'decimals':2,'thresholds':thresholds(unit),
                                  'color':{'mode':'palette-classic'}},'overrides':[]},
      'options':({'legend':{'displayMode':'table','placement':'bottom','calcs':['lastNotNull']},
                  'tooltip':{'mode':'multi','sort':'desc'},'lineWidth':2,'fillOpacity':20,
                  'showPoints':'never','gradientMode':'opacity'} if kind=='timeseries' else
                  {'reduceOptions':{'values':False,'calcs':['lastNotNull'],'fields':''},'orientation':'auto',
                   'textMode':'auto','colorMode':'value','graphMode':'area','justifyMode':'auto'} if kind=='stat' else {})}
    return body
panel.counter=1

def ds(title, uid, tags,panels):
    board={'id':None,'uid':uid,'title':'CloudLab | '+title,'tags':['Day 48','Lab 20','Backup Recovery',*tags],
           'timezone':'browser','schemaVersion':40,'version':1,'refresh':'15s','editable':False,
           'time':{'from':'now-30m','to':'now'},'timepicker':{},'annotations':{'list':[]},
           'panels':panels,'templating':{'list':[]},'graphTooltip':1,
           'description':'Prometheus-backed training dashboard: only observed samples, no synthetic values.'}
    (OUTPUT/f'{uid}.json').write_text(json.dumps(board,indent=2))

p=[]
p.append(panel('Active app database','cloudlab_active_target == 1',0,0,4,5,'stat','none','{{target}}', '1 indicates current application route'))
p.append(panel('Primary DB availability','cloudlab_db_up{target="primary"}',4,0,4,5,'stat','none','primary'))
p.append(panel('Recovery DB availability','cloudlab_db_up{target="dr"}',8,0,4,5,'stat','none','DR'))
p.append(panel('Redis availability','cloudlab_cache_up',12,0,4,5,'stat','none','Redis'))
p.append(panel('Last measured RTO','cloudlab_last_rto_seconds',16,0,4,5,'stat','s','Recovery time'))
p.append(panel('RPO backup age at failure','cloudlab_last_backup_age_at_failure_seconds',20,0,4,5,'stat','s','Backup exposure'))
p.append(panel('Service availability over time','cloudlab_db_up',0,5,12,8,legend='{{target}}'))
p.append(panel('Database connection latency','cloudlab_db_latency_seconds * 1000',12,5,12,8,unit='ms',legend='{{target}}'))
p.append(panel('Backup age (live)','time() - cloudlab_last_backup_timestamp_seconds',0,13,8,8,unit='s',legend='Backup age'))
p.append(panel('Application primary outage simulation','cloudlab_simulated_primary_outage',8,13,8,8,legend='Simulation 1/0'))
p.append(panel('Data integrity verification','cloudlab_recovery_verified',16,13,8,8,legend='1 match / 0 mismatch / -1 unknown'))
p.append(panel('Backup & recovery actions / 5m','sum by (result) (increase(cloudlab_backups_total[5m])) or vector(0)',0,21,8,8,legend='{{result}}'))
p.append(panel('Endpoint switch actions / 5m','sum by (result) (increase(cloudlab_switches_total[5m])) or vector(0)',8,21,8,8,legend='{{result}}'))
p.append(panel('HTTP requests per second','sum by (status) (rate(cloudlab_http_requests_total[5m]))',16,21,8,8,unit='reqps',legend='HTTP {{status}}'))
ds('Recovery Mission Control','cloudlab-command',['RTO','RPO','Failover'],p)

p=[]
p.append(panel('PostgreSQL main exporter up','pg_up{job="postgres-primary"}',0,0,6,5,'stat','none','Main'))
p.append(panel('PostgreSQL recovery exporter up','pg_up{job="postgres-recovery"}',6,0,6,5,'stat','none','Recovery'))
p.append(panel('Read replica observed replay delay','cloudlab_replica_replay_delay_seconds',12,0,6,5,'stat','s','{{target}}','Absent if not configured/no replay timestamp'))
p.append(panel('Read-only flag / target','cloudlab_db_read_only',18,0,6,5,'stat','none','{{target}}'))
p.append(panel('E-commerce product count','cloudlab_db_rows{table="products"}',0,5,8,8,legend='{{target}}'))
p.append(panel('E-commerce orders count','cloudlab_db_rows{table="orders"}',8,5,8,8,legend='{{target}}'))
p.append(panel('E-commerce order item count','cloudlab_db_rows{table="order_items"}',16,5,8,8,legend='{{target}}'))
p.append(panel('Database connection count','pg_stat_database_numbackends{datname="cloudlab"}',0,13,12,8,legend='{{job}}'))
p.append(panel('Committed transactions per second','sum by (job)(rate(pg_stat_database_xact_commit{datname="cloudlab"}[5m]))',12,13,12,8,unit='ops',legend='{{job}}'))
p.append(panel('Database deadlocks total','pg_stat_database_deadlocks{datname="cloudlab"}',0,21,8,8,legend='{{job}}'))
p.append(panel('PostgreSQL tuples inserted / 5m','sum by(job) (increase(pg_stat_database_tup_inserted{datname="cloudlab"}[5m]))',8,21,8,8,legend='{{job}}'))
p.append(panel('Application database probe times','cloudlab_db_latency_seconds * 1000',16,21,8,8,unit='ms',legend='{{target}}'))
ds('PostgreSQL & Recovery','cloudlab-postgres',['PostgreSQL','RDS'],p)

p=[]
p.append(panel('Store orders created','sum(cloudlab_orders_created_total) or vector(0)',0,0,6,5,'stat','short','Orders'))
p.append(panel('Store revenue (demo $)','sum(cloudlab_sales_amount_total) or vector(0)',6,0,6,5,'stat','currencyUSD','Revenue'))
p.append(panel('Redis cache connected','cloudlab_cache_up',12,0,6,5,'stat','none','Cache'))
p.append(panel('HTTP 5xx error rate','sum(rate(cloudlab_http_requests_total{status=~"5.."}[5m])) or vector(0)',18,0,6,5,'stat','reqps','Errors/s'))
p.append(panel('HTTP request throughput','sum by (route) (rate(cloudlab_http_requests_total[5m]))',0,5,12,8,unit='reqps',legend='{{route}}'))
p.append(panel('HTTP p95 request latency','histogram_quantile(0.95,sum by(le,route)(rate(cloudlab_http_request_duration_seconds_bucket[5m]))) * 1000',12,5,12,8,unit='ms',legend='{{route}}'))
p.append(panel('Store orders created per 5m','sum by(target)(increase(cloudlab_orders_created_total[5m]))',0,13,12,8,legend='{{target}}'))
p.append(panel('Cache hits vs misses / sec','sum(rate(cloudlab_cache_hits_total[5m])) or vector(0)',12,13,6,8,legend='Hits/s'))
p.append(panel('Cache misses / sec','sum(rate(cloudlab_cache_misses_total[5m])) or vector(0)',18,13,6,8,legend='Misses/s'))
p.append(panel('Redis used memory','redis_memory_used_bytes{job="redis-local"}',0,21,8,8,unit='bytes',legend='Redis'))
p.append(panel('Redis connected clients','redis_connected_clients{job="redis-local"}',8,21,8,8,legend='Redis'))
p.append(panel('Redis commands/second','rate(redis_commands_processed_total{job="redis-local"}[5m])',16,21,8,8,unit='ops',legend='Redis'))
ds('E-Commerce & Redis','cloudlab-store',['E-Commerce','Redis'],p)

p=[]
p.append(panel('Host CPU utilization','(1-avg(rate(node_cpu_seconds_total{mode="idle"}[5m]))) * 100',0,0,6,5,'stat','percent','CPU'))
p.append(panel('Host RAM utilization','(1-(node_memory_MemAvailable_bytes/node_memory_MemTotal_bytes)) * 100',6,0,6,5,'stat','percent','RAM'))
p.append(panel('Host root disk usage','(1 - node_filesystem_avail_bytes{mountpoint="/",fstype!~"tmpfs|overlay"} / node_filesystem_size_bytes{mountpoint="/",fstype!~"tmpfs|overlay"})*100',12,0,6,5,'stat','percent','Disk'))
p.append(panel('Prometheus scrape targets up','sum(up)',18,0,6,5,'stat','none','Targets'))
p.append(panel('CPU utilization per core','100 * (1-rate(node_cpu_seconds_total{mode="idle"}[5m]))',0,5,12,8,unit='percent',legend='Core {{cpu}}'))
p.append(panel('RAM used / available','node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes',12,5,12,8,unit='bytes',legend='Used RAM'))
p.append(panel('Network received bytes/s','rate(node_network_receive_bytes_total{device!~"lo|veth.*"}[5m])',0,13,12,8,unit='Bps',legend='{{device}}'))
p.append(panel('Network transmitted bytes/s','rate(node_network_transmit_bytes_total{device!~"lo|veth.*"}[5m])',12,13,12,8,unit='Bps',legend='{{device}}'))
p.append(panel('Filesystem free space','node_filesystem_avail_bytes{mountpoint="/",fstype!~"tmpfs|overlay"}',0,21,12,8,unit='bytes',legend='{{mountpoint}}'))
p.append(panel('Monitored services health','up',12,21,12,8,legend='{{job}}'))
ds('ECS Host Telemetry','cloudlab-host',['ECS','Host'],p)
print('Wrote 4 Grafana dashboards to',OUTPUT)

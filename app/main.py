"""Day 48 Cloud Recovery Lab — deliberately safe, student-oriented control plane.

Local recovery target is a RESTORED BACKUP, not a streaming PostgreSQL standby.
Cloud DRS is configured outside this app; this app never mutates Huawei resources.
"""
import asyncio
import base64
import gzip
import hashlib
import hmac
import ipaddress
import json
import os
import re
import secrets
import sqlite3
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, Optional

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
import redis
from cryptography.fernet import Fernet
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from prometheus_client import Counter, Gauge, Histogram, CONTENT_TYPE_LATEST, generate_latest
from starlette.middleware.sessions import SessionMiddleware

DATA_DIR = Path('/data')
DATA_DIR.mkdir(parents=True, exist_ok=True)
BACKUP_DIR = DATA_DIR / 'backups'
BACKUP_DIR.mkdir(parents=True, exist_ok=True)
SQLITE_PATH = DATA_DIR / 'control.db'
SECRET = os.environ['LAB_SECRET']
AUTH_PASSWORD = os.environ['LAB_PASSWORD']
APP_VERSION = '1.0.0'
FERNET = Fernet(base64.urlsafe_b64encode(hashlib.sha256((SECRET + ':settings').encode()).digest()))

MET_REQUEST = Counter('cloudlab_http_requests_total', 'Web HTTP requests', ['method','route','status'])
MET_LATENCY = Histogram('cloudlab_http_request_duration_seconds', 'HTTP response latency', ['route'])
MET_DB_UP = Gauge('cloudlab_db_up','Database connectivity', ['target'])
MET_DB_LAT = Gauge('cloudlab_db_latency_seconds','PostgreSQL probe latency', ['target'])
MET_DB_ROWS = Gauge('cloudlab_db_rows','Row count per table', ['target','table'])
MET_DB_READONLY = Gauge('cloudlab_db_read_only','PostgreSQL connection read-only flag', ['target'])
MET_REPLICA_LAG = Gauge('cloudlab_replica_replay_delay_seconds','Replica replay delay, only when reported by PostgreSQL', ['target'])
MET_ACTIVE = Gauge('cloudlab_active_target','Application active database route', ['target'])
MET_BACKUP_TOTAL = Counter('cloudlab_backups_total','Logical app backups taken',['result'])
MET_BACKUP_TS = Gauge('cloudlab_last_backup_timestamp_seconds','Last local logical backup timestamp')
MET_BACKUP_SIZE = Gauge('cloudlab_last_backup_size_bytes','Last local logical backup size')
MET_RESTORE_TOTAL = Counter('cloudlab_restores_total','Local restores attempted',['result'])
MET_SWITCH_TOTAL = Counter('cloudlab_switches_total','Application endpoint switches',['result'])
MET_PRIMARY_SIM_DOWN = Gauge('cloudlab_simulated_primary_outage','Software-only primary outage flag')
MET_AUTO_FAILOVER = Gauge('cloudlab_auto_failover_enabled','Local auto-recovery route switching enabled')
MET_DR_MATCH = Gauge('cloudlab_recovery_verified','DR data match status: 1 confirmed, 0 mismatch, -1 unknown')
MET_RTO = Gauge('cloudlab_last_rto_seconds','Last measured application route recovery time')
MET_RPO = Gauge('cloudlab_last_backup_age_at_failure_seconds','Time since last backup at failure simulation, upper bound exposure window')
MET_CACHE_UP = Gauge('cloudlab_cache_up','Redis/DCS reachable')
MET_CACHE_HITS = Counter('cloudlab_cache_hits_total','Catalog cache hits')
MET_CACHE_MISSES = Counter('cloudlab_cache_misses_total','Catalog cache misses')
MET_ORDERS = Counter('cloudlab_orders_created_total','Store orders created',['target'])
MET_SALES = Counter('cloudlab_sales_amount_total','Order totals by target',['target'])
MET_DRILL_EVENTS = Counter('cloudlab_drill_events_total','Lab events',['type'])

app = FastAPI(title='Cloud Recovery Lab', docs_url=None, redoc_url=None)
app.add_middleware(SessionMiddleware, secret_key=SECRET, same_site='strict', max_age=60 * 60 * 8)
LOCK = threading.RLock()
POLL_INTERVAL = 20

class Integration(BaseModel):
    host: str = Field(default='', max_length=255)
    port: int = Field(default=5432, ge=1, le=65535)
    database: str = Field(default='cloudlab', max_length=63)
    username: str = Field(default='', max_length=128)
    password: str = Field(default='', max_length=512)
    sslmode: Literal['disable','prefer','require','verify-ca','verify-full'] = 'require'
    ca_file: str = Field(default='', max_length=200)

class CacheIntegration(BaseModel):
    host: str = Field(default='', max_length=255)
    port: int = Field(default=6379, ge=1, le=65535)
    username: str = Field(default='', max_length=128)
    password: str = Field(default='', max_length=512)
    db: int = Field(default=0, ge=0, le=15)
    tls: bool = True
    ca_file: str = Field(default='', max_length=200)

class OrderIn(BaseModel):
    product_id: int = Field(ge=1)
    qty: int = Field(default=1, ge=1, le=20)
    customer: str = Field(default='Lab Student', min_length=1, max_length=90)

class ActionIn(BaseModel):
    confirm: str = ''
    backup: str = ''
    target: str = ''
    title: str = ''

class DbCreation(BaseModel):
    target: Literal['primary', 'dr'] = 'primary'
    confirm: str = ''

class SaveConfig(BaseModel):
    target: Literal['primary','dr','replica','cache']
    value: dict


def _db():
    conn = sqlite3.connect(SQLITE_PATH, timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA busy_timeout=15000')
    return conn


def state_get(key, default=None):
    with _db() as c:
        row = c.execute('SELECT value FROM state WHERE key=?',(key,)).fetchone()
        return json.loads(row['value']) if row else default


def state_set(key, val):
    with LOCK, _db() as c:
        c.execute('INSERT INTO state(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                  (key,json.dumps(val, default=str)))


def event(kind, message, details=None):
    with _db() as c:
        c.execute('INSERT INTO events (created_at,kind,message,details) VALUES(?,?,?,?)',
                  (datetime.now(timezone.utc).isoformat(),kind,message,json.dumps(details or {},default=str)))
    MET_DRILL_EVENTS.labels(kind).inc()


def integration_get(target):
    with _db() as c:
        row = c.execute('SELECT ciphertext FROM integrations WHERE target=?',(target,)).fetchone()
    if not row: return None
    try: return json.loads(FERNET.decrypt(row['ciphertext'].encode()).decode())
    except Exception: return None


def integration_save(target, value):
    cipher = FERNET.encrypt(json.dumps(value).encode()).decode()
    with _db() as c:
        c.execute('INSERT INTO integrations(target,ciphertext) VALUES(?,?) ON CONFLICT(target) DO UPDATE SET ciphertext=excluded.ciphertext',(target,cipher))
    event('configuration',f'Updated {target} integration (secret redacted)')


def safe_conn(target):
    cfg = integration_get(target)
    if cfg and cfg.get('host'):
        result=dict(host=cfg['host'], port=int(cfg.get('port') or 5432), dbname=cfg.get('database') or 'cloudlab',
                    user=cfg.get('username'), password=cfg.get('password'), sslmode=cfg.get('sslmode','require'), connect_timeout=3,
                    options='-c statement_timeout=4000')
        if cfg.get('ca_file'):
            ca=Path('/app/certs') / Path(cfg['ca_file']).name
            if str(ca)!=str(Path('/app/certs')/cfg['ca_file']) or not ca.is_file():
                raise ValueError('RDS CA certificate must be a filename in the certs/ folder')
            result['sslrootcert']=str(ca)
        return result
    if target == 'primary': host = 'pg-primary'
    elif target == 'dr': host = 'pg-recovery'
    else: raise ValueError('Read replica is optional; configure its RDS endpoint first')
    return dict(host=host,port=5432,dbname=os.getenv('POSTGRES_DB','cloudlab'),
                user=os.getenv('POSTGRES_USER','cloudlab'),password=os.environ['POSTGRES_PASSWORD'],
                sslmode='disable',connect_timeout=3,options='-c statement_timeout=4000')


def external(target):
    cfg=integration_get(target)
    return bool(cfg and cfg.get('host'))

@contextmanager
def pg(target, dbname=None):
    kwargs=safe_conn(target)
    if dbname: kwargs['dbname']=dbname
    with psycopg.connect(**kwargs, row_factory=dict_row) as conn:
        yield conn


def cache_client():
    cfg = integration_get('cache')
    if cfg and cfg.get('host'):
        kw = dict(host=cfg['host'],port=int(cfg.get('port',6379)),db=int(cfg.get('db',0)),
                  username=cfg.get('username') or None,password=cfg.get('password') or None,
                  socket_connect_timeout=2,socket_timeout=2, decode_responses=True, ssl=cfg.get('tls',True))
        if cfg.get('tls',True):
            kw['ssl_cert_reqs'] = 'required'
            ca = cfg.get('ca_file','')
            if ca:
                p=Path('/app/certs')/Path(ca).name
                if str(p)!=str(Path('/app/certs')/ca) or not p.is_file():
                    raise ValueError('CA certificate must be a filename in the certs/ folder')
                kw['ssl_ca_certs']=str(p)
        return redis.Redis(**kw)
    return redis.Redis(host='redis',port=6379,password=os.getenv('REDIS_PASSWORD'),
                       socket_connect_timeout=2,socket_timeout=2,decode_responses=True)


def _json(value):
    if isinstance(value,datetime): return value.astimezone(timezone.utc).isoformat()
    if isinstance(value,Decimal): return str(value)
    raise TypeError(f'Cannot serialize {type(value)}')


def now(): return datetime.now(timezone.utc).isoformat()

SCHEMA = [
    '''CREATE TABLE IF NOT EXISTS products (
      id SERIAL PRIMARY KEY, sku TEXT NOT NULL UNIQUE, title TEXT NOT NULL,
      category TEXT NOT NULL, price NUMERIC(10,2) NOT NULL CHECK(price>=0),
      stock INTEGER NOT NULL DEFAULT 0 CHECK(stock>=0), created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())''',
    '''CREATE TABLE IF NOT EXISTS orders (
      id BIGSERIAL PRIMARY KEY, customer TEXT NOT NULL, total NUMERIC(10,2) NOT NULL,
      status TEXT NOT NULL DEFAULT 'placed', created_at TIMESTAMPTZ NOT NULL DEFAULT NOW())''',
    '''CREATE TABLE IF NOT EXISTS order_items (
      id BIGSERIAL PRIMARY KEY, order_id BIGINT NOT NULL REFERENCES orders(id),
      product_id INTEGER NOT NULL REFERENCES products(id), qty INTEGER NOT NULL CHECK(qty>0),
      unit_price NUMERIC(10,2) NOT NULL)'''
]
SEED = [
 ('SKU-01','Cloud Hoodie','Clothing','32.00',24),('SKU-02','Recovery Sneakers','Footwear','58.00',18),
 ('SKU-03','Grafana T-Shirt','Clothing','21.00',35),('SKU-04','Failover Backpack','Accessories','43.00',14),
 ('SKU-05','DCS Water Bottle','Accessories','15.00',55),('SKU-06','DRS Jacket','Clothing','76.00',10),
 ('SKU-07','RDS Wireless Mouse','Electronics','26.00',34),('SKU-08','Ubuntu Notebook','Stationery','9.00',80)
]
TABLES = ['products','orders','order_items']
TABLE_COLUMNS = {
 'products':['id','sku','title','category','price','stock','created_at'],
 'orders':['id','customer','total','status','created_at'],
 'order_items':['id','order_id','product_id','qty','unit_price']
}


def schema_ready(conn):
    with conn.cursor() as cur:
        row=cur.execute("SELECT to_regclass('public.products') IS NOT NULL AS ok").fetchone()
        return bool(row['ok'])


def init_schema(target):
    with pg(target) as conn:
        with conn.cursor() as cur:
            for statement in SCHEMA: cur.execute(statement)
            for item in SEED:
                cur.execute('INSERT INTO products(sku,title,category,price,stock) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(sku) DO NOTHING',item)
    event('schema',f'Initialized e-commerce tables on {target}')
    return {'ok': True,'target':target,'tables':TABLES,'seeded_products':len(SEED)}


def table_data(conn):
    d={}
    with conn.cursor() as cur:
        for name in TABLES:
            d[name]=cur.execute(sql.SQL('SELECT * FROM {} ORDER BY id').format(sql.Identifier(name))).fetchall()
    return d


def digest(data):
    canonical=json.dumps(data,sort_keys=True,separators=(',',':'),default=_json).encode()
    return hashlib.sha256(canonical).hexdigest()


def inspect_db(target):
    t=time.monotonic()
    try:
        with pg(target) as conn:
            with conn.cursor() as cur:
                info=cur.execute('SELECT current_database() db, pg_is_in_recovery() recovery, current_setting(\'transaction_read_only\') read_only').fetchone()
                is_ready=schema_ready(conn)
                counts={}
                if is_ready:
                    for table in TABLES:
                        counts[table]=cur.execute(sql.SQL('SELECT COUNT(*) n FROM {}').format(sql.Identifier(table))).fetchone()['n']
                lag=None
                if info['recovery']:
                    row=cur.execute('SELECT EXTRACT(EPOCH FROM (now() - pg_last_xact_replay_timestamp())) lag').fetchone()
                    lag=float(row['lag']) if row['lag'] is not None else None
        result={'ok':True,'target':target,'latency_ms':round((time.monotonic()-t)*1000,1),
                'db':info['db'],'recovery':info['recovery'],'read_only':info['read_only']=='on',
                'schema_ready':is_ready,'rows':counts,'replay_delay_s':round(lag,2) if lag is not None else None}
        MET_DB_UP.labels(target).set(1)
        MET_DB_LAT.labels(target).set((time.monotonic()-t))
        MET_DB_READONLY.labels(target).set(int(result['read_only']))
        for name,n in counts.items(): MET_DB_ROWS.labels(target,name).set(n)
        if lag is not None: MET_REPLICA_LAG.labels(target).set(lag)
        return result
    except Exception as ex:
        MET_DB_UP.labels(target).set(0)
        return {'ok':False,'target':target,'error':str(ex)[:190],'latency_ms':round((time.monotonic()-t)*1000,1)}


def active_target(): return state_get('active','primary')


def guarded_db():
    target=active_target()
    if target=='primary' and state_get('simulated_primary_down',False):
        raise HTTPException(503,'Simulated primary outage: application writes are paused until recovery endpoint is activated')
    return target


def products(cache=True):
    target=guarded_db()
    key=f'cloudlab:catalog:{target}'
    if cache:
        try:
            cached=cache_client().get(key)
            if cached:
                MET_CACHE_HITS.inc(); return json.loads(cached)
            MET_CACHE_MISSES.inc()
        except Exception: MET_CACHE_UP.set(0)
    with pg(target) as conn:
        if not schema_ready(conn): raise HTTPException(409,'Schema is missing; open Database and initialize tables')
        rows=conn.execute('SELECT id,sku,title,category,price,stock FROM products ORDER BY id').fetchall()
        values=[{**x, 'price':float(x['price'])} for x in rows]
    if cache:
        try: cache_client().setex(key,25,json.dumps(values)); MET_CACHE_UP.set(1)
        except Exception: MET_CACHE_UP.set(0)
    return values


def clear_cache():
    try:
        client=cache_client(); client.delete('cloudlab:catalog:primary','cloudlab:catalog:dr')
    except Exception: pass


def create_backup():
    target=guarded_db()
    with pg(target) as conn:
        conn.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        if not schema_ready(conn): raise ValueError('Create database tables first')
        rows=table_data(conn)
    created=datetime.now(timezone.utc)
    payload={'format':'cloudlab-logical-v1','created_at':created.isoformat(),
             'source':target,'fingerprint':digest(rows),'rows':rows,
             'counts':{x:len(y) for x,y in rows.items()}}
    stamp=created.strftime('%Y%m%dT%H%M%SZ')
    filename=f'cloudlab-{stamp}-{secrets.token_hex(3)}.json.gz'
    out=BACKUP_DIR/filename
    tmp=BACKUP_DIR/(filename+'.tmp')
    with gzip.open(tmp,'wt',encoding='utf-8') as f: json.dump(payload,f,default=_json)
    os.replace(tmp,out)
    MET_BACKUP_TOTAL.labels('success').inc()
    MET_BACKUP_TS.set(created.timestamp()); MET_BACKUP_SIZE.set(out.stat().st_size)
    state_set('last_backup',{'file':filename,'created_at':created.isoformat(),'fingerprint':payload['fingerprint'],
                             'counts':payload['counts'],'bytes':out.stat().st_size})
    event('backup','Created application-level logical backup',{'filename':filename,'counts':payload['counts']})
    return {'ok':True,'filename':filename,'counts':payload['counts'],'bytes':out.stat().st_size,
            'fingerprint':payload['fingerprint'][:16]}


def read_backup(filename):
    if not re.fullmatch(r'cloudlab-[a-zA-Z0-9-]+\.json\.gz', filename):
        raise ValueError('Invalid backup filename')
    p=BACKUP_DIR/filename
    if not p.is_file(): raise ValueError('Backup not found')
    if p.stat().st_size > 20 * 1024 * 1024: raise ValueError('Oversized backup')
    with gzip.open(p,'rt',encoding='utf-8') as f: obj=json.load(f)
    if obj.get('format')!='cloudlab-logical-v1' or set(obj.get('rows',{}))!=set(TABLES):
        raise ValueError('Unsupported backup format')
    if digest(obj['rows'])!=obj['fingerprint']: raise ValueError('Backup checksum mismatch')
    return obj


def restore_local(filename,target):
    if target not in ('primary','dr') or external(target):
        raise ValueError('Restores are limited to bundled local PostgreSQL databases; use Huawei RDS restore console for managed instances')
    if target == active_target(): raise ValueError('Never overwrite active application database. Choose inactive target.')
    payload=read_backup(filename)
    with pg(target) as conn:
        if not schema_ready(conn):
            with conn.cursor() as cur:
                for stmt in SCHEMA: cur.execute(stmt)
        with conn.cursor() as cur:
            for name in ('order_items','orders','products'):
                cur.execute(sql.SQL('DELETE FROM {}').format(sql.Identifier(name)))
            for name in TABLES:
                cols=TABLE_COLUMNS[name]
                stmt=sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(
                    sql.Identifier(name),sql.SQL(',').join(map(sql.Identifier,cols)),
                    sql.SQL(',').join([sql.Placeholder() for _ in cols]))
                for item in payload['rows'][name]: cur.execute(stmt,[item[c] for c in cols])
                cur.execute(sql.SQL('SELECT setval(pg_get_serial_sequence({},\'id\'), COALESCE((SELECT MAX(id) FROM {}),1), EXISTS(SELECT 1 FROM {}))').format(
                    sql.Literal(name),sql.Identifier(name),sql.Identifier(name)))
        after=table_data(conn)
        if digest(after)!=payload['fingerprint']:
            raise ValueError('Restored fingerprint does not match backup; transaction rolled back')
    state_set('restored_checkpoint',{'target':target,'backup':filename,'fingerprint':payload['fingerprint'],
                                     'created_at':payload['created_at'],'restored_at':now()})
    MET_RESTORE_TOTAL.labels('success').inc()
    MET_DR_MATCH.set(1)
    event('restore',f'Restored logical backup to INACTIVE local {target}',{'filename':filename})
    return {'ok':True,'target':target,'backup':filename,'verified':True,'counts':payload['counts']}


def verify_targets():
    source=active_target(); other='dr' if source=='primary' else 'primary'
    result={'source':source,'target':other,'source_ok':False,'target_ok':False,'match':None,'fingerprint_source':None,'fingerprint_target':None}
    errors={}
    try:
        with pg(source) as c:
            if not schema_ready(c): raise ValueError('Missing application schema')
            result['fingerprint_source']=digest(table_data(c)); result['source_ok']=True
    except Exception as ex: errors[source]=str(ex)[:160]
    try:
        with pg(other) as c:
            if not schema_ready(c): raise ValueError('Missing application schema')
            result['fingerprint_target']=digest(table_data(c)); result['target_ok']=True
            result['read_only']=c.execute("SHOW transaction_read_only").fetchone()['transaction_read_only']=='on'
            result['in_recovery']=c.execute('SELECT pg_is_in_recovery() recovery').fetchone()['recovery']
    except Exception as ex: errors[other]=str(ex)[:160]
    if result['source_ok'] and result['target_ok']:
        result['match']=result['fingerprint_source']==result['fingerprint_target']
        MET_DR_MATCH.set(int(result['match']))
    else: MET_DR_MATCH.set(-1)
    result['errors']=errors
    if result['match']:
        state_set('verified_checkpoint',{'source':source,'target':other,'fingerprint':result['fingerprint_target'],
                                          'at':now()})
    event('verify','Compared active and recovery database data digests',{'match':result['match']})
    return result


def attempt_switch(target, confirm):
    source=active_target()
    if target not in ('primary','dr') or target==source: raise ValueError('Select the inactive database as destination')
    remote=external(source) or external(target)
    if remote and confirm!='DRS CUTOVER':
        raise ValueError('External RDS cutover requires manual DRS promotion and exact confirmation: DRS CUTOVER')
    if not remote and confirm!='SWITCH': raise ValueError('Enter SWITCH to acknowledge endpoint change')
    with pg(target) as conn:
        if not schema_ready(conn): raise ValueError('Target schema missing: restore or configure DRS first')
        status=conn.execute('SELECT pg_is_in_recovery() recovery, current_setting(\'transaction_read_only\') ro').fetchone()
        if status['recovery'] or status['ro']=='on':
            raise ValueError('Destination is still read-only/in recovery. Promote RDS/DRS through its cloud console first')
        fingerprint=digest(table_data(conn))
    if not remote:
        checkpoint=state_get('restored_checkpoint',{})
        if checkpoint.get('target')!=target or checkpoint.get('fingerprint')!=fingerprint:
            raise ValueError('Recovery target is not verified against a restored backup; restore and check first')
    else:
        checkpoint=state_get('verified_checkpoint',{})
        try: valid_age=(datetime.now(timezone.utc)-datetime.fromisoformat(checkpoint['at'])).total_seconds() < 120
        except (KeyError,ValueError): valid_age=False
        if checkpoint.get('source')!=source or checkpoint.get('target')!=target or checkpoint.get('fingerprint')!=fingerprint or not valid_age:
            raise ValueError('Re-run Verify within 2 minutes, then confirm the external DRS promotion in Huawei console')
    started=state_get('failure_started',None)
    rto=max(0,(datetime.now(timezone.utc)-datetime.fromisoformat(started)).total_seconds()) if started else 0
    state_set('active',target)
    state_set('simulated_primary_down',False)
    MET_PRIMARY_SIM_DOWN.set(0)
    MET_RTO.set(rto)
    for name in ('primary','dr'): MET_ACTIVE.labels(name).set(int(target==name))
    MET_SWITCH_TOTAL.labels('success').inc()
    clear_cache()
    event('switch',f'APPLICATION connection route changed: {source} → {target}',{'rto_seconds':round(rto,2),'external':remote})
    return {'ok':True,'old_active':source,'new_active':target,'rto_seconds':round(rto,2),
            'note':'Application-only route switch; does not change RDS HA, DRS replication or cloud DNS'}


def db_count():
    try:
        with pg(active_target()) as conn:
            return {k:len(v) for k,v in table_data(conn).items()}
    except Exception: return {}


def cache_probe():
    start=time.monotonic()
    try:
        x=cache_client(); pong=x.ping()
        MET_CACHE_UP.set(1 if pong else 0)
        return {'ok':bool(pong),'latency_ms':round((time.monotonic()-start)*1000,1),
                'mode':'Huawei DCS / external Redis' if external('cache') else 'Bundled Redis cache'}
    except Exception as ex:
        MET_CACHE_UP.set(0)
        return {'ok':False,'error':str(ex)[:170], 'mode':'External DCS' if external('cache') else 'Bundled Redis'}


def poll():
    for target in ['primary','dr','replica']:
        if target!='replica' or external('replica'): inspect_db(target)
    cache_probe()
    for name in ('primary','dr'): MET_ACTIVE.labels(name).set(int(active_target()==name))
    MET_PRIMARY_SIM_DOWN.set(int(state_get('simulated_primary_down',False)))
    MET_AUTO_FAILOVER.set(int(state_get('auto_failover',False)))
    b=state_get('last_backup',None)
    if b:
        MET_BACKUP_TS.set(datetime.fromisoformat(b['created_at']).timestamp())
        MET_BACKUP_SIZE.set(int(b.get('bytes',0)))


def _monitor_loop():
    while True:
        try:
            poll()
            if state_get('auto_failover',False) and state_get('simulated_primary_down',False) and active_target()=='primary' and not external('primary') and not external('dr'):
                last_attempt=state_get('auto_failover_last_attempt',0)
                if time.time()-last_attempt>30:
                    state_set('auto_failover_last_attempt',time.time())
                    try:
                        with LOCK: attempt_switch('dr','SWITCH')
                        event('autofailover','Local application auto-recovery completed after simulated outage')
                    except Exception as ex:
                        event('autofailover','Guarded application auto-recovery blocked',{'reason':str(ex)[:150]})
            interval=int(os.environ.get('AUTO_BACKUP_SECONDS','300'))
            active=active_target()
            last=state_get('last_auto_backup_ts',0)
            if interval >= 60 and time.time()-last >= interval and not external(active) and not state_get('simulated_primary_down',False):
                if inspect_db(active).get('schema_ready'):
                    try:
                        with LOCK:
                            create_backup()
                        state_set('last_auto_backup_ts',time.time())
                    except Exception as ex: event('error','Automatic backup failed',{'error':str(ex)[:120]})
        except Exception: pass
        time.sleep(POLL_INTERVAL)


@app.on_event('startup')
def startup():
    with _db() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS integrations(target TEXT PRIMARY KEY,ciphertext TEXT NOT NULL)')
        c.execute('CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,created_at TEXT,kind TEXT,message TEXT,details TEXT)')
    for target in ('primary','dr'):
        if not external(target):
            for attempt in range(12):
                try: init_schema(target); break
                except Exception:
                    if attempt==11: event('error',f'Local {target} database startup failed')
                    time.sleep(2)
    event('system',f'Cloud Recovery Lab {APP_VERSION} started')
    thread=threading.Thread(target=_monitor_loop,daemon=True,name='cloudlab-poller')
    thread.start()


@app.middleware('http')
async def telemetry(request:Request, call_next):
    route=request.url.path
    if route.startswith('/api/'): route=re.sub(r'\d+','{id}',route)
    start=time.monotonic()
    try:
        response=await call_next(request)
        status=response.status_code
    except Exception:
        status=500; raise
    finally:
        if route not in ('/metrics','/healthz'):
            MET_REQUEST.labels(request.method,route,str(status)).inc()
            MET_LATENCY.labels(route).observe(time.monotonic()-start)
    return response


def check(request):
    if request.session.get('authenticated') is not True: raise HTTPException(401,'Login required')


@app.get('/')
def root(request:Request):
    if not request.session.get('authenticated'):
        return FileResponse('/app/static/login.html')
    return FileResponse('/app/static/index.html')


@app.get('/static/{name}')
def static(name: str):
    if name not in ('app.js','style.css','login.html','index.html'):
        raise HTTPException(404)
    return FileResponse(Path('/app/static')/name)


@app.post('/api/login')
async def login(request:Request):
    payload=await request.json()
    password=str(payload.get('password',''))
    if not hmac.compare_digest(password,AUTH_PASSWORD):
        await asyncio.sleep(.45)
        raise HTTPException(401,'Incorrect lab password')
    request.session['authenticated']=True
    return {'ok':True}


@app.post('/api/logout')
def logout(request:Request):
    request.session.clear(); return {'ok':True}


@app.get('/healthz')
def healthz(): return {'ok':True,'service':'cloudlab','version':APP_VERSION}


@app.get('/metrics')
def metrics(request:Request):
    # Prometheus uses the internal Docker bridge; never expose metrics on public ECS IP.
    try: ip=ipaddress.ip_address(request.client.host)
    except (ValueError,AttributeError): raise HTTPException(403,'Internal metrics endpoint only')
    if not (ip.is_private or ip.is_loopback): raise HTTPException(403,'Internal metrics endpoint only')
    return Response(generate_latest(),media_type=CONTENT_TYPE_LATEST)


@app.get('/api/dashboard')
def dashboard(request:Request):
    check(request)
    try: poll()
    except Exception: pass
    last=state_get('last_backup')
    events=[]
    with _db() as c:
        events=[dict(x) for x in c.execute('SELECT id,created_at,kind,message FROM events ORDER BY id DESC LIMIT 12').fetchall()]
    return {'version':APP_VERSION,'active':active_target(),'simulated_down':state_get('simulated_primary_down',False),
            'databases':{target:inspect_db(target) for target in ('primary','dr')} | ({'replica':inspect_db('replica')} if external('replica') else {}),
            'cache':cache_probe(),'last_backup':last,'backup_count':len(list(BACKUP_DIR.glob('cloudlab-*.json.gz'))),
            'events':events,'config_modes':{t:('external' if external(t) else ('not configured' if t=='replica' else 'bundled local')) for t in ('primary','dr','replica','cache')},
            'failure_started':state_get('failure_started'), 'auto_failover':state_get('auto_failover',False), 'last_rto':MET_RTO._value.get(),
            'drs_task_id':state_get('drs_task_id',''), 'drs_note':'DRS task status is not automatically queried; view task in Huawei Cloud console'}


@app.get('/api/products')
def get_products(request:Request):
    check(request)
    try: return {'items':products()}
    except HTTPException: raise
    except Exception as ex: raise HTTPException(503,str(ex)[:200])


@app.get('/api/orders')
def get_orders(request:Request):
    check(request)
    try:
        with pg(guarded_db()) as conn:
            return {'items':[{**o,'total':float(o['total']),'created_at':str(o['created_at'])}
                    for o in conn.execute('SELECT * FROM orders ORDER BY id DESC LIMIT 30').fetchall()]}
    except HTTPException: raise
    except Exception as ex: raise HTTPException(503,str(ex)[:200])


@app.post('/api/orders')
def create_order(request:Request, data:OrderIn):
    check(request)
    target=guarded_db()
    try:
        with pg(target) as conn:
            with conn.cursor() as cur:
                product=cur.execute('SELECT id,price,stock,title FROM products WHERE id=%s FOR UPDATE',(data.product_id,)).fetchone()
                if not product: raise ValueError('Unknown product')
                if product['stock']<data.qty: raise ValueError('Insufficient stock')
                total=product['price']*data.qty
                order=cur.execute('INSERT INTO orders(customer,total) VALUES(%s,%s) RETURNING id',
                                  (data.customer,total)).fetchone()['id']
                cur.execute('INSERT INTO order_items(order_id,product_id,qty,unit_price) VALUES(%s,%s,%s,%s)',
                            (order,product['id'],data.qty,product['price']))
                cur.execute('UPDATE products SET stock=stock-%s WHERE id=%s',(data.qty,product['id']))
        MET_ORDERS.labels(target).inc()
        MET_SALES.labels(target).inc(float(total))
        event('order',f'Order #{order} created on {target}',{'total':float(total)})
        clear_cache()
        return {'ok':True,'order_id':order,'total':float(total),'database':target}
    except ValueError as ex: raise HTTPException(400,str(ex))
    except Exception as ex: raise HTTPException(503,str(ex)[:200])


@app.get('/api/config')
def config(request:Request):
    check(request)
    result={}
    for target in ('primary','dr','replica','cache'):
        x=integration_get(target) or {}
        result[target]={**{k:v for k,v in x.items() if k!='password'}, 'configured':external(target),
                        'has_password':bool(x.get('password'))}
    return result


@app.post('/api/config')
def save_config(request:Request, payload:SaveConfig):
    check(request)
    target=payload.target
    try:
        obj=CacheIntegration(**payload.value) if target=='cache' else Integration(**payload.value)
        values=obj.model_dump()
        prior=integration_get(target) or {}
        if not values.get('password') and prior.get('password'): values['password']=prior['password']
        if not values.get('host'):
            # Blank resets to local, only for primary/dr/cache. For replica: disables.
            with _db() as c: c.execute('DELETE FROM integrations WHERE target=?',(target,))
            event('configuration',f'Reset {target} integration')
            return {'ok':True,'mode':'local/reset'}
        if not values.get('username') and target!='cache': raise ValueError('PostgreSQL user is required')
        integration_save(target,values)
        return {'ok':True,'mode':'external','note':'Credentials encrypted at rest in /data/control.db'}
    except (ValueError,TypeError) as ex: raise HTTPException(400,str(ex))


@app.post('/api/test/{target}')
def test_target(request:Request,target:str):
    check(request)
    if target=='cache': return cache_probe()
    if target not in ('primary','dr','replica'): raise HTTPException(404)
    return inspect_db(target)


@app.post('/api/create-database')
def create_database(request:Request, data:DbCreation):
    check(request)
    if data.confirm!='CREATE': raise HTTPException(400,'Type CREATE before running CREATE DATABASE')
    cfg=safe_conn(data.target)
    name=cfg['dbname']
    if name in ('template0','template1','postgres'):
        raise HTTPException(400,'Refusing to create a reserved database')
    cfg['dbname']='postgres'
    try:
        with psycopg.connect(**cfg,autocommit=True,row_factory=dict_row) as c:
            exists=c.execute('SELECT 1 FROM pg_database WHERE datname=%s',(name,)).fetchone()
            if not exists: c.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        event('schema',f'CREATE DATABASE requested for {data.target}',{'database':name,'preexisting':bool(exists)})
        return {'ok':True,'database':name,'preexisting':bool(exists), 'note':'Requires CREATEDB privilege on Huawei RDS account'}
    except Exception as ex: raise HTTPException(400,str(ex)[:230])


@app.post('/api/init/{target}')
def initialize(request:Request,target:str,data:ActionIn):
    check(request)
    if target not in ('primary','dr'): raise HTTPException(404)
    if data.confirm!='INIT': raise HTTPException(400,'Type INIT to create schema and seed sample products')
    try: return init_schema(target)
    except Exception as ex: raise HTTPException(400,str(ex)[:230])


@app.get('/api/backups')
def backups(request:Request):
    check(request)
    items=[]
    for p in sorted(BACKUP_DIR.glob('cloudlab-*.json.gz'),reverse=True)[:50]:
        try:
            j=read_backup(p.name)
            items.append({'filename':p.name,'created_at':j['created_at'],'source':j['source'],
                          'counts':j['counts'],'size':p.stat().st_size,'fingerprint':j['fingerprint'][:16]})
        except Exception: continue
    return {'items':items}


@app.post('/api/backups')
def backup_now(request:Request):
    check(request)
    try:
        with LOCK: return create_backup()
    except Exception as ex:
        MET_BACKUP_TOTAL.labels('failed').inc()
        raise HTTPException(409,str(ex)[:230])


@app.post('/api/restore')
def restore(request:Request,data:ActionIn):
    check(request)
    if data.confirm!='RESTORE': raise HTTPException(400,'Type RESTORE to overwrite inactive LOCAL target data')
    try:
        with LOCK: return restore_local(data.backup,data.target)
    except Exception as ex:
        MET_RESTORE_TOTAL.labels('failed').inc()
        raise HTTPException(409,str(ex)[:250])


@app.post('/api/verify')
def verify(request:Request):
    check(request)
    try: return verify_targets()
    except Exception as ex: raise HTTPException(409,str(ex)[:220])


@app.post('/api/simulate')
def simulate(request:Request,data:ActionIn):
    check(request)
    if active_target()!='primary' or external('primary'):
        raise HTTPException(409,'Software-only outage exercise requires active bundled local primary')
    if data.confirm!='SIMULATE': raise HTTPException(400,'Type SIMULATE')
    state_set('failure_started',now()); state_set('simulated_primary_down',True)
    MET_PRIMARY_SIM_DOWN.set(1)
    last=state_get('last_backup')
    if last:
        seconds=max(0,(datetime.now(timezone.utc)-datetime.fromisoformat(last['created_at'])).total_seconds())
        MET_RPO.set(seconds)
    event('failure','SIMULATED application outage (no DB/VM stopped)')
    return {'ok':True,'simulation_only':True,'note':'Only application access to primary is blocked; no ECS or RDS was stopped'}


@app.post('/api/clear-simulation')
def clear_sim(request:Request):
    check(request)
    state_set('simulated_primary_down',False); MET_PRIMARY_SIM_DOWN.set(0)
    event('failure','Cleared simulation flag')
    return {'ok':True}


@app.post('/api/switch')
def switch(request:Request,data:ActionIn):
    check(request)
    try:
        with LOCK: return attempt_switch(data.target,data.confirm)
    except Exception as ex:
        MET_SWITCH_TOTAL.labels('failed').inc()
        raise HTTPException(409,str(ex)[:270])


@app.get('/api/replica/products')
def replica_products(request:Request):
    check(request)
    if not external('replica'): raise HTTPException(409,'Configure a Huawei RDS read replica first')
    try:
        with pg('replica') as conn:
            status=conn.execute('SELECT pg_is_in_recovery() standby').fetchone()
            rows=conn.execute('SELECT id,sku,title,stock FROM products ORDER BY id').fetchall()
        return {'ok':True,'postgres_reports_recovery':status['standby'],'items':rows,
                'note':'Only read queries are executed; read replica is separate from DR failover target'}
    except Exception as ex: raise HTTPException(503,str(ex)[:210])


@app.get('/api/events')
def events(request:Request):
    check(request)
    with _db() as c:
        items=[dict(r) for r in c.execute('SELECT * FROM events ORDER BY id DESC LIMIT 100').fetchall()]
    for x in items:
        try: x['details']=json.loads(x['details'])
        except Exception: x['details']={}
    return {'items':items}


@app.post('/api/drs')
async def drs(request:Request):
    check(request)
    body=await request.json()
    task=str(body.get('task_id','')).strip()[:100]
    state_set('drs_task_id',task)
    event('configuration','DRS task reference changed; status is NOT auto-verified')
    return {'ok':True,'note':'Reference only. Use Huawei DRS console to configure and monitor replication.'}


@app.post('/api/auto-failover')
async def auto_failover_setting(request:Request):
    check(request)
    body=await request.json()
    enabled=body.get('enabled') is True
    if enabled and (external('primary') or external('dr')):
        raise HTTPException(409,'This app-level auto-switch feature is strictly for bundled local databases. Use Huawei RDS managed HA/DRS in real environments.')
    state_set('auto_failover',enabled)
    MET_AUTO_FAILOVER.set(int(enabled))
    event('configuration',f'Local guarded auto-recovery {"enabled" if enabled else "disabled"}')
    return {'ok':True,'enabled':enabled,'note':'Auto-switch is guarded by verified local-restored backup integrity, never cloud-managed HA'}

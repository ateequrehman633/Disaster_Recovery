#!/usr/bin/env python3
"""Pixel-perfect, technically checked lecture visuals. Render with CairoSVG."""
from pathlib import Path
from html import escape
import cairosvg
OUT=Path(__file__).resolve().parent/'images';OUT.mkdir(exist_ok=True)
W,H=1920,1080
A='#53d6f8';B='#7798ff';G='#43d4a4';P='#b29aff';Y='#ffc479';R='#ff8895'
def rect(x,y,w,h,fill='#14243c',stroke='#2e4566',rad=20,sw=2):
 return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rad}" fill="{fill}" stroke="{stroke}" stroke-width="{sw}"/>'
def txt(x,y,s,size=30,color='#e9f4ff',weight=500,anchor='start',tracking=0):
 return f'<text x="{x}" y="{y}" fill="{color}" font-family="Inter, DejaVu Sans, Arial" font-weight="{weight}" font-size="{size}" letter-spacing="{tracking}" text-anchor="{anchor}">{escape(str(s))}</text>'
def ln(x1,y1,x2,y2,color=A,width=4,dash=''):
 return f'<path d="M{x1} {y1} L{x2} {y2}" fill="none" stroke="{color}" stroke-width="{width}" stroke-linecap="round" stroke-dasharray="{dash}"/>'
def pill(x,y,s,color=A,width=None):
 w=width or max(124,len(s)*10+32)
 return rect(x,y,w,42,'#122b43',color,18,1.5)+txt(x+w/2,y+28,s,20,color,700,'middle')
def arrow(x1,y1,x2,y2,color=A,width=4,dash=''):
 return ln(x1,y1,x2,y2,color,width,dash)+f'<path d="M{x2} {y2} l-17 -10 l0 20 Z" fill="{color}" transform="rotate({__import__("math").degrees(__import__("math").atan2(y2-y1,x2-x1))}, {x2}, {y2})"/>'
def lines(x,y,arr,size=22,col='#9ebad9',step=31):
 return ''.join(txt(x,y+i*step,a,size,col,500) for i,a in enumerate(arr))
def base(k,title,subtitle):
 grid=''.join(ln(x,0,x,H,'#172943',1) for x in range(0,W,120))+''.join(ln(0,y,W,y,'#152640',1) for y in range(0,H,120))
 return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}">
 <defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#09172a"/><stop offset=".56" stop-color="#0c1d34"/><stop offset="1" stop-color="#090d1a"/></linearGradient>
 <linearGradient id="accent" x1="0" y1="0" x2="1" y2=".2"><stop stop-color="#1e5d8d"/><stop offset="1" stop-color="#3a4b92"/></linearGradient>
 <filter id="shadow"><feGaussianBlur stdDeviation="10"/></filter>
 </defs><rect width="{W}" height="{H}" fill="url(#bg)"/>
 <g opacity=".16">{grid}</g><rect x="60" y="55" width="12" height="104" rx="6" fill="{A}"/>
 {pill(100,58,'DAY 48 · LAB 20',A,268)}
 {txt(100,175,title,64,'#f5f9ff',750)}{txt(102,220,subtitle,26,'#96b8d8')}
 {pill(1560,67,'HUAWEI CLOUD ECS',G,300)}
 '''
def foot(text,number):
 return rect(60,985,1800,60,'#11243d','#315277',16,1)+txt(95,1025,f'{number}   |   {text}',23,'#b9d2ec',650)+'</svg>'
def save(i,markup):
 p=OUT/f'{i}.png';cairosvg.svg2png(bytestring=markup.encode(),write_to=str(p)); print(p,p.stat().st_size)

# Image 1 — accurate topology.
s=base('1','Recovery Lab Architecture','One Ubuntu ECS  ·  10 Docker containers  ·  Optional Huawei managed-service endpoints')
s+=rect(60,270,800,675,'#10213a','#4079a2',24,3)+txt(98,325,'UBUNTU ECS  /  DOCKER COMPOSE',35,A,750)
s+=rect(98,353,725,128,'#193352','#37658e')+txt(132,398,'CloudLab Control Panel + Mini Store',30,'#eff7ff',750)+lines(133,434,['HTML / JavaScript UI  ·  FastAPI backend  ·  Real orders'],21)
s+=rect(98,506,346,160,'#18283e','#416284')+txt(123,554,'Local PostgreSQL',27,G,750)+lines(123,592,['Primary + recovery target','Restore via verified snapshot'],20)
s+=rect(468,506,355,160,'#18283e','#416284')+txt(492,554,'Local Redis Cache',27,Y,750)+lines(492,592,['Optional DCS endpoint','Password + TLS support'],20)
s+=rect(98,693,346,172,'#18283e','#416284')+txt(123,742,'Prometheus',28,A,750)+lines(123,782,['App + Postgres exporters','Redis + host exporters','Alert rules + metrics'],19)
s+=rect(468,693,355,172,'#18283e','#416284')+txt(492,742,'Grafana',28,P,750)+lines(492,782,['Four live dashboards','RTO / RPO exposure / sales','CPU / RAM / DB / Redis'],19)
s+=rect(910,270,950,675,'#101d34','#334f77',24,3)+txt(950,325,'OPTIONAL HUAWEI CLOUD EXTENSIONS',35,'#dceaff',750)
s+=rect(954,360,410,134,'#142b42','#2d8d88')+txt(985,407,'RDS primary (PostgreSQL)',26,G,750)+lines(985,449,['Main application write endpoint'],20)
s+=rect(1432,360,385,134,'#132740','#427ec6')+txt(1460,407,'RDS read replica',26,A,750)+lines(1460,449,['SELECT-only read offload'],20)
s+=arrow(1367,425,1426,425,A)
s+=rect(954,539,410,140,'#142b42','#8464d8')+txt(984,590,'DR RDS target',27,P,750)+lines(984,631,['Separate instance if configured'],19)
s+=rect(1432,539,385,140,'#142b42','#b48a4e')+txt(1460,590,'Huawei DCS Redis',27,Y,750)+lines(1460,631,['Optional managed cache'],19)
s+=rect(952,718,864,153,'#1c2441','#8b77bf')+txt(990,768,'Huawei DRS replication: configured in cloud console',26,'#d6c8ff',720)+lines(990,806,['Not created, controlled or verified by this training web app.'],22)
s+=arrow(1172,498,1172,531,P,4,'9 8')
s+=foot('Local recovery is a restored backup, NOT a native RDS standby. External managed HA is separate.','01')
save('01_architecture',s)

# Image 2 — recovery procedure with educational decision.
s=base('2','Backup, Failure and Recovery Workflow','A safe classroom drill that visibly distinguishes backup age, data loss and recovery time')
steps=[('01','CREATE ORDERS',['Postgres transaction','Inventory decreases'],A),
       ('02','TAKE BACKUP',['Consistent JSON+GZIP','Checksum SHA-256'],G),
       ('03','RESTORE DR',['Inactive local target','No external RDS restore'],P),
       ('04','VERIFY DATA',['Compare table digests','Identify missing writes'],Y),
       ('05','SIMULATE LOSS',['Software-only DB block','RTO clock begins'],R),
       ('06','SWITCH ROUTE',['Guarded auto or manual','Test new store order'],G)]
for i,(n,name,details,color) in enumerate(steps):
 x=70+(i%3)*620;y=290+(i//3)*260
 s+=rect(x,y,580,208,'#11223a',color,20,2)
 s+=rect(x+20,y+20,64,64,'#172f4a',color,13,2)+txt(x+52,y+63,n,27,color,750,'middle')
 s+=txt(x+106,y+62,name,31,'#eff6ff',750)
 s+=lines(x+30,y+115,details,24,'#a9c3e0',38)
 if i not in (2,5):s+=arrow(x+580,y+105,x+610,y+105,color,3)
s+=rect(73,826,875,126,'#11243d','#4e759f',19,2)+txt(105,878,'RTO',32,A,800)+lines(220,872,['Seconds from simulated outage','until application endpoint recovery'],22)
s+=rect(973,826,875,126,'#11243d','#8663a3',19,2)+txt(1005,878,'RPO',32,P,800)+lines(1120,872,['Snapshot age at failure = exposure window','Exact data loss requires record comparison'],22)
s+=foot('Automatic local failover runs only after a verified restore; no ECS/RDS is intentionally stopped.','02')
save('02_recovery_workflow',s)

# Image 3 — teaching Grafana panels, no invented metrics.
s=base('3','Observability: What Students Will Measure','Four provisioned Grafana dashboards with Prometheus time-series from real lab events')
metrics=[
 ('Recovery Command Center','cloudlab_db_up  ·  cloudlab_active_target',['DB connectivity','RTO & RPO exposure','Backup age / DR verification'],A),
 ('PostgreSQL & Recovery','pg_up  ·  cloudlab_db_rows',['Order and product counts','Database connection latency','Commits, tuples, deadlocks'],G),
 ('Store & Redis','cloudlab_http_requests_total  ·  redis_*',['Store orders and revenue','Request latency (p95)','Cache hits, misses, memory'],P),
 ('ECS Host Telemetry','node_cpu_seconds_total  ·  node_*',['CPU / RAM utilization','Filesystem free capacity','Network traffic / scrapes'],Y)
]
for i,(name,q,content,color) in enumerate(metrics):
 x=70+(i%2)*920;y=290+(i//2)*321
 s+=rect(x,y,880,287,'#111e34','#3c5476',20,2)
 s+=rect(x+20,y+18,9,64,color,color,5,0)
 s+=txt(x+51,y+54,name,33,'#f1f7ff',760)
 s+=txt(x+52,y+95,q,21,color,620)
 # no fake data lines: blueprint placeholders, with real metric names
 s+=rect(x+52,y+120,343,136,'#101b2d','#32455f',13,1)
 for j,label in enumerate(['METRIC','SOURCE','SCRAPE']):
  s+=txt(x+74,y+157+j*36,label,16,'#698bad',750)
  s+=rect(x+172,y+141+j*36,195,9,'#284765','none',5,0)
 s+=lines(x+455,y+157,content,22,'#a8c0dc',37)
s+=rect(73,948,1775,34,'#11263d','none',12,0)+txt(100,970,'Dashboard concept only — charts populate after Prometheus scrapes actual operations. No example readings are invented.',19,'#a0d8e7',700)
s+=foot('Open Grafana on port 3000; sample app + DB + cache + host metrics every 15 seconds.','03')
save('03_observability',s)

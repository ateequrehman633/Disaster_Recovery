Optional user-provided trusted CA certificates for PostgreSQL RDS or DCS Redis TLS.

Place files here before deployment:
  certs/rds-root.crt
  certs/dcs-root.crt

In web UI, set "CA certificate filename" (name only; no path). The app
mounts this folder read-only as /app/certs. Never put secret keys here.

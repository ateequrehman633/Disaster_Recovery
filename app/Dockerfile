FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt && groupadd --gid 10001 lab && useradd --uid 10001 --gid lab --home-dir /app lab && mkdir -p /data /app/certs && chown -R lab:lab /data /app
COPY --chown=lab:lab . /app
USER lab
EXPOSE 8080
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers"]

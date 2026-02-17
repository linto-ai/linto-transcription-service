FROM python:3.10-alpine
LABEL maintainer="rbaraglia@linagora.com"

WORKDIR /usr/src/app

RUN apk upgrade --no-cache && apk add --no-cache \
    bash curl ffmpeg gettext su-exec shadow \
    build-base python3-dev \
    && ln -s /sbin/su-exec /usr/local/bin/gosu

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY transcriptionservice /usr/src/app/transcriptionservice
COPY docker-entrypoint.sh wait-for-it.sh healthcheck.sh heartbeat.sh heartbeat.json ./
COPY supervisor /usr/src/app/supervisor
RUN mkdir -p /var/log/supervisor/
RUN mkdir /usr/src/app/logs
RUN chmod +x docker-entrypoint.sh wait-for-it.sh

ENV PYTHONPATH="${PYTHONPATH}:/usr/src/app/transcriptionservice"

HEALTHCHECK CMD ./healthcheck.sh

EXPOSE 80

ENTRYPOINT ["./docker-entrypoint.sh"]

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    BBR_SERVER_DATA=/data \
    PORT=8099

WORKDIR /app

COPY server/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY server/ ./

VOLUME ["/data"]
EXPOSE 8099

CMD ["waitress-serve", "--host=0.0.0.0", "--port=8099", "app:app"]

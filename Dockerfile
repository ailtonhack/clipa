FROM node:22-bookworm-slim AS javascript
FROM python:3.12-slim-bookworm
COPY --from=javascript /usr/local/bin/node /usr/local/bin/node
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core libstdc++6 libatomic1 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend ./backend
COPY dist ./dist
COPY start.py .
ENV CLIPA_BIND=0.0.0.0
EXPOSE 8000
CMD ["python", "start.py"]

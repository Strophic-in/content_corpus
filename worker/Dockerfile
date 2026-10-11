# Both worker lanes run this image (CORPUS_LANE=cpu|gpu), built from the repo
# root by deploy/docker-compose.yml. ffmpeg (with libass) assembles reels;
# openssh-client lets the gpu lane drive rented Race pods.

FROM python:3.11-slim-bookworm
RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg openssh-client ca-certificates \
 && rm -rf /var/lib/apt/lists/*
RUN useradd --uid 10001 --create-home worker \
 && mkdir -p /home/worker/.cache && chown worker:worker /home/worker/.cache

WORKDIR /app/worker
COPY worker/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY worker/ /app/worker/
COPY prompts/ /app/prompts/
COPY db/ /app/db/

USER worker
ENV PYTHONUNBUFFERED=1 HOME=/home/worker
CMD ["python", "-m", "corpus"]

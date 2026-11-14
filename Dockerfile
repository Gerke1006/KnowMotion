FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    OUTPUT_DIR=/app/outputs \
    MANIM_FONT="Noto Sans CJK SC" \
    FONT_PATH=/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg fonts-noto-cjk pkg-config libcairo2-dev libpango1.0-dev \
    build-essential texlive-latex-base texlive-latex-extra texlive-fonts-recommended \
    dvisvgm && rm -rf /var/lib/apt/lists/*
WORKDIR /app
# Copy only application inputs; never copy a local .env or generated artifacts.
COPY pyproject.toml ./
COPY harness ./harness
COPY workflows ./workflows
COPY renderers ./renderers
COPY domains ./domains
COPY assets ./assets
COPY storage ./storage
COPY api ./api
RUN pip install ".[manim,production]"
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

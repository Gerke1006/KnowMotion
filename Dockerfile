FROM node:22-bookworm-slim AS node-runtime
FROM python:3.12-slim-bookworm

# Copy Node/npm only; copying /usr/local wholesale would overwrite Python.
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/npm
RUN ln -s ../lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s ../lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    OUTPUT_DIR=/app/outputs \
    MANIM_FONT="Noto Serif CJK SC" \
    CHINESE_FONT="Noto Serif CJK SC" \
    ENGLISH_FONT="Liberation Serif" \
    SUBTITLE_FONT="Noto Sans CJK SC" \
    FONT_PATH=/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc \
    ENGLISH_FONT_PATH=/usr/share/fonts/truetype/liberation2/LiberationSerif-Regular.ttf \
    SUBTITLE_FONT_PATH=/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc \
    FFMPEG_PATH=/usr/bin/ffmpeg \
    FFPROBE_PATH=/usr/bin/ffprobe \
    LATEX_COMPILER_PATH=/usr/bin/pdflatex \
    REMOTION_PROJECT="" \
    REMOTION_ENTRY=src/index.ts \
    REMOTION_BROWSER_EXECUTABLE=""

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates ffmpeg fonts-noto-cjk fonts-liberation2 fontconfig \
    pkg-config libcairo2-dev libpango1.0-dev \
    build-essential texlive-latex-base texlive-latex-extra texlive-fonts-recommended \
    dvisvgm libnss3 libdbus-1-3 libatk1.0-0 libgbm1 libasound2 \
    libxrandr2 libxkbcommon0 libxfixes3 libxcomposite1 libxdamage1 \
    libatk-bridge2.0-0 libcups2 libatomic1 \
    && fc-cache -f && rm -rf /var/lib/apt/lists/*

# Install platform-native dependencies and Chrome in the image. The build
# context excludes host node_modules and browser caches via .dockerignore.
WORKDIR /app/renderers/remotion/project
COPY renderers/remotion/project/package.json renderers/remotion/project/package-lock.json ./
RUN npm ci --no-audit --no-fund \
    && node node_modules/@remotion/cli/remotion-cli.js browser ensure --log=error \
    && npm cache clean --force

WORKDIR /app
# Copy application inputs and approved public assets; never copy local .env,
# generated artifacts, host-installed browser binaries, or proprietary fonts.
COPY pyproject.toml ./
COPY harness ./harness
COPY workflows ./workflows
COPY renderers/*.py renderers/README.md ./renderers/
COPY renderers/manim ./renderers/manim
COPY renderers/ffmpeg ./renderers/ffmpeg
COPY renderers/blender ./renderers/blender
COPY renderers/remotion/__init__.py ./renderers/remotion/
COPY renderers/remotion/project/tsconfig.json renderers/remotion/project/README.md ./renderers/remotion/project/
COPY renderers/remotion/project/src ./renderers/remotion/project/src
COPY renderers/remotion/project/tools ./renderers/remotion/project/tools
COPY renderers/remotion/project/public/data ./renderers/remotion/project/public/data
COPY renderers/remotion/project/public/portraits ./renderers/remotion/project/public/portraits
COPY domains ./domains
COPY assets/*.py assets/*.json assets/*.md ./assets/
COPY assets/audio ./assets/audio
COPY assets/history ./assets/history
COPY storage ./storage
COPY api ./api
COPY scripts/verify_live.py ./scripts/verify_live.py
COPY scripts/verify_history.py ./scripts/verify_history.py
COPY tools ./tools
COPY third_party ./third_party
RUN pip install ".[manim,production]"
EXPOSE 8000
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

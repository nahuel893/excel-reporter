FROM python:3.12-slim

# Non-root user (uid 1000 to match Linux dev defaults)
RUN groupadd -g 1000 runner && useradd -u 1000 -g runner -m -d /home/runner -s /bin/bash runner

# System deps for matplotlib (no GUI backend) + libpng + freetype
RUN apt-get update && apt-get install -y --no-install-recommends \
        libfreetype6-dev libpng-dev fontconfig \
    && rm -rf /var/lib/apt/lists/*

# Pinned scientific stack
RUN pip install --no-cache-dir \
        "pandas==2.2.*" \
        "numpy==1.26.*" \
        "matplotlib==3.8.*" \
        "openpyxl==3.1.*" \
        "pyarrow==15.*" \
        "Pillow==10.*"

# Force matplotlib non-GUI backend (no DISPLAY in sandbox)
ENV MPLBACKEND=Agg \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Pre-create output dir owned by runner; /data and /code are bind-mounted RO at runtime
RUN mkdir -p /output && chown runner:runner /output && chmod 755 /output

USER runner
WORKDIR /home/runner
ENTRYPOINT ["python"]

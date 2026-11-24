# Security baseline (ifx-docs 14.1, step 4): pinned Python 3.12 base, multi-stage
# build with a virtualenv, runs as a non-root user. Layout is unchanged: the app
# lives in /src and reads its config from ../resources (/resources) by default.

# ---- build stage ----
FROM python:3.12.16-slim-bookworm AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt /
RUN pip install -r /requirements.txt

# ---- runtime stage ----
FROM python:3.12.16-slim-bookworm

RUN useradd -m -u 10001 appuser

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY . /
WORKDIR /src

# Non-root (uid 10001). The app only reads its files, so nothing needs chown.
USER 10001:10001

CMD [ "python3", "-u", "main.py" ]

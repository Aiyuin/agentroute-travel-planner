FROM python:3.13.14-slim

WORKDIR /app
ARG PACKAGE_INDEX=https://pypi.org/simple

ENV UV_PROJECT_ENVIRONMENT="/usr/local/"
ENV UV_COMPILE_BYTECODE=1

COPY pyproject.toml .
COPY uv.lock .
RUN pip install --no-cache-dir --index-url ${PACKAGE_INDEX} uv==0.11.32

# Install only the dependencies needed for the client application
# --frozen: Use exact versions from the lock file
# --only-group client: Only install dependencies marked as part of the "client" group in pyproject.toml
RUN uv export --frozen --only-group client --no-emit-project --format requirements-txt > /tmp/requirements.txt \
    && uv --no-config pip install --system --require-hashes --index-url ${PACKAGE_INDEX} -r /tmp/requirements.txt

COPY src/client/ ./client/
COPY src/schema/ ./schema/
COPY src/voice/ ./voice/
COPY src/streamlit_app.py .

CMD ["streamlit", "run", "streamlit_app.py"]

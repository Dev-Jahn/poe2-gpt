FROM python:3.14-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY src ./src
RUN pip install --no-cache-dir . && useradd --create-home --uid 10001 companion \
    && mkdir -p /home/companion/.cache/poe2-companion /engine-socket /private-builds /build-projections \
    && chown -R companion:companion /home/companion/.cache /engine-socket /private-builds /build-projections \
    && chmod 700 /engine-socket /private-builds /build-projections
USER companion
EXPOSE 8000
ENTRYPOINT ["poe2-companion"]
CMD ["--transport", "streamable-http", "--host", "0.0.0.0"]

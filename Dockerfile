FROM python:3.14-slim
WORKDIR /app
COPY pyproject.toml README.md LICENSE NOTICE ./
COPY requirements.lock.txt ./
COPY src ./src
RUN pip install --no-cache-dir -r requirements.lock.txt && pip install --no-cache-dir --no-deps . && useradd --create-home --uid 10001 companion \
    && mkdir -p /home/companion/.cache/poe2-companion /engine-socket /private-builds /build-projections /character-socket /character-state /account-socket /account-state /account-keys /account-config \
    && chown -R companion:companion /home/companion/.cache /engine-socket /private-builds /build-projections /character-socket /character-state /account-socket /account-state /account-keys /account-config \
    && chmod 700 /engine-socket /private-builds /build-projections /character-socket /character-state /account-socket /account-state /account-keys /account-config \
    && mkdir -p /workflow-state /workflow-keys && chown companion:companion /workflow-state /workflow-keys && chmod 700 /workflow-state /workflow-keys
USER companion
EXPOSE 8000
ENTRYPOINT ["poe2-companion"]
CMD ["--transport", "streamable-http", "--host", "0.0.0.0"]

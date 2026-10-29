FROM python:3.13-slim@sha256:2d44738ebf4ce5f63b9d9ea871e9c7cfdc0426f7b0c97cac915fd88ded1d86bb

ARG VERSION=1.1.2
ARG REVISION
LABEL org.opencontainers.image.title="rdappy" \
      org.opencontainers.image.description="Single-file Python RDAP command-line client" \
      org.opencontainers.image.source="https://github.com/koorg/rdappy" \
      org.opencontainers.image.url="https://github.com/koorg/rdappy" \
      org.opencontainers.image.authors="koorg" \
      org.opencontainers.image.licenses="Artistic-1.0-Perl AND BSD-2-Clause" \
      org.opencontainers.image.version="$VERSION" \
      org.opencontainers.image.revision="$REVISION"

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/nonexistent
WORKDIR /tmp
COPY rdappy.py /opt/rdappy/rdappy.py
COPY LICENSE NOTICE /usr/share/licenses/rdappy/
COPY LICENSES/BSD-2-Clause.txt /usr/share/licenses/rdappy/BSD-2-Clause.txt
USER 65532:65532
ENTRYPOINT ["/usr/local/bin/python3", "/opt/rdappy/rdappy.py"]
CMD ["--help"]

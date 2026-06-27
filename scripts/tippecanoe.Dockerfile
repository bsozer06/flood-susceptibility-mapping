# tippecanoe'yu kaynaktan derleyen yerel imaj (felt fork, .pmtiles ciktisi destekli).
# Kullanim:
#   docker build -t tippecanoe-local -f scripts/tippecanoe.Dockerfile .
FROM ubuntu:22.04 AS build
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential git ca-certificates libsqlite3-dev zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 https://github.com/felt/tippecanoe.git /src
WORKDIR /src
RUN make -j"$(nproc)" && make install

FROM ubuntu:22.04
RUN apt-get update && apt-get install -y --no-install-recommends \
        libsqlite3-0 zlib1g \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /usr/local/bin/tippecanoe* /usr/local/bin/
COPY --from=build /usr/local/bin/tile-join /usr/local/bin/
WORKDIR /work

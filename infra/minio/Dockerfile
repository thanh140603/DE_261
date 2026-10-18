# MinIO's prebuilt registry images are no longer accessible in this setup.
# Build the official, pinned sources instead of relying on a third-party mirror.
FROM golang:1.25-alpine AS build
ENV CGO_ENABLED=0 GOTOOLCHAIN=local

# Limit compilation parallelism for development machines running the whole stack.
# Go's module checksums verify the source dependencies.
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    go install -p 2 -trimpath -ldflags="-s -w" \
      github.com/minio/minio@RELEASE.2025-10-15T17-29-55Z && \
    mkdir -p /licenses && \
    cp "$(go list -m -f '{{.Dir}}' github.com/minio/minio@RELEASE.2025-10-15T17-29-55Z)/LICENSE" \
      /licenses/minio-AGPL-3.0.txt

RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    go install -p 2 -trimpath -ldflags="-s -w" \
      github.com/minio/mc@RELEASE.2025-08-13T08-35-41Z && \
    cp "$(go list -m -f '{{.Dir}}' github.com/minio/mc@RELEASE.2025-08-13T08-35-41Z)/LICENSE" \
      /licenses/mc-AGPL-3.0.txt

FROM alpine:3.22
RUN apk add --no-cache ca-certificates
COPY --from=build /go/bin/minio /go/bin/mc /usr/local/bin/
COPY --from=build /licenses /licenses
EXPOSE 9000 9001
ENTRYPOINT ["minio"]
CMD ["server", "/data", "--console-address", ":9001"]

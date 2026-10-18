#!/bin/sh
# Create the lakehouse buckets on the S3 endpoint (idempotent) and enable versioning on the
# corpus bucket (content context requires strict object versioning). Plain S3 API calls, so
# this works against any S3-compatible store, not only SeaweedFS.
set -eu
: "${S3_ENDPOINT:=http://seaweedfs:8333}"
: "${S3_REGION:=us-east-1}"
SIG="aws:amz:${S3_REGION}:s3"

s3() { curl -sS -o /dev/null -w '%{http_code}' --aws-sigv4 "$SIG" --user "${S3_ACCESS_KEY}:${S3_SECRET_KEY}" "$@"; }

for bucket in lakehouse corpus checkpoints; do
  code=$(s3 -X PUT "${S3_ENDPOINT}/${bucket}")
  case "$code" in 200|409) echo "bucket ${bucket}: ok (${code})" ;; *) echo "bucket ${bucket}: HTTP ${code}" >&2; exit 1 ;; esac
done

code=$(s3 -X PUT "${S3_ENDPOINT}/corpus?versioning" -H 'Content-Type: application/xml' \
  --data '<VersioningConfiguration xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><Status>Enabled</Status></VersioningConfiguration>')
[ "$code" = "200" ] || { echo "versioning on corpus: HTTP ${code}" >&2; exit 1; }
echo "versioning on corpus: enabled"

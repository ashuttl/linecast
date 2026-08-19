#!/bin/zsh
# Upload the baked built-up tile pyramid to the linecast-tiles R2 bucket.
#
# One-time setup (Cloudflare dashboard):
#   1. R2 → enable R2 on the account (accepts terms; free tier).
#   2. R2 → Manage API tokens → Create API token
#        - permission: Object Read & Write, scoped to bucket linecast-tiles
#        - copy the Access Key ID / Secret Access Key it shows
#   3. brew install rclone
#
# Then run:
#   R2_ACCOUNT_ID=<account id> \
#   R2_ACCESS_KEY_ID=<access key> \
#   R2_SECRET_ACCESS_KEY=<secret> \
#   scripts/upload_builtup_tiles.sh ~/Developer/linecast-tiles
#
# rclone syncs idempotently — rerun any time; only changed tiles move.
set -euo pipefail

SRC="${1:?usage: upload_builtup_tiles.sh <tile dir>}"
: "${R2_ACCOUNT_ID:?set R2_ACCOUNT_ID}"
: "${R2_ACCESS_KEY_ID:?set R2_ACCESS_KEY_ID}"
: "${R2_SECRET_ACCESS_KEY:?set R2_SECRET_ACCESS_KEY}"

exec rclone sync "$SRC" ":s3:linecast-tiles" \
    --s3-provider Cloudflare \
    --s3-endpoint "https://${R2_ACCOUNT_ID}.r2.cloudflarestorage.com" \
    --s3-access-key-id "$R2_ACCESS_KEY_ID" \
    --s3-secret-access-key "$R2_SECRET_ACCESS_KEY" \
    --s3-no-check-bucket \
    --exclude ".done" --exclude "build.log" \
    --header-upload "Content-Type: image/png" \
    --header-upload "Cache-Control: public, max-age=31536000, immutable" \
    --transfers 32 --checkers 32 --fast-list --progress

#!/usr/bin/env bash
set -euo pipefail

repository_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
hook_source="$repository_root/.githooks/pre-commit"
test_root=$(mktemp -d)
trap 'rm -rf -- "$test_root"' EXIT

new_repository() {
  local name=$1
  local path="$test_root/$name"
  mkdir -p "$path/.githooks"
  git -C "$path" init -q
  git -C "$path" config user.name 'Harness Test'
  git -C "$path" config user.email 'harness-test@example.invalid'
  cp "$hook_source" "$path/.githooks/pre-commit"
  chmod +x "$path/.githooks/pre-commit"
  git -C "$path" config core.hooksPath .githooks
  printf '%s\n' "$path"
}

expect_rejected() {
  local path=$1
  local label=$2
  if git -C "$path" commit -m "$label" >/dev/null 2>&1; then
    printf 'expected commit rejection: %s\n' "$label" >&2
    exit 1
  fi
}

allowed_repository=$(new_repository allowed-env-example)
printf '%s\n' 'EXAMPLE_VALUE=' >"$allowed_repository/.env.example"
git -C "$allowed_repository" add -- .env.example
git -C "$allowed_repository" commit -qm 'allow env example'

secret_repository=$(new_repository reject-secret-name)
printf '%s\n' 'SECRET_VALUE=redacted' >"$secret_repository/.env"
git -C "$secret_repository" add -f -- .env
expect_rejected "$secret_repository" 'reject secret filename'

key_repository=$(new_repository reject-private-key)
printf '%s%s\n' '-----BEGIN PRIVATE ' 'KEY-----' >"$key_repository/accidental.txt"
git -C "$key_repository" add -- accidental.txt
expect_rejected "$key_repository" 'reject private key marker'

whitespace_repository=$(new_repository reject-whitespace)
printf 'trailing whitespace  \n' >"$whitespace_repository/whitespace.txt"
git -C "$whitespace_repository" add -- whitespace.txt
expect_rejected "$whitespace_repository" 'reject whitespace error'

printf '%s\n' 'pre-commit behavior tests passed.'

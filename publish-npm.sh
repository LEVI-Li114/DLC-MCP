#!/usr/bin/env bash
set -euo pipefail

PACKAGE="@levisli/dlc-mcp"
REGISTRY="https://registry.npmjs.org/"
USERCONFIG=()
TMP_NPMRC=""

cleanup() {
  if [ -n "$TMP_NPMRC" ] && [ -f "$TMP_NPMRC" ]; then
    rm -f "$TMP_NPMRC"
  fi
}
trap cleanup EXIT

if [ -n "${NPM_TOKEN:-}" ]; then
  TMP_NPMRC=$(mktemp)
  printf 'registry=%s\n//registry.npmjs.org/:_authToken=${NPM_TOKEN}\n' "$REGISTRY" > "$TMP_NPMRC"
  chmod 600 "$TMP_NPMRC"
  USERCONFIG=(--userconfig "$TMP_NPMRC")
  echo "using temporary npm token config"
fi

if [ "$(npm "${USERCONFIG[@]}" config get registry)" != "$REGISTRY" ]; then
  echo "npm registry must be $REGISTRY" >&2
  echo "run: npm config set registry $REGISTRY" >&2
  exit 1
fi

if ! npm "${USERCONFIG[@]}" whoami >/dev/null; then
  echo "not logged in to npm; run npm login or set NPM_TOKEN" >&2
  exit 1
fi

name=$(node -p "require('./package.json').name")
if [ "$name" != "$PACKAGE" ]; then
  echo "package name mismatch: expected $PACKAGE, got $name" >&2
  exit 1
fi

if npm "${USERCONFIG[@]}" view "$PACKAGE" >/dev/null 2>&1; then
  echo "$PACKAGE exists. Choose version bump:"
  echo "1. patch"
  echo "2. minor"
  echo "3. major"
  read -r -p "1/2/3: " bump
  case "$bump" in
    1) npm version patch --no-git-tag-version ;;
    2) npm version minor --no-git-tag-version ;;
    3) npm version major --no-git-tag-version ;;
    *) echo "cancelled"; exit 1 ;;
  esac
fi

version=$(node -p "require('./package.json').version")
echo "publishing $PACKAGE@$version"
npm "${USERCONFIG[@]}" publish --access public
echo "published https://www.npmjs.com/package/$PACKAGE"

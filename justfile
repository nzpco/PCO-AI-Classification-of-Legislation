set dotenv-filename:= "_env"
set dotenv-load
APP_NAME := `uv run python -c "import toml; print(toml.load('fly.toml')['app'])"`

# HELP!
help:
  just --list

# sync and update python packages
sync:
  uv sync -U

# Run the streamlit app
sl:
  streamlit run app.py --server.headless true

# Build docker image
build:
  docker build -t pco-ui:latest .

# Run inside docker (for testing)
run:
  docker run \
    --rm \
    --env-file _env \
    -p 8501:8501 \
    pco-ui:latest

# Upload all data to the fly volume
upload-all:
  deploy/rsync-data $KUZU_PATH /data/kuzu
  deploy/rsync-data $LANCE_PATH /data/lance

upload-auth:
  deploy/rsync-data $AUTH_PATH /data/auth

# Versioning {{{

# Bump python version in toml and lock
_bump-version:
  @uv version --bump minor
  @uv lock

# Check only version and lock files have changed
_check-versions-changed:
  #!/usr/bin/env python3
  import subprocess, sys, re
  out = subprocess.check_output(["git", "status", "--porcelain"], text=True)
  files = [line.split()[1] for line in out.splitlines()]
  expected = {"pyproject.toml", "uv.lock"}
  if not files:
      sys.exit("⛔️  No changes to commit.")
  bad = set(files) - expected
  if bad:
      sys.exit(f"⛔️  Unexpected file(s): {', '.join(bad)}")

# Push a bumped version
_commit-version: _check-versions-changed
  @echo "Committing version bump"
  @git add pyproject.toml uv.lock
  @git commit -m "Bump version to `uv version --short`"

# Fail if git working directory isn’t clean
_ensure-clean:
  #!/usr/bin/env bash
  if [ -n "$(git status --porcelain)" ]; then
    echo "⛔️  Uncommitted changes detected. Commit or stash before releasing." >&2
    exit 1
  fi

# Make a new release version (minor)
make-release: _bump-version _commit-version
  @echo "Release ready to go!"

# Push a new release version (minor)
push-release: _ensure-clean
  git push && git push --tags
  gh release create v`uv version --short` --generate-notes

# }}}

#!/usr/bin/env bash
# Update uv version across all required files in the repository.
#
# Usage:
#   ./tools/update-uv-version.sh <new-version> [sha256-digest]
#
# Examples:
#   ./tools/update-uv-version.sh 0.11.0
#   ./tools/update-uv-version.sh 0.11.0 abc123def456...
#
# If the sha256 digest is not provided, it will be fetched automatically
# using skopeo or docker (one of them must be installed).

set -euo pipefail

NEW_VERSION="${1:?Usage: $0 <new-version> [sha256-digest]}"
DIGEST="${2:-}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="ghcr.io/astral-sh/uv"
IMAGE_TAG="${IMAGE}:${NEW_VERSION}"

DOCKERFILES=(
    "${REPO_ROOT}/dockerfiles/Dockerfile"
    "${REPO_ROOT}/qontract_api/Dockerfile"
    "${REPO_ROOT}/qontract_api_client/Dockerfile"
    "${REPO_ROOT}/qontract_utils/Dockerfile"
)

# ---------------------------------------------------------------------------
# Fetch digest if not provided
# ---------------------------------------------------------------------------
if [[ -z "$DIGEST" ]]; then
    echo "Fetching digest for ${IMAGE_TAG}..."
    if command -v skopeo &>/dev/null; then
        DIGEST=$(skopeo inspect --raw "docker://${IMAGE_TAG}" | sha256sum | awk '{print $1}')
    elif command -v docker &>/dev/null; then
        DIGEST=$(docker buildx imagetools inspect --raw "${IMAGE_TAG}" | sha256sum | awk '{print $1}')
    else
        echo "Error: skopeo or docker is required to fetch the image digest automatically." >&2
        echo "Install one of them, or pass the sha256 digest as a second argument." >&2
        exit 1
    fi
    echo "Digest: sha256:${DIGEST}"
fi

# Strip optional "sha256:" prefix
DIGEST="${DIGEST#sha256:}"
FULL_IMAGE_REF="${IMAGE_TAG}@sha256:${DIGEST}"

# ---------------------------------------------------------------------------
# Detect current version for the status message
# ---------------------------------------------------------------------------
OLD_VERSION=$(grep -oE 'ghcr\.io/astral-sh/uv:[0-9]+\.[0-9]+\.[0-9]+' \
    "${DOCKERFILES[0]}" | head -1 | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' || echo "unknown")

echo "Updating uv: ${OLD_VERSION} → ${NEW_VERSION} (sha256:${DIGEST})"
echo ""

# ---------------------------------------------------------------------------
# Helper: portable in-place sed (works on macOS and Linux)
# ---------------------------------------------------------------------------
inplace_sed() {
    local pattern="$1"
    local file="$2"
    sed -i.uvbak "$pattern" "$file"
    rm -f "${file}.uvbak"
}

# ---------------------------------------------------------------------------
# Update Dockerfiles
# ---------------------------------------------------------------------------
UV_IMAGE_PATTERN='ghcr\.io/astral-sh/uv:[0-9][0-9.]*@sha256:[a-f0-9]+'

for dockerfile in "${DOCKERFILES[@]}"; do
    if [[ -f "$dockerfile" ]]; then
        inplace_sed "s|ghcr\.io/astral-sh/uv:[0-9][0-9.]*@sha256:[a-f0-9]*|${FULL_IMAGE_REF}|g" "$dockerfile"
        echo "Updated: ${dockerfile#"${REPO_ROOT}/"}"
    fi
done

# ---------------------------------------------------------------------------
# Update pyproject.toml  [tool.uv] required-version
# ---------------------------------------------------------------------------
PYPROJECT="${REPO_ROOT}/pyproject.toml"
inplace_sed "s|required-version = \">=.*\"|required-version = \">=${NEW_VERSION}\"|" "$PYPROJECT"
echo "Updated: pyproject.toml"

# ---------------------------------------------------------------------------
# Update renovate.json  constraints.uv
# ---------------------------------------------------------------------------
RENOVATE="${REPO_ROOT}/renovate.json"
inplace_sed "s|\"uv\": \"[0-9][0-9.]*\"|\"uv\": \"${NEW_VERSION}\"|" "$RENOVATE"
echo "Updated: renovate.json"

echo ""
echo "Done. uv updated to ${NEW_VERSION}."
echo "Review the changes with: git diff"

#!/usr/bin/env bash
# Per-boot GitNexus index refresh for Cursor Cloud Agents.
# Failures of analysis/index validation remove .gitnexus and still exit 0.
set -euo pipefail

GITNEXUS_VERSION="1.6.10"
SYSTEM_LAUNCHER="/usr/local/bin/gitnexus"

log() {
    echo "[gitnexus] $*"
}

discard_index() {
    local reason="$1"
    log "${reason}"
    log "removing .gitnexus and continuing"
    rm -rf .gitnexus
    exit 0
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

log "start beginning in ${REPO_ROOT}"

if [[ ! -f .nvmrc ]]; then
    log "ERROR: .nvmrc is missing at ${REPO_ROOT}/.nvmrc"
    exit 1
fi

NODE_VERSION="$(sed -e 's/#.*//' -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' .nvmrc)"
if [[ -z "${NODE_VERSION}" ]]; then
    log "ERROR: .nvmrc did not contain a Node version"
    exit 1
fi
log "nvmrc Node version: ${NODE_VERSION}"

export NVM_DIR="${HOME}/.nvm"
if [[ ! -s "${NVM_DIR}/nvm.sh" ]]; then
    log "ERROR: NVM not found at ${NVM_DIR}/nvm.sh"
    exit 1
fi
# shellcheck disable=SC1091
. "${NVM_DIR}/nvm.sh"

nvm use "${NODE_VERSION}"
NODE_BIN="$(nvm which "${NODE_VERSION}")"
log "using Node ${NODE_BIN} ($("${NODE_BIN}" --version))"

if [[ ! -x "${SYSTEM_LAUNCHER}" ]]; then
    log "ERROR: ${SYSTEM_LAUNCHER} does not exist"
    exit 1
fi
log "launcher present: ${SYSTEM_LAUNCHER}"

VERSION_RAW="$("${SYSTEM_LAUNCHER}" --version 2>&1)"
VERSION="$(printf '%s\n' "${VERSION_RAW}" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n 1 || true)"
if [[ "${VERSION}" != "${GITNEXUS_VERSION}" ]]; then
    log "ERROR: expected GitNexus ${GITNEXUS_VERSION}, got: ${VERSION_RAW}"
    exit 1
fi
log "version ok: ${VERSION}"

log "running analyze --skip-agents-md --skip-skills"
set +e
"${SYSTEM_LAUNCHER}" analyze --skip-agents-md --skip-skills
ANALYZE_RC=$?
set -e
if [[ "${ANALYZE_RC}" -ne 0 ]]; then
    discard_index "analyze failed with exit ${ANALYZE_RC}"
fi

META=".gitnexus/gitnexus.json"
if [[ ! -f "${META}" ]]; then
    discard_index "missing ${META} after analyze"
fi

HEAD_SHA="$(git rev-parse HEAD)"
INDEXED_SHA="$(
    python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("lastCommit") or "")' "${META}"
)"
if [[ -z "${INDEXED_SHA}" ]]; then
    discard_index "${META} has empty lastCommit"
fi
if [[ "${INDEXED_SHA}" != "${HEAD_SHA}" ]]; then
    discard_index "lastCommit ${INDEXED_SHA} != HEAD ${HEAD_SHA}"
fi
log "index lastCommit matches HEAD ${HEAD_SHA}"

log "gitnexus status"
set +e
"${SYSTEM_LAUNCHER}" status
STATUS_RC=$?
set -e
if [[ "${STATUS_RC}" -ne 0 ]]; then
    discard_index "gitnexus status failed with exit ${STATUS_RC}"
fi

log "gitnexus list"
set +e
"${SYSTEM_LAUNCHER}" list
LIST_RC=$?
set -e
if [[ "${LIST_RC}" -ne 0 ]]; then
    discard_index "gitnexus list failed with exit ${LIST_RC}"
fi

log "start complete"

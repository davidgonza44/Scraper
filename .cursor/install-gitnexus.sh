#!/usr/bin/env bash
# Idempotent GitNexus 1.6.10 install for Cursor Cloud Agents.
# Uses the Node version from .nvmrc via NVM, never PATH's default node.
set -euo pipefail

GITNEXUS_VERSION="1.6.10"
NPM_GLOBAL="${HOME}/.npm-global"
CLI_JS="${NPM_GLOBAL}/lib/node_modules/gitnexus/dist/cli/index.js"
USER_LAUNCHER="${NPM_GLOBAL}/bin/gitnexus"
SYSTEM_LAUNCHER="/usr/local/bin/gitnexus"

log() {
    echo "[gitnexus] $*"
}

ensure_git_worktree() {
    if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
        log "ERROR: ${REPO_ROOT} is not a git worktree"
        exit 1
    fi
}

ensure_gitnexus_exclude() {
    local exclude_file exclude_parent
    exclude_file="$(git rev-parse --git-path info/exclude)"
    exclude_parent="$(dirname "${exclude_file}")"
    mkdir -p "${exclude_parent}"
    touch "${exclude_file}"
    if grep -qxF '.gitnexus/' "${exclude_file}"; then
        log ".gitnexus/ already listed in ${exclude_file}"
    else
        echo '.gitnexus/' >> "${exclude_file}"
        log "added .gitnexus/ to ${exclude_file}"
    fi
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${REPO_ROOT}"

if [[ "${GITNEXUS_CLOUD_PHASE:-}" == "ensure-exclude" ]]; then
    ensure_git_worktree
    ensure_gitnexus_exclude
    exit 0
fi

log "install starting in ${REPO_ROOT}"

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

log "installing Node ${NODE_VERSION} via nvm if needed"
nvm install "${NODE_VERSION}"
nvm use "${NODE_VERSION}"

NODE_BIN="$(nvm which "${NODE_VERSION}")"
if [[ -z "${NODE_BIN}" || ! -x "${NODE_BIN}" ]]; then
    log "ERROR: nvm did not provide a Node binary for ${NODE_VERSION}"
    exit 1
fi
if [[ "${NODE_BIN}" != "${NVM_DIR}/"* ]]; then
    log "ERROR: Node binary is not under NVM: ${NODE_BIN}"
    exit 1
fi
NPM_BIN="$(dirname "${NODE_BIN}")/npm"
if [[ ! -x "${NPM_BIN}" ]]; then
    log "ERROR: npm not found next to Node at ${NPM_BIN}"
    exit 1
fi
# npm's shebang is `#!/usr/bin/env node`. Without nvm first on PATH it
# picks /exec-daemon/node (v22.14.0) and skips GitNexus native scripts.
export PATH="$(dirname "${NODE_BIN}"):${PATH}"
hash -r
log "using Node ${NODE_BIN} ($("${NODE_BIN}" --version))"
log "using npm ${NPM_BIN} ($("${NPM_BIN}" --version))"
log "PATH node is $(command -v node) ($(node --version))"

mkdir -p "${NPM_GLOBAL}/bin" "${NPM_GLOBAL}/lib"
log "installing gitnexus@${GITNEXUS_VERSION} under ${NPM_GLOBAL}"
# Replace any previous bin symlink/launcher first so a later write cannot
# follow npm's bin -> dist/cli/index.js link and overwrite the CLI.
rm -f "${USER_LAUNCHER}"
"${NPM_BIN}" uninstall -g --prefix "${NPM_GLOBAL}" gitnexus >/dev/null 2>&1 || true
"${NPM_BIN}" install -g --prefix "${NPM_GLOBAL}" \
    "gitnexus@${GITNEXUS_VERSION}"

if [[ ! -f "${CLI_JS}" ]]; then
    log "ERROR: GitNexus CLI missing at ${CLI_JS}"
    exit 1
fi
if grep -q 'set -euo pipefail' "${CLI_JS}"; then
    log "ERROR: CLI entrypoint looks like a shell launcher, not JavaScript: ${CLI_JS}"
    exit 1
fi
log "CLI entrypoint: ${CLI_JS}"

log "writing stable launcher ${USER_LAUNCHER}"
# npm install -g recreates bin/gitnexus as a symlink to the JS CLI. Remove
# that symlink without following it, then write a regular file.
LAUNCHER_TMP="$(mktemp)"
cat > "${LAUNCHER_TMP}" <<EOF
#!/usr/bin/env bash
set -euo pipefail
exec $(printf '%q' "${NODE_BIN}") $(printf '%q' "${CLI_JS}") "\$@"
EOF
chmod 0755 "${LAUNCHER_TMP}"
rm -f "${USER_LAUNCHER}"
mv "${LAUNCHER_TMP}" "${USER_LAUNCHER}"
if [[ -L "${USER_LAUNCHER}" ]]; then
    log "ERROR: ${USER_LAUNCHER} is still a symlink; refusing to follow it"
    exit 1
fi
if grep -q 'set -euo pipefail' "${CLI_JS}"; then
    log "ERROR: writing the launcher overwrote ${CLI_JS}"
    exit 1
fi

log "exposing launcher at ${SYSTEM_LAUNCHER}"
sudo install -m 0755 "${USER_LAUNCHER}" "${SYSTEM_LAUNCHER}"

ensure_git_worktree
ensure_gitnexus_exclude

log "verifying ${SYSTEM_LAUNCHER} --version == ${GITNEXUS_VERSION}"
VERSION_RAW="$("${SYSTEM_LAUNCHER}" --version 2>&1)"
VERSION="$(printf '%s\n' "${VERSION_RAW}" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' | head -n 1 || true)"
if [[ "${VERSION}" != "${GITNEXUS_VERSION}" ]]; then
    log "ERROR: expected GitNexus ${GITNEXUS_VERSION}, got: ${VERSION_RAW}"
    exit 1
fi
log "version ok: ${VERSION}"

log "running analyze --skip-agents-md --skip-skills"
"${SYSTEM_LAUNCHER}" analyze --skip-agents-md --skip-skills

log "install complete"

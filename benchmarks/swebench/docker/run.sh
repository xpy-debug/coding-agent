#!/usr/bin/env bash
#
# Run a command inside the SWE-bench harness image.
#
#   ./docker/run.sh python select_instances.py --count 15
#   ./docker/run.sh ./evaluate.sh
#
# The host's Docker socket is mounted so the harness can create the per-instance
# containers as siblings, rather than trying (and failing) to nest a daemon.

set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "${here}/.." && pwd)"
image="${SWEBENCH_IMAGE:-coding-swebench-harness}"

if ! docker image inspect "${image}" >/dev/null 2>&1; then
    echo "Building ${image} (first run only)..."
    docker build -t "${image}" "${here}"
fi

tty_args=()
if [ -t 0 ] && [ -t 1 ]; then
    tty_args=(-t)
fi

# Forward the HuggingFace token when one is set, so dataset loads inside the
# container are authenticated instead of hitting the anonymous rate limit. The
# container cannot see the host environment, so this has to be explicit.
hf_env=()
if [ -n "${HF_TOKEN:-}" ]; then
    hf_env=(-e "HF_TOKEN=${HF_TOKEN}")
fi

# DOCKER_HOST is forced to the unix socket. Inheriting the host's value would
# hand the container a Windows npipe path (npipe:////./pipe/docker_engine),
# which does not exist inside the Linux container even though the socket does.
exec docker run --rm -i "${tty_args[@]}" \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v "${root}:/work" \
    -w /work \
    -e DOCKER_HOST=unix:///var/run/docker.sock \
    "${hf_env[@]}" \
    "${image}" "$@"

# Official SWE-bench harness environment.
#
# This image only *drives* the evaluation: it loads the dataset and, for each
# instance, creates/pulls a container and runs the tests inside it. The instance
# containers are siblings on the host daemon, so the Docker socket must be
# bind-mounted (see run.sh / run.ps1).
#
# Python 3.11 rather than the repo's 3.14: `swebench` needs 3.10+, and 3.11 is
# what the official docs assume. The two environments never share a process.

# Base images are build args because docker.io is not reachable from every
# network. Where it is blocked, pass mirrors that proxy the library namespace,
# e.g. --build-arg BASE_IMAGE=docker.m.daocloud.io/library/python:3.11-slim
ARG BASE_IMAGE=python:3.11-slim
ARG DOCKER_CLI_IMAGE=docker:cli

# The harness shells out to the `docker` CLI for container cleanup
# (docker_utils.cleanup_container runs `docker stop`/`kill`/`rm`), so the binary
# has to exist in this image. Copying the official static binary is deliberate:
# the distro package name is not stable -- Debian 13 ships the daemon as
# `docker.io` and splits the CLI into `docker-cli`, while older releases put both
# in `docker.io` -- so `apt-get install docker.io` silently yields an image with
# no CLI at all, and every instance then fails in cleanup.
FROM ${DOCKER_CLI_IMAGE} AS dockercli

FROM ${BASE_IMAGE}

ENV PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    SWEBENCH_REPO=/opt/SWE-bench

# git: to clone the harness. ca-certificates: TLS for Hugging Face + image pulls.
# build-essential: a few wheels still compile at install time.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        git \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY --from=dockercli /usr/local/bin/docker /usr/local/bin/docker

# HTTPS, not the SSH URL the official docs show: no key material in the image.
RUN git clone --depth 1 https://github.com/SWE-bench/SWE-bench.git "${SWEBENCH_REPO}" \
    && rm -rf "${SWEBENCH_REPO}/.git"

RUN pip install -e "${SWEBENCH_REPO}" \
    && pip install "datasets>=2.14"

# Evaluation logs land in <cwd>/logs; the runner's work dir is mounted here.
WORKDIR /work

# Fail fast and loudly if the socket was not mounted or the CLI is missing.
CMD ["bash", "-lc", "docker --version && python -c \"import docker; docker.from_env().version(); print('docker daemon reachable')\""]

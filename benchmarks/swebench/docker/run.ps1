# Run a command inside the SWE-bench harness image (Windows PowerShell).
#
#   .\docker\run.ps1 python select_instances.py --count 15
#   .\docker\run.ps1 ./evaluate.sh
#
# PowerShell equivalent of run.sh. Same socket mount, same forced DOCKER_HOST.

$ErrorActionPreference = 'Stop'

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
$image = if ($env:SWEBENCH_IMAGE) { $env:SWEBENCH_IMAGE } else { 'coding-swebench-harness' }

docker image inspect $image *> $null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Building $image (first run only)..."
    docker build -t $image $here
    if ($LASTEXITCODE -ne 0) { throw 'docker build failed' }
}

# Forward the HuggingFace token when one is set, so dataset loads inside the
# container are authenticated instead of hitting the anonymous rate limit.
# The container cannot see the host's environment, so this has to be explicit.
$hfArgs = @()
if ($env:HF_TOKEN) { $hfArgs = @('-e', "HF_TOKEN=$env:HF_TOKEN") }

# DOCKER_HOST is forced to the unix socket inside the container. Inheriting the
# host value would pass a Windows npipe path that does not exist in the Linux
# container, even though /var/run/docker.sock is mounted and working.
docker run --rm -i `
    -v /var/run/docker.sock:/var/run/docker.sock `
    -v "${root}:/work" `
    -w /work `
    -e DOCKER_HOST=unix:///var/run/docker.sock `
    @hfArgs `
    $image @args

exit $LASTEXITCODE

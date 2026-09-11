# azd postprovision hook — the data-plane artifacts, without Python.
#
# Bicep in infra/ has already created the account, project, model deployments,
# the guardrail, the project connections, and the RBAC the memory store needs.
# Those values arrive here as azd environment variables via Bicep outputs.
#
# This script creates what has no ARM type, in dependency order:
#   1. skills        azd ai skill create
#   2. toolbox       azd ai toolbox create   (tools + skills + MCP + guardrail)
#   3. memory store  az rest                 (no CLI command group exists)
#   4. prompt agent  az rest                 (toolbox tool + memory tool)
#
# azd then deploys the hosted agent, which uses the same toolbox, guardrail,
# and memory store.

$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$iac = Join-Path $root 'iac'
$rendered = Join-Path ([System.IO.Path]::GetTempPath()) "telco-iac-$PID"
New-Item -ItemType Directory -Force -Path $rendered | Out-Null

# Values not produced by Bicep. azd env values win when already set.
function Default-Env($name, $value) {
    if (-not [Environment]::GetEnvironmentVariable($name)) {
        [Environment]::SetEnvironmentVariable($name, $value)
    }
}
Default-Env 'MEMORY_STORE_NAME'   'telco-memory'
Default-Env 'PROMPT_AGENT_NAME'   'telco-prompt-agent'
Default-Env 'TOOLBOX_SERVER_LABEL' 'telcotoolbox'
Default-Env 'TOOLBOX_NAME'        'telco-toolbox'

$projectEndpoint = $env:AZURE_AI_PROJECT_ENDPOINT
if (-not $projectEndpoint) { throw 'AZURE_AI_PROJECT_ENDPOINT is not set. Run azd provision first.' }
$projectEndpoint = $projectEndpoint.TrimEnd('/')
$env:TOOLBOX_MCP_URL = "$projectEndpoint/toolboxes/$($env:TOOLBOX_NAME)/mcp?api-version=v1"

# Preview features the data plane requires.
$features = 'Skills=V1Preview, Toolboxes=V1Preview, MemoryStores=V1Preview'

function Render($fileName) {
    <# Replace @@TOKEN@@ with the matching environment variable. #>
    $text = Get-Content (Join-Path $iac $fileName) -Raw
    foreach ($match in [regex]::Matches($text, '@@([A-Z0-9_]+)@@')) {
        $name = $match.Groups[1].Value
        $value = [Environment]::GetEnvironmentVariable($name)
        if (-not $value) { throw "Template $fileName needs $name but it is not set." }
        $text = $text.Replace($match.Value, $value)
    }
    $out = Join-Path $rendered $fileName
    # ASCII, single line where possible: az rest --body @file is sensitive to encoding.
    Set-Content -Path $out -Value $text -Encoding ascii
    return $out
}

function Invoke-DataPlane($method, $path, $bodyFile) {
    $url = "$projectEndpoint/$path"
    $args = @(
        'rest', '--method', $method,
        '--resource', 'https://ai.azure.com',
        '--url', $url,
        '--headers', 'Content-Type=application/json', "Foundry-Features=$features"
    )
    if ($bodyFile) { $args += @('--body', "@$bodyFile") }
    az @args
    if ($LASTEXITCODE -ne 0) { throw "$method $path failed." }
}

Write-Host "`n===== 1/4  Skills =====" -ForegroundColor Cyan
foreach ($dir in Get-ChildItem (Join-Path $root 'skills') -Directory) {
    if (-not (Test-Path (Join-Path $dir.FullName 'SKILL.md'))) { continue }
    # `create --force` deletes first, which needs agents/delete. Update the
    # existing skill instead so the hook works with create-only permissions.
    az rest --method get --resource 'https://ai.azure.com' `
        --url "$projectEndpoint/skills/$($dir.Name)?api-version=v1" `
        --headers "Foundry-Features=$features" *> $null
    $verb = if ($LASTEXITCODE -eq 0) { 'update' } else { 'create' }
    Write-Host "  $($dir.Name) ($verb)"
    azd ai skill $verb $dir.Name --file $dir.FullName --no-prompt --project-endpoint $projectEndpoint
    if ($LASTEXITCODE -ne 0) { throw "skill $verb failed for $($dir.Name)" }
}

Write-Host "`n===== 2/4  Toolbox =====" -ForegroundColor Cyan
$toolboxFile = Render 'toolbox.yaml'
azd ai toolbox create $env:TOOLBOX_NAME --from-file $toolboxFile --no-prompt --project-endpoint $projectEndpoint
if ($LASTEXITCODE -ne 0) { throw 'toolbox create failed.' }

Write-Host "`n===== 3/4  Memory store =====" -ForegroundColor Cyan
$memoryFile = Render 'memory-store.json'
$existing = az rest --method get --resource 'https://ai.azure.com' `
    --url "$projectEndpoint/memory_stores/$($env:MEMORY_STORE_NAME)?api-version=v1" `
    --headers "Foundry-Features=$features" 2>$null
if ($LASTEXITCODE -eq 0 -and $existing) {
    Write-Host "  '$($env:MEMORY_STORE_NAME)' already exists; leaving it as is."
} else {
    Invoke-DataPlane 'post' 'memory_stores?api-version=v1' $memoryFile
}

Write-Host "`n===== 4/4  Prompt agent =====" -ForegroundColor Cyan
$agentFile = Render 'prompt-agent.json'
Invoke-DataPlane 'post' 'agents?api-version=v1' $agentFile

Remove-Item $rendered -Recurse -Force -ErrorAction SilentlyContinue
Write-Host "`nPostprovision complete. azd now deploys the hosted agent." -ForegroundColor Green

# MDAS-MCP-Client launcher (hosted MCP via config.aws.json).
# Usage:
#   .\run-proxy.ps1              # stdio bridge (blocks; same as Cursor)
#   .\run-proxy.ps1 -HandoffOnly # browser login + save tokens, then exit
#   .\run-proxy.ps1 -ForceHandoff # ignore saved tokens, open browser again

param(
    [switch]$HandoffOnly,
    [switch]$ForceHandoff,
    [string]$Config = "config.aws.json"
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root

$configPath = Join-Path $Root $Config
if (-not (Test-Path $configPath)) {
    Write-Error "Config not found: $configPath (copy config.example.json or use -Config)"
}

$env:MDAS_CONFIG_PATH = $configPath
if ($ForceHandoff) {
    $env:MDAS_FORCE_HANDOFF = "1"
}

# Default dev hosted MCP; override in mcp.json env if your admin gives another URL.
if (-not $env:MDAS_MCP_HTTP_URL) {
    $env:MDAS_MCP_HTTP_URL = "https://mdas-mcp-dev.viewtrade.dev/mcp/"
}

$proxyArgs = @(
    (Join-Path $Root "mcp_stdio_proxy.py"),
    "--config", $configPath
)

if ($HandoffOnly) {
    $proxyArgs += @("--handoff-only", "--timeout", "300")
}

Write-Host "MDAS MCP client proxy"
Write-Host "  config: $configPath"
Write-Host "  MCP URL: $env:MDAS_MCP_HTTP_URL"
Write-Host ""

python @proxyArgs

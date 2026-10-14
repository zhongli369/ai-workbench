# AI Workbench — GitHub publish entry (Windows PowerShell)
#
# Thin wrapper around tools/release_publish.sh (single source of truth).
# Locates Git Bash (installed with Git for Windows), then runs the bash
# publisher with the same arguments. Resumable / idempotent / non-destructive
# — see the .sh header for exit codes and resume semantics.
#
# Usage:
#   pwsh tools/release_publish.ps1                 # run / resume
#   pwsh tools/release_publish.ps1 --reset-state   # discard resume state
#   $env:RELAY = ''                                # go direct (no relay)
#
# Prerequisite (once, on a trusted network):
#   gh auth login -h github.com -p https -w
[CmdletBinding()]
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$ScriptArgs)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

$candidates = @(
    (Get-Command bash.exe -ErrorAction SilentlyContinue).Source,
    "$env:ProgramFiles\Git\bin\bash.exe",
    "${env:ProgramFiles(x86)}\Git\bin\bash.exe"
) | Where-Object { $_ -and (Test-Path $_) }

if (-not $candidates) {
    Write-Error @"
Git Bash not found. AI Workbench's publisher is a bash script (tools/release_publish.sh).
Install Git for Windows (https://git-scm.com/download/win) — it provides bash.exe —
or run the script from WSL:  bash tools/release_publish.sh
"@
    exit 2
}
$bash = $candidates[0]

$script = ($PSScriptRoot -replace '\\', '/') + '/release_publish.sh'
if ($script -match '^([A-Za-z]):') { $script = "/$($Matches[1].ToLower())" + $script.Substring(2) }

& $bash $script @ScriptArgs
exit $LASTEXITCODE

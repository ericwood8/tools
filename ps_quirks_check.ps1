<#
.SYNOPSIS
Shows two PowerShell behaviours that silently break scripts, in whichever PowerShell runs it.

.DESCRIPTION
  1. '| Select-Object -First N' stops the commands that feed it, so a script piped into it can end before its work is done.
     The check writes a marker file after the first output line and reports whether it exists afterwards,
     once with the pipe and once with '*> $null'.
  2. Windows PowerShell 5.1 drops double quotes inside an argument passed to a native program; PowerShell 7 keeps them.
     The check passes 'say "hello" now' to a small Python program that prints the argument it received, once as an argument
     and once on stdin. Needs python on PATH; without it this part is skipped.

Run it in each shell you care about:
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File ps_quirks_check.ps1
  pwsh -NoProfile -File ps_quirks_check.ps1

Expected on this machine's versions (checked 2026-10-29): in both, the pipe case has no marker and the '*> $null' case has one;
5.1 receives 'say hello now' (quotes lost), 7 receives 'say "hello" now'; stdin keeps the quotes in both.
Exit code 0 when the checks ran, 2 when python was needed and is missing (the first check still runs).
#>
param()

Write-Host ("PowerShell " + $PSVersionTable.PSVersion + " (" + $PSVersionTable.PSEdition + ")")

# 1. Select-Object -First stops the upstream commands
$marker = Join-Path ([IO.Path]::GetTempPath()) ('ps_quirks_' + [guid]::NewGuid().ToString('N') + '.txt')
$global:QuirksMarker = $marker
function Emit-Work {
    'line1'
    'line2'
    Set-Content -Path $global:QuirksMarker -Value 'work after the first output line'
    'line3'
}
$null = Emit-Work | Select-Object -First 1
$afterPipe = Test-Path $marker
Remove-Item $marker -ErrorAction SilentlyContinue
Emit-Work *> $null
$afterRedirect = Test-Path $marker
Remove-Item $marker -ErrorAction SilentlyContinue
Write-Host ("  '| Select-Object -First 1': work after the first line ran = $afterPipe   (False means the script was stopped)")
Write-Host ("  '*> `$null':               work after the first line ran = $afterRedirect")

# 2. Double quotes in a native-command argument
$pyWorks = $false
if (Get-Command python -ErrorAction SilentlyContinue) {
    $probeRun = & python -c 'print(41 + 1)' 2>$null
    $pyWorks = ("$probeRun".Trim() -eq '42')
}
if (-not $pyWorks) {
    Write-Host "  native argument check skipped: a working python is not on PATH (the Windows Store alias does not count)"
    exit 2
}
$probe = 'import sys; print(sys.argv[1] if len(sys.argv) > 1 else sys.stdin.read().strip())'
$text = 'say "hello" now'
$asArgument = & python -c $probe $text
$onStdin = $text | & python -c $probe
Write-Host ("  as an argument, python received: " + $asArgument + "   (quotes kept = " + ($asArgument -eq $text) + ")")
Write-Host ("  on stdin, python received:       " + $onStdin + "   (quotes kept = " + ($onStdin -eq $text) + ")")
exit 0

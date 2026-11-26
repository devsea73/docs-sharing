@echo off
setlocal DisableDelayedExpansion
set "ANTI_DOC_SCOPE=User"
if /i "%~1"=="--system" set "ANTI_DOC_SCOPE=Machine"

powershell.exe -NoProfile -Command ^
    "$ErrorActionPreference = 'Stop';" ^
    "$url = (Read-Host 'Google Docs URL').Trim();" ^
    "if ($url.StartsWith('docs.google.com/')) { $url = 'https://' + $url };" ^
    "[Uri]$address = $null;" ^
    "if (-not [Uri]::TryCreate($url, 'Absolute', [ref]$address)" ^
    "    -or $address.Scheme -notin @('http', 'https')" ^
    "    -or $address.Host -ne 'docs.google.com' -or $address.UserInfo" ^
    "    -or $address.Port -notin @(80, 443)" ^
    "    -or $address.AbsolutePath -cnotmatch '^/document/(?:u/\d+/)?d/[A-Za-z0-9_-]+(?:/|$)'" ^
    "    -or $address.AbsolutePath -cmatch '^/document/(?:u/\d+/)?d/e/')" ^
    "{ throw 'Enter a valid Google Docs document URL.' };" ^
    "[Environment]::SetEnvironmentVariable('ANTI_GOOGLE_DOC_URL', $url, $env:ANTI_DOC_SCOPE);" ^
    "Write-Host 'Saved ANTI_GOOGLE_DOC_URL. Open Anti to load the document.'"
exit /b %errorlevel%

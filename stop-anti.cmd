@echo off
setlocal DisableDelayedExpansion
set "ANTI_STOP_COMMAND=%~f0"
powershell.exe -NoProfile -Command "$source = [IO.File]::ReadAllText($env:ANTI_STOP_COMMAND); $body = ($source -split '(?m)^:ANTI_STOP_POWERSHELL\r?$', 2)[1]; & ([scriptblock]::Create($body))"
exit /b %errorlevel%

:ANTI_STOP_POWERSHELL
$ErrorActionPreference = 'Stop'

Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;

public static class AntiStopWindows
{
    private const string PropertyName = "MollySupportDoc.MainWindow";
    private const uint WM_CLOSE = 0x0010;

    private delegate bool WindowCallback(IntPtr window, IntPtr data);

    [DllImport("user32.dll")]
    private static extern bool EnumWindows(WindowCallback callback, IntPtr data);

    [DllImport("user32.dll", CharSet = CharSet.Unicode, ExactSpelling = true)]
    private static extern IntPtr GetPropW(IntPtr window, string name);

    [DllImport("user32.dll")]
    private static extern uint GetWindowThreadProcessId(IntPtr window, out uint processId);

    [DllImport("user32.dll", ExactSpelling = true)]
    private static extern bool PostMessageW(IntPtr window, uint message, IntPtr wParam, IntPtr lParam);

    public static IntPtr[] FindWindows()
    {
        var windows = new List<IntPtr>();
        EnumWindows((window, data) => {
            if (GetPropW(window, PropertyName) != IntPtr.Zero) windows.Add(window);
            return true;
        }, IntPtr.Zero);
        return windows.ToArray();
    }

    public static uint Owner(IntPtr window)
    {
        uint processId;
        GetWindowThreadProcessId(window, out processId);
        return processId;
    }

    public static void RequestClose(IntPtr window, uint expectedOwner)
    {
        if (GetPropW(window, PropertyName) != IntPtr.Zero && Owner(window) == expectedOwner)
            PostMessageW(window, WM_CLOSE, IntPtr.Zero, IntPtr.Zero);
    }
}
'@

$scriptDirectory = [IO.Path]::GetDirectoryName($env:ANTI_STOP_COMMAND)
$project = $scriptDirectory
if ((Split-Path -Leaf $project) -ieq 'dist') {
    $project = Split-Path -Parent $project
}
$sourceFile = Join-Path $project 'support_app.py'
$sourcePattern = $null
if ((Test-Path -LiteralPath $sourceFile) -and (Test-Path -LiteralPath (Join-Path $project 'win32.py'))) {
    $escaped = [regex]::Escape($sourceFile)
    $sourcePattern = '^\s*(?:"[^"]+"|\S+)\s+(?:"' + $escaped + '"|' + $escaped + ')(?:\s|$)'
}
$session = [Diagnostics.Process]::GetCurrentProcess().SessionId

function Test-AntiExecutable($entry) {
    if (-not $entry.ExecutablePath) { return $false }
    if ($entry.Name -ine 'notepad.exe' -and
        [IO.Path]::GetDirectoryName($entry.ExecutablePath) -ine $scriptDirectory) { return $false }
    try {
        $version = [Diagnostics.FileVersionInfo]::GetVersionInfo($entry.ExecutablePath)
        return $version.InternalName -ceq 'MollySupportDoc' -and $version.ProductName -ceq 'SupportApp'
    } catch {
        return $false
    }
}

function Find-AntiProcesses($windows) {
    $processes = @(Get-CimInstance Win32_Process -Filter "SessionId = $session")
    $windowOwners = @{}
    foreach ($window in $windows) { $windowOwners[[int][AntiStopWindows]::Owner($window)] = $true }
    $owned = @{}
    foreach ($entry in $processes) {
        $targetId = [int]$entry.ProcessId
        $sourceRun = $sourcePattern -and $entry.Name -in @('python.exe', 'pythonw.exe') -and
            $entry.CommandLine -match $sourcePattern
        if ($windowOwners.ContainsKey($targetId) -or $sourceRun -or (Test-AntiExecutable $entry)) {
            $owned[$targetId] = $entry
        }
    }
    # Follow only browser helpers belonging to a verified Anti process tree.
    do {
        $previous = $owned.Count
        foreach ($entry in $processes) {
            $parent = $owned[[int]$entry.ParentProcessId]
            if ($entry.Name -ieq 'QtWebEngineProcess.exe' -and $parent -and
                $entry.CreationDate -ge $parent.CreationDate) {
                $owned[[int]$entry.ProcessId] = $entry
            }
        }
    } while ($owned.Count -gt $previous)
    return $owned
}

function Track-Processes($entries, $tracked) {
    foreach ($entry in $entries.Values) {
        $targetId = [int]$entry.ProcessId
        if ($tracked.ContainsKey($targetId)) { continue }
        $process = $null
        try {
            $process = [Diagnostics.Process]::GetProcessById($targetId)
            $difference = $process.StartTime.ToUniversalTime() - $entry.CreationDate.ToUniversalTime()
            if ([math]::Abs($difference.TotalMilliseconds) -le 2) {
                $null = $process.SafeHandle
                $tracked[$targetId] = $process
                continue
            }
        } catch {
            # The process may have finished between discovery and opening its handle.
        }
        if ($process) { $process.Dispose() }
    }
}

$windows = [AntiStopWindows]::FindWindows()
$targets = Find-AntiProcesses $windows
if ($targets.Count -eq 0) {
    Write-Host 'Anti is already stopped.'
    exit 0
}

$tracked = @{}
try {
    Track-Processes $targets $tracked
    foreach ($window in $windows) {
        $owner = [AntiStopWindows]::Owner($window)
        if ($tracked.ContainsKey([int]$owner)) { [AntiStopWindows]::RequestClose($window, $owner) }
    }
    $deadline = [datetime]::UtcNow.AddSeconds(4)
    while ([datetime]::UtcNow -lt $deadline -and @($tracked.Values | Where-Object { -not $_.HasExited }).Count) {
        Start-Sleep -Milliseconds 120
    }

    Track-Processes (Find-AntiProcesses ([AntiStopWindows]::FindWindows())) $tracked
    foreach ($process in $tracked.Values) {
        try {
            if (-not $process.HasExited) { $process.Kill() }
        } catch {
            # Check all remaining processes together below.
        }
    }
    foreach ($process in $tracked.Values) {
        if (-not $process.HasExited) { $null = $process.WaitForExit(2000) }
    }
    $remaining = Find-AntiProcesses ([AntiStopWindows]::FindWindows())
    if ($remaining.Count -or @($tracked.Values | Where-Object { -not $_.HasExited }).Count) {
        [Console]::Error.WriteLine('Some Anti processes could not be stopped.')
        exit 1
    }
    Write-Host 'Anti stopped.'
} finally {
    foreach ($process in $tracked.Values) { $process.Dispose() }
}

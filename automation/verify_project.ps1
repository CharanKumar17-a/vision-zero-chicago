Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$env:PYTHONUNBUFFERED = "1"

$gates = [System.Collections.Generic.List[PSObject]]::new()
$scriptFailed = $false

function Add-GateResult {
    param(
        [string]$GateName,
        [string]$Status,
        [string]$Details
    )
    $gates.Add([PSCustomObject]@{
        GateName = $GateName
        Status   = $Status
        Details  = $Details
    })
    if ($Status -eq "FAIL" -or $Status -eq "BLOCKED") {
        $script:scriptFailed = $true
    }
}

# 1. Repository Root Validation
$repoRoot = $PWD.ProviderPath
try {
    $rawGitRoot = (git rev-parse --show-toplevel 2>&1).Trim()
    $normalizedGitRoot = [System.IO.Path]::GetFullPath($rawGitRoot)
    $normalizedPwd = [System.IO.Path]::GetFullPath($repoRoot)

    if ($normalizedGitRoot -ne $normalizedPwd) {
        Add-GateResult -GateName "Repository Root Validation" -Status "FAIL" -Details "PWD ($normalizedPwd) does not match Git root ($normalizedGitRoot)"
    } else {
        Add-GateResult -GateName "Repository Root Validation" -Status "PASS" -Details "Matches $normalizedGitRoot"
    }
} catch {
    Add-GateResult -GateName "Repository Root Validation" -Status "FAIL" -Details "Failed to determine Git root: $_"
}

# 2. Current Branch and HEAD Capture
$currentBranch = ""
$headCommit = ""
try {
    $currentBranch = (git branch --show-current 2>&1).Trim()
    $headCommit = (git rev-parse HEAD 2>&1).Trim()
    if ($currentBranch.Length -gt 0 -and $headCommit.Length -gt 0) {
        Add-GateResult -GateName "Current Branch and HEAD Capture" -Status "PASS" -Details "Branch: $currentBranch | HEAD: $headCommit"
    } else {
        Add-GateResult -GateName "Current Branch and HEAD Capture" -Status "FAIL" -Details "Could not determine branch or HEAD commit"
    }
} catch {
    Add-GateResult -GateName "Current Branch and HEAD Capture" -Status "FAIL" -Details "Error capturing Git branch/HEAD: $_"
}

# 3. Active .venv Interpreter Check
$expectedVenvPython = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (Test-Path $expectedVenvPython) {
    $env:PATH = "$(Join-Path $repoRoot '.venv\Scripts');$env:PATH"
}

try {
    $activePython = (python -c "import sys; print(sys.executable)" 2>&1).Trim()
    $normalizedActive = [System.IO.Path]::GetFullPath($activePython)
    $normalizedExpected = [System.IO.Path]::GetFullPath($expectedVenvPython)

    if ($normalizedActive -eq $normalizedExpected) {
        Add-GateResult -GateName "Active .venv Interpreter" -Status "PASS" -Details "$normalizedActive"
    } else {
        Add-GateResult -GateName "Active .venv Interpreter" -Status "FAIL" -Details "Active Python ($normalizedActive) outside .venv ($normalizedExpected)"
    }
} catch {
    Add-GateResult -GateName "Active .venv Interpreter" -Status "FAIL" -Details "Failed resolving Python executable: $_"
}

# 4. Python Compilation (including compiled-file count)
try {
    $srcFiles = Get-ChildItem -Path "src" -Recurse -Filter "*.py" -ErrorAction SilentlyContinue | Where-Object { $_.FullName -notmatch "(__pycache__|\.venv|\.pytest_cache)" }
    $testFiles = Get-ChildItem -Path "tests" -Recurse -Filter "*.py" -ErrorAction SilentlyContinue | Where-Object { $_.FullName -notmatch "(__pycache__|\.venv|\.pytest_cache)" }
    $allPyFiles = @()
    if ($null -ne $srcFiles) { $allPyFiles += $srcFiles }
    if ($null -ne $testFiles) { $allPyFiles += $testFiles }

    $compileErrors = @()
    foreach ($file in $allPyFiles) {
        $filePath = $file.FullName
        $res = & python -m py_compile "$filePath" 2>&1
        if ($LASTEXITCODE -ne 0) {
            $compileErrors += "${filePath}: ${res}"
        }
    }

    if ($compileErrors.Count -eq 0) {
        Add-GateResult -GateName "Python Compilation" -Status "PASS" -Details "Compiled $($allPyFiles.Count) Python files cleanly (0 errors)"
    } else {
        Add-GateResult -GateName "Python Compilation" -Status "FAIL" -Details "$($compileErrors.Count) of $($allPyFiles.Count) files failed compilation: $($compileErrors -join '; ')"
    }
} catch {
    Add-GateResult -GateName "Python Compilation" -Status "FAIL" -Details "Compilation check failed: $_"
}

# 5 & 6. Capture Git Status Before and After Pytest, and Run Pytest dynamically
$gitStatusBefore = ""
$gitStatusAfter = ""
try {
    $gitStatusBeforeRaw = (git status --porcelain=v1 -uall 2>&1)
    if ($null -ne $gitStatusBeforeRaw) {
        $gitStatusBefore = ($gitStatusBeforeRaw) -join "`n"
    }
} catch {
    $gitStatusBefore = "ERROR: Failed capturing status before pytest"
}

# Run Pytest Suite dynamically
try {
    $pytestOutputRaw = & python -m pytest -q 2>&1
    $pytestExitCode = $LASTEXITCODE
    $pytestLines = @($pytestOutputRaw)
    $pytestSummary = ""
    if ($pytestLines.Count -gt 0) {
        $pytestSummary = ($pytestLines | Select-Object -Last 2) -join " "
    }

    if ($pytestExitCode -eq 0) {
        Add-GateResult -GateName "Full Pytest Result" -Status "PASS" -Details "Pytest Exit Code 0 | Summary: $pytestSummary"
    } else {
        Add-GateResult -GateName "Full Pytest Result" -Status "FAIL" -Details "Pytest Exit Code $pytestExitCode | Summary: $pytestSummary"
    }
} catch {
    Add-GateResult -GateName "Full Pytest Result" -Status "FAIL" -Details "Failed executing pytest: $_"
}

try {
    $gitStatusAfterRaw = (git status --porcelain=v1 -uall 2>&1)
    if ($null -ne $gitStatusAfterRaw) {
        $gitStatusAfter = ($gitStatusAfterRaw) -join "`n"
    }
} catch {
    $gitStatusAfter = "ERROR: Failed capturing status after pytest"
}

if ($gitStatusBefore -eq $gitStatusAfter) {
    $beforeCount = @($gitStatusBefore -split "`n" | Where-Object { $_.Trim().Length -gt 0 }).Count
    Add-GateResult -GateName "Git-Visible Test Side Effects" -Status "PASS" -Details "Before: $beforeCount item(s) | After: $beforeCount item(s) (no side effects created)"
} else {
    Add-GateResult -GateName "Git-Visible Test Side Effects" -Status "FAIL" -Details "Git status changed during pytest execution!`nBEFORE:`n$gitStatusBefore`nAFTER:`n$gitStatusAfter"
}

# 7. Unstaged git diff --check
try {
    $diffCheckOutput = & git diff --check 2>&1
    if ($LASTEXITCODE -eq 0) {
        Add-GateResult -GateName "Unstaged git diff --check" -Status "PASS" -Details "git diff --check passed cleanly"
    } else {
        Add-GateResult -GateName "Unstaged git diff --check" -Status "FAIL" -Details "git diff --check found whitespace errors: $($diffCheckOutput -join ' ')"
    }
} catch {
    if ($LASTEXITCODE -eq 0) {
        Add-GateResult -GateName "Unstaged git diff --check" -Status "PASS" -Details "git diff --check passed cleanly"
    } else {
        Add-GateResult -GateName "Unstaged git diff --check" -Status "FAIL" -Details "Failed running git diff --check: $_"
    }
}

# 8 & 9. Staged git diff --cached --check and Prohibited Staged Artifact Scan
$stagedFiles = @()
try {
    $stagedNames = & git diff --cached --name-only --diff-filter=ACMR 2>&1
    if ($LASTEXITCODE -eq 0 -and $null -ne $stagedNames) {
        foreach ($name in $stagedNames) {
            if ($null -ne $name -and $name.ToString().Trim().Length -gt 0) {
                $stagedFiles += $name.ToString().Trim()
            }
        }
    }
} catch {
    # No staged changes
}

if ($stagedFiles.Count -gt 0) {
    # 8. Staged diff check
    try {
        $cachedDiffCheck = & git diff --cached --check 2>&1
        if ($LASTEXITCODE -eq 0) {
            Add-GateResult -GateName "Staged git diff --cached --check" -Status "PASS" -Details "git diff --cached --check passed cleanly ($($stagedFiles.Count) staged file(s))"
        } else {
            Add-GateResult -GateName "Staged git diff --cached --check" -Status "FAIL" -Details "git diff --cached --check found whitespace errors: $($cachedDiffCheck -join ' ')"
        }
    } catch {
        if ($LASTEXITCODE -eq 0) {
            Add-GateResult -GateName "Staged git diff --cached --check" -Status "PASS" -Details "git diff --cached --check passed cleanly ($($stagedFiles.Count) staged file(s))"
        } else {
            Add-GateResult -GateName "Staged git diff --cached --check" -Status "FAIL" -Details "Failed running git diff --cached --check: $_"
        }
    }


    # 9. Prohibited staged artifact scan
    $prohibitedPatterns = @(
        "^data/raw/",
        "^data/interim/",
        "^outputs/logs/",
        "\.parquet$",
        "\.geojson$",
        "\.pdf$"
    )
    $prohibitedStaged = @()
    foreach ($sf in $stagedFiles) {
        foreach ($pattern in $prohibitedPatterns) {
            if ($sf -match $pattern) {
                $prohibitedStaged += $sf
                break
            }
        }
    }

    if ($prohibitedStaged.Count -eq 0) {
        Add-GateResult -GateName "Prohibited Staged Artifact Scan" -Status "PASS" -Details "0 prohibited artifacts matched out of $($stagedFiles.Count) staged file(s)"
    } else {
        Add-GateResult -GateName "Prohibited Staged Artifact Scan" -Status "FAIL" -Details "$($prohibitedStaged.Count) prohibited file(s) matched: $($prohibitedStaged -join ', ')"
    }
} else {
    Add-GateResult -GateName "Staged git diff --cached --check" -Status "NOT_APPLICABLE" -Details "No staged changes present"
    Add-GateResult -GateName "Prohibited Staged Artifact Scan" -Status "PASS" -Details "0 prohibited artifacts matched (0 staged files present)"
}

# 10. Git Scope Validation & 11. Unexpected Changes
$authorizedScopePatterns = @(
    "^AGENTS\.md$",
    "^automation/verify_project\.ps1$",
    "^\.agents/",
    "^\.devcontainer/",
    "^\.dockerignore$",
    "^Dockerfile$",
    "^config/project\.yml$",
    "^dashboard/streamlit/",
    "^docs/audits/",
    "^docs/data_quality/",
    "^docs/submission/",
    "^notebooks/",
    "^reports/",
    "^tests/"
)
$gitStatusItems = @()
try {
    $porcelainLines = & git status --porcelain=v1 -uall 2>&1
    if ($null -ne $porcelainLines) {
        foreach ($line in $porcelainLines) {
            if ($null -ne $line -and $line.ToString().Trim().Length -gt 3) {
                $filePath = $line.ToString().Substring(3).Trim()
                $gitStatusItems += $filePath
            }
        }
    }
} catch {
    # Error getting status
}

$unexpectedItems = @()
foreach ($item in $gitStatusItems) {
    $isAuthorized = $false
    foreach ($pattern in $authorizedScopePatterns) {
        if ($item -match $pattern) {
            $isAuthorized = $true
            break
        }
    }
    if (-not $isAuthorized) {
        $unexpectedItems += $item
    }
}

if ($unexpectedItems.Count -eq 0) {
    Add-GateResult -GateName "Git Scope Validation" -Status "PASS" -Details "$($gitStatusItems.Count) changed file(s) all match authorized scope patterns"
    Add-GateResult -GateName "Unexpected Changes" -Status "PASS" -Details "0 unexpected changes outside authorized governance scope"
} else {
    Add-GateResult -GateName "Git Scope Validation" -Status "FAIL" -Details "Unauthorized files present: $($unexpectedItems -join ', ')"
    Add-GateResult -GateName "Unexpected Changes" -Status "FAIL" -Details "$($unexpectedItems.Count) unexpected file(s) found: $($unexpectedItems -join ', ')"
}

# 12. Overall Verification Result
if ($scriptFailed) {
    Add-GateResult -GateName "Overall Verification Result" -Status "FAIL" -Details "One or more mandatory completion gates failed or blocked"
} else {
    Add-GateResult -GateName "Overall Verification Result" -Status "PASS" -Details "All 11 individual mandatory completion gates passed"
}

# Output Section
Write-Host "`n=== UNSTAGED CHANGES (git diff --stat) ==="
& git diff --stat

Write-Host "`n=== STAGED CHANGES (git diff --cached --stat) ==="
& git diff --cached --stat

Write-Host "`n=== GIT STATUS (git status --short) ==="
& git status --short

Write-Host "`n======================================================================================================================"
Write-Host ("{0,-38} | {1,-14} | {2}" -f "Gate", "Status", "Evidence")
Write-Host "======================================================================================================================"
foreach ($g in $gates) {
    $cleanEvidence = ($g.Details -replace "[\r\n]+", " ").Trim() -replace "\s+", " "
    Write-Host ("{0,-38} | {1,-14} | {2}" -f $g.GateName, $g.Status, $cleanEvidence)
}
Write-Host "======================================================================================================================"

if ($scriptFailed) {
    Write-Host "`nVerification Result: FAIL" -ForegroundColor Red
    exit 1
} else {
    Write-Host "`nVerification Result: PASS" -ForegroundColor Green
    exit 0
}

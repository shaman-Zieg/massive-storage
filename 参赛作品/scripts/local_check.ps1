$ErrorActionPreference = 'Stop'
$projectDir = Split-Path -Parent $PSScriptRoot
$runtimePython = 'C:\Users\Qing2\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$localPackages = Join-Path (Split-Path -Parent $projectDir) '工作记录\runtime_packages'
if (-not (Test-Path -LiteralPath $runtimePython)) { throw '本机运行时不存在，请使用 README 中的常规 Python 命令。' }
$env:PYTHONIOENCODING = 'utf-8'
if (Test-Path -LiteralPath $localPackages) { $env:PYTHONPATH = $localPackages }
Push-Location -LiteralPath $projectDir
try {
    & $runtimePython -m evidence_rag build
    if ($LASTEXITCODE -ne 0) { throw '索引构建失败' }
    & $runtimePython -m unittest discover -s tests -v
    if ($LASTEXITCODE -ne 0) { throw '功能测试失败' }
    & $runtimePython scripts/compare_versions.py --questions '../索引与demo代码-0730/RAG-Anything-0713/queries_30.json'
    if ($LASTEXITCODE -ne 0) { throw '检索诊断失败' }
} finally { Pop-Location }

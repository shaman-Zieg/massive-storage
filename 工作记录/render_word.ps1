param([string]$InputDocx, [string]$OutputDir)
$ErrorActionPreference = 'Stop'
$resolvedInput = (Resolve-Path -LiteralPath $InputDocx).Path
New-Item -ItemType Directory -Path $OutputDir -Force | Out-Null
$resolvedOutput = (Resolve-Path -LiteralPath $OutputDir).Path
$pdfPath = Join-Path $resolvedOutput 'document.pdf'
$wordApp = New-Object -ComObject Word.Application
$wordApp.Visible = $false
$wordApp.DisplayAlerts = 0
try {
    $wordDoc = $wordApp.Documents.Open($resolvedInput, $false, $true)
    # Do not enumerate missing Header/Footer COM objects: Word can instantiate
    # absent stories and introduce header rules into the exported PDF.
    $wordDoc.ExportAsFixedFormat($pdfPath, 17)
    Write-Output ('Pages: ' + $wordDoc.ComputeStatistics(2))
    $wordDoc.Close(0)
} finally {
    $wordApp.Quit()
    [System.Runtime.InteropServices.Marshal]::ReleaseComObject($wordApp) | Out-Null
}
& 'C:\Users\Qing2\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\poppler\Library\bin\pdftoppm.exe' -scale-to 1400 -png $pdfPath (Join-Path $resolvedOutput 'page')
if ($LASTEXITCODE -ne 0) { throw 'PDF rendering failed' }

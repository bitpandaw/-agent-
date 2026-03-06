param(
  [switch]$Force
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Write-Host "Project root: $Root"

$dirs = @(
  "$Root\.hf_cache",
  "$Root\.hf_cache\hub",
  "$Root\.hf_cache\datasets",
  "$Root\chroma_db",
  "$Root\state\logs",
  "$Root\record"
)

foreach ($d in $dirs) {
  if (-not (Test-Path $d)) {
    New-Item -ItemType Directory -Force -Path $d | Out-Null
  }
}

# HuggingFace cache (local to project)
$env:HF_HOME = "$Root\.hf_cache"
$env:HUGGINGFACE_HUB_CACHE = "$Root\.hf_cache\hub"
$env:HF_DATASETS_CACHE = "$Root\.hf_cache\datasets"
$env:HF_HUB_DISABLE_SYMLINKS = "1"

$py = "python"
$venvPy = "$Root\venv\Scripts\python.exe"
if (Test-Path $venvPy) {
  $py = $venvPy
}

$dbPath = "$Root\hotpot.db"
if ($Force -or -not (Test-Path $dbPath)) {
  Write-Host "Initializing database..."
  & $py "$Root\init_db.py"
} else {
  Write-Host "Database already exists. Use -Force to re-init."
}

Write-Host "Init done."
Write-Host "Next: start services:"
Write-Host "  Embedding: python -m uvicorn embedding.embedding:app --host 0.0.0.0 --port 8011"
Write-Host "  RAG:       python -m uvicorn rag.rag_pipeline:app --host 0.0.0.0 --port 8010"
Write-Host "  Neo4j:     docker-compose up -d"

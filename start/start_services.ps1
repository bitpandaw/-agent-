param(
  [switch]$SkipDocker,
  [switch]$Distributed  # 微服务模式：启动 Embedding + RAG + Gateway；默认单进程（仅 Gateway）
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Write-Host "Project root: $Root"

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

$commonEnv = @(
  "`$env:HF_HOME='$env:HF_HOME'",
  "`$env:HUGGINGFACE_HUB_CACHE='$env:HUGGINGFACE_HUB_CACHE'",
  "`$env:HF_DATASETS_CACHE='$env:HF_DATASETS_CACHE'",
  "`$env:HF_HUB_DISABLE_SYMLINKS='$env:HF_HUB_DISABLE_SYMLINKS'"
) -join "; "

$gwCmd = "$commonEnv; & `"$py`" -m uvicorn gateway.gateway:app --host 0.0.0.0 --port 8000"
$embedCmd = "$commonEnv; & `"$py`" -m uvicorn embedding.embedding:app --host 0.0.0.0 --port 8011"
$ragCmd = "$commonEnv; & `"$py`" -m uvicorn rag.rag_pipeline:app --host 0.0.0.0 --port 8010"

Write-Host "Starting Gateway (8000)..."
Start-Process -FilePath "powershell" -WorkingDirectory $Root -ArgumentList "-NoExit", "-Command", $gwCmd

if ($Distributed) {
  Write-Host "Distributed mode: Starting Embedding (8011), RAG (8010)..."
  Start-Process -FilePath "powershell" -WorkingDirectory $Root -ArgumentList "-NoExit", "-Command", $embedCmd
  Start-Process -FilePath "powershell" -WorkingDirectory $Root -ArgumentList "-NoExit", "-Command", $ragCmd
} else {
  Write-Host "Single-process mode: Embedding/RAG in-process, only Gateway started."
}

if (-not $SkipDocker) {
  Write-Host "Starting Neo4j (docker-compose)..."
  & docker-compose -f "$Root\docker-compose.yml" up -d
}

Write-Host "All services started."

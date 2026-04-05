$ErrorActionPreference = "Stop"

$ContainerName = "finally"
$ImageName = "finally"
$ProjectDir = Split-Path -Parent $PSScriptRoot

Set-Location $ProjectDir

# Build if --build flag passed or image doesn't exist
$shouldBuild = $args -contains "--build"
if (-not $shouldBuild) {
    $imageExists = docker image inspect $ImageName 2>$null
    if (-not $imageExists) { $shouldBuild = $true }
}

if ($shouldBuild) {
    Write-Host "Building Docker image..."
    docker build -t $ImageName .
}

# Stop existing container if running
$running = docker ps -q -f "name=$ContainerName" 2>$null
if ($running) {
    Write-Host "Stopping existing container..."
    docker stop $ContainerName | Out-Null
    docker rm $ContainerName | Out-Null
} else {
    $stopped = docker ps -aq -f "name=$ContainerName" 2>$null
    if ($stopped) {
        docker rm $ContainerName | Out-Null
    }
}

# Check for .env file
$envFlag = @()
if (Test-Path ".env") {
    $envFlag = @("--env-file", ".env")
}

Write-Host "Starting FinAlly..."
docker run -d `
    --name $ContainerName `
    -p 8000:8000 `
    -v finally-data:/app/db `
    @envFlag `
    $ImageName

Write-Host ""
Write-Host "FinAlly is running at: http://localhost:8000"
Write-Host ""

# Open browser
Start-Process "http://localhost:8000"

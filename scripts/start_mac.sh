#!/bin/bash
set -e

CONTAINER_NAME="finally"
IMAGE_NAME="finally"
PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

cd "$PROJECT_DIR"

# Build if --build flag passed or image doesn't exist
if [[ "$1" == "--build" ]] || ! docker image inspect "$IMAGE_NAME" > /dev/null 2>&1; then
    echo "Building Docker image..."
    docker build -t "$IMAGE_NAME" .
fi

# Stop existing container if running
if docker ps -q -f name="$CONTAINER_NAME" | grep -q .; then
    echo "Stopping existing container..."
    docker stop "$CONTAINER_NAME" > /dev/null 2>&1
    docker rm "$CONTAINER_NAME" > /dev/null 2>&1
elif docker ps -aq -f name="$CONTAINER_NAME" | grep -q .; then
    docker rm "$CONTAINER_NAME" > /dev/null 2>&1
fi

# Check for .env file
ENV_FLAG=""
if [ -f ".env" ]; then
    ENV_FLAG="--env-file .env"
fi

echo "Starting FinAlly..."
docker run -d \
    --name "$CONTAINER_NAME" \
    -p 8000:8000 \
    -v finally-data:/app/db \
    $ENV_FLAG \
    "$IMAGE_NAME"

echo ""
echo "FinAlly is running at: http://localhost:8000"
echo ""

# Open browser if possible
if command -v open > /dev/null 2>&1; then
    open "http://localhost:8000"
fi

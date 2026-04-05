#!/bin/bash
set -e

CONTAINER_NAME="finally"

if docker ps -q -f name="$CONTAINER_NAME" | grep -q .; then
    echo "Stopping FinAlly..."
    docker stop "$CONTAINER_NAME" > /dev/null 2>&1
    docker rm "$CONTAINER_NAME" > /dev/null 2>&1
    echo "FinAlly stopped."
elif docker ps -aq -f name="$CONTAINER_NAME" | grep -q .; then
    echo "Removing stopped container..."
    docker rm "$CONTAINER_NAME" > /dev/null 2>&1
    echo "Done."
else
    echo "FinAlly is not running."
fi

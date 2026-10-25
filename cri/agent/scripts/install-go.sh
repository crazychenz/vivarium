#!/usr/bin/env bash

# Pick the current version/arch from https://go.dev/dl/ (use linux-arm64 on ARM)
GOLANG_VER=1.27.3
[ -e "go${GOLANG_VER}.linux-amd64.tar.gz" ] || curl -LO https://go.dev/dl/go${GOLANG_VER}.linux-amd64.tar.gz

mkdir -p "golang"
tar -C "golang" -xzf go${GOLANG_VER}.linux-amd64.tar.gz

export GO_PATH="$(pwd)/golang"
export PATH="${GO_PATH}/go/bin:$GO_PATH/bin:$PATH"

exec bash -li
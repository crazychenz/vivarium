GO  ?= go
BIN := bin

.PHONY: all build build-apt test vet clean

all: build

# Normal build. The first run downloads wireguard-go (as a Go library) into
# go.mod/go.sum; there is nothing else to install.
build: go.sum
	$(GO) build -o $(BIN)/qemu-wg-bridge ./cmd/qemu-wg-bridge
	$(GO) build -o $(BIN)/fakeguest ./cmd/fakeguest

go.sum:
	$(GO) get golang.zx2c4.com/wireguard@latest
	$(GO) mod tidy

# Alternative without the Go module proxy: build against the wireguard-go
# library packaged by Debian/Ubuntu (sudo apt install golang-golang-zx2c4-wireguard-dev).
# That package is an older snapshot with the pre-batching tun.Device API,
# hence the wgoldapi build tag.
GOPATH_DIR := $(CURDIR)/.gopath
build-apt:
	mkdir -p $(GOPATH_DIR)/src $(BIN)
	ln -sfn $(CURDIR) $(GOPATH_DIR)/src/qemu-wg-mitm
	GO111MODULE=off GOPATH=$(GOPATH_DIR):/usr/share/gocode $(GO) build -tags wgoldapi -o $(BIN)/qemu-wg-bridge qemu-wg-mitm/cmd/qemu-wg-bridge
	GO111MODULE=off GOPATH=$(GOPATH_DIR):/usr/share/gocode $(GO) build -o $(BIN)/fakeguest qemu-wg-mitm/cmd/fakeguest

# Unit tests: standard library only, no wireguard-go needed.
test:
	$(GO) test -race ./internal/...

vet:
	$(GO) vet ./internal/... ./cmd/fakeguest

clean:
	rm -rf $(BIN) $(GOPATH_DIR)

# Sandbox image for the go-*-cli environments. `go test ./...` is built into the base; SAST is the
# generic Semgrep image. Only writable cache/HOME is baked so the non-root --user run never hits
# `mkdir /.cache: permission denied`.
FROM golang:1.23-alpine
ENV HOME=/tmp \
    GOCACHE=/tmp/.cache/go-build \
    GOPATH=/tmp/go \
    GOMODCACHE=/tmp/go/pkg/mod

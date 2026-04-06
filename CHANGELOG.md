# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-04-06

### Added
- `ThreadPoolXMLRPCServer` for drop-in `SimpleXMLRPCServer`-style usage with bounded thread-pool concurrency.
- `ServerOverloadPolicy` enum with `BLOCK`, `CLOSE`, and `FAULT` modes.
- `XMLRPCServerConfig` dataclass for server configuration.
- `LimitedXMLRPCRequestHandler` with configurable `max_request_size` and strict `Content-Length` validation:
  - `411 Length Required` when `Content-Length` header is absent.
  - `400 Bad Request` for invalid or negative `Content-Length` values.
  - `413 Payload Too Large` when body exceeds `max_request_size`.
  - `501 Not Implemented` for `Transfer-Encoding: chunked` requests.
- `logRequests=False` suppresses both request and error-path log output.
- MIT license, packaging metadata, and CI workflow.

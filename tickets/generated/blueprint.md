## Tech Stack
- go-1.23 — 1.23.0 — Core language runtime.
- github.com/spf13/cobra — v1.8.1 — CLI command parsing.
- encoding/json — stdlib — High-performance stream-based JSON parsing.
- encoding/csv — stdlib — RFC 4180 compliant CSV serialization.
- os/flags — stdlib — Flag handling for delimiters.

## Non-Functional Requirements
- Performance: Conversion of a 1MB flat JSON file must complete under 500ms on standard x86_64 hardware.
- Memory: Peak heap usage must not exceed 2x the file size during execution.
- Accuracy: CSV header set must be deterministic and ordered lexicographically.
- Reliability: Process must terminate with code 1 for malformed JSON, code 2 for I/O errors, and code 0 for success.
- Concurrency: Single-threaded execution model to ensure stable deterministic column ordering.

## File Topology
```text
.
├── cmd
│   └── root.go
├── internal
│   └── converter
│       └── engine.go
├── go.mod
├── go.sum
└── main.go
```

## Data Contracts & Interfaces
- `Convert(input io.Reader, output io.Writer, delimiter rune) error`
  - Inputs: input (io.Reader), output (io.Writer), delimiter (rune).
  - Outputs: error (nil if successful).
  - Exceptions: ErrInvalidJSON (code 1), ErrInvalidFormat (root must be array), ErrIOFailure (code 2).
  - Side Effects: Writes RFC 4180 compliant byte stream to output.

## CLI Specification
- Library: github.com/spf13/cobra
- Command: `json2csv [input_path] [output_path]`
- Flags:
  - `--delimiter` (string, default: ",") — Sets the output CSV field separator.
- Exit Codes:
  - 0: Conversion success.
  - 1: Malformed JSON syntax error.
  - 2: File system error (Access denied, file not found, permission denied).
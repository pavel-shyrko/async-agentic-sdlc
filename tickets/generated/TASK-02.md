# Implement Conversion Engine

Implement the core conversion logic. Objective: Implement conversion logic in internal/converter/engine.go. Tech Stack: encoding/json, encoding/csv. Constraints: Single-threaded; peak heap memory < 2x file size; order headers lexicographically. Interface: Convert(input io.Reader, output io.Writer, delimiter rune) error. Acceptance Criteria: Given a flat JSON array of objects, When Convert is called, Then valid RFC 4180 CSV is written to output with deterministic, lexicographically sorted headers. Terminate with code 1 for invalid JSON, 2 for I/O errors.

# Implement CLI Interface

Implement command-line parsing. File paths: cmd/root.go, main.go. Stack: github.com/spf13/cobra v1.8.1. Logic: Parse command json2csv [input_path] [output_path] and --delimiter flag. Call converter.Convert. Handle exit codes: 0 (success), 1 (malformed JSON), 2 (I/O). Acceptance Criteria: CLI supports --delimiter flag, accepts input/output paths, and correctly routes errors to stderr with corresponding exit codes.

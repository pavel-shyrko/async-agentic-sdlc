# Implement JSON to CSV CLI Converter

## Goal
Provide a reliable command-line interface to transform structured JSON data into CSV format, enabling users to customize field delimiters for data interoperability.

## Success Metrics
- Conversion time: Less than 500ms for a 1MB JSON file.
- Accuracy: 100% parity between JSON keys and CSV headers.
- Error rate: Less than 0.1% failure rate for valid JSON inputs.

## User Stories

### Story 1: Convert Flat JSON to CSV
As a data analyst, I want to convert a flat JSON array to a CSV file so that I can process the data in spreadsheet software.
**In scope:** Handling of list of objects with consistent keys.
**Out of scope:** Handling of nested JSON objects or arrays.
**Edge cases:** Empty JSON files, files with non-array root.
**Acceptance Criteria:**
Given a JSON file containing a list of flat objects
When the converter is executed with input and output file paths
Then a CSV file is generated with keys as the first row header and values as subsequent rows

### Story 2: Specify Custom Delimiter
As a data analyst, I want to specify the CSV delimiter, so that I can adapt the output to local regional standards or specific system requirements.
**In scope:** Support for comma, semicolon, tab, and pipe delimiters.
**Out of scope:** Validation of delimiter character length > 1.
**Edge cases:** Providing a multi-character string as a delimiter.
**Acceptance Criteria:**
Given a JSON file
When the command is run with a flag specifying a semicolon as the delimiter
Then the output CSV file uses semicolons to separate data fields

### Story 3: Handle Malformed Input
As a user, I want the CLI to report clear errors when input is invalid, so that I can correct my data without guessing why the conversion failed.
**In scope:** Reporting syntax errors, file access errors, and empty input errors.
**Out of scope:** Auto-fixing malformed JSON structure.
**Edge cases:** JSON file contains non-JSON text; file does not exist.
**Acceptance Criteria:**
Given an invalid JSON string in the input file
When the conversion tool is executed
Then the tool terminates with a non-zero exit code and prints a descriptive error message to stderr
"""LLM-generated fallback: the extracted architecture is empty (no models,
services or commands), so there is nothing mechanical to be faithful to.
Generated from /Users/gillesstenger/Documents/Projets SFEIR/esus/out/validation/runs/mac-final5-20261126/prompt_cli_tool/requirements.txt by `generator.py --model`; verify by running it.
"""

import csv
import json
import sys
from typing import List, Dict, Any

class MissingFileError(OSError):
    """Raised when the input CSV file path does not exist or cannot be accessed."""
    pass

class MalformedCSVError(ValueError):
    """Raised when the CSV file contains malformed data."""
    pass

class ColumnLookupError(KeyError):
    """Raised when attempting to access a column header that is missing from the CSV header row."""
    pass


def main() -> None:
    # Parse command line arguments
    if len(sys.argv) < 2:
        print("error: missing input file path", file=sys.stderr)
        sys.exit(1)

    input_path: str = sys.argv[1]
    output_path: str = sys.argv[2] if len(sys.argv) > 2 else None

    # Validate input file path
    try:
        with open(input_path, 'r', encoding='utf-8') as file:
            # Read the CSV file
            reader = csv.DictReader(file)
            headers: List[str] = reader.fieldnames

            if headers is None:
                raise MalformedCSVError("CSV file has no header row or malformed header structure")

            # Parse all rows into a list of dictionaries
            data: List[Dict[str, Any]] = []
            for row in reader:
                # Validate each row has all required headers
                for header in headers:
                    if header not in row:
                        raise ColumnLookupError(f"Missing column header '{header}' in row data")
                data.append(row)

            # Output to file or stdout
            if output_path:
                try:
                    with open(output_path, 'w', encoding='utf-8') as file:
                        json.dump(data, file, indent=2)
                except OSError as e:
                    print(f"error: failed to write output file '{output_path}': {e}", file=sys.stderr)
                    sys.exit(1)
            else:
                # Print to stdout
                print(json.dumps(data, indent=2))

    except FileNotFoundError:
        raise MissingFileError(f"Input file '{input_path}' not found")
    except PermissionError:
        raise MissingFileError(f"Permission denied accessing input file '{input_path}'")
    except csv.Error as e:
        raise MalformedCSVError(f"Malformed CSV data: {e}")
    except Exception as e:
        # Catch any other unexpected errors and report them
        print(f"error: unexpected error processing file '{input_path}': {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)


"""LLM-generated fallback: the extracted architecture is empty (no models,
services or commands), so there is nothing mechanical to be faithful to.
Generated from out/validation/runs/gpu-final2-20261126/prompt_cli_tool/requirements.txt by `generator.py --model`; verify by running it.
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


def read_csv_to_dict(file_path: str) -> List[Dict[str, Any]]:
    """
    Read a CSV file and return a list of dictionaries with headers as keys.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            return [row for row in reader]
    except FileNotFoundError:
        raise MissingFileError(f"File not found: {file_path}")
    except PermissionError:
        raise MissingFileError(f"Permission denied: {file_path}")
    except Exception as e:
        # Catch any other unexpected file or I/O errors
        raise MalformedCSVError(f"Error reading file: {str(e)}")


def main() -> None:
    # Parse command line arguments
    if len(sys.argv) < 2:
        print("error: missing input file path", file=sys.stderr)
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None

    try:
        data = read_csv_to_dict(input_path)
    except MissingFileError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    except MalformedCSVError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)

    # Output to file or stdout
    if output_path:
        try:
            with open(output_path, 'w', encoding='utf-8') as file:
                json.dump(data, file, indent=2)
        except Exception as e:
            print(f"error: failed to write output file: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        # Print to stdout
        print(json.dumps(data, indent=2))


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)


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
    Read a CSV file and return a list of dictionaries with column names from the header.
    """
    try:
        with open(file_path, 'r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            # If no header is found, raise MalformedCSVError
            if not reader.fieldnames:
                raise MalformedCSVError("CSV file has no header row.")
            return [row for row in reader]
    except FileNotFoundError:
        raise MissingFileError(f"File not found: {file_path}")
    except PermissionError:
        raise MissingFileError(f"Permission denied accessing file: {file_path}")
    except csv.Error as e:
        raise MalformedCSVError(f"Malformed CSV data: {str(e)}")
    except Exception as e:
        raise MalformedCSVError(f"Unexpected error reading CSV: {str(e)}")


def main() -> None:
    """
    Main function to handle CLI arguments and process CSV to JSON conversion.
    """
    # Parse command line arguments
    if len(sys.argv) < 2:
        print("error: missing input file path", file=sys.stderr)
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else None

    try:
        data = read_csv_to_dict(input_path)
        if not data:
            # Empty file or invalid CSV
            print("[]", file=sys.stdout if output_path is None else open(output_path, 'w', encoding='utf-8'))
            return

        # Convert to JSON and write to output
        json_output = json.dumps(data, indent=None)
        if output_path is None:
            print(json_output)
        else:
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(json_output)

    except MissingFileError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    except MalformedCSVError as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"error: unexpected error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)


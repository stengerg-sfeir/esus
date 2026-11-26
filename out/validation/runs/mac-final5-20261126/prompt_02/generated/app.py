"""LLM-generated fallback: the extracted architecture is empty (no models,
services or commands), so there is nothing mechanical to be faithful to.
Generated from /Users/gillesstenger/Documents/Projets SFEIR/esus/out/validation/runs/mac-final5-20261126/prompt_02/requirements.txt by `generator.py --model`; verify by running it.
"""

import sys
from typing import Final

class DivisionByZeroError(RuntimeError):
    """Raised when attempting to divide a number by zero."""
    pass

def add(a: float, b: float) -> float:
    return a + b

def subtract(a: float, b: float) -> float:
    return a - b

def multiply(a: float, b: float) -> float:
    return a * b

def divide(a: float, b: float) -> float:
    if b == 0:
        raise DivisionByZeroError("Division by zero is not allowed.")
    return a / b

def parse_number(s: str) -> float:
    try:
        return float(s)
    except ValueError:
        raise ValueError(f"Invalid number: '{s}'")

def main() -> None:
    if len(sys.argv) != 4:
        sys.stderr.write(f"error: expected exactly 3 arguments (got {len(sys.argv) - 1})\n")
        sys.exit(1)
    
    try:
        operator: Final[str] = sys.argv[1]
        num1_str: Final[str] = sys.argv[2]
        num2_str: Final[str] = sys.argv[3]
        
        num1: float = parse_number(num1_str)
        num2: float = parse_number(num2_str)
        
        if operator == "+":
            result: float = add(num1, num2)
        elif operator == "-":
            result: float = subtract(num1, num2)
        elif operator == "*":
            result: float = multiply(num1, num2)
        elif operator == "/":
            result: float = divide(num1, num2)
        else:
            sys.stderr.write(f"error: unknown operator '{operator}'\n")
            sys.exit(1)
            
        print(result)
        
    except ValueError as e:
        sys.stderr.write(f"error: {e}\n")
        sys.exit(1)
    except DivisionByZeroError as e:
        sys.stderr.write(f"error: {e}\n")
        sys.exit(1)

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)


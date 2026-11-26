"""LLM-generated fallback: the extracted architecture is empty (no models,
services or commands), so there is nothing mechanical to be faithful to.
Generated from out/validation/runs/gpu-final2-20261126/prompt_02/requirements.txt by `generator.py --model`; verify by running it.
"""

import sys
from typing import Union

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
        sys.stderr.write(f"error: expected exactly 3 arguments (operation, operand1, operand2)\n")
        sys.exit(1)
    
    operation = sys.argv[1]
    try:
        operand1 = parse_number(sys.argv[2])
        operand2 = parse_number(sys.argv[3])
    except ValueError as e:
        sys.stderr.write(f"error: {e}\n")
        sys.exit(1)
    
    if operation == "add":
        result = add(operand1, operand2)
    elif operation == "subtract":
        result = subtract(operand1, operand2)
    elif operation == "multiply":
        result = multiply(operand1, operand2)
    elif operation == "divide":
        result = divide(operand1, operand2)
    else:
        sys.stderr.write(f"error: unknown operation '{operation}'\n")
        sys.exit(1)
    
    print(result)

if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)


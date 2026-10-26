def _clean_body(text):
    """Extract the function body from a complete function definition, or
    handle the legacy body-only format.

    New format (preferred): model writes complete function with `def`.
    Legacy format: model writes only body lines (no `def` line).
    """
    # Use keep_indent=True to preserve original indentation for legacy format
    code = extract_code(text, keep_indent=True, open_fence=True)
    if not code.strip():
        return []
    
    # Try to parse as a complete function first
    try:
        tree = ast.parse(code)
    except SyntaxError:
        tree = None
    
    func = None
    if tree:
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                func = node
                break
    
    if func:
        # New format: complete function with def line
        code_lines = code.splitlines()
        body_start = func.lineno
        body_end = getattr(func, 'end_lineno', len(code_lines))
        body_source = code_lines[body_start:body_end]
        if not body_source:
            return []
        body_lines = body_source[1:]  # skip def line
    else:
        # Legacy format: body lines only (no def line), but may have
        # a leading def line/docstring that AST couldn't parse (e.g. fences in middle).
        body_lines = [line for line in code.splitlines() if line.strip() or True]
        # Remove leading/trailing empty lines
        while body_lines and not body_lines[0].strip():
            body_lines.pop(0)
        while body_lines and not body_lines[-1].strip():
            body_lines.pop()
        # Strip leading def line if present (model echoed the stub)
        if body_lines and re.match(r'^\s*def\s+\w+\s*\(', body_lines[0]):
            body_lines.pop(0)
        # Strip leading docstring if present
        while body_lines and re.match(r'^\s*("""|\'\'\')', body_lines[0].lstrip()):
            body_lines.pop(0)
            # Find closing triple quotes
            while body_lines and not re.search(r'("""|\'\'\')', body_lines[0]):
                body_lines.pop(0)
            if body_lines:
                body_lines.pop(0)  # remove closing line
        # Remove fence lines
        body_lines = [line for line in body_lines if not re.match(r'^\s*```', line)]
        # Remove deliberation after a lone closing fence (model reasoning after code)
        # Find first lone ``` line and drop everything after it
        for i, line in enumerate(body_lines):
            if re.match(r'^\s*```', line.strip()):
                body_lines = body_lines[:i]
                break
    
    if not body_lines:
        return []
    
    # Dedent to minimum indent among body lines
    indents = [len(line) - len(line.lstrip(" ")) for line in body_lines if line.strip()]
    if not indents:
        return []
    trim = min(indents)
    
    # Dedent to 0; _spliced_candidate will add 8 spaces
    result = []
    for line in body_lines:
        if line.strip():
            dedented = line[trim:] if len(line) >= trim else line
            result.append(dedented)
        else:
            result.append("")
    
    return result

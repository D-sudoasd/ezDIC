import ast
import sys

path = "dic_virtual_extensometer_gui_v7_multi_roi_range.py"
with open(path, "r", encoding="utf-8") as f:
    src = f.read()

try:
    ast.parse(src)
    print("AST parse successful - no syntax errors.")
    sys.exit(0)
except SyntaxError as e:
    print(f"SYNTAX ERROR at line {e.lineno}: {e.msg}")
    lines = src.splitlines()
    start = max(0, e.lineno - 4)
    end = min(len(lines), e.lineno + 2)
    for i in range(start, end):
        marker = ">>>" if i + 1 == e.lineno else "   "
        print(f"{marker} {i+1}: {lines[i][:140]}")
    sys.exit(1)
except Exception as e:
    print(f"Unexpected error: {e}")
    sys.exit(1)

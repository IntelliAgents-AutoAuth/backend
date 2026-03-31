
import os
from pathlib import Path

workspace_root = Path(__file__).resolve().parents[3]
path = str(workspace_root / "frontend" / "src" / "pages" / "CaseDetails.jsx")
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

old_text = '{typeof value === \'object\' ? `${value.value} ${value.unit}` : value}'
new_text = '{value && typeof value === \'object\' ? `${value.value} ${value.unit}` : value}'

if old_text in content:
    new_content = content.replace(old_text, new_text)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print("SUCCESS: Content replaced.")
else:
    print("ERROR: Target text not found.")

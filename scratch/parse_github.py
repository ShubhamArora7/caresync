import re

content_path = r'C:\Users\shubh\.gemini\antigravity\brain\cee57faf-e198-4d2d-ac9c-743992c373e1\.system_generated\steps\2833\content.md'
with open(content_path, 'r', encoding='utf-8') as f:
    content = f.read()

# Look for href paths in ShubhamArora7/caresync
matches = re.findall(r'href="/ShubhamArora7/caresync/blob/main/([^"]+)"', content)
print("Blob files found:")
print(set(matches))

matches_dirs = re.findall(r'href="/ShubhamArora7/caresync/tree/main/([^"]+)"', content)
print("\nTree directories found:")
print(set(matches_dirs))

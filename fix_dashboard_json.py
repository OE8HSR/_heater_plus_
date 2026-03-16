#!/usr/bin/env python3
"""Fix and rewrite grafana_dashboard_allsky_complett.json so it is valid JSON."""
import json

with open("grafana_dashboard_allsky_complett.json") as f:
    s = f.read()

# Fix: double backslash before quote (\\") should be single backslash (\")
# so that the quote is properly escaped in JSON.
fixed = s.replace('\\"', '"')  # This would break - we need to only fix \\" to \"
# Actually: in file we have \ then \ then " which breaks JSON (string ends at the first ")
# So we need to replace the sequence backslash-backslash-quote with backslash-quote.
# In Python: '\\\\"' is backslash backslash quote. Replace with '\\"' (backslash quote).
# But wait - if we have \" in file (correct), that's backslash quote. So we must not replace that.
# So we need to replace only \\" (double backslash + quote) with \" (single backslash + quote).
# In the file, when we read: backslash is one char. So we look for the pattern: two backslashes followed by quote.
# In Python string literal: backslash is \ so \\ is one backslash. So \\\\ is two backslashes. So \\\\\" is two backslashes + quote.
fixed = s.replace('\\\\"', '\\"')

try:
    data = json.loads(fixed)
    print("JSON is valid after fixing backslashes")
    with open("grafana_dashboard_allsky_complett.json", "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print("File rewritten with json.dump - guaranteed valid JSON")
except json.JSONDecodeError as e:
    print("Still invalid:", e)
except Exception as e:
    print("Error:", e)

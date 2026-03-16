import json
c = open("grafana_dashboard_allsky_complett.json").read()
i = c.find('"type": "timeseries"')
start = c.find("[") + 1
while c[start] in " \n\t":
    start += 1
j = c.find("},", i)
first_panel = c[start:j+1]
print("First panel length:", len(first_panel))
try:
    obj = json.loads("[" + first_panel + "]")
    print("First panel parses OK")
except json.JSONDecodeError as e:
    print("Error:", e.msg, "at", e.pos)
    print("Context:", repr(first_panel[max(0,e.pos-50):e.pos+50]))

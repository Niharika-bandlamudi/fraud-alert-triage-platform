import csv, json, os, glob

os.makedirs("data_json", exist_ok=True)

for path in glob.glob("data_final/*.csv"):
    name = os.path.basename(path).replace(".csv", ".json")
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    with open(os.path.join("data_json", name), "w", encoding="utf-8") as f:
        json.dump(rows, f, indent=2)
    print(f"{name}: {len(rows)} records")

print("JSON export completed!")

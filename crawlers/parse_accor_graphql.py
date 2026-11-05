import json

with open('accor_graphql_3.json', 'r', encoding='utf-8') as f:
    d = json.load(f)

data = d.get('data', {})
print("Top-level keys in data:", list(data.keys()))

# Drill into the GraphQL response
def print_keys(obj, prefix=""):
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, (dict, list)):
                print(f"{prefix}{k}: ({type(v).__name__}, len={len(v)})")
                if isinstance(v, dict):
                    print_keys(v, prefix + "  ")
                elif isinstance(v, list) and len(v) > 0 and isinstance(v[0], dict):
                    print(f"{prefix}  [0] keys: {list(v[0].keys())}")
            else:
                print(f"{prefix}{k}: {str(v)[:60]}")

print("\n--- GRAPHQL STRUCTURE ---")
print_keys(data)

---
name: data-processing
description: |
  JSON processing, data transformation, jq, parsing, formatting, CSV,
  YAML, XML, data extraction, data cleaning, ETL, streaming data,
  large file processing, data validation, schema validation.

  Trigger phrases: parse JSON, jq query, transform data, CSV to JSON,
  YAML parsing, extract field, data cleaning, validate schema, format JSON,
  pretty print, minify, filter data, map data, reduce data, aggregate,
  stream processing, large file, chunk processing, data pipeline.
---

# Data Processing

Tools for transforming and processing data.

## Primary Tools

### jq - JSON Processing
```bash
# Pretty print
cat file.json | jq '.'

# Extract field
jq '.field' file.json

# Filter array
jq '.[] | select(.status == "active")' file.json

# Transform
jq '{name: .title, id: .uuid}' file.json
```

### Common jq Patterns
```bash
# Get all keys
jq 'keys' file.json

# Count items
jq 'length' file.json

# Flatten nested
jq '.[].items[]' file.json

# Group by field
jq 'group_by(.category)' file.json

# Unique values
jq '[.[].type] | unique' file.json
```

## Format Conversion

### JSON ↔ CSV
```bash
# JSON to CSV
jq -r '.[] | [.name, .value] | @csv' file.json

# CSV to JSON (Python)
python -c "import csv,json; print(json.dumps(list(csv.DictReader(open('file.csv')))))"
```

### JSON ↔ YAML
```bash
# YAML to JSON
yq -o json file.yaml

# JSON to YAML
yq -P file.json
```

## Data Validation

### JSON Schema
```bash
# Validate against schema
jsonschema -i data.json schema.json

# Python
from jsonschema import validate
validate(instance=data, schema=schema)
```

### Type Checking
```bash
# Check structure
jq 'type' file.json  # object, array, string, etc.

# Verify fields exist
jq 'has("required_field")' file.json
```

## Large File Processing

### Streaming JSON
```bash
# Process line by line (JSON Lines)
cat large.jsonl | jq -c 'select(.important)'

# Stream large array
jq --stream 'select(.[0][0] == "items")' large.json
```

### Chunking
```python
import json
def process_chunks(file, chunk_size=1000):
    with open(file) as f:
        data = json.load(f)
        for i in range(0, len(data), chunk_size):
            yield data[i:i+chunk_size]
```

## Python Data Tools

```python
import json
import csv
import yaml  # pip install pyyaml

# Parse
data = json.loads(json_string)
data = yaml.safe_load(yaml_string)

# Transform
result = [transform(item) for item in data]

# Validate
assert all('required' in item for item in data)
```

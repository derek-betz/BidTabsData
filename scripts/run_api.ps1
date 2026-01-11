param(
    [int]$Port = 9008,
    [string]$Host = "0.0.0.0"
)

$env:PYTHONPATH = (Resolve-Path ".").Path
python -m uvicorn bidtabs_api:app --host $Host --port $Port

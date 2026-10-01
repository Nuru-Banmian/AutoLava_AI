"""Export the live FastAPI contract in a stable form for frontend type generation."""

import argparse
import json
from pathlib import Path

from app.main import app


parser = argparse.ArgumentParser()
parser.add_argument(
    "--output",
    type=Path,
    default=Path(__file__).resolve().parents[2] / "frontend" / "src" / "api" / "openapi.json",
)
parser.add_argument("--check", action="store_true")
args = parser.parse_args()

schema = app.openapi()
generated = json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
weather_values = schema["components"]["schemas"]["RecordWeather"]["enum"]
weather_typescript = (
    "// Generated from the backend OpenAPI RecordWeather enum. Do not edit.\n"
    "export const recordWeatherValues = "
    + json.dumps(weather_values, ensure_ascii=False)
    + " as const;\n"
)
weather_output = args.output.with_name("weather-values.ts")
if args.check:
    if not args.output.is_file() or args.output.read_text(encoding="utf-8") != generated:
        parser.exit(1, f"OpenAPI snapshot is stale: {args.output}\n")
    if not weather_output.is_file() or weather_output.read_text(encoding="utf-8") != weather_typescript:
        parser.exit(1, f"Weather values are stale: {weather_output}\n")
else:
    args.output.write_bytes(generated.encode("utf-8"))
    weather_output.write_bytes(weather_typescript.encode("utf-8"))

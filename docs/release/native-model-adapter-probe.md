# Native model Adapter capability probe

Use this disposable probe before selecting or changing a production provider profile. It sends
only synthetic data and validates the configured model's real native-tool behavior:

- two tool definitions are accepted;
- both tools are called in one parallel model turn;
- tool results continue with their original call IDs;
- the model ends with a natural answer;
- Token counts, total latency, and configured estimated cost are available.

Configure `AUTOLAVA_MODEL_*` in the ignored root `.env` or injected environment, then run:

```powershell
cd backend
uv run python -m app.scripts.probe_native_model_adapter
```

The JSON report contains only the configured provider/model labels, capability booleans, counts,
latency, and estimated cost. It excludes the API key, prompts, model answer, and tool payloads.
Keep the output with the release evaluation evidence; do not commit `.env` or provider responses.

Run the probe separately for each candidate profile by changing only environment configuration.
The result informs the provider/model choice and ordering, but neither identifier belongs in the
Agent domain protocol.

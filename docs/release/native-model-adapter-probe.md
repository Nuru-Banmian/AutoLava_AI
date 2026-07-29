# Native model Adapter capability probe

Use this disposable probe before selecting or changing a production provider profile. It sends
only synthetic data and validates the configured model's real native-tool behavior:

- two tool definitions are accepted;
- both tools are called in one parallel model turn;
- tool results continue with their original call IDs;
- the model ends with a natural answer;
- Token counts, total latency, and configured estimated cost are available.

The probe fails closed when the provider omits input Token, output Token, or estimated-cost
measurements. A successful HTTP response or a natural answer alone is not enough to qualify a
production profile.

Configure `AUTOLAVA_MODEL_*`, including both per-million Token cost rates, in the ignored root
`.env` or injected environment, then run:

```powershell
cd backend
uv run python -m app.scripts.probe_native_model_adapter
```

The JSON report contains only the configured provider/model labels, capability booleans, counts,
latency, estimated cost, and five `release_cases` entries:

- `native_tool_calling`
- `parallel_tool_calls`
- `tool_result_continuation`
- `natural_answer`
- `usage_metrics`

It excludes the API key, prompts, model answer, and tool payloads. Keep the output with the release
evaluation evidence; do not commit `.env` or provider responses. Copy the five successful
`release_cases` into the release evaluation's redacted `adapter-cases.json` alongside the six
real-provider error-mapping cases below and the separately measured structured-output, safety, and
two redaction cases. The runtime gate
requires exactly those 15 unique cases and rejects any failed, missing, duplicated, or
artifact-hash-mismatched result.

Run the probe separately for each candidate profile by changing only environment configuration.
The result informs the provider/model choice and ordering, but neither identifier belongs in the
Agent domain protocol. This probe is an operator-run real-provider evaluation: CI must continue to
use only the deterministic Fake model and must not load provider credentials or make paid calls.

## Real provider error mapping

The candidate Adapter must also observe and classify each required provider failure. Prepare a
provider test profile or controlled endpoint that produces the named real failure for the
synthetic request, then run the matching command:

```powershell
uv run python -m app.scripts.probe_native_model_adapter --expect-error timeout
uv run python -m app.scripts.probe_native_model_adapter --expect-error rate_limit
uv run python -m app.scripts.probe_native_model_adapter --expect-error provider_5xx
uv run python -m app.scripts.probe_native_model_adapter --expect-error invalid_api_key
uv run python -m app.scripts.probe_native_model_adapter --expect-error insufficient_balance
uv run python -m app.scripts.probe_native_model_adapter --expect-error invalid_output
```

For example, use an intentionally tiny request timeout for `timeout`, a non-production invalid
Secret for `invalid_api_key`, and provider-supported test accounts or controlled test endpoints for
rate limit, 5xx, balance, and malformed-output cases. The command passes only when the real Adapter
observes exactly the expected provider-neutral category; a successful response, a different
category, or no response failure is rejected. It emits one redacted `release_cases` entry for the
matching release case (`server_error`, `authentication`, and `balance` are the release names for
the corresponding provider-neutral categories).

Do not manufacture these outputs or substitute a local Fake result. If a candidate provider cannot
reproducibly supply one of the six failures, its release evidence is incomplete and production
approval remains false.

# voidcraft-bridge-debug-capture

Let a local coding agent inspect your web app's live state. Your app sends a small snapshot when
someone presses Capture; the agent reads it from the bridge. No account, model or cloud storage.

This is an initial proof of concept using the optional `voidcraft-world-bridge` plugin SDK.
It collects nothing automatically. Choose the fields you want to share and redact them before sending.

## Try it

With uv and Python installed, clone this repository, then run from its root:

```bash
uv sync --locked
VOIDCRAFT_BRIDGE_PLUGINS="$PWD" uv run voidcraft-world-bridge
```

The package metadata and lock pin the reviewed SDK commit until its next package release, including
when installed with pip. The plugin mounts at
`http://127.0.0.1:7682/plugin/debug-capture/`. If another bridge owns that port, configure this
plugin on that bridge instead, or use a spare port and update the browser helper's endpoint.

In another terminal, serve the example from the repository root:

```bash
python3 -m http.server 7790 --bind 127.0.0.1
```

Open `http://127.0.0.1:7790/examples/`, increment the counter, then press **Capture state**.
Your coding agent can read the result with:

```bash
curl http://127.0.0.1:7682/plugin/debug-capture/latest
```

The example must be served from loopback, not opened as a `file:` URL. A browser may ask for local
network permission. The bridge's origin and Host guards still apply, and this plugin additionally
rejects proxy requests and browser requests without an appropriate Origin.

## Add it to your app

Copy `browser/capture.mjs` into your application and call it from a visible capture button:

```js
import { send_capture } from './capture.mjs';

await send_capture({
  version: 1,
  kind: 'editor',
  state: { selected_id: 'item-3', active_tab: 'preview', unsaved: true },
});
```

Options: `endpoint`, `redact(value)`, `max_bytes` (4096 by default), and `timeout_ms` (5000).
Redaction receives a clone of your object before serialization or network access. An oversized
capture is refused rather than silently truncated. Credentials are omitted from the fetch.
The helper does not automatically read DOM, storage, cookies, URLs or console logs.

For server-side redaction, construct `CaptureStore(redact=your_function)` and supply it to
`DebugCapturePlugin(store=store)` from your own `bridge_plugin.py` entry.

## API and storage

| Route | Result |
| --- | --- |
| `POST /capture` | Versioned JSON object → `{id, stored_at, bytes, pruned}` plus plugin metadata |
| `GET /latest` | Newest capture, or `capture: null` when empty |
| `GET /list?limit=10` | Newest-first metadata |
| `GET /get?id=…` | One capture; unknown ids return 404 |
| `GET /state` | Directory, capture count, retention count and newest id |

The store keeps 25 captures in `~/.local/state/voidcraft-world-bridge/debug-capture/`.
Set `VOIDCRAFT_CAPTURE_DIR` to use another directory. Each capture is limited to 4096 bytes
before its storage envelope. Writes are atomic; generated files have owner-only permissions.
The byte budget counts UTF-8 JSON, matching the browser helper. One bridge process writes each
directory. Capture IDs preserve write order within a clock tick and after clock adjustments;
`stored_at` keeps the actual wall-clock time.
Recognized capture filenames are the only files pruned; unrelated JSON and symlinks are ignored.
Retention is count-based, not time-based. Local programs running as you can read the files.

The `version` inside `capture` belongs to your application. The outer envelope's version belongs
to this plugin. Never send secrets or personal data your agent should not receive.

## Development

```bash
uv run voidcraft-world-bridge check-plugin .
uv run pytest tests/test_store.py tests/test_plugin.py tests/test_safety.py
node --test tests/test_capture.mjs
```

Python code uses only the standard library and the public bridge SDK. The browser helper has no
package dependencies. CI runs the Python and helper tests; visual verification of the example is manual.

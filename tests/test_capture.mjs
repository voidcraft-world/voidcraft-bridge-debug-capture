import assert from 'node:assert/strict';
import test from 'node:test';
import { send_capture } from '../browser/capture.mjs';

test('redacts before sending and leaves caller state unchanged', async () => {
  const original = { version: 1, password: 'example', counter: 2 };
  let sent;
  const result = await send_capture(original, {
    redact: value => { delete value.password; return value; },
    fetch_impl: async (url, options) => {
      sent = options;
      return { ok: true, json: async () => ({ id: 'saved' }) };
    },
  });
  assert.equal(result.id, 'saved');
  assert.deepEqual(JSON.parse(sent.body), { version: 1, counter: 2 });
  assert.equal(sent.credentials, 'omit');
  assert.equal(original.password, 'example');
});

test('byte budget counts Unicode and rejects before the network', async () => {
  let called = false;
  await assert.rejects(send_capture({ version: 1, text: '😀'.repeat(20) }, {
    max_bytes: 50, fetch_impl: async () => { called = true; },
  }), RangeError);
  assert.equal(called, false);
});

test('reports server refusal', async () => {
  await assert.rejects(send_capture({ version: 1 }, {
    fetch_impl: async () => ({ ok: false, status: 403, json: async () => ({ error: 'refused' }) }),
  }), /refused/);
});

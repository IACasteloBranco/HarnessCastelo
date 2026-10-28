import assert from 'node:assert/strict';
import {test} from 'node:test';
import {validConversationObservation} from '../src/background/capture-validation.js';

test('accepts the first prompt before ChatGPT assigns a conversation URL', () => {
  assert.equal(validConversationObservation({capture_status: 'unknown',
    reason: 'ID da conversa indisponível no momento do envio'}, 'https://chatgpt.com/'), true);
});

test('requires an observed conversation URL to share the sender origin', () => {
  assert.equal(validConversationObservation({capture_status: 'observed',
    url: 'https://chatgpt.com/c/123'}, 'https://chatgpt.com/'), true);
  assert.equal(validConversationObservation({capture_status: 'observed',
    url: 'https://example.com/c/123'}, 'https://chatgpt.com/'), false);
  assert.equal(validConversationObservation({capture_status: 'unknown',
    reason: 'context unknown', url: 'https://example.com/'}, 'https://chatgpt.com/'), false);
});

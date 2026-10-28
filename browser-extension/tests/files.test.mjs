import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {test} from 'node:test';
import vm from 'node:vm';

const source = await readFile(new URL('../src/content/files.js', import.meta.url), 'utf8');

function createFiles(document = null, MutationObserver = null) {
  const location = {pathname: '/conversation/1'};
  const context = {Number, location, document, MutationObserver};
  context.globalThis = context;
  vm.runInNewContext(source, context);
  return {api: context.GovernancaFiles, location};
}

const serialize = value => JSON.parse(JSON.stringify(value));

test('observes only file metadata inside the submitted composer', () => {
  let bytesRead = false;
  const file = {name: 'relatorio-sintetico.pdf', type: 'application/pdf', size: 1234,
    arrayBuffer() { bytesRead = true; throw new Error('file bytes must not be read'); }};
  const root = {querySelectorAll: selector => selector === 'input[type="file"]' ? [{files: [file]}] : []};

  const observation = serialize(createFiles().api.observe(root));

  assert.deepEqual(observation, {capture_status: 'observed', truncated: false, items: [{
    name: 'relatorio-sintetico.pdf', mime_type: 'application/pdf', size_bytes: 1234,
    capture_status: 'metadata_only', source: 'selection_event'
  }]});
  assert.equal(bytesRead, false);
});

test('preserves duplicate filenames and unknown MIME without guessing', () => {
  const {api: files} = createFiles();
  const root = {querySelectorAll: () => [{files: [
    {name: 'anexo.txt', type: '', size: 12}, {name: 'anexo.txt', type: '', size: 13}
  ]}]};

  const observation = serialize(files.observe(root));

  assert.equal(observation.items.length, 2);
  assert.equal(observation.items[0].mime_type, null);
  assert.equal(observation.items[0].size_bytes, 12);
  assert.equal(observation.items[1].size_bytes, 13);
});

test('captures a visible composer card after ChatGPT clears the file input', () => {
  const {api: files} = createFiles();
  const root = {querySelectorAll: selector => selector === '[data-composer-attachments] button[aria-label]'
    ? [{getAttribute: name => name === 'aria-label' ? 'synthetic-document.txt' : null},
      {getAttribute: name => name === 'aria-label' ? 'Remover synthetic-document.txt' : null}]
    : []};

  const observation = serialize(files.observe(root));

  assert.deepEqual(observation, {capture_status: 'observed', truncated: false, items: [{
    name: 'synthetic-document.txt', mime_type: null, size_bytes: null,
    capture_status: 'metadata_only', source: 'visible_card'
  }]});
});

test('matches selection metadata after FileList clears and the composer node is replaced', () => {
  const {api: files} = createFiles();
  const file = {name: 'synthetic-document.txt', type: 'text/plain', size: 48,
    arrayBuffer() { throw new Error('file bytes must not be read'); }};
  const input = {files: [file]};
  const submittedRoot = {querySelectorAll: selector => selector === 'input[type="file"]' ? [input] :
    [{getAttribute: name => name === 'aria-label' ? file.name : null}]};

  files.rememberSelection(input);
  input.files = [];
  const observation = files.observe(submittedRoot);

  assert.deepEqual(serialize(observation), {capture_status: 'observed', truncated: false, items: [{
    name: file.name, mime_type: 'text/plain', size_bytes: 48,
    capture_status: 'metadata_only', source: 'selection_event'
  }]});
  files.consume(observation);
  assert.equal(serialize(files.observe(submittedRoot)).items[0].source, 'visible_card');
});

test('matches selection metadata when ChatGPT adds a duplicate-name suffix to the card', () => {
  const {api: files} = createFiles();
  const input = {files: [{name: 'synthetic-document.txt', type: 'text/plain', size: 156}]};
  const root = {querySelectorAll: selector => selector === 'input[type="file"]' ? [input] :
    [{getAttribute: name => name === 'aria-label' ? 'synthetic-document(10).txt' : null}]};

  files.rememberSelection(input);
  input.files = [];

  assert.deepEqual(serialize(files.observe(root)).items, [{name: 'synthetic-document.txt',
    mime_type: 'text/plain', size_bytes: 156, capture_status: 'metadata_only', source: 'selection_event'}]);
});

test('matches selection metadata when ChatGPT adds a timestamp suffix to the card', () => {
  const {api: files} = createFiles();
  const input = {files: [{name: 'synthetic-document.txt', type: 'text/plain', size: 156}]};
  const root = {querySelectorAll: selector => selector === 'input[type="file"]' ? [input] :
    [{getAttribute: name => name === 'aria-label' ? 'synthetic-document(20261014-195506).txt' : null}]};

  files.rememberSelection(input);
  input.files = [];

  assert.deepEqual(serialize(files.observe(root)).items, [{name: 'synthetic-document.txt',
    mime_type: 'text/plain', size_bytes: 156, capture_status: 'metadata_only', source: 'selection_event'}]);
});

test('deduplicates input and change events for the same FileList', () => {
  const {api: files} = createFiles();
  const input = {files: [{name: 'synthetic.txt', type: 'text/plain', size: 7}]};
  const root = {querySelectorAll: selector => selector === 'input[type="file"]' ? [input] :
    [{getAttribute: () => 'synthetic.txt'}]};

  files.rememberSelection(input);
  files.rememberSelection(input);
  input.files = [];

  const observation = serialize(files.observe(root));
  assert.equal(observation.items[0].size_bytes, 7);
  assert.equal(observation.items[0].association_status, undefined);
});

test('watches dynamically created file inputs directly', () => {
  const handlers = new Map();
  let observeMutations;
  const input = {files: [{name: 'synthetic.txt', type: 'text/plain', size: 7}],
    matches: selector => selector === 'input[type="file"]',
    addEventListener: (type, handler) => handlers.set(type, handler)};
  const documentRoot = {querySelectorAll: () => []};
  const document = {documentElement: documentRoot, addEventListener: () => {}};
  class FakeMutationObserver {
    constructor(callback) { observeMutations = callback; }
    observe() {}
  }
  const {api: files} = createFiles(document, FakeMutationObserver);
  observeMutations([{addedNodes: [input]}]);
  handlers.get('input')();
  handlers.get('change')();
  input.files = [];

  const root = {querySelectorAll: selector => selector === 'input[type="file"]' ? [input] :
    [{getAttribute: () => 'synthetic.txt'}]};
  const observation = serialize(files.observe(root));
  assert.equal(observation.items[0].source, 'selection_event');
  assert.equal(observation.items[0].mime_type, 'text/plain');
  assert.equal(observation.items[0].size_bytes, 7);
});

test('captures metadata from a pasted file without reading its bytes', () => {
  let onPaste;
  const document = {documentElement: {querySelectorAll: () => []},
    addEventListener: (type, handler) => { if (type === 'paste') onPaste = handler; }};
  const {api: files} = createFiles(document);
  const file = {name: 'synthetic-document.txt', type: 'text/plain', size: 156,
    arrayBuffer() { throw new Error('file bytes must not be read'); }};
  const root = {querySelectorAll: selector => selector === '[data-composer-attachments] button[aria-label]'
    ? [{getAttribute: name => name === 'aria-label' ? 'synthetic-document(20261014-200718).txt' : null}]
    : []};

  onPaste({clipboardData: {types: ['Files'], files: [], items: [{kind: 'file', type: 'text/plain',
    getAsFile: () => file}]}});

  assert.deepEqual(serialize(files.observe(root)).items, [{name: file.name, mime_type: 'text/plain',
    size_bytes: 156, capture_status: 'metadata_only', source: 'selection_event'}]);
});

test('captures metadata from a dropped file without reading its bytes', () => {
  const handlers = new Map();
  const document = {documentElement: {querySelectorAll: () => []},
    addEventListener: (type, handler) => handlers.set(type, handler)};
  const {api: files} = createFiles(document);
  const file = {name: 'synthetic-document.txt', type: 'text/plain', size: 156,
    arrayBuffer() { throw new Error('file bytes must not be read'); }};
  const root = {querySelectorAll: selector => selector === '[data-composer-attachments] button[aria-label]'
    ? [{getAttribute: name => name === 'aria-label' ? 'synthetic-document(20261014-203716).txt' : null}]
    : []};

  handlers.get('drop')({dataTransfer: {files: [file]}});

  assert.deepEqual(serialize(files.observe(root)).items, [{name: file.name, mime_type: 'text/plain',
    size_bytes: 156, capture_status: 'metadata_only', source: 'selection_event'}]);
});

test('does not guess which duplicate card matches each selection snapshot', () => {
  const {api: files} = createFiles();
  const input = {files: [
    {name: 'same.txt', type: 'text/plain', size: 12},
    {name: 'same.txt', type: 'text/plain', size: 13}
  ]};
  const root = {querySelectorAll: selector => selector === 'input[type="file"]' ? [input] :
    [12, 13].map(() => ({getAttribute: () => 'same.txt'}))};

  files.rememberSelection(input);
  input.files = [];

  assert.deepEqual(serialize(files.observe(root)).items.map(item => [item.size_bytes, item.association_status]),
    [[null, 'ambiguous'], [null, 'ambiguous']]);
});

test('keeps a selection snapshot when the card has not rendered yet', () => {
  const {api: files} = createFiles();
  const input = {files: [{name: 'removed.txt', type: 'text/plain', size: 12}]};
  let attached = false;
  const root = {querySelectorAll: selector => selector === 'input[type="file"]' ? [input] :
    attached ? [{getAttribute: () => 'removed.txt'}] : []};

  files.rememberSelection(input);
  input.files = [];
  assert.equal(files.observe(root).capture_status, 'not_observed');

  attached = true;
  const observation = serialize(files.observe(root));

  assert.equal(observation.items[0].mime_type, 'text/plain');
  assert.equal(observation.items[0].size_bytes, 12);
});

test('marks duplicate-name correlations ambiguous instead of guessing', () => {
  const {api: files} = createFiles();
  const input = {files: [{name: 'same.txt', type: 'text/plain', size: 12},
    {name: 'same.txt', type: 'text/plain', size: 13}]};
  const root = {querySelectorAll: selector => selector === 'input[type="file"]' ? [input] :
    [0, 1].map(() => ({getAttribute: () => 'same.txt'}))};

  files.rememberSelection(input);
  input.files = [];
  const observation = serialize(files.observe(root));

  assert.deepEqual(observation.items, [12, 13].map(() => ({name: 'same.txt', mime_type: null,
    size_bytes: null, capture_status: 'metadata_only', source: 'visible_card',
    association_status: 'ambiguous'})));
});

test('drops selection metadata when navigation changes the conversation route', () => {
  const {api: files, location} = createFiles();
  const input = {files: [{name: 'same.txt', type: 'text/plain', size: 12}]};
  const root = {querySelectorAll: selector => selector === 'input[type="file"]' ? [input] :
    [{getAttribute: () => 'same.txt'}]};

  files.rememberSelection(input);
  input.files = [];
  location.pathname = '/conversation/2';

  assert.equal(serialize(files.observe(root)).items[0].source, 'visible_card');
});

test('merges file input and visible card evidence without duplicating matching files', () => {
  const {api: files} = createFiles();
  const root = {querySelectorAll: selector => selector === 'input[type="file"]'
    ? [{files: [{name: 'known.txt', type: 'text/plain', size: 4}]}]
    : [{getAttribute: () => 'known.txt'}, {getAttribute: () => 'card-only.pdf'}]};

  const observation = serialize(files.observe(root));

  assert.equal(observation.items.length, 2);
  assert.equal(observation.items[0].source, 'selection_event');
  assert.deepEqual(observation.items[1], {name: 'card-only.pdf', mime_type: null, size_bytes: null,
    capture_status: 'metadata_only', source: 'visible_card'});
});

test('distinguishes empty and unavailable composer observations and reports truncation', () => {
  const {api: files} = createFiles();
  const empty = serialize(files.observe({querySelectorAll: () => [{files: []}]}));
  const missing = serialize(files.observe({querySelectorAll: () => []}));
  const many = serialize(files.observe({querySelectorAll: () => [{files: Array.from({length: 21}, (_, i) => ({
    name: `file-${i}.txt`, type: 'text/plain', size: i
  }))}]}));

  assert.deepEqual(empty, {capture_status: 'not_observed', items: [], truncated: false});
  assert.deepEqual(missing, {capture_status: 'unavailable', items: [], truncated: false});
  assert.equal(many.items.length, 20);
  assert.equal(many.truncated, true);
});

(() => {
  globalThis.GovernancaCaptureAdapter = Object.freeze({
    platform: 'chatgpt_web',
    requestMethod: 'POST',
    requestPath: '/backend-api/f/conversation',
    contentType: 'text/event-stream',
    doneMarker: '[DONE]',
    version: '0.3.0'
  });
})();

export function validConversationObservation(conversation, senderUrl) {
  if (conversation?.capture_status === 'unknown')
    return !conversation.url && typeof conversation.reason === 'string' &&
      conversation.reason.length > 0 && conversation.reason.length <= 240;
  if (conversation?.capture_status !== 'observed') return false;
  try { return new URL(conversation.url).origin === new URL(senderUrl).origin; }
  catch { return false; }
}

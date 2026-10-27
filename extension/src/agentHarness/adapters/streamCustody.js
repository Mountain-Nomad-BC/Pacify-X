'use strict';

function aborted() { return Object.assign(new Error('provider-stream-aborted'), { name: 'AbortError' }); }

async function withStreamReader(body, signal, consume) {
  const reader = body.getReader(); let cancellation = null; let failure = null;
  const cancel = () => {
    if (!cancellation) cancellation = Promise.resolve().then(() => reader.cancel());
    return cancellation;
  };
  const onAbort = () => { void cancel().catch(() => {}); };
  signal?.addEventListener?.('abort', onAbort, { once: true });
  try {
    if (signal?.aborted) throw aborted();
    const result = await consume(reader);
    if (signal?.aborted) throw aborted();
    return result;
  } catch (error) {
    failure = signal?.aborted ? aborted() : error;
    throw failure;
  } finally {
    signal?.removeEventListener?.('abort', onAbort);
    let timer;
    try {
      await Promise.race([cancel(), new Promise((_, reject) => {
        timer = setTimeout(() => reject(new Error('provider-stream-custody-unsettled')), 1000);
      })]);
    } catch (error) {
      if (!failure) throw error;
      if (Object.isExtensible(failure)) failure.cleanupError = String(error.message || error);
    } finally { clearTimeout(timer); reader.releaseLock(); }
  }
}

async function errorPreview(response, signal) {
  if (!response.body) return '';
  return withStreamReader(response.body, signal, async reader => {
    const decoder = new TextDecoder(); let text = '';
    while (text.length < 1024) {
      const {done, value} = await reader.read(); if (done) break;
      text += decoder.decode(value.subarray(0, 4096), {stream: true});
    }
    return text.slice(0, 1024);
  });
}

module.exports = { withStreamReader, errorPreview };

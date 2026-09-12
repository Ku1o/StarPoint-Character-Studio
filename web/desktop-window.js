/* Native close uses the same save queue as the visible Save/Exit buttons. */
'use strict';
(() => {
  let closing = false;
  const cancelClose = () => api('/api/desktop-close-cancel', {}).catch(() => {});
  window.addEventListener('studio-desktop-close', async () => {
    if (closing) return;
    if (!document.querySelector('#busy')?.hidden) {
      toast('当前操作正在处理中，请完成后再关闭窗口。');
      await cancelClose();
      return;
    }
    closing = true;
    try {
      // Many fields commit on change/blur. Alt+F4 and WM_CLOSE need not blur the
      // focused input, so commit its last typed value before flushing the queue.
      document.activeElement?.blur();
      stop();
      await saveNow();
      await api('/api/shutdown', {});
    } catch (error) {
      toast('保存未完成，窗口已保留：' + error.message, true);
      await cancelClose();
    } finally {
      closing = false;
    }
  });
  // app.js owns session initialization; wait until its token is ready without
  // weakening CSP or exposing a native/Python bridge to untrusted page content.
  const announce = async () => {
    if (!S.token) { setTimeout(announce, 100); return; }
    try { await api('/api/desktop-ready', {}); } catch (_) {}
  };
  announce();
})();

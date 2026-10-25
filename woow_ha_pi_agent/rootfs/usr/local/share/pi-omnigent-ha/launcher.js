(() => {
  if (document.getElementById('ha-omnigent-link')) return;
  const prefix = window.__INGRESS_PATH__ || '';
  const link = document.createElement('a');
  link.id = 'ha-omnigent-link'; link.href = `${prefix}/omnigent`;
  link.textContent = 'Omnigent'; link.title = 'Omnigent 連線設定';
  link.style.cssText = 'position:fixed;right:12px;top:12px;z-index:1000;background:Canvas;color:CanvasText;border:1px solid GrayText;border-radius:6px;padding:8px 12px;font:14px system-ui;text-decoration:none';
  document.body.append(link);
})();

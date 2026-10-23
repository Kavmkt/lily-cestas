(function () {
  function ev(name, params) { try { if (window.gtag) window.gtag('event', name, params || {}); } catch (e) {} }
  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a');
    if (!a) return;
    var href = a.getAttribute('href') || '';
    var base = { page_path: location.pathname };
    if (href.indexOf('wa.me') > -1) {
      if (a.id === 'whatsapp-direct-link') { ev('generate_lead', { currency: 'BRL', link_location: 'finalizar_pedido', page_path: base.page_path }); return; }
      var where = (a.className || '').indexOf('wafab') > -1 ? 'botao_flutuante' : 'pagina';
      ev('whatsapp_click', { link_location: where, page_path: base.page_path });
    } else if (href.indexOf('ifood.com.br') > -1) {
      ev('ifood_click', base);
    } else if (href.indexOf('instagram.com') > -1) {
      ev('instagram_click', base);
    } else if (a.getAttribute('data-ga')) {
      ev(a.getAttribute('data-ga'), { item_id: a.getAttribute('data-ga-item') || '', page_path: base.page_path });
    }
  }, true);
})();

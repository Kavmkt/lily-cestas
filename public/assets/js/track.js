(function () {
  function ev(name, params) { try { if (window.gtag) window.gtag('event', name, params || {}); } catch (e) {} }
  document.addEventListener('click', function (e) {
    var a = e.target.closest && e.target.closest('a');
    if (!a) return;
    var href = a.getAttribute('href') || '';
    var base = { page_path: location.pathname };
    if (href.indexOf('wa.me') > -1) {
      if (a.id === 'whatsapp-direct-link') {
        var o = window.__lilyOrder || {};
        var p = { currency: 'BRL', value: o.value || 0, payment_type: o.payment_type || '', items: o.items || [], link_location: 'finalizar_pedido', page_path: base.page_path };
        ev('generate_lead', p);
        // Google Ads: conversão "pedido enviado" (só dispara se o código do Google Ads estiver configurado)
        try { var ads = window.LILY_ADS || {}; if (ads.lead && window.gtag) window.gtag('event', 'conversion', { send_to: ads.lead, value: o.value || 0, currency: 'BRL' }); } catch (e) {}
        return;
      }
      var where = (a.className || '').indexOf('wafab') > -1 ? 'botao_flutuante' : 'pagina';
      ev('whatsapp_click', { link_location: where, page_path: base.page_path });
      try { var ads2 = window.LILY_ADS || {}; if (ads2.contato && window.gtag) window.gtag('event', 'conversion', { send_to: ads2.contato }); } catch (e) {}
    } else if (href.indexOf('ifood.com.br') > -1) {
      ev('ifood_click', base);
    } else if (href.indexOf('instagram.com') > -1) {
      ev('instagram_click', base);
    } else if (a.getAttribute('data-ga')) {
      ev(a.getAttribute('data-ga'), { item_id: a.getAttribute('data-ga-item') || '', page_path: base.page_path });
    }
  }, true);
})();

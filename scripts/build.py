#!/usr/bin/env python3
"""Gera o site da Lily Cestas a partir dos arquivos em data/.

Uso: python3 scripts/build.py   (saida em _site/)
Quem edita produtos, categorias e precos pelo painel nao precisa mexer neste arquivo.
"""
import datetime
import hashlib
import html
import json
import re
import shutil
import sys
import unicodedata
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / '_site'
BASE = 'https://lilycestas.com.br'
ERRORS = []

try:
    from PIL import Image, ImageOps
    try:
        import pillow_heif
        pillow_heif.register_heif_opener()
    except Exception:
        pass
except Exception:  # pragma: no cover
    Image = None


# ---------------------------------------------------------------- utilidades
def fail(msg):
    ERRORS.append(msg)


def slugify(s):
    s = unicodedata.normalize('NFKD', str(s)).encode('ascii', 'ignore').decode().lower()
    return re.sub(r'[^a-z0-9]+', '-', s).strip('-')


def esc(s):
    return html.escape(str(s), quote=True)


def brl(v):
    return ('R$ %.2f' % v).replace('.', ',')


def load_json(path, default=None):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        if default is not None:
            return default
        fail(f'Arquivo não encontrado: {path.relative_to(ROOT)}')
    except json.JSONDecodeError as e:
        fail(f'O arquivo {path.relative_to(ROOT)} tem um erro de formatação (linha {e.lineno}). Desfaça a última alteração.')
    return {}


def to_number(value, where, required=True):
    if value in (None, ''):
        if required:
            fail(f'{where}: falta preencher o valor.')
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).replace('R$', '').replace(' ', '').strip()
    if ',' in s:
        s = s.replace('.', '').replace(',', '.')
    try:
        return float(s)
    except ValueError:
        fail(f'{where}: "{value}" não é um número válido. Use apenas números, por exemplo 89,90.')
        return None


# ---------------------------------------------------------------- dados
config = {
    'loja_no_ar': False, 'whatsapp': '5511914955434', 'instagram': 'https://www.instagram.com/lilycestas.ofc/',
    'ifood_url': 'https://www.ifood.com.br/delivery/santana-de-parnaiba-sp/lily-cestas--presentes-colinas-da-anhanguera/25073e59-c1d1-43a8-a317-7f5c948f97ab',
    'pix_desconto': 5, 'taxa_entrega': 15, 'entrega_gratis_a_partir': 125, 'pedido_minimo': 35, 'brinde1_valor': 150, 'brinde1_nome': 'Chaveiro de brinde',
    'foto_chaveiro_simples': '',
    'entrega_rapida_horas': 2,
    'popup_brinde_ativo': True, 'popup_brinde_segundos': 5,
    'brinde_opcao1_nome': 'Coração 3D', 'brinde_opcao2_nome': 'Mãozinha de coração', 'foto_chaveiro_2': '/assets/brinde/chaveiro-maozinha-coracao.webp',
    'nome_proprietaria': 'Alicya Lima', 'cargo_proprietaria': 'Proprietária e criadora da Lily Cestas', 'foto_proprietaria': '/assets/equipe/alycia-lima.webp',
    'foto_estudio_litofania': '', 'foto_estudio_polaroid': '', 'ga4_id': '', 'clarity_id': '',
}
config.update({k: v for k, v in load_json(ROOT / 'data/config.json', {}).items() if v not in (None, '')})
config['whatsapp'] = re.sub(r'\D', '', str(config['whatsapp']))
if len(config['whatsapp']) in (10, 11):
    config['whatsapp'] = '55' + config['whatsapp']
for k in ('pix_desconto', 'taxa_entrega', 'brinde1_valor', 'entrega_gratis_a_partir', 'pedido_minimo'):
    config[k] = to_number(config[k], f'Configurações › {k}') or 0
LOJA_NO_AR = bool(config['loja_no_ar'])
SHOP = '/' if LOJA_NO_AR else '/home/'   # onde fica a loja completa
WA = config['whatsapp']
FRETE_MIN = config['entrega_gratis_a_partir']
PED_MIN = config['pedido_minimo']
FRETE_TXT = brl(FRETE_MIN).replace(',00', '')
MIN_TXT = brl(PED_MIN).replace(',00', '')
try:
    _fh = int(float(config.get('entrega_rapida_horas') or 0))
except (TypeError, ValueError):
    _fh = 0
FAST_TXT = f'Entrega rápida em até {_fh}h' if _fh > 0 else ''
FAST_NOTE = f'*Entrega em até {_fh}h para produtos prontos, conforme região e horário. Personalizados têm prazo combinado no pedido.' if _fh > 0 else ''
ENTREGA_TXT = f'Entrega grátis em pedidos a partir de {FRETE_TXT}; pedido mínimo de {MIN_TXT}.'
phone = f"+{WA[:2]} {WA[2:4]} {WA[4:-4]}-{WA[-4:]}" if len(WA) >= 12 else '+' + WA

# categorias
cats = []
for f in sorted((ROOT / 'data/categorias').glob('*.json')):
    c = load_json(f)
    if not c:
        continue
    c['_stem'] = f.stem
    c['chave'] = slugify(c.get('chave') or f.stem)
    if not c.get('nome'):
        fail(f'Categoria {f.name}: falta o nome.')
    c.setdefault('nome_curto', c.get('nome', ''))
    c.setdefault('icone', '🎁')
    c['nome_tile'] = c.get('nome_tile') or c['nome_curto']
    c['ordem'] = to_number(c.get('ordem'), f'Categoria {f.name} › ordem', False) or 999
    c['pagina_url'] = slugify(c.get('pagina_url') or c['chave'])
    cats.append(c)
cats_all = sorted(cats, key=lambda c: (c['ordem'], c['nome']))
cats = [c for c in cats_all if c.get('ativa', True)]
if len({c['chave'] for c in cats_all}) != len(cats_all):
    fail('Duas categorias estão com a mesma "chave interna". Cada categoria precisa de uma chave diferente.')


def resolve_cat(value):
    v = str(value or '').strip()
    v = re.sub(r'\.json$', '', v.split('/')[-1])
    for c in cats_all:
        if v in (c['chave'], c['_stem']) or slugify(v) in (c['chave'], slugify(c['nome']), slugify(c['nome_curto'])):
            return c
    return None


# produtos
prods = []
seen = set()
for f in sorted((ROOT / 'data/produtos').glob('*.json')):
    p = load_json(f)
    if not p:
        continue
    where = f'Produto "{p.get("nome") or f.name}"'
    p['id'] = f.stem
    if not p.get('nome'):
        fail(f'Produto {f.name}: falta o nome.')
    cat = resolve_cat(p.get('categoria'))
    if not cat:
        fail(f'{where}: a categoria "{p.get("categoria")}" não existe. Escolha uma categoria da lista.')
        continue
    p['_cat'] = cat
    p['preco'] = to_number(p.get('preco'), f'{where} › preço')
    if p['preco'] is not None and p['preco'] <= 0:
        fail(f'{where}: o preço precisa ser maior que zero.')
    promo = to_number(p.get('preco_promocional'), f'{where} › preço promocional', False)
    if promo and p['preco'] and promo >= p['preco']:
        fail(f'{where}: o preço promocional (R$ {promo:.2f}) precisa ser menor que o preço normal.')
        promo = None
    p['_promo'] = promo
    p['status'] = (p.get('status') or 'ativo').strip().lower()
    if p['status'] not in ('ativo', 'esgotado', 'oculto'):
        fail(f'{where}: situação "{p["status"]}" inválida. Use Ativo, Esgotado ou Oculto.')
    foto = (p.get('foto') or '').lstrip('/')
    if p['status'] != 'oculto' and (not foto or not (ROOT / foto).exists()):
        fail(f'{where}: a foto não foi encontrada. Envie a foto de novo no painel.')
    p['_foto'] = foto
    p['ordem'] = to_number(p.get('ordem'), f'{where} › ordem', False) or 999
    p.setdefault('selo', '')
    p.setdefault('descricao', '')
    p.setdefault('personalizacao', '')
    p['inclui'] = [x for x in (p.get('inclui') or []) if x]
    p['quiz'] = p.get('quiz') or []
    prods.append(p)
visible = sorted([p for p in prods if p['status'] != 'oculto' and p['_cat'].get('ativa', True)], key=lambda p: (p['ordem'], p['nome']))
active = [p for p in visible if p['status'] == 'ativo']
if not visible:
    fail('Não há nenhum produto visível. Deixe ao menos um produto como Ativo.')
if not cats:
    fail('Não há nenhuma categoria ativa.')


def final_price(p):
    return p['_promo'] or p['preco']


cats_with = [c for c in cats if any(p['_cat'] is c for p in visible)]
cat_prods = {c['chave']: [p for p in visible if p['_cat'] is c] for c in cats}
# categorias ativas ainda sem produtos aparecem na home (cartão e filtro), sem página própria
cats_home = [c for c in cats if c in cats_with or (not cat_prods[c['chave']] and c.get('foto'))]

# adicionais (upsell: cartao com frase, polaroid...)
addons = []
for f in sorted((ROOT / 'data/adicionais').glob('*.json')):
    a = load_json(f)
    if not a:
        continue
    where = f'Adicional "{a.get("nome") or f.name}"'
    if not a.get('nome'):
        fail(f'Adicional {f.name}: falta o nome.')
        continue
    a['id'] = f.stem
    a['preco'] = to_number(a.get('preco'), f'{where} › preço')
    promo = to_number(a.get('preco_promocional'), f'{where} › preço promocional', False)
    if promo and a['preco'] and promo >= a['preco']:
        fail(f'{where}: o preço promocional precisa ser menor que o preço normal.')
        promo = None
    a['_promo'] = promo
    a['status'] = (a.get('status') or 'ativo').strip().lower()
    a['ordem'] = to_number(a.get('ordem'), f'{where} › ordem', False) or 999
    a['pede'] = a.get('pede') or 'nada'
    a.setdefault('descricao', '')
    if a['status'] == 'ativo' and a['preco']:
        addons.append(a)
addons.sort(key=lambda a: (a['ordem'], a['nome']))

# estudio
estudio = load_json(ROOT / 'data/estudio.json', {})
SIM = {}
for key, label in (('bases', 'Base do presente'), ('louca', 'Louça'), ('pecas_3d', 'Peça 3D'), ('polaroids', 'Polaroids')):
    opts = []
    for i, o in enumerate(estudio.get(key) or []):
        w = f'Estúdio › {label} › item {i + 1}'
        if not o.get('nome') or not o.get('chave'):
            fail(f'{w}: preencha o nome e a chave.')
            continue
        o['preco'] = to_number(o.get('preco'), f'{w} ({o["nome"]}) › preço') or 0
        o['texto_menu'] = o.get('texto_menu') or o['nome']
        opts.append(o)
    if not opts:
        fail(f'Estúdio › {label}: precisa ter pelo menos uma opção.')
    SIM[key] = opts

faq = [(x.get('pergunta'), x.get('resposta')) for x in (load_json(ROOT / 'data/faq.json', {}).get('perguntas') or []) if x.get('pergunta') and x.get('resposta')]

if ERRORS:
    print('\nO SITE NÃO FOI ATUALIZADO. Corrija os pontos abaixo no painel e salve de novo:\n')
    for e in ERRORS:
        print(' •', e)
    sys.exit(1)

# ---------------------------------------------------------------- saida
if OUT.exists():
    shutil.rmtree(OUT)
shutil.copytree(ROOT / 'public', OUT, ignore=shutil.ignore_patterns('links.html'))
(OUT / 'assets/p').mkdir(parents=True, exist_ok=True)

_img_cache = {}


def img_url(path):
    """Redimensiona a foto (largura max 1000px, WebP) e devolve a URL publica."""
    rel = (path or '').lstrip('/')
    if not rel:
        return ''
    if rel in _img_cache:
        return _img_cache[rel]
    src = ROOT / rel
    if not src.exists():
        return '/' + rel
    data = src.read_bytes()
    h = hashlib.sha1(data).hexdigest()[:8]
    name = f'{slugify(src.stem)[:40]}-{h}.webp'
    dest = OUT / 'assets/p' / name
    if Image is None:
        dest = OUT / 'assets/p' / f'{slugify(src.stem)[:40]}-{h}{src.suffix.lower()}'
        shutil.copy(src, dest)
    else:
        try:
            im = ImageOps.exif_transpose(Image.open(src))
            if im.width > 1000:
                im = im.resize((1000, round(im.height * 1000 / im.width)), Image.LANCZOS)
            im = im.convert('RGBA' if 'A' in im.mode else 'RGB')
            im.save(dest, 'WEBP', quality=82, method=6)
        except Exception as e:
            print(f'Aviso: não foi possível otimizar {rel} ({e}); usando o original.')
            dest = OUT / 'assets/p' / f'{slugify(src.stem)[:40]}-{h}{src.suffix.lower()}'
            shutil.copy(src, dest)
    _img_cache[rel] = '/assets/p/' + dest.name
    return _img_cache[rel]


for p in visible:
    p['_img'] = img_url(p['_foto'])
for c in cats:
    first = (cat_prods.get(c['chave']) or [None])[0]
    c['_img'] = img_url(c.get('foto')) or (first['_img'] if first else '')
for a in addons:
    a['_img'] = img_url(a.get('foto'))
photo_lit = img_url(config.get('foto_estudio_litofania')) or next((p['_img'] for p in visible if 'litofania' in slugify(p['nome'])), visible[0]['_img'])
photo_pol = img_url(config.get('foto_estudio_polaroid')) or visible[0]['_img']


def cat_min(c):
    ps = [final_price(p) for p in cat_prods.get(c['chave'], []) if p['status'] == 'ativo'] or [final_price(p) for p in cat_prods.get(c['chave'], [])]
    return min(ps) if ps else 0


PRECO_MIN = min(final_price(p) for p in (active or visible))

# ---------------------------------------------------------------- JSON-LD
BUSINESS = {
    '@type': ['Store', 'LocalBusiness'], '@id': BASE + '/#negocio', 'name': 'Lily Cestas',
    'alternateName': 'Lily Cestas & Atelier Personalizados', 'url': BASE + '/',
    'image': BASE + '/assets/img/og-lily-cestas.jpg', 'logo': BASE + '/assets/img/icon-512.png',
    'description': 'Atelier de cestas de presente, cestas de café da manhã, canecas personalizadas e presentes em 3D em Santana de Parnaíba, SP. Entregas em Santana de Parnaíba, Alphaville, Barueri, Cajamar, Osasco e Carapicuíba, com entrega grátis a partir de ' + FRETE_TXT + '.',
    'priceRange': f'R${int(PRECO_MIN)} - R${int(max(final_price(p) for p in visible))}',
    'telephone': phone,
    'contactPoint': {'@type': 'ContactPoint', 'telephone': phone, 'contactType': 'customer service', 'availableLanguage': 'Portuguese', 'url': f'https://wa.me/{WA}'},
    'address': {'@type': 'PostalAddress', 'addressLocality': 'Santana de Parnaíba', 'addressRegion': 'SP', 'addressCountry': 'BR'},
    'areaServed': [{'@type': 'City', 'name': n} for n in ['Santana de Parnaíba', 'Barueri', 'Cajamar', 'Osasco', 'Carapicuíba']] + [{'@type': 'Place', 'name': 'Alphaville'}],
    'sameAs': [config['instagram']],
    'openingHoursSpecification': [{'@type': 'OpeningHoursSpecification', 'dayOfWeek': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'], 'opens': '08:00', 'closes': '19:00'}],
}


def prod_url(p):
    return f'/produto/{p["id"]}/'


def prod_desc(p):
    if p.get('descricao'):
        return p['descricao']
    return f'{p["nome"]}: {p["_cat"]["nome"].lower()} da Lily Cestas por {brl(final_price(p))}. Escolha no site e combine os detalhes pelo WhatsApp.'


def prod_ld(p):
    offer = {'@type': 'Offer', 'url': BASE + prod_url(p), 'priceCurrency': 'BRL', 'price': '%.2f' % final_price(p),
             'itemCondition': 'https://schema.org/NewCondition',
             'availability': 'https://schema.org/OutOfStock' if p['status'] == 'esgotado' else 'https://schema.org/InStock',
             'seller': {'@id': BASE + '/#negocio'},
             'shippingDetails': {'@type': 'OfferShippingDetails', 'shippingRate': {'@type': 'MonetaryAmount', 'value': '0.00' if final_price(p) >= FRETE_MIN else '%.2f' % config['taxa_entrega'], 'currency': 'BRL'},
                                 'shippingDestination': {'@type': 'DefinedRegion', 'addressCountry': 'BR', 'addressRegion': 'SP'}}}
    return {'@type': 'Product', 'name': p['nome'], 'url': BASE + prod_url(p), 'sku': p['id'], 'image': BASE + p['_img'], 'description': prod_desc(p),
            'brand': {'@type': 'Brand', 'name': 'Lily Cestas'}, 'category': p['_cat']['nome'], 'offers': offer}


def faq_ld(items):
    return {'@type': 'FAQPage', 'mainEntity': [{'@type': 'Question', 'name': q, 'acceptedAnswer': {'@type': 'Answer', 'text': a}} for q, a in items]}


def crumb_ld(trail):
    return {'@type': 'BreadcrumbList', 'itemListElement': [{'@type': 'ListItem', 'position': i + 1, 'name': n, 'item': BASE + u} for i, (n, u) in enumerate(trail)]}


def jsonld(*nodes):
    return '<script type="application/ld+json">' + json.dumps({'@context': 'https://schema.org', '@graph': list(nodes)}, ensure_ascii=False).replace('</', '<\\/') + '</script>'


def head(title, desc, path, robots='index, follow, max-image-preview:large'):
    url = BASE + path
    return f'''<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<link rel="canonical" href="{url}">
<meta name="robots" content="{robots}">
<meta name="theme-color" content="#B76E79">
<link rel="icon" href="/favicon.ico" sizes="any"><link rel="icon" type="image/png" sizes="192x192" href="/assets/img/icon-192.png"><link rel="apple-touch-icon" href="/assets/img/icon-180.png">
<meta property="og:locale" content="pt_BR"><meta property="og:type" content="website"><meta property="og:site_name" content="Lily Cestas">
<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(desc)}"><meta property="og:url" content="{url}">
<meta property="og:image" content="{BASE}/assets/img/og-lily-cestas.jpg"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630">
<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="{esc(title)}"><meta name="twitter:description" content="{esc(desc)}"><meta name="twitter:image" content="{BASE}/assets/img/og-lily-cestas.jpg">
<meta name="geo.region" content="BR-SP"><meta name="geo.placename" content="Santana de Parnaíba">
'''


# ---------------------------------------------------------------- paginas estaticas (categorias e cidades)
def write_page(path, content):
    d = OUT / path.strip('/')
    d.mkdir(parents=True, exist_ok=True)
    (d / 'index.html').write_text(content, encoding='utf-8')


OWNER_BLOCK = ''
_of = img_url(config.get('foto_proprietaria'))
_on = str(config.get('nome_proprietaria') or '').strip()
if _of and _on:
    OWNER_BLOCK = (f'<div class="owner"><img src="{_of}" alt="{esc(_on)}, {esc(str(config.get("cargo_proprietaria") or "").lower())}" width="56" height="56" loading="lazy" decoding="async">'
                   f'<div><b>{esc(_on)}</b><span>{esc(config.get("cargo_proprietaria") or "")}</span></div></div>')
    BUSINESS['founder'] = {'@type': 'Person', 'name': _on, 'jobTitle': str(config.get('cargo_proprietaria') or 'Proprietária'), 'image': BASE + _of if _of.startswith('/') else _of}

IG_SVG = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="3" width="18" height="18" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.5" cy="6.5" r="1" fill="currentColor" stroke="none"/></svg>'
IG_HANDLE = '@' + config['instagram'].rstrip('/').split('/')[-1]
IG_BTN = f'<a class="igbtn" href="{esc(config["instagram"])}" target="_blank" rel="noopener" data-ga="instagram_click" data-ga-item="rodape">{IG_SVG}<span>Siga {esc(IG_HANDLE)} no Instagram</span></a>'


def footer_html():
    cat_li = ''.join(f'<li><a href="/{c["pagina_url"]}/">{esc(c["nome"])}</a></li>' for c in cats_with if c.get('pagina_url'))
    cat_li += ''.join(f'<li><a href="/{o["slug"]}/">{esc(o["nome"])}</a></li>' for o in OCCASIONS_OK)
    city_li = ''.join(f'<li><a href="/{x["slug"]}/">Presentes em {x["cidade"]}</a></li>' for x in CITIES)
    return f'''<footer class="foot"><div class="wrap grid">
<div><strong>Lily Cestas</strong><p>Atelier de cestas de presente, canecas e peças personalizadas. Santana de Parnaíba, SP.</p><p><a href="https://wa.me/{WA}" rel="noopener" target="_blank">WhatsApp {phone}</a></p>{OWNER_BLOCK}{IG_BTN}</div>
<div><strong>Nossos presentes</strong><ul>{cat_li}</ul></div>
<div><strong>Onde entregamos</strong><ul>{city_li}</ul></div>
</div><p class="copy">© {datetime.date.today().year} Lily Cestas &amp; Atelier Personalizados.</p></footer>
<a class="wafab" href="https://wa.me/{WA}?text={esc('Oi! Vim pelo site da Lily Cestas.')}" target="_blank" rel="noopener" style="position:fixed;right:18px;bottom:18px;z-index:30;background:#25D366;color:#fff;border-radius:99px;padding:12px 18px;font:600 14px Montserrat,sans-serif;text-decoration:none;box-shadow:0 14px 30px -10px rgba(37,211,102,.7)">💬 WhatsApp</a>'''


def top_html():
    return f'''<header class="top"><div class="wrap bar"><a class="brand" href="/"><img src="/assets/img/logo.webp" alt="Logo Lily Cestas" width="56" height="54"><span>Lily Cestas<small>Atelier de Presentes</small></span></a>
<nav><a href="{SHOP}#catalogo">Catálogo</a><a class="btn sm" href="https://wa.me/{WA}" target="_blank" rel="noopener">WhatsApp</a></nav></div></header>'''


def ship_pill(p):
    if p['status'] == 'esgotado':
        return ''
    return '<span class="pship">🚚 Entrega grátis</span>' if final_price(p) >= FRETE_MIN else f'<span class="pship">🚚 Grátis acima de {FRETE_TXT}</span>'


def cards_html(plist):
    out = ''
    for p in plist:
        old = f'<span style="text-decoration:line-through;color:#8C6C73;font-size:12px;display:block">{brl(p["preco"])}</span>' if p['_promo'] else ''
        action = '<span style="font-size:12px;font-weight:600;color:#6E5057">Esgotado</span>' if p['status'] == 'esgotado' else f'<a class="btn sm" href="{SHOP}#p={p["id"]}">Adicionar</a>'
        out += f'''<article class="card"><a href="{prod_url(p)}"><img src="{p["_img"]}" alt="{esc(p.get("alt") or p["nome"])}" width="760" height="567" loading="lazy">{ship_pill(p)}</a><div class="cb"><h3><a href="{prod_url(p)}">{esc(p["nome"])}</a></h3><p>{esc(p["descricao"])}</p><div class="pr"><span>{old}<b>{brl(final_price(p))}</b></span>{action}</div></div></article>'''
    return out


def page_html(path, title, desc, h1, intro, blocks, plist, faq_items, trail, extra_nodes, related_html, hero_img=None, cta='Ver presentes'):
    nodes = [BUSINESS, crumb_ld(trail), faq_ld(faq_items)] + extra_nodes
    crumbs = ' › '.join(f'<a href="{u}">{esc(n)}</a>' if i < len(trail) - 1 else f'<span>{esc(n)}</span>' for i, (n, u) in enumerate(trail))
    sec = ''.join(f'<section><h2>{esc(h)}</h2><p>{esc(t)}</p></section>' for h, t in blocks)
    img = f'<img class="hero" src="{hero_img[0]}" alt="{esc(hero_img[1])}" width="760" height="567">' if hero_img else ''
    faq_block = ''.join(f'<details><summary>{esc(q)}</summary><p>{esc(a)}</p></details>' for q, a in faq_items)
    fast_pill = f'<p class="fastnote">⚡ <b>{FAST_TXT}*</b><small>{FAST_NOTE}</small></p>' if FAST_TXT else ''
    return (head(title, desc, path) + jsonld(*nodes) + '''
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;600;700&family=Plus+Jakarta+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/assets/css/pages.css">
</head><body>''' + top_html() + f'''<main><div class="wrap"><nav class="crumbs" aria-label="Navegação">{crumbs}</nav>
<div class="lead"><div><h1>{esc(h1)}</h1><p class="intro">{esc(intro)}</p>{fast_pill}<p><a class="btn" href="{SHOP}#catalogo">{cta}</a> <a class="btn ghost" href="/catalogo/">Ver catálogo completo</a></p></div>{img}</div>
{sec}
<section><h2>Produtos</h2><div class="cards">{cards_html(plist)}</div></section>
<section><h2>Perguntas frequentes</h2><div class="faq">{faq_block}</div></section>
{related_html}
</div></main>''' + footer_html() + '</body></html>')


CITIES = [
    dict(slug='cestas-de-presente-santana-de-parnaiba', cidade='Santana de Parnaíba',
         title='Cestas de Presente em Santana de Parnaíba | Café da Manhã e Personalizados',
         desc='Cestas de presente, café da manhã, canecas personalizadas e presentes em 3D em Santana de Parnaíba, SP. Atelier local, pedido pelo site e Pix com desconto.',
         h1='Cestas de Presente e Café da Manhã em Santana de Parnaíba',
         intro='A Lily Cestas nasceu em Santana de Parnaíba. Aqui o atelier monta cestas de presente, cestas de café da manhã, boxes com chocolates, canecas com nome e peças personalizadas em 3D, tudo feito à mão e entregue com carinho.',
         blocks=[('Um atelier da cidade, perto de você', 'Somos de Santana de Parnaíba e conhecemos a região: do Centro Histórico à Fazendinha, do Suru ao Colinas da Anhanguera e aos condomínios do entorno. Informe o CEP no checkout e confirmamos a entrega para o seu endereço.'),
                 ('Presentes para quem mora aqui e para quem mora longe', 'Quer surpreender a família em Santana de Parnaíba estando em outra cidade? Escolha a cesta, informe o endereço de quem vai receber e a mensagem do cartão, e a gente cuida do resto.'),
                 ('Cesta de café da manhã, box com chocolates ou algo personalizado', 'Cestas de café da manhã para aniversário e agradecimento, boxes com chocolates e pelúcia para namorados e amigos, canecas com nome e peças em 3D, como luminária com foto e kits Polaroid. Veja tudo abaixo e adicione ao pedido em poucos cliques.'),
                 ('Como pedir', 'Escolha o presente, clique em Adicionar e finalize em 3 etapas. Nome, frase e fotos da personalização são combinados pelo WhatsApp depois do pedido. Pagando no Pix, você tem desconto automático.'),
                 ('Datas em que mais encomendam por aqui', 'Aniversário, Dia das Mães, Dia dos Namorados, Natal, nascimento de bebê, formatura e agradecimento a professores e equipes. Em datas especiais, peça com antecedência; se o prazo estiver curto, chame no WhatsApp para vermos o que dá para fazer.')],
         vizinhas=['alphaville', 'barueri', 'cajamar', 'osasco', 'carapicuiba']),
    dict(slug='cestas-de-presente-alphaville', cidade='Alphaville',
         title='Cestas de Presente em Alphaville e Barueri | Lily Cestas',
         desc='Cestas de presente, café da manhã e xícaras personalizadas para Alphaville, Tamboré e região. Escolha no site e combine a entrega pelo WhatsApp.',
         h1='Cestas de Presente e Café da Manhã para Alphaville',
         intro='Alphaville fica entre Barueri e Santana de Parnaíba, e é uma das regiões que mais recebe nossos presentes: cestas de café da manhã para casa ou escritório, presentes para o time e cestas para aniversário.',
         blocks=[('Presentes corporativos e para o escritório', 'Cestas de café da manhã e presentes personalizados com nome funcionam bem para aniversário de equipe, boas-vindas a novos colaboradores e agradecimento a clientes. Informe o endereço do escritório no checkout e combinamos o melhor horário de entrega.'),
                 ('Condomínios e residenciais', 'Para entregas em condomínios fechados, informe o nome do residencial, a quadra e o lote ou a torre e o apartamento, além de um contato para a portaria. Assim a cesta chega na hora combinada.'),
                 ('Confira o catálogo', 'Veja as cestas, os boxes e as xícaras disponíveis, escolha o que combina com a ocasião e agende a entrega. Se precisar de ajuda, fale com a gente pelo WhatsApp.')],
         vizinhas=['barueri', 'santana-de-parnaiba', 'cajamar']),
    dict(slug='cestas-de-presente-barueri', cidade='Barueri',
         title='Cestas de Presente em Barueri | Lily Cestas',
         desc='Cestas de presente, café da manhã e xícaras personalizadas para Barueri, SP. Escolha no site e agende a entrega.',
         h1='Cestas de Presente e Café da Manhã em Barueri',
         intro='Atendemos Barueri com cestas de presente, cestas de café da manhã e xícaras e canecas personalizadas. Você escolhe no site e combina a entrega pelo WhatsApp.',
         blocks=[('Entrega em Barueri', 'Para o Centro, o Jardim Silveira, o Tamboré, a Aldeia da Serra e demais bairros, informe o CEP no checkout. Confirmamos a disponibilidade e a entrega para o seu endereço antes de fechar o pedido.'),
                 ('Presente de última hora?', 'Chame no WhatsApp para combinar o prazo e a entrega, conforme a agenda do atelier. Para pedidos com personalização, combine também os detalhes.'),
                 ('Opções para todos os orçamentos', f'O catálogo tem presentes a partir de {brl(PRECO_MIN)}. O Concierge ajuda a escolher pelo valor que você quer investir.')],
         vizinhas=['alphaville', 'santana-de-parnaiba', 'cajamar']),
    dict(slug='cestas-de-presente-cajamar', cidade='Cajamar',
         title='Cestas de Presente em Cajamar | Lily Cestas',
         desc='Cestas de presente, café da manhã e xícaras personalizadas para Cajamar, SP. Peça pelo site e combine a entrega pelo WhatsApp.',
         h1='Cestas de Presente e Café da Manhã em Cajamar',
         intro='Também atendemos Cajamar. Escolha a cesta ou a xícara no site, informe o CEP no checkout e combinamos a entrega pelo WhatsApp.',
         blocks=[('Como pedir de Cajamar', 'Escolha o presente e finalize o checkout em 3 etapas. Informe o bairro e o CEP, como Polvilho, Jordanésia ou outras regiões, e confirmamos a entrega antes de seguir com o pedido. A entrega é grátis em pedidos a partir de ' + FRETE_TXT + '.'),
                 ('Atendimento pelo WhatsApp', 'Dúvidas sobre prazo, personalização ou entrega? Chame no WhatsApp. Respondemos e combinamos os detalhes do seu pedido.')],
         vizinhas=['santana-de-parnaiba', 'alphaville', 'barueri']),
    dict(slug='cestas-de-presente-osasco', cidade='Osasco',
         title='Cestas de Presente em Osasco | Café da Manhã e Personalizados',
         desc='Cestas de presente, café da manhã, canecas personalizadas e presentes em 3D para Osasco, SP. Escolha no site e confirme a entrega pelo CEP.',
         h1='Cestas de Presente e Café da Manhã em Osasco',
         intro='Atendemos Osasco com cestas de presente, cestas de café da manhã, boxes com chocolates, canecas com nome e presentes personalizados. Você escolhe no site e combina os detalhes pelo WhatsApp.',
         blocks=[('Como receber em Osasco', 'Escolha o presente, finalize o pedido e informe o CEP no checkout. Conferimos na hora se entregamos no seu endereço e combinamos o horário pelo WhatsApp.'),
                 ('Presente para quem você ama, do jeito que ela merece', 'De cestas de café da manhã a boxes românticos e canecas com nome, temos opções para aniversário, namoro, agradecimento e datas como Dia das Mães e Natal.'),
                 ('Personalização combinada pelo WhatsApp', 'Nome na caneca, frase no cartão ou foto Polaroid: depois do pedido, você envia os detalhes pelo WhatsApp e confirmamos tudo antes de produzir.')],
         vizinhas=['carapicuiba', 'barueri', 'santana-de-parnaiba']),
    dict(slug='cestas-de-presente-carapicuiba', cidade='Carapicuíba',
         title='Cestas de Presente em Carapicuíba | Café da Manhã e Personalizados',
         desc='Cestas de presente, café da manhã, canecas personalizadas e presentes em 3D para Carapicuíba, SP. Escolha no site e confirme a entrega pelo CEP.',
         h1='Cestas de Presente e Café da Manhã em Carapicuíba',
         intro='Atendemos Carapicuíba com cestas de presente, café da manhã, boxes com chocolates, canecas com nome e presentes personalizados, feitos à mão pelo atelier.',
         blocks=[('Como receber em Carapicuíba', 'Escolha o presente, finalize o pedido e informe o CEP no checkout. Conferimos na hora se entregamos no seu endereço e combinamos o horário pelo WhatsApp.'),
                 ('Opções para todos os orçamentos', f'O catálogo tem presentes a partir de {brl(PRECO_MIN)}. Use o Concierge para receber uma indicação pela pessoa e pelo valor que você quer investir.'),
                 ('Personalização combinada pelo WhatsApp', 'Nome na caneca, frase no cartão ou foto Polaroid: depois do pedido, você envia os detalhes pelo WhatsApp e confirmamos tudo antes de produzir.')],
         vizinhas=['osasco', 'barueri', 'santana-de-parnaiba']),
]
CITIES[3]['vizinhas'] = ['santana-de-parnaiba', 'alphaville', 'barueri', 'osasco']
CITY_BY = {c['slug'].replace('cestas-de-presente-', ''): c for c in CITIES}
FAQ_COMMON = faq

# ---- páginas por ocasião (busca por "cesta de aniversário", "presente dia das mães"...)
# "ids" é a lista de preferência; só entram produtos que estão visíveis no site. Se faltar, completa com os mais bem colocados.
OCCASIONS = [
    dict(slug='cesta-de-aniversario', nome='Cesta de aniversário', cat_filter=None,
         ids=['box-feliz-aniversario', 'cesta-lily-imperial-rose', 'cesta-despertar-delicado', 'box-floral', 'cesta-doce-encanto', 'caneca-personalizada-chaveiro', 'kit-porta-retratos-polaroid', 'luminaria-litofania-3d-foto'],
         title='Cesta de Aniversário e Presentes Personalizados | Lily Cestas',
         desc='Cestas de aniversário com chocolates, balões e mimos, além de presentes personalizados. Escolha no site, combine o cartão pelo WhatsApp e receba em casa.',
         h1='Cesta de Aniversário: presentes que fazem a diferença',
         intro='Aniversário pede um presente que mostre carinho de verdade. Nossas cestas e boxes saem do atelier montados à mão, com chocolates, balões, pelúcias e a mensagem que você escolher.',
         blocks=[('Como escolher a cesta de aniversário', 'Pense em quem vai receber: para quem gosta de chocolate, as boxes com bombons e Nutella; para quem ama decoração, peças personalizadas; para surpreender de manhã, a cesta de café. Se tiver dúvida, o Concierge do site indica pela pessoa e pelo valor.'),
                 ('Cartão com a sua mensagem', 'Nas cestas com cartão personalizado, a frase é combinada pelo WhatsApp antes da produção. Dá para escrever o nome, a idade ou uma lembrança só de vocês.'),
                 ('Personalizado também vale', 'Canecas com nome, porta-retratos Polaroid e luminária com foto são ótimas para quem já tem tudo. A personalização (nome, frase ou foto) é combinada pelo WhatsApp depois do pedido.')],
         faq=[('Dá para colocar o nome do aniversariante?', 'Dá. Nome, idade e frase são combinados pelo WhatsApp depois que você finaliza o pedido.'),
              ('Posso agendar para o dia do aniversário?', 'Combinamos a data e o horário pelo WhatsApp, conforme a agenda do atelier. Quanto mais cedo você pedir, melhor.')]),
    dict(slug='cesta-de-cafe-da-manha', nome='Cesta de café da manhã', cat_filter=None,
         ids=['cesta-cafe-especial', 'cesta-despertar-delicado', 'cesta-com-amor', 'cesta-lily-imperial-rose', 'box-floral', 'box-feliz-aniversario'],
         title='Cesta de Café da Manhã para Presente | Lily Cestas',
         desc='Cestas de café da manhã para aniversário, agradecimento e surpresa. Montadas à mão, com cartão personalizado. Peça pelo site e combine a entrega no WhatsApp.',
         h1='Cesta de Café da Manhã para presentear',
         intro='Acordar com uma cesta de café da manhã na porta é daqueles carinhos que ficam na memória. Montamos cada cesta no atelier, com itens selecionados e acabamento caprichado.',
         blocks=[('Para quem enviar', 'Funciona para aniversário, namorados, nascimento de bebê, boas-vindas, agradecimento e para quem simplesmente merece uma manhã especial. Também vai bem em escritórios, para celebrar a equipe.'),
                 ('O que costuma vir', 'Cada cesta tem a sua composição, que fica descrita na página do produto. Em geral combinam chocolates, petiscos, bebida, mimos e um toque de decoração.'),
                 ('Horário e combinação', 'A data e o horário da entrega são combinados pelo WhatsApp, conforme a agenda do atelier. Se for para uma surpresa, avise e alinhamos o melhor momento.')],
         faq=[('As cestas de café da manhã têm itens perecíveis?', 'A composição de cada cesta está descrita na página do produto. Se tiver restrição alimentar, avise pelo WhatsApp antes de finalizar.'),
              ('Dá para enviar para o escritório?', 'Dá. Informe o endereço, o nome de quem recebe e um contato da recepção no checkout.')]),
    dict(slug='presente-dia-das-maes', nome='Presente de Dia das Mães', cat_filter=None,
         ids=['cesta-doce-encanto', 'box-floral', 'caneca-afeto-em-flor', 'cesta-despertar-delicado', 'buque-de-flores-artificial', 'luminaria-litofania-3d-foto', 'caneca-personalizada-chaveiro', 'trio-decorativo-3d-vaso'],
         title='Presente de Dia das Mães: Cestas e Personalizados | Lily Cestas',
         desc='Cestas de presente, flores artificiais e peças personalizadas para o Dia das Mães. Escolha no site, personalize pelo WhatsApp e receba em casa.',
         h1='Presente de Dia das Mães com carinho de verdade',
         intro='Mãe merece um presente pensado com cuidado. Reunimos cestas, boxes, flores e peças personalizadas feitas à mão para dizer obrigada do jeito certo.',
         blocks=[('Ideias para presentear', 'Cestas com chocolates e bebida para celebrar, boxes delicadas com flores, canecas com nome e peças em 3D com foto da família. Escolha pelo estilo dela e pelo valor que você quer investir.'),
                 ('Peça com antecedência', 'O Dia das Mães concentra muitos pedidos. Para garantir o presente personalizado e o horário que você quer, faça o pedido com antecedência e combine os detalhes pelo WhatsApp.'),
                 ('Mensagem no cartão', 'Algumas cestas incluem cartão com a sua mensagem. Conte o que quer dizer e a gente cuida do acabamento.')],
         faq=[('Posso mandar o presente para a casa da minha mãe?', 'Pode. Informe o endereço dela, o nome de quem vai receber e o recado do cartão no checkout.'),
              ('Dá para personalizar com foto?', 'Dá. Luminária com foto e porta-retratos Polaroid usam fotos enviadas pelo WhatsApp depois do pedido.')]),
    dict(slug='presente-dia-dos-namorados', nome='Presente de Dia dos Namorados', cat_filter=None,
         ids=['box-luxo-lily-romantica', 'com-todo-meu-amor', 'caneca-afeto-em-flor', 'kit-memorias-polaroid-iluminado', 'quadro-shadow-box-3d', 'luminaria-litofania-3d-foto', 'kit-letras-palavras-esculturais', 'buque-de-flores-artificial', 'kit-porta-retratos-polaroid'],
         title='Presente de Dia dos Namorados: Cestas Românticas | Lily Cestas',
         desc='Cestas românticas, boxes com chocolates e presentes personalizados com foto para o Dia dos Namorados. Peça pelo site e combine os detalhes no WhatsApp.',
         h1='Presentes para o Dia dos Namorados',
         intro='Um presente romântico fica melhor quando conta a história de vocês. Temos boxes com chocolates e pelúcia, flores, porta-retratos e peças personalizadas com as fotos do casal.',
         blocks=[('Cestas e boxes românticas', 'Boxes com chocolates, balões, flores e frases carinhosas são pedidas clássicas para surpreender. A composição de cada uma está na página do produto.'),
                 ('Presentes com a foto de vocês', 'Porta-retratos Polaroid, luminária com foto e quadro com fotos transformam uma lembrança em decoração. As fotos são enviadas pelo WhatsApp depois do pedido.'),
                 ('Combine a surpresa', 'Quer que chegue em um horário específico ou com um recado secreto? Avise pelo WhatsApp e alinhamos tudo com você.')],
         faq=[('Dá para escolher a mensagem do cartão?', 'Dá. A frase é combinada pelo WhatsApp antes de seguirmos com a produção.'),
              ('Quanto antes devo pedir?', 'Quanto antes, melhor, principalmente para presentes personalizados. Em datas especiais a agenda lota rápido.')]),
    dict(slug='cesta-de-natal', nome='Cesta de Natal', cat_filter=None,
         ids=['cesta-natal-magico', 'combo-natal-encantado', 'cesta-doce-encanto', 'trio-decorativo-3d-vaso', 'box-floral'],
         title='Cesta de Natal e Presentes Natalinos | Lily Cestas',
         desc='Cestas de Natal e presentes natalinos personalizados: letreiro, árvore 3D e quadro com foto. Escolha no site e combine a entrega pelo WhatsApp.',
         h1='Cestas de Natal e presentes natalinos',
         intro='Para presentear família, amigos e equipe no fim do ano, o atelier prepara cestas de Natal e peças decorativas personalizadas, com acabamento capricho e entrega combinada.',
         blocks=[('Para a família e para a equipe', 'Cestas de Natal são uma boa escolha para amigo secreto, agradecimento a clientes e presente de equipe. Se for um pedido com várias unidades, chame no WhatsApp para combinar.'),
                 ('Decoração personalizada', 'O combo com letreiro, árvore em 3D e quadro com a sua foto enfeita a casa e serve de lembrança. A foto do quadro é enviada pelo WhatsApp.'),
                 ('Pedidos de fim de ano', 'Dezembro enche a agenda do atelier. Faça o pedido com antecedência para garantir o produto e o horário.')],
         faq=[('Vocês fazem pedidos em quantidade para empresas?', 'Fazemos. Chame no WhatsApp com a quantidade e a data desejada para combinarmos valores e prazo.'),
              ('As peças de Natal ficam disponíveis o ano todo?', 'São produtos sazonais. Quando saem de linha, aparecem como esgotados ou deixam de ser exibidos no catálogo.')]),
]
OCC_MIN = 3


def occ_products(o):
    byid = {p['id']: p for p in visible}
    chosen = [byid[i] for i in o['ids'] if i in byid]
    if len(chosen) < OCC_MIN:
        chosen += [p for p in (active or visible) if p not in chosen][:OCC_MIN - len(chosen)]
    return chosen


for o in OCCASIONS:
    o['_prods'] = occ_products(o)
OCCASIONS_OK = [o for o in OCCASIONS if len(o['_prods']) >= OCC_MIN]

page_urls = []
CANECAS = load_json(ROOT / 'data/canecas.json', {}) or {}
for c in cats_with:
    if not c.get('pagina_url'):
        continue
    if CANECAS.get('ativa', True) and c['pagina_url'] == 'canecas':
        continue  # a página /canecas/ é montada mais abaixo, a partir de data/canecas.json
    path = f'/{c["pagina_url"]}/'
    ps = cat_prods[c['chave']]
    prices = [final_price(p) for p in ps]
    items = [
        (f'Quanto custa {c["nome"].lower()} na Lily Cestas?', f'Os preços do catálogo vão de {brl(min(prices))} a {brl(max(prices))} nesta categoria. O valor final pode variar conforme os detalhes combinados pelo WhatsApp.'),
        ('Vocês entregam na minha região?', 'Atendemos Santana de Parnaíba, Alphaville, Barueri, Cajamar, Osasco e Carapicuíba. Informe o CEP no checkout e conferimos na hora. ' + ENTREGA_TXT),
        ('Posso combinar os detalhes antes da produção?', 'Sim. Nome, frase e demais detalhes são combinados pelo WhatsApp antes de seguirmos com o pedido.'),
    ] + FAQ_COMMON[-1:]
    rel = '<section class="rel"><h2>Outras linhas e cidades atendidas</h2><p>' + ''.join(
        f'<a href="/{o["pagina_url"]}/">{esc(o["nome"])}</a>' for o in cats_with if o is not c and o.get('pagina_url')) + '</p><p>' + ''.join(
        f'<a href="/{x["slug"]}/">{x["cidade"]}</a>' for x in CITIES) + '</p></section>'
    extra = [{'@type': 'CollectionPage', 'name': c['pagina_h1'], 'url': BASE + path, 'about': c['nome'], 'mainEntity': {'@type': 'ItemList', 'itemListElement': [{'@type': 'ListItem', 'position': i + 1, 'item': prod_ld(p)} for i, p in enumerate(ps)]}}]
    secoes = [(s.get('titulo', ''), s.get('texto', '')) for s in (c.get('pagina_secoes') or []) if s.get('titulo')]
    write_page(path, page_html(path, c.get('pagina_titulo') or c['nome'], c.get('pagina_descricao') or '', c.get('pagina_h1') or c['nome'], c.get('pagina_intro') or '', secoes, ps, items,
                               [('Início', '/'), (c['nome'], path)], extra, rel, (ps[0]['_img'], ps[0].get('alt') or ps[0]['nome'])))
    page_urls.append(path)

# ---- catálogo completo: todos os produtos organizados por categoria
cat_path = '/catalogo/'
chips = ''.join(f'<a href="#cat-{c["chave"]}">{esc(c["nome_curto"])} ({len(cat_prods[c["chave"]])})</a>' for c in cats_with)
sections = ''.join(
    f'<section id="cat-{c["chave"]}"><h2>{esc(c["nome"])}</h2><p class="sub">{esc(c.get("frase_apoio") or "")}</p>'
    f'<div class="cards">{cards_html(cat_prods[c["chave"]])}</div>'
    + (f'<p class="more"><a href="/{c["pagina_url"]}/">Ver página de {esc(c["nome"].lower())} →</a></p>' if c.get('pagina_url') else '') + '</section>'
    for c in cats_with)
def addon_cards():
    out = ''
    for a in addons:
        old = f'<span style="text-decoration:line-through;color:#8C6C73;font-size:12px;display:block">{brl(a["preco"])}</span>' if a['_promo'] else ''
        out += f'''<article class="card"><img src="{a["_img"]}" alt="{esc(a["nome"])}" width="760" height="760" loading="lazy"><div class="cb"><span class="tag">Adicional</span><h3>{esc(a["nome"])}</h3><p>{esc(a["descricao"])}</p><div class="pr"><span>{old}<b>{brl(a["_promo"] or a["preco"])}</b></span><a class="btn sm" href="{SHOP}#a={a["id"]}">Adicionar</a></div></div></article>'''
    return out


addon_section = (f'<section id="adicionais"><h2>Adicionais</h2><p class="sub">Capriche no presente: cartão com a sua mensagem e Polaroid com a sua foto.</p><div class="cards">{addon_cards()}</div></section>') if addons else ''
if addons:
    chips += f'<a href="#adicionais">Adicionais ({len(addons)})</a>'
cat_items = [(f'Como compro no catálogo da Lily Cestas?', 'Escolha o presente e clique em Adicionar. Você finaliza o pedido na loja e combina nome e detalhes pelo WhatsApp.')] + FAQ_COMMON[-2:]
cat_ld = [{'@type': 'CollectionPage', 'name': 'Catálogo completo Lily Cestas', 'url': BASE + cat_path,
           'mainEntity': {'@type': 'ItemList', 'itemListElement': [{'@type': 'ListItem', 'position': i + 1, 'item': prod_ld(p)} for i, p in enumerate(visible)]}}]
rel_cat = '<section class="rel"><h2>Cidades atendidas</h2><p>' + ''.join(f'<a href="/{x["slug"]}/">{x["cidade"]}</a>' for x in CITIES) + '</p></section>'
faq_cat = ''.join(f'<details><summary>{esc(q)}</summary><p>{esc(a)}</p></details>' for q, a in cat_items)
write_page(cat_path, head('Catálogo de Cestas e Presentes Personalizados | Lily Cestas', 'Veja todas as cestas de presente, cestas de café da manhã, xícaras e presentes personalizados da Lily Cestas. Entregas em Santana de Parnaíba, Alphaville, Barueri, Cajamar, Osasco e Carapicuíba.', cat_path)
           + jsonld(BUSINESS, crumb_ld([('Início', '/'), ('Catálogo', cat_path)]), faq_ld(cat_items), *cat_ld) + '''
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;600;700&family=Plus+Jakarta+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/assets/css/pages.css">
</head><body>''' + top_html() + f'''<main><div class="wrap"><nav class="crumbs" aria-label="Navegação"><a href="/">Início</a> › <span>Catálogo</span></nav>
<div class="cathead"><h1>Catálogo completo</h1><p class="intro">Todas as cestas de presente, xícaras e presentes personalizados da Lily Cestas, organizados por categoria.</p><nav class="chips" aria-label="Categorias">{chips}</nav></div>
{sections}
{addon_section}
<section><h2>Perguntas frequentes</h2><div class="faq">{faq_cat}</div></section>
{rel_cat}
</div></main>''' + footer_html() + '</body></html>')
page_urls.append(cat_path)

REDIRECTS = {'/polaroid-quadro-qr-code-musical/': '/polaroid-quadro-shadow-box/'}
for old_path, new_path in REDIRECTS.items():
    if any(f'/{c["pagina_url"]}/' == new_path for c in cats_with):
        write_page(old_path, f'''<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8"><title>Página movida | Lily Cestas</title>
<link rel="canonical" href="{BASE}{new_path}"><meta name="robots" content="noindex"><meta http-equiv="refresh" content="0; url={new_path}">
</head><body><p>Esta página mudou. <a href="{new_path}">Clique aqui para continuar</a>.</p></body></html>''')

featured = ([p for p in active if p.get('destaque')] + [p for p in active if not p.get('destaque')])[:4]
for c in CITIES:
    path = f'/{c["slug"]}/'
    cid = c['cidade']
    items = [
        (f'A Lily Cestas entrega em {cid}?', f'Sim, atendemos {cid}. Informe o CEP no checkout e veja na hora se entregamos no seu endereço.'),
        (f'Qual o prazo para receber uma cesta de presente em {cid}?', 'Combinamos a data e o horário pelo WhatsApp, conforme a agenda do atelier. Para pedidos com personalização, combine também o prazo.'),
        ('Posso personalizar o pedido?', 'Pode. Depois de escolher o presente, combine nome e detalhes pelo WhatsApp.'),
    ] + FAQ_COMMON[-2:]
    viz = ''.join(f'<a href="/{CITY_BY[v]["slug"]}/">{CITY_BY[v]["cidade"]}</a>' for v in c['vizinhas'])
    rel = '<section class="rel"><h2>Também atendemos</h2><p>' + viz + '</p><p>' + ''.join(f'<a href="/{o["pagina_url"]}/">{esc(o["nome"])}</a>' for o in cats_with if o.get('pagina_url')) + '</p></section>'
    extra = [{'@type': 'WebPage', 'name': c['h1'], 'url': BASE + path, 'about': {'@id': BASE + '/#negocio'}, 'spatialCoverage': {'@type': 'City', 'name': cid}}]
    write_page(path, page_html(path, c['title'], c['desc'], c['h1'], c['intro'], c['blocks'], featured, items, [('Início', '/'), (f'Presentes em {cid}', path)], extra, rel,
                               (featured[0]['_img'], featured[0].get('alt') or featured[0]['nome']) if featured else None))
    page_urls.append(path)


# ---- páginas de ocasião
for o in OCCASIONS_OK:
    path = f'/{o["slug"]}/'
    ps = o['_prods']
    prices = [final_price(p) for p in ps]
    items = [(f'Quanto custa {o["nome"].lower()} na Lily Cestas?', f'Os presentes desta página custam de {brl(min(prices))} a {brl(max(prices))}.'),
             ('Vocês entregam na minha região?', 'Atendemos Santana de Parnaíba, Alphaville, Barueri, Cajamar, Osasco e Carapicuíba. Informe o CEP no checkout e conferimos na hora. ' + ENTREGA_TXT)] + o['faq'] + FAQ_COMMON[-1:]
    rel = '<section class="rel"><h2>Mais ideias de presente</h2><p>' + ''.join(
        f'<a href="/{x["slug"]}/">{esc(x["nome"])}</a>' for x in OCCASIONS_OK if x is not o) + '</p><p>' + ''.join(
        f'<a href="/{c["pagina_url"]}/">{esc(c["nome"])}</a>' for c in cats_with if c.get('pagina_url')) + '</p></section>'
    extra = [{'@type': 'CollectionPage', 'name': o['h1'], 'url': BASE + path, 'mainEntity': {'@type': 'ItemList', 'itemListElement': [{'@type': 'ListItem', 'position': i + 1, 'item': prod_ld(p)} for i, p in enumerate(ps)]}}]
    write_page(path, page_html(path, o['title'], o['desc'], o['h1'], o['intro'], o['blocks'], ps, items, [('Início', '/'), (o['nome'], path)], extra, rel,
                               (ps[0]['_img'], ps[0].get('alt') or ps[0]['nome'])))
    page_urls.append(path)

# ---- página de cada produto
def product_page(p):
    path = prod_url(p)
    c = p['_cat']
    title = f'{p["nome"]} | {c["nome_curto"]} | Lily Cestas'
    desc = (prod_desc(p) + f' {brl(final_price(p))}. Peça pelo site e combine os detalhes pelo WhatsApp.')[:300]
    wa_text = f'Oi! Vim pelo site da Lily Cestas e quero o produto: {p["nome"]} ({brl(final_price(p))}).'
    old = f'<span class="old">{brl(p["preco"])}</span> ' if p['_promo'] else ''
    sold = p['status'] == 'esgotado'
    buy = ('<p><strong>Esgotado no momento.</strong> Chame no WhatsApp para saber quando volta ou escolher algo parecido.</p>'
           f'<p><a class="btn" href="https://wa.me/{WA}?text={esc(urllib.parse.quote(wa_text))}" target="_blank" rel="noopener">Perguntar no WhatsApp</a></p>') if sold else (
           f'<p class="buy"><a class="btn" data-ga="add_to_cart_click" data-ga-item="{p["id"]}" href="{SHOP}#p={p["id"]}">Adicionar ao pedido</a> '
           f'<a class="btn ghost" href="https://wa.me/{WA}?text={esc(urllib.parse.quote(wa_text))}" target="_blank" rel="noopener">Pedir pelo WhatsApp</a></p>')
    inc = ('<section><h2>O que vem</h2><ul class="inc">' + ''.join(f'<li>{esc(x)}</li>' for x in p['inclui']) + '</ul></section>') if p['inclui'] else ''
    pers = f'<section><h2>Personalização</h2><p>{esc(p["personalizacao"])}. Depois de finalizar o pedido, você combina tudo pelo WhatsApp antes da produção.</p></section>' if p['personalizacao'] else ''
    entrega = (f'<section><h2>Entrega e pagamento</h2><p>Entregamos em {", ".join(config.get("cidades_entrega") or [])}. Informe o CEP no checkout para conferir a entrega. {ENTREGA_TXT}'
               f' Pagando no Pix, você tem {int(config["pix_desconto"])}% de desconto nos produtos.</p></section>')
    items = [(f'Quanto custa {p["nome"]}?', f'{p["nome"]} custa {brl(final_price(p))}. ' + ('A entrega é grátis.' if final_price(p) >= FRETE_MIN else f'A entrega é grátis em pedidos a partir de {FRETE_TXT}.') + f' Pedido mínimo de {MIN_TXT}.'),
             ('Dá para personalizar?', 'Dá. Nome, frase ou foto são combinados pelo WhatsApp depois que você finaliza o pedido.'),
             ('Vocês entregam na minha região?', 'Atendemos Santana de Parnaíba, Alphaville, Barueri, Cajamar, Osasco e Carapicuíba. Informe o CEP no checkout e conferimos na hora.')]
    faq_block = ''.join(f'<details><summary>{esc(q)}</summary><p>{esc(a)}</p></details>' for q, a in items)
    others = [x for x in visible if x is not p and x['_cat'] is c][:4]
    if len(others) < 4:
        others += [x for x in (active or visible) if x is not p and x not in others][:4 - len(others)]
    trail = [('Início', '/')] + ([(c['nome'], f'/{c["pagina_url"]}/')] if c.get('pagina_url') and c in cats_with else []) + [(p['nome'], path)]
    crumbs = ' › '.join(f'<a href="{u}">{esc(n)}</a>' if i < len(trail) - 1 else f'<span>{esc(n)}</span>' for i, (n, u) in enumerate(trail))
    badge = f'<span class="tag">{esc(p["selo"])}</span>' if p['selo'] else ''
    fast_line = f'<p class="fastnote">⚡ <b>{FAST_TXT}*</b><small>{FAST_NOTE}</small></p>' if FAST_TXT and not p['personalizacao'] else ''
    return (head(title, desc, path).replace('<meta property="og:type" content="website">', '<meta property="og:type" content="product">') + jsonld(BUSINESS, crumb_ld(trail), faq_ld(items), prod_ld(p)) + '''
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;600;700&family=Plus+Jakarta+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/assets/css/pages.css">
</head><body>''' + top_html() + f'''<main><div class="wrap"><nav class="crumbs" aria-label="Navegação">{crumbs}</nav>
<div class="lead"><div>{badge}<h1>{esc(p["nome"])}</h1><p class="intro">{esc(prod_desc(p))}</p><p class="price">{old}<b>{brl(final_price(p))}</b></p>{fast_line}<p class="shipnote">{"🚚 Entrega grátis neste produto" if final_price(p) >= FRETE_MIN else f"🚚 Entrega grátis em pedidos a partir de {FRETE_TXT}"} · Pedido mínimo {MIN_TXT}</p>{buy}</div>
<img class="hero" src="{p["_img"]}" alt="{esc(p.get("alt") or p["nome"])}" width="760" height="567" fetchpriority="high"></div>
{inc}{pers}{entrega}
<section><h2>Perguntas frequentes</h2><div class="faq">{faq_block}</div></section>
<section><h2>Você também pode gostar</h2><div class="cards">{cards_html(others)}</div></section>
</div></main>''' + footer_html() + '</body></html>')


for p in visible:
    write_page(prod_url(p), product_page(p))
    page_urls.append(prod_url(p))

# ---- feed gratuito do Google Shopping (Merchant Center)
def xml(t):
    return html.escape(str(t), quote=False)


feed_items = ''
for p in visible:
    price = f'{p["preco"]:.2f} BRL'
    sale = f'<g:sale_price>{final_price(p):.2f} BRL</g:sale_price>' if p['_promo'] else ''
    feed_items += (f'<item><g:id>{xml(p["id"])}</g:id><g:title>{xml(p["nome"])}</g:title><g:description>{xml(prod_desc(p))}</g:description>'
                   f'<g:link>{BASE}{prod_url(p)}</g:link><g:image_link>{BASE}{p["_img"]}</g:image_link>'
                   f'<g:availability>{"out_of_stock" if p["status"] == "esgotado" else "in_stock"}</g:availability>'
                   f'<g:price>{price}</g:price>{sale}<g:condition>new</g:condition><g:brand>Lily Cestas</g:brand>'
                   f'<g:identifier_exists>no</g:identifier_exists><g:product_type>{xml(p["_cat"]["nome"])}</g:product_type></item>\n')
(OUT / 'feed-google.xml').write_text('<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0" xmlns:g="http://base.google.com/ns/1.0"><channel>'
                                     f'<title>Lily Cestas</title><link>{BASE}/</link><description>Cestas de presente e presentes personalizados</description>\n{feed_items}</channel></rss>\n', encoding='utf-8')

# ---------------------------------------------------------------- banners da home
def resize_to(path, maxw):
    """Reduz uma imagem de banner (largura max maxw, WebP) e devolve a URL publica."""
    rel = (path or '').lstrip('/')
    src = ROOT / rel
    if not rel or not src.is_file():
        return ''
    data = src.read_bytes()
    h = hashlib.sha1(data).hexdigest()[:8]
    dest = OUT / 'assets/p' / f'bn-{slugify(src.stem)[:30]}-{maxw}-{h}.webp'
    try:
        im = ImageOps.exif_transpose(Image.open(src))
        if im.width > maxw:
            im = im.resize((maxw, round(im.height * maxw / im.width)), Image.LANCZOS)
        im.convert('RGB').save(dest, 'WEBP', quality=84, method=6)
        return '/assets/p/' + dest.name
    except Exception as e:
        print(f'Aviso: não foi possível usar o banner {rel} ({e}).')
        return ''


def fill_vars(t):
    return (str(t or '').replace('{frete}', FRETE_TXT).replace('{minimo}', MIN_TXT)
            .replace('{brinde}', brl(config['brinde1_valor']).replace(',00', '')).replace('{pix}', str(int(config['pix_desconto']))))


banners = []
for f in sorted((ROOT / 'data/banners').glob('*.json')):
    b = load_json(f, {})
    if not b or b.get('ativo') is False:
        continue
    b['_ordem'] = to_number(b.get('ordem'), f'Banner {f.name} › ordem', False) or 999
    banners.append(b)
banners.sort(key=lambda b: (b['_ordem'], str(b.get('nome'))))


def banner_html(b):
    web = resize_to(b.get('imagem_web'), 1600)
    mob = resize_to(b.get('imagem_mobile'), 900)
    link = (b.get('link') or '').strip()
    ext = link.startswith('http')
    attrs = f' href="{esc(link)}"' + (' target="_blank" rel="noopener"' if ext else '') + f' data-ga="banner_click" data-ga-item="{esc(slugify(b.get("nome") or b.get("titulo") or ""))}"' if link else ''
    tag = 'a' if link else 'div'
    if web or mob:
        alt = esc(b.get('alt') or fill_vars(b.get('titulo')) or b.get('nome') or 'Banner Lily Cestas')
        src_web = web or mob
        picture = (f'<picture>{f"<source media=(max-width:767px) srcset={mob}>" if mob else ""}'
                   f'<img src="{src_web}" alt="{alt}" width="1600" height="320" loading="lazy" decoding="async"></picture>')
        return f'<{tag} class="bn-slide bn-img"{attrs}>{picture}</{tag}>'
    cor = b.get('cor') if b.get('cor') in ('rose', 'vinho', 'creme') else 'rose'
    icone = f'<span class="bn-ic">{esc(b["icone"])}</span>' if b.get('icone') else ''
    sub = f'<small>{esc(fill_vars(b.get("subtitulo")))}</small>' if b.get('subtitulo') else ''
    btn = f'<em class="bn-btn">{esc(b["botao"])} →</em>' if b.get('botao') and link else ''
    return (f'<{tag} class="bn-slide bn-txt bn-{cor}"{attrs}>{icone}<span class="bn-t"><b>{esc(fill_vars(b.get("titulo") or b.get("nome")))}</b>{sub}</span>{btn}</{tag}>')


BANNERS_HTML = ''
if banners:
    slides = ''.join(banner_html(b) for b in banners)
    dots = ''.join(f'<button type="button" class="bn-dot" aria-label="Banner {i + 1}"></button>' for i in range(len(banners))) if len(banners) > 1 else ''
    BANNERS_HTML = (f'<div class="nh-banners" aria-label="Destaques"><div class="bn-track">{slides}</div>' + (f'<div class="bn-dots">{dots}</div>' if dots else '') + '</div>'
                    + ('<script>(function(){var w=document.querySelector(".nh-banners");if(!w)return;var t=w.querySelector(".bn-track"),d=[].slice.call(w.querySelectorAll(".bn-dot")),n=t.children.length,i=0,timer;'
                       'function go(k){i=(k+n)%n;t.scrollTo({left:t.children[i].offsetLeft-t.offsetLeft,behavior:"smooth"});}'
                       'function mark(){var k=Math.round(t.scrollLeft/t.clientWidth);i=Math.max(0,Math.min(n-1,k));d.forEach(function(e,j){e.classList.toggle("on",j===i)});}'
                       'if(n>1){t.addEventListener("scroll",mark,{passive:true});d.forEach(function(e,j){e.addEventListener("click",function(){stop();go(j)})});'
                       'function start(){timer=setInterval(function(){go(i+1)},5500)}function stop(){clearInterval(timer)}'
                       'w.addEventListener("touchstart",stop,{passive:true});w.addEventListener("mouseenter",stop);w.addEventListener("mouseleave",start);start();}mark();})();</script>' if len(banners) > 1 else ''))

# ---------------------------------------------------------------- catálogos de canecas (/canecas/<tema>/)
CATALOGOS = []
for _f in sorted((ROOT / 'data/catalogos').glob('*.json')):
    _c = load_json(_f, {}) or {}
    if not _c or _c.get('ativo') is False or not _c.get('paginas'):
        continue
    _c['slug'] = slugify(_f.stem)
    _c['_ordem'] = to_number(_c.get('ordem'), f'Catálogo {_f.name} › ordem', False) or 999
    _c['_preco'] = to_number(_c.get('preco'), f'Catálogo {_f.name} › preço', False) or 0
    _c['_de'] = to_number(_c.get('preco_de'), f'Catálogo {_f.name} › preço antigo', False) or 0
    if _c['_de'] and _c['_de'] <= _c['_preco']:
        _c['_de'] = 0
    _c['_off'] = round((1 - _c['_preco'] / _c['_de']) * 100) if _c['_de'] and _c['_preco'] else 0
    _c['_url'] = f'/canecas/{_c["slug"]}/'
    _c['_pages'] = [u for u in (resize_to(x, 1400) for x in _c['paginas']) if u]
    _c['_capa'] = resize_to(_c.get('capa') or _c['paginas'][0], 700)
    if not _c['_pages']:
        continue
    CATALOGOS.append(_c)
CATALOGOS.sort(key=lambda c: (c['_ordem'], c.get('nome', '')))


def cat_price_html(c, cls='cp'):
    if not c['_preco']:
        return f'<span class="{cls}"><b>Consulte o valor</b></span>'
    old = f'<s>{brl(c["_de"])}</s> ' if c['_de'] else ''
    off = f'<i class="cp-off">-{c["_off"]}%</i>' if c['_off'] else ''
    return f'<span class="{cls}">{old}<b>{brl(c["_preco"])}</b>{off}</span>'


def catalogo_cards():
    out = ''
    for c in CATALOGOS:
        n = len(c.get('modelos') or [])
        badge = f'<span class="ct-badge">-{c["_off"]}%</span>' if c['_off'] else ''
        capa = c['_capa'] or c['_pages'][0]
        out += (f'<a class="ctcard" href="{c["_url"]}" data-ga="catalogo_click" data-ga-item="{c["slug"]}">'
                f'<span class="ct-img"><img src="{esc(capa)}" alt="Catálogo de canecas personalizadas: {esc(c["nome"])}" width="700" height="700" loading="lazy">{badge}</span>'
                f'<span class="ct-body"><h3>{esc(c["nome"])}</h3><span class="ct-n">{n} modelos prontos para personalizar</span>'
                f'{cat_price_html(c)}<em class="ct-btn">Ver catálogo →</em></span></a>')
    return out


def catalogo_page(c):
    path = c['_url']
    nome = c['nome']
    v = fill_vars
    h1 = f'Canecas Personalizadas: {nome}'
    desc = v(c.get('descricao') or '')[:300]
    robots = 'noindex, nofollow' if CANECAS.get('noindex', True) else 'index, follow, max-image-preview:large'
    trail = [('Início', '/'), ('Canecas personalizadas', '/canecas/'), (nome, path)]
    crumbs = ' › '.join(f'<a href="{u}">{esc(nm)}</a>' if i < len(trail) - 1 else f'<span>{esc(nm)}</span>' for i, (nm, u) in enumerate(trail))
    pages = c['_pages']
    imgs = ''.join(f'<img class="cv-pg" src="{esc(u)}" alt="{esc(nome)}: página {i + 1} do catálogo" width="1400" height="989" {"fetchpriority=high" if i == 0 else "loading=lazy"} decoding="async">'
                   for i, u in enumerate(pages))
    modelos = c.get('modelos') or []
    opts = '<option value="">Escolha o modelo…</option>' + ''.join(
        f'<option value="{esc(m["numero"])}|{esc(m["nome"])}">{esc(m["numero"])} · {esc(m["nome"])}</option>' for m in modelos) + '<option value="x|Outro modelo (conto pelo WhatsApp)">Outro modelo (conto pelo WhatsApp)</option>'
    prazo = esc(v(c.get('prazo') or 'Prazo de produção combinado no pedido'))
    can_buy = bool(c['_preco'])
    wa_base = f'Oi! Vim pelo site da Lily Cestas e quero uma caneca personalizada do catálogo {nome}.'
    buy_btn = (f'<button type="button" class="btn cv-buy" id="cv-buy">Comprar agora</button>' if can_buy else '')
    cfg = json.dumps({'tema': nome, 'slug': c['slug'], 'preco': c['_preco'], 'shop': SHOP, 'wa': WA, 'wabase': wa_base}, ensure_ascii=False).replace('</', '<\\/')
    js = '''<script>(function(){var C=%s,sel=document.getElementById("cv-model"),msg=document.getElementById("cv-msg"),b=document.getElementById("cv-buy"),w=document.getElementById("cv-wa");
function pick(){var v=sel.value;if(!v){msg.textContent="Escolha o número do modelo primeiro 😉";msg.hidden=false;sel.focus();return null}msg.hidden=true;var p=v.split("|");return{n:p[0],t:p[1]}}
function ev(n,m){try{window.gtag&&gtag("event",n,{item_name:C.tema,model:m})}catch(e){}}
if(b)b.addEventListener("click",function(){var m=pick();if(!m)return;var nm=m.n==="x"?"Caneca personalizada · "+C.tema+" (modelo a combinar)":"Caneca personalizada · "+C.tema+" · Modelo "+m.n+" "+m.t;
var cart=[];try{cart=JSON.parse(localStorage.getItem("lily_cart_v2")||"[]")}catch(e){}
cart.push({id:"catalogo-"+C.slug+"-"+m.n+"-"+Date.now(),name:nm,price:C.preco,qty:1,details:"Personalização (nome, foto ou frase) combinada no WhatsApp"});
try{localStorage.setItem("lily_cart_v2",JSON.stringify(cart))}catch(e){}ev("catalogo_comprar_agora",m.n);location.href=C.shop+"#sacola"});
if(w)w.addEventListener("click",function(e){var m=pick();if(!m){e.preventDefault();return}var t=C.wabase+(m.n==="x"?" Quero combinar um modelo.":" Quero o modelo "+m.n+" ("+m.t+").");w.href="https://wa.me/"+C.wa+"?text="+encodeURIComponent(t);ev("catalogo_whatsapp",m.n)});
var tr=document.getElementById("cv-track"),ct=document.getElementById("cv-count"),n=tr.children.length;
function cur(){return Math.max(0,Math.min(n-1,Math.round(tr.scrollLeft/tr.clientWidth)))}
function upd(){ct.textContent=(cur()+1)+" / "+n}tr.addEventListener("scroll",upd,{passive:true});
document.getElementById("cv-prev").addEventListener("click",function(){tr.scrollTo({left:(cur()-1)*tr.clientWidth,behavior:"smooth"})});
document.getElementById("cv-next").addEventListener("click",function(){tr.scrollTo({left:(cur()+1)*tr.clientWidth,behavior:"smooth"})});
document.addEventListener("keydown",function(e){if(e.target.closest&&e.target.closest("select,input,textarea"))return;if(e.key==="ArrowRight")document.getElementById("cv-next").click();if(e.key==="ArrowLeft")document.getElementById("cv-prev").click()});upd()})();</script>''' % cfg
    fonts = ('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
             '<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;600;700&family=Plus+Jakarta+Sans:wght@400;500;600&display=swap" rel="stylesheet">'
             '<link rel="stylesheet" href="/assets/css/pages.css"><link rel="stylesheet" href="/assets/css/canecas.css">\n</head><body class="cat-page">')
    faq = [('Como escolho o modelo?', 'Folheie o catálogo, anote o número do modelo que você gostou e escolha-o na lista ao lado. Para outro tema ou uma arte diferente, é só combinar pelo WhatsApp.'),
           ('Posso colocar foto, nome e frase?', 'Pode. Depois de finalizar o pedido, você envia nome, frase, foto ou as cores que preferir pelo WhatsApp e confirmamos tudo antes de produzir.'),
           ('Qual é o prazo?', c.get('prazo') or 'O prazo de produção é combinado no pedido, conforme a agenda do atelier.'),
           ('Vocês entregam na minha região?', v('Atendemos Santana de Parnaíba, Alphaville, Barueri, Cajamar, Osasco e Carapicuíba. Entrega grátis a partir de {frete}; locais mais distantes podem ter taxa.'))]
    faq_block = ''.join(f'<details><summary>{esc(q)}</summary><p>{esc(a)}</p></details>' for q, a in faq)
    body = f'''<main><div class="wrap"><nav class="crumbs" aria-label="Navegação">{crumbs}</nav>
<div class="cv"><div class="cv-view"><div class="cv-track" id="cv-track" aria-label="Páginas do catálogo">{imgs}</div>
<button type="button" class="cv-nav cv-prev" id="cv-prev" aria-label="Página anterior">‹</button><button type="button" class="cv-nav cv-next" id="cv-next" aria-label="Próxima página">›</button><span class="cv-count" id="cv-count">1 / {len(pages)}</span></div>
<aside class="cv-buybox"><span class="tag">☕ Catálogo</span><h1>{esc(h1)}</h1><p class="cv-sub">{esc(v(c.get("descricao") or ""))}</p>
{cat_price_html(c, "cp cp-lg")}<p class="cv-prazo">⏱ {prazo}</p>
<label class="cv-lbl" for="cv-model">Qual modelo você quer?</label><select id="cv-model" class="cv-sel">{opts}</select><p class="cv-msg" id="cv-msg" hidden></p>
{buy_btn}<a class="btn ghost cv-wa" id="cv-wa" href="#" target="_blank" rel="noopener">Pedir pelo WhatsApp</a>
<p class="nota">Nome, foto ou frase são combinados pelo WhatsApp depois do pedido. *Entrega grátis a partir de {FRETE_TXT}; locais mais distantes podem ter taxa.</p></aside></div>
<section><h2>Perguntas frequentes</h2><div class="faq">{faq_block}</div></section>
<p class="more"><a href="/canecas/#catalogos">← Ver outros catálogos de canecas</a></p>
</div></main>'''
    bar = (f'<div class="cv-bar">{cat_price_html(c, "cp")}<a class="btn" href="#cv-model" id="cv-bar-btn">Escolher modelo</a></div>')
    write_page(path, head(f'Canecas Personalizadas {nome} | Catálogo | Lily Cestas', desc, path, robots)
               + jsonld(BUSINESS, crumb_ld(trail), faq_ld(faq), {'@type': 'CollectionPage', 'name': h1, 'url': BASE + path}) + fonts + top_html() + body + bar + js
               + footer_html() + '</body></html>')
    if CANECAS.get('noindex', True) is False:
        page_urls.append(path)


# ---------------------------------------------------------------- página dedicada de canecas (/canecas/)
def canecas_page():
    C = CANECAS
    path = '/canecas/'
    ids = [str(i).strip() for i in (C.get('produtos') or [])]
    byid = {p['id']: p for p in visible}
    byid.update({slugify(p['nome']): p for p in visible})  # o painel guarda o nome; o arquivo usa o código
    ids = [slugify(i) if i not in byid else i for i in ids]
    plist = [p for p in visible if p['_cat']['chave'] == 'canecas']
    plist += [byid[i] for i in ids if i in byid and byid[i] not in plist]
    plist.sort(key=lambda p: (p['ordem'], p['nome']))
    v = fill_vars

    def wa(t):
        return f'https://wa.me/{WA}?text={urllib.parse.quote(t)}'

    h1 = v(C.get('h1') or 'Canecas Personalizadas')
    title = C.get('titulo_seo') or f'{h1} | Lily Cestas'
    desc = v(C.get('descricao_seo') or '')
    # banners próprios da página
    slides = ''
    n = 0
    for b in (C.get('banners') or []):
        if b.get('ativo', True) is False:
            continue
        web = resize_to(b.get('imagem_web'), 1600)
        mob = resize_to(b.get('imagem_mobile'), 900)
        if not (web or mob):
            continue
        link = (b.get('link') or '').strip()
        ext = link.startswith('http')
        attrs = (f' href="{esc(link)}"' + (' target="_blank" rel="noopener"' if ext else '') + ' data-ga="banner_click" data-ga-item="canecas"') if link else ''
        tag = 'a' if link else 'div'
        src_mob = f'<source media="(max-width:767px)" srcset="{mob}">' if mob else ''
        pic = (f'<picture>{src_mob}<img src="{web or mob}" alt="{esc(b.get("alt") or "Canecas personalizadas")}" '
               f'width="1600" height="320" loading="lazy" decoding="async"></picture>')
        slides += f'<{tag} class="cn-slide"{attrs}>{pic}</{tag}>'
        n += 1
    banners_blk = ''
    if n:
        dots = ''.join(f'<button type="button" class="cn-dot" aria-label="Banner {i + 1}"></button>' for i in range(n)) if n > 1 else ''
        banners_blk = f'<div class="cn-banners" aria-label="Destaques"><div class="cn-track">{slides}</div>' + (f'<div class="cn-dots">{dots}</div>' if dots else '') + '</div>'
        if n > 1:
            banners_blk += ('<script>(function(){var w=document.querySelector(".cn-banners"),t=w.querySelector(".cn-track"),d=[].slice.call(w.querySelectorAll(".cn-dot")),n=t.children.length,i=0,tm;'
                            'function go(k){i=(k+n)%n;t.scrollTo({left:t.children[i].offsetLeft-t.offsetLeft,behavior:"smooth"})}'
                            'function mark(){i=Math.max(0,Math.min(n-1,Math.round(t.scrollLeft/t.clientWidth)));d.forEach(function(e,j){e.classList.toggle("on",j===i)})}'
                            'function stop(){clearInterval(tm)}function start(){tm=setInterval(function(){go(i+1)},5500)}'
                            't.addEventListener("scroll",mark,{passive:true});d.forEach(function(e,j){e.addEventListener("click",function(){stop();go(j)})});'
                            'w.addEventListener("touchstart",stop,{passive:true});w.addEventListener("mouseenter",stop);w.addEventListener("mouseleave",start);start();mark()})();</script>')
    # temas
    tcards = ''
    for t in (C.get('temas') or []):
        if t.get('ativo', True) is False or not t.get('nome'):
            continue
        foto = resize_to(t.get('foto'), 700) if t.get('foto') else ''
        top = (f'<img src="{foto}" alt="{esc(t.get("alt") or t["nome"])}" width="350" height="350" loading="lazy">' if foto
               else f'<span class="tm-e" aria-hidden="true">{esc(t.get("emoji") or "☕")}</span>')
        msg = f'Oi! Vim pelo site da Lily Cestas e quero uma caneca personalizada no tema: {t["nome"]}.'
        tcards += (f'<a class="tema{" has-img" if foto else ""}" href="{esc(wa(msg))}" target="_blank" rel="noopener" data-ga="caneca_tema_click" data-ga-item="{esc(slugify(t["nome"]))}">'
                   f'{top}<h3>{esc(t["nome"])}</h3><p>{esc(v(t.get("descricao") or ""))}</p><em>Quero este →</em></a>')
    steps = ''.join(f'<li><b>{i + 1}</b><h3>{esc(s.get("titulo", ""))}</h3><p>{esc(v(s.get("texto", "")))}</p></li>'
                    for i, s in enumerate(C.get('passos') or []) if s.get('titulo'))
    secs = ''.join(f'<section><h2>{esc(s["titulo"])}</h2><p>{esc(v(s.get("texto", "")))}</p></section>' for s in (C.get('secoes') or []) if s.get('titulo'))
    faq_items = [(q['pergunta'], v(q.get('resposta', ''))) for q in (C.get('faq') or []) if q.get('pergunta')]
    faq_block = ''.join(f'<details><summary>{esc(q)}</summary><p>{esc(a)}</p></details>' for q, a in faq_items)
    trail = [('Início', '/'), ('Canecas personalizadas', path)]
    crumbs = ' › '.join(f'<a href="{u}">{esc(nm)}</a>' if i < len(trail) - 1 else f'<span>{esc(nm)}</span>' for i, (nm, u) in enumerate(trail))
    extra = [{'@type': 'CollectionPage', 'name': h1, 'url': BASE + path, 'about': 'Canecas personalizadas'}]
    robots = 'noindex, nofollow' if C.get('noindex', True) else 'index, follow, max-image-preview:large'
    prods_blk = (f'<section id="produtos"><h2>{esc(C.get("produtos_titulo") or "Canecas prontas para pedir")}</h2><div class="cards">{cards_html(plist)}</div></section>') if plist else ''
    cta_msg = 'Oi! Vim pelo site da Lily Cestas e quero criar uma caneca personalizada do meu jeito.'
    catalogos_blk = (f'<section id="catalogos"><h2>{esc(C.get("catalogos_titulo") or "Catálogos por tema")}</h2><p class="sub">{esc(v(C.get("catalogos_texto") or "Folheie o catálogo, escolha o número do modelo e personalize."))}</p><div class="ctcards">{catalogo_cards()}</div></section>') if CATALOGOS else ''
    fonts = ('<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
             '<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;600;700&family=Plus+Jakarta+Sans:wght@400;500;600&display=swap" rel="stylesheet">'
             '<link rel="stylesheet" href="/assets/css/pages.css"><link rel="stylesheet" href="/assets/css/canecas.css">\n</head><body>')
    body = f'''<main><div class="wrap"><nav class="crumbs" aria-label="Navegação">{crumbs}</nav>
<header class="cn-hero"><span class="tag">☕ Canecas personalizadas</span><h1>{esc(h1)}</h1><p class="intro">{esc(v(C.get("intro") or ""))}</p>
<p><a class="btn" href="#catalogos">{esc(C.get("botao_principal") or "Escolher meu tema")}</a> <a class="btn ghost" href="{esc(wa(cta_msg))}" target="_blank" rel="noopener" data-ga="whatsapp_click" data-ga-item="canecas_hero">Falar no WhatsApp</a></p></header>
{banners_blk}
{catalogos_blk}
<section><h2>Como funciona</h2><ol class="passos">{steps}</ol><p class="nota">*Locais mais distantes podem ter taxa de entrega. Confira pelo CEP no checkout ou pelo WhatsApp.</p></section>
{prods_blk}
{secs}
<section class="cn-cta"><h2>{esc(C.get("cta_titulo") or "Não achou o seu tema?")}</h2><p>{esc(v(C.get("cta_texto") or ""))}</p><p><a class="btn" href="{esc(wa(cta_msg))}" target="_blank" rel="noopener" data-ga="whatsapp_click" data-ga-item="canecas_cta">Criar minha caneca no WhatsApp</a></p></section>
<section><h2>Perguntas frequentes</h2><div class="faq">{faq_block}</div></section>
</div></main>'''
    write_page(path, head(title, desc, path, robots) + jsonld(BUSINESS, crumb_ld(trail), faq_ld(faq_items), *extra) + fonts + top_html() + body + footer_html() + '</body></html>')
    if C.get('noindex', True) is False:
        page_urls.append(path)


if CANECAS.get('ativa', True):
    canecas_page()
    for _c in CATALOGOS:
        catalogo_page(_c)


# ---------------------------------------------------------------- home (loja completa)
tpl = (ROOT / 'templates/home.html').read_text(encoding='utf-8')
hero_p = next((p for p in active if p.get('destaque')), active[0] if active else visible[0])
pill_cls = 'px-4 py-2 rounded-full text-xs font-display font-medium bg-white text-[#5A3D43] border border-[#EED9DF] hover:border-[#C87888] transition-all'


def opt(o):
    txt = esc(o['texto_menu']) + (f' (+{brl(o["preco"])})' if o['preco'] > 0 else '')
    return f'<option value="{esc(o["chave"])}" data-price="{o["preco"]:.2f}" data-label="{esc(o["nome"])}">{txt}</option>'


products_js = []
for p in visible:
    products_js.append({
        'id': p['id'], 'name': p['nome'], 'category': p['_cat']['chave'], 'categoryLabel': p['_cat']['nome'],
        'price': final_price(p), 'priceOriginal': p['preco'] if p['_promo'] else None, 'badge': p['selo'], 'image': p['_img'],
        'shortDesc': p['descricao'], 'customizable': p['personalizacao'], 'includes': p['inclui'], 'quiz': p['quiz'],
        'order': p['ordem'], 'soldOut': p['status'] == 'esgotado', 'isBasket': bool(p['_cat'].get('eh_cesta'))})
addons_js = [{'id': a['id'], 'name': a['nome'], 'desc': a['descricao'], 'price': a['_promo'] or a['preco'],
              'priceOriginal': a['preco'] if a['_promo'] else None, 'image': a['_img'], 'ask': a['pede']} for a in addons]
cats_js = [{'key': c['chave'], 'label': c['nome'], 'sub': c.get('frase_apoio') or '', 'icon': c.get('icone') or '', 'basket': bool(c.get('eh_cesta'))} for c in cats_home]
hotspots = {}
for i, c in enumerate(cats_with):
    ps = cat_prods[c['chave']]
    hotspots[c['chave']] = {
        'badge': f'Pilar {i + 1:02d} • {c["nome_curto"]}', 'title': c['nome'], 'desc': c.get('frase_apoio') or c.get('pagina_intro') or c['nome'],
        'highlights': (c.get('destaques') or [p['nome'] for p in ps[:3]])[:3], 'priceFrom': f'A partir de {brl(cat_min(c))}',
        'filterKey': c['chave'], 'heroImg': c['_img'], 'caption': f'Foto real: {ps[0]["nome"]}'}
sim0 = {k: {'chave': v[0]['chave'], 'preco': v[0]['preco'], 'nome': v[0]['nome']} for k, v in
        {'base': SIM['bases'], 'louca': SIM['louca'], 'pecas_3d': SIM['pecas_3d'], 'polaroids': SIM['polaroids']}.items()}
cfg_js = {k: config[k] for k in ('pix_desconto', 'taxa_entrega', 'brinde1_valor', 'brinde1_nome', 'brinde_opcao1_nome', 'brinde_opcao2_nome', 'entrega_gratis_a_partir', 'pedido_minimo')}
cfg_js['cidades_entrega'] = [x for x in (config.get('cidades_entrega') or []) if x]
cfg_js.update({'foto_estudio_litofania': photo_lit, 'foto_estudio_polaroid': photo_pol})
dumps = lambda o: json.dumps(o, ensure_ascii=False).replace('</', '<\\/')
data_js = (f'const CONFIG = {dumps(cfg_js)};\n  const SIM0 = {dumps(sim0)};\n  const HOTSPOTS = {dumps(hotspots)};\n'
           f'  const PRODUCTS = {dumps(products_js)};\n  const ADDONS = {dumps(addons_js)};\n  const CATS = {dumps(cats_js)};\n  const FAQS = {dumps([{"q": q, "a": a} for q, a in faq])};')

hero_cats = ''.join(
    f'<button type="button" class="cat" data-hero-cat="{c["chave"]}"><img src="{c["_img"]}" alt="{esc(c["nome_tile"])}" width="760" height="567" loading="lazy"><span class="ct"><b>{esc(c["nome_tile"])}</b><small>{("a partir de " + brl(cat_min(c))) if cat_prods[c["chave"]] else "novidades em breve"}</small></span></button>'
    for c in cats_home)
hero_cats = f'<div class="cats">\n        {hero_cats}\n      </div>'
hero_img = f'''<div class="heroimg">
            <img src="{hero_p["_img"]}" alt="{esc(hero_p.get("alt") or hero_p["nome"])}" width="760" height="567" fetchpriority="high">
            <div class="tag"><div><small>{esc(hero_p["selo"] or "Destaque")}</small><b>{esc(hero_p["nome"])}</b></div><div style="text-align:right"><span class="pr">{brl(final_price(hero_p))}</span><button type="button" data-customize-prod="{hero_p["id"]}" class="btn1" style="display:block;margin-top:4px;padding:8px 14px">Personalizar</button></div></div>
          </div>'''
foto_k1 = img_url(config.get('foto_chaveiro_simples'))
if foto_k1:
    v1 = brl(config["brinde1_valor"]).replace(",00", "")
    hero_img = f'''<div class="kw">
            <span class="kw-eyebrow">Brinde Lily Cestas</span>
            <h2>Em compras a partir de {v1}, você ganha um chaveiro de brinde</h2>
            <div class="kw-row">
              <div class="kw-item"><img src="{foto_k1}" alt="{esc(config["brinde1_nome"])}" width="300" height="300" loading="eager"><small>Compras a partir de {v1}</small><b>{esc(config["brinde1_nome"])}</b></div>
            </div>
            <a class="kw-cta" href="#catalogo">Ver presentes →</a>
          </div>'''

# ---------------------------------------------------------------- pop-up do brinde e proprietaria (rodape)
_f1, _f2 = img_url(config.get('foto_chaveiro_simples')), img_url(config.get('foto_chaveiro_2'))
_secs = int(to_number(config.get('popup_brinde_segundos'), 'Configurações › popup_brinde_segundos', False) or 5)
BRINDE_POPUP = ''
_fast = f'<b>⚡ {FAST_TXT}*</b>' if FAST_TXT else ''
_fnote = f' e prazo maior. {FAST_TXT} vale para produtos prontos' if FAST_TXT else ''
if config.get('popup_brinde_ativo') is not False and _f1 and _f2:
    _v = brl(config['brinde1_valor']).replace(',00', '')
    _fm = brl(FRETE_MIN).replace(',00', '')
    _cids = [c for c in (config.get('cidades_entrega') or []) if c]
    if 'Alphaville' not in _cids:
        _cids.append('Alphaville')
    _cid = ', '.join(_cids[:-1]) + ' e ' + _cids[-1] if len(_cids) > 1 else _cids[0]
    BRINDE_POPUP = f'''<div id="brinde-pop" class="bp-ov" role="dialog" aria-modal="true" aria-labelledby="bp-title" hidden>
    <div class="bp">
      <button type="button" class="bp-x" id="bp-close" aria-label="Fechar">&times;</button>
      <span class="bp-eyebrow">🎁 Brinde Lily Cestas</span>
      <h2 id="bp-title">Em compras a partir de {_v}, você ganha um chaveiro de brinde</h2>
      <p class="bp-sub">Escolha o seu favorito:</p>
      <div class="bp-row">
        <div class="bp-opt"><img src="{_f1}" alt="Chaveiro {esc(config["brinde_opcao1_nome"])}" width="150" height="150" loading="lazy" decoding="async"><b>{esc(config["brinde_opcao1_nome"])}</b></div>
        <div class="bp-opt"><img src="{_f2}" alt="Chaveiro {esc(config["brinde_opcao2_nome"])}" width="150" height="150" loading="lazy" decoding="async"><b>{esc(config["brinde_opcao2_nome"])}</b></div>
      </div>
      <p class="bp-note">Você escolhe na hora de finalizar o pedido, pelo WhatsApp. Sem custo.</p>
      <div class="bp-ship">{_fast}<b>🚚 Entrega grátis* a partir de {_fm}</b><span>{esc(_cid)}</span><small>*Consulte seu endereço pelo WhatsApp. Locais mais distantes podem ter taxa de entrega{_fnote}.</small></div>
      <a class="bp-cta" href="#catalogo" id="bp-cta" data-ga="brinde_popup_cta">Ver presentes →</a>
      <button type="button" class="bp-no" id="bp-no">Agora não</button>
    </div>
  </div>
  <script>(function(){{var ov=document.getElementById('brinde-pop');if(!ov)return;var KEY='lily_brinde_pop',DAYS=7,tries=0,prev=null;
    try{{var t=+localStorage.getItem(KEY)||0;if(Date.now()-t<DAYS*864e5)return;}}catch(e){{}}
    function ev(n){{try{{if(window.gtag)window.gtag('event',n,{{page_path:location.pathname}});}}catch(e){{}}}}
    function busy(){{return !!document.querySelector('#cart-drawer:not(.hidden),#product-custom-modal:not(.hidden),#checkout-modal:not(.hidden)')||/^(INPUT|TEXTAREA|SELECT)$/.test((document.activeElement||{{}}).tagName||'');}}
    function show(){{if(busy()&&tries++<8){{setTimeout(show,4000);return;}}if(busy())return;
      try{{localStorage.setItem(KEY,String(Date.now()));}}catch(e){{}}
      prev=document.activeElement;ov.hidden=false;ov.classList.add('on');requestAnimationFrame(function(){{ov.classList.add('vis');}});
      document.getElementById('bp-close').focus({{preventScroll:true}});ev('brinde_popup_view');}}
    function hide(why){{ov.classList.remove('vis');setTimeout(function(){{ov.classList.remove('on');ov.hidden=true;}},250);
      if(why)ev(why);try{{if(prev&&prev.focus)prev.focus({{preventScroll:true}});}}catch(e){{}}}}
    document.getElementById('bp-close').addEventListener('click',function(){{hide('brinde_popup_close');}});
    document.getElementById('bp-no').addEventListener('click',function(){{hide('brinde_popup_close');}});
    document.getElementById('bp-cta').addEventListener('click',function(){{hide('');}});
    ov.addEventListener('click',function(e){{if(e.target===ov)hide('brinde_popup_close');}});
    document.addEventListener('keydown',function(e){{if(ov.hidden)return;if(e.key==='Escape')hide('brinde_popup_close');
      if(e.key==='Tab'){{var f=ov.querySelectorAll('button,a[href]'),a=f[0],z=f[f.length-1];
        if(e.shiftKey&&document.activeElement===a){{e.preventDefault();z.focus();}}else if(!e.shiftKey&&document.activeElement===z){{e.preventDefault();a.focus();}}}}}});
    setTimeout(show,{_secs * 1000});}})();</script>'''

pills = '\n          '.join(f'<button type="button" data-cat-filter="{c["chave"]}" class="{pill_cls}">\n            {esc(c["icone"])} {esc(c["nome_curto"])} ({len(cat_prods[c["chave"]])})\n          </button>' for c in cats_home)
mimos = f'<p class="text-xs text-white/90">Em compras a partir de <strong>{brl(config["brinde1_valor"]).replace(",00", "")}</strong> você ganha {esc(config["brinde1_nome"])}!</p>'
reward_init = f'Compre a partir de {brl(config["brinde1_valor"])} e ganhe {esc(config["brinde1_nome"])}!'

title = 'Cestas de Presente e Presentes Personalizados | Lily Cestas'
desc_home = 'Cestas de presente, café da manhã e presentes personalizados. Personalize pelo WhatsApp e receba em casa. Entrega grátis a partir de ' + FRETE_TXT + '.'
home_ld = jsonld(BUSINESS,
                 {'@type': 'WebSite', '@id': BASE + '/#site', 'url': BASE + '/', 'name': 'Lily Cestas', 'inLanguage': 'pt-BR', 'publisher': {'@id': BASE + '/#negocio'}},
                 {'@type': 'ItemList', 'name': 'Catálogo Lily Cestas', 'itemListElement': [{'@type': 'ListItem', 'position': i + 1, 'item': prod_ld(p)} for i, p in enumerate(visible)]},
                 faq_ld(faq))
repl = {
    'TITLE': esc(title), 'CANONICAL': f'<link rel="canonical" href="{BASE}{SHOP}">',
    'ROBOTS': f'<meta name="robots" content="{"index, follow, max-image-preview:large" if LOJA_NO_AR else "noindex, nofollow"}">',
    'JSONLD': home_ld, 'WA': WA, 'INSTA': config['instagram'], 'IFOOD': config['ifood_url'], 'PIX': str(int(config['pix_desconto'])), 'N': str(len(visible)),
    'HOME_LINKS': ''.join(f'<a href="/{c["pagina_url"]}/" class="p-4 rounded-2xl border border-[#EED9DF] bg-[#FDF8F9] hover:bg-white text-sm font-display font-semibold text-[#A65365]">{esc(c["nome"])} →</a>' for c in cats_with if c.get('pagina_url')) + ''.join(f'<a href="/{o["slug"]}/" class="p-4 rounded-2xl border border-[#EED9DF] bg-[#FDF8F9] hover:bg-white text-sm font-display font-semibold text-[#A65365]">{esc(o["nome"])} →</a>' for o in OCCASIONS_OK) + '<a href="/catalogo/" class="p-4 rounded-2xl border border-[#EED9DF] bg-[#FDF8F9] hover:bg-white text-sm font-display font-semibold text-[#A65365]">Catálogo completo →</a>',
    'CIDADES_JSON': json.dumps([x for x in (config.get('cidades_entrega') or []) if x], ensure_ascii=False),
    'FOOTER_CATS': ''.join(f'<li><a href="/{c["pagina_url"]}/" class="hover:text-white hover:underline">{esc(c["nome"])}</a></li>' for c in cats_with if c.get('pagina_url')) + ''.join(f'<li><a href="/{o["slug"]}/" class="hover:text-white hover:underline">{esc(o["nome"])}</a></li>' for o in OCCASIONS_OK),
    'BANNERS': BANNERS_HTML, 'IG_BTN': IG_BTN, 'BRINDE_POPUP': BRINDE_POPUP, 'OWNER_BLOCK': OWNER_BLOCK,
    'FAST_TOP': (f'<span class="fast">⚡ {FAST_TXT}*</span>' if FAST_TXT else ''), 'FAST_CHIP': (f'<span class="fastchip">⚡ {FAST_TXT}*</span>' if FAST_TXT else ''), 'FAST_FOOT': (f' {FAST_TXT}* em produtos prontos.' if FAST_TXT else ''),
    'B1V': brl(config['brinde1_valor']).replace(',00', ''), 'FRETE_MIN': brl(FRETE_MIN).replace(',00', ''), 'HERO_CATS': hero_cats, 'HERO_IMG': hero_img, 'CAT_PILLS': pills, 'MIMOS_TEXT': mimos, 'REWARD_INIT': reward_init, 'DATA_JS': data_js,
    'OPT_BASES': ''.join(opt(o) for o in SIM['bases']), 'OPT_LOUCA': ''.join(opt(o) for o in SIM['louca']),
    'OPT_3D': ''.join(opt(o) for o in SIM['pecas_3d']), 'OPT_POL': ''.join(opt(o) for o in SIM['polaroids']),
}
home = tpl
for k, v in repl.items():
    home = home.replace('{{%s}}' % k, v)
# ajustes de template que dependem dos dados
home = home.replace('💳 Pix com 5% off', f'💳 Pix com {int(config["pix_desconto"])}% off').replace('💠 PIX (5% OFF)', f'💠 PIX ({int(config["pix_desconto"])}% OFF)')
home = home.replace('(5% PIX)', '(${CONFIG.pix_desconto}% PIX)')
home = re.sub(r'\.cats\{display:grid;grid-template-columns:repeat\(2,1fr\);gap:12px;margin-top:34px\}@media\(min-width:900px\)\{\.cats\{grid-template-columns:repeat\(4,1fr\);gap:18px\}\}',
              '.cats{display:grid;grid-template-columns:repeat(2,1fr);gap:12px;margin-top:34px}@media(min-width:900px){.cats{grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:18px}}', home)
left = re.findall(r'\{\{[A-Z_0-9]+\}\}', home)
if left:
    print('ERRO interno: marcadores sem substituição:', set(left))
    sys.exit(1)
if LOJA_NO_AR:
    (OUT / 'index.html').write_text(home, encoding='utf-8')
    links = (ROOT / 'public/links.html').read_text(encoding='utf-8')
    links = links.replace('<link rel="canonical" href="https://lilycestas.com.br/">', f'<link rel="canonical" href="{BASE}/links/">\n  <meta name="robots" content="noindex">')
    write_page('/links/', links)
else:
    shutil.copy(ROOT / 'public/links.html', OUT / 'index.html')
    write_page('/home/', home)

# imagens legadas usadas por trechos escondidos da pagina
legacy = {'logo': '/assets/img/logo.webp', 'logo_white': '/assets/img/logo-white.webp', 'litofania_3d': photo_lit, 'polaroid_led': photo_pol}
for key, c in zip(('cesta_macarons', 'caneca_coracao', 'quadro_shadowbox'), (cats_with + cats_with + cats_with)[:3]):
    legacy[key] = c['_img']
(OUT / 'lily-images.js').write_text('window.LILY_IMAGES=' + json.dumps(legacy) + ';\n', encoding='utf-8')


# ---------------------------------------------------------------- analytics (GA4) e rastreio de cliques
GA4 = str(config.get('ga4_id') or '').strip().upper()
if GA4 and not re.fullmatch(r'G-[A-Z0-9]{6,14}', GA4):
    print(f'Aviso: o código do Google Analytics "{GA4}" não parece válido (deve ser como G-ABC123XYZ). Analytics não foi ligado.')
    GA4 = ''
ga_snippet = ''
if GA4:
    ga_snippet = (f'<script async src="https://www.googletagmanager.com/gtag/js?id={GA4}"></script>'
                  "<script>window.dataLayer=window.dataLayer||[];function gtag(){dataLayer.push(arguments);}"
                  "gtag('consent','default',{ad_storage:'denied',ad_user_data:'denied',ad_personalization:'denied',analytics_storage:'granted'});"
                  f"gtag('js',new Date());gtag('config','{GA4}');</script>")
CLARITY = str(config.get('clarity_id') or '').strip().lower()
if CLARITY and not re.fullmatch(r'[a-z0-9]{8,12}', CLARITY):
    print(f'Aviso: o código do Microsoft Clarity "{CLARITY}" não parece válido. Clarity não foi ligado.')
    CLARITY = ''
if CLARITY:
    # carrega só depois da página pronta e ociosa, para não pesar no carregamento
    ga_snippet += ("<script>(function(c,l,a,r,i){c[a]=c[a]||function(){(c[a].q=c[a].q||[]).push(arguments)};"
                   "function go(){var t=l.createElement(r);t.async=1;t.src='https://www.clarity.ms/tag/'+i;"
                   "var y=l.getElementsByTagName(r)[0];y.parentNode.insertBefore(t,y);}"
                   "function idle(){(window.requestIdleCallback||function(f){setTimeout(f,1500)})(go)}"
                   "if(l.readyState==='complete')idle();else c.addEventListener('load',idle);"
                   f"}})(window,document,'clarity','script','{CLARITY}');</script>")
ga_snippet += '<script defer src="/assets/js/track.js"></script>'
for f in OUT.rglob('*.html'):
    if f.name.startswith('google') or '/assets/' in str(f):
        continue
    t = f.read_text(encoding='utf-8')
    if 'http-equiv="refresh"' in t or '</head>' not in t:
        continue
    f.write_text(t.replace('</head>', ga_snippet + '</head>', 1), encoding='utf-8')

# ---------------------------------------------------------------- sitemap e robots
urls = ['/'] + page_urls
today = datetime.date.today().isoformat()
(OUT / 'sitemap.xml').write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + ''.join(
    f'  <url><loc>{BASE}{u}</loc><lastmod>{today}</lastmod><changefreq>{"weekly" if u == "/" else "monthly"}</changefreq><priority>{"1.0" if u == "/" else ("0.6" if u.startswith("/produto/") else "0.8")}</priority></url>\n' for u in urls) + '</urlset>\n', encoding='utf-8')
(OUT / 'robots.txt').write_text(f'User-agent: *\nAllow: /\n\nSitemap: {BASE}/sitemap.xml\n', encoding='utf-8')

print(f'Site gerado em _site/: {len(visible)} produtos ({len(active)} ativos), {len(cats_with)} categorias, {len(page_urls)} páginas de SEO. '
      f'Loja principal: {"NO AR em /" if LOJA_NO_AR else "em /home/ (página de links em /)"}')

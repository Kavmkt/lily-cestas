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
    'pix_desconto': 5, 'taxa_entrega': 15, 'brinde1_valor': 150, 'brinde1_nome': 'Chaveiro de brinde',
    'brinde2_valor': 200, 'brinde2_nome': 'Chaveiro personalizado com o seu nome',
    'foto_chaveiro_simples': '', 'foto_chaveiro_personalizado': '',
    'foto_estudio_litofania': '', 'foto_estudio_polaroid': '',
}
config.update({k: v for k, v in load_json(ROOT / 'data/config.json', {}).items() if v not in (None, '')})
config['whatsapp'] = re.sub(r'\D', '', str(config['whatsapp']))
if len(config['whatsapp']) in (10, 11):
    config['whatsapp'] = '55' + config['whatsapp']
for k in ('pix_desconto', 'taxa_entrega', 'brinde1_valor', 'brinde2_valor'):
    config[k] = to_number(config[k], f'Configurações › {k}') or 0
LOJA_NO_AR = bool(config['loja_no_ar'])
SHOP = '/' if LOJA_NO_AR else '/home/'   # onde fica a loja completa
WA = config['whatsapp']
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
    'description': 'Atelier de cestas de presente afetivas, cestas de café da manhã, xícaras e canecas personalizadas, litofania 3D, letras 3D e Polaroids.',
    'priceRange': f'R${int(PRECO_MIN)} - R${int(max(final_price(p) for p in visible))}',
    'telephone': phone,
    'contactPoint': {'@type': 'ContactPoint', 'telephone': phone, 'contactType': 'customer service', 'availableLanguage': 'Portuguese', 'url': f'https://wa.me/{WA}'},
    'address': {'@type': 'PostalAddress', 'addressLocality': 'Santana de Parnaíba', 'addressRegion': 'SP', 'addressCountry': 'BR'},
    'areaServed': [{'@type': 'City', 'name': n} for n in ['Santana de Parnaíba', 'Barueri', 'Cajamar']] + [{'@type': 'Place', 'name': 'Alphaville'}],
    'sameAs': [config['instagram']],
    'openingHoursSpecification': [{'@type': 'OpeningHoursSpecification', 'dayOfWeek': ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'], 'opens': '08:00', 'closes': '19:00'}],
}


def prod_ld(p):
    offer = {'@type': 'Offer', 'url': BASE + SHOP + '#catalogo', 'priceCurrency': 'BRL', 'price': '%.2f' % final_price(p),
             'availability': 'https://schema.org/OutOfStock' if p['status'] == 'esgotado' else 'https://schema.org/InStock',
             'seller': {'@id': BASE + '/#negocio'}}
    return {'@type': 'Product', 'name': p['nome'], 'image': BASE + p['_img'], 'description': p['descricao'],
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


def footer_html():
    cat_li = ''.join(f'<li><a href="/{c["pagina_url"]}/">{esc(c["nome"])}</a></li>' for c in cats_with if c.get('pagina_url'))
    city_li = ''.join(f'<li><a href="/{x["slug"]}/">Presentes em {x["cidade"]}</a></li>' for x in CITIES)
    return f'''<footer class="foot"><div class="wrap grid">
<div><strong>Lily Cestas</strong><p>Atelier de cestas de presente afetivas, louças personalizadas, arte 3D e Polaroids. Santana de Parnaíba, SP.</p><p><a href="https://wa.me/{WA}" rel="noopener" target="_blank">WhatsApp {phone}</a><br><a href="{config['instagram']}" rel="noopener" target="_blank">Instagram @lilycestas.ofc</a></p></div>
<div><strong>Nossos presentes</strong><ul>{cat_li}</ul></div>
<div><strong>Onde entregamos</strong><ul>{city_li}</ul></div>
</div><p class="copy">© {datetime.date.today().year} Lily Cestas &amp; Atelier Personalizados.</p></footer>
<a class="wafab" href="https://wa.me/{WA}?text={esc('Oi! Vim pelo site da Lily Cestas.')}" target="_blank" rel="noopener" style="position:fixed;right:18px;bottom:18px;z-index:30;background:#25D366;color:#fff;border-radius:99px;padding:12px 18px;font:600 14px Montserrat,sans-serif;text-decoration:none;box-shadow:0 14px 30px -10px rgba(37,211,102,.7)">💬 WhatsApp</a>'''


def top_html():
    return f'''<header class="top"><div class="wrap bar"><a class="brand" href="/"><img src="/assets/img/logo.webp" alt="Logo Lily Cestas" width="56" height="54"><span>Lily Cestas<small>Atelier &amp; Personalizados 3D</small></span></a>
<nav><a href="{SHOP}#catalogo">Catálogo</a><a href="{SHOP}#simulador">Estúdio ao vivo</a><a class="btn sm" href="https://wa.me/{WA}" target="_blank" rel="noopener">WhatsApp</a></nav></div></header>'''


def cards_html(plist):
    out = ''
    for p in plist:
        old = f'<span style="text-decoration:line-through;color:#8C6C73;font-size:12px;display:block">{brl(p["preco"])}</span>' if p['_promo'] else ''
        action = '<span style="font-size:12px;font-weight:600;color:#6E5057">Esgotado</span>' if p['status'] == 'esgotado' else f'<a class="btn sm" href="{SHOP}#catalogo">Personalizar</a>'
        out += f'''<article class="card"><img src="{p["_img"]}" alt="{esc(p.get("alt") or p["nome"])}" width="760" height="567" loading="lazy"><div class="cb"><h3>{esc(p["nome"])}</h3><p>{esc(p["descricao"])}</p><div class="pr"><span>{old}<b>{brl(final_price(p))}</b></span>{action}</div></div></article>'''
    return out


def page_html(path, title, desc, h1, intro, blocks, plist, faq_items, trail, extra_nodes, related_html, hero_img=None, cta='Montar meu presente'):
    nodes = [BUSINESS, crumb_ld(trail), faq_ld(faq_items)] + extra_nodes
    crumbs = ' › '.join(f'<a href="{u}">{esc(n)}</a>' if i < len(trail) - 1 else f'<span>{esc(n)}</span>' for i, (n, u) in enumerate(trail))
    sec = ''.join(f'<section><h2>{esc(h)}</h2><p>{esc(t)}</p></section>' for h, t in blocks)
    img = f'<img class="hero" src="{hero_img[0]}" alt="{esc(hero_img[1])}" width="760" height="567">' if hero_img else ''
    faq_block = ''.join(f'<details><summary>{esc(q)}</summary><p>{esc(a)}</p></details>' for q, a in faq_items)
    return (head(title, desc, path) + jsonld(*nodes) + '''
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@300;400;600;700&family=Plus+Jakarta+Sans:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="/assets/css/pages.css">
</head><body>''' + top_html() + f'''<main><div class="wrap"><nav class="crumbs" aria-label="Navegação">{crumbs}</nav>
<div class="lead"><div><h1>{esc(h1)}</h1><p class="intro">{esc(intro)}</p><p><a class="btn" href="{SHOP}#simulador">{cta}</a> <a class="btn ghost" href="{SHOP}#catalogo">Ver catálogo completo</a></p></div>{img}</div>
{sec}
<section><h2>Produtos</h2><div class="cards">{cards_html(plist)}</div></section>
<section><h2>Perguntas frequentes</h2><div class="faq">{faq_block}</div></section>
{related_html}
</div></main>''' + footer_html() + '</body></html>')


CITIES = [
    dict(slug='cestas-de-presente-santana-de-parnaiba', cidade='Santana de Parnaíba',
         title='Cestas de Presente em Santana de Parnaíba | Lily Cestas',
         desc='Cestas de presente, café da manhã, xícaras e presentes personalizados em Santana de Parnaíba, SP. Entrega agendada a partir das 06h30. Peça pelo site.',
         h1='Cestas de Presente e Presentes Personalizados em Santana de Parnaíba',
         intro='A Lily Cestas é um atelier de presentes de Santana de Parnaíba, em São Paulo. Montamos cestas de presente afetivas, cestas de café da manhã, xícaras e canecas personalizadas, luminárias litofania 3D e fotos Polaroid.',
         blocks=[('Presentes para o Centro Histórico, Fazendinha e outras regiões da cidade', 'Atendemos moradores de Santana de Parnaíba que querem surpreender família, amigos e quem mora longe, e também quem trabalha na cidade. Para o Centro Histórico, a Fazendinha, o Suru e demais bairros, informe o CEP no checkout para confirmarmos a entrega no horário escolhido.'),
                 ('Entrega agendada a partir das 06h30', 'Cestas e kits Polaroid podem ser agendados para chegar logo cedo, inclusive para o mesmo dia ou dia seguinte, conforme a disponibilidade. Para presentes personalizados com arte (xícaras, litofania e 3D) reserve de 1 a 2 dias úteis para a aprovação da prévia.'),
                 ('Datas em que mais encomendam por aqui', 'Aniversário, Dia das Mães, Dia dos Namorados, Natal, nascimento de bebê, formatura e agradecimento a professores e equipes. Se o prazo estiver curto, chame no WhatsApp para vermos o que dá para fazer.')],
         vizinhas=['alphaville', 'barueri', 'cajamar']),
    dict(slug='cestas-de-presente-alphaville', cidade='Alphaville',
         title='Cestas de Presente em Alphaville (Barueri e Santana de Parnaíba) | Lily Cestas',
         desc='Cestas de presente, café da manhã, xícaras e presentes personalizados para Alphaville, Tamboré e região. Personalize no site e combine a entrega pelo WhatsApp.',
         h1='Cestas de Presente e Presentes Personalizados para Alphaville',
         intro='Alphaville fica entre Barueri e Santana de Parnaíba, e é uma das regiões que mais recebe nossos presentes: cestas de café da manhã para casa ou escritório, presentes para o time, cestas para aniversário e presentes afetivos personalizados.',
         blocks=[('Presentes corporativos e para o escritório', 'Cestas de café da manhã e presentes personalizados com nome funcionam bem para aniversário de equipe, boas-vindas a novos colaboradores e agradecimento a clientes. Informe o endereço do escritório no checkout e combinamos o melhor horário de entrega.'),
                 ('Condomínios e residenciais', 'Para entregas em condomínios fechados, informe o nome do residencial, a quadra e o lote ou a torre e o apartamento, além de um contato para a portaria. Assim a cesta chega fresquinha e na hora combinada.'),
                 ('Peças que fazem sucesso na região', 'Cesta Lily Imperial, luminária litofania com foto da família, box romântico com espumante e kits de Polaroids. Confira o catálogo completo e monte o seu presente no Estúdio ao vivo.')],
         vizinhas=['barueri', 'santana-de-parnaiba', 'cajamar']),
    dict(slug='cestas-de-presente-barueri', cidade='Barueri',
         title='Cestas de Presente em Barueri | Lily Cestas',
         desc='Cestas de presente, café da manhã, xícaras personalizadas e presentes em 3D para Barueri, SP. Personalize no site e agende a entrega.',
         h1='Cestas de Presente e Presentes Personalizados em Barueri',
         intro='Atendemos Barueri com cestas de presente afetivas, cestas de café da manhã, xícaras e canecas personalizadas, litofania 3D e Polaroids. Você personaliza no site e agenda a entrega no horário que preferir.',
         blocks=[('Entrega em Barueri', 'Para o Centro, o Jardim Silveira, o Tamboré, a Aldeia da Serra e demais bairros, informe o CEP no checkout. Confirmamos a disponibilidade, o horário e a taxa de entrega para o seu endereço antes de fechar o pedido.'),
                 ('Presente de última hora?', 'Cestas prontas e kits Polaroid podem ser agendados para o mesmo dia ou dia seguinte, conforme a agenda do atelier. Para peças personalizadas com arte, o prazo é de 1 a 2 dias úteis após a aprovação.'),
                 ('Opções para todos os orçamentos', f'Do kit Polaroid iluminado a cestas completas, o catálogo tem presentes a partir de {brl(PRECO_MIN)}. O Quiz Concierge ajuda a escolher pelo valor que você quer investir.')],
         vizinhas=['alphaville', 'santana-de-parnaiba', 'cajamar']),
    dict(slug='cestas-de-presente-cajamar', cidade='Cajamar',
         title='Cestas de Presente em Cajamar | Lily Cestas',
         desc='Cestas de presente, café da manhã, xícaras personalizadas e presentes em 3D para Cajamar, SP. Peça pelo site e combine a entrega pelo WhatsApp.',
         h1='Cestas de Presente e Presentes Personalizados em Cajamar',
         intro='Também atendemos Cajamar. Escolha a cesta ou monte o seu presente personalizado no site, informe o CEP no checkout e combinamos a entrega pelo WhatsApp.',
         blocks=[('Como pedir de Cajamar', 'Escolha o presente, personalize no Estúdio ao vivo e finalize o checkout em 3 etapas. Informe o bairro e o CEP, como Polvilho, Jordanésia ou outras regiões, e confirmamos a entrega e a taxa antes de seguir com o pedido.'),
                 ('Presentes que também viajam bem', 'Xícaras, litofania 3D, letras 3D e Polaroids podem ser enviados com embalagem protegida para todo o Brasil, ótimo para presentear quem mora longe.'),
                 ('Atendimento personalizado', 'Dúvidas sobre prazo, personalização ou entrega? Chame no WhatsApp. A prévia digital da arte sempre passa pela sua aprovação antes da produção.')],
         vizinhas=['santana-de-parnaiba', 'alphaville', 'cajamar']),
]
CITIES[3]['vizinhas'] = ['santana-de-parnaiba', 'alphaville', 'barueri']
CITY_BY = {c['slug'].replace('cestas-de-presente-', ''): c for c in CITIES}
FAQ_COMMON = faq

page_urls = []
for c in cats_with:
    if not c.get('pagina_url'):
        continue
    path = f'/{c["pagina_url"]}/'
    ps = cat_prods[c['chave']]
    prices = [final_price(p) for p in ps]
    items = [
        (f'Quanto custa {c["nome"].lower()} na Lily Cestas?', f'Os preços do catálogo vão de {brl(min(prices))} a {brl(max(prices))} nesta categoria. O valor final depende das personalizações e adicionais escolhidos no Estúdio ao vivo.'),
        ('Vocês entregam em Alphaville, Barueri, Santana de Parnaíba e Cajamar?', 'Atendemos essas cidades. Informe o CEP no checkout para confirmarmos a disponibilidade, o horário e a taxa de entrega.'),
        ('Posso aprovar a arte antes da produção?', 'Sim. Você recebe a prévia digital pelo WhatsApp e só depois seguimos para a produção.'),
    ] + FAQ_COMMON[-1:]
    rel = '<section class="rel"><h2>Outras linhas e cidades atendidas</h2><p>' + ''.join(
        f'<a href="/{o["pagina_url"]}/">{esc(o["nome"])}</a>' for o in cats_with if o is not c and o.get('pagina_url')) + '</p><p>' + ''.join(
        f'<a href="/{x["slug"]}/">{x["cidade"]}</a>' for x in CITIES) + '</p></section>'
    extra = [{'@type': 'CollectionPage', 'name': c['pagina_h1'], 'url': BASE + path, 'about': c['nome'], 'mainEntity': {'@type': 'ItemList', 'itemListElement': [{'@type': 'ListItem', 'position': i + 1, 'item': prod_ld(p)} for i, p in enumerate(ps)]}}]
    secoes = [(s.get('titulo', ''), s.get('texto', '')) for s in (c.get('pagina_secoes') or []) if s.get('titulo')]
    write_page(path, page_html(path, c.get('pagina_titulo') or c['nome'], c.get('pagina_descricao') or '', c.get('pagina_h1') or c['nome'], c.get('pagina_intro') or '', secoes, ps, items,
                               [('Início', '/'), (c['nome'], path)], extra, rel, (ps[0]['_img'], ps[0].get('alt') or ps[0]['nome'])))
    page_urls.append(path)

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
        (f'A Lily Cestas entrega em {cid}?', f'Sim, atendemos {cid}. Informe o CEP no checkout e confirmamos a disponibilidade, o horário e a taxa de entrega para o seu endereço.'),
        (f'Qual o prazo para receber uma cesta de presente em {cid}?', 'Cestas e kits Polaroid podem ser agendados para o mesmo dia ou dia seguinte, conforme a agenda, com entregas a partir das 06h30. Peças personalizadas com arte levam de 1 a 2 dias úteis após a aprovação.'),
        ('Posso personalizar a cesta com nome e fotos?', 'Pode. A xícara leva o nome, a palavra em 3D e as fotos Polaroid são personalizadas.'),
    ] + FAQ_COMMON[-2:]
    viz = ''.join(f'<a href="/{CITY_BY[v]["slug"]}/">{CITY_BY[v]["cidade"]}</a>' for v in c['vizinhas'])
    rel = '<section class="rel"><h2>Também atendemos</h2><p>' + viz + '</p><p>' + ''.join(f'<a href="/{o["pagina_url"]}/">{esc(o["nome"])}</a>' for o in cats_with if o.get('pagina_url')) + '</p></section>'
    extra = [{'@type': 'WebPage', 'name': c['h1'], 'url': BASE + path, 'about': {'@id': BASE + '/#negocio'}, 'spatialCoverage': {'@type': 'City', 'name': cid}}]
    write_page(path, page_html(path, c['title'], c['desc'], c['h1'], c['intro'], c['blocks'], featured, items, [('Início', '/'), (f'Presentes em {cid}', path)], extra, rel,
                               (featured[0]['_img'], featured[0].get('alt') or featured[0]['nome']) if featured else None))
    page_urls.append(path)

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
hotspots = {}
for i, c in enumerate(cats_with):
    ps = cat_prods[c['chave']]
    hotspots[c['chave']] = {
        'badge': f'Pilar {i + 1:02d} • {c["nome_curto"]}', 'title': c['nome'], 'desc': c.get('frase_apoio') or c.get('pagina_intro') or c['nome'],
        'highlights': (c.get('destaques') or [p['nome'] for p in ps[:3]])[:3], 'priceFrom': f'A partir de {brl(cat_min(c))}',
        'filterKey': c['chave'], 'heroImg': c['_img'], 'caption': f'Foto real: {ps[0]["nome"]}'}
sim0 = {k: {'chave': v[0]['chave'], 'preco': v[0]['preco'], 'nome': v[0]['nome']} for k, v in
        {'base': SIM['bases'], 'louca': SIM['louca'], 'pecas_3d': SIM['pecas_3d'], 'polaroids': SIM['polaroids']}.items()}
cfg_js = {k: config[k] for k in ('pix_desconto', 'taxa_entrega', 'brinde1_valor', 'brinde1_nome', 'brinde2_valor', 'brinde2_nome')}
cfg_js.update({'foto_estudio_litofania': photo_lit, 'foto_estudio_polaroid': photo_pol})
dumps = lambda o: json.dumps(o, ensure_ascii=False).replace('</', '<\\/')
data_js = (f'const CONFIG = {dumps(cfg_js)};\n  const SIM0 = {dumps(sim0)};\n  const HOTSPOTS = {dumps(hotspots)};\n'
           f'  const PRODUCTS = {dumps(products_js)};\n  const FAQS = {dumps([{"q": q, "a": a} for q, a in faq])};')

hero_cats = ''.join(
    f'<button type="button" class="cat" data-hero-cat="{c["chave"]}"><img src="{c["_img"]}" alt="{esc(c["nome_tile"])}" width="760" height="567" loading="lazy"><span class="ct"><b>{esc(c["nome_tile"])}</b><small>a partir de {brl(cat_min(c))}</small></span></button>'
    for c in cats_with)
hero_cats = f'<div class="cats">\n        {hero_cats}\n      </div>'
hero_img = f'''<div class="heroimg">
            <img src="{hero_p["_img"]}" alt="{esc(hero_p.get("alt") or hero_p["nome"])}" width="760" height="567" fetchpriority="high">
            <div class="tag"><div><small>{esc(hero_p["selo"] or "Destaque")}</small><b>{esc(hero_p["nome"])}</b></div><div style="text-align:right"><span class="pr">{brl(final_price(hero_p))}</span><button type="button" data-customize-prod="{hero_p["id"]}" class="btn1" style="display:block;margin-top:4px;padding:8px 14px">Personalizar</button></div></div>
          </div>'''
foto_k1 = img_url(config.get('foto_chaveiro_simples'))
foto_k2 = img_url(config.get('foto_chaveiro_personalizado'))
if foto_k1 and foto_k2:
    v1 = brl(config["brinde1_valor"]).replace(",00", "")
    v2 = brl(config["brinde2_valor"]).replace(",00", "")
    hero_img = f'''<div class="kw">
            <span class="kw-eyebrow">Brinde Lily Cestas</span>
            <h2>Ganhe um chaveiro nas suas compras</h2>
            <div class="kw-row">
              <div class="kw-item"><img src="{foto_k1}" alt="{esc(config["brinde1_nome"])}" width="300" height="300" loading="eager"><small>Compras a partir de {v1}</small><b>{esc(config["brinde1_nome"])}</b></div>
              <div class="kw-item hl"><img src="{foto_k2}" alt="{esc(config["brinde2_nome"])}" width="300" height="300" loading="eager"><small>Compras a partir de {v2}</small><b>{esc(config["brinde2_nome"])}</b></div>
            </div>
            <a class="kw-cta" href="#catalogo">Ver presentes →</a>
          </div>'''
pills = '\n          '.join(f'<button type="button" data-cat-filter="{c["chave"]}" class="{pill_cls}">\n            {esc(c["icone"])} {esc(c["nome_curto"])} ({len(cat_prods[c["chave"]])})\n          </button>' for c in cats_with)
mimos = (f'<p class="text-xs text-white/90">Acima de <strong>{brl(config["brinde1_valor"]).replace(",00", "")}</strong> você ganha {esc(config["brinde1_nome"])} • '
         f'Acima de <strong>{brl(config["brinde2_valor"]).replace(",00", "")}</strong> ganha <strong>{esc(config["brinde2_nome"])}</strong>!</p>')
reward_init = f'Compre a partir de {brl(config["brinde1_valor"])} e ganhe {esc(config["brinde1_nome"])}!'

title = 'Cestas de Presente em Santana de Parnaíba e Alphaville | Lily Cestas'
desc_home = 'Cestas de presente, café da manhã, xícaras personalizadas, litofania 3D e Polaroid. Santana de Parnaíba, Alphaville, Barueri e Cajamar.'
home_ld = jsonld(BUSINESS,
                 {'@type': 'WebSite', '@id': BASE + '/#site', 'url': BASE + '/', 'name': 'Lily Cestas', 'inLanguage': 'pt-BR', 'publisher': {'@id': BASE + '/#negocio'}},
                 {'@type': 'ItemList', 'name': 'Catálogo Lily Cestas', 'itemListElement': [{'@type': 'ListItem', 'position': i + 1, 'item': prod_ld(p)} for i, p in enumerate(visible)]},
                 faq_ld(faq))
repl = {
    'TITLE': esc(title), 'CANONICAL': f'<link rel="canonical" href="{BASE}{SHOP}">',
    'ROBOTS': f'<meta name="robots" content="{"index, follow, max-image-preview:large" if LOJA_NO_AR else "noindex, nofollow"}">',
    'JSONLD': home_ld, 'WA': WA, 'INSTA': config['instagram'], 'PIX': str(int(config['pix_desconto'])), 'N': str(len(visible)),
    'B1V': brl(config['brinde1_valor']).replace(',00', ''), 'HERO_CATS': hero_cats, 'HERO_IMG': hero_img, 'CAT_PILLS': pills, 'MIMOS_TEXT': mimos, 'REWARD_INIT': reward_init, 'DATA_JS': data_js,
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

# ---------------------------------------------------------------- sitemap e robots
urls = ['/'] + page_urls
today = datetime.date.today().isoformat()
(OUT / 'sitemap.xml').write_text('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n' + ''.join(
    f'  <url><loc>{BASE}{u}</loc><lastmod>{today}</lastmod><changefreq>{"weekly" if u == "/" else "monthly"}</changefreq><priority>{"1.0" if u == "/" else "0.8"}</priority></url>\n' for u in urls) + '</urlset>\n', encoding='utf-8')
(OUT / 'robots.txt').write_text(f'User-agent: *\nAllow: /\n\nSitemap: {BASE}/sitemap.xml\n', encoding='utf-8')

print(f'Site gerado em _site/: {len(visible)} produtos ({len(active)} ativos), {len(cats_with)} categorias, {len(page_urls)} páginas de SEO. '
      f'Loja principal: {"NO AR em /" if LOJA_NO_AR else "em /home/ (página de links em /)"}')

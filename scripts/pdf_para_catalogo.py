#!/usr/bin/env python3
"""Converte um PDF de catálogo de canecas em páginas WebP + data/catalogos/<slug>.json.

Uso (no computador, precisa de: pip install pymupdf pillow):
    python3 scripts/pdf_para_catalogo.py "/caminho/Canecas Personalizadas - Pets e Animais.pdf" pets "Pets e Animais" --ordem 9

Cria assets/catalogos/<slug>/p01.webp, p02.webp... e, se ainda não existir, data/catalogos/<slug>.json
(preço e prazo ficam para editar no painel). Os modelos (número e nome) saem do texto da página-índice.
"""
import argparse
import io
import json
import re
import sys
from pathlib import Path

import fitz
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent

ap = argparse.ArgumentParser()
ap.add_argument('pdf')
ap.add_argument('slug')
ap.add_argument('nome')
ap.add_argument('--ordem', type=int, default=10)
ap.add_argument('--largura', type=int, default=1400)
a = ap.parse_args()

doc = fitz.open(a.pdf)
out = ROOT / 'assets/catalogos' / a.slug
out.mkdir(parents=True, exist_ok=True)
paginas = []
modelos = {}
for i, page in enumerate(doc):
    zoom = a.largura / page.rect.width
    pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
    im = Image.open(io.BytesIO(pix.tobytes('png'))).convert('RGB')
    name = f'p{i + 1:02d}.webp'
    im.save(out / name, 'WEBP', quality=80, method=6)
    paginas.append(f'/assets/catalogos/{a.slug}/{name}')
    # índice de modelos: linhas "01" seguidas do nome
    lines = [l.strip() for l in page.get_text().splitlines() if l.strip()]
    for l in lines:  # índice com número e nome na mesma linha ("04 Engenheiro")
        mm = re.fullmatch(r'(\d{2}) (\D.{1,60})', l)
        if mm:
            modelos.setdefault(mm.group(1), mm.group(2))
    for k in range(len(lines) - 1):
        if re.fullmatch(r'\d{2}', lines[k]) and not re.fullmatch(r'\d{2}', lines[k + 1]) and 'M O D E L O' not in lines[k + 1]:
            modelos.setdefault(lines[k], lines[k + 1])

dest = ROOT / 'data/catalogos' / f'{a.slug}.json'
dest.parent.mkdir(parents=True, exist_ok=True)
if dest.exists():
    print(f'{dest} já existe: só as páginas foram atualizadas.')
else:
    data = {
        'nome': a.nome, 'ativo': True, 'ordem': a.ordem,
        'preco': 0, 'preco_de': 0,
        'prazo': 'Prazo de produção combinado no pedido',
        'descricao': f'Catálogo de canecas personalizadas: {a.nome}. Escolha o número do modelo e personalize com nome, foto ou frase.',
        'capa': paginas[0],
        'paginas': paginas,
        'modelos': [{'numero': n, 'nome': t} for n, t in sorted(modelos.items())],
    }
    dest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(f'{len(paginas)} páginas, {len(modelos)} modelos -> {out}')

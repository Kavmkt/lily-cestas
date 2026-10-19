# Como editar a loja da Lily Cestas

Guia para quem cuida do site. Não precisa saber programar.

## Entrar no painel
1. Abra **https://app.pagescms.org** e clique em **Entrar com GitHub**.
2. Escolha o repositório **Kavmkt/lily-cestas**.
3. No menu da esquerda você vê: **Produtos**, **Categorias**, **Estúdio ao vivo**, **Perguntas frequentes** e **Configurações da loja**.

> O painel está em inglês nos botões: **Save** = Salvar, **Add an entry** = Adicionar, **Add an item** = Adicionar item, **Edit** = Editar. Os campos e as explicações estão em português.

> Depois de clicar em **Salvar**, o site se atualiza sozinho em **1 a 3 minutos**. Se a mudança não aparecer, recarregue a página (Ctrl+Shift+R no computador).

## Trocar o preço de um produto
1. **Produtos** → clique no produto.
2. Altere o campo **Preço (R$)**. Use ponto: `89.90`.
3. Clique em **Save**.

## Fazer uma promoção
No produto, preencha **Preço promocional**. O site mostra o preço antigo riscado. Para encerrar, apague o campo e salve.

## Produto esgotado ou fora de linha
No produto, campo **Situação**:
- **Ativo**: à venda.
- **Esgotado**: aparece com a faixa "Esgotado", sem botão de compra.
- **Oculto**: some do site, mas não é apagado (dá para voltar depois).

## Adicionar um produto novo
1. **Produtos** → **Add an entry**.
2. Preencha nome, categoria, preço e envie a **foto** (pode ser direto do celular).
3. Escreva uma descrição curta e o que dá para personalizar.
4. **Salvar**.

A foto é reduzida e otimizada automaticamente.

## Trocar a foto de um produto
No produto, clique em **Foto principal** e envie outra. **Salvar**.

## Criar uma categoria nova (ex.: Velas)
1. **Categorias** → **Add an entry**.
2. Preencha **Nome**, **Código interno** (minúsculas, sem espaço, ex.: `velas`), **Nome curto**, **Emoji** e a **Foto do cartão**.
3. Preencha os campos do bloco de página (endereço, títulos e textos) para o Google encontrar a categoria. Isso cria uma página nova em `lilycestas.com.br/<endereço>/`.
4. Depois, ao criar ou editar um produto, escolha essa categoria.

A categoria aparece sozinha no site, nos filtros e no mapa do Google.

## Estúdio ao vivo (montar presente)
**Estúdio ao vivo** guarda as opções e os preços da montagem: base do presente, xícaras, peças 3D e Polaroids. Mude o **Preço** ou o **Nome** de cada opção. Não mude o **Código interno**.

## Perguntas frequentes e Configurações
- **Perguntas frequentes**: adicione, edite ou remova perguntas.
- **Configurações da loja**: WhatsApp, Instagram, desconto no Pix, taxa de entrega e brindes do pedido.
- **Loja completa como página principal**: só ligue quando combinado. Desligado, o site mostra a página de links e a loja fica em `/home/`.

## Se algo der errado
- O site **não é atualizado** se houver um erro (por exemplo, preço escrito errado, foto que não carregou ou categoria que não existe). O site continua como estava.
- Você recebe um e-mail do GitHub avisando "Publicar site falhou". Em **github.com/Kavmkt/lily-cestas/actions**, abra a última execução: a mensagem em português diz exatamente o que corrigir. Corrija no painel e salve de novo.
- Para **desfazer** uma alteração: no painel, abra o item e restaure o valor anterior; ou peça ajuda (todo salvamento fica guardado no histórico).

## Dicas
- Fotos na **horizontal** ficam melhores nos cartões.
- Escreva descrições curtas e diretas.
- Use **Ordem na vitrine** para decidir quais produtos aparecem primeiro (menor número = primeiro).

---
### Para quem mantém o código
- Os dados ficam em `data/` (produtos, categorias, estúdio, FAQ, configurações). As fotos enviadas ficam em `assets/produtos/`.
- `scripts/build.py` valida tudo e gera o site em `_site/`. `templates/home.html` é o modelo da loja. `public/` guarda os arquivos fixos (página de links, logos, CSS).
- O deploy é feito pelo GitHub Actions (`.github/workflows/deploy.yml`) a cada alteração na branch `main`.
- Rodar localmente: `pip install pillow pillow-heif && python3 scripts/build.py`.

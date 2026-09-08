# POE2 GPT

[English](README.md) · [한국어](README.ko.md) · [Deutsch](README.de.md) · [Русский](README.ru.md) · [Português (Brasil)](README.pt-BR.md)

Um plugin do ChatGPT e servidor MCP para hospedagem própria, dedicado ao **Path of Exile 2**: preços de moedas, busca de equipamentos no site oficial de trocas, cálculos privados do Path of Building e melhorias dentro do orçamento.

**Status: 0.9.0, experimental.** Há até 26 ferramentas MCP. A implantação no homelab, a autenticação e os testes com seu personagem são etapas da instalação. Este repositório não oferece um servidor hospedado nem uma publicação no diretório público do ChatGPT.

## Recursos

| Área | Disponível agora |
|---|---|
| Preços de moedas | API JSON do Scout, 17 grupos de categorias, seleção de liga, busca, avaliação de conjuntos, cache e informações de origem e horário |
| Busca de equipamentos | Filtros tipados e busca de atributos pela API web experimental `trade2` do site oficial de trocas |
| Builds salvas | Tag/nome do personagem ou anexo do ChatGPT, IDs opacos, resumos limitados e páginas de nós passivos |
| Cálculo PoB | Versão fixada do PoE2 PoB em um processo privado; comparação de equipamentos e validação de requisitos |
| Melhorias | Maximizar atributos explícitos do personagem ou minimizar o custo respeitando orçamento e valores mínimos |

A liga padrão é **Forbidden Rites**; confirme outras temporadas com `list_leagues`. Os preços padrão são em **Exalted Orbs por item**. Um catálogo integrado do PoE2DB associa nomes em inglês e coreano verificado para moedas, bases, classes e habilidades selecionadas. `search_game_terms` retorna nomes e fontes; traduções ausentes não são inventadas. O servidor não precisa de uma chave da API OpenAI.

O motor combina uma revisão fixa de desenvolvimento do PoB2 com dados 0.5.5 verificados por hash. Ele distingue DPS do jogador, do lacaio selecionado e FullDPS configurado explicitamente. Passivas desconhecidas e efeitos não calculados impedem recomendações de melhorias validadas. [Compatibilidade do motor](docs/pob-engine.md).

A versão 0.9 amplia os cálculos de cargas, oferendas, companheiros e conjuntos de armas. Consulte a [cobertura da liga atual](docs/league-coverage.md) (em inglês) para ver as mecânicas suportadas e os limites restantes.

**Códigos PoB e XML bruto ficam fora do MCP e do contexto do modelo.** O serviço privado recebe dados do Ninja ou referências a anexos do ChatGPT. Não é necessário enviar arquivos ao servidor físico. Somente o processo privado lê os arquivos; o ChatGPT recebe IDs, números validados e status. Nunca cole um código PoB no chat. [Limite de dados](docs/pob-boundary.md).

## Início rápido

É necessário Python 3.11+. O processo PoB exige Linux e o ambiente Lua com versão fixada.

```bash
git clone https://github.com/Dev-Jahn/poe2-gpt.git
cd poe2-gpt
python3 -m venv .venv
.venv/bin/python -m pip install .
.venv/bin/python -m poe2_companion.check
```

No Windows, crie o ambiente com `py -3 -m venv .venv` e use `.venv\Scripts\python.exe`. O módulo `poe2_companion` e o comando anterior `poe2-companion` continuam compatíveis.

Inicie o serviço MCP no homelab:

```bash
docker compose up -d --build
```

O endereço local é `http://127.0.0.1:8000/mcp`. Conecte o ChatGPT web/desktop por um Secure MCP Tunnel restrito à conta ou por um endereço HTTPS com autenticação compatível. O Cloudflare pode fornecer OAuth; cada instância MCP aceita apenas um usuário configurado. [Instalação](docs/installation.md) · [Implantação](docs/deployment.md).

Para um Mac mini com conexões de entrada bloqueadas, siga a [configuração Mac mini + Cloudflare](docs/mac-mini-cloudflare.md): contêineres Linux nativos ARM64/amd64, Managed OAuth com validação de JWT no servidor e serviços supervisionados após o login.

[Compartilhe com dois amigos](docs/friends.md): instâncias MCP autenticadas, builds, buscas de trocas e processos PoB separados no mesmo Mac. O domínio, o túnel e o cache de preços públicos são compartilhados.

O repositório inclui `.codex-plugin/plugin.json`, `.mcp.json` e um catálogo de marketplace com origem Git para hosts locais de plugins. Instalar um servidor STDIO local não o disponibiliza no ChatGPT web. A publicação no diretório público exige uma análise separada. [Formato oficial](https://developers.openai.com/plugins/build/plugins).

## Exemplos

- “Consulte o preço de Divine Orb em Forbidden Rites em Exalted Orbs. Mostre a atualidade e a fonte.”
- “Encontre elmos raros com pelo menos 100 de vida por menos de 100 Exalted Orbs.”
- “Usando o ID da minha build importada e esses anúncios, maximize a vida com até 20 Divine Orbs, mantendo resistência a gelo de pelo menos 75.”

O último pedido exige o processo privado PoB. Consulte as condições de ativação na [referência de ferramentas](docs/tools.md).

## Escopo e limitações

Os preços do Scout são estimativas agregadas; o horário da consulta não é o horário original de observação do mercado. Um anúncio pode ser vendido antes da compra. A API web de trocas é diferente da API OAuth documentada da GGG e pode mudar ou negar acesso. O adaptador respeita limites de requisições e interrompe chamadas diante de respostas de autenticação ou desafio de acesso.

O PoB calcula a configuração ativa salva, não um personagem ao vivo. Somente combinações aprovadas nas verificações suportadas entram nas recomendações; mecânicas desconhecidas ficam como `indeterminate`. A otimização considera os candidatos retidos, não o mercado inteiro. O otimizador separado de atributos de itens não calcula PoB nem DPS do personagem.

São aceitos a tag da conta e o nome do personagem, ou um arquivo `.txt` anexado no ChatGPT. Compras automáticas e exportação de builds modificadas não estão implementadas. Teste o Docker e a compatibilidade do seu PoB no servidor de destino.

## Desenvolvimento e licença

```bash
.venv/bin/python -m pip install -e '.[test]'
.venv/bin/python -m pytest -q
.venv/bin/python scripts/check_release.py
```

Os testes com o motor real são explicitamente ignorados quando o ambiente opcional não está configurado. [Contribuição](CONTRIBUTING.md) · [Arquitetura](docs/architecture.md) · [Motor](docs/pob-engine.md) · [CI/CD](docs/releases.md) · [Segurança](SECURITY.md) · [Privacidade](docs/privacy.md).

[Licença MIT](LICENSE); consulte [NOTICE](NOTICE) para componentes de terceiros e marcas. O inglês é a referência principal. Os cinco idiomas do README foram escolhidos usando um indicador público de comunidades linguísticas, com a inclusão do coreano solicitada; não representam um ranking de países por jogadores. [Localização](docs/localization.md).

[Character integration / file attachments](docs/characters.md)

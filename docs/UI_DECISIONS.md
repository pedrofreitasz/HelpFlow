# Interface HelpFlow — decisões e referências

## Direção adotada

Interface operacional simples: navegação lateral, cabeçalho de conta, títulos claros, tabelas para comparar chamados e formulários HTML tradicionais. Verde escuro, branco e cinza; uma cor de ação e texto de alerta quando necessário. Sem gradientes decorativos, cápsulas coloridas de status, vitrines de cards ou gráficos fictícios.

O sistema é para reconhecer um problema e conduzir trabalho, não para exibir uma tecnologia. Por isso as ações usam verbos concretos: Aprovar chamado, Salvar responsável, Aceitar e iniciar, Enviar para aprovação e Sair da conta.

## Referências consultadas

- **Nielsen Norman Group:** visibilidade do estado, consistência, prevenção de erro e minimalismo orientaram feedback de envio, estado textual, ações por etapa e explicações de erro. [10 Usability Heuristics](https://www.nngroup.com/articles/ten-usability-heuristics/).
- **GOV.UK Design System:** componentes convencionais, labels explícitas, navegação e estados que não parecem botões ajudaram a definir formulários e listagens. [Components](https://design-system.service.gov.uk/components/) e [Task list](https://design-system.service.gov.uk/components/task-list/).
- **Site oficial de Lando Norris:** referência editorial para hierarquia tipográfica, poucas mensagens por seção e contraste. O site não foi copiado; uma interface de operação exige muito menos efeito visual. [Lando Norris](https://landonorris.com/).
- **NucleoTech do usuário:** leitura local de `frontend/pages/dashboard.html`, `frontend/css/main.css` e `frontend/css/dashboard.css` no repositório `C:/Users/Moysés/Documents/GitHub/nucleotech`. A inspiração ficou na navegação lateral e na hierarquia. Não foram reutilizados o backend, credenciais, dados nem os efeitos de vidro/pílulas.

Essas referências orientaram decisões; não constituem teste de usabilidade com usuários do HelpFlow nem uma afirmação sobre como os sites de referência foram produzidos.

## Aplicações concretas

- Status é texto, não botão colorido. Prazo vencido inclui palavras, não depende só de cor.
- Botão principal corresponde à ação disponível naquele estágio do chamado.
- Portal anônimo mostra apenas resumos aprovados. Dados pessoais e fotos exigem permissão.
- QR identifica empresa/local antes do login; o usuário não precisa preencher novamente o ambiente.
- Prestador só encontra as próprias demandas; gestão recebe ações de atribuição e revisão.
- Listagens têm busca/filtro, indicação de vazio e paginação. A exportação usa os mesmos filtros.
- No celular, o menu recolhe, formulários ficam em uma coluna e tabelas rolam dentro do bloco.
- Foco de teclado visível, link para pular ao conteúdo, labels associadas, mensagens com role=status, dimensões mínimas nos controles principais e preferência por redução de movimento respeitada.
- Fotos ficam protegidas e o usuário recebe prévia antes do envio. Exceções são traduzidas em mensagens compreensíveis, sem stack traces na tela.

## Limites de validação

Houve inspeção no navegador em desktop e viewport móvel, além de testes automatizados dos fluxos. Não foram realizados pesquisa com usuários, teste em aparelho físico, teste com leitor de tela nem certificação WCAG. Esses ensaios devem acompanhar o primeiro piloto.

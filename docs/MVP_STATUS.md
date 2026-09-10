# HelpFlow — entrega e pendências

Atualizado em 10/09/2026. Escopo: MVP funcional para piloto controlado; não é um produto certificado para operação em larga escala.

## O que foi feito

| Área | Implementação real |
| --- | --- |
| Tecnologia | Reescrita Flask + Jinja + HTML/CSS; JavaScript progressivo; sem React, TypeScript, Vite ou dependência de build do antigo site |
| Persistência | SQLite por padrão; SQLAlchemy, 11 tabelas de domínio e uma tabela Alembic; índices, FKs e migrações versionadas |
| PostgreSQL | Seleção por DATABASE_URL, migrações automáticas no startup, configuração Compose e transferência bidirecional de dados com verificação de contagens e sequências |
| Usuários | Cadastro, login, logout, edição de nome, alteração de senha com senha atual, recuperação com token expirável/uso único e invalidação de sessões |
| Empresas | Criação, responsável inicial, múltiplos vínculos por usuário e troca de empresa sem trocar conta |
| Equipe | Convites de colaboradores/gestores; apenas responsável pode convidar gestor; ativação/desativação e controle de permissões no servidor |
| Prestadores | Cadastro, especialidade, telefone, observações, convite, vínculo com conta própria, ativação/desativação, documentos/contratos com validade e histórico/avaliações |
| Chamados | Relato com foto opcional, categoria, prioridade, protocolo, prazo, busca, filtros e paginação |
| Gestão | Aprovar, atribuir/trocar prestador, ajustar prazo/prioridade/visibilidade, cancelar e reabrir com justificativa |
| Operação técnica | Prestador vê suas demandas; aceita/inicia, registra espera, retoma e entrega com texto e foto obrigatória; não aprova o próprio serviço |
| Encerramento | Gestor revisa a evidência, aprova com nota ou reabre; eventos e comentários preservados |
| Portal público | Resumos consultáveis sem login quando a empresa permite e a gestão libera o chamado; não expõe relato, fotos ou identidade do solicitante |
| QR Codes | Código real e aleatório por local/equipamento, download PNG, impressão A4/Salvar como PDF, copiar link, substituição/invalidação e desativação |
| Leitor QR | Câmera com início/parada explícitos, leitura de imagem local, código manual, validação da origem do link e ambiente preservado ao entrar |
| Locais | Unidade raiz e um nível de ambientes/equipamentos, edição e desativação; local desativado bloqueia novos relatos, inclusive via QR |
| Notificações | Central interna, leitura individual/todas, abertura com troca segura de contexto de empresa, fila SMTP/outbox e alertas deduplicados de atraso/documentos |
| Relatórios | Indicadores reais de pendências, atraso, revisão, tempo médio e atendimento no prazo; locais recorrentes, histórico e CSV filtrado |
| Empresa/Plano | Nome, logo, cor sóbria, SLA e portal/e-mail configuráveis; plano piloto com limite real de 50 pontos QR ativos |
| Segurança básica | Scrypt, sessão assinada HttpOnly/SameSite, CSRF, rate limiting, escape HTML, autorização por vínculo/atribuição, proteção de anexos, CSP e conflito de edição concorrente |
| Uploads | Até 5 MB por arquivo/12 MB por requisição; fotos decodificadas e regravadas sem metadados; arquivos fora da pasta pública; PDF de contrato servido para download |
| Operação | Waitress, health check, worker local embutido ou separado, backup SQLite + anexos e restauração validada em pasta nova |
| Documentação | README com execução, contas demo, SMTP, QR no celular, Docker, migrações, backup e diferenças em relação ao site antigo |

## Auditoria do protótipo e decisões da reescrita

- Persistência e trocas de perfil simuladas foram substituídas por dados reais, login e vínculos por empresa.
- Chamados, fornecedores, QR Codes e indicadores não dependem mais de arrays estáticos/localStorage.
- Os controles apresentados têm ação real: filtros, downloads, impressão, cópia, convites, status, formulários, logout e troca de empresa.
- Ações indisponíveis não fingem funcionar: a tela informa quando faltam prestador/local e o servidor recusa mudanças de estado inválidas.
- A área comercial não tem botão de cobrança simulado: a tela identifica o plano piloto e seus limites.
- Correções encontradas nos testes: expiração do CSRF em segundos; conexões do backup fechadas corretamente no Windows; anexos de requisições falhas removidos; notificações para o novo prestador após reatribuição; horários UTC convertidos para Brasília; empresa correta ao abrir uma notificação; proteção contra edições simultâneas.
- A versão TypeScript original foi preservada em sua pasta. Não há importação silenciosa de dados antigos nem publicação automática do novo Flask no endereço chatgpt.site.

## Validação executada

- SQLite: 24 testes automatizados de integração passaram na rodada-base.
- PostgreSQL 17.11 real: 23 passaram; 1 teste ignorado intencionalmente por validar backup ZIP exclusivo do SQLite.
- Transferência SQLite → PostgreSQL → SQLite: registros, contagens, IDs, sequências e hash de senha conferidos; destino não vazio recusado.
- Teste de concorrência com duas sessões SQLAlchemy: atualização antiga não sobrescreve a recente.
- PNG de QR decodificado em teste pelo mesmo jsQR usado no frontend.
- Navegador: login da gestora, logout, navegação móvel, leitura de QR por imagem, retorno ao local após login da usuária e criação de chamado confirmados.
- Interface inspecionada em desktop de 1366 px e celular de 390 px; tabelas têm rolagem horizontal interna e a página não transborda.
- A instância PostgreSQL de teste foi parada ao final e não foi registrada como serviço do Windows. A demonstração continua no SQLite.

## Para colocar um piloto com pessoas reais no ar

1. **Hospedagem Python/contêiner + HTTPS:** definir domínio, disco persistente e PUBLIC_BASE_URL; reimprimir etiquetas com a URL correta. O antigo site publicado não roda este backend.
2. **Credenciais e dados reais:** instalação limpa sem contas demo; SECRET_KEY própria, banco com usuário restrito, backups protegidos e política de retenção.
3. **SMTP:** configurar remetente/provedor e testar entrega externa, recuperação e convites; hoje o modo local grava `.eml` e não envia mensagens a ninguém.
4. **Teste de campo:** câmera e permissões em Android/iPhone, iluminação/tamanho das etiquetas e impressão física. A leitura por imagem está testada; câmera física não foi exercitada.
5. **Rotina operacional:** responsável por chamados, SLA adequado, backup periódico com ensaio de restauração e verificação dos logs/fila.
6. **Privacidade:** definir avisos, finalidade, retenção, atendimento a exclusões e regras de publicação de resumos com o responsável pelo negócio. Não há promessa de conformidade legal automática.

## Evolução após o MVP — não implementado

- Cobrança recorrente real Asaas/Stripe, webhooks, faturas, inadimplência e múltiplos planos comerciais.
- Intermediação de pagamentos a técnicos (fora do escopo original do MVP).
- WhatsApp automático, SMS ou notificações push. Compartilhar/copiar links é manual.
- SSO/MFA, confirmação de e-mail no cadastro comum e políticas corporativas de senha. Convites exigem token e conta com o e-mail convidado.
- API pública, chaves de integração, webhooks de chamados e SDK para software houses.
- Manutenção preventiva recorrente, estoque, orçamento de OS, custos/hora, agenda técnica e checklists sofisticados.
- Alteração de perfil de um vínculo existente/transferência de titularidade pela interface. O perfil é definido no convite; mudanças administrativas devem ser planejadas.
- Hierarquia de locais com profundidade arbitrária, múltiplos anexos de uma vez e edição/exclusão de documentos pela interface.
- Antivírus para PDFs, storage externo/object storage, quotas de armazenamento e limpeza periódica de anexos órfãos de falhas abruptas do processo.
- Fila distribuída com locks/backoff, múltiplos workers e limite de requisições compartilhado por Redis. O modo atual é de uma instância; limite por IP em memória reinicia com o processo.
- Auditoria imutável, rastreamento de erros externo, dashboards de infraestrutura, teste de carga, alta disponibilidade e política automatizada de recuperação de desastre.
- Migração sem parada, MySQL, importação do protótipo localStorage, testes de navegador completos em CI e auditoria formal de acessibilidade/segurança.

## Critério de conclusão do MVP

Uma pessoa identifica o local, entra e relata; a gestão recebe, atribui e acompanha; o técnico entrega evidência; a gestão aprova ou reabre; os dados permanecem após reiniciar. Esse ciclo funciona com SQLite e PostgreSQL. Configurações externas acima são necessárias para transformar a demonstração local em um piloto público.

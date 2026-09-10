# HelpFlow

MVP de gestão de manutenção reconstruído em **Python / Flask**, com HTML renderizado pelo servidor, CSS próprio e JavaScript apenas para interações e leitura de QR Codes. Não precisa de Node, npm, TypeScript ou Vite.

## Executar no Windows

Requisito: Python 3.11 ou superior (validado no 3.11).

```powershell
cd 'C:\Users\Moysés\Documents\GitHub\HelpFlow'
.\start.ps1
```

Abra <http://localhost:5000>. O script prepara o ambiente; o servidor cria/atualiza o SQLite por migrações e processa alertas em segundo plano. Para encerrar, use Ctrl+C no terminal que iniciou o servidor. Se a porta estiver ocupada, use `.\start.ps1 --port 5001` e ajuste `PUBLIC_BASE_URL` antes de gerar etiquetas.

Se a política do PowerShell impedir executar scripts, não precisa mudá-la: use os comandos equivalentes:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock.txt
.\.venv\Scripts\python.exe run.py
```

Para reiniciar depois da instalação, basta o último comando. Não há hot reload: alterações no Python/templates exigem reiniciar o servidor e recarregar o navegador.

## Demonstração

O banco local entregue já tem Edifício Aurora, Escritório Central, locais, etiquetas e chamados fictícios. A mesma senha de demonstração é `HelpFlow2026!`.

| Perfil | E-mail |
| --- | --- |
| Gestora / responsável | marina@aurora.com.br |
| Usuária / colaboradora | ana@email.com |
| Prestador de elétrica | lucas@eletrika.com.br |
| Prestador de climatização | contato@climapro.com.br |

Para preparar uma instalação nova com dados fictícios:

```powershell
$env:DEMO_PASSWORD = 'HelpFlow2026!'
.\.venv\Scripts\python.exe run.py --demo
```

O seed é explícito e idempotente; não substitui contas existentes. Nunca use os dados e senhas demo em produção. A criação de novos usuários e empresas pela interface é real.

### Roteiro de apresentação

1. Sem login, abra Edifício Aurora e consulte os resumos públicos. Textos, nomes e fotos ficam restritos.
2. Como Marina, acesse QR Codes, abra/baixe uma etiqueta ou use Imprimir etiquetas e Salvar como PDF.
3. Saia. Em Ler QR Code, selecione a imagem da etiqueta. O ambiente será identificado; entre como Ana para relatar, sem perder o local.
4. Envie um chamado com descrição e foto opcional. Ele aparece em Meus relatos e na gestão.
5. Como Marina, aprove/atribua o chamado a Lucas. Copie o link do chamado para compartilhar com o técnico.
6. Como Lucas, aceite e inicie. Registre espera se necessário e entregue com descrição e foto obrigatória.
7. Como Marina, aprove a conclusão com avaliação ou reabra com motivo. Confira indicadores, histórico e exportação CSV.
8. Em Prestadores, cadastre outra pessoa. Copie o convite; ela cria a própria conta com o e-mail convidado e aceita o vínculo. Use Trocar empresa para alternar espaços da mesma conta.

## Configuração

Copie `.env.example` para `.env` e preencha conforme necessário. O arquivo é privado e está no `.gitignore`.

| Variável | Efeito |
| --- | --- |
| `DATABASE_URL` vazia | SQLite em `instance/helpflow.db` |
| `DATABASE_URL=postgresql+psycopg://...` | PostgreSQL existente; sem alterar código |
| `SECRET_KEY` | Chave de sessão; obrigatória em produção; desenvolvimento gera `instance/.secret` |
| `PUBLIC_BASE_URL` | URL real impressa nas etiquetas, convites e e-mails |
| `APP_ENV=production` | Exige chave e ativa cookies Secure; requer HTTPS |
| `TIMEZONE` | Exibição dos horários; padrão America/Sao_Paulo; banco armazena UTC |
| `MAIL_MODE=outbox` | Salva mensagens `.eml` em `instance/outbox`; **não envia e-mail externo** |
| `MAIL_MODE=smtp` | Entrega por SMTP configurado |
| `RUN_JOBS_INLINE=true` | Um ciclo de alertas/e-mails a cada 30 segundos no processo local |
| `AUTO_MIGRATE=true` | Aplica migrações ao iniciar `run.py` |

### QR Code no celular

`localhost` no celular significa o próprio celular, não o computador. Para etiquetas de uso real, configure um domínio HTTPS acessível em `PUBLIC_BASE_URL` e reimprima as etiquetas. Para ensaio na rede local é possível iniciar com `--host 0.0.0.0` e usar o IP da máquina, respeitando as regras da sua rede; esse modo não foi ativado automaticamente.

A leitura ao vivo pelo navegador exige câmera permitida e HTTPS (ou localhost). A leitura de uma imagem e a digitação do código são alternativas. O teste automatizado decodifica o PNG com a mesma biblioteca jsQR da interface; a leitura por imagem também foi validada no navegador. A câmera física de um telefone ainda precisa ser ensaiada no ambiente de instalação.

### E-mails e notificações

A central interna funciona sem serviço externo. Convites e recuperação de senha geram mensagens reais na fila. Em modo local, abra o `.eml` em `instance/outbox` para testar o link; esses arquivos contêm links de acesso e devem ser protegidos.

Para entrega externa, configure `MAIL_MODE=smtp`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM` e `SMTP_TLS=true`. O servidor/domínio remetente precisa estar autorizado pelo seu provedor. O envio SMTP externo não foi ensaiado com uma conta real nesta entrega.

Chamados vencidos e documentos vencidos/a vencer geram alertas deduplicados. Tentativas de envio falhas ficam na fila (máximo 5 tentativas); o erro é registrado sem imprimir credenciais. O worker é simples: mantenha **uma única instância** processando a fila.

```powershell
# Processar uma vez (com RUN_JOBS_INLINE=false no servidor)
.\.venv\Scripts\python.exe -m flask --app helpflow:create_app process-jobs
# Ou manter worker separado
.\.venv\Scripts\python.exe -m flask --app helpflow:create_app worker
```

## PostgreSQL desde o início

### Com Docker Compose

Instale Docker e Docker Compose por sua distribuição oficial. Eles não estavam instalados nesta máquina. No `.env`, defina `POSTGRES_PASSWORD` e `SECRET_KEY` com valores aleatórios. Para evitar caracteres reservados na URL do Compose, gere a senha com `python -c "import secrets; print(secrets.token_hex(32))"`.

```powershell
docker compose up --build -d
```

O Compose sobe PostgreSQL 17, espera sua disponibilidade, aplica as migrações, inicia o web e um worker separado. Dados ficam nos volumes `postgres_data` e `app_data`. `docker compose down` para os serviços e preserva os volumes; **não use a opção de remover volumes** se quiser manter os dados.

O Compose é configuração de execução local; não inclui domínio/TLS nem representa uma implantação de produção pronta. A configuração foi revisada, mas o contêiner não foi executado aqui. O backend e a migração foram testados contra PostgreSQL 17.11 real, isolado, no Windows.

### Com servidor existente

Crie um banco vazio e usuário específico no PostgreSQL e configure no `.env`:

```dotenv
DATABASE_URL=postgresql+psycopg://usuario:senha_codificada@servidor:5432/helpflow
```

Inicie `run.py`. As migrações são aplicadas automaticamente; a criação do banco/usuário no servidor é uma etapa administrativa. Use TLS na conexão remota conforme o provedor (por exemplo, `?sslmode=require`). MySQL não foi incluído/testado; a alternativa implementada ao SQLite é PostgreSQL.

## Transferir dados de SQLite para PostgreSQL

Mudar somente `DATABASE_URL` **não copia dados existentes**. O script abaixo faz essa cópia, preserva IDs, corrige sequências PostgreSQL e verifica as contagens. Também suporta o caminho de volta para SQLite.

1. Pare web e worker. Faça backup. Atualize a origem para a migração atual.
2. Prepare um destino vazio. O script recusa banco com registros ou tabelas de outro sistema.
3. Configure as duas URLs e execute:

```powershell
$env:SOURCE_DATABASE_URL = 'sqlite:///C:/Users/Moysés/Documents/GitHub/HelpFlow/instance/helpflow.db'
$env:TARGET_DATABASE_URL = 'postgresql+psycopg://usuario:senha_codificada@servidor:5432/helpflow'
.\.venv\Scripts\python.exe scripts/transfer_database.py --confirm-stopped
```

4. Copie também `instance/uploads` para o novo servidor. A transferência do banco não transfere arquivos.
5. Troque `DATABASE_URL`, preserve a chave de sessão se desejar manter sessões, inicie o destino e valide login, chamados e fotos. Mantenha a origem e o backup até aceitar a migração.

É uma migração simples com janela de manutenção, não replicação/zero downtime. O script carrega uma tabela por vez em memória, adequado ao porte deste MVP. Não importa automaticamente o antigo `localStorage` do protótipo TypeScript.

## Backup e restauração

SQLite, com snapshot consistente do banco e cópia dos anexos:

```powershell
.\.venv\Scripts\python.exe -m flask --app helpflow:create_app backup 'backup-HelpFlow-2026-09-10.zip'
.\.venv\Scripts\python.exe scripts/restore_backup.py 'backup-HelpFlow-2026-09-10.zip' 'C:\Users\Moysés\Desktop\HelpFlow-restaurado'
```

Escolha nomes/destinos novos. A restauração não sobrescreve o banco atual e valida integridade/referências. Para um backup coordenado entre dados e arquivos, pause web e worker durante a operação. A chave de sessão e configurações não entram no ZIP; guarde-as separadamente.

Para testar o banco restaurado, aponte `DATABASE_URL` para o `helpflow.db` restaurado e configure `UPLOAD_FOLDER` no aplicativo para sua pasta `uploads` (ou mova a restauração para a pasta `instance` de **uma cópia nova do projeto**). Não sobrescreva uma instalação ativa.

No PostgreSQL, use `pg_dump -Fc` e restaure com `pg_restore` para um banco novo, mais a cópia de `instance/uploads`. Exercite o procedimento e a retenção no ambiente final.

## Testes e estrutura

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m flask --app helpflow:create_app db check
```

Consulte [MVP_STATUS.md](docs/MVP_STATUS.md) para entregas, evidências e pendências e [UI_DECISIONS.md](docs/UI_DECISIONS.md) para as referências de interface.

| Pasta/arquivo | Responsabilidade |
| --- | --- |
| `helpflow/models.py` | 11 tabelas de domínio; sem banco de dados fictício no navegador |
| `helpflow/auth.py` | Cadastro, login/logout, conta, convites e recuperação |
| `helpflow/views.py` | Páginas e ações das três personas |
| `helpflow/services.py` | Autorização, validação, fotos e notificações |
| `helpflow/cli.py` | Seed, fila/alertas e backup |
| `helpflow/templates/` | HTML Jinja server-rendered |
| `helpflow/static/` | CSS, JS pequeno e jsQR local com licença |
| `migrations/` | Histórico Alembic versionado |
| `tests/` | Integração e regressão em bancos reais |
| `scripts/` | Transferência, restauração e verificação opcional PostgreSQL |

`requirements.lock.txt` reproduz as versões testadas; `requirements.txt` registra faixas de atualização. O código antigo em `Desktop/QR-Resolve` foi preservado. A versão publicada anteriormente em `chatgpt.site` não foi substituída: Flask precisa de hospedagem Python/contêiner com disco persistente ou armazenamento equivalente.

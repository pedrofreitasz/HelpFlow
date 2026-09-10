# Registro de validação — 10/09/2026

## Rodada final

| Verificação | Resultado |
| --- | --- |
| `python -m pytest -q` — SQLite | 24 passaram, sem warnings |
| Mesma suíte — PostgreSQL 17.11 | 23 passaram, 1 ignorado: backup ZIP exclusivo de SQLite |
| `flask ... db check` | Nenhuma alteração de esquema sem migração |
| SQLite → PostgreSQL → SQLite | Cópia com contagens, IDs, senhas e sequências verificados |
| Destino de transferência preenchido | Recusado; dados preservados |
| Backup SQLite e restauração | ZIP criado, restaurado em pasta nova, integridade e login conferidos |
| Concorrência de edição | Duas sessões independentes; segunda gravação desatualizada recusada |
| QR PNG → jsQR | URL original decodificada corretamente |
| Navegador / QR por imagem | Etiqueta real identificou Torre A / Copa · 8º andar |
| Login após QR | Conta Ana entrou e retornou ao mesmo local |
| Criação pelo navegador | HF-80832171, explicitamente identificado como teste de apresentação |
| Layout | Desktop 1366 px e móvel 390 px; formulário, menu e conta inspecionados |
| Console do navegador no fluxo QR | Sem erros encontrados |

## Abrangência automatizada

Páginas públicas e administrativas, autenticação/CSRF, cadastro, criação/troca de empresa, isolamento de empresa, permissão de prestador, resumos públicos sem dados privados, QR inválido/desativado/substituído, limite do plano, upload de foto e rejeição de arquivo falso/oversize, idempotência de criação, etapas completas da OS, foto obrigatória na entrega, aprovação/reabertura, reatribuição, convites e desativação, documentos vencidos, configurações/logo, recuperação de senha, invalidação de sessão, outbox, notificações/deduplicação, contexto da empresa, exportação CSV sem fórmulas executáveis, escape de HTML, datas, paginação, migração e recuperação de backup.

## Como repetir PostgreSQL

A suíte aceita `TEST_POSTGRESQL_URL` apontando para uma instância **dedicada a testes**. O usuário do banco precisa criar/remover bancos: cada teste usa um banco `hf_test_<uuid>` e o remove ao terminar. Nunca aponte esse recurso a um servidor de produção.

`scripts/verify_postgres.py` é uma alternativa opcional específica do Windows. Ele usa o arquivo de binários oficiais EDB `postgresql-17.11-3-windows-x64-binaries.zip` em `work/postgresql-17.11-binaries.zip`, extrai apenas bin/lib/share, cria um cluster temporário com senha aleatória e autenticação SCRAM, ouve somente em 127.0.0.1:55439, executa a transferência e os testes, e para a instância. Não registra serviço do sistema. Fonte oficial: [EDB PostgreSQL binaries](https://www.enterprisedb.com/download-postgresql-binaries).

Os binários e bancos temporários não fazem parte do ZIP de entrega. O teste foi feito com o seed local e sua senha demonstrativa; em outra cópia, prepare os dados demo antes de repetir esse verificador.

## Não validado nesta máquina

Docker Compose em execução (Docker ausente), entrega de e-mail por SMTP externo, câmera física/qualidade de etiqueta impressa, Android/iOS reais, domínio HTTPS, carga concorrente em escala, storage remoto, acessibilidade com leitor de tela, segurança ofensiva ou auditoria de conformidade. O funcionamento da câmera não é apresentado como ensaio em aparelho físico.

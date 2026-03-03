# Hub WhatsApp RB - PEKC

Documentacao de handover do bot de consulta PEKC para vendedores, integrado com Evolution API e SQL Server.

## 1. Objetivo do projeto

Permitir que o vendedor consulte no WhatsApp, a partir do codigo do cliente RB:

- Quantos itens PEKC estao positivados.
- Quantos itens faltam.
- Quais itens faltam (`COD_PRODUTO - NOME_PRODUTO`).

Fluxo atual:

1. Vendedor envia mensagem para o numero do bot.
2. Bot responde menu de entrada.
3. Vendedor envia codigo numerico do cliente (ou `0` para sair).
4. Bot consulta a view `Rbdistrib_Trade.dbo.vw_ListaProdutosPecksKimberly`.
5. Bot retorna o resumo.

## 2. Arquitetura

Componentes:

1. Evolution API (Docker): recebe e envia mensagens WhatsApp.
2. Bot Python (FastAPI): recebe webhook, valida fluxo, consulta banco e responde.
3. SQL Server: fonte dos dados PEKC.

Fluxo tecnico:

1. WhatsApp -> Evolution (`messages.upsert`).
2. Evolution -> `POST /webhook/evolution` no bot.
3. Bot extrai telefone + texto, valida sessao e formato.
4. Bot executa query parametrizada no SQL Server.
5. Bot chama endpoint `sendText` da Evolution.
6. Evolution entrega resposta no WhatsApp.

## 3. Estrutura de arquivos

- `main.py`: webhook, estado de conversa, validacoes, mensagens.
- `database.py`: conexao SQL Server e consultas PEKC.
- `whatsapp.py`: cliente HTTP para envio de mensagem via Evolution.
- `config.py`: leitura de configuracoes JSON.
- `docker-compose.yml`: stack da Evolution API (Postgres + Redis + Evolution).
- `config_banco.json`: configuracao local de banco (sensivel, nao versionar).
- `config_bot.json`: configuracao local da Evolution e regras (sensivel, nao versionar).
- `config_banco.example.json`: modelo seguro sem credenciais.
- `config_bot.example.json`: modelo seguro sem credenciais.

## 4. Requisitos

1. Windows 10/11 ou Windows Server (recomendado para operacao 24x7).
2. Python 3.11+ (ou 3.13, ja testado).
3. Docker Desktop.
4. Driver ODBC SQL Server (`ODBC Driver 17 for SQL Server` ou superior).
5. Acesso de rede ao SQL Server e ao host do bot.

## 5. Instalacao local (do zero)

### 5.1 Clonar projeto

```powershell
git clone <URL_DO_REPOSITORIO>
cd hub_whatsapp_rb
```

### 5.2 Criar configuracoes locais

Copiar os exemplos:

```powershell
Copy-Item config_banco.example.json config_banco.json
Copy-Item config_bot.example.json config_bot.json
```

Preencher:

1. `config_banco.json`: servidor, database, usuario, senha.
2. `config_bot.json`: `base_url`, `api_key` da instancia e `instance`.

### 5.3 Subir Evolution API

```powershell
docker compose up -d
docker ps
```

### 5.4 Instalar dependencias do bot

```powershell
py -m pip install -r requirements.txt
```

### 5.5 Subir API do bot

```powershell
py -m uvicorn main:app --host 0.0.0.0 --port 3000
```

### 5.6 Health check

Abrir:

- `http://localhost:3000/health`

Resposta esperada:

```json
{"status":"ok"}
```

## 6. Configuracao da Evolution (Webhook)

Na instancia conectada:

1. Configurar webhook para `http://<IP_DO_BOT>:3000/webhook/evolution`.
2. Habilitar evento `messages.upsert`.
3. Garantir instancia `open` no `fetchInstances`.

Observacao:

- Este projeto foi testado com Evolution `v2.3.6`.

## 7. Como o bot funciona (regra de negocio)

### 7.1 Sessao

1. Primeira mensagem: envia boas-vindas.
2. Sessao expira apos 10 minutos sem interacao.
3. `0` encerra atendimento manualmente.

### 7.2 Entrada valida

- Somente codigo numerico do cliente.
- Texto nao numerico recebe mensagem de formato invalido.

### 7.3 Saida

- Cliente encontrado: nome, positivados, faltantes, lista faltante.
- Cliente nao encontrado: informa que nao esta na base PEKC.

### 7.4 Itens faltantes

Lista enviada no formato:

- `COD_PRODUTO - NOME_PRODUTO`

## 8. Seguranca e protecao contra erro

Implementado no codigo:

1. Query parametrizada (`?`) para `COD_CLIENTE`.
2. Filtro estrito: `COD_CLIENTE` deve ser numerico.
3. Validacao do nome da view (`db.schema.objeto`) para bloquear injection por configuracao.
4. Tratamento de excecao de banco (`pyodbc.Error`) com resposta amigavel.
5. Bloqueio de mensagens `fromMe` para evitar loop.
6. Ignora mensagens de grupos.

Recomendacoes adicionais:

1. Migrar credenciais de JSON para variaveis de ambiente.
2. Restringir IPs que acessam `/webhook/evolution`.
3. Ativar HTTPS no endpoint do bot em producao.
4. Adicionar auditoria de acesso por vendedor.

## 9. Validacao de vendedor ativo (anti-leak)

Campo em `config_bot.json`:

- `sql_validacao_vendedor`

Comportamento:

1. Vazio: qualquer numero consulta (modo piloto).
2. Preenchido: bot valida o telefone no SQL antes de responder.

Padrao esperado da query:

1. Receber 1 parametro (`?`) com telefone.
2. Retornar ao menos 1 linha para autorizado.

Exemplo:

```sql
SELECT 1
FROM dbo.vendedores_ativos
WHERE telefone = ? AND ativo = 1;
```

## 10. Troubleshooting rapido

### Erro `uvicorn nao reconhecido`

Use:

```powershell
py -m uvicorn main:app --host 0.0.0.0 --port 3000
```

### Webhook retorna 200 mas vendedor nao recebe

Checar:

1. `api_key` e `instance` no `config_bot.json`.
2. Se o telefone extraido no payload e o correto.
3. Se a instancia Evolution esta `open`.

### Erro SQL

Checar:

1. Driver ODBC instalado.
2. Credenciais no `config_banco.json`.
3. Rede/porta do SQL Server.
4. Permissao de leitura na view `vw_ListaProdutosPecksKimberly`.

### Cliente sempre "nao encontrado"

Checar:

1. Codigo enviado no WhatsApp.
2. Se existe `COD_CLIENTE` na view.
3. Formato do codigo no banco (numerico compativel).

## 11. Publicacao em servidor (producao)

### 11.1 Topologia recomendada

1. Servidor Windows dedicado para bot + Evolution.
2. SQL Server na rede interna da empresa.
3. Reverse proxy (Nginx/IIS) com HTTPS para webhook.

### 11.2 Passo a passo

1. Instalar Docker Desktop.
2. Instalar Python 3.11+.
3. Instalar ODBC Driver SQL.
4. Publicar codigo do projeto no servidor.
5. Preencher `config_banco.json` e `config_bot.json`.
6. Subir Evolution com `docker compose up -d`.
7. Subir bot com `py -m uvicorn ...`.
8. Configurar webhook da instancia.
9. Validar com 1 usuario piloto.
10. Habilitar servico para auto-start.

### 11.3 Rodar como servico Windows (NSSM)

Exemplo:

```powershell
nssm install hub-whatsapp-rb "C:\Windows\py.exe" "-m uvicorn main:app --host 0.0.0.0 --port 3000"
nssm set hub-whatsapp-rb AppDirectory "B:\Trade\Compartilhado\Inteligência de Mercado\Scripts\hub_whatsapp_rb"
nssm set hub-whatsapp-rb AppStdout "B:\Trade\Compartilhado\Inteligência de Mercado\Scripts\hub_whatsapp_rb\logs\output.log"
nssm set hub-whatsapp-rb AppStderr "B:\Trade\Compartilhado\Inteligência de Mercado\Scripts\hub_whatsapp_rb\logs\error.log"
nssm start hub-whatsapp-rb
```

Comandos de operacao:

```powershell
nssm status hub-whatsapp-rb
nssm restart hub-whatsapp-rb
Get-Content ".\logs\output.log" -Wait -Tail 100
```

### 11.4 Disponibilizar HTTPS

Opcoes:

1. Nginx com certificado validado.
2. IIS com URL Rewrite + certificado.

Sem HTTPS, a operacao pode falhar em cenarios externos e nao atende boas praticas.

## 12. Checklist de handover para novo analista

1. Subir localmente com `py -m uvicorn`.
2. Confirmar envio e recebimento via WhatsApp.
3. Validar consulta de cliente existente e inexistente.
4. Configurar `sql_validacao_vendedor`.
5. Configurar servico Windows e logs.
6. Executar teste de reinicio (host reboot).
7. Documentar responsavel por credenciais.

## 13. Ideias para proximos projetos

1. Menu com mais consultas (metas, pedidos, pendencias financeiras).
2. Lista de comandos (`1`, `2`, `3`) para navegar sem texto livre.
3. Cache de consulta por cliente por 1-5 minutos para reduzir carga no SQL.
4. Controle de perfil (vendedor, supervisor, gerente).
5. Auditoria completa (quem consultou qual cliente e quando).
6. Painel de monitoramento (uptime, erro, volume de mensagens).
7. Deploy em container unico (bot + supervisor) para facilitar operacao.
8. CI/CD com validacao automatica e deploy versionado.

## 14. Observacoes finais

1. Nunca versionar `config_banco.json` e `config_bot.json` reais.
2. Sempre usar os arquivos `.example` como base.
3. Antes de atualizar em producao, testar em uma instancia piloto.


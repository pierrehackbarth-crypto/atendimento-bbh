# Atendimentos com IA – Buss & Hackbarth

Módulo que grava o atendimento presencial pelo microfone, transcreve a conversa, analisa os documentos anexados (CNIS, laudos, relatórios de tempo, cartas do INSS) e gera uma ficha estruturada, com referência às fontes, para revisão do advogado. O áudio é excluído quando a transcrição foi concluída e a ficha é finalizada.

## 1. Por que é um sistema separado da página de fichas atual

O sistema de fichas que já existe é uma página estática publicada no claude.ai. Ela usa o banco de dados e os anexos da própria plataforma e **não tem servidor próprio**. Quatro limitações impedem implementar este módulo lá:

- a plataforma **não concede o microfone** às páginas;
- a página **não pode chamar serviços externos**, como a API da OpenAI;
- não existe lugar seguro para guardar uma **chave de API**: no navegador ela ficaria exposta;
- não há **tarefas em segundo plano** com retentativas.

Por isso este módulo traz o próprio backend. Ele foi feito para rodar num servidor do escritório, local ou em nuvem, com HTTPS.

## 2. Arquitetura

| Camada | Implementação |
|---|---|
| Frontend | HTML/JS sem dependências (`app/static`), servido pelo backend. Captura com `getUserMedia` + `MediaRecorder` (webm/opus a 32 kbps, partes independentes de 10 min) |
| Backend | Python 3.12 · FastAPI (`app/main.py`), endpoints autenticados |
| Autenticação | Login com senha (bcrypt), sessão em cookie `HttpOnly`/`Secure`/`SameSite=Strict`, token CSRF em toda escrita |
| Autorização | Por cliente: dono do cliente, usuários com acesso concedido ou administrador. Documentos sensíveis exigem `can_view_sensitive`. Acesso negado responde 404 (não revela existência) |
| Banco | SQLAlchemy 2 + Alembic. PostgreSQL em produção; SQLite para desenvolvimento |
| Armazenamento | Disco privado, nomes internos aleatórios, conteúdo **criptografado** (Fernet/AES-128-CBC+HMAC). Download só por endpoint autenticado, sem URL pública. Áudio em diretório separado (`STORAGE_AUDIO_DIR`), para ficar fora do backup |
| Processamento | Fila persistida na tabela `jobs` (worker com compare-and-set, espera exponencial, `dedupe_key` única), sem duplicar etapas concluídas |
| IA | SDK oficial da OpenAI, somente no servidor |

Estados do atendimento: `draft`, `recording`, `uploading`, `transcribing`, `analyzing_documents`, `generating_summary`, `awaiting_review`, `finalized` e `failed`. O áudio tem estado próprio: `none`, `stored`, `audio_deletion_pending`, `deleted` e `expired`.

## 3. Uso das APIs da OpenAI (conferido na documentação em 30/10/2026)

**Transcrição** (`POST /v1/audio/transcriptions`, multipart)
- O modelo é configurável e o padrão é `gpt-4o-transcribe`.
- **Atenção:** a documentação marca `gpt-4o-transcribe` como **descontinuado, com desligamento em 26/02/2027**, e recomenda `gpt-transcribe` para novas integrações. Basta trocar `OPENAI_TRANSCRIPTION_MODEL=gpt-transcribe`.
- Idioma: o código envia `language="pt"` aos modelos antigos e `languages=["pt"]` ao `gpt-transcribe`, conforme a documentação. Nunca envia os dois.
- Limites: arquivos de até 25 MB, nos formatos mp3, mp4, mpeg, mpga, m4a, wav e webm. Por isso a gravação é dividida em partes de 10 minutos.
- **Não** são enviados timestamps (`timestamp_granularities` só vale para `whisper-1`) nem identificação de falantes (só existe no modelo `gpt-4o-transcribe-diarize`, também descontinuado). A interface avisa que não há identificação de quem fala.
- O áudio é enviado direto na requisição, sem criar arquivo na Files API.

**Análise e ficha** (`POST /v1/responses`)
- Modelo definido por `OPENAI_ANALYSIS_MODEL`, que é obrigatório e precisa aceitar texto, imagens, PDF e Structured Outputs.
- A saída usa `text.format = {type: "json_schema", strict: true}`. O JSON é **validado de novo no servidor** (`jsonschema`), e as referências são conferidas: documento, página e segmento inexistentes são removidos e listados como aviso.
- Todas as chamadas usam `store: false`. Isso não garante ausência de retenção pelo provedor, e a interface diz isso.
- **PDF com texto:** vai só o texto por página. **PDF com páginas digitalizadas:** vai o PDF em base64 (`input_file.file_data`), e a API usa texto e imagem de cada página. **JPG/PNG:** vai como `input_image`.
- Com `OPENAI_USE_FILES_API=true`, o PDF vai por `POST /v1/files` (`purpose=user_data`). O `file_id` é registrado em `provider_files` e excluído com `DELETE /v1/files/{id}` logo após o uso. Se a exclusão falhar, há nova tentativa automática.

**Proteções**
- Áudio, transcrição e documentos vão marcados como dados não confiáveis, e o modelo é instruído a ignorar instruções contidas neles.
- Os logs registram só metadados (ação, ids, tamanhos). Chaves e conteúdo nunca vão para log.

## 4. Ficha estruturada

- O schema fica em `app/schemas.py` (`FICHA_SCHEMA`). Ele traz os campos pedidos e mais `orientacoes_advogado` e `informacoes_ausentes`.
- Cada item tem `fontes[]`, e cada fonte é um de três tipos: `documento` (com `document_id`, página e trecho), `transcricao` (com segmento T001, T002…, gerado deterministicamente pelo servidor) ou `anotacao`.
- A extração de documentos segue `DOC_EXTRACTION_SCHEMA`:
  - CNIS: vínculos e indicadores;
  - documentos médicos: data, profissional, CRM, diagnósticos e CID só quando expressos, limitações e conclusão do documento;
  - relatórios de tempo;
  - documentos administrativos: NB, DER, DIB e motivo da decisão.
- Divergências entre o relato e os documentos vão para `divergencias`, com as duas fontes.
- **Cálculo determinístico:** a soma dos vínculos do CNIS é feita pelo servidor, unindo períodos sobrepostos e mostrando método, intervalos e sobreposições. Não depende do modelo.
- **Versões preservadas:** transcrição original e revisada, todos os resultados da IA (`ai_runs`, com modelo e data), ficha revisada e ficha final.
- Reprocessar cria uma nova versão da IA, mas **nunca sobrescreve** a ficha revisada. O advogado traz da IA, seção por seção, só o que quiser.

## 5. Descarte do áudio

**Regra: transcrição concluída com sucesso + ficha finalizada pelo advogado = exclusão do áudio** (`pipeline.delete_audio`).

**O que o sistema faz ao finalizar**
1. Exige confirmação expressa na interface, que avisa que não será possível ouvir de novo nem retranscrever.
2. Grava a ficha final e confirma a persistência da transcrição e da ficha antes de excluir.
3. Exclui os segmentos do armazenamento (operação idempotente) e eventuais arquivos de áudio no provedor (nesta versão não há nenhum, porque o envio é direto).
4. Registra data e resultado na auditoria, sem conservar conteúdo.
5. O navegador descarta as referências locais ao áudio. Cada parte é liberada assim que o envio é confirmado.

**Outras situações**
- **Falha na exclusão:** o estado vira `audio_deletion_pending` e o worker tenta de novo, com espera exponencial.
- **Rascunhos:** o áudio fica no máximo `TEMP_AUDIO_TTL_HOURS`. Depois disso o worker o exclui (estado `expired`) e a interface informa que não é possível transcrever.
- **Gravação não transcrita:** a finalização é bloqueada enquanto houver parte de gravação sem transcrição.

## 6. Instalação

### Desenvolvimento (SQLite)
```bash
pip install -r requirements.txt
cp .env.example .env          # preencha OPENAI_API_KEY, OPENAI_ANALYSIS_MODEL e STORAGE_ENCRYPTION_KEY
python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"   # gera a chave
alembic upgrade head
python -m app.cli create-user advogado@hackbarth.adv.br "Nome do Advogado" advogado   # pede a senha
uvicorn app.main:app --port 8000            # com RUN_WORKER_IN_PROCESS=true o worker roda junto
```
Para usar o microfone, acesse por `http://localhost:8000` ou por **HTTPS**. O navegador bloqueia o microfone em `http` comum. Para testar sem chamar a OpenAI, defina `OPENAI_FAKE=true`.

### Produção (Docker + PostgreSQL)
```bash
cp .env.example .env    # preencher; SESSION_COOKIE_SECURE=true
POSTGRES_PASSWORD=... docker compose up -d --build
docker compose exec app python -m app.cli create-user email@... "Nome" admin
```
- Publique a porta 8000 atrás de um proxy HTTPS (Caddy ou Nginx).
- **Inclua o volume `storage` no backup e exclua o `audio_tmp`.**
- Guarde a `STORAGE_ENCRYPTION_KEY` com segurança: sem ela, os documentos não podem ser lidos.

Papéis: `admin` (tudo), `advogado` e `assistente`. Desmarque `can_view_sensitive` para quem não deve abrir documentos médicos. Para conceder acesso a um cliente, o dono do cliente usa o endpoint `POST /api/clients/{id}/access`.

## 7. Testes
```bash
python -m pytest -q tests            # 12 testes de backend (IA simulada)
node tests/e2e.js                    # navegador: precisa do servidor em OPENAI_FAKE=true e do Playwright
```

**Backend (pytest)**
- criação idempotente;
- bloqueio de outro usuário e CSRF;
- consentimento obrigatório para gravar;
- validação de anexos: extensão, MIME, assinatura, tamanho e quantidade;
- PDF textual, digitalizado, protegido por senha e corrompido;
- fluxo completo com referências e divergência;
- edição manual preservada ao reprocessar;
- exclusão do áudio, inclusive com falha e retentativa;
- ficha só com documentos;
- falha do resumo preservando as etapas anteriores;
- expiração do áudio de rascunho;
- permissão para documentos sensíveis.

**Navegador (`tests/e2e.js`, microfone simulado)**
- gravar, pausar, retomar e encerrar;
- microfone negado;
- arrastar e soltar documento e anexar pelo botão;
- anexo inválido;
- transcrever, analisar e gerar ficha;
- divergência com fontes;
- edição preservada;
- finalização com exclusão do áudio;
- bloqueio de outro usuário.

## 8. Limitações conhecidas
- Prioriza o atendimento **presencial**: o microfone não capta o áudio remoto de videoconferências.
- Sem identificação de quem fala (o modelo escolhido não oferece). As orientações do advogado são inferidas do conteúdo da conversa.
- O schema estrito não inclui datas normalizadas: datas e valores ficam **como aparecem na fonte**, por exigência do projeto.
- Integração com a página de fichas do claude.ai: a página não consegue chamar este servidor diretamente, pelo mesmo bloqueio de rede. A troca de dados precisa ser feita por exportação e importação de arquivo (JSON).
- Não testado nesta entrega: execução com PostgreSQL e Docker, e chamadas reais à OpenAI. Os testes usam SQLite e respostas simuladas.

## 9. Ficha de atendimento no servidor próprio (sem claude.ai)

A ficha de atendimento (que antes rodava só no claude.ai) agora roda neste servidor, em `/ficha/`.

- **Login:** o mesmo do sistema (e-mail e senha de cada pessoa). Sem login, a ficha manda para a tela de entrada.
- **Banco:** fichas, lixeira e base de clientes ficam nas tabelas `store_docs`/`store_versions` (PostgreSQL ou SQLite).
- **Anexos:** gravados criptografados no disco (`STORAGE_DIR`), servidos só para usuários logados.
- **IA:** resumo e leitura de documentos usam a OpenAI pelo servidor (`OPENAI_ANALYSIS_MODEL`).
- **Bibliotecas** (Word, PDF, Excel, leitura de PDF): servidas pelo próprio servidor (`app/static/ficha/vendor`), sem CDN.
- **CEP:** base local em `app/static/ficha/cep` + consulta pública ViaCEP/BrasilAPI.
- **Ainda não migrado:** busca no Tramitação Inteligente (precisa de chave de API nova guardada no servidor).
- Como funciona: `app/static/ficha-shim.js` atende os pedidos da ficha (`window.claude.use(...)`) com as rotas `/api/ficha/...` (`app/ficha_api.py`). O arquivo da ficha (`app/static/ficha/index.html`) é o mesmo do claude.ai.

Permissões: todos os usuários ativos leem e gravam as fichas; excluir definitivamente da lixeira e gravar a base de clientes só o administrador.

**Migração dos dados**
```bash
python -m app.cli import-ficha migracao/base_clientes_ficha.json.gz   # base de clientes (17.733)
python -m app.cli import-ficha fichas-backup-AAAA-MM-DD.json           # fichas: "Exportar backup" na ficha do claude.ai
```
A importação nunca apaga: só cria ou atualiza com a versão mais nova. A pasta `migracao/` contém dados pessoais de clientes: não compartilhe e apague depois da importação.

**Usuários**
```bash
python -m app.cli create-user email@bbh.adv.br "Nome" advogado     # admin | advogado | assistente
python -m app.cli set-password email@bbh.adv.br
python -m app.cli deactivate-user email@bbh.adv.br
python -m app.cli list-users
```

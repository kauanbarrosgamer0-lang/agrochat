# AgroChat IA — Deploy Guide

## Arquivos necessários
- `server.py` — servidor Flask
- `index.html` — interface web
- `requirements.txt` — dependências Python
- `Procfile` — comando de start
- `railway.json` — config Railway

## Passo a passo para hospedar no Railway

### 1. Criar conta Groq (API de IA gratuita)
1. Acesse https://console.groq.com
2. Crie uma conta gratuita
3. Vá em "API Keys" → "Create API Key"
4. Copie a chave (começa com `gsk_...`)

### 2. Criar conta GitHub
1. Acesse https://github.com e crie uma conta
2. Crie um repositório novo chamado `agrochat`
3. Faça upload de todos os arquivos desta pasta

### 3. Criar conta Railway
1. Acesse https://railway.app
2. Clique em "Start a New Project"
3. Escolha "Deploy from GitHub repo"
4. Selecione o repositório `agrochat`

### 4. Configurar variáveis de ambiente no Railway
No painel do Railway, vá em "Variables" e adicione:

| Variável | Valor |
|----------|-------|
| `GROQ_API_KEY` | sua chave Groq (gsk_...) |
| `ADMIN_EMAIL` | seu email de admin |
| `GROQ_MODEL` | llama-3.3-70b-versatile |

### 5. Deploy automático
O Railway fará o deploy automaticamente.
Acesse a URL gerada (ex: agrochat-production.up.railway.app)

## Login padrão
- Email: admin@agrochat.com (ou o ADMIN_EMAIL configurado)
- Senha: admin123

## Limites gratuitos
- Railway: 5$/mês de crédito grátis (~500h de uptime)
- Groq: 14.400 requisições/dia grátis

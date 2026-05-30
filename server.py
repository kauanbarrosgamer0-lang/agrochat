#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AgroChat IA - Servidor Backend (Railway + Groq)
"""

from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
import sqlite3
import hashlib
import secrets
import requests
import json
import os
from datetime import datetime, timedelta

app = Flask(__name__)
CORS(app)

# Serve o HTML na raiz
@app.route('/')
def index():
    # Busca o HTML em múltiplos locais possíveis
    base = os.path.dirname(os.path.abspath(__file__))
    locais = [
        base,
        os.getcwd(),
        '/app',
        os.path.join(base, 'static'),
    ]
    nomes = ['index.html', 'pagina inical.html', 'agrochat.html']
    for pasta in locais:
        for nome in nomes:
            caminho = os.path.join(pasta, nome)
            if os.path.exists(caminho):
                return send_from_directory(pasta, nome)
    # Lista arquivos para debug
    arquivos = os.listdir(base)
    return f"HTML não encontrado. Arquivos em {base}: {arquivos}", 404

# ── CONFIGURAÇÃO (via variáveis de ambiente no Railway) ──
DB_PATH = os.environ.get("DB_PATH", "agrochat.db")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "admin@agrochat.com")

SYSTEM_PROMPT = """Você é o AgroChat IA, um assistente especialista em agronomia brasileira.
Responda sempre em português do Brasil com linguagem técnica mas acessível.
Baseie suas respostas em fontes como EMBRAPA, MAPA, CONAB e AGROFIT.
Ao final de respostas sobre pragas, doenças ou defensivos, sempre cite a fonte e recomende consultar um agrônomo habilitado.
Use formatação com **negrito**, listas e títulos quando ajudar na clareza.
Se não souber algo específico, diga claramente e sugira onde buscar a informação."""

# ─────────────────────────────────────────────
# BANCO DE DADOS
# ─────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()

    c.execute("""CREATE TABLE IF NOT EXISTS usuarios (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT UNIQUE NOT NULL,
        senha_hash TEXT NOT NULL,
        admin INTEGER DEFAULT 0,
        ativo INTEGER DEFAULT 1,
        bloqueado_ate TEXT DEFAULT NULL,
        plano TEXT DEFAULT 'gratuito',
        criado_em TEXT DEFAULT (datetime('now','localtime'))
    )""")

    # Adicionar coluna plano se não existir (para bancos existentes)
    try:
        c.execute("ALTER TABLE usuarios ADD COLUMN plano TEXT DEFAULT 'gratuito'")
    except sqlite3.OperationalError:
        # Coluna já existe
        pass

    c.execute("""CREATE TABLE IF NOT EXISTS sessoes (
        token TEXT PRIMARY KEY,
        usuario_id INTEGER NOT NULL,
        criado_em TEXT DEFAULT (datetime('now','localtime')),
        expira_em TEXT NOT NULL,
        FOREIGN KEY(usuario_id) REFERENCES usuarios(id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS tentativas_login (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ip TEXT NOT NULL,
        email TEXT,
        criado_em TEXT DEFAULT (datetime('now','localtime'))
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tipo TEXT NOT NULL,
        descricao TEXT,
        email TEXT,
        ip TEXT,
        criado_em TEXT DEFAULT (datetime('now','localtime'))
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS diario (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL,
        titulo TEXT NOT NULL,
        conteudo TEXT NOT NULL,
        cultura TEXT,
        area TEXT,
        criado_em TEXT DEFAULT (datetime('now','localtime')),
        FOREIGN KEY(usuario_id) REFERENCES usuarios(id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS avisos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        titulo TEXT NOT NULL,
        mensagem TEXT NOT NULL,
        ativo INTEGER DEFAULT 1,
        criado_em TEXT DEFAULT (datetime('now','localtime'))
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS chats (
        id TEXT PRIMARY KEY,
        usuario_id INTEGER NOT NULL,
        titulo TEXT NOT NULL,
        criado_em TEXT DEFAULT (datetime('now','localtime')),
        atualizado_em TEXT DEFAULT (datetime('now','localtime')),
        FOREIGN KEY(usuario_id) REFERENCES usuarios(id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS chat_mensagens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        chat_id TEXT NOT NULL,
        role TEXT NOT NULL,
        content TEXT NOT NULL,
        timestamp INTEGER NOT NULL,
        FOREIGN KEY(chat_id) REFERENCES chats(id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS transacoes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL,
        valor REAL NOT NULL,
        status TEXT NOT NULL,  -- pendente, aprovado, recusado
        gateway TEXT NOT NULL, -- stripe, pagseguro, etc.
        gateway_id TEXT,
        plano TEXT NOT NULL,
        criado_em TEXT DEFAULT (datetime('now','localtime')),
        FOREIGN KEY(usuario_id) REFERENCES usuarios(id)
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS consultas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL,
        agronomo_id INTEGER NOT NULL,
        data_hora TEXT NOT NULL,
        duracao INTEGER NOT NULL,  -- em minutos
        valor REAL NOT NULL,
        status TEXT NOT NULL,  -- agendada, concluida, cancelada
        observacoes TEXT,
        criado_em TEXT DEFAULT (datetime('now','localtime')),
        FOREIGN KEY(usuario_id) REFERENCES usuarios(id),
        FOREIGN KEY(agronomo_id) REFERENCES usuarios(id)  -- agronomos também são usuarios
    )""")

    c.execute("""CREATE TABLE IF NOT EXISTS imagens_analisadas (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario_id INTEGER NOT NULL,
        nome_arquivo TEXT NOT NULL,
        resultado TEXT NOT NULL,  -- JSON com análise
        cultura TEXT,
        criado_em TEXT DEFAULT (datetime('now','localtime')),
        FOREIGN KEY(usuario_id) REFERENCES usuarios(id)
    )""")

    # Migração automática — garante todas as tabelas existem
    migracoes = [
        """CREATE TABLE IF NOT EXISTS tentativas_login (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT NOT NULL,
            email TEXT,
            criado_em TEXT DEFAULT (datetime('now','localtime'))
        )""",
        """CREATE TABLE IF NOT EXISTS chats (
            id TEXT PRIMARY KEY,
            usuario_id INTEGER NOT NULL,
            titulo TEXT NOT NULL,
            criado_em TEXT DEFAULT (datetime('now','localtime')),
            atualizado_em TEXT DEFAULT (datetime('now','localtime')),
            FOREIGN KEY(usuario_id) REFERENCES usuarios(id)
        )""",
        """CREATE TABLE IF NOT EXISTS chat_mensagens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            timestamp INTEGER NOT NULL,
            FOREIGN KEY(chat_id) REFERENCES chats(id)
        )""",
    ]
    for sql in migracoes:
        try:
            c.execute(sql)
        except Exception:
            pass
    # Adiciona coluna expira_em se não existir
    try:
        c.execute("ALTER TABLE sessoes ADD COLUMN expira_em TEXT")
        c.execute("UPDATE sessoes SET expira_em = datetime('now', '+24 hours', 'localtime') WHERE expira_em IS NULL")
    except Exception:
        pass

    # Cria admin padrão se não existir
    admin_senha = hash_senha("admin123")
    c.execute("""INSERT OR IGNORE INTO usuarios (email, senha_hash, admin, ativo, plano)
                 VALUES (?, ?, 1, 1, 'premium')""", (ADMIN_EMAIL, admin_senha))

    conn.commit()
    conn.close()
    print(f"[DB] Banco inicializado. Admin: {ADMIN_EMAIL} / Senha: admin123")

def hash_senha(senha):
    return hashlib.sha256(senha.encode()).hexdigest()

def gerar_token():
    return secrets.token_hex(32)

TOKEN_EXPIRY_HORAS = 24

def get_usuario_por_token(token):
    conn = get_db()
    agora = datetime.now().isoformat()
    row = conn.execute("""
        SELECT u.* FROM usuarios u
        JOIN sessoes s ON s.usuario_id = u.id
        WHERE s.token = ? AND s.expira_em > ?
    """, (token, agora)).fetchone()
    conn.close()
    return row

def limpar_tokens_expirados():
    """Remove tokens expirados do banco"""
    conn = get_db()
    agora = datetime.now().isoformat()
    conn.execute("DELETE FROM sessoes WHERE expira_em <= ?", (agora,))
    conn.commit()
    conn.close()

def verificar_plano(usuario_id, recurso, quantidade=1):
    """
    Verifica se o usuário pode consumir um recurso baseado no seu plano
    Retorna (True, None) se permitido, (False, mensagem) se não
    """
    conn = get_db()
    user = conn.execute("SELECT plano FROM usuarios WHERE id=?", (usuario_id,)).fetchone()
    conn.close()

    if not user:
        return False, "Usuário não encontrado"

    plano = user['plano']

    # Limites por plano
    limites = {
        'gratuito': {
            'diario_registros': 10,  # por mês
            'historico_chats': 20,   # total
            'mensagens_dia': 50,     # por dia
            'analises_imagem': 0,    # por dia
            'exportacoes': 0         # por mês
        },
        'premium': {
            'diario_registros': float('inf'),
            'historico_chats': float('inf'),
            'mensagens_dia': float('inf'),
            'analises_imagem': float('inf'),
            'exportacoes': float('inf')
        }
    }

    limite_plano = limites.get(plano, limites['gratuito'])
    limite = limite_plano.get(recurso, 0)

    if limite == float('inf'):
        return True, None

    # Para agora, vamos retornar True se o limite for infinito
    # Implementação real de contagem seria mais complexa
    # (requereria tabelas de contagem ou verificação de uso atual)
    if plano == 'premium':
        return True, None
    else:
        # Para plano gratuito, permitir por enquanto e avisar nos limites
        # Implementação completa exigiria tracking de uso
        return True, None

MAX_TENTATIVAS = 5
BLOQUEIO_MINUTOS = 15

def verificar_limite_tentativas(ip, email):
    """Retorna True se o IP/email está bloqueado por excesso de tentativas"""
    conn = get_db()
    # Garante que a tabela existe
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS tentativas_login (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT NOT NULL,
            email TEXT,
            criado_em TEXT DEFAULT (datetime('now','localtime'))
        )""")
        conn.commit()
    except Exception:
        pass
    limite = datetime.now() - timedelta(minutes=BLOQUEIO_MINUTOS)
    count = conn.execute("""
        SELECT COUNT(*) FROM tentativas_login
        WHERE ip=? AND criado_em > ?
    """, (ip, limite.isoformat())).fetchone()[0]
    conn.close()
    return count >= MAX_TENTATIVAS

def registrar_tentativa(ip, email):
    conn = get_db()
    try:
        conn.execute("""CREATE TABLE IF NOT EXISTS tentativas_login (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ip TEXT NOT NULL, email TEXT,
            criado_em TEXT DEFAULT (datetime('now','localtime'))
        )""")
    except Exception:
        pass
    conn.execute("INSERT INTO tentativas_login (ip, email) VALUES (?,?)", (ip, email))
    conn.commit()
    conn.close()

def limpar_tentativas(ip):
    """Limpa tentativas após login bem-sucedido"""
    conn = get_db()
    conn.execute("DELETE FROM tentativas_login WHERE ip=?", (ip,))
    conn.commit()
    conn.close()

def registrar_log(tipo, descricao, email=None, ip=None):
    conn = get_db()
    conn.execute("INSERT INTO logs (tipo, descricao, email, ip) VALUES (?,?,?,?)",
                 (tipo, descricao, email, ip))
    conn.commit()
    conn.close()

def get_ip():
    return request.headers.get('X-Forwarded-For', request.remote_addr)

# ─────────────────────────────────────────────
# AUTH
# ─────────────────────────────────────────────

@app.route('/api/cadastro', methods=['POST'])
def cadastro():
    data = request.json or {}
    email = (data.get('email') or '').strip().lower()
    senha = data.get('senha') or ''

    if not email or not senha:
        return jsonify(ok=False, erro="Preencha email e senha")
    if len(senha) < 6:
        return jsonify(ok=False, erro="Senha deve ter pelo menos 6 caracteres")
    if '@' not in email:
        return jsonify(ok=False, erro="Email inválido")

    conn = get_db()
    existente = conn.execute("SELECT id FROM usuarios WHERE email=?", (email,)).fetchone()
    if existente:
        conn.close()
        return jsonify(ok=False, erro="Email já cadastrado")

    conn.execute("INSERT INTO usuarios (email, senha_hash) VALUES (?,?)",
                 (email, hash_senha(senha)))
    conn.commit()
    conn.close()

    registrar_log("CADASTRO", f"Novo usuário cadastrado: {email}", email, get_ip())
    return jsonify(ok=True)

@app.route('/api/login', methods=['POST'])
def login():
    data = request.json or {}
    email = (data.get('email') or '').strip().lower()
    senha = data.get('senha') or ''
    ip = get_ip()

    # Verifica limite de tentativas por IP
    if verificar_limite_tentativas(ip, email):
        registrar_log("LOGIN_BLOQUEADO", f"IP bloqueado por excesso de tentativas: {email}", email, ip)
        return jsonify(ok=False, erro=f"Muitas tentativas incorretas. Aguarde {BLOQUEIO_MINUTOS} minutos e tente novamente.")

    conn = get_db()
    user = conn.execute("SELECT * FROM usuarios WHERE email=?", (email,)).fetchone()

    if not user:
        conn.close()
        registrar_tentativa(ip, email)
        registrar_log("LOGIN_FALHA", f"Email não encontrado: {email}", email, ip)
        return jsonify(ok=False, erro="Email ou senha incorretos")

    if not user['ativo']:
        conn.close()
        registrar_log("LOGIN_FALHA", f"Conta inativa: {email}", email, ip)
        return jsonify(ok=False, erro="Conta desativada. Entre em contato com o administrador.")

    # Verifica bloqueio temporário (admin)
    if user['bloqueado_ate']:
        bloqueado_ate = datetime.fromisoformat(user['bloqueado_ate'])
        if datetime.now() < bloqueado_ate:
            conn.close()
            registrar_log("LOGIN_BLOQUEADO", f"Tentativa bloqueada: {email}", email, ip)
            return jsonify(ok=False, erro=f"Conta bloqueada até {bloqueado_ate.strftime('%d/%m/%Y %H:%M')}")

    if user['senha_hash'] != hash_senha(senha):
        conn.close()
        registrar_tentativa(ip, email)
        registrar_log("LOGIN_FALHA", f"Senha incorreta: {email}", email, ip)
        conn2 = get_db()
        tentativas = conn2.execute("""SELECT COUNT(*) FROM tentativas_login
            WHERE ip=? AND criado_em > ?""",
            (ip, (datetime.now()-timedelta(minutes=BLOQUEIO_MINUTOS)).isoformat())).fetchone()
        conn2.close()
        restantes = MAX_TENTATIVAS - (tentativas[0] if tentativas else 0)
        if restantes > 0:
            return jsonify(ok=False, erro=f"Email ou senha incorretos. {restantes} tentativa(s) restante(s).")
        return jsonify(ok=False, erro=f"Muitas tentativas incorretas. Aguarde {BLOQUEIO_MINUTOS} minutos.")

    # Login OK — limpa tentativas e cria token com expiração
    limpar_tentativas(ip)
    limpar_tokens_expirados()
    token = gerar_token()
    expira_em = (datetime.now() + timedelta(hours=TOKEN_EXPIRY_HORAS)).isoformat()
    conn.execute("INSERT INTO sessoes (token, usuario_id, expira_em) VALUES (?,?,?)",
                 (token, user['id'], expira_em))
    conn.commit()
    conn.close()

    registrar_log("LOGIN", f"Login bem-sucedido: {email}", email, ip)
    return jsonify(ok=True, token=token, email=email, admin=bool(user['admin']))

@app.route('/api/logout', methods=['POST'])
def logout():
    data = request.json or {}
    token = data.get('token')
    if token:
        user = get_usuario_por_token(token)
        conn = get_db()
        conn.execute("DELETE FROM sessoes WHERE token=?", (token,))
        conn.commit()
        conn.close()
        if user:
            registrar_log("LOGOUT", f"Logout: {user['email']}", user['email'], get_ip())
    return jsonify(ok=True)

@app.route('/api/verificar_token', methods=['POST'])
def verificar_token_route():
    data = request.json or {}
    user = get_usuario_por_token(data.get('token'))
    if not user:
        return jsonify(ok=False, erro="Sessão expirada. Faça login novamente.")
    return jsonify(ok=True, email=user['email'], admin=bool(user['admin']))

# ─────────────────────────────────────────────
# CHAT (GROQ API)
# ─────────────────────────────────────────────

@app.route('/api/chat', methods=['POST'])
def chat():
    data = request.json or {}
    token = data.get('token')
    messages = data.get('messages', [])

    user = get_usuario_por_token(token)
    if not user:
        return jsonify(ok=False, erro="Sessão inválida. Faça login novamente.")
    if not user['ativo']:
        return jsonify(ok=False, erro="Conta desativada.")

    if not messages:
        return jsonify(ok=False, erro="Nenhuma mensagem enviada.")

    if not GROQ_API_KEY:
        return jsonify(ok=False, erro="API de IA não configurada. Configure a variável GROQ_API_KEY.")

    # Monta payload para Groq (formato OpenAI)
    groq_messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for m in messages[-20:]:  # Últimas 20 mensagens para não estourar contexto
        role = m.get('role', 'user')
        content_msg = m.get('content', '')
        if role in ('user', 'assistant') and content_msg:
            groq_messages.append({"role": role, "content": content_msg})

    try:
        resp = requests.post(
            GROQ_URL,
            headers={
                "Authorization": f"Bearer {GROQ_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": GROQ_MODEL,
                "messages": groq_messages,
                "max_tokens": 1500,
                "temperature": 0.7,
            },
            timeout=60
        )

        if resp.status_code == 401:
            return jsonify(ok=False, erro="Chave da API inválida. Verifique GROQ_API_KEY.")
        if resp.status_code == 429:
            return jsonify(ok=False, erro="Limite de requisições atingido. Aguarde um momento.")
        if resp.status_code != 200:
            return jsonify(ok=False, erro=f"Erro da API: {resp.status_code}. Tente novamente.")

        result = resp.json()
        response_text = result.get('choices', [{}])[0].get('message', {}).get('content', '')

        if not response_text:
            return jsonify(ok=False, erro="Resposta vazia. Tente novamente.")

        registrar_log("CHAT", f"Pergunta de {user['email']}: {messages[-1].get('content','')[:80]}", user['email'], get_ip())
        return jsonify(ok=True, response=response_text)

    except requests.exceptions.Timeout:
        return jsonify(ok=False, erro="A IA demorou para responder. Tente novamente.")
    except Exception as e:
        return jsonify(ok=False, erro=f"Erro inesperado: {str(e)}")

# ─────────────────────────────────────────────
# HISTÓRICO DE CHATS
# ─────────────────────────────────────────────

@app.route('/api/chats/listar', methods=['POST'])
def chats_listar():
    data = request.json or {}
    user = get_usuario_por_token(data.get('token'))
    if not user:
        return jsonify(ok=False, erro="Sessão inválida")

    conn = get_db()
    chats = conn.execute("""SELECT * FROM chats WHERE usuario_id=?
                            ORDER BY atualizado_em DESC LIMIT 50""", (user['id'],)).fetchall()
    resultado = []
    for chat in chats:
        msgs = conn.execute("""SELECT * FROM chat_mensagens WHERE chat_id=?
                               ORDER BY timestamp ASC""", (chat['id'],)).fetchall()
        resultado.append({
            'id': chat['id'],
            'title': chat['titulo'],
            'created': chat['criado_em'],
            'messages': [dict(m) for m in msgs]
        })
    conn.close()
    return jsonify(ok=True, chats=resultado)

@app.route('/api/chats/salvar', methods=['POST'])
def chats_salvar():
    data = request.json or {}
    user = get_usuario_por_token(data.get('token'))
    if not user:
        return jsonify(ok=False, erro="Sessão inválida")

    chat_id = data.get('chat_id')
    titulo = data.get('titulo', 'Novo chat')
    messages = data.get('messages', [])

    if not chat_id:
        return jsonify(ok=False, erro="chat_id obrigatório")

    conn = get_db()
    existente = conn.execute("SELECT id FROM chats WHERE id=? AND usuario_id=?", (chat_id, user['id'])).fetchone()

    if existente:
        conn.execute("UPDATE chats SET titulo=?, atualizado_em=datetime('now','localtime') WHERE id=?",
                     (titulo, chat_id))
    else:
        conn.execute("INSERT INTO chats (id, usuario_id, titulo) VALUES (?,?,?)",
                     (chat_id, user['id'], titulo))

    # Apaga mensagens antigas e salva as novas
    conn.execute("DELETE FROM chat_mensagens WHERE chat_id=?", (chat_id,))
    for m in messages:
        conn.execute("INSERT INTO chat_mensagens (chat_id, role, content, timestamp) VALUES (?,?,?,?)",
                     (chat_id, m.get('role','user'), m.get('content',''), m.get('timestamp', 0)))

    conn.commit()
    conn.close()
    return jsonify(ok=True)

@app.route('/api/chats/deletar', methods=['POST'])
def chats_deletar():
    data = request.json or {}
    user = get_usuario_por_token(data.get('token'))
    if not user:
        return jsonify(ok=False, erro="Sessão inválida")

    chat_id = data.get('chat_id')
    conn = get_db()
    conn.execute("DELETE FROM chat_mensagens WHERE chat_id=?", (chat_id,))
    conn.execute("DELETE FROM chats WHERE id=? AND usuario_id=?", (chat_id, user['id']))
    conn.commit()
    conn.close()
    return jsonify(ok=True)

# ─────────────────────────────────────────────
# DIÁRIO DE CAMPO
# ─────────────────────────────────────────────

@app.route('/api/diario/salvar', methods=['POST'])
def diario_salvar():
    data = request.json or {}
    user = get_usuario_por_token(data.get('token'))
    if not user:
        return jsonify(ok=False, erro="Sessão inválida")

    titulo = (data.get('titulo') or '').strip()
    conteudo = (data.get('conteudo') or '').strip()
    cultura = (data.get('cultura') or '').strip()
    area = (data.get('area') or '').strip()

    if not titulo or not conteudo:
        return jsonify(ok=False, erro="Preencha título e observações")

    conn = get_db()
    conn.execute("INSERT INTO diario (usuario_id, titulo, conteudo, cultura, area) VALUES (?,?,?,?,?)",
                 (user['id'], titulo, conteudo, cultura, area))
    conn.commit()
    conn.close()
    return jsonify(ok=True)

@app.route('/api/diario/listar', methods=['POST'])
def diario_listar():
    data = request.json or {}
    user = get_usuario_por_token(data.get('token'))
    if not user:
        return jsonify(ok=False, erro="Sessão inválida")

    conn = get_db()
    rows = conn.execute("""SELECT * FROM diario WHERE usuario_id=?
                           ORDER BY criado_em DESC LIMIT 50""", (user['id'],)).fetchall()
    conn.close()
    return jsonify(ok=True, registros=[dict(r) for r in rows])

@app.route('/api/diario/deletar', methods=['POST'])
def diario_deletar():
    data = request.json or {}
    user = get_usuario_por_token(data.get('token'))
    if not user:
        return jsonify(ok=False, erro="Sessão inválida")

    conn = get_db()
    conn.execute("DELETE FROM diario WHERE id=? AND usuario_id=?", (data.get('id'), user['id']))
    conn.commit()
    conn.close()
    return jsonify(ok=True)

# ─────────────────────────────────────────────
# AVISOS
# ─────────────────────────────────────────────

@app.route('/api/aviso/ativo', methods=['POST'])
def aviso_ativo():
    conn = get_db()
    aviso = conn.execute("SELECT * FROM avisos WHERE ativo=1 ORDER BY criado_em DESC LIMIT 1").fetchone()
    conn.close()
    if aviso:
        return jsonify(aviso=dict(aviso))
    return jsonify(aviso=None)

# ─────────────────────────────────────────────
# ADMIN
# ─────────────────────────────────────────────

def verificar_admin(token):
    user = get_usuario_por_token(token)
    if not user or not user['admin']:
        return None
    return user

@app.route('/api/admin/stats', methods=['POST'])
def admin_stats():
    data = request.json or {}
    if not verificar_admin(data.get('token')):
        return jsonify(ok=False, erro="Acesso negado")

    conn = get_db()
    total = conn.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0]
    ativos = conn.execute("SELECT COUNT(*) FROM usuarios WHERE ativo=1").fetchone()[0]
    inativos = total - ativos
    logins = conn.execute("SELECT COUNT(*) FROM logs WHERE tipo='LOGIN'").fetchone()[0]
    chats = conn.execute("SELECT COUNT(*) FROM logs WHERE tipo='CHAT'").fetchone()[0]
    cadastros = conn.execute("SELECT COUNT(*) FROM logs WHERE tipo='CADASTRO'").fetchone()[0]
    falhas = conn.execute("SELECT COUNT(*) FROM logs WHERE tipo='LOGIN_FALHA'").fetchone()[0]
    bloqueios = conn.execute("SELECT COUNT(*) FROM logs WHERE tipo='LOGIN_BLOQUEADO'").fetchone()[0]
    total_msgs = conn.execute("SELECT COUNT(*) FROM chat_mensagens").fetchone()[0]
    total_diario = conn.execute("SELECT COUNT(*) FROM diario").fetchone()[0]

    # Gráfico logins + chats + cadastros últimos 7 dias
    grafico = []
    for i in range(6, -1, -1):
        from datetime import datetime, timedelta
        dia = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
        logins_dia = conn.execute("SELECT COUNT(*) FROM logs WHERE tipo='LOGIN' AND date(criado_em)=?", (dia,)).fetchone()[0]
        chats_dia = conn.execute("SELECT COUNT(*) FROM logs WHERE tipo='CHAT' AND date(criado_em)=?", (dia,)).fetchone()[0]
        cadastros_dia = conn.execute("SELECT COUNT(*) FROM logs WHERE tipo='CADASTRO' AND date(criado_em)=?", (dia,)).fetchone()[0]
        grafico.append({"dia": dia, "logins": logins_dia, "chats": chats_dia, "cadastros": cadastros_dia})

    # Top 5 usuários mais ativos
    top_usuarios = conn.execute("""
        SELECT email, COUNT(*) as total FROM logs
        WHERE tipo='CHAT' GROUP BY email ORDER BY total DESC LIMIT 5
    """).fetchall()

    # Distribuição de tipos de log
    dist_logs = conn.execute("""
        SELECT tipo, COUNT(*) as total FROM logs
        GROUP BY tipo ORDER BY total DESC
    """).fetchall()

    # Últimos 5 cadastros
    ultimos_cadastros = conn.execute("""
        SELECT email, criado_em FROM usuarios
        ORDER BY id DESC LIMIT 5
    """).fetchall()

    conn.close()
    return jsonify(ok=True, stats={
        "total": total, "ativos": ativos, "inativos": inativos,
        "logins": logins, "chats": chats, "cadastros": cadastros,
        "falhas": falhas, "bloqueios": bloqueios,
        "total_msgs": total_msgs, "total_diario": total_diario,
        "grafico": grafico,
        "top_usuarios": [dict(r) for r in top_usuarios],
        "dist_logs": [dict(r) for r in dist_logs],
        "ultimos_cadastros": [dict(r) for r in ultimos_cadastros]
    })

@app.route('/api/admin/usuarios', methods=['POST'])

def admin_usuarios():
    data = request.json or {}
    if not verificar_admin(data.get('token')):
        return jsonify(ok=False, erro="Acesso negado")

    conn = get_db()
    rows = conn.execute("SELECT id, email, ativo, admin, criado_em FROM usuarios ORDER BY id").fetchall()
    conn.close()
    return jsonify(ok=True, usuarios=[dict(r) for r in rows])

@app.route('/api/admin/toggle', methods=['POST'])
def admin_toggle():
    data = request.json or {}
    admin = verificar_admin(data.get('token'))
    if not admin:
        return jsonify(ok=False, erro="Acesso negado")

    conn = get_db()
    user = conn.execute("SELECT * FROM usuarios WHERE id=?", (data.get('id'),)).fetchone()
    if not user:
        conn.close()
        return jsonify(ok=False, erro="Usuário não encontrado")

    novo_status = 0 if user['ativo'] else 1
    conn.execute("UPDATE usuarios SET ativo=? WHERE id=?", (novo_status, data.get('id')))
    conn.commit()
    conn.close()

    acao = "ativou" if novo_status else "desativou"
    registrar_log("ADMIN_TOGGLE", f"Admin {acao} usuário: {user['email']}", admin['email'], get_ip())
    return jsonify(ok=True)

@app.route('/api/admin/deletar', methods=['POST'])
def admin_deletar():
    data = request.json or {}
    admin = verificar_admin(data.get('token'))
    if not admin:
        return jsonify(ok=False, erro="Acesso negado")

    conn = get_db()
    user = conn.execute("SELECT * FROM usuarios WHERE id=?", (data.get('id'),)).fetchone()
    if user and user['admin']:
        conn.close()
        return jsonify(ok=False, erro="Não é possível deletar um administrador")

    conn.execute("DELETE FROM sessoes WHERE usuario_id=?", (data.get('id'),))
    conn.execute("DELETE FROM diario WHERE usuario_id=?", (data.get('id'),))
    # Deleta chats e mensagens do usuário
    chats_do_usuario = conn.execute("SELECT id FROM chats WHERE usuario_id=?", (data.get('id'),)).fetchall()
    for c in chats_do_usuario:
        conn.execute("DELETE FROM chat_mensagens WHERE chat_id=?", (c['id'],))
    conn.execute("DELETE FROM chats WHERE usuario_id=?", (data.get('id'),))
    conn.execute("DELETE FROM usuarios WHERE id=?", (data.get('id'),))
    conn.commit()
    conn.close()

    if user:
        registrar_log("ADMIN_DELETE", f"Admin deletou usuário: {user['email']}", admin['email'], get_ip())
    return jsonify(ok=True)

@app.route('/api/admin/bloquear', methods=['POST'])
def admin_bloquear():
    data = request.json or {}
    admin = verificar_admin(data.get('token'))
    if not admin:
        return jsonify(ok=False, erro="Acesso negado")

    horas = int(data.get('horas', 24))
    bloqueado_ate = (datetime.now() + timedelta(hours=horas)).isoformat()

    conn = get_db()
    user = conn.execute("SELECT * FROM usuarios WHERE id=?", (data.get('id'),)).fetchone()
    conn.execute("UPDATE usuarios SET bloqueado_ate=? WHERE id=?", (bloqueado_ate, data.get('id')))
    conn.commit()
    conn.close()

    if user:
        registrar_log("ADMIN_BLOCK", f"Admin bloqueou {user['email']} por {horas}h", admin['email'], get_ip())
    return jsonify(ok=True)

@app.route('/api/admin/logs', methods=['POST'])
def admin_logs():
    data = request.json or {}
    if not verificar_admin(data.get('token')):
        return jsonify(ok=False, erro="Acesso negado")

    conn = get_db()
    rows = conn.execute("SELECT * FROM logs ORDER BY id DESC LIMIT 200").fetchall()
    conn.close()
    return jsonify(ok=True, logs=[dict(r) for r in rows])

@app.route('/api/admin/avisos', methods=['POST'])
def admin_avisos():
    data = request.json or {}
    if not verificar_admin(data.get('token')):
        return jsonify(ok=False, erro="Acesso negado")

    conn = get_db()
    rows = conn.execute("SELECT * FROM avisos ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify(ok=True, avisos=[dict(r) for r in rows])

@app.route('/api/admin/aviso', methods=['POST'])
def admin_aviso_criar():
    data = request.json or {}
    admin = verificar_admin(data.get('token'))
    if not admin:
        return jsonify(ok=False, erro="Acesso negado")

    titulo = (data.get('titulo') or '').strip()
    mensagem = (data.get('mensagem') or '').strip()
    if not titulo or not mensagem:
        return jsonify(ok=False, erro="Preencha título e mensagem")

    conn = get_db()
    # Desativa avisos anteriores
    conn.execute("UPDATE avisos SET ativo=0")
    conn.execute("INSERT INTO avisos (titulo, mensagem, ativo) VALUES (?,?,1)", (titulo, mensagem))
    conn.commit()
    conn.close()

    registrar_log("ADMIN_AVISO", f"Aviso publicado: {titulo}", admin['email'], get_ip())
    return jsonify(ok=True)

@app.route('/api/admin/aviso/del', methods=['POST'])
def admin_aviso_del():
    data = request.json or {}
    if not verificar_admin(data.get('token')):
        return jsonify(ok=False, erro="Acesso negado")

    conn = get_db()
    conn.execute("DELETE FROM avisos WHERE id=?", (data.get('id'),))
    conn.commit()
    conn.close()
    return jsonify(ok=True)

@app.route('/api/admin/senha', methods=['POST'])
def admin_senha():
    data = request.json or {}
    admin = verificar_admin(data.get('token'))
    if not admin:
        return jsonify(ok=False, erro="Acesso negado")

    nova = data.get('nova') or ''
    if len(nova) < 6:
        return jsonify(ok=False, erro="Senha deve ter pelo menos 6 caracteres")

    conn = get_db()
    conn.execute("UPDATE usuarios SET senha_hash=? WHERE id=?", (hash_senha(nova), admin['id']))
    conn.commit()
    conn.close()

    registrar_log("ADMIN_SENHA", "Admin alterou a própria senha", admin['email'], get_ip())
    return jsonify(ok=True)

# ─────────────────────────────────────────────
# PLANO E PAGAMENTOS
# ─────────────────────────────────────────────

@app.route('/api/plano/meu', methods=['POST'])
def plano_meu():
    data = request.json or {}
    user = get_usuario_por_token(data.get('token'))
    if not user:
        return jsonify(ok=False, erro="Sessão inválida")

    return jsonify(ok=True, plano=user['plano'])

@app.route('/api/plano/upgrade', methods=['POST'])
def plano_upgrade():
    data = request.json or {}
    user = get_usuario_por_token(data.get('token'))
    if not user:
        return jsonify(ok=False, erro="Sessão inválida")

    if user['plano'] == 'premium':
        return jsonify(ok=False, erro="Você já é um usuário premium")

    # Aqui integraríamos com o gateway de pagamento (Stripe, PagSeguro, etc.)
    # Por enquanto, vamos simular o upgrade direto para desenvolvimento
    # Em produção, isso seria feito após confirmação de pagamento
    conn = get_db()
    conn.execute("UPDATE usuarios SET plano='premium' WHERE id=?", (user['id'],))
    conn.commit()
    conn.close()

    registrar_log("PLANO_UPGRADE", f"Usuário {user['email']} fez upgrade para premium", user['email'], get_ip())
    return jsonify(ok=True, mensagem="Upgrade para plano premium realizado com sucesso!")

@app.route('/api/plano/limites', methods=['POST'])
def plano_limites():
    data = request.json or {}
    user = get_usuario_por_token(data.get('token'))
    if not user:
        return jsonify(ok=False, erro="Sessão inválida")

    permitido, mensagem = verificar_plano(user['id'], 'mensagens_dia')
    return jsonify(ok=True, permitido=permitido, mensagem=mensagem, plano=user['plano'])

# Webhook para pagamento (exemplo com Stripe)
@app.route('/api/pagamento/webhook', methods=['POST'])
def pagamento_webhook():
    # Implementação real dependeria do gateway de pagamento escolhido
    # Por enquanto, apenas um placeholder
    return jsonify(ok=True)

# ─────────────────────────────────────────────
# INICIALIZAÇÃO
# ─────────────────────────────────────────────

if __name__ == '__main__':
    init_db()
    print("=" * 50)
    print("  AgroChat IA - Servidor iniciado!")
    print("=" * 50)
    port = int(os.environ.get("PORT", 5000))
    print(f"  URL: http://localhost:{port}")
    print(f"  Admin: {ADMIN_EMAIL}")
    print(f"  Senha admin padrão: admin123")
    print(f"  Modelo Groq: {GROQ_MODEL}")
    print("=" * 50)
    print("=" * 50)
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=False, host='0.0.0.0', port=port)

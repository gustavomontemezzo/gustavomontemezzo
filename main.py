"""
Sistema de Estudos - Tiago
Backend principal FastAPI + SQLite + Claude AI
"""

import sqlite3
import json
import os
import hashlib
from datetime import datetime, date
from pathlib import Path
from typing import Optional, List
from contextlib import asynccontextmanager

from pywebpush import webpush, WebPushException
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import anthropic
import aiofiles

# ─── Configuração ────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent

# Cache temporário de fotos por token (TTL 300s)
_fotos_por_token: dict = {}

# Suporte a volume persistente no Railway (/data) ou local
DATA_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR / "data")))
DB_PATH  = DATA_DIR / "sistema.db"
UPLOADS  = DATA_DIR / "uploads"
UPLOADS.mkdir(parents=True, exist_ok=True)

# VAPID: salva chave privada em arquivo temporário se vier de env var
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# ─── VAPID (Web Push) ─────────────────────────────────────────────────────────
_vapid_pem_b64 = os.environ.get("VAPID_PRIVATE_KEY_B64", "")
if _vapid_pem_b64:
    import base64, tempfile
    _pem_bytes = base64.b64decode(_vapid_pem_b64)
    _pem_file  = tempfile.NamedTemporaryFile(delete=False, suffix=".pem")
    _pem_file.write(_pem_bytes)
    _pem_file.close()
    VAPID_PRIVATE_KEY = _pem_file.name
else:
    VAPID_PRIVATE_KEY = str(BASE_DIR / "private_key.pem")

VAPID_PUBLIC_KEY  = "BEtZLw4fHHCWDLZwc61SSYgHyjHbY_GkBVUsNPpjRfSGyv9-Oovc4Ca0RbbjQLnZldrgEUV5A_2qCWAm34Ke5KI"
VAPID_CLAIMS      = {"sub": "mailto:gustavomontemezzo@hotmail.com"}

TZ_BR = pytz.timezone("America/Sao_Paulo")

# Horários dos lembretes por dia da semana (day_of_week: hora, minuto)
AGENDA_LEMBRETES = {
    "mon": (15, 0),
    "tue": (14, 0),
    "wed": (16, 0),
    "thu": (14, 0),
    "fri": (13, 30),
    "sat": (10, 0),
    "sun": (18, 0),
}

USUARIOS = ["tiago", "henrique"]

MSGS_LEMBRETE = {
    "tiago": [
        ("⚽ Hora do treino, Tiago!", "O campo está pronto. Vamos registrar a aula de hoje!"),
        ("🏆 Bora estudar, Tiago!", "Renato Gaúcho sempre escalou quem treinou mais. Sua vez!"),
        ("🔵⚫⚪ Tiago, é hora!", "Grêmio nunca desistiu. Você também não vai!"),
        ("🇧🇷 Convocação do dia!", "A Seleção te espera. Primeiro: estudar!"),
        ("🔴 You'll Never Study Alone!", "Anfield vibra com quem não para. Bora!"),
    ],
    "henrique": [
        ("⚽ Hora do treino, Henrique!", "O campo está pronto. Vamos registrar a aula de hoje!"),
        ("🏆 Bora estudar, Henrique!", "Os craques treinam todo dia. Sua vez!"),
        ("🔵⚫⚪ Henrique, é hora!", "Grêmio nunca desistiu. Você também não vai!"),
        ("🇧🇷 Convocação do dia!", "A Seleção te espera. Primeiro: estudar!"),
        ("🔴 You'll Never Study Alone!", "Anfield vibra com quem não para. Bora!"),
    ],
}

MATERIAS_POR_USUARIO = {
    "tiago": [
        "Arte", "Biologia", "Filosofia", "Física", "Geografia",
        "História", "Língua Espanhola", "Língua Inglesa",
        "Língua Portuguesa", "Literatura", "Matemática", "Química", "Sociologia", "Redação"
    ],
    "henrique": [
        "Arte", "Ciências", "Educação Digital", "Educação Física",
        "Ensino Religioso", "Filosofia", "Geografia", "História",
        "Língua Espanhola", "Língua Inglesa", "Língua Portuguesa",
        "Matemática"
    ],
}
MATERIAS = MATERIAS_POR_USUARIO["tiago"]  # fallback

TRIMESTRES = ["1º Trimestre", "2º Trimestre", "3º Trimestre"]

# ─── Banco de Dados ──────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = get_db()
    c = conn.cursor()

    c.executescript("""
    CREATE TABLE IF NOT EXISTS aulas (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario     TEXT    NOT NULL DEFAULT 'tiago',
        data        TEXT    NOT NULL,
        materia     TEXT    NOT NULL,
        trimestre   TEXT    NOT NULL,
        capitulo    TEXT,
        pagina_ini  INTEGER,
        pagina_fim  INTEGER,
        conteudo    TEXT    NOT NULL,
        fonte       TEXT    DEFAULT 'manual',
        resumo      TEXT,
        criado_em   TEXT    DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS quiz_perguntas (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario     TEXT    NOT NULL DEFAULT 'tiago',
        aula_id     INTEGER REFERENCES aulas(id),
        materia     TEXT,
        trimestre   TEXT,
        pergunta    TEXT    NOT NULL,
        alternativas TEXT   NOT NULL,
        correta     INTEGER NOT NULL,
        explicacao  TEXT,
        nivel       TEXT    DEFAULT 'medio'
    );

    CREATE TABLE IF NOT EXISTS quiz_resultados (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario     TEXT    NOT NULL DEFAULT 'tiago',
        pergunta_id INTEGER REFERENCES quiz_perguntas(id),
        resposta    INTEGER NOT NULL,
        correta     INTEGER NOT NULL,
        respondido_em TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS streaks (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario     TEXT    NOT NULL DEFAULT 'tiago',
        data        TEXT    NOT NULL,
        registros   INTEGER DEFAULT 0,
        UNIQUE(usuario, data)
    );

    CREATE TABLE IF NOT EXISTS guias_prova (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario     TEXT    NOT NULL DEFAULT 'tiago',
        materia     TEXT    NOT NULL,
        trimestre   TEXT    NOT NULL,
        topicos     TEXT    NOT NULL,
        pagina_ini  INTEGER,
        pagina_fim  INTEGER,
        guia_html   TEXT    NOT NULL,
        criado_em   TEXT    DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS push_subscriptions (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        usuario     TEXT    NOT NULL DEFAULT 'tiago',
        endpoint    TEXT    UNIQUE NOT NULL,
        p256dh      TEXT    NOT NULL,
        auth        TEXT    NOT NULL,
        dispositivo TEXT    DEFAULT 'android',
        criado_em   TEXT    DEFAULT (datetime('now','localtime'))
    );

    """)

    conn.commit()

    # Migrations
    migrations = [
        ("aulas", "pagina_ini", "INTEGER"),
        ("aulas", "pagina_fim", "INTEGER"),
        ("aulas", "usuario", "TEXT NOT NULL DEFAULT 'tiago'"),
        ("quiz_perguntas", "usuario", "TEXT NOT NULL DEFAULT 'tiago'"),
        ("quiz_resultados", "usuario", "TEXT NOT NULL DEFAULT 'tiago'"),
        ("streaks", "usuario", "TEXT NOT NULL DEFAULT 'tiago'"),
        ("guias_prova", "usuario", "TEXT NOT NULL DEFAULT 'tiago'"),
        ("push_subscriptions", "usuario", "TEXT NOT NULL DEFAULT 'tiago'"),
        ("quiz_perguntas", "tema", "TEXT DEFAULT ''"),
    ]
    for table, col, tipo in migrations:
        try:
            c.execute(f"ALTER TABLE {table} ADD COLUMN {col} {tipo}")
            conn.commit()
        except Exception:
            pass

    # Recria streaks se a constraint for UNIQUE(data) em vez de UNIQUE(usuario, data)
    indexes = [row[1] for row in c.execute("PRAGMA index_list(streaks)").fetchall()]
    unique_cols = set()
    for idx in indexes:
        info = c.execute(f"PRAGMA index_info({idx})").fetchall()
        if len(info) == 1:
            unique_cols.add(info[0][2])
    if "data" in unique_cols and "usuario" not in unique_cols:
        c.execute("ALTER TABLE streaks RENAME TO streaks_old")
        c.execute("""
            CREATE TABLE streaks (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario   TEXT    NOT NULL DEFAULT 'tiago',
                data      TEXT    NOT NULL,
                registros INTEGER DEFAULT 0,
                UNIQUE(usuario, data)
            )
        """)
        c.execute("INSERT INTO streaks (usuario, data, registros) SELECT usuario, data, registros FROM streaks_old")
        c.execute("DROP TABLE streaks_old")
        conn.commit()

    conn.close()

# ─── Lifespan ─────────────────────────────────────────────────────────────────

import random

def enviar_push_usuario(usuario: str, titulo: str, corpo: str):
    conn = get_db()
    subs = conn.execute("SELECT * FROM push_subscriptions WHERE usuario=?", (usuario,)).fetchall()
    conn.close()
    for sub in subs:
        try:
            webpush(
                subscription_info={
                    "endpoint": sub["endpoint"],
                    "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}
                },
                data=json.dumps({"title": titulo, "body": corpo}),
                vapid_private_key=VAPID_PRIVATE_KEY,
                vapid_claims=VAPID_CLAIMS,
            )
        except WebPushException:
            pass  # subscription expirada ou inválida

def enviar_push_todos(titulo: str, corpo: str):
    for u in USUARIOS:
        enviar_push_usuario(u, titulo, corpo)

def disparar_lembrete():
    for u in USUARIOS:
        titulo, corpo = random.choice(MSGS_LEMBRETE[u])
        enviar_push_usuario(u, titulo, corpo)

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()

    scheduler = AsyncIOScheduler(timezone=TZ_BR)
    for dia, (hora, minuto) in AGENDA_LEMBRETES.items():
        scheduler.add_job(
            disparar_lembrete,
            CronTrigger(day_of_week=dia, hour=hora, minute=minuto, timezone=TZ_BR),
            id=f"lembrete_{dia}",
            replace_existing=True,
        )
    scheduler.start()

    yield
    scheduler.shutdown()

# ─── App ─────────────────────────────────────────────────────────────────────

app = FastAPI(title="Sistema de Estudos - Tiago", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

# ─── Modelos ─────────────────────────────────────────────────────────────────

class AulaCreate(BaseModel):
    usuario: str = "tiago"
    data: str
    materia: str
    trimestre: str
    capitulo: Optional[str] = ""
    pagina_ini: Optional[int] = None
    pagina_fim: Optional[int] = None
    conteudo: str = ""
    fonte: str = "manual"
    fotos: Optional[list] = None
    foto_token: Optional[str] = None

class QuizResposta(BaseModel):
    usuario: str = "tiago"
    pergunta_id: int
    resposta: int

# ─── IA: Gerar Resumo + Quiz ──────────────────────────────────────────────────

PERFIS_USUARIOS = {
    "tiago": {
        "nome": "Tiago", "idade": 15, "serie": "1º ano do Ensino Médio",
        "escola": "Colégio Vicentino São José, Foz do Iguaçu - PR",
        "interesses": "Tiago torce para Grêmio, Seleção Brasileira e Liverpool."
    },
    "henrique": {
        "nome": "Henrique", "idade": 11, "serie": "6º ano do Ensino Fundamental",
        "escola": "Colégio Vicentino São José, Foz do Iguaçu - PR",
        "interesses": ""
    },
}

def gerar_resumo_e_quiz(materia: str, capitulo: str, conteudo: str, trimestre: str,
                         usuario: str = "tiago", fotos: list = None) -> dict:
    if not ANTHROPIC_API_KEY:
        return {
            "resumo": f"📚 Resumo de {materia} - {capitulo}: {conteudo[:200]}...",
            "perguntas": []
        }

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    perfil = PERFIS_USUARIOS.get(usuario, PERFIS_USUARIOS["tiago"])

    conteudo_msg = []

    # Adicionar fotos se existirem
    if fotos:
        import base64
        media_types = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp", ".gif": "image/gif"}
        for fp in fotos[:15]:
            if Path(fp).exists():
                with open(fp, "rb") as f:
                    img_data = base64.standard_b64encode(f.read()).decode("utf-8")
                ext = Path(fp).suffix.lower()
                media_type = media_types.get(ext, "image/jpeg")
                conteudo_msg.append({
                    "type": "image",
                    "source": {"type": "base64", "media_type": media_type, "data": img_data}
                })

    prompt = f"""Você é um professor criativo e exigente.
Seu aluno é {perfil['nome']}, {perfil['idade']} anos, {perfil['serie']}, {perfil['escola']}.
{perfil['interesses']}
MATÉRIA: {materia}
CAPÍTULO/TÓPICO: {capitulo}
TRIMESTRE: {trimestre}
{f"FONTE PRINCIPAL — FOTOS DO CADERNO/APOSTILA: Há {len(fotos)} foto(s) acima. Leia TODO o conteúdo visível nas imagens (textos, esquemas, tabelas, exercícios). As fotos são a base principal do resumo e do quiz." if fotos else ""}
ANOTAÇÕES DO ALUNO (complemento):
---
{conteudo[:3000] if conteudo and conteudo.strip() else "(nenhuma anotação — use apenas as fotos acima)"}
---

TAREFA:
1. Crie um RESUMO CRIATIVO (mínimo 400 palavras, máximo 600 palavras) do conteúdo.
   - Ocasionalmente (não sempre) use uma analogia com futebol quando for realmente natural e enriquecedora. Na maioria das vezes, explique o conteúdo de forma direta e clara.
   - Seja animado, use emojis com moderação.
   - Destaque os 3-4 pontos mais importantes em negrito.
   - Finalize com uma frase motivacional curta.

2. Crie EXATAMENTE 10 PERGUNTAS de múltipla escolha de nível DIFÍCIL sobre o conteúdo.
   - Nível: difícil — exija raciocínio, análise e aplicação, não apenas memorização.
   - Cada pergunta deve ter 4 alternativas (A, B, C, D)
   - OBRIGATÓRIO: distribua as respostas corretas aleatoriamente entre A, B, C e D. Não concentre respostas em nenhuma letra específica. Use todas as letras de forma equilibrada ao longo das 10 perguntas.
   - OBRIGATÓRIO: todas as alternativas devem ter tamanho similar. A resposta correta NÃO pode ser sistematicamente mais longa ou detalhada que as incorretas.
   - As alternativas incorretas devem ser plausíveis e bem elaboradas — não óbvias.
   - Forneça uma explicação detalhada da resposta correta.
   - Varie entre perguntas conceituais, de aplicação, de análise e de raciocínio crítico.

FORMATO DE RESPOSTA (JSON puro, sem markdown):
{{
  "resumo": "texto do resumo aqui",
  "perguntas": [
    {{
      "pergunta": "texto da pergunta",
      "alternativas": ["A) texto", "B) texto", "C) texto", "D) texto"],
      "correta": 0,
      "explicacao": "explicação detalhada aqui",
      "tema": "tema específico em 2-4 palavras, ex: Descobrimento do Brasil"
    }}
  ]
}}"""

    conteudo_msg.append({"type": "text", "text": prompt})

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=8000,
            messages=[{"role": "user", "content": conteudo_msg}]
        )
        raw = message.content[0].text.strip()
        # Limpar possível markdown
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        # Tentar parse direto
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # JSON truncado — extrair o que foi gerado até onde está completo
            import re
            resumo_match = re.search(r'"resumo"\s*:\s*"((?:[^"\\]|\\.)*)"', raw)
            resumo = resumo_match.group(1) if resumo_match else f"Resumo de {materia}: {conteudo[:300]}"
            # Extrair perguntas completas (que têm todos os campos)
            perguntas = []
            for m in re.finditer(r'\{[^{}]*"pergunta"[^{}]*"alternativas"[^{}]*"correta"[^{}]*"explicacao"[^{}]*\}', raw, re.DOTALL):
                try:
                    p = json.loads(m.group())
                    if isinstance(p.get("alternativas"), list) and len(p["alternativas"]) == 4:
                        perguntas.append(p)
                except Exception:
                    pass
            return {"resumo": resumo.replace('\\"', '"'), "perguntas": perguntas}
    except Exception as e:
        print(f"Erro IA: {e}")
        return {"resumo": f"Resumo de {materia}: {conteudo[:300]}", "perguntas": []}


# ─── Endpoints ───────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def root():
    return FileResponse(BASE_DIR / "static" / "index.html")

@app.get("/pais", response_class=HTMLResponse)
async def painel_pais():
    return FileResponse(BASE_DIR / "static" / "pais.html")

# --- Matérias e estrutura ---

@app.get("/api/materias")
async def listar_materias(usuario: str = "tiago"):
    materias = MATERIAS_POR_USUARIO.get(usuario, MATERIAS)
    return {"materias": materias, "trimestres": TRIMESTRES}

# --- Aulas ---

@app.post("/api/aulas")
async def criar_aula(aula: AulaCreate):
    import traceback
    usuario = aula.usuario or "tiago"
    conn = get_db()
    c = conn.cursor()

    try:
        fotos_recentes = []
        if aula.foto_token and aula.foto_token in _fotos_por_token:
            entradas = _fotos_por_token.pop(aula.foto_token)
            fotos_recentes = [str(UPLOADS / n) for n, _ in entradas if (UPLOADS / n).exists()]
        print(f"[aula] token={aula.foto_token} fotos={fotos_recentes} conteudo={len(aula.conteudo)}")

        ia_result = gerar_resumo_e_quiz(aula.materia, aula.capitulo or "", aula.conteudo, aula.trimestre, usuario, fotos_recentes)
        resumo = ia_result.get("resumo", "")
        perguntas = ia_result.get("perguntas", [])

        c.execute("""
            INSERT INTO aulas (usuario, data, materia, trimestre, capitulo, pagina_ini, pagina_fim, conteudo, fonte, resumo)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (usuario, aula.data, aula.materia, aula.trimestre, aula.capitulo, aula.pagina_ini, aula.pagina_fim, aula.conteudo, aula.fonte, resumo))
        aula_id = c.lastrowid

        for p in perguntas:
            c.execute("""
                INSERT INTO quiz_perguntas (usuario, aula_id, materia, trimestre, pergunta, alternativas, correta, explicacao, tema)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (usuario, aula_id, aula.materia, aula.trimestre, p["pergunta"],
                  json.dumps(p["alternativas"], ensure_ascii=False),
                  p["correta"], p.get("explicacao", ""), p.get("tema", "")))

        hoje = date.today().isoformat()
        existe_streak = c.execute("SELECT id FROM streaks WHERE usuario=? AND data=?", (usuario, hoje)).fetchone()
        if existe_streak:
            c.execute("UPDATE streaks SET registros = registros + 1 WHERE usuario=? AND data=?", (usuario, hoje))
        else:
            c.execute("INSERT INTO streaks (usuario, data, registros) VALUES (?, ?, 1)", (usuario, hoje))

        conn.commit()
        conn.close()

        return {
            "id": aula_id,
            "resumo": resumo,
            "total_perguntas": len(perguntas),
            "mensagem": "Aula registrada com sucesso! 🎉"
        }

    except Exception as e:
        conn.close()
        tb = traceback.format_exc()
        print(f"ERRO criar_aula: {tb}")
        raise HTTPException(status_code=500, detail=f"{str(e)} | {tb}")

@app.get("/api/aulas")
async def listar_aulas(usuario: str = "tiago", materia: Optional[str] = None, trimestre: Optional[str] = None):
    conn = get_db()
    c = conn.cursor()
    query = "SELECT * FROM aulas WHERE usuario=?"
    params = [usuario]
    if materia:
        query += " AND materia = ?"
        params.append(materia)
    if trimestre:
        query += " AND trimestre = ?"
        params.append(trimestre)
    query += " ORDER BY data DESC, criado_em DESC"
    rows = c.execute(query, params).fetchall()
    conn.close()
    return {"aulas": [dict(r) for r in rows]}

@app.get("/api/aulas/{aula_id}")
async def detalhe_aula(aula_id: int):
    conn = get_db()
    c = conn.cursor()
    aula = c.execute("SELECT * FROM aulas WHERE id=?", (aula_id,)).fetchone()
    if not aula:
        raise HTTPException(404, "Aula não encontrada")
    perguntas = c.execute("SELECT * FROM quiz_perguntas WHERE aula_id=?", (aula_id,)).fetchall()
    conn.close()
    return {
        "aula": dict(aula),
        "perguntas": [dict(p) for p in perguntas]
    }

# --- Quiz ---

@app.get("/api/quiz")
async def obter_quiz(
    usuario: str = "tiago",
    materia: Optional[str] = None,
    trimestre: Optional[str] = None,
    limite: int = 10,
    ate_data: Optional[str] = None,
    pagina_ini: Optional[int] = None,
    pagina_fim: Optional[int] = None,
):
    conn = get_db()
    c = conn.cursor()

    usar_filtro_aula = ate_data or pagina_ini or pagina_fim
    aula_query = "SELECT id FROM aulas WHERE usuario=?"
    aula_params = [usuario]
    if materia:
        aula_query += " AND materia = ?"; aula_params.append(materia)
    if trimestre:
        aula_query += " AND trimestre = ?"; aula_params.append(trimestre)
    if ate_data:
        aula_query += " AND data <= ?"; aula_params.append(ate_data)
    if pagina_ini:
        aula_query += " AND pagina_fim >= ?"; aula_params.append(pagina_ini)
    if pagina_fim:
        aula_query += " AND pagina_ini <= ?"; aula_params.append(pagina_fim)
    aula_ids = [r[0] for r in c.execute(aula_query, aula_params).fetchall()] if usar_filtro_aula else None

    query = "SELECT * FROM quiz_perguntas WHERE usuario=?"
    params = [usuario]
    if materia:
        query += " AND materia = ?"; params.append(materia)
    if trimestre:
        query += " AND trimestre = ?"; params.append(trimestre)
    if usar_filtro_aula:
        if aula_ids:
            placeholders = ",".join("?" * len(aula_ids))
            query += f" AND aula_id IN ({placeholders})"
            params.extend(aula_ids)
        else:
            conn.close()
            return {"perguntas": []}

    query += " ORDER BY RANDOM() LIMIT ?"
    params.append(limite)
    rows = c.execute(query, params).fetchall()
    conn.close()

    perguntas = []
    for r in rows:
        p = dict(r)
        p["alternativas"] = json.loads(p["alternativas"])
        perguntas.append(p)
    return {"perguntas": perguntas}

@app.get("/api/quiz/revisao")
async def quiz_revisao(usuario: str = "tiago"):
    conn = get_db()
    c = conn.cursor()
    rows = c.execute("""
        SELECT qp.* FROM quiz_perguntas qp
        LEFT JOIN (
            SELECT pergunta_id, AVG(correta) as taxa
            FROM quiz_resultados WHERE usuario=? GROUP BY pergunta_id
        ) r ON qp.id = r.pergunta_id
        WHERE qp.usuario=? AND (r.taxa IS NULL OR r.taxa < 0.6)
        ORDER BY RANDOM() LIMIT 5
    """, (usuario, usuario)).fetchall()
    conn.close()
    perguntas = []
    for r in rows:
        p = dict(r)
        p["alternativas"] = json.loads(p["alternativas"])
        perguntas.append(p)
    return {"perguntas": perguntas}

@app.post("/api/quiz/responder")
async def responder_quiz(resposta: QuizResposta):
    conn = get_db()
    c = conn.cursor()
    pergunta = c.execute("SELECT * FROM quiz_perguntas WHERE id=?", (resposta.pergunta_id,)).fetchone()
    if not pergunta:
        raise HTTPException(404, "Pergunta não encontrada")
    correta = 1 if resposta.resposta == pergunta["correta"] else 0
    c.execute("""
        INSERT INTO quiz_resultados (usuario, pergunta_id, resposta, correta)
        VALUES (?, ?, ?, ?)
    """, (resposta.usuario, resposta.pergunta_id, resposta.resposta, correta))
    conn.commit()
    conn.close()
    return {
        "correta": bool(correta),
        "resposta_certa": pergunta["correta"],
        "explicacao": pergunta["explicacao"]
    }

# --- Dashboard / Stats ---

@app.get("/api/stats")
async def estatisticas(usuario: str = "tiago"):
    conn = get_db()
    c = conn.cursor()

    total_aulas = c.execute("SELECT COUNT(*) FROM aulas WHERE usuario=?", (usuario,)).fetchone()[0]
    total_perguntas = c.execute("SELECT COUNT(*) FROM quiz_perguntas WHERE usuario=?", (usuario,)).fetchone()[0]
    total_respostas = c.execute("SELECT COUNT(*) FROM quiz_resultados WHERE usuario=?", (usuario,)).fetchone()[0]
    total_corretas = c.execute("SELECT SUM(correta) FROM quiz_resultados WHERE usuario=?", (usuario,)).fetchone()[0] or 0

    # Streak atual
    streak_atual = 0
    dia_check = date.today()
    while True:
        existe = c.execute("SELECT 1 FROM streaks WHERE usuario=? AND data=?", (usuario, dia_check.isoformat())).fetchone()
        if existe:
            streak_atual += 1
            from datetime import timedelta
            dia_check = dia_check - timedelta(days=1)
        else:
            break

    # Por matéria
    por_materia = c.execute("""
        SELECT materia, COUNT(*) as total_aulas,
               (SELECT COUNT(*) FROM quiz_perguntas qp WHERE qp.materia=a.materia AND qp.usuario=a.usuario) as perguntas
        FROM aulas a WHERE a.usuario=? GROUP BY materia ORDER BY total_aulas DESC
    """, (usuario,)).fetchall()

    # Últimas aulas
    ultimas = c.execute("""
        SELECT id, data, materia, trimestre, capitulo, resumo, criado_em
        FROM aulas WHERE usuario=? ORDER BY criado_em DESC LIMIT 5
    """, (usuario,)).fetchall()

    # Desempenho no quiz
    desempenho = c.execute("""
        SELECT qp.materia,
               COUNT(qr.id) as respostas,
               SUM(qr.correta) as corretas
        FROM quiz_resultados qr
        JOIN quiz_perguntas qp ON qr.pergunta_id = qp.id
        WHERE qr.usuario=?
        GROUP BY qp.materia
    """, (usuario,)).fetchall()

    # Dias estudados este mês
    mes_atual = date.today().strftime("%Y-%m")
    dias_mes = c.execute("SELECT COUNT(*) FROM streaks WHERE usuario=? AND data LIKE ?", (usuario, f"{mes_atual}%")).fetchone()[0]

    conn.close()

    taxa = round(total_corretas / total_respostas * 100, 1) if total_respostas > 0 else 0

    return {
        "total_aulas": total_aulas,
        "total_perguntas": total_perguntas,
        "total_respostas": total_respostas,
        "taxa_acerto": taxa,
        "streak_atual": streak_atual,
        "dias_estudados_mes": dias_mes,
        "por_materia": [dict(r) for r in por_materia],
        "ultimas_aulas": [dict(r) for r in ultimas],
        "desempenho_quiz": [dict(r) for r in desempenho]
    }

# --- Upload de imagens (caderno/apostila) ---

@app.post("/api/upload")
async def upload_imagem(file: UploadFile = File(...), token: str = Form(default="")):
    import time
    ext = Path(file.filename).suffix
    nome = f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}{ext}"
    destino = UPLOADS / nome
    async with aiofiles.open(destino, "wb") as f:
        content = await file.read()
        await f.write(content)
    if token:
        agora = time.time()
        if token not in _fotos_por_token:
            _fotos_por_token[token] = []
        _fotos_por_token[token].append((nome, agora))
        print(f"[upload] token={token} arquivo={nome}")
    return {"filename": nome, "url": f"/uploads/{nome}"}

@app.get("/uploads/{filename}")
async def servir_upload(filename: str):
    path = UPLOADS / filename
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path)

# ─── Guia de Prova ───────────────────────────────────────────────────────────

class GuiaProvaCreate(BaseModel):
    usuario: str = "tiago"
    materia: str
    trimestre: str
    topicos: str
    pagina_ini: Optional[int] = None
    pagina_fim: Optional[int] = None
    conteudo_extra: Optional[str] = ""

def gerar_guia_prova(materia: str, trimestre: str, topicos: str,
                     pagina_ini: Optional[int], pagina_fim: Optional[int],
                     conteudo_extra: str, fotos: list = None) -> str:
    if not ANTHROPIC_API_KEY:
        return "<p>API não configurada.</p>"

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    paginas_info = f"Páginas {pagina_ini} a {pagina_fim} da apostila." if pagina_ini and pagina_fim else ""

    conteudo_msg = []
    if fotos:
        import base64
        for fp in fotos[:15]:
            if Path(fp).exists():
                with open(fp, "rb") as f:
                    img_data = base64.standard_b64encode(f.read()).decode("utf-8")
                ext = Path(fp).suffix.lower()
                media_type = "image/jpeg" if ext in [".jpg", ".jpeg"] else "image/png"
                conteudo_msg.append({"type": "image", "source": {"type": "base64", "media_type": media_type, "data": img_data}})

    prompt = f"""Você é um professor especialista em criar materiais de revisão para provas do Ensino Médio.
Seu aluno é Tiago, 15 anos, 1º ano do Ensino Médio, Colégio Vicentino São José, Foz do Iguaçu - PR.
MATÉRIA: {materia}
TRIMESTRE: {trimestre}
TÓPICOS A ESTUDAR: {topicos}
{paginas_info}
{f"FONTE PRINCIPAL — FOTOS DO CADERNO/APOSTILA: Há {len(fotos)} foto(s) acima. Leia TODO o conteúdo visível nas imagens. As fotos são a base principal do guia." if fotos else ""}
{f"CONTEÚDO ADICIONAL DO ALUNO: {conteudo_extra[:2000]}" if conteudo_extra else ""}

Crie um GUIA COMPLETO DE ESTUDO PARA PROVA em HTML. O guia deve ser rico, visual e direto ao ponto.

ESTRUTURA OBRIGATÓRIA (use exatamente estas seções em HTML):

1. <div class="guia-secao destaque">
   <h3>🎯 O que mais cai nesta prova</h3>
   Lista dos 5-8 pontos mais prováveis de cair, em ordem de importância.
   </div>

2. <div class="guia-secao">
   <h3>📖 Resumo Completo por Tópico</h3>
   Para cada tópico: título em negrito, explicação clara de 3-5 linhas, exemplos quando útil.
   </div>

3. <div class="guia-secao">
   <h3>📊 Tabela Comparativa</h3>
   Quando houver 2+ elementos para comparar (pessoas, correntes, períodos, teorias):
   crie uma <table> com colunas relevantes (nome, período, principais ideias, obras/legado).
   </div>

4. <div class="guia-secao">
   <h3>⚡ Conceitos-Chave — Decore isso!</h3>
   Lista de definições curtas e precisas dos termos mais importantes.
   Formato: <strong>Termo:</strong> definição em 1-2 linhas.
   </div>

5. <div class="guia-secao alerta">
   <h3>⚠️ Pegadinhas e Confusões Comuns</h3>
   2-4 erros que os alunos costumam cometer sobre este conteúdo.
   </div>

REGRAS:
- Retorne APENAS o HTML das seções, sem <!DOCTYPE>, <html>, <head> ou <body>
- Use <strong> para termos importantes
- Use <ul><li> para listas
- Tabelas devem ter <thead> e <tbody>
- Seja completo — este é o material principal de estudo do Tiago para a prova
- Linguagem clara, direta, sem rodeios"""

    conteudo_msg.append({"type": "text", "text": prompt})
    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=8000,
            messages=[{"role": "user", "content": conteudo_msg}]
        )
        return message.content[0].text.strip()
    except Exception as e:
        print(f"Erro guia prova: {e}")
        return f"<p>Erro ao gerar guia: {e}</p>"

@app.post("/api/guia-prova")
async def criar_guia_prova(dados: GuiaProvaCreate):
    fotos_recentes = []
    try:
        agora = datetime.now().timestamp()
        fotos_recentes = [
            str(f) for f in sorted(UPLOADS.glob("*"), key=lambda f: f.stat().st_mtime, reverse=True)
            if f.is_file() and (agora - f.stat().st_mtime) < 60
            and f.suffix.lower() in [".jpg", ".jpeg", ".png", ".webp"]
        ]
    except Exception:
        pass
    guia_html = gerar_guia_prova(
        dados.materia, dados.trimestre, dados.topicos,
        dados.pagina_ini, dados.pagina_fim, dados.conteudo_extra or "", fotos_recentes
    )
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO guias_prova (usuario, materia, trimestre, topicos, pagina_ini, pagina_fim, guia_html)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (dados.usuario, dados.materia, dados.trimestre, dados.topicos,
          dados.pagina_ini, dados.pagina_fim, guia_html))
    guia_id = c.lastrowid
    conn.commit()
    conn.close()
    return {"id": guia_id, "guia_html": guia_html}

@app.get("/api/guia-prova")
async def listar_guias(usuario: str = "tiago", materia: Optional[str] = None, trimestre: Optional[str] = None):
    conn = get_db()
    c = conn.cursor()
    query = "SELECT id, materia, trimestre, topicos, pagina_ini, pagina_fim, criado_em FROM guias_prova WHERE usuario=?"
    params = [usuario]
    if materia:
        query += " AND materia = ?"
        params.append(materia)
    if trimestre:
        query += " AND trimestre = ?"
        params.append(trimestre)
    query += " ORDER BY criado_em DESC"
    rows = c.execute(query, params).fetchall()
    conn.close()
    return {"guias": [dict(r) for r in rows]}

@app.get("/api/guia-prova/{guia_id}")
async def detalhe_guia(guia_id: int):
    conn = get_db()
    c = conn.cursor()
    guia = c.execute("SELECT * FROM guias_prova WHERE id=?", (guia_id,)).fetchone()
    conn.close()
    if not guia:
        raise HTTPException(404, "Guia não encontrado")
    return dict(guia)

# ─── Push Notifications ──────────────────────────────────────────────────────

class PushSubscription(BaseModel):
    usuario: str = "tiago"
    endpoint: str
    p256dh: str
    auth: str

@app.post("/api/push/subscribe")
async def subscribe_push(sub: PushSubscription):
    conn = get_db()
    conn.execute("""
        INSERT OR REPLACE INTO push_subscriptions (usuario, endpoint, p256dh, auth)
        VALUES (?, ?, ?, ?)
    """, (sub.usuario, sub.endpoint, sub.p256dh, sub.auth))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.delete("/api/push/unsubscribe")
async def unsubscribe_push(sub: PushSubscription):
    conn = get_db()
    conn.execute("DELETE FROM push_subscriptions WHERE endpoint=?", (sub.endpoint,))
    conn.commit()
    conn.close()
    return {"ok": True}

@app.get("/api/push/vapid-public-key")
async def vapid_key():
    return {"publicKey": VAPID_PUBLIC_KEY}

@app.post("/api/push/testar")
async def testar_push():
    disparar_lembrete()
    return {"ok": True, "mensagem": "Notificação de teste enviada"}

class PushMensagem(BaseModel):
    titulo: str
    corpo: str

@app.post("/api/push/enviar")
async def enviar_notificacao_manual(msg: PushMensagem):
    enviar_push_todos(msg.titulo, msg.corpo)
    return {"ok": True}


class PushMensagemUsuario(BaseModel):
    titulo: str
    corpo: str
    usuario: str = "tiago"

@app.post("/api/push/enviar-usuario")
async def enviar_notificacao_usuario(msg: PushMensagemUsuario):
    enviar_push_usuario(msg.usuario, msg.titulo, msg.corpo)
    return {"ok": True}


@app.get("/api/debug/colunas")
async def debug_colunas():
    """Verifica colunas das tabelas no banco"""
    conn = get_db()
    c = conn.cursor()
    tabelas = {}
    for tabela in ["aulas", "quiz_perguntas", "quiz_resultados", "streaks"]:
        rows = c.execute(f"PRAGMA table_info({tabela})").fetchall()
        tabelas[tabela] = [r["name"] for r in rows]
    conn.close()
    return tabelas


# ─── Novos endpoints: Quiz do Dia, Semana, Dificuldades, Aulas do Dia ────────

@app.get("/api/aulas/dia")
async def aulas_do_dia(usuario: str = "tiago", data: Optional[str] = None):
    """Retorna aulas do dia com total de perguntas e se o quiz foi concluído."""
    if not data:
        data = date.today().isoformat()
    conn = get_db()
    c = conn.cursor()
    rows = c.execute(
        "SELECT * FROM aulas WHERE usuario=? AND data=? ORDER BY criado_em",
        (usuario, data)
    ).fetchall()

    aulas_out = []
    for a in rows:
        aula_dict = dict(a)
        total_perguntas = c.execute(
            "SELECT COUNT(*) FROM quiz_perguntas WHERE aula_id=? AND usuario=?",
            (a["id"], usuario)
        ).fetchone()[0]

        # Quiz concluído = pelo menos 8 respostas para perguntas desta aula
        pergunta_ids = [r[0] for r in c.execute(
            "SELECT id FROM quiz_perguntas WHERE aula_id=? AND usuario=?",
            (a["id"], usuario)
        ).fetchall()]
        quiz_concluido = False
        if pergunta_ids:
            placeholders = ",".join("?" * len(pergunta_ids))
            respostas = c.execute(
                f"SELECT COUNT(*) FROM quiz_resultados WHERE usuario=? AND pergunta_id IN ({placeholders})",
                [usuario] + pergunta_ids
            ).fetchone()[0]
            quiz_concluido = respostas >= 8

        aulas_out.append({
            "id": aula_dict["id"],
            "materia": aula_dict["materia"],
            "capitulo": aula_dict.get("capitulo", ""),
            "trimestre": aula_dict["trimestre"],
            "resumo": aula_dict.get("resumo", ""),
            "total_perguntas": total_perguntas,
            "quiz_concluido": quiz_concluido
        })

    conn.close()
    return {"aulas": aulas_out, "data": data}


@app.get("/api/quiz/dia")
async def quiz_do_dia(usuario: str = "tiago", aula_id: int = 0):
    """Retorna perguntas para o quiz de uma aula + revisões pendentes da mesma matéria."""
    if not aula_id:
        raise HTTPException(400, "aula_id é obrigatório")
    conn = get_db()
    c = conn.cursor()

    # Dados da aula
    aula = c.execute("SELECT * FROM aulas WHERE id=? AND usuario=?", (aula_id, usuario)).fetchone()
    if not aula:
        conn.close()
        raise HTTPException(404, "Aula não encontrada")

    materia = aula["materia"]

    # 10 perguntas da aula indicada
    rows_novas = c.execute(
        "SELECT * FROM quiz_perguntas WHERE aula_id=? AND usuario=? LIMIT 10",
        (aula_id, usuario)
    ).fetchall()
    perguntas_novas = []
    for r in rows_novas:
        p = dict(r)
        p["alternativas"] = json.loads(p["alternativas"])
        p["revisao"] = False
        perguntas_novas.append(p)

    # Perguntas de revisão: outras aulas da mesma matéria onde o último resultado foi errado
    revisao_rows = c.execute("""
        SELECT qp.* FROM quiz_perguntas qp
        WHERE qp.usuario=? AND qp.materia=? AND qp.aula_id != ?
          AND qp.id IN (
            SELECT pergunta_id FROM quiz_resultados
            WHERE usuario=? AND id IN (
              SELECT MAX(id) FROM quiz_resultados WHERE usuario=? GROUP BY pergunta_id
            ) AND correta=0
          )
        ORDER BY RANDOM() LIMIT 5
    """, (usuario, materia, aula_id, usuario, usuario)).fetchall()

    perguntas_revisao = []
    for r in revisao_rows:
        p = dict(r)
        p["alternativas"] = json.loads(p["alternativas"])
        p["revisao"] = True
        perguntas_revisao.append(p)

    conn.close()
    return {
        "aula": dict(aula),
        "perguntas": perguntas_novas + perguntas_revisao
    }


@app.get("/api/quiz/semana")
async def quiz_semana(usuario: str = "tiago"):
    """Retorna perguntas de revisão pendentes agrupadas por matéria."""
    conn = get_db()
    c = conn.cursor()

    # Perguntas cujo último resultado foi errado
    rows = c.execute("""
        SELECT qp.* FROM quiz_perguntas qp
        WHERE qp.usuario=?
          AND qp.id IN (
            SELECT pergunta_id FROM quiz_resultados
            WHERE usuario=? AND id IN (
              SELECT MAX(id) FROM quiz_resultados WHERE usuario=? GROUP BY pergunta_id
            ) AND correta=0
          )
        ORDER BY qp.materia
    """, (usuario, usuario, usuario)).fetchall()

    por_materia = {}
    for r in rows:
        p = dict(r)
        p["alternativas"] = json.loads(p["alternativas"])
        m = p["materia"] or "Sem matéria"
        if m not in por_materia:
            por_materia[m] = []
        por_materia[m].append(p)

    conn.close()
    return {
        "materias": [
            {"materia": m, "total": len(ps), "perguntas": ps}
            for m, ps in por_materia.items()
        ]
    }


@app.get("/api/dificuldades")
async def mapa_dificuldades(usuario: str = "tiago"):
    conn = get_db()
    c = conn.cursor()

    rows = c.execute("""
        SELECT
            qp.materia,
            qp.tema,
            COUNT(qr.id) as total_respondidas,
            SUM(CASE WHEN qr.correta=0 THEN 1 ELSE 0 END) as total_erros
        FROM quiz_resultados qr
        JOIN quiz_perguntas qp ON qr.pergunta_id = qp.id
        WHERE qr.usuario=? AND qp.usuario=? AND qp.tema != '' AND qp.tema IS NOT NULL
        GROUP BY qp.materia, qp.tema
        HAVING total_erros > 0
        ORDER BY qp.materia, total_erros DESC
    """, (usuario, usuario)).fetchall()

    conn.close()
    return {
        "dificuldades": [
            {
                "materia": r["materia"],
                "tema": r["tema"],
                "total_erros": r["total_erros"],
                "total_respondidas": r["total_respondidas"]
            }
            for r in rows
        ]
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

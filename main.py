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

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import anthropic
import aiofiles

# ─── Configuração ────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent

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

MSGS_LEMBRETE = [
    ("⚽ Hora do treino, Tiago!", "O campo está pronto. Vamos registrar a aula de hoje!"),
    ("🏆 Bora estudar!", "Renato Gaúcho sempre escalou quem treinou mais. Sua vez!"),
    ("🔵⚫⚪ Tiago, é hora!", "Grêmio nunca desistiu. Você também não vai!"),
    ("🇧🇷 Convocação do dia!", "A Seleção te espera. Primeiro: estudar!"),
    ("🔴 You'll Never Study Alone!", "Anfield vibra com quem não para. Bora!"),
]

MATERIAS = [
    "Arte", "Biologia", "Filosofia", "Física", "Geografia",
    "História", "Língua Espanhola", "Língua Inglesa",
    "Língua Portuguesa", "Literatura", "Matemática", "Química", "Sociologia", "Redação"
]

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
        data        TEXT    NOT NULL,
        materia     TEXT    NOT NULL,
        trimestre   TEXT    NOT NULL,
        capitulo    TEXT,
        pagina_ini  INTEGER,
        pagina_fim  INTEGER,
        conteudo    TEXT    NOT NULL,
        fonte       TEXT    DEFAULT 'manual',  -- 'manual' ou 'bernoulli'
        resumo      TEXT,
        criado_em   TEXT    DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS quiz_perguntas (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        aula_id     INTEGER REFERENCES aulas(id),
        materia     TEXT,
        trimestre   TEXT,
        pergunta    TEXT    NOT NULL,
        alternativas TEXT   NOT NULL,  -- JSON array
        correta     INTEGER NOT NULL,  -- índice 0-3
        explicacao  TEXT,
        nivel       TEXT    DEFAULT 'medio'
    );

    CREATE TABLE IF NOT EXISTS quiz_resultados (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        pergunta_id INTEGER REFERENCES quiz_perguntas(id),
        resposta    INTEGER NOT NULL,
        correta     INTEGER NOT NULL,
        respondido_em TEXT DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS streaks (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        data        TEXT    UNIQUE NOT NULL,
        registros   INTEGER DEFAULT 0
    );

    CREATE TABLE IF NOT EXISTS guias_prova (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
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
        endpoint    TEXT    UNIQUE NOT NULL,
        p256dh      TEXT    NOT NULL,
        auth        TEXT    NOT NULL,
        dispositivo TEXT    DEFAULT 'android',
        criado_em   TEXT    DEFAULT (datetime('now','localtime'))
    );

    CREATE TABLE IF NOT EXISTS bernoulli_cache (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        materia     TEXT    NOT NULL,
        capitulo    TEXT    NOT NULL,
        conteudo    TEXT,
        atualizado_em TEXT  DEFAULT (datetime('now','localtime')),
        UNIQUE(materia, capitulo)
    );
    """)

    conn.commit()

    # Migration: adicionar colunas de páginas se ainda não existem
    for col, tipo in [("pagina_ini", "INTEGER"), ("pagina_fim", "INTEGER")]:
        try:
            c.execute(f"ALTER TABLE aulas ADD COLUMN {col} {tipo}")
            conn.commit()
        except Exception:
            pass  # coluna já existe

    conn.close()

# ─── Lifespan ─────────────────────────────────────────────────────────────────

import random

def enviar_push_todos(titulo: str, corpo: str):
    conn = get_db()
    subs = conn.execute("SELECT * FROM push_subscriptions").fetchall()
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

def disparar_lembrete():
    titulo, corpo = random.choice(MSGS_LEMBRETE)
    enviar_push_todos(titulo, corpo)

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
    data: str
    materia: str
    trimestre: str
    capitulo: Optional[str] = ""
    pagina_ini: Optional[int] = None
    pagina_fim: Optional[int] = None
    conteudo: str
    fonte: str = "manual"

class QuizResposta(BaseModel):
    pergunta_id: int
    resposta: int

class BernoulliContent(BaseModel):
    materia: str
    capitulo: str
    conteudo: str

# ─── IA: Gerar Resumo + Quiz ──────────────────────────────────────────────────

def gerar_resumo_e_quiz(materia: str, capitulo: str, conteudo: str, trimestre: str) -> dict:
    if not ANTHROPIC_API_KEY:
        return {
            "resumo": f"📚 Resumo de {materia} - {capitulo}: {conteudo[:200]}...",
            "perguntas": []
        }

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    prompt = f"""Você é um professor criativo e exigente.
Seu aluno é Tiago, 15 anos, 1º ano do Ensino Médio, Colégio Vicentino São José, Foz do Iguaçu - PR.
Tiago torce para Grêmio, Seleção Brasileira e Liverpool.
Material didático: Bernoulli.

MATÉRIA: {materia}
CAPÍTULO/TÓPICO: {capitulo}
TRIMESTRE: {trimestre}
CONTEÚDO ESTUDADO:
---
{conteudo[:3000]}
---

TAREFA:
1. Crie um RESUMO CRIATIVO (máx. 200 palavras) do conteúdo.
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
      "explicacao": "explicação detalhada aqui"
    }}
  ]
}}"""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=8000,
            messages=[{"role": "user", "content": prompt}]
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
async def listar_materias():
    return {"materias": MATERIAS, "trimestres": TRIMESTRES}

# --- Aulas ---

@app.post("/api/aulas")
async def criar_aula(aula: AulaCreate):
    conn = get_db()
    c = conn.cursor()

    # Gerar resumo e quiz via IA
    ia_result = gerar_resumo_e_quiz(aula.materia, aula.capitulo or "", aula.conteudo, aula.trimestre)
    resumo = ia_result.get("resumo", "")
    perguntas = ia_result.get("perguntas", [])

    # Salvar aula
    c.execute("""
        INSERT INTO aulas (data, materia, trimestre, capitulo, pagina_ini, pagina_fim, conteudo, fonte, resumo)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (aula.data, aula.materia, aula.trimestre, aula.capitulo, aula.pagina_ini, aula.pagina_fim, aula.conteudo, aula.fonte, resumo))
    aula_id = c.lastrowid

    # Salvar perguntas
    for p in perguntas:
        c.execute("""
            INSERT INTO quiz_perguntas (aula_id, materia, trimestre, pergunta, alternativas, correta, explicacao)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (aula_id, aula.materia, aula.trimestre, p["pergunta"],
              json.dumps(p["alternativas"], ensure_ascii=False),
              p["correta"], p.get("explicacao", "")))

    # Registrar streak do dia
    hoje = date.today().isoformat()
    c.execute("""
        INSERT INTO streaks (data, registros) VALUES (?, 1)
        ON CONFLICT(data) DO UPDATE SET registros = registros + 1
    """, (hoje,))

    conn.commit()
    conn.close()

    return {
        "id": aula_id,
        "resumo": resumo,
        "total_perguntas": len(perguntas),
        "mensagem": "Aula registrada com sucesso! 🎉"
    }

@app.get("/api/aulas")
async def listar_aulas(materia: Optional[str] = None, trimestre: Optional[str] = None):
    conn = get_db()
    c = conn.cursor()
    query = "SELECT * FROM aulas WHERE 1=1"
    params = []
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
    materia: Optional[str] = None,
    trimestre: Optional[str] = None,
    limite: int = 10,
    ate_data: Optional[str] = None,
    pagina_ini: Optional[int] = None,
    pagina_fim: Optional[int] = None,
):
    """Retorna perguntas para o quiz. Filtros opcionais: data de corte e/ou intervalo de páginas."""
    conn = get_db()
    c = conn.cursor()

    usar_filtro_aula = ate_data or pagina_ini or pagina_fim

    # Buscar IDs de aulas dentro dos filtros
    aula_query = "SELECT id FROM aulas WHERE 1=1"
    aula_params = []
    if materia:
        aula_query += " AND materia = ?"
        aula_params.append(materia)
    if trimestre:
        aula_query += " AND trimestre = ?"
        aula_params.append(trimestre)
    if ate_data:
        aula_query += " AND data <= ?"
        aula_params.append(ate_data)
    if pagina_ini:
        aula_query += " AND pagina_fim >= ?"
        aula_params.append(pagina_ini)
    if pagina_fim:
        aula_query += " AND pagina_ini <= ?"
        aula_params.append(pagina_fim)
    aula_ids = [r[0] for r in c.execute(aula_query, aula_params).fetchall()] if usar_filtro_aula else None

    query = "SELECT * FROM quiz_perguntas WHERE 1=1"
    params = []
    if materia:
        query += " AND materia = ?"
        params.append(materia)
    if trimestre:
        query += " AND trimestre = ?"
        params.append(trimestre)
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
async def quiz_revisao():
    """Perguntas para revisão espaçada — erradas ou antigas"""
    conn = get_db()
    c = conn.cursor()
    # Perguntas erradas nos últimos 7 dias ou nunca respondidas
    rows = c.execute("""
        SELECT qp.* FROM quiz_perguntas qp
        LEFT JOIN (
            SELECT pergunta_id, MAX(respondido_em) as ultima, AVG(correta) as taxa
            FROM quiz_resultados GROUP BY pergunta_id
        ) r ON qp.id = r.pergunta_id
        WHERE r.taxa IS NULL OR r.taxa < 0.6
        ORDER BY RANDOM() LIMIT 5
    """).fetchall()
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
        INSERT INTO quiz_resultados (pergunta_id, resposta, correta)
        VALUES (?, ?, ?)
    """, (resposta.pergunta_id, resposta.resposta, correta))
    conn.commit()
    conn.close()
    return {
        "correta": bool(correta),
        "resposta_certa": pergunta["correta"],
        "explicacao": pergunta["explicacao"]
    }

# --- Dashboard / Stats ---

@app.get("/api/stats")
async def estatisticas():
    conn = get_db()
    c = conn.cursor()

    total_aulas = c.execute("SELECT COUNT(*) FROM aulas").fetchone()[0]
    total_perguntas = c.execute("SELECT COUNT(*) FROM quiz_perguntas").fetchone()[0]
    total_respostas = c.execute("SELECT COUNT(*) FROM quiz_resultados").fetchone()[0]
    total_corretas = c.execute("SELECT SUM(correta) FROM quiz_resultados").fetchone()[0] or 0

    # Streak atual
    hoje = date.today().isoformat()
    streak_atual = 0
    dia_check = date.today()
    while True:
        existe = c.execute("SELECT 1 FROM streaks WHERE data=?", (dia_check.isoformat(),)).fetchone()
        if existe:
            streak_atual += 1
            from datetime import timedelta
            dia_check = dia_check - timedelta(days=1)
        else:
            break

    # Por matéria
    por_materia = c.execute("""
        SELECT materia, COUNT(*) as total_aulas,
               (SELECT COUNT(*) FROM quiz_perguntas qp WHERE qp.materia=a.materia) as perguntas
        FROM aulas a GROUP BY materia ORDER BY total_aulas DESC
    """).fetchall()

    # Últimas aulas
    ultimas = c.execute("""
        SELECT id, data, materia, trimestre, capitulo, resumo, criado_em
        FROM aulas ORDER BY criado_em DESC LIMIT 5
    """).fetchall()

    # Desempenho no quiz
    desempenho = c.execute("""
        SELECT qp.materia,
               COUNT(qr.id) as respostas,
               SUM(qr.correta) as corretas
        FROM quiz_resultados qr
        JOIN quiz_perguntas qp ON qr.pergunta_id = qp.id
        GROUP BY qp.materia
    """).fetchall()

    # Dias estudados este mês
    mes_atual = date.today().strftime("%Y-%m")
    dias_mes = c.execute("SELECT COUNT(*) FROM streaks WHERE data LIKE ?", (f"{mes_atual}%",)).fetchone()[0]

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
async def upload_imagem(file: UploadFile = File(...)):
    ext = Path(file.filename).suffix
    nome = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}{ext}"
    destino = UPLOADS / nome
    async with aiofiles.open(destino, "wb") as f:
        content = await file.read()
        await f.write(content)
    return {"filename": nome, "url": f"/uploads/{nome}"}

@app.get("/uploads/{filename}")
async def servir_upload(filename: str):
    path = UPLOADS / filename
    if not path.exists():
        raise HTTPException(404)
    return FileResponse(path)

# --- Bernoulli (conteúdo capturado pelo agente) ---

@app.post("/api/bernoulli/conteudo")
async def salvar_bernoulli(content: BernoulliContent):
    conn = get_db()
    c = conn.cursor()

    # Verificar se é conteúdo novo (não existia antes)
    existente = c.execute(
        "SELECT id FROM bernoulli_cache WHERE materia=? AND capitulo=?",
        (content.materia, content.capitulo)
    ).fetchone()
    eh_novo = existente is None

    c.execute("""
        INSERT INTO bernoulli_cache (materia, capitulo, conteudo)
        VALUES (?, ?, ?)
        ON CONFLICT(materia, capitulo) DO UPDATE SET
            conteudo = excluded.conteudo,
            atualizado_em = datetime('now','localtime')
    """, (content.materia, content.capitulo, content.conteudo))
    conn.commit()
    conn.close()

    # Notificar Tiago se for conteúdo novo
    if eh_novo:
        enviar_push_todos(
            "📚 Novo material disponível!",
            f"Bernoulli adicionou conteúdo novo: {content.materia} — {content.capitulo}"
        )

    return {"ok": True, "novo": eh_novo}

@app.get("/api/bernoulli/conteudo")
async def listar_bernoulli(materia: Optional[str] = None):
    conn = get_db()
    c = conn.cursor()
    if materia:
        rows = c.execute("SELECT * FROM bernoulli_cache WHERE materia=? ORDER BY atualizado_em DESC", (materia,)).fetchall()
    else:
        rows = c.execute("SELECT materia, capitulo, atualizado_em FROM bernoulli_cache ORDER BY materia, capitulo").fetchall()
    conn.close()
    return {"conteudos": [dict(r) for r in rows]}

# ─── Guia de Prova ───────────────────────────────────────────────────────────

class GuiaProvaCreate(BaseModel):
    materia: str
    trimestre: str
    topicos: str
    pagina_ini: Optional[int] = None
    pagina_fim: Optional[int] = None
    conteudo_extra: Optional[str] = ""

def gerar_guia_prova(materia: str, trimestre: str, topicos: str,
                     pagina_ini: Optional[int], pagina_fim: Optional[int],
                     conteudo_extra: str) -> str:
    if not ANTHROPIC_API_KEY:
        return "<p>API não configurada.</p>"

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    paginas_info = f"Páginas {pagina_ini} a {pagina_fim} da apostila." if pagina_ini and pagina_fim else ""

    prompt = f"""Você é um professor especialista em criar materiais de revisão para provas do Ensino Médio.
Seu aluno é Tiago, 15 anos, 1º ano do Ensino Médio, Colégio Vicentino São José, Foz do Iguaçu - PR.
Material didático: Bernoulli.

MATÉRIA: {materia}
TRIMESTRE: {trimestre}
TÓPICOS A ESTUDAR: {topicos}
{paginas_info}
{f"CONTEÚDO ADICIONAL: {conteudo_extra[:2000]}" if conteudo_extra else ""}

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

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=8000,
            messages=[{"role": "user", "content": prompt}]
        )
        return message.content[0].text.strip()
    except Exception as e:
        print(f"Erro guia prova: {e}")
        return f"<p>Erro ao gerar guia: {e}</p>"

@app.post("/api/guia-prova")
async def criar_guia_prova(dados: GuiaProvaCreate):
    guia_html = gerar_guia_prova(
        dados.materia, dados.trimestre, dados.topicos,
        dados.pagina_ini, dados.pagina_fim, dados.conteudo_extra or ""
    )
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        INSERT INTO guias_prova (materia, trimestre, topicos, pagina_ini, pagina_fim, guia_html)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (dados.materia, dados.trimestre, dados.topicos,
          dados.pagina_ini, dados.pagina_fim, guia_html))
    guia_id = c.lastrowid
    conn.commit()
    conn.close()
    return {"id": guia_id, "guia_html": guia_html}

@app.get("/api/guia-prova")
async def listar_guias(materia: Optional[str] = None, trimestre: Optional[str] = None):
    conn = get_db()
    c = conn.cursor()
    query = "SELECT id, materia, trimestre, topicos, pagina_ini, pagina_fim, criado_em FROM guias_prova WHERE 1=1"
    params = []
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
    endpoint: str
    p256dh: str
    auth: str

@app.post("/api/push/subscribe")
async def subscribe_push(sub: PushSubscription):
    conn = get_db()
    conn.execute("""
        INSERT OR REPLACE INTO push_subscriptions (endpoint, p256dh, auth)
        VALUES (?, ?, ?)
    """, (sub.endpoint, sub.p256dh, sub.auth))
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

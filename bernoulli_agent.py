#!/usr/bin/env python3
"""
Agente Automático Bernoulli — Sistema de Estudos do Tiago
=========================================================
Navega o app Meu Bernoulli 4.0 automaticamente usando Claude AI + computer use.
Extrai conteúdo dos e-books, tarefas e avisos, e alimenta o sistema de estudos.

REQUISITOS (configurar uma vez):
  1. Terminal com Screen Recording:
     Ajustes do Sistema > Privacidade > Gravação de Tela > adicionar Terminal
  2. Terminal com Acessibilidade:
     Ajustes do Sistema > Privacidade > Acessibilidade > adicionar Terminal
  3. Chave Anthropic em ~/sistema-tiago/.env

USO:
  python3 ~/sistema-tiago/bernoulli_agent.py
  python3 ~/sistema-tiago/bernoulli_agent.py --materia Biologia
  python3 ~/sistema-tiago/bernoulli_agent.py --feed-only
"""

import os
import sys
import time
import json
import base64
import subprocess
import argparse
import requests
import tempfile
from datetime import datetime
from pathlib import Path
from anthropic import Anthropic

# ─── Configuração ────────────────────────────────────────────────────────────

BASE_DIR   = Path(__file__).parent
ENV_FILE   = BASE_DIR / ".env"
LOG_FILE   = BASE_DIR / "data" / "agente.log"
API_LOCAL  = "http://localhost:8000"

# Carregar .env
if ENV_FILE.exists():
    for line in ENV_FILE.read_text().splitlines():
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

# Matérias a extrair (pode filtrar por argumento)
MATERIAS_ALVO = [
    "Biologia", "Física", "Matemática", "Química",
    "História", "Geografia", "Língua Portuguesa",
    "Língua Inglesa", "Língua Espanhola",
    "Filosofia", "Sociologia", "Arte"
]

# ─── Log ─────────────────────────────────────────────────────────────────────

def log(msg: str, nivel: str = "INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    linha = f"[{ts}] [{nivel}] {msg}"
    print(linha)
    LOG_FILE.parent.mkdir(exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(linha + "\n")

# ─── Ferramentas de automação macOS ──────────────────────────────────────────

def tirar_screenshot() -> str:
    """Captura a tela e retorna como base64."""
    path = "/tmp/bernoulli_agent_cap.png"
    result = subprocess.run(
        ["screencapture", "-x", "-C", path],
        capture_output=True
    )
    if result.returncode != 0 or not os.path.exists(path):
        raise RuntimeError(f"Screenshot falhou: {result.stderr.decode()}")
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

def click(x: int, y: int):
    """Clica nas coordenadas via osascript."""
    script = f'tell application "System Events" to click at {{{x}, {y}}}'
    subprocess.run(["osascript", "-e", script], capture_output=True)
    time.sleep(0.6)

def scroll_down(x: int, y: int, ticks: int = 5):
    """Scroll para baixo."""
    script = f'tell application "System Events" to scroll down at {{{x}, {y}}} by {ticks}'
    subprocess.run(["osascript", "-e", script], capture_output=True)
    time.sleep(0.4)

def pressionar_tecla(tecla: str):
    """Pressiona uma tecla (ex: 'return', 'escape', 'tab')."""
    mapa = {"return": 36, "escape": 53, "tab": 48, "space": 49,
            "left": 123, "right": 124, "down": 125, "up": 126}
    codigo = mapa.get(tecla, 36)
    script = f'tell application "System Events" to key code {codigo}'
    subprocess.run(["osascript", "-e", script], capture_output=True)
    time.sleep(0.3)

def abrir_bernoulli():
    """Abre o app Meu Bernoulli 4.0."""
    subprocess.run(["open", "-a", "Meu Bernoulli 4.0"])
    log("Abrindo Meu Bernoulli 4.0...")
    time.sleep(4)

def trazer_bernoulli_frente():
    """Traz o Bernoulli para frente."""
    script = 'tell application "Meu Bernoulli 4.0" to activate'
    subprocess.run(["osascript", "-e", script], capture_output=True)
    time.sleep(1)

# ─── Escalar coordenadas (Retina 2x) ─────────────────────────────────────────

# Tela: 2408x1506 física / lógica ~1204x753 (2x Retina)
# Claude vê a screenshot em resolução física, mas clicks são em lógica
# → dividir coordenadas por 2

def escalar(x: int, y: int) -> tuple:
    """Converte coordenadas de screenshot (retina) para lógicas (click)."""
    return (x // 2, y // 2)

# ─── Verificar permissões ─────────────────────────────────────────────────────

def verificar_permissoes() -> dict:
    """Testa se as permissões necessárias estão concedidas."""
    resultado = {"screen_recording": False, "accessibility": False, "api_key": False}

    # Screen Recording — testa tirando screenshot
    try:
        path = "/tmp/bern_perm_test.png"
        r = subprocess.run(["screencapture", "-x", "-C", path], capture_output=True, timeout=5)
        resultado["screen_recording"] = r.returncode == 0 and os.path.exists(path)
    except Exception:
        pass

    # Accessibility — testa osascript
    try:
        r = subprocess.run(
            ["osascript", "-e", 'tell application "System Events" to name of first process whose frontmost is true'],
            capture_output=True, timeout=5
        )
        resultado["accessibility"] = r.returncode == 0
    except Exception:
        pass

    # API Key
    resultado["api_key"] = bool(ANTHROPIC_KEY) and ANTHROPIC_KEY != "COLOQUE_SUA_CHAVE_AQUI"

    return resultado

def mostrar_guia_permissoes(permissoes: dict):
    """Exibe guia claro para configurar permissões ausentes."""
    print("\n" + "="*60)
    print("⚙️  CONFIGURAÇÃO NECESSÁRIA")
    print("="*60)

    if not permissoes["screen_recording"]:
        print("""
❌ GRAVAÇÃO DE TELA — Terminal não tem permissão

   Para corrigir (30 segundos):
   1. Ajustes do Sistema → Privacidade e Segurança
   2. Clique em "Gravação de Tela"
   3. Clique no "+" e adicione "Terminal"
   4. Reinicie o Terminal
""")

    if not permissoes["accessibility"]:
        print("""
❌ ACESSIBILIDADE — Terminal não tem permissão

   Para corrigir (30 segundos):
   1. Ajustes do Sistema → Privacidade e Segurança
   2. Clique em "Acessibilidade"
   3. Clique no "+" e adicione "Terminal"
   4. Reinicie o Terminal
""")

    if not permissoes["api_key"]:
        print("""
❌ CHAVE DA API — Configure em ~/sistema-tiago/.env

   Abra o arquivo e substitua:
   ANTHROPIC_API_KEY=COLOQUE_SUA_CHAVE_AQUI

   pela sua chave real de https://console.anthropic.com
""")

    print("="*60)
    print("Após configurar, execute novamente: python3 ~/sistema-tiago/bernoulli_agent.py")
    print("="*60 + "\n")

# ─── Postar conteúdo na API ───────────────────────────────────────────────────

def postar_conteudo(materia: str, capitulo: str, conteudo: str) -> bool:
    """Envia conteúdo extraído para o sistema de estudos."""
    try:
        r = requests.post(f"{API_LOCAL}/api/bernoulli/conteudo", json={
            "materia": materia,
            "capitulo": capitulo,
            "conteudo": conteudo
        }, timeout=10)
        if r.status_code == 200:
            log(f"✅ Postado: {materia} — {capitulo[:60]}")
            return True
        else:
            log(f"⚠️  API retornou {r.status_code}", "WARN")
            return False
    except Exception as e:
        log(f"❌ Erro ao postar conteúdo: {e}", "ERROR")
        return False

def verificar_sistema_online() -> bool:
    """Verifica se o sistema de estudos está rodando."""
    try:
        r = requests.get(f"{API_LOCAL}/api/materias", timeout=5)
        return r.status_code == 200
    except Exception:
        return False

# ─── Agente Claude com Computer Use ──────────────────────────────────────────

class AgenteComputerUse:
    """Agente que usa Claude API + computer use para navegar o Bernoulli."""

    def __init__(self):
        self.client = Anthropic(api_key=ANTHROPIC_KEY)
        self.resultados = []

    def executar_tool(self, tool_name: str, tool_input: dict) -> dict:
        """Executa uma ferramenta de computer use retornada pelo Claude."""
        if tool_name == "computer":
            action = tool_input.get("action")

            if action == "screenshot":
                img_b64 = tirar_screenshot()
                return {
                    "type": "tool_result",
                    "content": [{
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": img_b64
                        }
                    }]
                }

            elif action == "left_click":
                cx, cy = tool_input["coordinate"]
                lx, ly = escalar(cx, cy)
                click(lx, ly)
                time.sleep(0.8)
                return {"type": "tool_result", "content": "Clicado."}

            elif action == "scroll":
                cx, cy = tool_input["coordinate"]
                lx, ly = escalar(cx, cy)
                direction = tool_input.get("direction", "down")
                amount = tool_input.get("amount", 3)
                scroll_down(lx, ly, amount)
                return {"type": "tool_result", "content": "Scroll executado."}

            elif action == "key":
                key = tool_input.get("key", "")
                pressionar_tecla(key)
                return {"type": "tool_result", "content": f"Tecla {key} pressionada."}

            elif action == "wait":
                ms = tool_input.get("duration", 1000)
                time.sleep(ms / 1000)
                return {"type": "tool_result", "content": "Aguardado."}

        return {"type": "tool_result", "content": "Ação não reconhecida."}

    def executar_tarefa(self, prompt_tarefa: str, max_turnos: int = 30) -> str:
        """
        Executa uma tarefa autônoma usando Claude + computer use.
        Retorna o conteúdo extraído como string.
        """
        # Screenshot inicial
        img_inicial = tirar_screenshot()

        mensagens = [{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": img_inicial
                    }
                },
                {
                    "type": "text",
                    "text": prompt_tarefa
                }
            ]
        }]

        resultado_final = ""

        for turno in range(max_turnos):
            log(f"  Turno {turno + 1}/{max_turnos}...")

            response = self.client.beta.messages.create(
                model="claude-opus-4-5",
                max_tokens=4096,
                tools=[{
                    "type": "computer_20241022",
                    "name": "computer",
                    "display_width_px": 2408,
                    "display_height_px": 1506,
                }],
                messages=mensagens,
                betas=["computer-use-2024-10-22"],
                system="""Você é um agente de extração de conteúdo educacional.
Sua tarefa é navegar o app Meu Bernoulli 4.0 e extrair conteúdo didático.
IMPORTANTE:
- Sempre tire um screenshot antes de clicar para confirmar o que está na tela
- Quando encontrar conteúdo de texto de uma aula, extraia-o completamente
- Ao terminar a extração, diga EXPLICITAMENTE: "EXTRAÇÃO CONCLUÍDA: " seguido do conteúdo
- Seja eficiente: mínimo de cliques necessários
- A resolução da tela é 2408x1506 (Retina 2x) — use essas coordenadas nos cliques"""
            )

            # Processar resposta
            tool_calls = []
            texto_resposta = ""

            for bloco in response.content:
                if bloco.type == "text":
                    texto_resposta += bloco.text
                    if "EXTRAÇÃO CONCLUÍDA:" in bloco.text:
                        resultado_final = bloco.text.split("EXTRAÇÃO CONCLUÍDA:", 1)[1].strip()
                elif bloco.type == "tool_use":
                    tool_calls.append(bloco)

            # Se não há mais tool calls, tarefa concluída
            if response.stop_reason == "end_turn" or not tool_calls:
                if resultado_final:
                    log(f"  Tarefa concluída em {turno + 1} turnos.")
                else:
                    resultado_final = texto_resposta
                break

            # Executar tool calls e preparar próxima mensagem
            mensagens.append({"role": "assistant", "content": response.content})

            resultados_tools = []
            for tc in tool_calls:
                resultado_tool = self.executar_tool(tc.name, tc.input)
                resultados_tools.append({
                    "type": "tool_result",
                    "tool_use_id": tc.id,
                    **resultado_tool
                })

            mensagens.append({"role": "user", "content": resultados_tools})

        return resultado_final

# ─── Tarefas de extração ──────────────────────────────────────────────────────

def extrair_feed(agente: AgenteComputerUse) -> list:
    """Extrai mensagens novas do Feed do Bernoulli."""
    log("📢 Verificando Feed de mensagens...")
    trazer_bernoulli_frente()

    prompt = """
    Estou vendo o app Meu Bernoulli 4.0.
    1. Clique no botão Home (ícone de casinha na barra lateral esquerda)
    2. Aguarde a tela inicial carregar
    3. Leia todas as mensagens do Feed que aparecem no lado direito da tela
    4. Para cada mensagem, anote: remetente, data, e texto completo
    5. Se precisar, clique em "Ver mais" para expandir

    Ao terminar, diga:
    EXTRAÇÃO CONCLUÍDA: [lista das mensagens no formato JSON:
    [{"remetente": "...", "data": "...", "texto": "..."}, ...]
    ]
    """

    resultado = agente.executar_tarefa(prompt, max_turnos=15)
    log(f"Feed extraído: {len(resultado)} caracteres")
    return resultado

def extrair_ebook_materia(agente: AgenteComputerUse, materia: str) -> list:
    """Extrai conteúdo dos e-books de uma matéria."""
    log(f"📚 Extraindo {materia}...")
    trazer_bernoulli_frente()

    extraidos = []

    prompt = f"""
    Estou no app Meu Bernoulli 4.0.

    TAREFA: Extrair o conteúdo do e-book de {materia}.

    PASSOS:
    1. Clique no ícone de "Unidades de Aprendizagem" na barra lateral (ícone de livro)
    2. Aguarde a tela carregar com as matérias
    3. Encontre e clique na matéria "{materia}"
    4. Aguarde os capítulos carregarem
    5. Clique na PRIMEIRA unidade disponível (ex: A1 ou similar)
    6. Clique no botão "E-book"
    7. Aguarde o e-book abrir (pode demorar 3-5 segundos)
    8. Leia o TÍTULO do capítulo e as primeiras páginas de conteúdo
    9. Role para baixo para ler mais conteúdo
    10. Extraia o texto principal (ignore cabeçalhos decorativos, foque no conteúdo didático)

    Ao terminar, diga:
    EXTRAÇÃO CONCLUÍDA:
    CAPÍTULO: [título do capítulo]
    CONTEÚDO: [texto extraído do e-book, mínimo 200 palavras se disponível]
    """

    resultado = agente.executar_tarefa(prompt, max_turnos=25)

    if resultado and "CAPÍTULO:" in resultado:
        partes = resultado.split("CONTEÚDO:", 1)
        capitulo = partes[0].replace("CAPÍTULO:", "").strip() if len(partes) > 0 else "Capítulo"
        conteudo = partes[1].strip() if len(partes) > 1 else resultado

        if postar_conteudo(materia, capitulo, conteudo):
            extraidos.append({"materia": materia, "capitulo": capitulo, "chars": len(conteudo)})
    elif resultado:
        # Tentar postar mesmo sem formato perfeito
        capitulo = f"{materia} — capítulo extraído automaticamente"
        if postar_conteudo(materia, capitulo, resultado):
            extraidos.append({"materia": materia, "capitulo": capitulo, "chars": len(resultado)})

    return extraidos

def extrair_tarefas(agente: AgenteComputerUse) -> list:
    """Verifica tarefas pendentes nas Unidades de Aprendizagem."""
    log("📋 Verificando tarefas pendentes...")
    trazer_bernoulli_frente()

    prompt = """
    Estou no app Meu Bernoulli 4.0.

    TAREFA: Verificar tarefas pendentes.

    PASSOS:
    1. Clique no ícone de Unidades de Aprendizagem
    2. Procure e clique em "Tarefas" (se disponível como filtro ou seção)
    3. Liste todas as tarefas com prazo, matéria e descrição
    4. Inclua tarefas com prazo próximo ou vencidas

    Ao terminar, diga:
    EXTRAÇÃO CONCLUÍDA: [lista de tarefas no formato:
    - [matéria] | [prazo] | [descrição]
    ]
    """

    return agente.executar_tarefa(prompt, max_turnos=15)

# ─── Função principal ─────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Agente Automático Bernoulli")
    parser.add_argument("--materia", help="Extrair apenas uma matéria específica")
    parser.add_argument("--feed-only", action="store_true", help="Extrair apenas o Feed")
    parser.add_argument("--tarefas", action="store_true", help="Verificar tarefas pendentes")
    parser.add_argument("--checar", action="store_true", help="Apenas verificar permissões")
    args = parser.parse_args()

    print("\n" + "⚽"*30)
    print("  AGENTE AUTOMÁTICO BERNOULLI")
    print("  Sistema de Estudos — Tiago")
    print("⚽"*30 + "\n")

    # ─── Verificar permissões ─────────────────────────────────────────────────
    log("Verificando permissões e configurações...")
    permissoes = verificar_permissoes()

    status = {
        "Screen Recording": "✅" if permissoes["screen_recording"] else "❌",
        "Acessibilidade":   "✅" if permissoes["accessibility"] else "❌",
        "API Key":          "✅" if permissoes["api_key"] else "❌",
        "Sistema Online":   "✅" if verificar_sistema_online() else "❌",
    }

    for k, v in status.items():
        print(f"  {v}  {k}")
    print()

    if args.checar:
        if not all([permissoes["screen_recording"], permissoes["accessibility"]]):
            mostrar_guia_permissoes(permissoes)
        else:
            print("✅ Tudo configurado! Pronto para rodar o agente.")
        return

    # Verificar se pode prosseguir
    problemas = []
    if not permissoes["screen_recording"]:
        problemas.append("screen_recording")
    if not permissoes["accessibility"]:
        problemas.append("accessibility")
    if not permissoes["api_key"]:
        problemas.append("api_key")

    if problemas:
        mostrar_guia_permissoes(permissoes)
        sys.exit(1)

    if not verificar_sistema_online():
        log("❌ Sistema de estudos não está rodando. Execute: bash ~/sistema-tiago/iniciar.sh", "ERROR")
        sys.exit(1)

    # ─── Abrir Bernoulli ──────────────────────────────────────────────────────
    abrir_bernoulli()

    # ─── Criar agente ─────────────────────────────────────────────────────────
    agente = AgenteComputerUse()

    inicio = datetime.now()
    total_extraidos = 0

    try:
        # Feed
        if not args.materia or args.feed_only:
            extrair_feed(agente)

        if args.feed_only:
            log("Modo feed-only concluído.")
            return

        # Tarefas
        if args.tarefas or not args.materia:
            extrair_tarefas(agente)

        # E-books por matéria
        materias = [args.materia] if args.materia else MATERIAS_ALVO

        for materia in materias:
            try:
                resultado = extrair_ebook_materia(agente, materia)
                total_extraidos += len(resultado)
            except Exception as e:
                log(f"Erro ao extrair {materia}: {e}", "ERROR")
            time.sleep(2)  # Pausa entre matérias

    except KeyboardInterrupt:
        log("Agente interrompido pelo usuário.", "WARN")

    # ─── Relatório final ──────────────────────────────────────────────────────
    duracao = (datetime.now() - inicio).seconds
    print("\n" + "="*50)
    print(f"✅ SINCRONIZAÇÃO CONCLUÍDA")
    print(f"   Conteúdos extraídos: {total_extraidos}")
    print(f"   Duração: {duracao}s")
    print(f"   Log: {LOG_FILE}")
    print("="*50 + "\n")


if __name__ == "__main__":
    main()

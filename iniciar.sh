#!/bin/bash
# ─── Iniciar Sistema de Estudos do Tiago ───────────────────────────────────
# Execute: bash ~/sistema-tiago/iniciar.sh

echo "⚽ Iniciando Arena do Conhecimento..."

# Verificar se já está rodando
if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "✅ Servidor já está rodando em http://localhost:8000"
    open "http://localhost:8000"
    exit 0
fi

# Carregar variável de ambiente da API
CHAVE_FILE="$HOME/sistema-tiago/.env"
if [ -f "$CHAVE_FILE" ]; then
    export $(cat "$CHAVE_FILE" | xargs)
fi

# Iniciar servidor
cd "$HOME/sistema-tiago"
nohup "$HOME/Library/Python/3.9/bin/uvicorn" main:app \
    --host 0.0.0.0 \
    --port 8000 \
    > /tmp/sistema-tiago.log 2>&1 &

echo "PID: $!"
sleep 3

# Verificar se subiu
if lsof -Pi :8000 -sTCP:LISTEN -t >/dev/null 2>&1; then
    echo "✅ Sistema rodando!"
    echo "📱 Tiago (celular/tablet): http://$(ipconfig getifaddr en0):8000"
    echo "📊 Pais (supervisão):      http://$(ipconfig getifaddr en0):8000/pais"
    echo "🖥️  Local (este Mac):       http://localhost:8000"
    open "http://localhost:8000"
else
    echo "❌ Erro ao iniciar. Verifique o log: cat /tmp/sistema-tiago.log"
fi

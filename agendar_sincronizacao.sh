#!/bin/bash
# ─── Agendador de Sincronização Automática do Bernoulli ───────────────────
# Execute UMA VEZ para agendar: bash ~/sistema-tiago/agendar_sincronizacao.sh

PYTHON="/Library/Developer/CommandLineTools/usr/bin/python3"
SCRIPT="$HOME/sistema-tiago/bernoulli_agent.py"
SERVIDOR="$HOME/sistema-tiago/iniciar.sh"
LOG="/tmp/bernoulli_sync.log"

echo "⚽ Configurando sincronização automática do Bernoulli..."

# ─── Verificar permissões primeiro ───────────────────────────────────────────
echo ""
echo "Verificando permissões..."
$PYTHON $SCRIPT --checar
if [ $? -ne 0 ]; then
    echo ""
    echo "⚠️  Configure as permissões acima antes de agendar."
    echo "   Depois execute este script novamente."
    exit 1
fi

# ─── Criar LaunchAgent para sincronização diária ─────────────────────────────
PLIST="$HOME/Library/LaunchAgents/com.tiago.bernoulli-sync.plist"

cat > "$PLIST" << PLISTEOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.tiago.bernoulli-sync</string>

    <key>ProgramArguments</key>
    <array>
        <string>/bin/bash</string>
        <string>-c</string>
        <string>
            # Iniciar sistema se não estiver rodando
            if ! curl -s http://localhost:8000/api/materias > /dev/null 2>&1; then
                bash $SERVIDOR &
                sleep 5
            fi
            # Sincronizar Bernoulli
            $PYTHON $SCRIPT >> $LOG 2>&1
        </string>
    </array>

    <!-- Executar todo dia às 10:00 (quando o MacBook normalmente está ligado) -->
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>10</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>

    <key>StandardOutPath</key>
    <string>$LOG</string>
    <key>StandardErrorPath</key>
    <string>$LOG</string>

    <key>RunAtLoad</key>
    <false/>

    <key>EnvironmentVariables</key>
    <dict>
        <key>HOME</key>
        <string>$HOME</string>
        <key>PATH</key>
        <string>/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
PLISTEOF

# Carregar o LaunchAgent
launchctl unload "$PLIST" 2>/dev/null
launchctl load "$PLIST"

if [ $? -eq 0 ]; then
    echo ""
    echo "✅ Sincronização automática configurada!"
    echo ""
    echo "   📅 Horário: Todo dia às 17:30"
    echo "   📄 Log: $LOG"
    echo "   ⚙️  Arquivo: $PLIST"
    echo ""
    echo "Outros comandos úteis:"
    echo "   Sincronizar agora:     python3 $SCRIPT"
    echo "   Só uma matéria:        python3 $SCRIPT --materia Biologia"
    echo "   Só o Feed:             python3 $SCRIPT --feed-only"
    echo "   Ver log:               tail -f $LOG"
    echo "   Desativar agendamento: launchctl unload $PLIST"
else
    echo "❌ Erro ao registrar agendamento. Tente rodar como administrador."
fi

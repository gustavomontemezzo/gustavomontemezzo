#!/bin/bash
# Roda o agente Bernoulli para o Henrique
# IMPORTANTE: Antes de rodar, certifique-se que:
#   1. O app "Meu Bernoulli 4.0" está instalado e logado com a conta do Henrique
#      (usuário: 45008893@redevicentina.com.br)
#   2. As permissões de Tela e Acessibilidade estão ativas para o Terminal

cd "$(dirname "$0")"
python3 bernoulli_agent.py --usuario henrique "$@"

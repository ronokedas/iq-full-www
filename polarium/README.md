# Polarium Full - Robô de Trading Algorítmico

Sistema de automação de operações de Opções Binárias/Digital para a corretora **Polarium Broker** (`https://trade.polariumbroker.com/traderoom`).

## Como Executar

### Opção 1: Via Script PowerShell
1. Abra o terminal na pasta `polarium`.
2. Execute:
   ```powershell
   .\run_bot.ps1
   ```

### Opção 2: Via Python
1. Execute diretamente:
   ```powershell
   python unified_ai_bot.py
   ```

## Fluxo Interativo de Entrada

Ao abrir o robô, ele solicitará:
1. **E-mail Polarium**: Digite seu e-mail de login da Polarium Broker.
2. **Senha Polarium**: Digite sua senha (os caracteres ficam ocultos por segurança).
3. **Conta**: Escolha `1` para **DEMO** ou `2` para **REAL**.
4. **Valor por Operação**: Informe o valor numérico em Reais (ex: `10.00`).
5. **Estratégias**: Digite `0` para ativar **TODAS** ou informe o número/combinação desejada (ex: `1,4`).

## Estratégias Suportadas

1. **Cenário Perfeito + Recusado Primeiro Registro**
2. **Start Pattern**
3. **Retest Primeiro Registro**
4. **Inverso Retest Primeiro Registro**
5. **Inverso Retest + EMA5**
6. **V1/V2/V3 Retest**

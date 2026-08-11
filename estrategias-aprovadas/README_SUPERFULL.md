# SuperFull - Sistema Unificado EvePulse

## 🚀 Visão Geral

O **SuperFull** é um sistema unificado que integra todas as estratégias do catálogo EvePulse em um único robô de trading automatizado para IQ Option. Ele monitora múltiplas estratégias simultaneamente e executa entradas automaticamente sempre que qualquer estratégia ativada gera um sinal.

## ✨ Funcionalidades Principais

### 🔐 Autenticação Interativa
- Solicita email e senha da IQ Option ao iniciar
- Permite escolher entre **Conta Demo** (PRACTICE) ou **Conta Real** (REAL)
- Validação de credenciais com retry automático

### 📊 Seleção de Estratégias
O sistema lista 15 estratégias disponíveis numeradas:

| Nº | ID | Nome | Timeframe | Tipo |
|----|----|------|-----------|------|
| 1 | S1 | Três Velas Reversão | M1 | Principal |
| 2 | S5 | Primeiro Retorno M1 | M1 | Principal |
| 3 | S5-M5 | Primeiro Retorno M5 | M1/M5 | Principal |
| 4 | S5-M15 | Primeiro Retorno M15 | M1/M15 | Principal |
| 5 | S9 | Lateral H1 Reversão | M1/H1 | Principal |
| 6 | S13 | Pavios de Rejeição | M1 | Principal |
| 7 | S14 | Continuação Rejeição Rompimento | M1 | Manual |
| 8 | S15 | Falso Rompimento | M1 | Manual |
| 9 | S16 | Engolfo M5 na Abertura M15 | M5/M15 | Manual |
| 10 | S17 | Rompimento Dupla Posição | M5 | Manual |
| 11 | S1-Lab | Engolfo com Retorno (Lab) | M1 | Laboratório |
| 12 | S2-Lab | Zonas 3 M15 (Lab) | M1/M15 | Laboratório |
| 13 | S6-Lab | Varredura M5 (Lab) | M5 | Laboratório |
| 14 | S7-Lab | Pavio + Reversão (Lab) | M1 | Laboratório |
| 15 | S10-Lab | Toques Nível (Lab) | M1 | Laboratório |

**Como usar:** Digite os números separados por vírgula (ex: `1,3,5,10`) ou deixe em branco para ativar TODAS.

### 🎯 Mercado e Ativos
- Escolha entre **Digital** ou **Binárias/Turbo**
- Selecione pares OTC, principais ou todos

### ⚙️ Execução Automática
- **Modo Automático**: Executa ordens automaticamente ao detectar sinais
- **Modo Observação**: Envia apenas alertas sem executar ordens
- Valor de entrada configurável (padrão: R$ 2,00)

### 📱 Alertas WhatsApp
- Envia alertas em tempo real para múltiplos números
- Mensagens formatadas com detalhes do sinal
- Thread dedicada para não bloquear o monitoramento

## 🛠️ Instalação

### Pré-requisitos
- Python 3.8+
- Conta na IQ Option

### Dependências
```bash
pip install requests iqoptionapi
```

## 🚀 Como Usar

### Iniciar o Sistema
```bash
cd estrategias-aprovadas
python superfull.py
```

### Fluxo de Configuração

1. **Login**: Digite seu email e senha da IQ Option
2. **Conta**: Escolha entre Demo (1) ou Real (2)
3. **Mercado**: Escolha Digital (1) ou Binárias (2)
4. **Estratégias**: Digite os números das estratégias desejadas
5. **Ativos**: Escolha quais pares monitorar
6. **Execução**: Ative ou desative execução automática

### Exemplo de Interação

```
========================================================================
  SUPERFULL - SISTEMA UNIFICADO EVEPULSE
========================================================================

📧 Digite seu email da IQ Option: usuario@email.com
🔑 Digite sua senha: *********

------------------------------------------------------------------------
  SELEÇÃO DE CONTA
------------------------------------------------------------------------

Em qual conta deseja operar?
  1 - CONTA DEMO (PRACTICE)
  2 - CONTA REAL (REAL)

Escolha (1 ou 2): 1
✅ Conta DEMO selecionada

------------------------------------------------------------------------
  ESTRATÉGIAS DISPONÍVEIS
------------------------------------------------------------------------

Nº   ID         Nome                              TF         Tipo        
------------------------------------------------------------------------
1    S1         Três Velas Reversão               M1         Principal   
2    S5         Primeiro Retorno M1               M1         Principal   
3    S5-M5      Primeiro Retorno M5               M1/M5      Principal   
...

💡 Dica: Digite os números separados por vírgula (ex: 1,3,5,10)
   Deixe em branco para ativar TODAS as estratégias

📊 Número das estratégias para monitorar: 1,9,10

✅ 3 estratégia(s) ativada(s):
   • S1 - Três Velas Reversão
   • S16 - Engolfo M5 na Abertura M15
   • S17 - Rompimento Dupla Posição
```

## 📋 Estrutura do Código

### Classes Principais

- **`ConfigSistema`**: Armazena todas as configurações do usuário
- **`Vela`**: Representação normalizada de candles
- **`Sinal`**: Dados de um sinal gerado por estratégia
- **`EstadoPar`**: Estado do monitoramento por par
- **`DetectorEstrategias`**: Classe base para detectores
- **`GerenciadorSinais`**: Gerencia detecção e execução
- **`FilaWhatsApp`**: Envio assíncrono de alertas

### Detectores Implementados

- `DetectorS1`: Três Velas Reversão
- `DetectorS5`: Primeiro Retorno M1
- `DetectorS16`: Engolfo M5 na Abertura M15
- `DetectorS17`: Rompimento Dupla Posição

> **Nota**: Mais detectores podem ser adicionados seguindo o padrão das classes existentes.

## 🔧 Personalização

### Adicionar Nova Estratégia

1. Crie uma nova classe detector herdando de `DetectorEstrategias`
2. Implemente o método `detectar(self, estado: EstadoPar) -> Optional[Sinal]`
3. Registre no dicionário `ESTRATEGIAS_DISPONIVEIS`
4. Adicione ao `self.detectores` no `GerenciadorSinais`

### Exemplo de Novo Detector

```python
class DetectorS9(DetectorEstrategias):
    """S9 - Lateral H1 Reversão"""
    
    def detectar(self, estado: EstadoPar) -> Optional[Sinal]:
        # Sua lógica aqui
        if condicao_detectada:
            return Sinal(
                estrategia_id="S9",
                estrategia_nome="Lateral H1 Reversão",
                par=estado.par,
                direcao="call",  # ou "put"
                timeframe="M1",
                timestamp=vela_atual.inicio,
                preco_entrada=vela_atual.fechamento,
                expiracao=60,
                padrao="Descrição do padrão"
            )
        return None
```

## ⚠️ Avisos Importantes

1. **Conta Real**: Use com extrema cautela. Teste exaustivamente em conta demo primeiro.
2. **Risco Financeiro**: Trading envolve risco de perda. Nunca opere mais do que pode perder.
3. **Conectividade**: Mantenha conexão estável com a internet durante operação.
4. **Backtesting**: Valide estratégias historicamente antes de usar com dinheiro real.

## 📞 Suporte

Para dúvidas ou problemas:
1. Verifique se as dependências estão instaladas corretamente
2. Execute em modo observação primeiro para validar sinais
3. Consulte logs detalhados no terminal

## 📄 Licença

Este software é fornecido "como está" para fins educacionais e de pesquisa.

---

**Desenvolvido com base no catálogo EvePulse de estratégias**
Versão: 1.0 | Última atualização: 2026

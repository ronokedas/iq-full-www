# Estratégias EvePulse - Documentação Completa

## Visão Geral

O sistema **EvePulse** implementa um conjunto de estratégias de trading baseadas em padrões de candles, divididas em dois grupos:

- **Estratégias Principais (S1–S17)**: Motor canônico usado pelo scanner e pelo robô de produção.
- **Estratégias de Laboratório (S1–S10)**: Implementações experimentais com regras numéricas estritas, sem look-ahead.

---

## CATÁLOGO DE ESTRATÉGIAS PRINCIPAIS

### S1 - Três Velas Reversão

**Descrição:** Vela oposta ou doji seguida por 3 velas iguais; entrada contrária.

**Timeframe:** M1

**Passo a passo até o gatilho:**

1. O sistema observa a sequência de candles M1.
2. Detecta uma vela **oposta** (ou DOJI) em relação às próximas.
3. As **próximas 3 velas M1 consecutivas** têm a **mesma cor** (GREEN ou RED).
4. A vela anterior às 3 iguais precisa ser **oposta ou DOJI** (evita tratar sequência de 4+ como novo padrão).
5. **Gatilho de entrada:** Assim que a 3ª vela fecha, entrada na direção **contrária**.
   - 3 verdes → PUT (entrada de baixa)
   - 3 vermelhas → CALL (entrada de alta)

---

### S5 - Primeiro Retorno M1 (Comando M1)

**Descrição:** Primeiro retorno M1 à abertura de um comando M1.

**Timeframe:** M1

**Passo a passo até o gatilho:**

1. O sistema procura um **candle de comando** nos últimos 21 candles M1.
   - **Comando de Alta (Green Command):** Vela verde sem pavio inferior (Low == Open).
   - **Comando de Baixa (Red Command):** Vela vermelha sem pavio superior (High == Open).
2. O nível de referência é o **preço de abertura** do comando.
3. Após o comando fechar, o sistema observa as M1 seguintes (máximo 20 minutos).
4. **Gatilho de entrada:** A primeira M1 que toca o nível de abertura do comando, sem que nenhuma M1 intermediária tenha tocado.
   - Comando vermelho + toque → CALL (reversão de alta)
   - Comando verde + toque → PUT (reversão de baixa)

---

### S5-M5 - Primeiro Retorno M5 (Comando M5)

**Descrição:** Primeiro retorno M1 à abertura de um comando M5.

**Timeframe:** M1, M5

**Passo a passo até o gatilho:**

1. O sistema usa candles **M5** como referências de comando.
2. Procura um comando M5 fechado nos últimos 20 candles M5.
3. O nível de referência é o **preço de abertura** do comando M5.
4. Observa as M1 após o fechamento do comando M5.
5. **Gatilho de entrada:** A primeira M1 que toca o nível de abertura do comando M5.
   - Comando M5 vermelho + toque → CALL
   - Comando M5 verde + toque → PUT

---

### S5-M15 - Primeiro Retorno M15 (Comando M15)

**Descrição:** Primeiro retorno M1 à abertura de um comando M15.

**Timeframe:** M1, M15

**Passo a passo até o gatilho:**

1. O sistema usa candles **M15** como referências de comando.
2. Procura um comando M15 fechado nos últimos 20 candles M15.
3. O nível de referência é o **preço de abertura** do comando M15.
4. Observa as M1 após o fechamento do comando M15.
5. **Gatilho de entrada:** A primeira M1 que toca o nível de abertura do comando M15.
   - Comando M15 vermelho + toque → CALL
   - Comando M15 verde + toque → PUT

---

### S9 - Lateral H1 Reversão

**Descrição:** Lateralidade H1 e reversão após 3 velas M1 iguais.

**Timeframe:** M1, H1

**Passo a passo até o gatilho:**

1. O sistema verifica se as **duas últimas velas H1** formam um padrão de **lateralidade**:
   - H1 mais recente tem High e Low dentro da faixa da H1 anterior.
   - As H1 são consecutivas (intervalo de 3600 segundos).
2. A configuração lateral vale **somente durante a H1 imediatamente seguinte**.
3. Dentro dessa H1, o sistema procura **3 velas M1 consecutivas da mesma cor**.
4. **Gatilho de entrada:** Assim que a 3ª vela M1 fecha, entrada na direção **contrária**.
   - 3 verdes M1 → PUT
   - 3 vermelhas M1 → CALL

---

### S13 - Pavios de Rejeição

**Descrição:** Três velas iguais com pavios de rejeição e corpos dentro da primeira.

**Timeframe:** M1

**Passo a passo até o gatilho:**

1. O sistema detecta **3 velas M1 consecutivas da mesma cor**.
2. Todas as 3 velas precisam ter **pavios de rejeição**:
   - Se verdes: todas com **pavio superior**.
   - Se vermelhas: todas com **pavio inferior**.
3. O fechamento da 2ª e 3ª velas fica **dentro do corpo da 1ª vela**:
   - Se verdes: 2ª e 3ª fecham abaixo do High da 1ª.
   - Se vermelhas: 2ª e 3ª fecham acima do Low da 1ª.
4. **Gatilho de entrada:** Assim que a 3ª vela fecha, entrada na direção **contrária**.
   - 3 verdes com pavios superiores → PUT
   - 3 vermelhas com pavios inferiores → CALL

---

### S14 - Continuação Rejeição Rompimento

**Descrição:** Continuação após rejeição do primeiro rompimento de um lote M1.

**Timeframe:** M1

**Tipo:** Estratégia manual aprovada (exige confirmação).

**Passo a passo até o gatilho:**

1. O sistema analisa **lotes** (sequências de mesma cor) nos últimos 21 candles M1.
2. Identifica um **candle de rompimento** (o último antes da confirmação).
3. Para um **lote vermelho**:
   - O rompimento fecha **acima do High** do primeiro candle do lote.
   - Nenhum candle intermediário rompeu antes.
   - A vela de confirmação é **vermelha**.
   - A confirmação toca o **nível de abertura** do primeiro candle vermelho e fecha acima dele.
4. Para um **lote verde** (inverso):
   - O rompimento fecha **abaixo do Low** do primeiro candle do lote.
   - A confirmação é **verde**.
   - A confirmação toca o **nível de abertura** do primeiro candle verde.
5. **Gatilho de entrada:** Na M1 seguinte à confirmação.
   - Lote vermelho + confirmação → CALL (UP)
   - Lote verde + confirmação → PUT (DOWN)
6. **Prazo:** Entrada deve ocorrer dentro de **60 segundos**.

---

### S15 - Falso Rompimento

**Descrição:** Falso rompimento e retorno ao primeiro preço de um lote M1.

**Timeframe:** M1

**Tipo:** Estratégia manual aprovada (exige confirmação).

**Passo a passo até o gatilho:**

1. O sistema analisa **lotes** nos últimos 21 candles M1.
2. Identifica um **candle de rompimento** que fecha além do primeiro candle do lote.
3. Para um **lote vermelho**:
   - O rompimento fecha acima do High do primeiro.
   - A confirmação é vermelha.
   - O fechamento da confirmação fica **entre o Low e o nível de abertura** do primeiro candle.
4. Para um **lote verde** (inverso):
   - O rompimento fecha abaixo do Low do primeiro.
   - A confirmação é verde.
   - O fechamento da confirmação fica **entre o nível de abertura e o High** do primeiro.
5. **Gatilho de entrada:** Na M1 seguinte à confirmação.
   - Lote vermelho + falso rompimento → PUT (DOWN)
   - Lote verde + falso rompimento → CALL (UP)
6. **Prazo:** Entrada deve ocorrer dentro de **60 segundos**.

---

### S16 - Engolfo M5 na Abertura M15

**Descrição:** Engolfo M5 na abertura de uma nova M15.

**Timeframe:** M5, M15

**Tipo:** Estratégia manual aprovada.

**Passo a passo até o gatilho:**

1. O sistema analisa **3 velas M5 consecutivas**.
2. A **2ª vela M5** pertence à **M15 anterior**.
3. A **3ª vela M5** é a **primeira da nova M15** (muda o bucket de 900s).
4. Para engolfo de alta:
   - 2ª M5 é vermelha, 3ª M5 é verde.
   - A 3ª M5 fecha **acima do High** da 2ª M5.
5. Para engolfo de baixa (inverso):
   - 2ª M5 é verde, 3ª M5 é vermelha.
   - A 3ª M5 fecha **abaixo do Low** da 2ª M5.
6. **Gatilho de entrada:** Na mesma vela M5 do engolfo.
   - Engolfo de alta → CALL (UP)
   - Engolfo de baixa → PUT (DOWN)
7. **Prazo:** Entrada deve ocorrer dentro de **20 segundos**.

---

### S17 - Rompimento Dupla Posição

**Descrição:** Rompimento M5 de uma dupla posição da mesma cor.

**Timeframe:** M5

**Tipo:** Estratégia manual aprovada.

**Passo a passo até o gatilho:**

1. O sistema analisa **3 velas M5 consecutivas**.
2. As **2 primeiras** têm a **mesma cor** e a **2ª está contida** na 1ª:
   - Se verdes: High da 2ª <= High da 1ª.
   - Se vermelhas: Low da 2ª >= Low da 1ª.
3. A **3ª vela M5** rompe o nível da 1ª vela por fechamento:
   - Se verdes: 3ª fecha **acima do High** da 1ª.
   - Se vermelhas: 3ª fecha **abaixo do Low** da 1ª.
4. **Gatilho de entrada:** Na mesma vela M5 do rompimento.
   - Dupla verde + rompimento → CALL (UP)
   - Dupla vermelha + rompimento → PUT (DOWN)
5. **Prazo:** Entrada deve ocorrer dentro de **20 segundos**.

---

## CATÁLOGO DE ESTRATÉGIAS DE LABORATÓRIO

### S1 (Lab) - Reversão/Engolfo com Retorno

**Descrição:** Sequência de reversão/engolfo com retorno ao nível da primeira vela.

**Timeframe:** M1

**Passo a passo até o gatilho:**

1. O sistema detecta padrão de engolfo em **3 velas M1 consecutivas**.
2. **Engolfo de alta:**
   - Vela 1: vermelha, com pavios superior e inferior.
   - Vela 2: verde, fecha acima do High da vela 1.
   - Vela 3: verde, fecha acima do High da vela 2, sem tocar o High da vela 1.
   - Nível de referência: **High da vela 1**.
3. **Engolfo de baixa** (inverso):
   - Vela 1: verde, com pavios.
   - Vela 2: vermelha, fecha abaixo do Low da vela 1.
   - Vela 3: vermelha, fecha abaixo do Low da vela 2, sem tocar o Low da vela 1.
   - Nível de referência: **Low da vela 1**.
4. Após o padrão, o sistema aguarda o **primeiro toque posterior** ao nível de referência.
5. **Gatilho de entrada:** Na M1 seguinte ao toque.
   - Engolfo de alta → CALL
   - Engolfo de baixa → PUT
6. **Expiração:** M1 seguinte à entrada.

---

### S2 - Zonas das 3 M15 Anteriores

**Descrição:** Máxima e mínima das 3 M15 fechadas anteriores como zonas.

**Timeframe:** M1, M15

**Passo a passo até o gatilho:**

1. Para cada candle M1 atual, o sistema identifica a **M15 correspondente**.
2. Calcula as **3 M15 fechadas anteriores** (não a atual).
3. **Resistência** = max(High) das 3 M15.
4. **Suporte** = min(Low) das 3 M15.
5. Tolerância baseada na amplitude entre resistência e suporte.
6. Se a M1 toca a **resistência** (High >= resistência - tol): sinal de **PUT**.
7. Se a M1 toca o **suporte** (Low <= suporte + tol): sinal de **CALL**.
8. Se a M1 toca **ambos** simultaneamente: **descartado**.
9. **Gatilho de entrada:** Na próxima M1.
10. **Expiração:** M1 seguinte à entrada.

---

### S6 - Varredura M5 com Fechamento

**Descrição:** Varredura da máxima/mínima anterior em M5.

**Timeframe:** M5

**Passo a passo até o gatilho:**

1. O sistema detecta **varredura (sweep)** em M5:
   - **Varredura de High:** candle atual faz High > High anterior, mas fecha **abaixo** do High anterior.
   - **Varredura de Low:** candle atual faz Low < Low anterior, mas fecha **acima** do Low anterior.
2. O candle seguinte deve fechar **além do corpo** do candle de varredura:
   - Varredura de High → candle seguinte fecha abaixo do **min(Open, Close)** da varredura → PUT.
   - Varredura de Low → candle seguinte fecha acima do **max(Open, Close)** da varredura → CALL.
3. **Gatilho de entrada:** Na M5 seguinte ao candle de confirmação.
4. **Expiração:** M5 seguinte à entrada.

---

### S7 - Captura de Pavio com Reversão

**Descrição:** Captura do pavio da vela anterior + fechamento de reversão.

**Timeframe:** M1

**Passo a passo até o gatilho:**

1. O sistema analisa a **vela anterior** (i-1).
2. Calcula a amplitude (High - Low) e os pavios:
   - **Pavio superior** = High - max(Open, Close).
   - **Pavio inferior** = min(Open, Close) - Low.
3. Se o **pavio superior** é significativo (>= min_wick_ratio da amplitude):
   - Espera reversão de baixa.
   - Vela atual fecha **vermelha** e abaixo do Low da anterior → PUT.
4. Se o **pavio inferior** é significativo:
   - Espera reversão de alta.
   - Vela atual fecha **verde** e acima do High da anterior → CALL.
5. **Gatilho de entrada:** Na próxima M1.
6. **Expiração:** M1 seguinte à entrada.

---

### S10 - Suporte/Resistência por Toques

**Descrição:** Suporte/resistência por dois toques não adjacentes.

**Timeframe:** M1

**Passo a passo até o gatilho:**

1. O sistema detecta **dois toques num nível** (High ou Low) que **não sejam adjacentes**.
2. A tolerância de zona é baseada na **amplitude mediana** dos candles recentes.
3. O nível de referência é a **média dos preços de toque**.
4. Tipos de nível:
   - **Resistência:** toques nos Highs → sinal de PUT no 3º toque.
   - **Suporte:** toques nos Lows → sinal de CALL no 3º toque.
5. **Gatilho de entrada:** No **terceiro toque**, na próxima M1.
6. **Expiração:** M1 seguinte à entrada.
7. Níveis sem novo toque dentro do período de lookback são **descartados**.

---

## CONCEITOS COMUNS

### Candle de Comando

- **Comando de Alta (Green Command):** Vela verde sem pavio inferior. O Low é igual ao Open.
- **Comando de Baixa (Red Command):** Vela vermelha sem pavio superior. O High é igual ao Open.

### Pavios de Rejeição

- **Pavio Superior:** Diferença significativa entre High e max(Open, Close).
- **Pavio Inferior:** Diferença significativa entre min(Open, Close) e Low.

### Lote

- Sequência de candles da **mesma cor** (GREEN ou RED), ignorando DOJI.

### Resultado

- **WIN:** A direção do sinal coincide com a cor da vela seguinte.
- **LOSS:** A direção do sinal é oposta à cor da vela seguinte.
- **DOJI:** A vela seguinte é DOJI (Open == Close).

### Wilson Score

- Métrica estatística usada para validar a confiabilidade de uma estratégia.
- Limite mínimo: **0.53** (53%) para aprovação.
- Tamanho mínimo de amostra: **50** ocorrências.

### Regra "2 Wins após 1 Loss"

- Após um LOSS, o símbolo fica **bloqueado para execução** até ocorrerem **2 VITÓRIAS consecutivas**.
- O detector continua **observando padrões** mesmo durante o bloqueio.

---

## RESUMO DO CATÁLOGO

| ID | Nome | Timeframe | Tipo | Direção |
|----|------|-----------|------|---------|
| S1 | Três Velas Reversão | M1 | Principal | Contrária |
| S5 | Primeiro Retorno M1 | M1 | Principal | Reversão |
| S5-M5 | Primeiro Retorno M5 | M1, M5 | Principal | Reversão |
| S5-M15 | Primeiro Retorno M15 | M1, M15 | Principal | Reversão |
| S9 | Lateral H1 Reversão | M1, H1 | Principal | Contrária |
| S13 | Pavios de Rejeição | M1 | Principal | Contrária |
| S14 | Continuação Rejeição | M1 | Manual | Continuação |
| S15 | Falso Rompimento | M1 | Manual | Reversão |
| S16 | Engolfo M5/M15 | M5, M15 | Manual | Engolfo |
| S17 | Dupla Posição | M5 | Manual | Rompimento |
| S1(Lab) | Engolfo com Retorno | M1 | Lab | Continuação |
| S2(Lab) | Zonas 3 M15 | M1, M15 | Lab | Reversão |
| S6(Lab) | Varredura M5 | M5 | Lab | Reversão |
| S7(Lab) | Pavio + Reversão | M1 | Lab | Reversão |
| S10(Lab) | Toques Nível | M1 | Lab | Reversão |

---

*Documento gerado para o sistema EvePulse - versão do catálogo: 2026.08.canonical-1*
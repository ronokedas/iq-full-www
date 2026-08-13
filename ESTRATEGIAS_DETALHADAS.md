# Catalogo e Especificação de Estratégias EvePulse

Este documento especifica a lógica completa, passo a passo e o gatilho de entrada exato de todas as 15 estratégias do sistema EvePulse (10 Principais + 5 de Laboratório). A padronização rígida destas regras é o pré-requisito para a extração de dados e treinamento dos modelos de Inteligência Artificial para garantir assertividade acima de 50%.

---

## Sumário
1. [S1 - Três Velas Reversão (M1)](#s1---três-velas-reversão-m1)
2. [S5 - Primeiro Retorno M1 / Comando M1](#s5---primeiro-retorno-m1--comando-m1)
3. [S5-M5 - Primeiro Retorno M5 / Comando M5](#s5-m5---primeiro-retorno-m5--comando-m5)
4. [S5-M15 - Primeiro Retorno M15 / Comando M15](#s5-m15---primeiro-retorno-m15--comando-m15)
5. [S9 - Lateral H1 Reversão (M1/H1)](#s9---lateral-h1-reversão-m1h1)
6. [S13 - Pavios de Rejeição (M1)](#s13---pavios-de-rejeição-m1)
7. [S14 - Continuação Rejeição Rompimento (M1)](#s14---continuação-rejeição-rompimento-m1)
8. [S15 - Falso Rompimento (M1)](#s15---falso-rompimento-m1)
9. [S16 - Engolfo M5 na Abertura M15 (M5/M15)](#s16---engolfo-m5-na-abertura-m15-m5m15)
10. [S17 - Rompimento Dupla Posição (M5)](#s17---rompimento-dupla-posição-m5)
11. [S1-Lab - Engolfo com Retorno (M1)](#s1-lab---engolfo-com-retorno-m1)
12. [S2-Lab - Zonas 3 M15 (M1/M15)](#s2-lab---zonas-3-m15-m1m15)
13. [S6-Lab - Varredura M5 (M5)](#s6-lab---varredura-m5-m5)
14. [S7-Lab - Captura de Pavio (M1)](#s7-lab---captura-de-pavio-m1)
15. [S10-Lab - Toques Nível (M1)](#s10-lab---toques-nível-m1)

---

## 1. S1 - Três Velas Reversão (M1)

### Descrição
Estratégia baseada em exaustão de microtendência. Identifica uma sequência de 3 velas consecutivas de mesma cor após uma vela de cor oposta ou Doji, operando a reversão imediata na 4ª vela.

### Passo a Passo Lógico
1. **Identificação da Vela 0 (V0)**:
   - Deve ser uma vela de cor OPOSTA à sequência seguinte OU ser um Doji (`Close == Open`).
2. **Identificação das Velas 1, 2 e 3 (V1, V2, V3)**:
   - Três velas consecutivas no gráfico M1.
   - **V1, V2 e V3 devem ter a mesma cor exata** (todas VERDES para Alta ou todas VERMELHAS para Baixa).
   - Nenhuma das 3 velas pode ser Doji.
3. **Validação**:
   - Confirmação de fechamento da V3 mantendo a mesma cor de V1 e V2.

### Gatilho de Entrada
- **Momento**: Exatamente no instante de fechamento da Vela 3 (aos 59 segundos / virada da Vela 4).
- **Operação CALL (Compra)**: Se V1, V2 e V3 forem VERMELHAS (após V0 Verde ou Doji).
- **Operação PUT (Venda)**: Se V1, V2 e V3 forem VERDES (após V0 Vermelha ou Doji).
- **Tempo de Expiração**: 60 segundos (M1 - expiração da Vela 4).

---

## 2. S5 - Primeiro Retorno M1 / Comando M1

### Descrição
Explora o nível de abertura de um "Comando" em M1 (vela sem pavio no preço de abertura). O preço tende a respeitar o primeiro teste/retorno a esse nível de taxa.

### Passo a Passo Lógico
1. **Identificação do Comando (M1)**:
   - **Comando de Alta**: Vela Verde onde `Low == Open` (sem pavio inferior na abertura).
   - **Comando de Baixa**: Vela Vermelha onde `High == Open` (sem pavio superior na abertura).
2. **Mapeamento da Taxa de Referência**:
   - Define o preço de Abertura do Comando como Nível Chave de Suporte/Resistência.
3. **Monitoramento do Histórico Recente (Até 20 velas)**:
   - Verifica se nenhuma vela posterior já tocou essa taxa de abertura desde a formação do comando.
4. **Identificação do Primeiro Retorno**:
   - Aguarda uma vela posterior retornar à taxa do comando.

### Gatilho de Entrada
- **Momento**: Após o fechamento da vela M1 que realizou o toque na taxa de abertura do Comando M1.
- **Confirmação Necessária**: A vela que toca a taxa deve fechar com a cor OPOSTA à cor do Comando (Rejeição com fechamento).
- **Operação CALL (Compra)**: Se o comando for de Alta (Verde), a vela M1 que toca a taxa deve fechar **Vermelha** e seu fechamento deve ser **ACIMA** da taxa de abertura do comando. Entramos no início da próxima vela para CALL.
- **Operação PUT (Venda)**: Se o comando for de Baixa (Vermelho), a vela M1 que toca a taxa deve fechar **Verde** e seu fechamento deve ser **ABAIXO** da taxa de abertura do comando. Entramos no início da próxima vela para PUT.
- **Tempo de Expiração**: 1 minuto (final da vela de entrada).

---

## 3. S5-M5 - Primeiro Retorno M5 / Comando M5

### Descrição
Versão multitimeframe da S5. Identifica velas de Comando no timeframe M5 (agrupamento de 5 velas M1 alinhadas ao relógio) e opera o primeiro toque do preço M1 nessa zona institucional.

### Passo a Passo Lógico
1. **Agrupamento e Leitura de M5**:
   - Agrupa velas M1 em blocos de 5 minutos alinhados (ex: 10:00, 10:05, 10:10).
2. **Identificação do Comando M5**:
   - **Comando M5 de Alta**: Vela M5 Verde onde `Low == Open` (sem pavio inferior na abertura dos primeiros 5 min).
   - **Comando M5 de Baixa**: Vela M5 Vermelha onde `High == Open` (sem pavio superior na abertura).
3. **Mapeamento da Taxa de Referência**:
   - Nível Chave = Preço de abertura do bloco M5.
4. **Verificação do Primeiro Retorno**:
   - Confirma que o preço não tocou essa abertura nas últimas velas M1 após o encerramento do bloco M5.

### Gatilho de Entrada
- **Momento**: Após o fechamento da vela M1 que realizou o primeiro toque na taxa de abertura do Comando M5.
- **Confirmação Necessária**: A vela M1 que toca a taxa deve fechar com a cor OPOSTA à cor do Comando M5.
- **Operação CALL**: Toque em Comando M5 de Alta (Verde) + Vela M1 de toque fecha **Vermelha** (fechando acima da taxa). Entrada na próxima vela M1 para CALL.
- **Operação PUT**: Toque em Comando M5 de Baixa (Vermelho) + Vela M1 de toque fecha **Verde** (fechando abaixo da taxa). Entrada na próxima vela M1 para PUT.
- **Tempo de Expiração**: 1 minuto (M1).

---

## 4. S5-M15 - Primeiro Retorno M15 / Comando M15

### Descrição
Identifica Comandos no gráfico de M15 (agrupamento de 15 velas M1) para definir fortes suportes/resistências institucionais do dia.

### Passo a Passo Lógico
1. **Agrupamento e Leitura de M15**:
   - Blocos de 15 minutos (ex: 10:00, 10:15, 10:30).
2. **Identificação do Comando M15**:
   - **Comando M15 Verde**: `Low == Open` no bloco M15.
   - **Comando M15 Vermelho**: `High == Open` no bloco M15.
3. **Mapeamento de Taxa**:
   - Linha de Suporte/Resistência na taxa de abertura da M15.
4. **Filtro de Primeiro Toque**:
   - O nível não pode ter sido violado/testado anteriormente no histórico do ciclo.

### Gatilho de Entrada
- **Momento**: Após o fechamento da vela M1 que realizou o primeiro toque na taxa de abertura da M15.
- **Confirmação Necessária**: A vela M1 que toca a taxa deve fechar com a cor OPOSTA à cor do Comando M15.
- **Operação CALL**: Toque em Comando M15 de Alta (Verde) + Vela M1 de toque fecha **Vermelha** (fechando acima da taxa). Entrada na próxima vela M1 para CALL.
- **Operação PUT**: Toque em Comando M15 de Baixa (Vermelho) + Vela M1 de toque fecha **Verde** (fechando abaixo da taxa). Entrada na próxima vela M1 para PUT.
- **Tempo de Expiração**: 1 minuto (M1).

---

## 5. S9 - Lateral H1 Reversão (M1/H1)

### Descrição
Operação de Reversão de M1 dentro dos limites de consolidação/lateralização do ciclo de 1 hora (H1).

### Passo a Passo Lógico
1. **Identificação do Canal H1**:
   - Mapeia o valor Máximo (`High_H1`) e Mínimo (`Low_H1`) da hora anterior ou do bloco de 60 minutos vigente.
2. **Validação do Contexto Lateral**:
   - Verifica se o preço se manteve oscilando dentro do intervalo sem tendência forte definida.
3. **Sinal de Exaustão em M1**:
   - Aguarda uma sequência de 3 velas M1 consecutivas empurrando o preço em direção ao topo (`High_H1`) ou ao fundo (`Low_H1`).

### Gatilho de Entrada
- **Momento**: Fechamento da 3ª vela M1 que aproxima o preço do limite do canal H1.
- **Operação CALL**: Preço testando o suporte de `Low_H1` após 3 velas vermelhas.
- **Operação PUT**: Preço testando a resistência de `High_H1` após 3 velas verdes.
- **Tempo de Expiração**: 60s (M1).

---

## 6. S13 - Pavios de Rejeição (M1)

### Descrição
Leitura de rejeição continuada de preço através da observação de pavios em velas consecutivas de mesma cor.

### Passo a Passo Lógico
1. **Análise das Últimas 3 Velas (V1, V2, V3 em M1)**:
   - **Caso de Rejeição de Alta (Pavios Superiores)**: V1, V2 e V3 são velas verdes com pavios superiores significativos (mínimo de 40% da amplitude total do candle).
   - **Caso de Rejeição de Baixa (Pavios Inferiores)**: V1, V2 e V3 são velas vermelhas com pavios inferiores significativos.
2. **Confirmação da Pressão Contrária**:
   - A cada vela, os pavios demonstram que os compradores/vendedores tentaram empurrar o preço, mas encontraram forte defesa da contraparte.

### Gatilho de Entrada
- **Momento**: No fechamento da 3ª vela M1 com pavio de rejeição.
- **Operação PUT**: Entrada após 3 velas verdes com pavios superiores proeminentes.
- **Operação CALL**: Entrada após 3 velas vermelhas com pavios inferiores proeminentes.
- **Tempo de Expiração**: 60s (M1).

---

## 7. S14 - Continuação Rejeição Rompimento (M1)

### Descrição
Operação de continuidade a favor da força compradora/vendedora quando há rompimento de uma taxa e rejeição de retorno.

### Passo a Passo Lógico
1. **Mapeamento de Nível**:
   - Identifica topo/fundo local relevante.
2. **Rompimento e Rejeição**:
   - Uma vela rompe o nível.
   - A vela seguinte tenta retornar, deixa um pavio de rejeição na zona rompida (pullback de rejeição) e fecha a favor do rompimento.
3. **Confirmação do Fluxo**:
   - Demonstração de que a zona rompida mudou de polaridade (suporte virou resistência ou vice-versa).

### Gatilho de Entrada
- **Momento**: Fechamento da vela de confirmação da rejeição sobre o nível rompido.
- **Operação CALL**: Rompimento de alta + rejeição da tentativa de queda.
- **Operação PUT**: Rompimento de baixa + rejeição da tentativa de alta.
- **Tempo de Expiração**: 60s (M1).

---

## 8. S15 - Falso Rompimento (M1)

### Descrição
Captura de armadilha de liquidez (*bull trap* / *bear trap*). O preço viola uma taxa de suporte/resistência recente, mas não sustenta e fecha de volta dentro da estrutura.

### Passo a Passo Lógico
1. **Identificação de Suporte/Resistência Local**:
   - Ponto de topo (`High_ref`) ou fundo (`Low_ref`) das últimas 10 a 30 velas M1.
2. **Violação da Zona (Vela V1)**:
   - A vela V1 ultrapassa a máxima/mínima de referência.
3. **Retorno Imediato (Vela V2)**:
   - A vela V2 (ou a própria V1) não consegue sustentar e fecha seu corpo de volta DENTRO do intervalo anterior.

### Gatilho de Entrada
- **Momento**: Fechamento da vela V2 que confirma a falha e o retorno para dentro da zona.
- **Operação PUT**: Falso rompimento de alta (preço furou topo e voltou).
- **Operação CALL**: Falso rompimento de baixa (preço furou fundo e voltou).
- **Tempo de Expiração**: 60s (M1).

---

## 9. S16 - Engolfo M5 na Abertura M15 (M5/M15)

### Descrição
Padrão de alta assertividade cruzando alinhamento de M5 e M15. Identifica um engolfo formado no gráfico M5 exatamente na transição de um bloco M15, operando o pullback em M1 na abertura da vela engolfada.

### Passo a Passo Lógico
1. **Alinhamento do Ciclo M15**:
   - Considera a virada do bloco de 15 minutos (ex: vela M5 das 10:00-10:05 e vela M5 das 10:05-10:10).
2. **Identificação do Engolfo M5**:
   - **Engolfo M5 de Alta**: Vela M5 anterior é Vermelha (C2). A vela M5 atual (C3 - primeira do bloco M15) é Verde e seu fechamento ultrapassa a Máxima da C2 (`C3.Close > C2.High`).
   - **Engolfo M5 de Baixa**: Vela M5 anterior é Verde (C2). A vela M5 atual (C3) é Vermelha e seu fechamento ultrapassa a Mínima da C2 (`C3.Close < C2.Low`).
3. **Mapeamento da Taxa de Pullback**:
   - Taxa Alvo = Preço de Abertura da vela engolfada C2 (`C2.Open`).

### Gatilho de Entrada
- **Momento**: Na vela M1 seguinte (início do segundo bloco M5 da M15), aguarda o preço realizar o pullback e TOCAR no preço de abertura da C2.
- **Operação CALL**: Após Engolfo M5 de Alta, toque na taxa de `C2.Open`.
- **Operação PUT**: Após Engolfo M5 de Baixa, toque na taxa de `C2.Open`.
- **Tempo de Expiração**: 300s (5 minutos - expiração da vela M5 vigente).

---

## 10. S17 - Rompimento Dupla Posição (M5)

### Descrição
Identificação de padrão de Dupla Posição (duas velas M5 seguidas da mesma cor onde a segunda está contida na amplitude da primeira) seguida de rompimento na 3ª vela M5.

### Passo a Passo Lógico
1. **Identificação da Dupla Posição (C1 e C2 em M5)**:
   - ambas de mesma cor (ambas Verdes ou ambas Vermelhas).
   - **Estrutura de Alta**: C1 Verde, C2 Verde onde `C2.High <= C1.High`.
   - **Estrutura de Baixa**: C1 Vermelha, C2 Vermelha onde `C2.Low >= C1.Low`.
2. **Rompimento na Vela C3 (M5)**:
   - **No caso de Alta**: C3 fecha acima da máxima de C1 (`C3.Close > C1.High`).
   - **No caso de Baixa**: C3 fecha abaixo da mínima de C1 (`C3.Close < C1.Low`).
3. **Mapeamento da Taxa de Entrada**:
   - Nível de Referência = Abertura da penúltima vela M5 (C2) (`Taxa = C2.Open`).

### Gatilho de Entrada
- **Momento**: Na vela M1 seguinte (durante a 4ª M5), aguarda o toque da taxa de abertura de C2.
- **Operação CALL**: Após rompimento de alta da dupla posição.
- **Operação PUT**: Após rompimento de baixa da dupla posição.
- **Tempo de Expiração**: 300s (M5 / 5 minutos).

---

## 11. S1-Lab - Engolfo com Retorno (Lab)

### Descrição
Variação experimental da S1 operando em M1. Detecta um Engolfo direto de M1 e aguarda o reteste do ponto de abertura da vela engolfada.

### Passo a Passo Lógico
1. **Identificação do Engolfo M1 (V1 e V2)**:
   - V1 é de cor oposta a V2.
   - V2 cobre totalmente o corpo de V1 (`V2.Close > V1.High` para alta ou `V2.Close < V1.Low` para baixa).
2. **Definição da Taxa de Retorno**:
   - Taxa = `V1.Open` (Abertura da vela engolfada).

### Gatilho de Entrada
- **Momento**: Na vela V3 (ou subsequente imediata), quando o preço recua e toca a taxa `V1.Open`.
- **Operação CALL**: No retorno após Engolfo de Alta.
- **Operação PUT**: No retorno após Engolfo de Baixa.
- **Tempo de Expiração**: 60s (M1).

---

## 12. S2-Lab - Zonas 3 M15 (Lab)

### Descrição
Estruturação de zonas dinâmicas de suporte e resistência mapeando as últimas 3 velas completas de M15.

### Passo a Passo Lógico
1. **Leitura das 3 M15 Anteriores**:
   - Coleta a Mínima mais baixa (`Low_zone`) e a Máxima mais alta (`High_zone`) dentre as últimas 3 velas M15 completas.
2. **Mapeamento do Canal**:
   - `High_zone` atua como Resistência Principal.
   - `Low_zone` atua como Suporte Principal.
3. **Aproximação em M1**:
   - Monitora a vela M1 atual aproximando-se das extremidades da zona.

### Gatilho de Entrada
- **Momento**: Toque direto da vela M1 no nível `High_zone` ou `Low_zone`.
- **Operação PUT**: Toque em `High_zone`.
- **Operação CALL**: Toque em `Low_zone`.
- **Tempo de Expiração**: 60s (M1).

---

## 13. S6-Lab - Varredura M5 (Lab)

### Descrição
Estratégia baseada em varredura de liquidez (*Liquidity Sweep*) no gráfico M5. Operação de reversão no M1 após captura de topo/fundo.

### Passo a Passo Lógico
1. **Formação M5 (Vela C1)**:
   - Registra `C1.High` e `C1.Low`.
2. **Varredura na Vela C2 (M5)**:
   - **Varredura de Alta**: C2 rompe a máxima de C1 (`C2.High > C1.High`), mas fecha ABAIXO da máxima de C1 (`C2.Close < C1.High`).
   - **Varredura de Baixa**: C2 rompe a mínima de C1 (`C2.Low < C1.Low`), mas fecha ACIMA da mínima de C1 (`C2.Close > C1.Low`).
3. **Confirmação na Vela C3 (M5)**:
   - A vela C3 fecha confirmando o movimento contrário à varredura (abaixo do corpo de C2 para baixa ou acima do corpo de C2 para alta).

### Gatilho de Entrada
- **Momento**: Abertura da primeira vela M1 imediatamente após o fechamento da M5 de confirmação (C3).
- **Operação PUT**: Após varredura de topo (High).
- **Operação CALL**: Após varredura de fundo (Low).
- **Tempo de Expiração**: 60s (M1) ou 300s conforme teste.

---

## 14. S7-Lab - Captura de Pavio (M1)

### Descrição
Operação a favor da tendência principal identificada por Médias Móveis Exponenciais (EMA 9 e EMA 21), filtrando velas com pavios de absorção/captura na direção do fluxo.

### Passo a Passo Lógico
1. **Cálculo dos Indicadores de Tendência (M1)**:
   - `EMA9` = Média Móvel Exponencial de 9 períodos.
   - `EMA21` = Média Móvel Exponencial de 21 períodos.
2. **Definição da Tendência**:
   - **Tendência de Alta**: `EMA9 > EMA21`.
   - **Tendência de Baixa**: `EMA9 < EMA21`.
3. **Padrão de Captura de Pavio**:
   - **Em Tendência de Alta**: Vela M1 apresenta pavio inferior longo (`Lower_Wick > Body * 0.8`), indicando rejeição de preços baixos e absorção compradora.
   - **Em Tendência de Baixa**: Vela M1 apresenta pavio superior longo (`Upper_Wick > Body * 0.8`), indicando rejeição de preços altos.

### Gatilho de Entrada
- **Momento**: Fechamento da vela M1 com o pavio de captura configurado.
- **Operação CALL**: Em tendência de alta após pavio inferior longo.
- **Operação PUT**: Em tendência de baixa após pavio superior longo.
- **Tempo de Expiração**: 60s (M1).

---

## 15. S10-Lab - Toques Nível (M1)

### Descrição
Mapeamento e operação em pontos de Suporte e Resistência baseados na regra do 3º toque não adjacente.

### Passo a Passo Lógico
1. **Mapeamento de Níveis (Janela de 50 velas M1)**:
   - Agrupa topos (`High`) e fundos (`Low`) em faixas de preço com tolerância de até 5% da amplitude média das velas.
2. **Contagem de Toques Não Adjacentes**:
   - Registra toques separados por pelo menos 2 velas de distância para evitar falsa contagem no mesmo consolidado.
3. **Validação**:
   - 1º Toque: Criação do Nível.
   - 2º Toque: Confirmação do Nível.
   - 3º Toque: Nível maduro para operação de reversão.

### Gatilho de Entrada
- **Momento**: No exato instante em que a vela M1 realiza o 3º toque na taxa do suporte/resistência mapeado.
- **Operação PUT**: No 3º toque em nível de Resistência (Topos).
- **Operação CALL**: No 3º toque em nível de Suporte (Fundos).
- **Tempo de Expiração**: 60s (M1).

---

## Próximos Passos para Integração com IA (Machine Learning)

1. **Geração de Dataset de Feature Engineering**:
   - Para cada sinal gerado por qualquer uma das 15 estratégias acima nos dados históricos em `dados/iq_option/m1/`, extrair um vetor de características contendo:
     - Volatilidade recente (ATR, Desvio Padrão).
     - Inclinação da tendência (Diferencial entre EMA9 e EMA21).
     - Payout atual e horário do dia (sazonalidade).
     - Proporção do tamanho dos corpos e pavios nos últimos 5 candles.
     - Distância em pips em relação às zonas de suporte/resistência de M15/H1.
2. **Rotulagem (Target)**:
   - `Target = 1` se o sinal resultou em **WIN**.
   - `Target = 0` se o sinal resultou em **LOSS** ou **DOJI**.
3. **Treinamento do Modelo de Filtragem de Sinais**:
   - Algoritmo recomendado: LightGBM / XGBoost / Random Forest Classifier.
   - **Regra de Ouro**: O bot só fará a entrada real na IQ Option se `Probabilidade_Modelo(WIN) >= 0.55` (55% de confiança mínima, garantindo a meta solicitada acima de 50%).
"""Radar M1 - Rompimento, rejeicao e retorno ao lote.

O sistema procura lotes historicos formados por uma ou mais velas da mesma
cor. A referencia de preco e sempre a PRIMEIRA vela do lote. Depois do
primeiro fechamento que rompe essa referencia, a vela seguinte precisa
confirmar um dos quatro padroes abaixo:

- lote vermelho rompido para cima + rejeicao acima: CALL;
- lote vermelho rompido para cima + fechamento de volta no lote: PUT;
- lote verde rompido para baixo + rejeicao abaixo: PUT;
- lote verde rompido para baixo + fechamento de volta no lote: CALL.

O sinal fica armado somente durante a proxima vela M1. A entrada/alerta ocorre
quando essa vela toca a abertura da primeira vela do lote. Nao ha martingale,
placar, filtro de payout ou reaproveitamento de lote ja rompido.
"""

import os
import time

try:
    import requests
except ImportError as erro:  # Permite importar e testar a logica pura.
    requests = None
    ERRO_REQUESTS = str(erro)
else:
    ERRO_REQUESTS = None

try:
    from iqoptionapi.stable_api import IQ_Option
except ImportError as erro:  # Permite importar e testar a logica pura.
    IQ_Option = None
    ERRO_IQOPTION = str(erro)
else:
    ERRO_IQOPTION = None


PARES_OTC = [
    "AUDCAD-OTC", "EURGBP-OTC", "EURJPY-OTC", "EURUSD-OTC",
    "GBPJPY-OTC", "GBPUSD-OTC", "NZDUSD-OTC", "USDCHF-OTC",
    "USDHKD-OTC", "USDINR-OTC", "USDJPY-OTC", "USDSGD-OTC",
    "USDXOF-OTC", "USDZAR-OTC",
]


def _numeros_do_ambiente(valor, fallback):
    if not valor:
        return list(fallback)
    return [
        numero.strip()
        for numero in valor.replace(";", ",").split(",")
        if numero.strip()
    ]


CONFIG = {
    # Mantem os fallbacks usados pelos radares existentes. Em producao, prefira
    # definir as variaveis de ambiente e nao armazenar credenciais no arquivo.
    "email": os.getenv("IQOPTION_EMAIL", "dicasbbom@gmail.com"),
    "password": os.getenv("IQOPTION_PASSWORD", "1P9w@w4a5"),
    "pairs": PARES_OTC,
    "whatsapp": _numeros_do_ambiente(
        os.getenv("WHATSAPP_NUMBERS"),
        ["5591989340275"],
    ),
    "whatsapp_url": os.getenv(
        "WHATSAPP_URL",
        "http://localhost:3001/send-message",
    ),
    "whatsapp_intervalo_envio": 0.8,
    "timeframe": 60,
    "janela_lotes": 20,
    "historico_stream": 30,
    "valor_entrada": 2.0,
    "auto_executar": False,
    "conta": "PRACTICE",
    "tempo_maximo_sem_vela": 150,
    "falhas_maximas_por_par": 30,
    "intervalo_reinicio_par": 30,
    "intervalo_varredura": 0.5,
}


def validar_dependencias():
    faltando = []
    if requests is None:
        faltando.append(f"requests ({ERRO_REQUESTS})")
    if IQ_Option is None:
        faltando.append(f"iqoptionapi ({ERRO_IQOPTION})")
    if faltando:
        raise RuntimeError(
            "Dependencias ausentes: "
            + ", ".join(faltando)
            + ". Instale requests e a iqoptionapi no Python usado para iniciar "
            "este arquivo."
        )


def selecionar_mercado():
    while True:
        print("\nQual mercado deseja monitorar?")
        print("  1 - DIGITAL")
        print("  2 - BINARY/TURBO")
        escolha = input("Escolha: ").strip()
        if escolha == "1":
            return "DIGITAL"
        if escolha == "2":
            return "BINARY"
        print("Opcao invalida. Digite 1 ou 2.")


def selecionar_execucao_automatica():
    while True:
        print("\nDeseja que o sistema faca entradas automaticamente?")
        print(f"  Conta configurada: {CONFIG['conta']}")
        print("  1 - SIM, executar no toque da abertura do lote")
        print("  2 - NAO, somente alertas no toque")
        escolha = input("Escolha: ").strip().lower()
        if escolha in {"1", "sim", "s"}:
            return True
        if escolha in {"2", "nao", "não", "n"}:
            return False
        print("Opcao invalida. Digite 1 ou 2.")


def numeros_whatsapp():
    numeros = CONFIG["whatsapp"]
    if isinstance(numeros, str):
        numeros = _numeros_do_ambiente(numeros, [])
    return list(dict.fromkeys(str(numero).strip() for numero in numeros if str(numero).strip()))


def enviar_alerta(mensagem):
    """Envia a mensagem a todos os destinatarios e nunca derruba o radar."""
    if requests is None:
        print("[WHATSAPP] requests nao esta instalado; alerta nao enviado.")
        return 0

    numeros = numeros_whatsapp()
    enviados = 0
    for indice, numero in enumerate(numeros):
        try:
            resposta = requests.post(
                CONFIG["whatsapp_url"],
                json={"number": numero, "message": mensagem},
                timeout=10,
            )
            if 200 <= resposta.status_code < 300:
                enviados += 1
                print(f"[WHATSAPP] Enviado para {numero}")
            else:
                print(
                    f"[WHATSAPP] Falha HTTP {resposta.status_code} para {numero}: "
                    f"{resposta.text[:200]}"
                )
        except Exception as erro:
            print(f"[WHATSAPP] Falha para {numero}: {erro}")

        if indice < len(numeros) - 1:
            time.sleep(CONFIG["whatsapp_intervalo_envio"])

    print(f"[WHATSAPP] Entrega: {enviados}/{len(numeros)} destinatarios.")
    return enviados


def cor_da_vela(vela):
    if vela["close"] > vela["open"]:
        return "verde"
    if vela["close"] < vela["open"]:
        return "vermelho"
    return "doji"


def eh_verde(vela):
    return cor_da_vela(vela) == "verde"


def eh_vermelha(vela):
    return cor_da_vela(vela) == "vermelho"


def mapear_lotes(velas):
    """Agrupa sequencias coloridas; doji separa os lotes e nao e incluido."""
    lotes = []
    indice = 0

    while indice < len(velas):
        cor = cor_da_vela(velas[indice])
        if cor == "doji":
            indice += 1
            continue

        inicio = indice
        while indice + 1 < len(velas) and cor_da_vela(velas[indice + 1]) == cor:
            indice += 1
        fim = indice
        primeira = velas[inicio]
        lotes.append({
            "cor": cor,
            "inicio": inicio,
            "fim": fim,
            "from": primeira["from"],
            "abertura": float(primeira["open"]),
            "maxima": float(primeira["max"]),
            "minima": float(primeira["min"]),
        })
        indice += 1

    return lotes


def _rompeu_referencia(vela, lote):
    if lote["cor"] == "vermelho":
        return vela["close"] > lote["maxima"]
    return vela["close"] < lote["minima"]


def _houve_rompimento_anterior(velas, lote, indice_rompimento):
    """Considera somente fechamentos posteriores ao fim do lote."""
    return any(
        _rompeu_referencia(vela, lote)
        for vela in velas[lote["fim"] + 1:indice_rompimento]
    )


def localizar_lote_rompido(velas_ate_rompimento, janela=None):
    """Retorna o lote mais recente cujo primeiro rompimento e a ultima vela."""
    if len(velas_ate_rompimento) < 2:
        return None

    janela = CONFIG["janela_lotes"] if janela is None else janela
    indice_rompimento = len(velas_ate_rompimento) - 1
    rompimento = velas_ate_rompimento[indice_rompimento]
    primeiro_indice_elegivel = max(0, indice_rompimento - janela)
    candidatos = []

    for lote in mapear_lotes(velas_ate_rompimento):
        # O lote precisa ter terminado antes da vela de rompimento e sua
        # primeira vela precisa estar dentro da janela escolhida.
        if lote["fim"] >= indice_rompimento or lote["inicio"] < primeiro_indice_elegivel:
            continue
        if not _rompeu_referencia(rompimento, lote):
            continue
        if _houve_rompimento_anterior(velas_ate_rompimento, lote, indice_rompimento):
            continue
        candidatos.append(lote)

    if not candidatos:
        return None
    return max(candidatos, key=lambda lote: (lote["fim"], lote["inicio"]))


def classificar_confirmacao(confirmacao, lote):
    """Classifica a confirmacao consecutiva ou retorna None."""
    abertura = lote["abertura"]

    if lote["cor"] == "vermelho" and eh_vermelha(confirmacao):
        if (
            confirmacao["min"] <= abertura
            and confirmacao["close"] > abertura
            and confirmacao["close"] > lote["maxima"]
        ):
            return "call", "CONTINUACAO_REJEICAO"
        if lote["minima"] <= confirmacao["close"] < abertura:
            return "put", "FALSO_ROMPIMENTO_RETORNO"

    if lote["cor"] == "verde" and eh_verde(confirmacao):
        if (
            confirmacao["max"] >= abertura
            and confirmacao["close"] < abertura
            and confirmacao["close"] < lote["minima"]
        ):
            return "put", "CONTINUACAO_REJEICAO"
        if abertura < confirmacao["close"] <= lote["maxima"]:
            return "call", "FALSO_ROMPIMENTO_RETORNO"

    return None


def detectar_sinal(velas_fechadas):
    """Detecta um sinal cuja confirmacao e a ultima vela fechada."""
    if len(velas_fechadas) < 4:
        return None

    confirmacao = velas_fechadas[-1]
    velas_ate_rompimento = velas_fechadas[:-1]
    rompimento = velas_ate_rompimento[-1]
    lote = localizar_lote_rompido(velas_ate_rompimento)
    if not lote:
        return None

    classificacao = classificar_confirmacao(confirmacao, lote)
    if not classificacao:
        return None

    direcao, padrao = classificacao
    return {
        "direcao": direcao,
        "padrao": padrao,
        "lote": lote,
        "nivel_entrada": lote["abertura"],
        "rompimento_from": rompimento["from"],
        "confirmacao_from": confirmacao["from"],
    }


def criar_entrada_pendente(sinal):
    inicio = sinal["confirmacao_from"] + CONFIG["timeframe"]
    return {
        **sinal,
        "inicio_entrada": inicio,
        "expira_em": inicio + CONFIG["timeframe"],
        "tentativa_realizada": False,
    }


def vela_tocou_nivel(vela, nivel):
    return vela["min"] <= nivel <= vela["max"]


def executar_ordem(api, par, mercado, direcao):
    if mercado == "DIGITAL":
        sucesso, ordem_id = api.buy_digital_spot_v2(
            par,
            CONFIG["valor_entrada"],
            direcao,
            1,
        )
    else:
        sucesso, ordem_id = api.buy(
            CONFIG["valor_entrada"],
            par,
            direcao,
            1,
        )
    return bool(sucesso), ordem_id


def _nome_direcao(direcao):
    return "COMPRA (CALL)" if direcao == "call" else "VENDA (PUT)"


def _nome_padrao(padrao):
    if padrao == "CONTINUACAO_REJEICAO":
        return "CONTINUACAO POR REJEICAO"
    return "FALSO ROMPIMENTO COM RETORNO AO LOTE"


def formatar_alerta_toque(par, mercado, pendente, status, detalhe=""):
    mensagem = (
        f"{_nome_direcao(pendente['direcao'])} - {par} [{mercado}]\n"
        f"Padrao: {_nome_padrao(pendente['padrao'])}\n"
        f"Toque na abertura da primeira vela: {pendente['nivel_entrada']:.6f}\n"
        f"Conta: {CONFIG['conta']} | Valor: {CONFIG['valor_entrada']:.2f}\n"
        f"Status: {status}"
    )
    if detalhe:
        mensagem += f"\n{detalhe}"
    return mensagem


def monitorar_entrada_pendente(api, par, mercado, pendente, vela_atual):
    """Tenta uma unica entrada no toque ocorrido durante a vela N+1."""
    if not pendente:
        return None

    inicio_atual = vela_atual["from"]
    if inicio_atual < pendente["inicio_entrada"]:
        return pendente
    if inicio_atual >= pendente["expira_em"]:
        print(f"[{par}] Sinal expirou sem toque na abertura do lote.")
        return None
    if inicio_atual != pendente["inicio_entrada"]:
        return pendente
    if pendente["tentativa_realizada"] or not vela_tocou_nivel(
        vela_atual,
        pendente["nivel_entrada"],
    ):
        return pendente

    pendente["tentativa_realizada"] = True

    if not CONFIG["auto_executar"]:
        mensagem = formatar_alerta_toque(
            par,
            mercado,
            pendente,
            "SINAL MANUAL - SOMENTE ALERTAS",
        )
        print(f"[{par}] {mensagem.replace(chr(10), ' | ')}")
        enviar_alerta(mensagem)
        return None

    # A ordem sempre e tentada antes do WhatsApp para nao atrasar a entrada.
    try:
        sucesso, ordem_id = executar_ordem(
            api,
            par,
            mercado,
            pendente["direcao"],
        )
        if sucesso:
            status = "ORDEM EXECUTADA"
            detalhe = f"ID: {ordem_id} | Expiracao: M1 (mesma vela)"
        else:
            status = "ORDEM RECUSADA"
            detalhe = f"Motivo/ID retornado: {ordem_id}"
    except Exception as erro:
        status = "ERRO AO ENVIAR ORDEM"
        detalhe = str(erro)

    mensagem = formatar_alerta_toque(par, mercado, pendente, status, detalhe)
    print(f"[{par}] {mensagem.replace(chr(10), ' | ')}")
    enviar_alerta(mensagem)
    return None


def conectar(api):
    while True:
        try:
            conectado, motivo = api.connect()
            if conectado:
                api.change_balance(CONFIG["conta"])
                print(f"Autenticado. Conta selecionada: {CONFIG['conta']}")
                return
            print(f"Falha ao conectar: {motivo}. Nova tentativa em 5 segundos...")
        except Exception as erro:
            print(f"Erro ao conectar: {erro}. Nova tentativa em 5 segundos...")
        time.sleep(5)


def abrir_canais(api):
    print(f"[CONEXAO] Abrindo streams M1 para {len(CONFIG['pairs'])} pares...")
    for par in CONFIG["pairs"]:
        try:
            api.start_candles_stream(
                par,
                CONFIG["timeframe"],
                CONFIG["historico_stream"],
            )
        except Exception as erro:
            print(f"[{par}] Falha ao abrir stream: {erro}")
        time.sleep(0.8)


def reiniciar_canal(api, par, motivo):
    print(f"[{par}] Reiniciando somente este stream: {motivo}")
    try:
        api.stop_candles_stream(par, CONFIG["timeframe"])
    except Exception:
        pass
    time.sleep(0.3)
    try:
        api.start_candles_stream(
            par,
            CONFIG["timeframe"],
            CONFIG["historico_stream"],
        )
        print(f"[{par}] Stream reiniciado com sucesso.")
        return True
    except Exception as erro:
        print(f"[{par}] Falha ao reiniciar stream: {erro}")
        return False


def criar_nova_sessao(motivo):
    print(f"\n[CONEXAO] Criando nova sessao: {motivo}")
    nova_api = IQ_Option(CONFIG["email"], CONFIG["password"])
    conectar(nova_api)
    abrir_canais(nova_api)
    print("[CONEXAO] Nova sessao pronta. Monitoramento retomado.\n")
    return nova_api


def main():
    validar_dependencias()
    print("=" * 72)
    print("  RADAR M1 - ROMPIMENTO, REJEICAO E RETORNO AO LOTE")
    print("=" * 72)
    mercado = selecionar_mercado()
    CONFIG["auto_executar"] = selecionar_execucao_automatica()
    print(
        "Execucao automatica: "
        f"{'ATIVA' if CONFIG['auto_executar'] else 'DESATIVADA (somente alertas)'}"
    )
    print("Payout: sem filtro | Entrada fixa: 2 | Expiracao: M1")

    api = IQ_Option(CONFIG["email"], CONFIG["password"])
    conectar(api)
    abrir_canais(api)

    ultima_processada = {par: 0 for par in CONFIG["pairs"]}
    ultimo_from_stream = {par: 0 for par in CONFIG["pairs"]}
    ultimo_avanco = {par: time.monotonic() for par in CONFIG["pairs"]}
    falhas = {par: 0 for par in CONFIG["pairs"]}
    ultimo_reinicio = {par: 0.0 for par in CONFIG["pairs"]}
    entradas_pendentes = {par: None for par in CONFIG["pairs"]}

    try:
        while True:
            try:
                conectado = api.check_connect()
            except Exception as erro:
                print(f"[CONEXAO] Falha ao verificar conexao: {erro}")
                conectado = False

            if not conectado:
                api = criar_nova_sessao("conexao com a corretora foi perdida")
                agora = time.monotonic()
                ultimo_from_stream = {par: 0 for par in CONFIG["pairs"]}
                ultimo_avanco = {par: agora for par in CONFIG["pairs"]}
                falhas = {par: 0 for par in CONFIG["pairs"]}
                ultimo_reinicio = {par: agora for par in CONFIG["pairs"]}
                continue

            for par in CONFIG["pairs"]:
                try:
                    dados = api.get_realtime_candles(par, CONFIG["timeframe"])
                    minimo_velas = CONFIG["janela_lotes"] + 3
                    if not dados or len(dados) < minimo_velas:
                        falhas[par] += 1
                        agora = time.monotonic()
                        if (
                            falhas[par] >= CONFIG["falhas_maximas_por_par"]
                            and agora - ultimo_reinicio[par]
                            >= CONFIG["intervalo_reinicio_par"]
                        ):
                            reiniciar_canal(api, par, "stream sem dados suficientes")
                            ultimo_reinicio[par] = agora
                            ultimo_from_stream[par] = 0
                            ultimo_avanco[par] = agora
                            falhas[par] = 0
                        continue

                    falhas[par] = 0
                    velas = sorted(dados.values(), key=lambda vela: vela["from"])
                    velas_fechadas = velas[:-1]
                    vela_atual = velas[-1]
                    ultima_fechada = velas_fechadas[-1]

                    if ultima_fechada["from"] != ultimo_from_stream[par]:
                        ultimo_from_stream[par] = ultima_fechada["from"]
                        ultimo_avanco[par] = time.monotonic()
                    elif (
                        time.monotonic() - ultimo_avanco[par]
                        > CONFIG["tempo_maximo_sem_vela"]
                    ):
                        agora = time.monotonic()
                        if agora - ultimo_reinicio[par] >= CONFIG["intervalo_reinicio_par"]:
                            reiniciar_canal(api, par, "stream congelado")
                            ultimo_reinicio[par] = agora
                            ultimo_from_stream[par] = 0
                            ultimo_avanco[par] = agora
                            falhas[par] = 0
                        continue

                    entradas_pendentes[par] = monitorar_entrada_pendente(
                        api,
                        par,
                        mercado,
                        entradas_pendentes[par],
                        vela_atual,
                    )

                    if ultima_fechada["from"] != ultima_processada[par]:
                        sinal = detectar_sinal(velas_fechadas)
                        if sinal:
                            entradas_pendentes[par] = criar_entrada_pendente(sinal)
                            print(
                                f"[{par}] {_nome_padrao(sinal['padrao'])} "
                                f"{sinal['direcao'].upper()} armado em "
                                f"{sinal['nivel_entrada']:.6f}; aguardando toque."
                            )
                            entradas_pendentes[par] = monitorar_entrada_pendente(
                                api,
                                par,
                                mercado,
                                entradas_pendentes[par],
                                vela_atual,
                            )
                        ultima_processada[par] = ultima_fechada["from"]

                except Exception as erro:
                    falhas[par] += 1
                    print(f"[{par}] Erro no monitoramento: {erro}")
                    agora = time.monotonic()
                    if (
                        falhas[par] >= CONFIG["falhas_maximas_por_par"]
                        and agora - ultimo_reinicio[par]
                        >= CONFIG["intervalo_reinicio_par"]
                    ):
                        reiniciar_canal(api, par, "erros repetidos no stream")
                        ultimo_reinicio[par] = agora
                        ultimo_from_stream[par] = 0
                        ultimo_avanco[par] = agora
                        falhas[par] = 0

            time.sleep(CONFIG["intervalo_varredura"])
    except KeyboardInterrupt:
        print("\nRadar encerrado pelo usuario.")


if __name__ == "__main__":
    try:
        main()
    except RuntimeError as erro:
        print(f"[ERRO DE DEPENDENCIA] {erro}")
        raise SystemExit(1)

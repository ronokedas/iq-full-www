"""Radar M1 do TradeMasterPro baseado em uma sequencia de tres WINs.

O indicador original gera:

* PUT/V quando a vela abre acima da banda superior de 30 aberturas e o
  preco volta para baixo da banda;
* CALL/C quando a vela abre abaixo da banda inferior e o preco volta para
  cima da banda.

As bandas usam SMA(open, 30) e desvio-padrao AMOSTRAL (n - 1). O radar
reconstroi os sinais confirmados nas ultimas 1.000 velas M1 de cada ativo.
Depois de tres sinais vencedores consecutivos, a proxima seta produz um
pre-alerta intravela. Se a seta sobreviver ao fechamento, a entrada e
confirmada para a abertura da vela seguinte; caso contrario, e cancelada.

Este arquivo somente monitora e envia alertas. Nenhuma ordem e executada.
"""

from __future__ import annotations

import math
import os
import queue
import statistics
import sys
import threading
import time
from collections import deque
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Callable, Iterable, Sequence

try:
    import requests
except ImportError as erro:
    requests = None
    ERRO_REQUESTS = str(erro)
else:
    ERRO_REQUESTS = None

try:
    from iqoptionapi.stable_api import IQ_Option
except ImportError as erro:
    IQ_Option = None
    ERRO_IQOPTION = str(erro)
else:
    ERRO_IQOPTION = None


PERIODO = 30
MULTIPLICADOR = 2.0
TIMEFRAME = 60
TOTAL_HISTORICO = 1_000
BUFFER_STREAM = 40
INTERVALO_VARREDURA = 0.5
MINIMO_STREAM = PERIODO
FALHAS_ANTES_REINICIO = 30
INTERVALO_REINICIO = 30.0
TEMPO_STREAM_CONGELADO = 150.0

PARES_OTC = [
    "AUDCAD-OTC", "EURGBP-OTC", "EURJPY-OTC", "EURUSD-OTC",
    "GBPJPY-OTC", "GBPUSD-OTC", "NZDUSD-OTC", "USDCHF-OTC",
    "USDHKD-OTC", "USDINR-OTC", "USDJPY-OTC", "USDSGD-OTC",
    "USDZAR-OTC",
]


def _numeros_do_ambiente(valor: str | None, fallback: Sequence[str]) -> list[str]:
    if not valor:
        return list(fallback)
    return [
        numero.strip()
        for numero in valor.replace(";", ",").split(",")
        if numero.strip()
    ]


# CONFIGURACAO COMPLETA E INDEPENDENTE.
# Variaveis de ambiente, quando definidas, substituem os valores abaixo.
CONFIG = {
    "email": os.getenv("IQOPTION_EMAIL", "dicasbbom@gmail.com"),
    "password": os.getenv("IQOPTION_PASSWORD", "1P9w@w4a5"),
    "pairs": PARES_OTC,
    "whatsapp": _numeros_do_ambiente(
        os.getenv("WHATSAPP_NUMBERS"),
        ["5598988976885", "5591989340275"],
    ),
    "whatsapp_url": os.getenv(
        "WHATSAPP_URL",
        "http://localhost:3001/send-message",
    ),
    # Envia ao primeiro numero e aguarda 8 segundos antes do proximo.
    # A espera ocorre na thread do WhatsApp e nao pausa o radar de candles.
    "whatsapp_intervalo_envio": 8.0,
    "conta": "PRACTICE",
    "valor_entrada": 2.0,
    "mercado": "DIGITAL",
    "auto_executar": False,
    # Nao envia uma ordem recuperada muito depois da abertura da vela.
    "tolerancia_entrada_segundos": 5,
}


def validar_dependencias() -> None:
    faltando = []
    if requests is None:
        faltando.append(f"requests ({ERRO_REQUESTS})")
    if IQ_Option is None:
        faltando.append(f"iqoptionapi ({ERRO_IQOPTION})")
    if faltando:
        raise RuntimeError(
            "Dependencias ausentes: "
            + ", ".join(faltando)
            + ". Use o comando py deste projeto ou instale requests e iqoptionapi."
        )


def numeros_whatsapp() -> list[str]:
    numeros = CONFIG["whatsapp"]
    if isinstance(numeros, str):
        numeros = _numeros_do_ambiente(numeros, [])
    return list(
        dict.fromkeys(
            str(numero).strip()
            for numero in numeros
            if str(numero).strip()
        )
    )


def enviar_alerta(mensagem: str) -> int:
    """Envia WhatsApp sem permitir que uma falha derrube o radar."""
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


def conectar(api) -> None:
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


def selecionar_mercado() -> str:
    while True:
        print("\nQual mercado deseja operar/monitorar?")
        print("  1 - DIGITAL")
        print("  2 - BINÁRIAS/TURBO")
        escolha = input("Escolha: ").strip()
        if escolha == "1":
            return "DIGITAL"
        if escolha == "2":
            return "BINARY"
        print("Opção inválida. Digite 1 ou 2.")


def selecionar_execucao_automatica() -> bool:
    while True:
        print("\nDeseja que o sistema faça entradas automaticamente?")
        print(f"  Conta: {CONFIG['conta']} | Valor: {CONFIG['valor_entrada']:.2f}")
        print("  1 - SIM, executar automaticamente na confirmação")
        print("  2 - NÃO, somente alertas")
        escolha = input("Escolha: ").strip().lower()
        if escolha in {"1", "sim", "s"}:
            return True
        if escolha in {"2", "nao", "não", "n"}:
            return False
        print("Opção inválida. Digite 1 ou 2.")


def executar_ordem(api, par: str, mercado: str, direcao: str) -> tuple[bool, object]:
    """Envia uma unica ordem M1 no mercado escolhido pelo usuario."""
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


@dataclass(frozen=True)
class Vela:
    """Representacao normalizada de um candle da IQ Option."""

    inicio: int
    abertura: float
    fechamento: float
    maxima: float
    minima: float


@dataclass(frozen=True)
class Engolfo:
    """As duas velas que confirmaram o novo padrao independente."""

    anterior: Vela
    atual: Vela


@dataclass(frozen=True)
class Sinal:
    """Sinal detectado pelo TradeMasterPro."""

    inicio: int
    direcao: str
    seta: str
    banda: float
    abertura: float
    estado: str = "confirmado"
    alertado: bool = False
    padroes: tuple[str, ...] = ()
    engolfo: Engolfo | None = None


@dataclass(frozen=True)
class Evento:
    """Evento produzido pela logica e posteriormente publicado."""

    tipo: str
    mensagem: str
    whatsapp: bool = False
    sinal: Sinal | None = None
    par: str = ""


@dataclass
class EstadoPar:
    """Todo o estado necessario para monitorar um unico ativo."""

    par: str
    historico: deque[Vela] = field(
        default_factory=lambda: deque(maxlen=TOTAL_HISTORICO)
    )
    sequencia_wins: int = 0
    ultimos_wins: deque[Sinal] = field(default_factory=lambda: deque(maxlen=3))
    candidato: Sinal | None = None
    pendente: Sinal | None = None
    ultima_vela_alertada: int = 0
    ultimo_processado: int = 0
    armado_apos: int = 0
    sinais_detectados: int = 0
    ultimo_from_stream: int = 0
    ultimo_avanco: float = field(default_factory=time.monotonic)
    falhas_stream: int = 0
    ultimo_reinicio: float = 0.0

    @property
    def armado(self) -> bool:
        return (
            self.sequencia_wins >= 3
            and self.candidato is None
            and self.pendente is None
        )


class FilaWhatsApp:
    """Serializa os envios sem bloquear a varredura das velas."""

    def __init__(self) -> None:
        self._fila: queue.Queue[str] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def enviar(self, mensagem: str) -> None:
        with self._lock:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._trabalhar,
                    name="whatsapp-trademasterpro",
                    daemon=True,
                )
                self._thread.start()
        self._fila.put(mensagem)

    def _trabalhar(self) -> None:
        while True:
            mensagem = self._fila.get()
            try:
                enviar_alerta(mensagem)
            except Exception as erro:
                print(f"[WHATSAPP] Erro inesperado, radar mantido ativo: {erro}")
            finally:
                self._fila.task_done()


FILA_WHATSAPP = FilaWhatsApp()


def normalizar_vela(dado: dict) -> Vela:
    """Converte e valida o formato de candle retornado pela API."""
    vela = Vela(
        inicio=int(dado["from"]),
        abertura=float(dado["open"]),
        fechamento=float(dado["close"]),
        maxima=float(dado["max"]),
        minima=float(dado["min"]),
    )
    valores = (vela.abertura, vela.fechamento, vela.maxima, vela.minima)
    if not all(math.isfinite(valor) for valor in valores):
        raise ValueError("Candle possui preco nao finito")
    if vela.maxima < vela.minima:
        raise ValueError("Candle possui maxima menor que a minima")
    return vela


def normalizar_velas(dados: Iterable[dict]) -> list[Vela]:
    """Ordena candles e elimina timestamps duplicados."""
    unicas: dict[int, Vela] = {}
    for dado in dados:
        try:
            vela = normalizar_vela(dado)
        except (KeyError, TypeError, ValueError):
            continue
        unicas[vela.inicio] = vela
    return [unicas[inicio] for inicio in sorted(unicas)]


def velas_continuas(velas: Sequence[Vela]) -> bool:
    return all(
        atual.inicio == anterior.inicio + TIMEFRAME
        for anterior, atual in zip(velas, velas[1:])
    )


def calcular_bandas(aberturas: Sequence[float]) -> tuple[float, float]:
    """Calcula SMA +/- 2 desvios amostrais nas ultimas 30 aberturas."""
    if len(aberturas) < PERIODO:
        raise ValueError(f"Sao necessarias {PERIODO} aberturas")
    janela = [float(valor) for valor in aberturas[-PERIODO:]]
    media = statistics.fmean(janela)
    desvio = statistics.stdev(janela)
    return media + MULTIPLICADOR * desvio, media - MULTIPLICADOR * desvio


def detectar_sinal(
    janela: Sequence[Vela],
    preco_atual: float | None = None,
    estado: str = "confirmado",
) -> Sinal | None:
    """Detecta o C/CALL ou V/PUT usando a ultima vela da janela."""
    if len(janela) < PERIODO:
        return None
    ultimas = list(janela[-PERIODO:])
    if not velas_continuas(ultimas):
        return None

    atual = ultimas[-1]
    preco = atual.fechamento if preco_atual is None else float(preco_atual)
    superior, inferior = calcular_bandas([vela.abertura for vela in ultimas])

    if atual.abertura > superior and preco < superior:
        return Sinal(
            inicio=atual.inicio,
            direcao="put",
            seta="V",
            banda=superior,
            abertura=atual.abertura,
            estado=estado,
        )
    if atual.abertura < inferior and preco > inferior:
        return Sinal(
            inicio=atual.inicio,
            direcao="call",
            seta="C",
            banda=inferior,
            abertura=atual.abertura,
            estado=estado,
        )
    return None


def detectar_engolfo(janela: Sequence[Vela], sinal: Sinal | None) -> Engolfo | None:
    """Confirma o engolfo estrito somente na vela fechada do sinal."""
    if sinal is None or len(janela) < 2:
        return None
    anterior, atual = janela[-2], janela[-1]
    if atual.inicio != anterior.inicio + TIMEFRAME or sinal.inicio != atual.inicio:
        return None

    if sinal.direcao == "put":
        anterior_verde = anterior.fechamento > anterior.abertura
        atual_vermelha = atual.fechamento < atual.abertura
        if (
            anterior_verde
            and atual_vermelha
            and atual.maxima > anterior.maxima
            and atual.fechamento < anterior.abertura
        ):
            return Engolfo(anterior=anterior, atual=atual)

    if sinal.direcao == "call":
        anterior_vermelha = anterior.fechamento < anterior.abertura
        atual_verde = atual.fechamento > atual.abertura
        if (
            anterior_vermelha
            and atual_verde
            and atual.minima < anterior.minima
            and atual.fechamento > anterior.abertura
        ):
            return Engolfo(anterior=anterior, atual=atual)

    return None


def qualificar_sinal(
    sinal: Sinal,
    janela: Sequence[Vela],
    sequencia_3_wins: bool = False,
) -> Sinal:
    """Anexa as origens sem transformar uma vela em duas operacoes."""
    padroes: list[str] = []
    if sequencia_3_wins:
        padroes.append("SEQUENCIA_3_WINS")
    engolfo = detectar_engolfo(janela, sinal)
    if engolfo is not None:
        padroes.append("ENGOLFO")
    return replace(sinal, padroes=tuple(padroes), engolfo=engolfo)


def classificar_resultado(sinal: Sinal, proxima: Vela) -> str:
    """Classifica a cor da vela imediatamente posterior ao sinal."""
    if proxima.inicio != sinal.inicio + TIMEFRAME:
        return "INVALIDO"
    if proxima.fechamento == proxima.abertura:
        return "DOJI"
    if sinal.direcao == "call":
        return "WIN" if proxima.fechamento > proxima.abertura else "LOSS"
    return "WIN" if proxima.fechamento < proxima.abertura else "LOSS"


def _aplicar_resultado(
    estado: EstadoPar,
    sinal: Sinal,
    resultado: str,
    vela_resultado: Vela,
) -> None:
    if resultado == "WIN":
        estado.sequencia_wins += 1
        estado.ultimos_wins.append(sinal)
        if estado.sequencia_wins >= 3:
            # Somente velas posteriores ao fechamento deste resultado podem
            # ser consideradas a "proxima seta" da sequencia conhecida.
            estado.armado_apos = vela_resultado.inicio
    else:
        estado.sequencia_wins = 0
        estado.ultimos_wins.clear()
        estado.armado_apos = 0


def reconstruir_estado(par: str, velas_fechadas: Sequence[Vela]) -> EstadoPar:
    """Reconstroi o placar cronologico nas velas historicas fornecidas."""
    velas = sorted({vela.inicio: vela for vela in velas_fechadas}.values(), key=lambda v: v.inicio)
    velas = velas[-TOTAL_HISTORICO:]
    estado = EstadoPar(par=par)
    estado.historico.extend(velas)
    if velas:
        estado.ultimo_processado = velas[-1].inicio
        estado.ultimo_from_stream = velas[-1].inicio

    for indice in range(PERIODO - 1, len(velas)):
        sinal = detectar_sinal(velas[indice - PERIODO + 1:indice + 1])
        if sinal is None:
            continue
        estado.sinais_detectados += 1
        if indice + 1 >= len(velas):
            estado.pendente = sinal
            continue
        proxima = velas[indice + 1]
        resultado = classificar_resultado(sinal, proxima)
        _aplicar_resultado(estado, sinal, resultado, proxima)

    return estado


def _hora(timestamp: int) -> str:
    return datetime.fromtimestamp(timestamp).strftime("%d/%m/%Y %H:%M:%S")


def _direcao_texto(sinal: Sinal) -> str:
    return "COMPRA (CALL)" if sinal.direcao == "call" else "VENDA (PUT)"


def _padroes_texto(sinal: Sinal) -> str:
    nomes = {
        "SEQUENCIA_3_WINS": "SEQUÊNCIA DE 3 WINs",
        "ENGOLFO": "ENGOLFO",
    }
    return " + ".join(nomes.get(item, item) for item in sinal.padroes) or "SINAL"


def _detalhes_engolfo(sinal: Sinal) -> str:
    if sinal.engolfo is None:
        return ""
    anterior = sinal.engolfo.anterior
    atual = sinal.engolfo.atual
    cor_anterior = "VERDE" if anterior.fechamento > anterior.abertura else "VERMELHA"
    cor_atual = "VERDE" if atual.fechamento > atual.abertura else "VERMELHA"
    return (
        "\n🕯️ *PADRÃO DE ENGOLFO CONFIRMADO*\n"
        f"Anterior {cor_anterior}: O {anterior.abertura:.6f} | "
        f"H {anterior.maxima:.6f} | L {anterior.minima:.6f} | "
        f"C {anterior.fechamento:.6f}\n"
        f"Sinal {cor_atual}: O {atual.abertura:.6f} | "
        f"H {atual.maxima:.6f} | L {atual.minima:.6f} | "
        f"C {atual.fechamento:.6f}"
    )


def _linha_ultimos_wins(estado: EstadoPar) -> str:
    if not estado.ultimos_wins:
        return "sem registros"
    return " | ".join(
        f"{sinal.seta} {_hora(sinal.inicio)[:16]}"
        for sinal in estado.ultimos_wins
    )


def mensagem_pre_alerta(estado: EstadoPar, sinal: Sinal) -> str:
    return (
        "⚠️ *PRÉ-ALERTA — PRÓXIMO SINAL APÓS 3 WINs*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Ativo: *{estado.par}*\n"
        "⏱️ Timeframe: *M1*\n"
        f"🎯 Direção possível: *{_direcao_texto(sinal)}* | Seta {sinal.seta}\n"
        f"🔥 Sequência atual: *{estado.sequencia_wins} WINs consecutivos*\n"
        f"📐 Banda atravessada: {sinal.banda:.6f}\n"
        f"🕒 Detectado: {_hora(sinal.inicio)}\n"
        f"🏆 Últimos WINs: {_linha_ultimos_wins(estado)}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "⏳ A vela ainda está em formação. Aguarde a confirmação."
    )


def mensagem_confirmacao(estado: EstadoPar, sinal: Sinal) -> str:
    entrada = sinal.inicio + TIMEFRAME
    if sinal.padroes == ("ENGOLFO",):
        titulo = "ENGOLFO CONFIRMADO — TRADEMASTERPRO"
    elif "ENGOLFO" in sinal.padroes and "SEQUENCIA_3_WINS" in sinal.padroes:
        titulo = "ENTRADA CONFIRMADA — 3 WINs + ENGOLFO"
    else:
        titulo = "ENTRADA CONFIRMADA — TRADEMASTERPRO"
    return (
        f"🚨 *{titulo}*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Ativo: *{estado.par}*\n"
        f"🎯 Operação: *{_direcao_texto(sinal)}*\n"
        f"🔎 Motivo: *{_padroes_texto(sinal)}*\n"
        "⏱️ Expiração: *M1*\n"
        f"🕒 Entrada: *abertura da vela de {_hora(entrada)}*\n"
        f"📐 Banda: {sinal.banda:.6f}\n"
        f"{_detalhes_engolfo(sinal)}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "✅ Padrão validado no fechamento."
    )


def mensagem_cancelamento(estado: EstadoPar, sinal: Sinal, motivo: str = "") -> str:
    detalhe = motivo or "A seta desapareceu antes do fechamento da vela."
    return (
        "❌ *SINAL CANCELADO — NÃO ENTRAR*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Ativo: *{estado.par}* | M1\n"
        f"🎯 Seta observada: {sinal.seta} — {_direcao_texto(sinal)}\n"
        f"🕒 Vela: {_hora(sinal.inicio)}\n"
        f"ℹ️ Motivo: {detalhe}\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "🔥 A sequência anterior permanece armada."
    )


def mensagem_resultado(
    estado: EstadoPar,
    sinal: Sinal,
    resultado: str,
    vela: Vela,
) -> str:
    icone = {"WIN": "✅", "LOSS": "❌", "DOJI": "⚪"}.get(resultado, "⚠️")
    titulo = resultado if resultado != "INVALIDO" else "RESULTADO INDETERMINADO"
    sequencia = (
        f"{estado.sequencia_wins} WINs — radar continua armado"
        if estado.sequencia_wins >= 3
        else "sequência zerada; aguardando novos 3 WINs"
    )
    return (
        f"{icone} *{titulo} — RESULTADO M1*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 Ativo: *{estado.par}*\n"
        f"🎯 Operação: {_direcao_texto(sinal)}\n"
        f"🔎 Motivo: {_padroes_texto(sinal)}\n"
        f"🕒 Vela avaliada: {_hora(vela.inicio)}\n"
        f"📈 Open: {vela.abertura:.6f} | Close: {vela.fechamento:.6f}\n"
        f"🔥 Estado: {sequencia}\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )


def monitorar_intravela(
    estado: EstadoPar,
    vela_atual: Vela,
) -> list[Evento]:
    """Produz no maximo um pre-alerta por ativo/vela."""
    if not estado.armado:
        return []
    if vela_atual.inicio <= estado.armado_apos:
        return []
    if vela_atual.inicio == estado.ultima_vela_alertada:
        return []

    anteriores = list(estado.historico)[-(PERIODO - 1):]
    sinal = detectar_sinal(
        anteriores + [vela_atual],
        preco_atual=vela_atual.fechamento,
        estado="intravela",
    )
    if sinal is None:
        return []

    sinal = replace(
        sinal,
        alertado=True,
        padroes=("SEQUENCIA_3_WINS",),
    )
    estado.candidato = sinal
    estado.ultima_vela_alertada = vela_atual.inicio
    return [
        Evento(
            tipo="PRE_ALERTA",
            mensagem=mensagem_pre_alerta(estado, sinal),
            whatsapp=True,
        )
    ]


def _evento_resultado(
    estado: EstadoPar,
    sinal: Sinal,
    resultado: str,
    vela: Vela,
) -> Evento:
    tipo = f"RESULTADO_{resultado}"
    if sinal.alertado:
        return Evento(
            tipo=tipo,
            mensagem=mensagem_resultado(estado, sinal, resultado, vela),
            whatsapp=True,
        )
    return Evento(
        tipo=tipo,
        mensagem=(
            f"[{estado.par}] Sinal {sinal.seta}/{sinal.direcao.upper()} de "
            f"{_hora(sinal.inicio)}: {resultado}. "
            f"Sequencia atual: {estado.sequencia_wins}."
        ),
        whatsapp=False,
    )


def processar_fechamento(estado: EstadoPar, vela: Vela) -> list[Evento]:
    """Processa uma nova vela fechada em ordem cronologica."""
    if vela.inicio <= estado.ultimo_processado:
        return []

    eventos: list[Evento] = []
    estado.historico.append(vela)
    estado.ultimo_processado = vela.inicio

    # Primeiro resolve o sinal da vela imediatamente anterior. Somente depois
    # disso o terceiro WIN passa a ser conhecido e pode armar velas futuras.
    if estado.pendente is not None:
        pendente = estado.pendente
        if vela.inicio >= pendente.inicio + TIMEFRAME:
            resultado = classificar_resultado(pendente, vela)
            _aplicar_resultado(estado, pendente, resultado, vela)
            eventos.append(_evento_resultado(estado, pendente, resultado, vela))
            estado.pendente = None

    janela = list(estado.historico)[-PERIODO:]

    # Um candidato alertado e validado/cancelado exatamente no fechamento da
    # sua propria vela. Nao ha sinal oposto possivel com a mesma abertura.
    if estado.candidato is not None:
        candidato = estado.candidato
        if candidato.inicio == vela.inicio:
            confirmado = detectar_sinal(janela, estado="confirmado")
            estado.candidato = None
            if confirmado is not None and confirmado.direcao == candidato.direcao:
                confirmado = qualificar_sinal(
                    confirmado,
                    janela,
                    sequencia_3_wins=True,
                )
                confirmado = replace(confirmado, alertado=True)
                estado.pendente = confirmado
                estado.sinais_detectados += 1
                eventos.append(
                    Evento(
                        tipo="CONFIRMACAO",
                        mensagem=mensagem_confirmacao(estado, confirmado),
                        whatsapp=True,
                        sinal=confirmado,
                        par=estado.par,
                    )
                )
            else:
                eventos.append(
                    Evento(
                        tipo="CANCELAMENTO",
                        mensagem=mensagem_cancelamento(estado, candidato),
                        whatsapp=True,
                    )
                )
            return eventos

        if candidato.inicio < vela.inicio:
            estado.candidato = None
            eventos.append(
                Evento(
                    tipo="CANCELAMENTO",
                    mensagem=mensagem_cancelamento(
                        estado,
                        candidato,
                        "Não foi possível validar a vela do sinal após uma lacuna de dados.",
                    ),
                    whatsapp=True,
                )
            )

    # Sinais confirmados sem pre-alerta (ativo desarmado, bloqueado ou periodo
    # de reconexao) continuam fazendo parte da sequencia estatistica.
    sinal = detectar_sinal(janela, estado="confirmado")
    if sinal is not None:
        sinal = qualificar_sinal(sinal, janela)
        if "ENGOLFO" in sinal.padroes:
            sinal = replace(sinal, alertado=True)
            estado.pendente = sinal
            estado.sinais_detectados += 1
            eventos.append(
                Evento(
                    tipo="CONFIRMACAO",
                    mensagem=mensagem_confirmacao(estado, sinal),
                    whatsapp=True,
                    sinal=sinal,
                    par=estado.par,
                )
            )
            return eventos

        estado.pendente = sinal
        estado.sinais_detectados += 1
        eventos.append(
            Evento(
                tipo="SINAL_INTERNO",
                mensagem=(
                    f"[{estado.par}] Sinal confirmado {sinal.seta}/"
                    f"{sinal.direcao.upper()} em {_hora(sinal.inicio)}; "
                    "aguardando a vela seguinte."
                ),
                whatsapp=False,
            )
        )

    return eventos


def despachar_eventos(
    eventos: Iterable[Evento],
    enviar_whatsapp: Callable[[str], object] | None = None,
    imprimir: Callable[[str], object] = print,
) -> None:
    remetente = FILA_WHATSAPP.enviar if enviar_whatsapp is None else enviar_whatsapp
    for evento in eventos:
        imprimir(f"\n{evento.mensagem}\n")
        if evento.whatsapp:
            try:
                remetente(evento.mensagem)
            except Exception as erro:
                imprimir(f"[WHATSAPP] Erro inesperado, radar mantido ativo: {erro}")


def processar_ordens_e_despachar(api, eventos: Iterable[Evento]) -> None:
    """Executa a ordem de confirmacao antes de enfileirar o WhatsApp."""
    processados: list[Evento] = []
    for evento in eventos:
        if evento.tipo != "CONFIRMACAO" or evento.sinal is None:
            processados.append(evento)
            continue

        mercado = CONFIG["mercado"]
        if not CONFIG["auto_executar"]:
            detalhe = (
                f"\n🔔 Modo manual: nenhuma ordem foi enviada. "
                f"Mercado selecionado: {mercado}."
            )
        else:
            inicio_entrada = evento.sinal.inicio + TIMEFRAME
            atraso = max(0, _timestamp_servidor(api) - inicio_entrada)
            if atraso > CONFIG["tolerancia_entrada_segundos"]:
                detalhe = (
                    "\n⏰ *ORDEM AUTOMÁTICA NÃO ENVIADA*\n"
                    f"A confirmação chegou {atraso}s após a abertura; "
                    "proteção contra entrada atrasada acionada."
                )
            else:
                try:
                    sucesso, ordem_id = executar_ordem(
                        api,
                        evento.par,
                        mercado,
                        evento.sinal.direcao,
                    )
                    if sucesso:
                        detalhe = (
                            "\n🤖 *ORDEM AUTOMÁTICA EXECUTADA*\n"
                            f"Mercado: {mercado} | Conta: {CONFIG['conta']} | "
                            f"Valor: {CONFIG['valor_entrada']:.2f}\n"
                            f"🧾 ID: {ordem_id}"
                        )
                    else:
                        detalhe = (
                            "\n⚠️ *ORDEM AUTOMÁTICA RECUSADA*\n"
                            f"Mercado: {mercado} | Retorno: {ordem_id}"
                        )
                except Exception as erro:
                    detalhe = (
                        "\n❌ *ERRO AO ENVIAR ORDEM AUTOMÁTICA*\n"
                        f"Detalhe: {erro}"
                    )
        processados.append(replace(evento, mensagem=evento.mensagem + detalhe))

    despachar_eventos(processados)


def _timestamp_servidor(api) -> int:
    try:
        timestamp = int(api.get_server_timestamp())
        if timestamp > 0:
            return timestamp
    except Exception:
        pass
    return int(time.time())


def obter_historico(api, par: str) -> list[Vela]:
    agora = _timestamp_servidor(api)
    dados = api.get_candles(par, TIMEFRAME, TOTAL_HISTORICO, agora)
    velas = normalizar_velas(dados or [])
    return [vela for vela in velas if vela.inicio + TIMEFRAME <= agora]


def abrir_stream(api, par: str) -> bool:
    try:
        resultado = api.start_candles_stream(par, TIMEFRAME, BUFFER_STREAM)
        return resultado is not False
    except Exception as erro:
        print(f"[{par}] Falha ao abrir stream: {erro}")
        return False


def reiniciar_stream(api, estado: EstadoPar, motivo: str) -> None:
    agora = time.monotonic()
    if agora - estado.ultimo_reinicio < INTERVALO_REINICIO:
        return
    estado.ultimo_reinicio = agora
    print(f"[{estado.par}] Reiniciando stream: {motivo}")
    try:
        api.stop_candles_stream(estado.par, TIMEFRAME)
    except Exception:
        pass
    time.sleep(0.3)
    if abrir_stream(api, estado.par):
        estado.falhas_stream = 0
        estado.ultimo_from_stream = 0
        estado.ultimo_avanco = time.monotonic()
        print(f"[{estado.par}] Stream reiniciado.")


def sincronizar_historico(api, estado: EstadoPar) -> None:
    """Recupera velas perdidas sem reconstruir/duplicar o estado inteiro."""
    try:
        recebidas = obter_historico(api, estado.par)
    except Exception as erro:
        print(f"[{estado.par}] Falha ao sincronizar historico: {erro}")
        return
    for vela in recebidas:
        if vela.inicio > estado.ultimo_processado:
            processar_ordens_e_despachar(api, processar_fechamento(estado, vela))


def preparar_ativos(api) -> dict[str, EstadoPar]:
    estados: dict[str, EstadoPar] = {}
    pares = list(CONFIG["pairs"])
    print(f"\n[INICIALIZAÇÃO] Analisando 1.000 candles de {len(pares)} pares...\n")

    for indice, par in enumerate(pares, start=1):
        try:
            historico = obter_historico(api, par)
            estado = reconstruir_estado(par, historico)
            estados[par] = estado
            if estado.pendente is not None:
                status = "AGUARDANDO RESULTADO DO ÚLTIMO SINAL"
            elif estado.sequencia_wins >= 3:
                status = "ARMADO"
            elif estado.sinais_detectados < 3:
                status = "HISTÓRICO INSUFICIENTE"
            else:
                status = "DESARMADO"
            print(
                f"[{indice:02d}/{len(pares):02d}] {par}: {status} | "
                f"sinais={estado.sinais_detectados} | "
                f"sequência={estado.sequencia_wins}"
            )
        except Exception as erro:
            print(f"[{par}] Erro no histórico: {erro}")
            estados[par] = EstadoPar(par=par)

        abrir_stream(api, par)
        time.sleep(0.2)

    return estados


def criar_sessao() -> object:
    api = IQ_Option(CONFIG["email"], CONFIG["password"])
    conectar(api)
    return api


def monitorar(api, estados: dict[str, EstadoPar]) -> None:
    while True:
        try:
            conectado = bool(api.check_connect())
        except Exception:
            conectado = False

        if not conectado:
            print("\n[CONEXÃO] Sessão perdida. Criando nova conexão...")
            api = criar_sessao()
            for estado in estados.values():
                abrir_stream(api, estado.par)
                sincronizar_historico(api, estado)
            print("[CONEXÃO] Monitoramento retomado.\n")

        servidor_agora = _timestamp_servidor(api)
        for par, estado in estados.items():
            try:
                dados = api.get_realtime_candles(par, TIMEFRAME)
                if not dados or len(dados) < MINIMO_STREAM:
                    estado.falhas_stream += 1
                    if estado.falhas_stream >= FALHAS_ANTES_REINICIO:
                        reiniciar_stream(api, estado, "dados insuficientes")
                    continue

                velas = normalizar_velas(dados.values())
                if len(velas) < MINIMO_STREAM:
                    estado.falhas_stream += 1
                    continue
                estado.falhas_stream = 0

                ultimo_from = velas[-1].inicio
                if ultimo_from != estado.ultimo_from_stream:
                    estado.ultimo_from_stream = ultimo_from
                    estado.ultimo_avanco = time.monotonic()
                elif time.monotonic() - estado.ultimo_avanco > TEMPO_STREAM_CONGELADO:
                    reiniciar_stream(api, estado, "stream congelado")
                    sincronizar_historico(api, estado)
                    continue

                fechadas = [
                    vela
                    for vela in velas
                    if vela.inicio + TIMEFRAME <= servidor_agora
                ]
                for vela in fechadas:
                    if vela.inicio > estado.ultimo_processado:
                        # Se o buffer pulou mais de uma vela, tenta preencher
                        # antes de classificar o resultado como invalido.
                        if (
                            estado.ultimo_processado
                            and vela.inicio > estado.ultimo_processado + TIMEFRAME
                        ):
                            sincronizar_historico(api, estado)
                            break
                        processar_ordens_e_despachar(
                            api,
                            processar_fechamento(estado, vela),
                        )

                abertas = [
                    vela
                    for vela in velas
                    if vela.inicio + TIMEFRAME > servidor_agora
                ]
                if abertas:
                    processar_ordens_e_despachar(
                        api,
                        monitorar_intravela(estado, abertas[-1]),
                    )

            except Exception as erro:
                estado.falhas_stream += 1
                print(f"[{par}] Erro no monitoramento: {erro}")
                if estado.falhas_stream >= FALHAS_ANTES_REINICIO:
                    reiniciar_stream(api, estado, "erros repetidos")

        time.sleep(INTERVALO_VARREDURA)


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    validar_dependencias()
    print("=" * 76)
    print("  RADAR TRADEMASTERPRO M1 — 3 WINs + PRÓXIMO SINAL")
    print("=" * 76)
    CONFIG["mercado"] = selecionar_mercado()
    CONFIG["auto_executar"] = selecionar_execucao_automatica()
    modo = "ENTRADAS AUTOMÁTICAS" if CONFIG["auto_executar"] else "SOMENTE ALERTAS"
    print(
        f"\nModo: {modo} | Mercado: {CONFIG['mercado']} | "
        f"Conta: {CONFIG['conta']} | Valor: {CONFIG['valor_entrada']:.2f}"
    )
    print("Expiração M1 | Resultado estatístico pela cor da próxima vela")
    print(f"Pares: {len(CONFIG['pairs'])} OTC | Histórico: 1.000 candles por par")

    api = criar_sessao()
    estados = preparar_ativos(api)
    print("\n[PRONTO] Radar ao vivo iniciado. Pressione Ctrl+C para encerrar.\n")
    monitorar(api, estados)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nRadar encerrado pelo usuário.")
    except RuntimeError as erro:
        print(f"[ERRO DE DEPENDÊNCIA] {erro}")
        raise SystemExit(1)

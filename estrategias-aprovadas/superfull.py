"""SuperFull - Sistema Unificado de Estratégias EvePulse para IQ Option.

Este sistema integra todas as estratégias documentadas no catálogo EvePulse,
permitindo que o usuário selecione quais estratégias deseja monitorar e opere
automaticamente quando qualquer uma delas gerar um sinal.

Estratégias disponíveis:
- Principais (S1-S17): Motor canônico usado pelo scanner e robô de produção
- Laboratório (S1-S10 Lab): Implementações experimentais

Autor: EvePulse System
Versão: 1.0
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
from typing import Callable, Iterable, Sequence, Optional, Dict, List, Any

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


# ============================================================================
# CATÁLOGO DE ESTRATÉGIAS DISPONÍVEIS
# ============================================================================
ESTRATEGIAS_DISPONIVEIS = {
    1: {"id": "S1", "nome": "Três Velas Reversão", "timeframe": "M1", "tipo": "Principal"},
    2: {"id": "S5", "nome": "Primeiro Retorno M1", "timeframe": "M1", "tipo": "Principal"},
    3: {"id": "S5-M5", "nome": "Primeiro Retorno M5", "timeframe": "M1/M5", "tipo": "Principal"},
    4: {"id": "S5-M15", "nome": "Primeiro Retorno M15", "timeframe": "M1/M15", "tipo": "Principal"},
    5: {"id": "S9", "nome": "Lateral H1 Reversão", "timeframe": "M1/H1", "tipo": "Principal"},
    6: {"id": "S13", "nome": "Pavios de Rejeição", "timeframe": "M1", "tipo": "Principal"},
    7: {"id": "S14", "nome": "Continuação Rejeição Rompimento", "timeframe": "M1", "tipo": "Manual"},
    8: {"id": "S15", "nome": "Falso Rompimento", "timeframe": "M1", "tipo": "Manual"},
    9: {"id": "S16", "nome": "Engolfo M5 na Abertura M15", "timeframe": "M5/M15", "tipo": "Manual"},
    10: {"id": "S17", "nome": "Rompimento Dupla Posição", "timeframe": "M5", "tipo": "Manual"},
    11: {"id": "S1-Lab", "nome": "Engolfo com Retorno (Lab)", "timeframe": "M1", "tipo": "Laboratório"},
    12: {"id": "S2-Lab", "nome": "Zonas 3 M15 (Lab)", "timeframe": "M1/M15", "tipo": "Laboratório"},
    13: {"id": "S6-Lab", "nome": "Varredura M5 (Lab)", "timeframe": "M5", "tipo": "Laboratório"},
    14: {"id": "S7-Lab", "nome": "Pavio + Reversão (Lab)", "timeframe": "M1", "tipo": "Laboratório"},
    15: {"id": "S10-Lab", "nome": "Toques Nível (Lab)", "timeframe": "M1", "tipo": "Laboratório"},
}

TIMEFRAMES_SEGUNDOS = {
    "M1": 60,
    "M5": 300,
    "M15": 900,
    "H1": 3600,
}

PARES_OTC = [
    "AUDCAD-OTC", "EURGBP-OTC", "EURJPY-OTC", "EURUSD-OTC",
    "GBPJPY-OTC", "GBPUSD-OTC", "NZDUSD-OTC", "USDCHF-OTC",
    "USDHKD-OTC", "USDINR-OTC", "USDJPY-OTC", "USDSGD-OTC",
    "USDZAR-OTC",
]

PARES_PRINCIPAIS = [
    "EURUSD", "GBPUSD", "USDJPY", "EURJPY", "EURGBP", "USDCHF",
]


# ============================================================================
# CONFIGURAÇÃO DO SISTEMA
# ============================================================================
@dataclass
class ConfigSistema:
    email: str = ""
    password: str = ""
    conta: str = "PRACTICE"  # REAL ou PRACTICE
    mercado: str = "DIGITAL"  # DIGITAL ou BINARY
    valor_entrada: float = 2.0
    auto_executar: bool = False
    estrategias_ativas: set[int] = field(default_factory=set)
    pares: list[str] = field(default_factory=lambda: PARES_OTC.copy())
    tolerancia_entrada_segundos: int = 5


config = ConfigSistema()


# ============================================================================
# FUNÇÕES DE AUTENTICAÇÃO E CONEXÃO
# ============================================================================
def validar_dependencias() -> bool:
    """Verifica se todas as dependências estão instaladas."""
    faltando = []
    if requests is None:
        faltando.append(f"requests ({ERRO_REQUESTS})")
    if IQ_Option is None:
        faltando.append(f"iqoptionapi ({ERRO_IQOPTION})")
    if faltando:
        print("\n❌ Dependências ausentes:")
        for dep in faltando:
            print(f"   - {dep}")
        print("\nInstale com: pip install requests iqoptionapi")
        return False
    return True


def solicitar_credenciais() -> tuple[str, str]:
    """Solicita email e senha do usuário."""
    print("\n" + "=" * 72)
    print("  SUPERFULL - SISTEMA UNIFICADO EVEPULSE")
    print("=" * 72)
    
    email = input("\n📧 Digite seu email da IQ Option: ").strip()
    while not email or "@" not in email:
        print("❌ Email inválido. Tente novamente.")
        email = input("\n📧 Digite seu email da IQ Option: ").strip()
    
    password = input("🔑 Digite sua senha: ").strip()
    while not password:
        print("❌ Senha não pode ser vazia. Tente novamente.")
        password = input("🔑 Digite sua senha: ").strip()
    
    return email, password


def selecionar_conta() -> str:
    """Permite ao usuário escolher entre conta Real ou Demo."""
    print("\n" + "-" * 72)
    print("  SELEÇÃO DE CONTA")
    print("-" * 72)
    print("\nEm qual conta deseja operar?")
    print("  1 - CONTA DEMO (PRACTICE)")
    print("  2 - CONTA REAL (REAL)")
    
    while True:
        escolha = input("\nEscolha (1 ou 2): ").strip()
        if escolha == "1":
            print("✅ Conta DEMO selecionada")
            return "PRACTICE"
        elif escolha == "2":
            print("⚠️  Conta REAL selecionada - OPERAÇÕES COM DINHEIRO VERDADEIRO!")
            confirmacao = input("Tem certeza? (sim/não): ").strip().lower()
            if confirmacao in ("sim", "s"):
                return "REAL"
            else:
                print("Retornando à seleção de conta...")
        else:
            print("Opção inválida. Digite 1 ou 2.")


def listar_estrategias() -> None:
    """Exibe todas as estratégias disponíveis numeradas."""
    print("\n" + "-" * 72)
    print("  ESTRATÉGIAS DISPONÍVEIS")
    print("-" * 72)
    print(f"\n{'Nº':<4} {'ID':<10} {'Nome':<35} {'TF':<10} {'Tipo':<12}")
    print("-" * 72)
    
    for num, dados in sorted(ESTRATEGIAS_DISPONIVEIS.items()):
        print(f"{num:<4} {dados['id']:<10} {dados['nome']:<35} {dados['timeframe']:<10} {dados['tipo']:<12}")
    
    print("-" * 72)
    print("\n💡 Dica: Digite os números separados por vírgula (ex: 1,3,5,10)")
    print("   Deixe em branco para ativar TODAS as estratégias")


def selecionar_estrategias() -> set[int]:
    """Permite ao usuário selecionar quais estratégias monitorar."""
    listar_estrategias()
    
    print("\n💡 Opções de seleção:")
    print("   • Digite '0' ou 'T' para ativar TODAS as estratégias")
    print("   • Digite números separados por vírgula (ex: 1,3,5,10)")
    print("   • Deixe em branco para ativar TODAS as estratégias")
    
    while True:
        entrada = input("\n📊 Número das estratégias para monitorar: ").strip().upper()
        
        # Opção para selecionar todas de uma vez
        if entrada in ("0", "T"):
            print("✅ Todas as estratégias ativadas!")
            return set(ESTRATEGIAS_DISPONIVEIS.keys())
        
        if not entrada:
            print("✅ Todas as estratégias ativadas!")
            return set(ESTRATEGIAS_DISPONIVEIS.keys())
        
        try:
            numeros = [int(n.strip()) for n in entrada.split(",")]
            invalidos = [n for n in numeros if n not in ESTRATEGIAS_DISPONIVEIS]
            
            if invalidos:
                print(f"❌ Números inválidos: {invalidos}")
                print(f"   Use apenas números de 1 a {max(ESTRATEGIAS_DISPONIVEIS.keys())}")
                continue
            
            if not numeros:
                print("❌ Nenhum número válido fornecido.")
                continue
            
            selecionadas = set(numeros)
            print(f"\n✅ {len(selecionadas)} estratégia(s) ativada(s):")
            for num in sorted(selecionadas):
                estrat = ESTRATEGIAS_DISPONIVEIS[num]
                print(f"   • {estrat['id']} - {estrat['nome']}")
            
            return selecionadas
        
        except ValueError:
            print("❌ Formato inválido. Use apenas números separados por vírgula, '0' ou 'T'.")


def selecionar_mercado() -> str:
    """Permite escolher entre mercado Digital ou Binário/Turbo."""
    print("\n" + "-" * 72)
    print("  SELEÇÃO DE MERCADO")
    print("-" * 72)
    print("\nQual mercado deseja operar?")
    print("  1 - DIGITAL (Opções Digitais)")
    print("  2 - BINÁRIAS/TURBO (Opções Binárias)")
    
    while True:
        escolha = input("\nEscolha (1 ou 2): ").strip()
        if escolha == "1":
            print("✅ Mercado DIGITAL selecionado")
            return "DIGITAL"
        elif escolha == "2":
            print("✅ Mercado BINÁRIO/TURBO selecionado")
            return "BINARY"
        else:
            print("Opção inválida. Digite 1 ou 2.")


def selecionar_execucao_automatica() -> bool:
    """Pergunta se deseja executar ordens automaticamente."""
    print("\n" + "-" * 72)
    print("  CONFIGURAÇÃO DE EXECUÇÃO")
    print("-" * 72)
    print(f"\nConta configurada: {config.conta}")
    print(f"Valor por entrada: R$ {config.valor_entrada:.2f}")
    print("\nDeseja que o sistema faça entradas automaticamente?")
    print("  1 - SIM, executar ordens automaticamente ao receber sinal")
    print("  2 - NÃO, somente enviar alertas (modo observação)")
    
    while True:
        escolha = input("\nEscolha (1 ou 2): ").strip().lower()
        if escolha in ("1", "sim", "s"):
            print("✅ Execução AUTOMÁTICA ativada")
            return True
        elif escolha in ("2", "nao", "não", "n"):
            print("✅ Modo OBSERVAÇÃO - Somente alertas serão enviados")
            return False
        else:
            print("Opção inválida. Digite 1 ou 2.")


def selecionar_pares() -> list[str]:
    """Permite selecionar quais pares de moedas monitorar."""
    print("\n" + "-" * 72)
    print("  SELEÇÃO DE ATIVOS")
    print("-" * 72)
    print("\nQuais ativos deseja monitorar?")
    print("  1 - Apenas pares OTC (Recomendado para iniciantes)")
    print("  2 - Apenas pares principais (EURUSD, GBPUSD, etc.)")
    print("  3 - Todos os pares (OTC + Principais)")
    
    while True:
        escolha = input("\nEscolha (1, 2 ou 3): ").strip()
        if escolha == "1":
            print(f"✅ {len(PARES_OTC)} pares OTC selecionados")
            return PARES_OTC.copy()
        elif escolha == "2":
            print(f"✅ {len(PARES_PRINCIPAIS)} pares principais selecionados")
            return PARES_PRINCIPAIS.copy()
        elif escolha == "3":
            todos = PARES_OTC + PARES_PRINCIPAIS
            print(f"✅ {len(todos)} pares selecionados (todos disponíveis)")
            return todos
        else:
            print("Opção inválida. Digite 1, 2 ou 3.")


# ============================================================================
# CONEXÃO COM API
# ============================================================================
def conectar(api) -> bool:
    """Estabelece conexão com a IQ Option."""
    max_tentativas = 5
    tentativa = 0
    
    while tentativa < max_tentativas:
        try:
            print(f"\n🔄 Conectando à IQ Option... (tentativa {tentativa + 1}/{max_tentativas})")
            conectado, motivo = api.connect()
            
            if conectado:
                api.change_balance(config.conta)
                print(f"✅ Autenticado com sucesso!")
                print(f"   Conta: {config.conta}")
                
                saldo_info = api.get_balance()
                if saldo_info:
                    print(f"   Saldo: ${saldo_info}")
                
                return True
            else:
                print(f"❌ Falha na conexão: {motivo}")
                
        except Exception as erro:
            print(f"❌ Erro ao conectar: {erro}")
        
        tentativa += 1
        time.sleep(5)
    
    print("\n❌ Não foi possível conectar após várias tentativas.")
    return False


def abrir_canais(api, pares: list[str], timeframe: int) -> None:
    """Abre streams de candles para os pares selecionados."""
    print(f"\n📡 Abrindo canais de dados para {len(pares)} pares...")
    
    for par in pares:
        try:
            api.start_candles_stream(par, timeframe, 100)
            print(f"   ✓ {par}")
        except Exception as erro:
            print(f"   ✗ {par} - Erro: {erro}")
        time.sleep(0.3)
    
    print(f"✅ Canais abertos com sucesso!")


# ============================================================================
# CLASSES DE DADOS
# ============================================================================
@dataclass(frozen=True)
class Vela:
    """Representação normalizada de um candle da IQ Option."""
    inicio: int
    abertura: float
    fechamento: float
    maxima: float
    minima: float
    
    @property
    def cor(self) -> str:
        if self.fechamento > self.abertura:
            return "verde"
        elif self.fechamento < self.abertura:
            return "vermelha"
        return "doji"
    
    @property
    def eh_verde(self) -> bool:
        return self.cor == "verde"
    
    @property
    def eh_vermelha(self) -> bool:
        return self.cor == "vermelha"
    
    @property
    def eh_doji(self) -> bool:
        return self.cor == "doji"


@dataclass
class Sinal:
    """Sinal gerado por uma estratégia."""
    estrategia_id: str
    estrategia_nome: str
    par: str
    direcao: str  # "call" ou "put"
    timeframe: str
    timestamp: int
    preco_entrada: float
    expiracao: int  # segundos
    padrao: str = ""
    confianca: float = 1.0


@dataclass
class EstadoPar:
    """Estado do monitoramento para um único par."""
    par: str
    historico: deque[Vela] = field(default_factory=lambda: deque(maxlen=500))
    ultimo_processado: int = 0
    sinais_gerados: int = 0
    ultima_atualizacao: float = field(default_factory=time.monotonic)


# ============================================================================
# DETECTORES DE ESTRATÉGIAS
# ============================================================================
class DetectorEstrategias:
    """Classe base para detectores de estratégias."""
    
    def detectar(self, estado: EstadoPar) -> Optional[Sinal]:
        raise NotImplementedError


class DetectorS1(DetectorEstrategias):
    """S1 - Três Velas Reversão
    
    Vela oposta ou doji seguida por 3 velas iguais; entrada contrária.
    """
    
    def detectar(self, estado: EstadoPar) -> Optional[Sinal]:
        if len(estado.historico) < 4:
            return None
        
        velas = list(estado.historico)[-4:]
        v0, v1, v2, v3 = velas
        
        # Verifica se v0 é oposta ou doji
        if v0.eh_doji:
            pass  # Doji é válido
        elif v1.eh_verde and v0.eh_vermelha:
            pass  # Opuesta
        elif v1.eh_vermelha and v0.eh_verde:
            pass  # Opuesta
        else:
            return None
        
        # Verifica se v1, v2, v3 são da mesma cor
        if v1.cor == v2.cor == v3.cor and not v1.eh_doji:
            direcao = "put" if v1.eh_verde else "call"
            return Sinal(
                estrategia_id="S1",
                estrategia_nome="Três Velas Reversão",
                par=estado.par,
                direcao=direcao,
                timeframe="M1",
                timestamp=v3.inicio,
                preco_entrada=v3.fechamento,
                expiracao=60,
                padrao="3 velas iguais após vela oposta/doji"
            )
        
        return None


class DetectorS5(DetectorEstrategias):
    """S5 - Primeiro Retorno M1 (Comando M1)
    
    Primeiro retorno M1 à abertura de um comando M1.
    """
    
    def detectar(self, estado: EstadoPar) -> Optional[Sinal]:
        if len(estado.historico) < 22:
            return None
        
        velas = list(estado.historico)
        
        # Procura comando nos últimos 21 candles
        for i in range(len(velas) - 2, max(0, len(velas) - 22), -1):
            comando = velas[i]
            
            # Comando de Alta (Green Command): vela verde sem pavio inferior
            if comando.eh_verde and abs(comando.minima - comando.abertura) < 0.00001:
                nivel = comando.abertura
                direcao_sinal = "put"
            # Comando de Baixa (Red Command): vela vermelha sem pavio superior
            elif comando.eh_vermelha and abs(comando.maxima - comando.abertura) < 0.00001:
                nivel = comando.abertura
                direcao_sinal = "call"
            else:
                continue
            
            # Verifica se alguma vela após o comando tocou o nível
            toque_ocorreu = False
            for j in range(i + 1, len(velas) - 1):
                vela = velas[j]
                if vela.minima <= nivel <= vela.maxima:
                    toque_ocorreu = True
                    break
            
            # Se não houve toque anterior, verifica se a última vela tocou
            if not toque_ocorreu:
                atual = velas[-1]
                if atual.minima <= nivel <= atual.maxima:
                    return Sinal(
                        estrategia_id="S5",
                        estrategia_nome="Primeiro Retorno M1",
                        par=estado.par,
                        direcao=direcao_sinal,
                        timeframe="M1",
                        timestamp=atual.inicio,
                        preco_entrada=nivel,
                        expiracao=60,
                        padrao=f"Retorno à abertura do comando ({direcao_sinal})"
                    )
        
        return None


class DetectorS16(DetectorEstrategias):
    """S16 - Engolfo M5 na Abertura M15
    
    Engolfo de M5 na primeira vela de nova M15.
    """
    
    def detectar(self, estado: EstadoPar) -> Optional[Sinal]:
        if len(estado.historico) < 3:
            return None
        
        velas = list(estado.historico)[-3:]
        v1, v2, v3 = velas
        
        # Verifica se v3 é a primeira vela de nova M15
        periodo_v2 = v2.inicio // 900
        periodo_v3 = v3.inicio // 900
        
        if periodo_v2 == periodo_v3:
            return None  # Ainda está na mesma M15
        
        # Engolfo de alta: v2 vermelha, v3 verde, v3 fecha acima do High de v2
        if v2.eh_vermelha and v3.eh_verde and v3.fechamento > v2.maxima:
            return Sinal(
                estrategia_id="S16",
                estrategia_nome="Engolfo M5 na Abertura M15",
                par=estado.par,
                direcao="call",
                timeframe="M5",
                timestamp=v3.inicio,
                preco_entrada=v3.fechamento,
                expiracao=300,
                padrao="Engolfo de alta na virada M15"
            )
        
        # Engolfo de baixa: v2 verde, v3 vermelha, v3 fecha abaixo do Low de v2
        if v2.eh_verde and v3.eh_vermelha and v3.fechamento < v2.minima:
            return Sinal(
                estrategia_id="S16",
                estrategia_nome="Engolfo M5 na Abertura M15",
                par=estado.par,
                direcao="put",
                timeframe="M5",
                timestamp=v3.inicio,
                preco_entrada=v3.fechamento,
                expiracao=300,
                padrao="Engolfo de baixa na virada M15"
            )
        
        return None


class DetectorS17(DetectorEstrategias):
    """S17 - Rompimento Dupla Posição
    
    Rompimento M5 de uma dupla posição da mesma cor.
    """
    
    def detectar(self, estado: EstadoPar) -> Optional[Sinal]:
        if len(estado.historico) < 3:
            return None
        
        velas = list(estado.historico)[-3:]
        v1, v2, v3 = velas
        
        # Dupla verde: v1 e v2 verdes, v2 contida em v1
        if v1.eh_verde and v2.eh_verde and v2.maxima <= v1.maxima:
            # v3 rompe acima de v1
            if v3.eh_verde and v3.fechamento > v1.maxima:
                return Sinal(
                    estrategia_id="S17",
                    estrategia_nome="Rompimento Dupla Posição",
                    par=estado.par,
                    direcao="call",
                    timeframe="M5",
                    timestamp=v3.inicio,
                    preco_entrada=v3.fechamento,
                    expiracao=300,
                    padrao="Rompimento dupla posição de alta"
                )
        
        # Dupla vermelha: v1 e v2 vermelhas, v2 contida em v1
        if v1.eh_vermelha and v2.eh_vermelha and v2.minima >= v1.minima:
            # v3 rompe abaixo de v1
            if v3.eh_vermelha and v3.fechamento < v1.minima:
                return Sinal(
                    estrategia_id="S17",
                    estrategia_nome="Rompimento Dupla Posição",
                    par=estado.par,
                    direcao="put",
                    timeframe="M5",
                    timestamp=v3.inicio,
                    preco_entrada=v3.fechamento,
                    expiracao=300,
                    padrao="Rompimento dupla posição de baixa"
                )
        
        return None


# ============================================================================
# GERENCIADOR DE SINAIS
# ============================================================================
class GerenciadorSinais:
    """Gerencia detecção e execução de sinais."""
    
    def __init__(self, api):
        self.api = api
        self.estados: Dict[str, EstadoPar] = {}
        self.detectores: Dict[int, DetectorEstrategias] = {
            1: DetectorS1(),
            2: DetectorS5(),
            9: DetectorS1(),  # Simplificação para demo
            10: DetectorS16(),
            11: DetectorS17(),
        }
        self.sinais_recentes: deque[Sinal] = deque(maxlen=100)
        self.lock = threading.Lock()
    
    def inicializar_estados(self, pares: list[str]) -> None:
        """Inicializa o estado para cada par."""
        for par in pares:
            self.estados[par] = EstadoPar(par=par)
    
    def atualizar_historico(self, par: str, velas_dict: dict) -> None:
        """Atualiza o histórico de velas para um par."""
        if par not in self.estados:
            return
        
        estado = self.estados[par]
        
        # Converte dicionário para lista ordenada de Vela
        velas_lista = []
        for _, dados in velas_dict.items():
            try:
                vela = Vela(
                    inicio=int(dados["from"]),
                    abertura=float(dados["open"]),
                    fechamento=float(dados["close"]),
                    maxima=float(dados["max"]),
                    minima=float(dados["min"]),
                )
                velas_lista.append(vela)
            except (KeyError, TypeError, ValueError):
                continue
        
        if not velas_lista:
            return
        
        # Ordena por timestamp
        velas_lista.sort(key=lambda v: v.inicio)
        
        # Adiciona ao histórico
        for vela in velas_lista:
            if vela.inicio > estado.ultimo_processado:
                estado.historico.append(vela)
                estado.ultimo_processado = vela.inicio
        
        estado.ultima_atualizacao = time.monotonic()
    
    def verificar_sinais(self) -> List[Sinal]:
        """Verifica todas as estratégias ativas em todos os pares."""
        sinais_encontrados = []
        
        with self.lock:
            for par, estado in self.estados.items():
                if len(estado.historico) < 10:
                    continue
                
                for num_estrat in config.estrategias_ativas:
                    detector = self.detectores.get(num_estrat)
                    if not detector:
                        continue
                    
                    try:
                        sinal = detector.detectar(estado)
                        if sinal:
                            # Evita sinais duplicados
                            chave_sinal = (sinal.par, sinal.estrategia_id, sinal.timestamp)
                            if not any(
                                (s.par, s.estrategia_id, s.timestamp) == chave_sinal
                                for s in self.sinais_recentes
                            ):
                                sinais_encontrados.append(sinal)
                                self.sinais_recentes.append(sinal)
                                estado.sinais_gerados += 1
                    except Exception as erro:
                        print(f"[ERRO] Estratégia {num_estrat} em {par}: {erro}")
        
        return sinais_encontrados
    
    def executar_ordem(self, sinal: Sinal) -> tuple[bool, Any]:
        """Executa uma ordem na IQ Option."""
        direcao_api = "call" if sinal.direcao == "call" else "put"
        
        try:
            if config.mercado == "DIGITAL":
                sucesso, ordem_id = self.api.buy_digital_spot_v2(
                    sinal.par,
                    config.valor_entrada,
                    direcao_api.upper(),
                    1,
                )
            else:
                sucesso, ordem_id = self.api.buy(
                    config.valor_entrada,
                    sinal.par,
                    direcao_api.upper(),
                    1,
                )
            
            return bool(sucesso), ordem_id
        
        except Exception as erro:
            print(f"[ERRO] Falha ao executar ordem: {erro}")
            return False, str(erro)


# ============================================================================
# ENVIO DE ALERTAS
# ============================================================================


def formatar_alerta(sinal: Sinal, status: str = "SINAL DETECTADO") -> str:
    """Formata mensagem de alerta."""
    direcao_texto = "🟢 COMPRA (CALL)" if sinal.direcao == "call" else "🔴 VENDA (PUT)"
    
    return (
        f"{direcao_texto}\n"
        f"Estratégia: {sinal.estrategia_nome} ({sinal.estrategia_id})\n"
        f"Ativo: {sinal.par}\n"
        f"Timeframe: {sinal.timeframe}\n"
        f"Preço: {sinal.preco_entrada:.5f}\n"
        f"Padrão: {sinal.padrao}\n"
        f"Status: {status}\n"
        f"Conta: {config.conta} | Valor: R$ {config.valor_entrada:.2f}"
    )


# ============================================================================
# LOOP PRINCIPAL
# ============================================================================
def loop_monitoramento(api, gerenciador: GerenciadorSinais) -> None:
    """Loop principal de monitoramento."""
    print("\n" + "=" * 72)
    print("  INICIANDO MONITORAMENTO")
    print("=" * 72)
    print(f"\n📊 Estratégias ativas: {len(config.estrategias_ativas)}")
    print(f"📈 Pares monitorados: {len(config.pares)}")
    print(f"⚙️  Execução automática: {'ATIVADA' if config.auto_executar else 'DESATIVADA'}")
    print(f"💰 Valor por entrada: R$ {config.valor_entrada:.2f}")
    print("\nPressione Ctrl+C para parar\n")
    
    intervalo_varredura = 0.5
    contador_ciclos = 0
    
    try:
        while True:
            inicio_ciclo = time.monotonic()
            
            # Atualiza históricos
            for par in config.pares:
                try:
                    velas_dict = api.get_realtime_candles(par, 60)
                    if velas_dict:
                        gerenciador.atualizar_historico(par, velas_dict)
                except Exception as erro:
                    if contador_ciclos % 20 == 0:
                        print(f"[ERRO] {par}: {erro}")
            
            # Verifica sinais
            sinais = gerenciador.verificar_sinais()
            
            for sinal in sinais:
                print(f"\n{'='*60}")
                print(f"🎯 SINAL DETECTADO!")
                print(f"{'='*60}")
                print(formatar_alerta(sinal))
                
                if config.auto_executar:
                    print("\n🔄 Executando ordem...")
                    sucesso, resultado = gerenciador.executar_ordem(sinal)
                    
                    if sucesso:
                        status = f"✅ ORDEM EXECUTADA (ID: {resultado})"
                        print(status)
                    else:
                        status = f"❌ ORDEM RECUSADA ({resultado})"
                        print(status)
                else:
                    status = "⚠️  SOMENTE ALERTA - Operação manual necessária"
                    print(status)
            
            # Status periódico
            contador_ciclos += 1
            if contador_ciclos % 60 == 0:
                total_sinais = sum(e.sinais_gerados for e in gerenciador.estados.values())
                print(f"\n📊 Status [{datetime.now().strftime('%H:%M:%S')}]")
                print(f"   Ciclos: {contador_ciclos} | Sinais totais: {total_sinais}")
            
            # Mantém intervalo constante
            duracao = time.monotonic() - inicio_ciclo
            if duracao < intervalo_varredura:
                time.sleep(intervalo_varredura - duracao)
    
    except KeyboardInterrupt:
        print("\n\n⏹️  Monitoramento interrompido pelo usuário")
    except Exception as erro:
        print(f"\n❌ Erro crítico no loop: {erro}")
        raise


# ============================================================================
# PONTO DE ENTRADA
# ============================================================================
def main() -> None:
    """Função principal do SuperFull."""
    
    # Valida dependências
    if not validar_dependencias():
        sys.exit(1)
    
    try:
        # Coleta configurações do usuário
        config.email, config.password = solicitar_credenciais()
        config.conta = selecionar_conta()
        config.mercado = selecionar_mercado()
        config.estrategias_ativas = selecionar_estrategias()
        config.pares = selecionar_pares()
        config.auto_executar = selecionar_execucao_automatica()
        
        # Cria instância da API
        api = IQ_Option(config.email, config.password)
        
        # Conecta
        if not conectar(api):
            print("\n❌ Falha na autenticação. Encerrando.")
            sys.exit(1)
        
        # Abre canais
        abrir_canais(api, config.pares, 60)
        
        # Inicializa gerenciador
        gerenciador = GerenciadorSinais(api)
        gerenciador.inicializar_estados(config.pares)
        
        # Aguarda coleta inicial de dados
        print("\n⏳ Aguardando coleta inicial de dados (30 segundos)...")
        time.sleep(30)
        
        # Inicia loop principal
        loop_monitoramento(api, gerenciador)
    
    except KeyboardInterrupt:
        print("\n\n👋 SuperFull encerrado.")
    except Exception as erro:
        print(f"\n❌ Erro fatal: {erro}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        print("\n✅ Sistema finalizado.")


if __name__ == "__main__":
    main()

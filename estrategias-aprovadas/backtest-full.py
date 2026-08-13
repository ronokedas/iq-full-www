"""Backtest completo de estratégias EvePulse usando histórico Parquet.

Executar:
  python backtest-full.py

O programa lê todos os arquivos Parquet da pasta dados/iq_option/m1/,
aplica todas as estratégias do catálogo EvePulse e gera relatório
detalhado com taxa de assertividade, Wilson Score e ranking.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

try:
    import pandas as pd
    import numpy as np
except ImportError as exc:
    raise SystemExit("Instale pandas, numpy e pyarrow: pip install pandas numpy pyarrow") from exc


@dataclass
class Trade:
    """Registro de um trade no backtest."""
    symbol: str
    strategy: str
    timestamp: int
    direction: str  # "CALL" ou "PUT"
    entry_price: float
    exit_price: Optional[float] = None
    result: Optional[str] = None  # "WIN", "LOSS", "DOJI"
    expiry_candle: Optional[dict] = None


@dataclass
class StrategyStats:
    """Estatísticas de uma estratégia."""
    strategy: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    dojis: int = 0
    win_rate: float = 0.0
    wilson_score: float = 0.0
    symbols_tested: set = field(default_factory=set)
    trades: List[Trade] = field(default_factory=list)

    def calculate_metrics(self):
        """Calcula métricas estatísticas."""
        if self.total_trades == 0:
            return
        
        self.win_rate = (self.wins / self.total_trades) * 100 if self.total_trades > 0 else 0
        
        # Wilson Score Interval (95% confidence)
        n = self.total_trades
        if n >= 30:  # Mínimo para cálculo estatístico
            p = self.wins / n
            z = 1.96  # 95% confidence
            denominator = 1 + z**2 / n
            center = p + z**2 / (2 * n)
            variance = p * (1 - p) / n + z**2 / (4 * n**2)
            self.wilson_score = (center - z * (variance ** 0.5)) / denominator
        else:
            self.wilson_score = 0.0


class BacktestEngine:
    """Motor de backtest para todas as estratégias EvePulse."""
    
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.dataframes: Dict[str, pd.DataFrame] = {}
        self.results: Dict[str, StrategyStats] = {}
        self.manifest_path = data_dir.parent / "manifest.json"
        self.manifest = {}
        
    def load_data(self) -> bool:
        """Carrega todos os arquivos Parquet disponíveis."""
        print("\n📊 Carregando dados históricos...")
        
        if not self.data_dir.exists():
            print(f"❌ Pasta de dados não encontrada: {self.data_dir}")
            return False
        
        # Carregar manifesto se existir
        if self.manifest_path.exists():
            self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            print(f"✅ Manifesto carregado: {len(self.manifest.get('pairs', {}))} pares")
        
        parquet_files = list(self.data_dir.glob("*.parquet"))
        if not parquet_files:
            print("❌ Nenhum arquivo Parquet encontrado.")
            return False
        
        for file in parquet_files:
            try:
                symbol = file.stem.replace("_", "-").upper()
                if not symbol.endswith("-OTC") and "-OTC-" not in symbol:
                    # Tenta extrair do conteúdo se não tiver sufixo claro
                    df_temp = pd.read_parquet(file)
                    if 'symbol' in df_temp.columns:
                        symbol = df_temp['symbol'].iloc[0]
                
                df = pd.read_parquet(file)
                
                # Normalizar colunas
                required_cols = ['from_ts', 'open', 'high', 'low', 'close']
                if not all(col in df.columns for col in required_cols):
                    print(f"⚠️  Arquivo {file.name} não tem colunas necessárias, pulando...")
                    continue
                
                # Ordenar por timestamp e remover duplicados
                df = df.sort_values('from_ts').drop_duplicates(subset=['from_ts'], keep='last')
                df = df.reset_index(drop=True)
                
                self.dataframes[symbol] = df
                print(f"  ✓ {symbol}: {len(df)} velas ({df['from_ts'].min()} até {df['from_ts'].max()})")
                
            except Exception as e:
                print(f"⚠️  Erro ao carregar {file.name}: {e}")
        
        if not self.dataframes:
            print("❌ Nenhum dado válido carregado.")
            return False
        
        print(f"\n✅ Total: {len(self.dataframes)} pares carregados")
        return True
    
    def _is_green(self, candle: dict) -> bool:
        """Verifica se vela é verde."""
        return candle['close'] > candle['open']
    
    def _is_red(self, candle: dict) -> bool:
        """Verifica se vela é vermelha."""
        return candle['close'] < candle['open']
    
    def _is_doji(self, candle: dict, threshold: float = 0.00001) -> bool:
        """Verifica se vela é Doji."""
        return abs(candle['close'] - candle['open']) < threshold
    
    def _get_upper_wick(self, candle: dict) -> float:
        """Calcula pavio superior."""
        return candle['high'] - max(candle['open'], candle['close'])
    
    def _get_lower_wick(self, candle: dict) -> float:
        """Calcula pavio inferior."""
        return min(candle['open'], candle['close']) - candle['low']
    
    def _get_body_size(self, candle: dict) -> float:
        """Calcula tamanho do corpo."""
        return abs(candle['close'] - candle['open'])
    
    def _get_candle_range(self, candle: dict) -> float:
        """Calcula amplitude total."""
        return candle['high'] - candle['low']
    
    def _has_upper_wick(self, candle: dict, min_ratio: float = 0.3) -> bool:
        """Verifica se tem pavio superior significativo."""
        wick = self._get_upper_wick(candle)
        body = self._get_body_size(candle)
        return wick > (body * min_ratio) if body > 0 else wick > 0.00001
    
    def _has_lower_wick(self, candle: dict, min_ratio: float = 0.3) -> bool:
        """Verifica se tem pavio inferior significativo."""
        wick = self._get_lower_wick(candle)
        body = self._get_body_size(candle)
        return wick > (body * min_ratio) if body > 0 else wick > 0.00001
    
    def _check_result(self, df: pd.DataFrame, idx: int, direction: str) -> str:
        """Verifica resultado do trade na próxima vela."""
        if idx + 1 >= len(df):
            return "PENDING"
        
        next_candle = df.iloc[idx + 1]
        
        if self._is_doji(next_candle):
            return "DOJI"
        
        if direction == "CALL":
            return "WIN" if self._is_green(next_candle) else "LOSS"
        elif direction == "PUT":
            return "WIN" if self._is_red(next_candle) else "LOSS"
        
        return "UNKNOWN"
    
    def _strategy_s1(self, symbol: str, df: pd.DataFrame) -> List[Trade]:
        """S1 - Três Velas Reversão."""
        trades = []
        
        for i in range(3, len(df) - 1):
            candles = [df.iloc[i-3], df.iloc[i-2], df.iloc[i-1], df.iloc[i]]
            
            # Verifica se primeira vela é oposta ou Doji
            first = candles[0]
            rest = candles[1:]
            
            is_first_opposite = (self._is_green(first) and all(self._is_red(c) for c in rest)) or \
                               (self._is_red(first) and all(self._is_green(c) for c in rest))
            is_first_doji = self._is_doji(first)
            
            if not (is_first_opposite or is_first_doji):
                continue
            
            # Verifica se 3 velas seguintes são iguais
            if all(self._is_green(c) for c in rest):
                # 3 verdes → PUT
                direction = "PUT"
                trades.append(Trade(
                    symbol=symbol,
                    strategy="S1-TresVelasReversao",
                    timestamp=int(candles[-1]['from_ts']),
                    direction=direction,
                    entry_price=float(candles[-1]['close']),
                    result=self._check_result(df, i, direction)
                ))
            elif all(self._is_red(c) for c in rest):
                # 3 vermelhas → CALL
                direction = "CALL"
                trades.append(Trade(
                    symbol=symbol,
                    strategy="S1-TresVelasReversao",
                    timestamp=int(candles[-1]['from_ts']),
                    direction=direction,
                    entry_price=float(candles[-1]['close']),
                    result=self._check_result(df, i, direction)
                ))
        
        return trades
    
    def _strategy_s5_m1(self, symbol: str, df: pd.DataFrame) -> List[Trade]:
        """S5 - Primeiro Retorno M1."""
        trades = []
        lookback = min(21, len(df))
        
        for i in range(lookback, len(df) - 1):
            # Procura comando nas últimas 21 velas
            command_found = False
            command_idx = None
            command_candle = None
            
            for j in range(i - lookback, i):
                candle = df.iloc[j]
                
                # Comando de alta: verde sem pavio inferior
                if self._is_green(candle) and abs(candle['low'] - candle['open']) < 0.00001:
                    command_found = True
                    command_idx = j
                    command_candle = candle
                    target_direction = "PUT"  # Retorno à abertura → baixa
                    reference_level = float(candle['open'])
                    break
                
                # Comando de baixa: vermelho sem pavio superior
                elif self._is_red(candle) and abs(candle['high'] - candle['open']) < 0.00001:
                    command_found = True
                    command_idx = j
                    command_candle = candle
                    target_direction = "CALL"  # Retorno à abertura → alta
                    reference_level = float(candle['open'])
                    break
            
            if not command_found or command_candle is None:
                continue
            
            # Verifica se alguma vela entre comando e atual tocou o nível
            touched_before = False
            for k in range(command_idx + 1, i):
                candle = df.iloc[k]
                if candle['low'] <= reference_level <= candle['high']:
                    touched_before = True
                    break
            
            if touched_before:
                continue
            
            # Verifica se vela atual tocou o nível
            current = df.iloc[i]
            if current['low'] <= reference_level <= current['high']:
                trades.append(Trade(
                    symbol=symbol,
                    strategy="S5-PrimeiroRetornoM1",
                    timestamp=int(current['from_ts']),
                    direction=target_direction,
                    entry_price=reference_level,
                    result=self._check_result(df, i, target_direction)
                ))
        
        return trades
    
    def _strategy_s13(self, symbol: str, df: pd.DataFrame) -> List[Trade]:
        """S13 - Pavios de Rejeição."""
        trades = []
        
        for i in range(3, len(df) - 1):
            candles = [df.iloc[i-2], df.iloc[i-1], df.iloc[i]]
            
            # Verifica se 3 velas são da mesma cor
            all_green = all(self._is_green(c) for c in candles)
            all_red = all(self._is_red(c) for c in candles)
            
            if not (all_green or all_red):
                continue
            
            # Verifica pavios de rejeição
            if all_green:
                # 3 verdes com pavio superior
                if all(self._has_upper_wick(c, 0.3) for c in candles):
                    # Verifica se fechamento da 2ª e 3ª está dentro do corpo da 1ª
                    first_high = float(candles[0]['high'])
                    second_close = float(candles[1]['close'])
                    third_close = float(candles[2]['close'])
                    
                    if second_close < first_high and third_close < first_high:
                        trades.append(Trade(
                            symbol=symbol,
                            strategy="S13-PaviosRejeicao",
                            timestamp=int(candles[-1]['from_ts']),
                            direction="PUT",
                            entry_price=float(candles[-1]['close']),
                            result=self._check_result(df, i, "PUT")
                        ))
            
            elif all_red:
                # 3 vermelhas com pavio inferior
                if all(self._has_lower_wick(c, 0.3) for c in candles):
                    # Verifica se fechamento da 2ª e 3ª está dentro do corpo da 1ª
                    first_low = float(candles[0]['low'])
                    second_close = float(candles[1]['close'])
                    third_close = float(candles[2]['close'])
                    
                    if second_close > first_low and third_close > first_low:
                        trades.append(Trade(
                            symbol=symbol,
                            strategy="S13-PaviosRejeicao",
                            timestamp=int(candles[-1]['from_ts']),
                            direction="CALL",
                            entry_price=float(candles[-1]['close']),
                            result=self._check_result(df, i, "CALL")
                        ))
        
        return trades
    
    def _strategy_s5_m5(self, symbol: str, df: pd.DataFrame) -> List[Trade]:
        """S5-M5 - Primeiro Retorno M5 (Comando M5)."""
        trades = []
        # Precisamos de dados M5 agregados
        if len(df) < 100:
            return trades
        
        # Agregar candles M5 a partir de M1
        m5_data = []
        for i in range(0, len(df) - 4, 5):
            chunk = df.iloc[i:i+5]
            if len(chunk) == 5:
                m5_candle = {
                    'from_ts': int(chunk['from_ts'].iloc[0]),
                    'open': float(chunk['open'].iloc[0]),
                    'high': float(chunk['high'].max()),
                    'low': float(chunk['low'].min()),
                    'close': float(chunk['close'].iloc[-1]),
                }
                m5_data.append(m5_candle)
        
        if len(m5_data) < 25:
            return trades
        
        lookback = min(20, len(m5_data))
        for i in range(lookback, len(m5_data) - 1):
            command_found = False
            command_idx = None
            command_candle = None
            
            for j in range(i - lookback, i):
                candle = m5_data[j]
                
                # Comando de alta: verde sem pavio inferior
                if candle['close'] > candle['open'] and abs(candle['low'] - candle['open']) < 0.00001:
                    command_found = True
                    command_idx = j
                    command_candle = candle
                    target_direction = "PUT"
                    reference_level = float(candle['open'])
                    break
                
                # Comando de baixa: vermelho sem pavio superior
                elif candle['close'] < candle['open'] and abs(candle['high'] - candle['open']) < 0.00001:
                    command_found = True
                    command_idx = j
                    command_candle = candle
                    target_direction = "CALL"
                    reference_level = float(candle['open'])
                    break
            
            if not command_found or command_candle is None:
                continue
            
            # Verifica se alguma vela entre comando e atual tocou o nível (em M1)
            start_m1_idx = command_idx * 5
            end_m1_idx = i * 5
            touched_before = False
            
            for k in range(start_m1_idx + 5, end_m1_idx):
                if k >= len(df):
                    break
                candle = df.iloc[k]
                if candle['low'] <= reference_level <= candle['high']:
                    touched_before = True
                    break
            
            if touched_before:
                continue
            
            # Verifica se alguma M1 atual tocou o nível
            current_m1_start = i * 5
            current_m1_end = min((i + 1) * 5, len(df))
            
            for k in range(current_m1_start, current_m1_end):
                if k >= len(df):
                    break
                candle = df.iloc[k]
                if candle['low'] <= reference_level <= candle['high']:
                    trades.append(Trade(
                        symbol=symbol,
                        strategy="S5-M5-PrimeiroRetornoM5",
                        timestamp=int(candle['from_ts']),
                        direction=target_direction,
                        entry_price=reference_level,
                        result=self._check_result(df, k, target_direction)
                    ))
                    break
        
        return trades
    
    def _strategy_s5_m15(self, symbol: str, df: pd.DataFrame) -> List[Trade]:
        """S5-M15 - Primeiro Retorno M15 (Comando M15)."""
        trades = []
        if len(df) < 300:
            return trades
        
        # Agregar candles M15 a partir de M1
        m15_data = []
        for i in range(0, len(df) - 14, 15):
            chunk = df.iloc[i:i+15]
            if len(chunk) == 15:
                m15_candle = {
                    'from_ts': int(chunk['from_ts'].iloc[0]),
                    'open': float(chunk['open'].iloc[0]),
                    'high': float(chunk['high'].max()),
                    'low': float(chunk['low'].min()),
                    'close': float(chunk['close'].iloc[-1]),
                }
                m15_data.append(m15_candle)
        
        if len(m15_data) < 25:
            return trades
        
        lookback = min(20, len(m15_data))
        for i in range(lookback, len(m15_data) - 1):
            command_found = False
            command_idx = None
            command_candle = None
            
            for j in range(i - lookback, i):
                candle = m15_data[j]
                
                if candle['close'] > candle['open'] and abs(candle['low'] - candle['open']) < 0.00001:
                    command_found = True
                    command_idx = j
                    command_candle = candle
                    target_direction = "PUT"
                    reference_level = float(candle['open'])
                    break
                elif candle['close'] < candle['open'] and abs(candle['high'] - candle['open']) < 0.00001:
                    command_found = True
                    command_idx = j
                    command_candle = candle
                    target_direction = "CALL"
                    reference_level = float(candle['open'])
                    break
            
            if not command_found or command_candle is None:
                continue
            
            start_m1_idx = command_idx * 15
            end_m1_idx = i * 15
            touched_before = False
            
            for k in range(start_m1_idx + 15, end_m1_idx):
                if k >= len(df):
                    break
                candle = df.iloc[k]
                if candle['low'] <= reference_level <= candle['high']:
                    touched_before = True
                    break
            
            if touched_before:
                continue
            
            current_m1_start = i * 15
            current_m1_end = min((i + 1) * 15, len(df))
            
            for k in range(current_m1_start, current_m1_end):
                if k >= len(df):
                    break
                candle = df.iloc[k]
                if candle['low'] <= reference_level <= candle['high']:
                    trades.append(Trade(
                        symbol=symbol,
                        strategy="S5-M15-PrimeiroRetornoM15",
                        timestamp=int(candle['from_ts']),
                        direction=target_direction,
                        entry_price=reference_level,
                        result=self._check_result(df, k, target_direction)
                    ))
                    break
        
        return trades
    
    def _strategy_s9(self, symbol: str, df: pd.DataFrame) -> List[Trade]:
        """S9 - Lateral H1 Reversão."""
        trades = []
        if len(df) < 120:
            return trades
        
        # Agregar candles H1 a partir de M1
        h1_data = []
        for i in range(0, len(df) - 59, 60):
            chunk = df.iloc[i:i+60]
            if len(chunk) == 60:
                h1_candle = {
                    'from_ts': int(chunk['from_ts'].iloc[0]),
                    'open': float(chunk['open'].iloc[0]),
                    'high': float(chunk['high'].max()),
                    'low': float(chunk['low'].min()),
                    'close': float(chunk['close'].iloc[-1]),
                }
                h1_data.append(h1_candle)
        
        if len(h1_data) < 5:
            return trades
        
        for i in range(2, len(h1_data)):
            prev_h1 = h1_data[i-2]
            curr_h1 = h1_data[i-1]
            
            # Verifica lateralidade: H1 atual dentro da faixa da anterior
            is_lateral = (curr_h1['high'] <= prev_h1['high'] and 
                         curr_h1['low'] >= prev_h1['low'] and
                         abs(curr_h1['from_ts'] - prev_h1['from_ts']) == 3600)
            
            if not is_lateral:
                continue
            
            # Durante a próxima H1, procurar 3 velas M1 iguais
            start_m1_idx = i * 60
            end_m1_idx = min((i + 1) * 60, len(df))
            
            for j in range(start_m1_idx + 2, end_m1_idx - 1):
                candles_m1 = [df.iloc[j-2], df.iloc[j-1], df.iloc[j]]
                
                all_green = all(self._is_green(c) for c in candles_m1)
                all_red = all(self._is_red(c) for c in candles_m1)
                
                if all_green:
                    trades.append(Trade(
                        symbol=symbol,
                        strategy="S9-LateralH1Reversao",
                        timestamp=int(candles_m1[-1]['from_ts']),
                        direction="PUT",
                        entry_price=float(candles_m1[-1]['close']),
                        result=self._check_result(df, j, "PUT")
                    ))
                elif all_red:
                    trades.append(Trade(
                        symbol=symbol,
                        strategy="S9-LateralH1Reversao",
                        timestamp=int(candles_m1[-1]['from_ts']),
                        direction="CALL",
                        entry_price=float(candles_m1[-1]['close']),
                        result=self._check_result(df, j, "CALL")
                    ))
        
        return trades
    
    def _strategy_s14(self, symbol: str, df: pd.DataFrame) -> List[Trade]:
        """S14 - Continuação Rejeição Rompimento."""
        trades = []
        lookback = min(21, len(df))
        
        for i in range(lookback, len(df) - 2):
            # Identificar lotes (sequências de mesma cor)
            lote_start = i
            for j in range(i-1, max(0, i-lookback), -1):
                if self._is_doji(df.iloc[j]):
                    continue
                prev_is_same = (self._is_green(df.iloc[j]) and self._is_green(df.iloc[j+1])) or \
                              (self._is_red(df.iloc[j]) and self._is_red(df.iloc[j+1]))
                if prev_is_same:
                    lote_start = j
                else:
                    break
            
            lote_size = i - lote_start + 1
            if lote_size < 2:
                continue
            
            first_candle = df.iloc[lote_start]
            last_candle = df.iloc[i]
            
            # Verificar rompimento e confirmação
            if self._is_red(last_candle) and lote_size >= 2:
                # Lote vermelho
                prev_red_count = sum(1 for k in range(lote_start, i) if self._is_red(df.iloc[k]))
                if prev_red_count >= 1:
                    # Verifica se rompeu acima do High do primeiro
                    if last_candle['close'] > first_candle['high']:
                        # Confirmação na próxima vela
                        if i + 1 < len(df):
                            confirm = df.iloc[i+1]
                            if self._is_red(confirm) and confirm['low'] <= first_candle['open'] <= confirm['high']:
                                trades.append(Trade(
                                    symbol=symbol,
                                    strategy="S14-ContinuacaoRejeicao",
                                    timestamp=int(confirm['from_ts']),
                                    direction="CALL",
                                    entry_price=float(confirm['close']),
                                    result=self._check_result(df, i+1, "CALL")
                                ))
            
            elif self._is_green(last_candle) and lote_size >= 2:
                # Lote verde
                prev_green_count = sum(1 for k in range(lote_start, i) if self._is_green(df.iloc[k]))
                if prev_green_count >= 1:
                    if last_candle['close'] < first_candle['low']:
                        if i + 1 < len(df):
                            confirm = df.iloc[i+1]
                            if self._is_green(confirm) and confirm['low'] <= first_candle['open'] <= confirm['high']:
                                trades.append(Trade(
                                    symbol=symbol,
                                    strategy="S14-ContinuacaoRejeicao",
                                    timestamp=int(confirm['from_ts']),
                                    direction="PUT",
                                    entry_price=float(confirm['close']),
                                    result=self._check_result(df, i+1, "PUT")
                                ))
        
        return trades
    
    def _strategy_s15(self, symbol: str, df: pd.DataFrame) -> List[Trade]:
        """S15 - Falso Rompimento."""
        trades = []
        lookback = min(21, len(df))
        
        for i in range(lookback, len(df) - 2):
            lote_start = i
            for j in range(i-1, max(0, i-lookback), -1):
                if self._is_doji(df.iloc[j]):
                    continue
                prev_is_same = (self._is_green(df.iloc[j]) and self._is_green(df.iloc[j+1])) or \
                              (self._is_red(df.iloc[j]) and self._is_red(df.iloc[j+1]))
                if prev_is_same:
                    lote_start = j
                else:
                    break
            
            if i - lote_start < 1:
                continue
            
            first_candle = df.iloc[lote_start]
            last_candle = df.iloc[i]
            
            if self._is_red(last_candle):
                # Lote vermelho - falso rompimento para cima
                if last_candle['close'] > first_candle['high']:
                    if i + 1 < len(df):
                        confirm = df.iloc[i+1]
                        if self._is_red(confirm):
                            # Fechamento entre Low e Open do primeiro
                            if first_candle['low'] <= confirm['close'] <= first_candle['open']:
                                trades.append(Trade(
                                    symbol=symbol,
                                    strategy="S15-FalsoRompimento",
                                    timestamp=int(confirm['from_ts']),
                                    direction="PUT",
                                    entry_price=float(confirm['close']),
                                    result=self._check_result(df, i+1, "PUT")
                                ))
            
            elif self._is_green(last_candle):
                # Lote verde - falso rompimento para baixo
                if last_candle['close'] < first_candle['low']:
                    if i + 1 < len(df):
                        confirm = df.iloc[i+1]
                        if self._is_green(confirm):
                            # Fechamento entre Open e High do primeiro
                            if first_candle['open'] <= confirm['close'] <= first_candle['high']:
                                trades.append(Trade(
                                    symbol=symbol,
                                    strategy="S15-FalsoRompimento",
                                    timestamp=int(confirm['from_ts']),
                                    direction="CALL",
                                    entry_price=float(confirm['close']),
                                    result=self._check_result(df, i+1, "CALL")
                                ))
        
        return trades
    
    def _strategy_s16(self, symbol: str, df: pd.DataFrame) -> List[Trade]:
        """S16 - Engolfo M5 na Abertura M15."""
        trades = []
        if len(df) < 15:
            return trades
        
        # Agregar M5
        m5_data = []
        for i in range(0, len(df) - 4, 5):
            chunk = df.iloc[i:i+5]
            if len(chunk) == 5:
                m5_candle = {
                    'from_ts': int(chunk['from_ts'].iloc[0]),
                    'open': float(chunk['open'].iloc[0]),
                    'high': float(chunk['high'].max()),
                    'low': float(chunk['low'].min()),
                    'close': float(chunk['close'].iloc[-1]),
                    'm15_bucket': int(chunk['from_ts'].iloc[0] // 900),
                }
                m5_data.append(m5_candle)
        
        if len(m5_data) < 3:
            return trades
        
        for i in range(2, len(m5_data) - 1):
            candle1 = m5_data[i-2]
            candle2 = m5_data[i-1]
            candle3 = m5_data[i]
            
            # Verificar se candle3 é primeira de nova M15
            if candle3['m15_bucket'] == candle2['m15_bucket']:
                continue
            
            # candle3 precisa estar FECHADA para confirmar o engolfo.
            # candle3 é a última M5 disponível em m5_data (i == len(m5_data)-1)?
            # Se sim, ainda não temos a vela seguinte (candle4) pra checar o pullback -> pula.
            if i + 1 >= len(m5_data):
                continue
            candle4 = m5_data[i + 1]
            
            # Vela engolfada (candle2) precisa pertencer ao MESMO bucket M15 que candle3
            # engoliu -- ou seja, candle4 ainda deve estar dentro da mesma M15 de candle3
            # (2ª M5 da nova M15), senão o "toque na abertura" perde o sentido de retração
            # dentro do mesmo M15.
            if candle4['m15_bucket'] != candle3['m15_bucket']:
                continue
            
            reference_level = float(candle2['open'])
            m1_touch_start = (i + 1) * 5       # início de candle4 (M1)
            m1_touch_end = min((i + 2) * 5, len(df))
            
            # Engolfo de alta: candle2 vermelha, candle3 verde fecha acima do High da candle2
            if self._is_red(candle2) and self._is_green(candle3):
                if candle3['close'] > candle2['high']:
                    # Esperar candle4 tocar a abertura da vela engolfada (candle2) -> pullback
                    for k in range(m1_touch_start, m1_touch_end):
                        if k >= len(df):
                            break
                        m1_candle = df.iloc[k]
                        if m1_candle['low'] <= reference_level <= m1_candle['high']:
                            trades.append(Trade(
                                symbol=symbol,
                                strategy="S16-EngolfoM5M15",
                                timestamp=int(m1_candle['from_ts']),
                                direction="CALL",
                                entry_price=reference_level,
                                result=self._check_result(df, k, "CALL")
                            ))
                            break
            
            # Engolfo de baixa: candle2 verde, candle3 vermelha fecha abaixo do Low da candle2
            elif self._is_green(candle2) and self._is_red(candle3):
                if candle3['close'] < candle2['low']:
                    # Esperar candle4 tocar a abertura da vela engolfada (candle2) -> pullback
                    for k in range(m1_touch_start, m1_touch_end):
                        if k >= len(df):
                            break
                        m1_candle = df.iloc[k]
                        if m1_candle['low'] <= reference_level <= m1_candle['high']:
                            trades.append(Trade(
                                symbol=symbol,
                                strategy="S16-EngolfoM5M15",
                                timestamp=int(m1_candle['from_ts']),
                                direction="PUT",
                                entry_price=reference_level,
                                result=self._check_result(df, k, "PUT")
                            ))
                            break
        
        return trades
    
    def _strategy_s17(self, symbol: str, df: pd.DataFrame) -> List[Trade]:
        """S17 - Rompimento Dupla Posição."""
        trades = []
        if len(df) < 15:
            return trades
        
        # Agregar M5
        m5_data = []
        for i in range(0, len(df) - 4, 5):
            chunk = df.iloc[i:i+5]
            if len(chunk) == 5:
                m5_candle = {
                    'from_ts': int(chunk['from_ts'].iloc[0]),
                    'open': float(chunk['open'].iloc[0]),
                    'high': float(chunk['high'].max()),
                    'low': float(chunk['low'].min()),
                    'close': float(chunk['close'].iloc[-1]),
                }
                m5_data.append(m5_candle)
        
        if len(m5_data) < 3:
            return trades
        
        for i in range(2, len(m5_data) - 1):
            candle1 = m5_data[i-2]
            candle2 = m5_data[i-1]
            candle3 = m5_data[i]
            
            # candle3 precisa estar FECHADA para confirmar o rompimento, e precisamos
            # de candle4 (a vela seguinte) para checar o pullback no nível rompido.
            if i + 1 >= len(m5_data):
                continue
            candle4 = m5_data[i + 1]
            
            m1_touch_start = (i + 1) * 5       # início de candle4 (M1)
            m1_touch_end = min((i + 2) * 5, len(df))
            
            # Mesma cor nas duas primeiras
            both_green = self._is_green(candle1) and self._is_green(candle2)
            both_red = self._is_red(candle1) and self._is_red(candle2)
            
            if both_green:
                # Candle2 contida na candle1: High2 <= High1
                if candle2['high'] <= candle1['high']:
                    # Candle3 rompe acima do High da candle1 (confirmado no fechamento)
                    if candle3['close'] > candle1['high']:
                        # Nível de retração = abertura da penúltima vela (candle2),
                        # que foi a vela imediatamente anterior ao rompimento
                        reference_level = float(candle2['open'])
                        # Esperar candle4 tocar de volta essa abertura -> pullback
                        for k in range(m1_touch_start, m1_touch_end):
                            if k >= len(df):
                                break
                            m1_candle = df.iloc[k]
                            if m1_candle['low'] <= reference_level <= m1_candle['high']:
                                trades.append(Trade(
                                    symbol=symbol,
                                    strategy="S17-RompimentoDuplaPosicao",
                                    timestamp=int(m1_candle['from_ts']),
                                    direction="CALL",
                                    entry_price=reference_level,
                                    result=self._check_result(df, k, "CALL")
                                ))
                                break
            
            elif both_red:
                # Candle2 contida na candle1: Low2 >= Low1
                if candle2['low'] >= candle1['low']:
                    # Candle3 rompe abaixo do Low da candle1 (confirmado no fechamento)
                    if candle3['close'] < candle1['low']:
                        # Nível de retração = abertura da penúltima vela (candle2),
                        # que foi a vela imediatamente anterior ao rompimento
                        reference_level = float(candle2['open'])
                        # Esperar candle4 tocar de volta essa abertura -> pullback
                        for k in range(m1_touch_start, m1_touch_end):
                            if k >= len(df):
                                break
                            m1_candle = df.iloc[k]
                            if m1_candle['low'] <= reference_level <= m1_candle['high']:
                                trades.append(Trade(
                                    symbol=symbol,
                                    strategy="S17-RompimentoDuplaPosicao",
                                    timestamp=int(m1_candle['from_ts']),
                                    direction="PUT",
                                    entry_price=reference_level,
                                    result=self._check_result(df, k, "PUT")
                                ))
                                break
        
        return trades
    
    def _strategy_s1_lab(self, symbol: str, df: pd.DataFrame) -> List[Trade]:
        """S1 (Lab) - Reversão/Engolfo com Retorno."""
        trades = []
        
        for i in range(3, len(df) - 1):
            candles = [df.iloc[i-3], df.iloc[i-2], df.iloc[i-1], df.iloc[i]]
            
            # Engolfo de alta
            if self._is_red(candles[0]) and self._has_upper_wick(candles[0], 0.1) and self._has_lower_wick(candles[0], 0.1):
                if self._is_green(candles[1]) and candles[1]['close'] > candles[0]['high']:
                    if self._is_green(candles[2]) and candles[2]['close'] > candles[1]['high']:
                        if candles[2]['low'] > candles[0]['high']:  # Não tocou High da vela 1
                            reference_level = float(candles[0]['high'])
                            # Aguardar toque posterior
                            for j in range(i+1, min(i+20, len(df)-1)):
                                if df.iloc[j]['high'] >= reference_level:
                                    trades.append(Trade(
                                        symbol=symbol,
                                        strategy="S1-Lab-EngolfoRetorno",
                                        timestamp=int(df.iloc[j]['from_ts']),
                                        direction="CALL",
                                        entry_price=reference_level,
                                        result=self._check_result(df, j, "CALL")
                                    ))
                                    break
            
            # Engolfo de baixa
            elif self._is_green(candles[0]) and self._has_upper_wick(candles[0], 0.1) and self._has_lower_wick(candles[0], 0.1):
                if self._is_red(candles[1]) and candles[1]['close'] < candles[0]['low']:
                    if self._is_red(candles[2]) and candles[2]['close'] < candles[1]['low']:
                        if candles[2]['high'] < candles[0]['low']:
                            reference_level = float(candles[0]['low'])
                            for j in range(i+1, min(i+20, len(df)-1)):
                                if df.iloc[j]['low'] <= reference_level:
                                    trades.append(Trade(
                                        symbol=symbol,
                                        strategy="S1-Lab-EngolfoRetorno",
                                        timestamp=int(df.iloc[j]['from_ts']),
                                        direction="PUT",
                                        entry_price=reference_level,
                                        result=self._check_result(df, j, "PUT")
                                    ))
                                    break
        
        return trades
    
    def _strategy_s2_lab(self, symbol: str, df: pd.DataFrame) -> List[Trade]:
        """S2 (Lab) - Zonas das 3 M15 Anteriores."""
        trades = []
        if len(df) < 45:
            return trades
        
        for i in range(45, len(df) - 1):
            current_ts = int(df.iloc[i]['from_ts'])
            current_m15_bucket = current_ts // 900
            
            # Pegar 3 M15 fechadas anteriores
            m15_buckets = set()
            highs = []
            lows = []
            
            for j in range(i-1, max(0, i-100), -1):
                ts = int(df.iloc[j]['from_ts'])
                bucket = ts // 900
                if bucket < current_m15_bucket and bucket not in m15_buckets:
                    m15_candles = [df.iloc[k] for k in range(max(0, j-14), j+1) if int(df.iloc[k]['from_ts']) // 900 == bucket]
                    if len(m15_candles) == 15:
                        highs.append(max(c['high'] for c in m15_candles))
                        lows.append(min(c['low'] for c in m15_candles))
                        m15_buckets.add(bucket)
                        if len(m15_buckets) == 3:
                            break
            
            if len(highs) < 3 or len(lows) < 3:
                continue
            
            resistance = max(highs)
            support = min(lows)
            tolerance = (resistance - support) * 0.05
            
            current = df.iloc[i]
            
            # Tocar resistência
            if current['high'] >= resistance - tolerance and current['low'] > support + tolerance:
                trades.append(Trade(
                    symbol=symbol,
                    strategy="S2-Lab-ZonasM15",
                    timestamp=int(current['from_ts']),
                    direction="PUT",
                    entry_price=float(current['close']),
                    result=self._check_result(df, i, "PUT")
                ))
            
            # Tocar suporte
            elif current['low'] <= support + tolerance and current['high'] < resistance - tolerance:
                trades.append(Trade(
                    symbol=symbol,
                    strategy="S2-Lab-ZonasM15",
                    timestamp=int(current['from_ts']),
                    direction="CALL",
                    entry_price=float(current['close']),
                    result=self._check_result(df, i, "CALL")
                ))
        
        return trades
    
    def _strategy_s6_lab(self, symbol: str, df: pd.DataFrame) -> List[Trade]:
        """S6 (Lab) - Varredura M5 com Fechamento."""
        trades = []
        if len(df) < 10:
            return trades
        
        # Agregar M5
        m5_data = []
        for i in range(0, len(df) - 4, 5):
            chunk = df.iloc[i:i+5]
            if len(chunk) == 5:
                m5_candle = {
                    'from_ts': int(chunk['from_ts'].iloc[0]),
                    'open': float(chunk['open'].iloc[0]),
                    'high': float(chunk['high'].max()),
                    'low': float(chunk['low'].min()),
                    'close': float(chunk['close'].iloc[-1]),
                }
                m5_data.append(m5_candle)
        
        if len(m5_data) < 3:
            return trades
        
        for i in range(1, len(m5_data) - 1):
            prev = m5_data[i-1]
            curr = m5_data[i]
            
            # Varredura de High
            if curr['high'] > prev['high'] and curr['close'] < prev['high']:
                next_candle = m5_data[i+1]
                body_low = min(curr['open'], curr['close'])
                if next_candle['close'] < body_low:
                    m1_idx = (i+1) * 5
                    if m1_idx < len(df):
                        trades.append(Trade(
                            symbol=symbol,
                            strategy="S6-Lab-VarreduraM5",
                            timestamp=int(df.iloc[m1_idx]['from_ts']),
                            direction="PUT",
                            entry_price=float(df.iloc[m1_idx]['close']),
                            result=self._check_result(df, m1_idx, "PUT")
                        ))
            
            # Varredura de Low
            elif curr['low'] < prev['low'] and curr['close'] > prev['low']:
                next_candle = m5_data[i+1]
                body_high = max(curr['open'], curr['close'])
                if next_candle['close'] > body_high:
                    m1_idx = (i+1) * 5
                    if m1_idx < len(df):
                        trades.append(Trade(
                            symbol=symbol,
                            strategy="S6-Lab-VarreduraM5",
                            timestamp=int(df.iloc[m1_idx]['from_ts']),
                            direction="CALL",
                            entry_price=float(df.iloc[m1_idx]['close']),
                            result=self._check_result(df, m1_idx, "CALL")
                        ))
        
        return trades
    
    def _strategy_s10_lab(self, symbol: str, df: pd.DataFrame) -> List[Trade]:
        """S10 (Lab) - Suporte/Resistência por Toques."""
        trades = []
        lookback = min(50, len(df))
        
        # Detectar toques em níveis
        levels = {}  # level_value -> {'type': 'support/resistance', 'touches': [indices]}
        
        for i in range(lookback):
            candle = df.iloc[i]
            
            # Verificar toque em Highs anteriores
            for j in range(i):
                prev = df.iloc[j]
                tolerance = abs(prev['high'] - prev['low']) * 0.05
                
                if abs(candle['high'] - prev['high']) < tolerance:
                    level_key = round(prev['high'], 5)
                    if level_key not in levels:
                        levels[level_key] = {'type': 'resistance', 'touches': [], 'last_touch': j}
                    
                    if i - levels[level_key]['last_touch'] > 1:  # Não adjacente
                        levels[level_key]['touches'].append(i)
                        levels[level_key]['last_touch'] = i
                        
                        if len(levels[level_key]['touches']) >= 3:
                            trades.append(Trade(
                                symbol=symbol,
                                strategy="S10-Lab-ToquesNivel",
                                timestamp=int(candle['from_ts']),
                                direction="PUT",
                                entry_price=float(candle['close']),
                                result=self._check_result(df, i, "PUT")
                            ))
                    break
            
            # Verificar toque em Lows anteriores
            for j in range(i):
                prev = df.iloc[j]
                tolerance = abs(prev['high'] - prev['low']) * 0.05
                
                if abs(candle['low'] - prev['low']) < tolerance:
                    level_key = round(prev['low'], 5)
                    if level_key not in levels:
                        levels[level_key] = {'type': 'support', 'touches': [], 'last_touch': j}
                    
                    if i - levels[level_key]['last_touch'] > 1:
                        levels[level_key]['touches'].append(i)
                        levels[level_key]['last_touch'] = i
                        
                        if len(levels[level_key]['touches']) >= 3:
                            trades.append(Trade(
                                symbol=symbol,
                                strategy="S10-Lab-ToquesNivel",
                                timestamp=int(candle['from_ts']),
                                direction="CALL",
                                entry_price=float(candle['close']),
                                result=self._check_result(df, i, "CALL")
                            ))
                    break
        
        return trades
    
    def _strategy_s7_lab(self, symbol: str, df: pd.DataFrame) -> List[Trade]:
        """S7 (Lab) - Captura de Pavio com Reversão."""
        trades = []
        
        if len(df) < 50:
            return trades
        
        # Calcular EMAs para tendência
        df_calc = df.copy()
        df_calc['ema9'] = df_calc['close'].ewm(span=9, adjust=False).mean()
        df_calc['ema21'] = df_calc['close'].ewm(span=21, adjust=False).mean()
        
        for i in range(30, len(df_calc)):
            candle = df_calc.iloc[i]
            
            body = abs(candle['close'] - candle['open'])
            upper_wick = candle['high'] - max(candle['open'], candle['close'])
            lower_wick = min(candle['open'], candle['close']) - candle['low']
            
            # Tendência de alta: EMA9 > EMA21
            if candle['ema9'] > candle['ema21']:
                # Procurar pavio inferior grande (captura de lows)
                if lower_wick > body * 0.8 and lower_wick > (candle['ema21'] * 0.0005):
                    trades.append(Trade(
                        symbol=symbol,
                        strategy="S7-Lab-CapturaPavio",
                        timestamp=int(candle['from_ts']),
                        direction="CALL",
                        entry_price=float(candle['close']),
                        result=self._check_result(df, i, "CALL")
                    ))
            
            # Tendência de baixa: EMA9 < EMA21
            elif candle['ema9'] < candle['ema21']:
                # Procurar pavio superior grande (captura de highs)
                if upper_wick > body * 0.8 and upper_wick > (candle['ema21'] * 0.0005):
                    trades.append(Trade(
                        symbol=symbol,
                        strategy="S7-Lab-CapturaPavio",
                        timestamp=int(candle['from_ts']),
                        direction="PUT",
                        entry_price=float(candle['close']),
                        result=self._check_result(df, i, "PUT")
                    ))
        
        return trades
    
    def run_backtest(self, strategies: Optional[List[str]] = None) -> Dict[str, StrategyStats]:
        """Executa backtest para todas ou estratégias selecionadas."""
        print("\n🚀 Iniciando backtest...")
        
        all_strategies = {
            # Principais
            "S1-TresVelasReversao": self._strategy_s1,
            "S5-PrimeiroRetornoM1": self._strategy_s5_m1,
            "S5-M5-PrimeiroRetornoM5": self._strategy_s5_m5,
            "S5-M15-PrimeiroRetornoM15": self._strategy_s5_m15,
            "S9-LateralH1Reversao": self._strategy_s9,
            "S13-PaviosRejeicao": self._strategy_s13,
            "S14-ContinuacaoRejeicao": self._strategy_s14,
            "S15-FalsoRompimento": self._strategy_s15,
            "S16-EngolfoM5M15": self._strategy_s16,
            "S17-RompimentoDuplaPosicao": self._strategy_s17,
            # Laboratório
            "S1-Lab-EngolfoRetorno": self._strategy_s1_lab,
            "S2-Lab-ZonasM15": self._strategy_s2_lab,
            "S6-Lab-VarreduraM5": self._strategy_s6_lab,
            "S7-Lab-CapturaPavio": self._strategy_s7_lab,
            "S10-Lab-ToquesNivel": self._strategy_s10_lab,
        }
        
        if strategies:
            all_strategies = {k: v for k, v in all_strategies.items() if any(s in k for s in strategies)}
        
        for symbol, df in self.dataframes.items():
            print(f"\n📈 Processando {symbol} ({len(df)} velas)...")
            
            for strat_name, strat_func in all_strategies.items():
                if strat_name not in self.results:
                    self.results[strat_name] = StrategyStats(strategy=strat_name)
                
                trades = strat_func(symbol, df)
                
                for trade in trades:
                    self.results[strat_name].trades.append(trade)
                    self.results[strat_name].symbols_tested.add(symbol)
                    self.results[strat_name].total_trades += 1
                    
                    if trade.result == "WIN":
                        self.results[strat_name].wins += 1
                    elif trade.result == "LOSS":
                        self.results[strat_name].losses += 1
                    elif trade.result == "DOJI":
                        self.results[strat_name].dojis += 1
                
                # Atualiza métricas periodicamente
                self.results[strat_name].calculate_metrics()
        
        return self.results
    
    def generate_report(self, output_path: Path) -> None:
        """Gera relatório detalhado em JSON e texto."""
        print("\n📋 Gerando relatório...")
        
        # Ordenar por Wilson Score
        sorted_results = sorted(
            self.results.values(),
            key=lambda x: x.wilson_score,
            reverse=True
        )
        
        report_data = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "total_symbols": len(self.dataframes),
            "strategies_tested": len(self.results),
            "results": []
        }
        
        for stats in sorted_results:
            result = {
                "strategy": stats.strategy,
                "total_trades": stats.total_trades,
                "wins": stats.wins,
                "losses": stats.losses,
                "dojis": stats.dojis,
                "win_rate_percent": round(stats.win_rate, 2),
                "wilson_score_95": round(stats.wilson_score, 4),
                "symbols_count": len(stats.symbols_tested),
                "symbols_list": sorted(list(stats.symbols_tested)),
                "approved": stats.wilson_score >= 0.53 and stats.total_trades >= 50
            }
            report_data["results"].append(result)
        
        # Salvar JSON
        output_json = output_path / "backtest_report.json"
        output_json.write_text(json.dumps(report_data, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"✅ Relatório JSON salvo: {output_json}")
        
        # Imprimir resumo no terminal
        print("\n" + "="*80)
        print("🏆 RANKING DE ESTRATÉGIAS (por Wilson Score)")
        print("="*80)
        print(f"{'Pos':<4} {'Estratégia':<30} {'Trades':<8} {'Win%':<8} {'Wilson':<8} {'Status':<10}")
        print("-"*80)
        
        for pos, stats in enumerate(sorted_results, 1):
            status = "✅ APROVADA" if stats.wilson_score >= 0.53 and stats.total_trades >= 50 else "⏳ Aguardando"
            print(f"{pos:<4} {stats.strategy:<30} {stats.total_trades:<8} {stats.win_rate:>6.2f}%  {stats.wilson_score:>6.4f}   {status:<10}")
        
        print("="*80)
        
        # Resumo final
        approved = [s for s in sorted_results if s.wilson_score >= 0.53 and s.total_trades >= 50]
        print(f"\n📊 Total de estratégias testadas: {len(self.results)}")
        print(f"✅ Estratégias aprovadas (Wilson >= 0.53, Trades >= 50): {len(approved)}")
        
        if approved:
            print("\n🎯 MELHORES ESTRATÉGIAS:")
            for stats in approved[:3]:
                print(f"   • {stats.strategy}: {stats.win_rate:.2f}% win rate, Wilson: {stats.wilson_score:.4f}")
        
        print(f"\n📁 Relatórios salvos em: {output_path}")


def main() -> int:
    print("="*80)
    print("🔬 BACKTEST FULL - Sistema EvePulse")
    print("="*80)
    
    # Configurar diretórios
    base_dir = Path(__file__).resolve().parent
    data_dir = base_dir / "dados" / "iq_option" / "m1"
    output_dir = base_dir / "backtest_results"
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Inicializar engine
    engine = BacktestEngine(data_dir)
    
    # Carregar dados
    if not engine.load_data():
        return 1
    
    # Selecionar estratégias
    print("\n" + "-"*80)
    print("ESTRATÉGIAS DISPONÍVEIS:")
    print("-"*80)
    strategies_list = [
        ("1", "S1 - Três Velas Reversão"),
        ("2", "S5 - Primeiro Retorno M1"),
        ("3", "S5-M5 - Primeiro Retorno M5"),
        ("4", "S5-M15 - Primeiro Retorno M15"),
        ("5", "S9 - Lateral H1 Reversão"),
        ("6", "S13 - Pavios de Rejeição"),
        ("7", "S14 - Continuação Rejeição"),
        ("8", "S15 - Falso Rompimento"),
        ("9", "S16 - Engolfo M5/M15"),
        ("10", "S17 - Rompimento Dupla Posição"),
        ("11", "S1 (Lab) - Engolfo com Retorno"),
        ("12", "S2 (Lab) - Zonas M15"),
        ("13", "S6 (Lab) - Varredura M5"),
        ("14", "S7 (Lab) - Captura de Pavio"),
        ("15", "S10 (Lab) - Toques Nível"),
        ("T", "TODAS as 15 estratégias"),
    ]
    
    for code, name in strategies_list:
        print(f"  [{code}] {name}")
    
    selection = input("\nDigite os números das estratégias (ex: 1,3,5 ou T para todas): ").strip().upper()
    
    selected_strats = None
    if selection != "T" and selection.strip():
        selected_codes = [c.strip() for c in selection.split(",")]
        strat_map = {
            "1": "S1", "2": "S5", "3": "S5-M5", "4": "S5-M15", "5": "S9",
            "6": "S13", "7": "S14", "8": "S15", "9": "S16", "10": "S17",
            "11": "S1-Lab", "12": "S2-Lab", "13": "S6-Lab", "14": "S7-Lab", "15": "S10-Lab"
        }
        selected_strats = [strat_map[c] for c in selected_codes if c in strat_map]
    
    # Executar backtest
    engine.run_backtest(selected_strats)
    
    # Gerar relatório
    engine.generate_report(output_dir)
    
    print("\n✅ Backtest concluído com sucesso!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
    
    def _strategy_s7_lab(self, symbol: str, df: pd.DataFrame) -> List[Trade]:
        """S7 (Lab) - Captura de Pavio com Reversão."""
        trades = []
        min_wick_ratio = 0.3
        
        for i in range(1, len(df) - 1):
            prev = df.iloc[i-1]
            curr = df.iloc[i]
            
            prev_range = self._get_candle_range(prev)
            if prev_range == 0:
                continue
            
            upper_wick = self._get_upper_wick(prev)
            lower_wick = self._get_lower_wick(prev)
            
            # Reversão de baixa após pavio superior
            if upper_wick >= (prev_range * min_wick_ratio):
                if self._is_red(curr) and curr['close'] < prev['low']:
                    trades.append(Trade(
                        symbol=symbol,
                        strategy="S7-Lab-CapturaPavio",
                        timestamp=int(curr['from_ts']),
                        direction="PUT",
                        entry_price=float(curr['close']),
                        result=self._check_result(df, i, "PUT")
                    ))
            
            # Reversão de alta após pavio inferior
            elif lower_wick >= (prev_range * min_wick_ratio):
                if self._is_green(curr) and curr['close'] > prev['high']:
                    trades.append(Trade(
                        symbol=symbol,
                        strategy="S7-Lab-CapturaPavio",
                        timestamp=int(curr['from_ts']),
                        direction="CALL",
                        entry_price=float(curr['close']),
                        result=self._check_result(df, i, "CALL")
                    ))
        
        return trades
    
    def run_backtest(self, strategies: Optional[List[str]] = None) -> Dict[str, StrategyStats]:
        """Executa backtest para todas ou estratégias selecionadas."""
        print("\n🚀 Iniciando backtest...")
        
        all_strategies = {
            "S1-TresVelasReversao": self._strategy_s1,
            "S5-PrimeiroRetornoM1": self._strategy_s5_m1,
            "S13-PaviosRejeicao": self._strategy_s13,
            "S7-Lab-CapturaPavio": self._strategy_s7_lab,
        }
        
        if strategies:
            all_strategies = {k: v for k, v in all_strategies.items() if k.split('-')[0] in strategies}
        
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
        ("3", "S13 - Pavios de Rejeição"),
        ("4", "S7 (Lab) - Captura de Pavio"),
        ("T", "TODAS as estratégias"),
    ]
    
    for code, name in strategies_list:
        print(f"  [{code}] {name}")
    
    selection = input("\nDigite os números das estratégias (ex: 1,3 ou T para todas): ").strip().upper()
    
    selected_strats = None
    if selection != "T" and selection.strip():
        selected_codes = [c.strip() for c in selection.split(",")]
        strat_map = {"1": "S1", "2": "S5", "3": "S13", "4": "S7"}
        selected_strats = [strat_map[c] for c in selected_codes if c in strat_map]
    
    # Executar backtest
    engine.run_backtest(selected_strats)
    
    # Gerar relatório
    engine.generate_report(output_dir)
    
    print("\n✅ Backtest concluído com sucesso!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

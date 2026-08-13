import os
import sys
import time
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path

# Adiciona o diretório atual ao path para importar evemexapi
sys.path.append(str(Path(__file__).parent))

from evemexapi.client import EvemexClient
from evemexapi.exceptions import AuthenticationError

def download_history():
    # Configurações
    email = input("📧 Email Evemex: ").strip()
    password = input("🔑 Senha Evemex: ").strip()
    
    client = EvemexClient(email, password)
    
    try:
        print("\n🔄 Autenticando na Evemex...")
        client.connect()
        print("✅ Autenticado com sucesso!")
    except AuthenticationError as e:
        print(f"❌ Erro de autenticação: {e}")
        return

    # Define o período: últimos 15 dias
    end_date = datetime.now()
    start_date = end_date - timedelta(days=15)
    
    print(f"📅 Período: {start_date.strftime('%d/%m/%Y')} até {end_date.strftime('%d/%m/%Y')}")

    # Obtém ativos OTC
    print("🔍 Buscando ativos OTC ativos...")
    assets = client.get_otc_assets(detailed=False)
    symbols = [a['symbol'] for a in assets]
    print(f"✅ Encontrados {len(symbols)} ativos OTC.")

    # Pasta para salvar os dados
    output_dir = Path("corretora-evemex/dados/m1")
    output_dir.mkdir(parents=True, exist_ok=True)

    for symbol in symbols:
        print(f"\n📈 Baixando histórico para {symbol}...")
        all_candles = []
        
        # A API get_candles tem limite de 500 por chamada
        # Vamos baixar em blocos
        current_to = int(end_date.timestamp())
        target_from = int(start_date.timestamp())
        
        while current_to > target_from:
            try:
                # Calcula o from para este bloco (aproximadamente 500 minutos atrás)
                current_from = current_to - (500 * 60)
                if current_from < target_from:
                    current_from = target_from
                
                candles = client.get_candles(
                    symbol=symbol,
                    timeframe="1m",
                    limit=500,
                    from_ts=current_from,
                    to_ts=current_to
                )
                
                if not candles:
                    break
                
                all_candles.extend(candles)
                
                # Atualiza o to para o próximo bloco (um segundo antes do candle mais antigo baixado)
                current_to = candles[0].from_ts - 1
                
                print(f"   - Baixados {len(candles)} candles... (Restante: {max(0, (current_to - target_from)//60)} min)", end="\r")
                time.sleep(0.5) # Evitar rate limit
                
            except Exception as e:
                print(f"\n❌ Erro ao baixar bloco para {symbol}: {e}")
                break
        
        if all_candles:
            # Converte para DataFrame e salva
            df_data = []
            for c in all_candles:
                df_data.append({
                    'from_ts': c.from_ts,
                    'open': c.open,
                    'high': c.high,
                    'low': c.low,
                    'close': c.close,
                    'volume': getattr(c, 'volume', 0)
                })
            
            df = pd.DataFrame(df_data)
            df = df.sort_values('from_ts').drop_duplicates('from_ts')
            
            file_path = output_dir / f"{symbol}.parquet"
            df.to_parquet(file_path)
            print(f"\n✅ {symbol}: {len(df)} candles salvos em {file_path}")
        else:
            print(f"\n⚠️ Nenhum dado encontrado para {symbol}")

    print("\n✨ Download concluído!")

if __name__ == "__main__":
    download_history()
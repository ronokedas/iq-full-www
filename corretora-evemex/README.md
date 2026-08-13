# Cliente Evemex e robô S13 M1

Projeto Python sem dependências externas obrigatórias. Ele usa a API consumida pela aplicação web da Evemex; essa API não é oficialmente documentada e pode mudar.

## Segurança

- O programa pergunta se deve usar a conta `DEMO` ou `REAL`.
- Após selecionar a conta, todo sinal aprovado pela IA abre uma operação automaticamente nessa conta.
- Senha e token nunca são gravados nos logs.
- Comece pela conta demo e acompanhe os logs antes de usar dinheiro real.
- Altere a senha que foi compartilhada durante o desenvolvimento antes de usar dinheiro real.

## Configuração

No PowerShell, defina as credenciais somente na sessão atual:

```powershell
$env:EVEMEX_EMAIL='seu-email@example.com'
$env:EVEMEX_PASSWORD='sua-senha'
```

Também é possível omitir essas variáveis; o programa solicitará e-mail e senha, escondendo a senha durante a digitação.

Também é possível escolher **Google** ao iniciar. O robô abre uma janela normal e dedicada do Microsoft Edge para você concluir o login e qualquer 2FA; ao voltar para a Evemex, confirme com `ENTER` no terminal. A sessão é salva no Gerenciador de Credenciais do Windows e é validada antes de operar; se expirar, o Edge será aberto novamente. Tokens e cookies nunca são gravados nos logs ou em arquivos do projeto.

## Execução recomendada

Iniciar o robô:

```powershell
.\run_bot.ps1
```

O programa pergunta o método de login, conta e valor por entrada. Não há modo somente análise, stop-loss total ou limite de operações.

## Estratégia ativa: S13

- Somente a S13 está habilitada para análise e entradas automáticas; S01, S16 e S5-M5 estão desativadas.
- A S13 confirma no segundo 59 da terceira vela M1 e envia a ordem para a abertura da quarta vela M1.
- CALL: três velas vermelhas; a primeira tem pavio inferior real e as duas seguintes fecham acima de sua mínima.
- PUT: três velas verdes; a primeira tem pavio superior real e as duas seguintes fecham abaixo de sua máxima.
- A entrada e a expiração são M1, e a IA exige probabilidade calibrada mínima de 65%.
- Todos os ativos OTC ativos são analisados; ativos de mercado real são ignorados.

Os eventos são gravados em `logs/trades-AAAA-MM-DD.jsonl`.

## Testes

```powershell
.\run_tests.ps1
```

O lançador tenta o Python do sistema e, nesta máquina, usa automaticamente o runtime funcional fornecido pelo Codex caso a instalação global esteja quebrada.

O teste integrado é somente leitura e fica desativado por padrão:

```powershell
$env:EVEMEX_INTEGRATION='1'
.\run_tests.ps1
```

Nenhum teste automatizado abre operações.

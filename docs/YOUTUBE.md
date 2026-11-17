# Links do YouTube no TrustVoice

O YouTube bloqueia downloads feitos a partir de servidores de nuvem (Railway, AWS, etc.). A página e o título do vídeo carregam, mas o áudio volta com "Sign in to confirm you're not a bot" ou "HTTP Error 403". Para o servidor conseguir baixar, configure **cookies**, **proxy residencial** ou os dois. Usar os dois juntos é o mais confiável.

Vimeo, TikTok, Instagram e as outras plataformas liberadas costumam funcionar sem nada disso.

## Opção A: cookies de uma conta Google secundária (grátis)

1. Crie ou use uma conta Google **secundária**. Nunca use a sua conta principal: o YouTube pode sinalizar a conta usada para downloads automáticos.
2. Abra uma **janela anônima** no Chrome, entre nessa conta e abra https://www.youtube.com. Assista alguns segundos de qualquer vídeo.
3. Instale a extensão **Get cookies.txt LOCALLY** (permita que ela rode na janela anônima) e exporte os cookies do youtube.com no formato Netscape. Você terá um arquivo `cookies.txt`.
4. Feche a janela anônima **sem sair da conta** (sair invalida os cookies).
5. Converta o arquivo para base64:
   - Windows (PowerShell): `[Convert]::ToBase64String([IO.File]::ReadAllBytes("$HOME\Downloads\cookies.txt")) | Set-Clipboard`
   - Mac: `base64 -i ~/Downloads/cookies.txt | pbcopy`
6. No Railway: serviço → **Variables** → **New Variable**
   - Nome: `YTDLP_COOKIES_B64`
   - Valor: cole o texto em base64
7. Salve. O Railway reinicia o serviço sozinho.

Os cookies expiram com o tempo (geralmente semanas). Quando o site voltar a mostrar "O YouTube recusou o download mesmo com cookies/proxy configurados", repita os passos 2 a 6.

## Opção B: proxy residencial (pago, mais estável)

1. Contrate um proxy **residencial** (não "datacenter"). Exemplos: IPRoyal, Webshare (plano residential), Decodo/Smartproxy, Bright Data. Planos por GB costumam bastar: um vídeo de 10 min em áudio usa uns 10 a 20 MB.
2. O provedor entrega um endereço no formato `http://usuario:senha@host:porta` (ou `socks5://...`). Se puder escolher o país, use Brasil.
3. No Railway: **Variables** → **New Variable**
   - Nome: `YTDLP_PROXY`
   - Valor: `http://usuario:senha@host:porta`
4. Salve.

O proxy é usado **só** para downloads de vídeo pelo yt-dlp. OpenAI, Supabase e o resto do site continuam saindo direto.

## Como conferir

Abra `https://SEU-DOMINIO/health`. Os campos mostram o que o servidor está usando (nunca mostram os valores):

- `"ytdlp_cookies": true`: cookies válidos carregados
- `"ytdlp_proxy": true`: proxy válido carregado
- `"js_runtime": true`: Deno instalado (o YouTube exige para resolver os desafios em JavaScript)

Se um campo continuar `false` depois de configurar, o valor está em formato errado (o servidor ignora e registra um aviso no log do Railway).

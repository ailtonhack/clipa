# Clipa — estúdio de cortes pela fala

Esta versão inclui backend Python e interface em português. Implementação própria, inspirada no fluxo de ferramentas como OpusClip.

## O que está implementado

- Upload local de vídeos até 1 GB e 2 horas.
- Importação de vídeos públicos do YouTube e vídeos/clips públicos da Twitch e Kick usando yt-dlp. Transmissões ao vivo não são suportadas. Downloads dependem da disponibilidade e das restrições de cada provedor.
- Extração do áudio em partes de cinco minutos, transcrição com timestamps e sugestões de cortes pela fala via OpenAI.
- Revisão dos tempos dos cortes e edição do texto das legendas.
- Renderização real com FFmpeg: MP4 H.264/AAC, recorte central em 9:16 ou 1:1, ou proporção original. Legendas incorporadas no vídeo e download de SRT.
- OAuth e adaptadores de envio para YouTube, TikTok, Páginas do Facebook e Instagram profissional vinculado a uma Página.
- Agenda persistida em SQLite, publicação no horário pelo servidor, cancelamento antes do envio e acompanhamento de estado. O servidor deve permanecer ligado. Depois de uma falha ou interrupção durante envio, o item exige verificação na rede e não é repetido automaticamente.

As contas sociais não estão conectadas. Os conectores estão escritos, mas exigem configuração e testes reais com as contas e aplicativos oficiais. A aprovação dos aplicativos pode limitar publicação e visibilidade. A análise por IA também exige chave e saldo na API OpenAI.

## Executar no computador

Requisitos: Python 3.12+, FFmpeg/FFprobe com filtro subtitles (libass), fonte DejaVu Sans e Node.js 22+ para os desafios JavaScript do YouTube.

Na pasta do projeto:

    python3 -m venv .venv
    .venv/bin/pip install -r requirements.txt
    .venv/bin/python start.py

Abra http://localhost:8000. No Windows, os executáveis do ambiente ficam em `.venv\Scripts` em vez de `.venv/bin`.

Use Conectar IA para informar sua chave nesta sessão ou copie `.env.example` para `.env` e preencha `OPENAI_API_KEY`. O lançador lê `.env` sem executar seu conteúdo. A cobrança da IA ocorre na sua conta OpenAI. A chave digitada na interface é enviada ao próprio backend e não é salva no banco; a chave do servidor permanece somente na configuração do ambiente.

Cole o link de um vídeo, importe, analise a fala, revise as legendas e gere o MP4. Para a Kick, use o link compartilhado de um clip, como `https://kick.com/<canal>/clips/clip_<id>` ou o formato com `?clip=clip_<id>`. Para Twitch, use o link do clip ou de um VOD. Links de canais e playlists não representam vídeos únicos.

## Conectar as contas oficiais

O projeto contém `.env.example` sem credenciais. Preencha os valores no seu próprio servidor e reinicie. Nunca compartilhe arquivos `.env` ou a pasta `data`.

| Rede | Variáveis | Callback a cadastrar no aplicativo |
| --- | --- | --- |
| YouTube | YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET | /api/oauth/youtube/callback |
| TikTok | TIKTOK_CLIENT_ID, TIKTOK_CLIENT_SECRET | /api/oauth/tiktok/callback |
| Facebook e Instagram | META_CLIENT_ID, META_CLIENT_SECRET | /api/oauth/facebook/callback |

Prefixe cada callback com `CLIPA_BASE_URL`. Exemplo: `https://seu-dominio.com/api/oauth/youtube/callback`. Configure exatamente esse endereço no painel da plataforma.

- Google: aplicativo OAuth do tipo Web, YouTube Data API v3 ativada, permissões youtube.upload e youtube.readonly, usuários de teste ou aplicação verificada. Aplicativos de upload não auditados podem enviar apenas vídeos privados.
- TikTok: Login Kit e Content Posting API / Direct Post, escopos user.info.basic e video.publish, domínio/callback registrado e aprovação para publicação pública. A versão atual envia com comentários, dueto e stitch desativados e solicita autorização explícita no agendamento. A interface e o uso precisam ser validados na auditoria do TikTok antes da operação pública.
- Meta: Facebook Login e permissões pages_show_list, pages_read_engagement, pages_manage_posts, instagram_basic e instagram_content_publish. Facebook publica em Páginas, não em perfis pessoais. Instagram exige conta profissional vinculada a uma Página. Aprovação e acesso avançado podem ser necessários. O código usa Graph API v23.0; confira requisitos e versões do aplicativo na implantação.

Os botões só ficam habilitados quando as credenciais e a URL necessária estão configuradas. Instagram e Facebook são conectados pelo mesmo login Meta. As contas conectadas aparecem por nome na agenda. Os tokens são criptografados em repouso. Desconectar remove os tokens locais e cancela itens ainda agendados; para revogar o aplicativo na plataforma, use também o painel da respectiva conta.

## Hospedar e manter o agendamento

É necessário um servidor Linux com processos persistentes, FFmpeg, espaço em disco e HTTPS. O backend Python/FFmpeg não roda diretamente no runtime Cloudflare Workers do Sites. Esta entrega não está publicada e não inclui provisionamento de hospedagem.

Há um Dockerfile para preparar a implantação. Ele não foi construído/testado neste ambiente. Exemplo de uso depois de configurar `.env` e um proxy HTTPS:

    docker build -t clipa .
    docker run -d --name clipa --restart unless-stopped --env-file .env -p 127.0.0.1:8000:8000 -v clipa-data:/app/data clipa

Configure `CLIPA_BASE_URL=https://seu-dominio.com` e `CLIPA_PASSWORD` antes de usar um endereço público. O acesso será solicitado pelo navegador: usuário `clipa` e a senha configurada. Os callbacks OAuth e as URLs temporárias assinadas para o Instagram funcionam sem essa autenticação. Para o Instagram buscar o vídeo, o endereço precisa ser acessível publicamente via HTTPS; cada link de mídia expira em uma hora.

Use um único processo de aplicação. A versão é um estúdio pessoal, com um espaço e uma senha de acesso. Não possui contas de múltiplos clientes, planos pagos ou isolamento por usuário. Persista a pasta `data`: ela contém o banco, vídeos, exports e a chave de criptografia dos tokens. Perder a chave exige reconectar as contas. Os arquivos são mantidos localmente; limpe ou arquive quando necessário. Agendamentos vencidos durante desligamento são processados quando o servidor volta, salvo itens que ficaram em estado de envio incerto.

## Verificação realizada

- 10 testes automatizados passaram: validação de links, limites de cortes, sincronização de SRT, upload, renderização real em 9:16 com áudio, edição de legendas, validação do agendamento, proteção OAuth, autenticação, links assinados e transcrição/análise com respostas de IA simuladas.
- Teste em Chromium: upload real, sugestões com IA simulada, revisão de legendas, renderização real, download MP4/SRT, estado das conexões e layout desktop/celular.
- A sintaxe Python e JavaScript foi verificada.
- Não houve chamadas pagas reais à IA, autenticação de contas sociais, publicação real ou validação de downloads nas três plataformas. Essas etapas dependem das credenciais e dos links de teste do usuário.

Para executar os testes:

    .venv/bin/python -m pytest -q

O teste opcional `tests/browser.cjs` usa Playwright e Chromium; os caminhos de execução podem precisar de ajuste no seu computador. As imagens `preview-desktop.png` e `preview-mobile.png` mostram a interface testada com conteúdo fictício.

## Limites atuais

Recorte central, sem acompanhamento automático de rosto. Legendas sincronizadas por segmentos, sem destaque palavra por palavra. Sem renderização em 4K ou download de conteúdo que exige login. Sem editor completo de timeline ou efeitos. Esta implementação não usa o código proprietário do OpusClip.

## Implantação preparada no Railway

Veja [deploy/RAILWAY.md](deploy/RAILWAY.md). A configuração inclui Dockerfile, verificação de saúde, porta automática e detecção do domínio Railway. Ainda é necessário conectar sua conta de hospedagem, criar o volume persistente e configurar as credenciais oficiais. Nenhum serviço foi publicado ou recurso pago criado nesta etapa.

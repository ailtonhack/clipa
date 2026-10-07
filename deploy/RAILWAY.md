# Implantação do Clipa no Railway

Estado: arquivos preparados; serviço ainda não criado ou publicado. Não há Railway conectado nesta conversa, e não foram provisionados recursos pagos.

## Configuração preparada

O `railway.json` seleciona o Dockerfile e a verificação `/api/health`. O Dockerfile instala FFmpeg, fontes para legendas e Node.js para o downloader. O processo usa a porta fornecida pelo Railway. Se `CLIPA_BASE_URL` não estiver definida, o endereço HTTPS é detectado por `RAILWAY_PUBLIC_DOMAIN`.

## Procedimento na conta

1. Conecte o Railway a esta conversa, ou entre no painel Railway com sua conta. A criação de hospedagem pode gerar custos; confirme o plano e os valores no provedor.
2. Disponibilize o código pelo repositório Git de sua preferência, sem `.env`, `.venv` ou `data`. O ZIP entregue contém o código e não contém credenciais. Se for usar CLI Railway, execute o envio a partir da pasta com `railway.json`.
3. Crie um único serviço usando este Dockerfile. Use uma única réplica e mantenha o serviço ativo, pois há uma fila de agendamento no processo. Não habilite suspensão por inatividade.
4. Anexe um volume persistente no caminho `/app/data`. Ele guarda SQLite, vídeos, cortes e a chave dos tokens. Sem volume, uma nova implantação pode apagar arquivos, contas e agendamentos.
5. Configure `CLIPA_DATA_DIR=/app/data` e uma senha forte em `CLIPA_PASSWORD` no painel de variáveis secretas. O usuário de acesso é `clipa`. Não envie senhas ou chaves no chat.
6. Gere o domínio público HTTPS do serviço. Deixe `CLIPA_BASE_URL` ausente para detectar o domínio Railway automaticamente; para domínio próprio, configure `CLIPA_BASE_URL=https://seu-dominio.com`.
7. Configure `OPENAI_API_KEY` no painel de variáveis secretas, ou use Conectar IA depois de abrir o site. O uso da API tem cobrança separada da hospedagem.
8. Implante e aguarde a verificação de saúde. Teste `/api/health` e abra o endereço do site; a página deverá solicitar a senha configurada.

## Conectar as redes

Depois que o endereço HTTPS estiver confirmado, crie/configure os aplicativos oficiais e preencha as variáveis secretas:

| Plataforma | Variáveis | Callback |
| --- | --- | --- |
| YouTube | YOUTUBE_CLIENT_ID / YOUTUBE_CLIENT_SECRET | https://DOMINIO/api/oauth/youtube/callback |
| TikTok | TIKTOK_CLIENT_ID / TIKTOK_CLIENT_SECRET | https://DOMINIO/api/oauth/tiktok/callback |
| Facebook e Instagram | META_CLIENT_ID / META_CLIENT_SECRET | https://DOMINIO/api/oauth/facebook/callback |

Não basta conectar o Railway para ter as redes autorizadas. Os aplicativos precisam das permissões descritas no README e, quando exigido, da aprovação da plataforma. Faça o login e dê as permissões dentro das páginas oficiais abertas pelos botões do Clipa. Para Instagram, use conta profissional vinculada a uma Página do Facebook.

## Validação antes de usar

- Importe um link público de conteúdo seu ou autorizado em cada plataforma desejada. Links protegidos ou bloqueados pelo provedor podem falhar.
- Analise um vídeo curto e confira a transcrição e os trechos sugeridos; haverá consumo da API OpenAI.
- Exporte um corte com legendas e confirme imagem, áudio e sincronização.
- Conecte uma conta de teste oficial. Agende uma publicação somente quando você quiser de fato publicá-la; confira a conta de destino e a visibilidade antes de confirmar.
- Verifique o resultado na própria rede. Aplicativos ainda não auditados podem ter limitações de publicação e visibilidade.

A implantação do contêiner e as integrações reais não foram verificadas nesta conversa. Os testes locais verificam o processamento e a interface. O projeto é um estúdio pessoal; não é um serviço com múltiplos usuários.

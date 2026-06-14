# Changelog — HA Intercom

## 1.3.3
- Correção: "failed to fetch" no atendimento WebRTC — SDP offer agora proxiado pelo Flask (`/api/webrtc/offer`) para evitar CORS/bloqueio de porta
- Áudio bidirecional: duas RTCPeerConnections por chamada (publisher e subscriber) com streams direcionais `_caller`/`_callee`
- Página de chamada com papéis (caller/callee): chamador vê "Ligando..." e aguarda atendimento via polling; chamado vê botões Atender/Rejeitar
- Sons de toque: padrão brasileiro (dois bipes) para chamada recebida; tom de discagem para chamador
- Vibração haptic ao receber chamada
- Chamador redirecionado automaticamente para página de chamada ao iniciar (`/call/{id}?role=caller`)
- Notificação push incluiu `?role=callee` na URL de atendimento

## 1.3.2
- Correção: criação de stream go2rtc com `echo:` falhava com 400 porque `requests` codificava o `:` como `%3A`; URL agora construída manualmente
- Correção: atender chamada já em estado `active` (duplo toque na notificação) retornava 404; endpoint agora retorna 200 com o estado atual
- Página de atendimento trata resposta `active` sem lançar erro

## 1.3.1
- Correção: adicionado `hassio_api: true` e `hassio_role: manager` para permitir chamadas à Supervisor API
- Sem essas permissões o botão de atualização manual e o `auto_update` não conseguiam acionar o Supervisor
- Log de erro detalhado no endpoint `/api/addon/update`

## 1.3.0
- `panel_admin: false`: painel visível para todos os usuários (não só admins)
- Página de atendimento WebRTC (`/call/<call_id>`) com UI de chamada recebida
- Notificação push agora inclui URL de destino: tocar em "Atender" abre a página de chamada direto
- `clickAction` na notificação abre a página de atendimento ao tocar na notificação
- Notificação persistente e sticky para não sumir antes de atender
- `ingress_url` obtido da Supervisor API para montar o link correto de atendimento

## 1.2.4
- Correção: path do ingress injetado server-side via header `X-Ingress-Path`
- Corrige acesso via Nabu Casa e HA frontend (BASE calculado no servidor, não no browser)

## 1.2.3
- Botão de atualização manual na aba Configurações
- Verificação automática de versão ao carregar o painel
- Changelog adicionado ao repositório (esta tela)

## 1.2.2
- Correção: URLs relativas no painel para funcionar via Nabu Casa (remote UI)
- Status do go2rtc verificado server-side via `/health` (sem CORS)
- Link de health dinâmico construído após carregamento

## 1.2.1
- `auto_update: true` habilitado no manifesto do add-on

## 1.2.0
- Aba **Dispositivos**: descoberta automática de mobile_app e Voice PE do HA
- Cadastro de dispositivos via UI (sem edição de YAML)
- Campo de **apelido** e **sala** para cada dispositivo
- Dispositivos salvos em `/data/intercom_devices.json`
- Ícone do menu lateral alterado para `mdi:phone-in-talk`

## 1.1.1
- Correção: SyntaxError em f-string com backslash (Python 3.11)

## 1.1.0
- **Watchdog** duplo: HA Supervisor monitora `/health`; supervisor interno reinicia após 3 falhas consecutivas
- Endpoint `GET /health` retorna uptime, chamadas ativas e status do go2rtc
- **Painel lateral** completo com 3 abas: Chamadas, Dispositivos, Configurações
- Grid de dispositivos com botões de chamada por dispositivo
- Lista de chamadas ativas com duração, estado e botão de encerrar
- Cards de dispositivo destacados em amarelo (chamando) ou verde (em chamada)
- Polling automático a cada 3s

## 1.0.4
- Substitui serviços s6-overlay por `supervisor.py` como PID 1
- Resolve crash `s6-overlay-suexec: fatal: can only run as pid 1`
- Gerenciamento de processos go2rtc e Flask via Python com restart automático

## 1.0.3
- Tentativa de serviços s6-overlay v3 (go2rtc, intercom-api, init-intercom)

## 1.0.2
- Correção: `pip3 install` com `--break-system-packages` para Alpine 3.19 (PEP 668)

## 1.0.1
- Correção: `COPY rootfs/ /` removido (diretório vazio não é rastreado pelo git)
- Correção: entrada `ssl:r` inválida removida do `map` no config.yaml
- Valor padrão adicionado ao `ARG BUILD_FROM` no Dockerfile

## 1.0.0
- Versão inicial
- Add-on instala e configura go2rtc (WebRTC, RTSP, API)
- API de sinalização Flask (porta 8099) com endpoints de chamada
- Suporte a Android (notificações push com Atender/Rejeitar) e Voice PE (TTS + RTSP)
- Componente customizado `ha_intercom` com entidades `button` e serviços HA
- Config flow para integração via UI
- Eventos HA: `ha_intercom_call_initiated`, `ha_intercom_call_answered`, `ha_intercom_call_rejected`, `ha_intercom_call_ended`
- Watchdog automático para timeout e duração máxima de chamadas
- Multi-arch: aarch64 (RPi 4) e amd64

# Changelog — HA Intercom

## 2.0.2
- Correção de áudio: `remoteAudio` agora é variável global acessível por `onConnected()`, que chama `.play()` quando ICE conecta
- `srcObject` criado como `new MediaStream()` antes de `ontrack`, e reassociado ao elemento após adicionar cada faixa
- Erros de `.play()` agora logados no debug em vez de silenciados
- Log de `ontrack` mostra o tipo da faixa (`audio`/`video`) para diagnóstico

## 2.0.1
- Correção crítica: Dockerfile usava `CMD` em vez de `ENTRYPOINT` — com a imagem base do HA (s6-overlay), isso causava erro "can only run as pid 1" e o add-on não iniciava
- Removidos supervisor.py e generate_config.py do diretório app/ (não usados no v2.0)
- Corrigido mapeamento user_id→device_id: agora lê corretamente `data.device_name` da config entry do mobile_app

## 2.0.0
- Reescrita completa do addon do zero (from scratch)
- Arquitetura simplificada: Flask como unico servidor (sem go2rtc, sem supervisor.py)
- WebRTC P2P direto entre browsers com sinalização SDP via Flask
- Descoberta automatica de dispositivos mobile_app via Supervisor API
- Deteccao automatica do dispositivo do usuario logado via X-Remote-User-ID
- Painel lateral redesenhado com UI moderna (dark theme)
- Tela de chamada com timer, mute e debug log
- Notificacoes push com acoes de Atender/Rejeitar via URI
- Limpeza automatica de notificacoes ao atender ou rejeitar
- Endpoints REST: /api/devices, /api/my_device, /api/call/*, /api/sdp/*
- Refresco automatico de dispositivos a cada 5 minutos em background
- Watchdog via GET /health com uptime
- Removidos: go2rtc.yaml, ha_client.py, intercom.py, supervisor.py, generate_config.py

## 1.3.10
- Debug: log de diagnostico visivel na tela de chamada (cada etapa WebRTC/ICE) para identificar onde o audio falha
- UX: aba Dispositivos agora mostra apenas botao "Chamar XXX" + botao de remover
- Sem outras mudancas funcionais nesta versao - diagnostico do audio mudo

## 1.3.9
- Correcao critica de audio bidirecional: callee agora faz `setRemoteDescription(offer)` ANTES de `getUserMedia`+`addTrack`+`createAnswer` - ordem correta para SDP negociation
- Botao de mudo ao lado de Encerrar (aparece apos conectar); alterna microfone local sem encerrar chamada
- Ao encerrar chamada: aguarda 2s e redireciona para tela principal (`BASE + '/'`) em vez de `history.back()`
- Notificacao "Atender" usa `auto_answer=1`: abre a tela de chamada e atende automaticamente
- Notificacao "Rejeitar" usa `action=reject`: rejeita a chamada server-side e exibe confirmacao
- Apos atender ou rejeitar: notificacao limpa nos dois dispositivos (caller e callee)
- `ontrack` do caller agora usa `e.track` diretamente (igual ao callee) para garantir audio remoto
- `onConnected()` protegido contra dupla execucao com guard `if (connected) return`

## 1.3.8
- UX: removido seletor "Chamando de:" da aba Chamadas
- UX: cada card de dispositivo tem um botao com o apelido do dispositivo a ser chamado
- UX: adicionado "Meu dispositivo" na aba Configuracoes (salvo em localStorage)
- Correcao audio: `ontrack` agora usa `e.track` diretamente

## 1.3.7
- Correcao UX: painel de chamadas redesenhado
- Adicionado seletor "Chamando de:" para escolher explicitamente seu proprio dispositivo
- Selecao do dispositivo salva em localStorage para persistir entre sessoes

## 1.3.6
- Correcao: ICE nao-trickle enviava SDP incompleto
- Implementado trickle ICE real com candidatos trocados via polling

## 1.3.5
- Correcao: go2rtc nao suporta publicacao WebRTC via HTTP POST
- Nova arquitetura: WebRTC P2P direto entre browsers

## 1.3.4
- Correcao: SyntaxError no f-string da pagina de chamada

## 1.3.3
- Correcao: "failed to fetch" no atendimento WebRTC
- Audio bidirecional com duas RTCPeerConnections por chamada

## 1.3.2
- Correcao: criacao de stream go2rtc com `echo:` falhava
- Correcao: atender chamada ja em estado `active` retornava 404

## 1.3.1
- Correcao: adicionado `hassio_api: true` e `hassio_role: manager`

## 1.3.0
- `panel_admin: false`: painel visivel para todos os usuarios
- Pagina de atendimento WebRTC com UI de chamada recebida
- Notificacao push com URL de destino

## 1.2.4
- Correcao: path do ingress injetado server-side via header `X-Ingress-Path`

## 1.2.3
- Botao de atualizacao manual na aba Configuracoes
- Verificacao automatica de versao ao carregar o painel

## 1.2.2
- Correcao: URLs relativas no painel para funcionar via Nabu Casa

## 1.2.1
- `auto_update: true` habilitado no manifesto do add-on

## 1.2.0
- Aba Dispositivos: descoberta automatica de mobile_app e Voice PE
- Cadastro de dispositivos via UI

## 1.1.1
- Correcao: SyntaxError em f-string com backslash

## 1.1.0
- Watchdog duplo
- Endpoint GET /health
- Painel lateral completo com 3 abas

## 1.0.4
- Substitui servicos s6-overlay por `supervisor.py` como PID 1

## 1.0.3
- Tentativa de servicos s6-overlay v3

## 1.0.2
- Correcao: `pip3 install` com `--break-system-packages` para Alpine 3.19

## 1.0.1
- Correcoes de Dockerfile e config.yaml

## 1.0.0
- Versao inicial

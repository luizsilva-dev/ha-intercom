# HA Intercom

Add-on para Home Assistant que implementa um sistema de intercom bidirecional entre dispositivos usando **go2rtc** e **WebRTC**.

## Funcionalidades

- Chamadas bidirecionais de áudio entre app Android (HA Companion) e dispositivos Voice PE
- Sinalização via API REST própria
- Integração nativa com notificações do app Android (botões Atender/Rejeitar)
- Anúncio de chamada via TTS no Voice PE
- Entidades `button` no HA para iniciar chamadas com um toque
- Eventos HA para automações personalizadas

## Arquitetura

```
┌─────────────────────────────────────────────────────────┐
│                    Raspberry Pi 4                        │
│                                                         │
│  ┌──────────────┐     ┌──────────────────────────────┐  │
│  │   go2rtc     │     │   Intercom Signaling API     │  │
│  │  :1984 (API) │     │        Flask :8099           │  │
│  │  :8554 (RTSP)│◄────│  - Gerencia chamadas         │  │
│  │  :8555 (WebRTC)    │  - Cria streams go2rtc       │  │
│  └──────────────┘     │  - Notifica dispositivos     │  │
│                       └──────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
         │                          │
         ▼                          ▼
  WebRTC stream              HA Events / REST API
         │
   ┌─────┴──────┐
   │            │
Android App   Voice PE
(WebRTC)     (RTSP/TTS)
```

## Instalação

### 1. Add-on

1. No HA, vá em **Configurações → Add-ons → Loja de add-ons**
2. Clique nos três pontos → **Repositórios**
3. Adicione: `https://github.com/luizsilva-dev/ha-intercom`
4. Instale **HA Intercom**
5. Configure os dispositivos (veja abaixo)
6. Inicie o add-on

### 2. Componente customizado

Copie a pasta `custom_components/ha_intercom/` para o diretório `custom_components/` da sua instalação HA, depois reinicie o HA.

Alternativamente, use o [HACS](https://hacs.xyz/):
1. HACS → Integrações → Menu → Repositórios customizados
2. URL: `https://github.com/luizsilva-dev/ha-intercom` | Categoria: Integration

### 3. Integração

Em **Configurações → Dispositivos e Serviços → Adicionar Integração**, procure "HA Intercom" e siga o assistente de configuração.

## Configuração do Add-on

```yaml
devices:
  - name: android_sala       # identificador único (sem espaços)
    type: android
    room: Sala
    mobile_app_id: pixel_8   # ID do dispositivo no HA (mobile_app_<id>)

  - name: android_quarto
    type: android
    room: Quarto
    mobile_app_id: samsung_s23

  - name: voice_pe_cozinha
    type: voice_pe
    room: Cozinha
    ha_device_id: media_player.voice_pe_cozinha  # entity_id do Voice PE

call_timeout: 30        # segundos até timeout se não atender
max_call_duration: 300  # duração máxima da chamada em segundos
log_level: info
```

## Como funciona uma chamada

### Android → Android

1. Usuário pressiona o botão "Ligar para [dispositivo]" no painel HA ou no app
2. A API cria um stream go2rtc com áudio echo bidirecional (`echo:`)
3. O app Android do destinatário recebe notificação push com botões **Atender** / **Rejeitar**
4. Ao atender, ambos os apps abrem a URL WebRTC do go2rtc e o áudio flui bidirecionalmente

### Android → Voice PE

1. Usuário inicia chamada para um Voice PE
2. O Voice PE anuncia via TTS: *"Chamada de intercom de [nome]. Diga OK para atender."*
3. O stream de áudio do Android é enviado ao Voice PE via RTSP
4. O Voice PE retorna o áudio ambiente via microfone (se configurado)

## Eventos HA disponíveis

| Evento | Dados |
|--------|-------|
| `ha_intercom_call_initiated` | `call_id`, `caller`, `callee`, URLs do stream |
| `ha_intercom_call_answered` | `call_id`, URLs do stream |
| `ha_intercom_call_rejected` | `call_id` |
| `ha_intercom_call_ended` | `call_id` |

## Serviços HA

| Serviço | Parâmetros |
|---------|-----------|
| `ha_intercom.initiate_call` | `caller`, `callee` |
| `ha_intercom.hangup_call` | `call_id` |

## API REST (porta 8099)

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| GET | `/api/devices` | Lista dispositivos configurados |
| POST | `/api/call/initiate` | Inicia chamada `{caller, callee}` |
| POST | `/api/call/answer/<id>` | Atende chamada |
| POST | `/api/call/reject/<id>` | Rejeita chamada |
| POST | `/api/call/hangup/<id>` | Encerra chamada |
| GET | `/api/call/status` | Lista chamadas ativas |
| GET | `/api/call/<id>` | Status de uma chamada |

## Automação de exemplo

```yaml
automation:
  - alias: "Intercom - Ligar para sala ao pressionar botão físico"
    trigger:
      - platform: state
        entity_id: binary_sensor.botao_porta
        to: "on"
    action:
      - service: ha_intercom.initiate_call
        data:
          caller: voice_pe_cozinha
          callee: android_sala
```

## Portas utilizadas

| Porta | Serviço |
|-------|---------|
| 1984 | go2rtc API & Web UI |
| 8554 | RTSP streams |
| 8555 | WebRTC signaling |
| 8099 | Intercom API (ingress) |

## Requisitos

- Home Assistant OS ou Supervised
- Raspberry Pi 4 (aarch64) ou x86_64
- App Android HA Companion instalado nos dispositivos Android
- Voice PE configurado como `media_player` no HA

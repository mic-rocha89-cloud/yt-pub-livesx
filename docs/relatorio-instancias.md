# Relatório: Arquitetura Multi-Instância yt-pub-lives

**Data:** 2026-03-25

## Código Comum (sincronizado via `scripts/sync-instances`)

| Arquivo | Descrição |
|---------|-----------|
| `scheduler.py` | Scheduler principal (cortes, publicação, auto-sync) |
| `dashboard/server.py` | API do dashboard |
| `dashboard/index.html` | Frontend do dashboard |
| `scripts/yt-thumbnail` | Geração de thumbnails |
| `scripts/yt-clip` | Corte de clips |
| `scripts/yt-publish` | Publicação no YouTube |

## Configuração Específica por Instância

### Identificadores

| Parâmetro | Lives1 | Lives2 | Lives3 | Lives4 |
|-----------|--------|--------|--------|--------|
| **INSTANCE_NAME** | yt-pub-lives1 | yt-pub-lives2 | yt-pub-lives3 | yt-pub-lives4 |
| **Porta Dashboard** | 8091 | 8092 | 8093 | 8094 |
| **Config Dir** | ~/.config/gws/ | config/ | config/ | config/ |

### Google Cloud & YouTube

| Parâmetro | Lives1 | Lives2 | Lives3 | Lives4 |
|-----------|--------|--------|--------|--------|
| **GCP_PROJECT** | inema-tds-459114 | certain-perigee-490501-r2 | symbolic-wind-455602-s9 | yt-pub4 |
| **SPREADSHEET_ID** | 1v_89FBEo1RJd... | 19OwctluvWp4w... | 1pDWm9iE4U8et... | 1zLeXzglgf5nN... |
| **YOUTUBE_CHANNEL_ID** | UC2QbQDyPKuHk93dwo5iq3Sw (todos igual) ||||
| **CLIENT_ID** | 77250... | 14388... | 51831... | 57467... |
| **API_KEY (YT)** | AIza...4Wk | AIza...uW0 | AIza...4Wk | AIza...0iY |

### API Keys

| Parâmetro | Lives1 | Lives2 | Lives3 | Lives4 |
|-----------|--------|--------|--------|--------|
| **PIRAMYD_KEY** | sk-860... | sk-150... | sk-574... | sk-150... |
| **KIE_KEY** | (planilha) | e8c9db... | (planilha) | e8c9db... |
| **GEMINI_KEY** | AIzaSyA1x... | - | - | - |

## Dados Específicos (NUNCA sincronizar)

| Item | Descrição |
|------|-----------|
| `lives/` | Vídeos, clips, JSONs processados |
| `config/.env` | Credenciais OAuth, API keys, IDs |
| `config/credentials.enc` | Token OAuth encriptado |
| `config/client_secret.json` | Client OAuth do GCP |
| `dashboard/scheduler_status.json` | Status runtime |
| `.scheduler.lock` | Lock de processo |
| `systemd/*.service` | Portas e paths específicos |

## Serviços Systemd

| Instância | Scheduler Service | Dashboard Service |
|-----------|-------------------|-------------------|
| Lives1 | yt-scheduler1.service | yt-dashboard1.service |
| Lives2 | yt-scheduler.service | yt-dashboard.service |
| Lives3 | yt-scheduler3.service (symlink) | yt-dashboard3.service (symlink) |
| Lives4 | yt-scheduler4.service (symlink) | yt-dashboard4.service (symlink) |

## Como Sincronizar

```bash
# Do lives2, roda o script:
./scripts/sync-instances

# Depois restart todos:
systemctl --user restart yt-scheduler1 yt-dashboard1 yt-scheduler yt-dashboard yt-scheduler3 yt-dashboard3 yt-scheduler4 yt-dashboard4
```

## Problemas Conhecidos (2026-03-25)

- **Lives1**: Token OAuth expirado em ~/.config/gws/credentials.enc — precisa re-autenticar
- **Lives3**: Token OAuth expirado em config/credentials.enc — precisa re-autenticar
- **Lives4**: kie_api_key copiada do lives2 via API — OK

# Instrucoes para Claude Code — yt-pub-livesx

## Regras de comportamento

### Antes de fazer mudancas de codigo
**Sempre mostrar o erro encontrado e a solucao proposta ANTES de aplicar qualquer mudanca.**
Formato:
- **Erro:** descricao clara do que esta errado e onde
- **Solucao:** o que vai ser alterado e por que
- Aguardar confirmacao do usuario antes de editar arquivos

### Nunca sobrescrever .env
Nunca usar Write para reescrever arquivos .env. Usar apenas Edit para alterar linhas especificas.
Motivo: causou outage no lives4 anteriormente.

### Sincronizacao entre instancias
- `yt-pub-livesx` e o template fonte de codigo
- `scripts/sync-instances` sincroniza para as instancias listadas em TARGETS
- NUNCA sincronizar config/, data/, credentials.enc, .env entre instancias
- Apos sync, reiniciar os servicos afetados

### Versao
Atualizar versao (vMAJOR.FEATURES.BUGS) no dashboard/index.html a cada mudanca funcional.

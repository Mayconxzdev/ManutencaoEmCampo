# Decisões técnicas e trade-offs

## SQLite para a demonstração

Escolhi SQLite para que qualquer pessoa consiga executar o projeto sem provisionar banco externo. A aplicação usa uma sessão assíncrona e separa banco transacional de evidências no sistema de arquivos. Para concorrência distribuída ou múltiplas unidades, a evolução natural seria PostgreSQL com migração e estratégia de backup adequada.

## Checklists versionados

Uma manutenção precisa manter o contexto do momento em que ocorreu. Por isso, o plano aponta para uma versão de checklist e a OM guarda essa referência. Atualizar o modelo futuro não altera automaticamente itens de execuções concluídas.

## Histórico antes de bloqueio

O aplicativo não impede uma nova execução porque existe uma anterior. Em vez disso, apresenta data, responsáveis e OM anterior como contexto. Isso evita perda de rastreabilidade e representa melhor um cenário de reinspeção, manutenção corretiva ou demonstração.

## Duas responsabilidades

Quem registra e confere pode ser diferente de quem executa. A separação é intencional: registra tanto a pessoa que operou o tablet quanto a pessoa responsável pelo serviço, sem criar um fluxo de permissões difícil de usar no campo.

## PWA e sincronização

O service worker armazena leituras seguras para melhorar resiliência de consulta. Escritas não são tratadas como “sucesso offline” de forma invisível; esse tipo de ação exige uma fila idempotente e auditável. O projeto inclui estruturas para esse fluxo e deixa claro o limite entre cache e confirmação transacional.

## Dados demonstrativos por código

Dados sintéticos não são um arquivo de banco versionado. O script `backend/scripts/seed_demo.py` cria a base local e impede `--reset` fora das pastas seguras da demonstração (`data/` e `.e2e_data/`). Isso reduz o risco de publicar dados reais e facilita a reprodução do cenário por recrutadores.

# Origem e escopo da versão pública

Este repositório é a versão pública e sanitizada do projeto **Manutenção em Campo**, construída e organizada por **Maycon Ferreira** para apresentação de portfólio.

## O que foi preservado

- o problema de produto: registrar manutenção em campo com rastreabilidade;
- a modelagem de ativos, planos, checklists, OMs, evidências, pessoas e auditoria;
- a separação entre quem confere a execução e quem realiza a manutenção;
- o fluxo de histórico, PDF final, hash e dossiê por ativo/ordem;
- a experiência responsiva para computador, tablet e celular.

## O que foi deliberadamente removido ou substituído

- qualquer pessoa, ativo, fabricante, setor, imagem, data, documento e cenário corporativo real;
- endereços de rede, NAS, credenciais, chaves, bancos, configurações e integrações da origem operacional;
- arquivos de dados, anexos e relatórios gerados fora desta demonstração;
- qualquer alegação de certificação, aprovação de qualidade ou implantação produtiva.

Todos os registros visíveis são gerados pelo script [`backend/scripts/seed_demo.py`](../backend/scripts/seed_demo.py). A base, evidências, PDFs e dossiês ficam apenas em `data/`, caminho ignorado pelo Git e recriável a qualquer momento.

## Limite de representação

Esta cópia mostra decisões técnicas e de UX que eu implementei. Ela não divulga informações de terceiros nem deve ser interpretada como uma aplicação conectada ao ambiente de uma empresa.

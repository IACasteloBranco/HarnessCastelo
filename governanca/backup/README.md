# Backup do PostgreSQL da Governança

Esta configuração protege o banco `governanca_staging` do PostgreSQL 17 da VM `governanca-castelobranco`. O timer cria um `pg_dump` consistente às terças e sextas, às 02h em `America/Bahia`. O primeiro backup bem-sucedido de cada mês é mensal; o primeiro de cada semana ISO é semanal; os demais são recentes. Assim, uma falha ou pausa da VM não elimina a cópia mensal seguinte.

## Estado em 12 de novembro de 2026

| Item | Estado |
| --- | --- |
| Código, timers, política de alertas e instruções | Criados e enviados para a branch `codex/governanca-backup` no commit `9ef0967`; ainda não integrados à `main`. |
| Bucket `cb-governanca-backups-psyched-edge-511720-s5` | Criado no projeto `psyched-edge-511720-s5`, região `southamerica-east1`. |
| Conta `governanca-vm@psyched-edge-511720-s5.iam.gserviceaccount.com` | Criada. Recebeu `roles/dlp.user`, `roles/logging.logWriter`, `roles/monitoring.metricWriter` no projeto e `roles/storage.objectCreator` apenas no bucket. |
| Conta anexada à VM | Pendente. A VM ainda usa a conta Compute com `roles/editor`; a troca exige parar e iniciar a VM. |
| Script e timers instalados na VM | Pendente. Nenhum backup automático está ativo. |
| Coleta de logs e alerta por e-mail | Pendente. A configuração do Ops Agent e o alerta ainda não foram aplicados. |
| Primeiro backup e restauração isolada | Pendente. Ainda não há prova operacional de recuperação. |

O bucket e os papéis da nova conta foram criados manualmente. Não repita os comandos de criação da seção seguinte; use-os como referência para conferir as definições. A VM fez `git fetch` desta branch para obter `lifecycle.json`, mas o código não foi integrado à `main` nem instalado no sistema.

### Próxima sequência

1. Revise e integre `codex/governanca-backup` à `main` pelo GitHub. Atualize a VM com `git pull --ff-only origin main`.
2. Na janela de manutenção, pare a VM e anexe `governanca-vm@psyched-edge-511720-s5.iam.gserviceaccount.com`, conforme os comandos abaixo. Inicie a VM e confirme que a extensão ainda consegue inspecionar texto pelo SDP e que o Ops Agent está ativo.
3. Instale o script e os arquivos systemd pela seção [Instalar na VM](#2-instalar-na-vm). Execute um backup manual antes de habilitar os timers.
4. Acrescente a configuração do Ops Agent sem apagar as configurações existentes e crie o alerta de e-mail pela seção [Logs, alertas e restauração](#3-logs-alertas-e-restauração).
5. Confirme que chegou um objeto ao bucket, que os timers estão ativos e que o alerta encontra `BACKUP_FAILED`.
6. Restaure uma cópia mensal em PostgreSQL 17 isolado e registre o resultado. Só então considere a recuperação validada.

O trabalho ainda não está concluído. O passo que causa indisponibilidade é parar a VM para trocar sua conta de serviço; faça isso numa janela de manutenção. A implantação, os primeiros logs, o primeiro backup e a restauração dependem de comandos executados na GCP e ainda precisam de evidência.

| Cópia | Classe no upload | Exclusão por ciclo de vida |
| --- | --- | --- |
| Recente | Standard | 30 dias |
| Semanal | Nearline | 90 dias |
| Mensal | Coldline | 180 dias |

O bucket mantém qualquer objeto por pelo menos 30 dias, sem travar a política. O ciclo de vida em [`lifecycle.json`](lifecycle.json) aplica os prazos por prefixo. Soft Delete permite recuperar um objeto excluído por mais 7 dias; assim, a remoção física pode ocorrer até 7 dias depois do prazo da tabela. A retenção de backups é separada do expurgo de dados da base ativa. Dois backups por semana deixam até quatro dias de alterações sem ponto de recuperação; se isso não atender à auditoria, será necessário arquivamento contínuo de WAL.

## 1. Identidade e bucket

A VM está no projeto `psyched-edge-511720-s5`, zona `southamerica-east1-c`. Sua conta atual `849637321104-compute@developer.gserviceaccount.com` tem `roles/editor`; **não** use essa conta como identidade final de backup. O papel Editor permite mais do que criar objetos. Antes de trocar a conta anexada, confirme se outros processos da VM usam APIs do Google Cloud. O serviço de Governança usa Sensitive Data Protection e o Ops Agent escreve logs e métricas.

Execute os comandos a seguir no Cloud Shell com uma conta administradora, após clonar este repositório e entrar na sua raiz. Escolha outro nome se o bucket global já existir; nesse caso, atualize também `/etc/governanca-backup.env` na VM. Confirme que `governanca/backup/lifecycle.json` existe antes de criar o bucket.

```bash
PROJECT=psyched-edge-511720-s5
BUCKET=cb-governanca-backups-psyched-edge-511720-s5
VM_SA=governanca-vm@$PROJECT.iam.gserviceaccount.com

gcloud services enable iam.googleapis.com storage.googleapis.com monitoring.googleapis.com \
  logging.googleapis.com --project="$PROJECT"
gcloud iam service-accounts create governanca-vm --project="$PROJECT" --display-name='Governanca VM'
gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$VM_SA" --role=roles/dlp.user
gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$VM_SA" --role=roles/logging.logWriter
gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$VM_SA" --role=roles/monitoring.metricWriter

gcloud storage buckets create "gs://$BUCKET" --project="$PROJECT" --location=southamerica-east1 \
  --default-storage-class=STANDARD --uniform-bucket-level-access --public-access-prevention \
  --soft-delete-duration=7d --retention-period=P30D --lifecycle-file=governanca/backup/lifecycle.json
gcloud storage buckets add-iam-policy-binding "gs://$BUCKET" \
  --member="serviceAccount:$VM_SA" --role=roles/storage.objectCreator
```

Não use `--lock-retention-period`: o travamento é irreversível. Não conceda à conta da VM `roles/storage.objectAdmin`. Para restauração, a TI deve usar outra identidade com acesso de leitura ao bucket.

Para anexar a nova conta, pare a VM numa janela de manutenção e execute no Cloud Shell:

```bash
gcloud compute instances stop governanca-castelobranco --project="$PROJECT" --zone=southamerica-east1-c
gcloud compute instances set-service-account governanca-castelobranco --project="$PROJECT" \
  --zone=southamerica-east1-c --service-account="$VM_SA" --scopes=cloud-platform
gcloud compute instances start governanca-castelobranco --project="$PROJECT" --zone=southamerica-east1-c
```

Antes de ativar o backup, confirme que a inspeção SDP da extensão e o Ops Agent ainda funcionam. Se outro serviço depender de permissões da conta antiga, conceda somente a permissão necessária à nova conta. Não remova o Editor da conta antiga sem conferir outras VMs que possam usá-la.

## 2. Instalar na VM

Depois de integrar esta pasta à `main` e atualizar `~/maximus`, execute:

```bash
cd ~/maximus
sudo install -d -m 0755 /usr/local/libexec
sudo install -m 0755 governanca/backup/backup.py /usr/local/libexec/governanca-backup.py
printf 'GOVERNANCA_BACKUP_BUCKET=%s\nGOVERNANCA_BACKUP_DATABASE=governanca_staging\n' \
  cb-governanca-backups-psyched-edge-511720-s5 | sudo tee /etc/governanca-backup.env
sudo chmod 0644 /etc/governanca-backup.env
sudo install -m 0644 governanca/backup/governanca-backup.service /etc/systemd/system/
sudo install -m 0644 governanca/backup/governanca-backup.timer /etc/systemd/system/
sudo install -m 0644 governanca/backup/governanca-backup-check.service /etc/systemd/system/
sudo install -m 0644 governanca/backup/governanca-backup-check.timer /etc/systemd/system/
sudo systemd-analyze calendar 'Tue,Fri *-*-* 02:00:00 America/Bahia'
sudo systemctl daemon-reload
sudo systemctl start governanca-backup.service
sudo systemctl status governanca-backup.service --no-pager
sudo systemctl enable --now governanca-backup.timer governanca-backup-check.timer
systemctl list-timers 'governanca-backup*'
```

O processo roda como `postgres`, usa autenticação local do PostgreSQL e obtém credenciais temporárias no metadata server da VM. Ele valida a estrutura do arquivo com `pg_restore --list`, envia o arquivo por HTTPS com verificação `Content-MD5` e impede sobrescrita no Cloud Storage. O arquivo temporário local é removido ao terminar. O serviço registra `BACKUP_OK` ou `BACKUP_FAILED` em `/var/log/governanca-backup/backup.log`; a checagem diária às 03h registra falha se não houve upload bem-sucedido por 97 horas.

Confirme o primeiro objeto com uma identidade de manutenção que possa listar o bucket:

```bash
gcloud storage ls 'gs://cb-governanca-backups-psyched-edge-511720-s5/monthly/'
sudo journalctl -u governanca-backup.service -n 30 --no-pager
sudo tail -n 30 /var/log/governanca-backup/backup.log
```

## 3. Logs, alertas e restauração

O Ops Agent está instalado na VM. Acrescente a configuração de [`ops-agent.yaml`](ops-agent.yaml) ao arquivo existente `/etc/google-cloud-ops-agent/config.yaml`; não substitua outras pipelines. Reinicie o agente e confirme que `BACKUP_OK` aparece no Logs Explorer. O timer de checagem registra `BACKUP_FAILED` quando falta uma cópia esperada, desde que a VM esteja ligada.

Para enviar falhas a `ia@castelobrancocontabilidade.com.br`, execute no Cloud Shell a partir da raiz do repositório, depois de confirmar que o agente enviou um registro ao Cloud Logging:

```bash
PROJECT=psyched-edge-511720-s5
CHANNEL=$(gcloud beta monitoring channels create --project="$PROJECT" --type=email \
  --display-name='Governança backup TI' \
  --channel-labels=email_address=ia@castelobrancocontabilidade.com.br --format='value(name)')
gcloud monitoring policies create --project="$PROJECT" \
  --policy-from-file=governanca/backup/alert-policy.json \
  --notification-channels="$CHANNEL"
```

Verifique o e-mail de confirmação do canal, se solicitado. O arquivo de alerta filtra o log `governanca_backup` e a mensagem `BACKUP_FAILED`. Uma checagem na própria VM não detecta a VM parada: configure também uma verificação externa de `https://governanca.castelotecnologia.com.br/healthz` com alerta para esse mesmo canal.

Todo mês, uma identidade de manutenção deve baixar uma cópia mensal em **outra VM ou ambiente PostgreSQL 17 isolado**, recriar a função de banco necessária e executar `pg_restore --exit-on-error --no-owner --no-acl` num banco vazio. Confira tabelas, contagens, permissões e uma consulta da aplicação; registre data, objeto e resultado. `pg_dump` não inclui funções e senhas globais do cluster. Guarde o procedimento e a credencial de criação do papel de banco fora do repositório.

Fontes: [Cloud Storage retention](https://docs.cloud.google.com/storage/docs/bucket-lock), [ciclo de vida](https://docs.cloud.google.com/storage/docs/lifecycle), [classes](https://docs.cloud.google.com/storage/docs/storage-classes), [Ops Agent](https://docs.cloud.google.com/logging/docs/agent/ops-agent/configuration).

#!/usr/bin/env bash
#
# Instalador do Coletor de OLTs num servidor Debian/Ubuntu — no mesmo
# servidor do PWA HOTNET Técnico (e do portal do cliente), sem mexer nos
# arquivos deles. Mesmo jeito do deploy/install.sh do app técnico.
#
# Duas formas de publicar:
#
#   1. DENTRO DO APP TÉCNICO (padrão quando ele está instalado): em
#      https://<domínio do técnico>/olt/. Usa o login do técnico (quem está
#      logado no PWA entra direto) e o certificado dele. O coletor só grava um
#      trecho em /etc/coletor-olt/web/, que o vhost do técnico (versão 1.6.0+)
#      inclui se existir — o técnico continua funcionando igual sem o coletor.
#
#   2. DOMÍNIO PRÓPRIO: vhost e certificado só do coletor, protegido por
#      usuário/senha do servidor web (HTTP Basic).
#
# Nos dois casos o backend é um serviço systemd ouvindo SÓ em 127.0.0.1 — é
# ele quem entra nas OLTs por SSH.
#
# Uso:
#   sudo bash install.sh
#
# Rodar de novo atualiza tudo (git pull, dependências, build, reinicia o
# serviço) sem apagar dados, credenciais ou a chave que cifra as senhas das
# OLTs. Respostas da primeira vez ficam em /etc/coletor-olt/install.conf.

set -euo pipefail

# O script se atualiza com "git pull" no meio da execução. O bash lê o
# arquivo aos poucos, então o corpo todo fica dentro de { ... } para ser lido
# inteiro antes de começar — senão a versão nova poderia ser executada pela
# metade, a partir da posição em que a antiga estava.
{

# --------------------------------------------------------------------------
# Configuração fixa
# --------------------------------------------------------------------------
REPO_URL="${REPO_URL:-https://github.com/jmanoelslva/COLETA-OLT.git}"
INSTALL_DIR="/opt/coletor-olt"
DATA_DIR="/var/lib/coletor-olt"
CONF_DIR="/etc/coletor-olt"
WEB_SNIPPETS="$CONF_DIR/web"
ENV_FILE="$CONF_DIR/coletor.env"
HTPASSWD_FILE="$CONF_DIR/htpasswd"
STATE_FILE="$CONF_DIR/install.conf"
TECNICO_STATE="/etc/hotnet-tecnico/install.conf"
ACME_WEBROOT="/var/www/certbot-acme"
SERVICE_USER="coletor-olt"
SERVICE_NAME="coletor-olt"
WWW_ROOT="/var/www/coletor-olt"
PUBLISH_DIR="$WWW_ROOT/dist"
TEMPLATE_DIR="$INSTALL_DIR/deploy"
DEFAULT_DOMAIN="olt.hotnet.net.br"
DEFAULT_PORT="8090"
DEFAULT_IPS=""
DEFAULT_MODO=""
NODE_MAJOR="24"
PYTHON_BIN="python3"
if [ -f "$STATE_FILE" ]; then
  # shellcheck source=/dev/null
  source "$STATE_FILE"
  DEFAULT_DOMAIN="${DOMINIO_SALVO:-$DEFAULT_DOMAIN}"
  DEFAULT_PORT="${BACKEND_PORT_SALVO:-$DEFAULT_PORT}"
  DEFAULT_IPS="${IPS_LIBERADOS_SALVO:-$DEFAULT_IPS}"
  DEFAULT_MODO="${MODO_SALVO:-}"
fi

# App técnico instalado neste servidor? (lido num subshell, para as variáveis
# dele não se misturarem com as nossas)
TEC_DOMINIO=""; TEC_PORTA=""
if [ -f "$TECNICO_STATE" ]; then
  TEC_DOMINIO="$( ( source "$TECNICO_STATE"; echo "${DOMINIO_SALVO:-}" ) )"
  TEC_PORTA="$( ( source "$TECNICO_STATE"; echo "${BACKEND_PORT_SALVO:-8000}" ) )"
fi

# --------------------------------------------------------------------------
# Saída formatada
# --------------------------------------------------------------------------
if [ -t 1 ]; then
  C_INFO='\033[36m'; C_OK='\033[32m'; C_WARN='\033[33m'; C_ERR='\033[31m'; C_RESET='\033[0m'
else
  C_INFO=''; C_OK=''; C_WARN=''; C_ERR=''; C_RESET=''
fi
info()  { printf '%b[info]%b %s\n'  "$C_INFO" "$C_RESET" "$1"; }
ok()    { printf '%b[ok]%b %s\n'    "$C_OK"   "$C_RESET" "$1"; }
warn()  { printf '%b[atencao]%b %s\n' "$C_WARN" "$C_RESET" "$1"; }
err()   { printf '%b[erro]%b %s\n'  "$C_ERR"  "$C_RESET" "$1" >&2; exit 1; }
trap 'err "Instalação interrompida (linha $LINENO). Nada foi desfeito — corrija o problema acima e rode o script de novo, ele retoma de onde parou."' ERR

# --------------------------------------------------------------------------
# 1. Intro
# --------------------------------------------------------------------------
cat <<'BANNER'
==========================================================================
 Instalador do Coletor de OLTs (HOTNET)
==========================================================================
 Este script vai, nesta ordem:
   1. Instalar dependências (Python 3.11+, Node.js, git, rsync, certbot)
   2. Clonar/atualizar o projeto, criar o venv Python e gerar o build
   3. Criar um usuário de sistema e um serviço systemd para o coletor,
      ouvindo só em 127.0.0.1
   4. Publicar a interface: dentro do app técnico (/olt/, com o login dele)
      ou num domínio próprio (com usuário e senha do servidor web)

 Não mexe nos arquivos do PWA técnico nem do portal do cliente.
==========================================================================
BANNER

# --------------------------------------------------------------------------
# 2. Pré-requisitos básicos
# --------------------------------------------------------------------------
[ "$(id -u)" -eq 0 ] || err "Rode este script como root (ex: sudo bash install.sh)."
command -v apt-get >/dev/null 2>&1 || err "Este instalador é só para Debian/Ubuntu (precisa de apt-get)."

# Atualização: baixa a versão nova antes das perguntas e, se o instalador
# mudou, recomeça por ele — senão as novidades do próprio instalador só
# valeriam na execução seguinte (este processo já leu o script antigo).
if [ -d "$INSTALL_DIR/.git" ] && [ -z "${COLETOR_INSTALADOR_NOVO:-}" ] && command -v git >/dev/null 2>&1; then
  git_pre() { git -c safe.directory="$INSTALL_DIR" -C "$INSTALL_DIR" "$@"; }
  info "Buscando a versão mais recente do coletor..."
  [ -z "$(git_pre status --porcelain --untracked-files=no)" ] || git_pre checkout -- .
  # Rodando o próprio arquivo do repositório (o normal), o "git pull" troca
  # esse arquivo: compara o conteúdo de antes e depois do pull. Rodando uma
  # cópia de outro lugar, compara a cópia com o do repositório.
  ANTES="$(git_pre hash-object deploy/install.sh 2>/dev/null || true)"
  git_pre pull --ff-only --quiet || true
  DEPOIS="$(git_pre hash-object deploy/install.sh 2>/dev/null || true)"
  if [ "$ANTES" != "$DEPOIS" ] || ! cmp -s "$0" "$INSTALL_DIR/deploy/install.sh"; then
    info "O instalador foi atualizado; continuando pela versão nova..."
    trap - ERR
    exec env COLETOR_INSTALADOR_NOVO=1 bash "$INSTALL_DIR/deploy/install.sh" "$@"
  fi
fi

# --------------------------------------------------------------------------
# 3. Perguntas
# --------------------------------------------------------------------------
DOMAIN_REGEX='^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$'

if [ -f "$STATE_FILE" ]; then
  ok "Instalação existente detectada — Enter mantém as respostas anteriores."
fi

echo
echo "Onde publicar o coletor?"
if [ -n "$TEC_DOMINIO" ]; then
  echo "  1) Dentro do app técnico: https://$TEC_DOMINIO/olt/  (usa o login do técnico)"
else
  echo "  1) Dentro do app técnico  (indisponível: o PWA técnico não está instalado aqui)"
fi
echo "  2) Domínio próprio  (vhost e certificado só do coletor, com usuário e senha)"
SUGESTAO_MODO="${DEFAULT_MODO:-$([ -n "$TEC_DOMINIO" ] && echo tecnico || echo dominio)}"
read -rp "Opção (Enter para '$([ "$SUGESTAO_MODO" = tecnico ] && echo 1 || echo 2)'): " resposta
case "${resposta:-}" in
  1) MODO="tecnico" ;;
  2) MODO="dominio" ;;
  "") MODO="$SUGESTAO_MODO" ;;
  *) err "Opção inválida: '$resposta' (use 1 ou 2)." ;;
esac
if [ "$MODO" = "tecnico" ] && [ -z "$TEC_DOMINIO" ]; then
  err "O PWA técnico não está instalado neste servidor ($TECNICO_STATE não existe). Instale-o antes ou use a opção 2."
fi

if [ "$MODO" = "tecnico" ]; then
  DOMINIO="$TEC_DOMINIO"
  ok "Coletor em https://$DOMINIO/olt/ — backend do técnico em 127.0.0.1:$TEC_PORTA."
else
  [ "$DEFAULT_DOMAIN" = "$TEC_DOMINIO" ] && DEFAULT_DOMAIN="olt.hotnet.net.br"
  read -rp "Domínio do coletor (Enter para usar '$DEFAULT_DOMAIN'): " DOMINIO
  DOMINIO="${DOMINIO:-$DEFAULT_DOMAIN}"
  [[ "$DOMINIO" =~ $DOMAIN_REGEX ]] || err "Domínio inválido: '$DOMINIO' (sem http://, sem barra no fim)."

  # Domínio próprio precisa ser só do coletor. Se algum site do servidor (PWA
  # técnico, portal...) já responde por esse nome, para aqui — antes de mexer
  # em qualquer coisa. Os vhosts do coletor levam a marca @coletor-olt@.
  site_alheio_com_dominio() {
    local dom_re="${DOMINIO//./\\.}" arq
    for arq in /etc/nginx/sites-available/* /etc/nginx/sites-enabled/* /etc/nginx/conf.d/*.conf \
               /etc/apache2/sites-available/*.conf /etc/apache2/sites-enabled/*.conf; do
      [ -f "$arq" ] || continue
      grep -Eiq "^[[:space:]]*(server_name|ServerName|ServerAlias)([[:space:]]+[^#]*)?[[:space:]]${dom_re}([[:space:]]|;|\$)" "$arq" || continue
      grep -q "@coletor-olt@" "$arq" && continue
      echo "$arq"
      return 0
    done
    return 1
  }
  if ARQ_ALHEIO="$(site_alheio_com_dominio)"; then
    err "O domínio '$DOMINIO' já é de outro site deste servidor ($ARQ_ALHEIO). Para usar o domínio do app técnico, escolha a opção 1; senão, use um domínio só do coletor (ex: olt.hotnet.net.br)."
  fi
fi

porta_valida() { [[ "$1" =~ ^[0-9]+$ ]] && [ "$1" -ge 1024 ] && [ "$1" -le 65535 ]; }
# Resposta salva inválida (ex.: "1" digitado por engano numa instalação
# anterior) não vira padrão de novo.
porta_valida "$DEFAULT_PORT" || DEFAULT_PORT="8090"
read -rp "Porta local do coletor (Enter para usar '$DEFAULT_PORT'): " BACKEND_PORT
BACKEND_PORT="${BACKEND_PORT:-$DEFAULT_PORT}"
porta_valida "$BACKEND_PORT" || err "Porta inválida: '$BACKEND_PORT'. Use um número de 1024 a 65535 (o normal é 8090)."
[ "$BACKEND_PORT" = "$TEC_PORTA" ] && err "A porta $BACKEND_PORT é a do backend do app técnico. Escolha outra."

echo "IPs/redes (IPv4 ou IPv6) que podem abrir o coletor, separados por espaço (ex: 177.85.130.0/24 2804:abc::/32)."
echo "Vazio = qualquer IP (sempre com login). Também dá para ajustar depois em Configurações."
read -rp "IPs liberados (Enter para usar '${DEFAULT_IPS:-qualquer}'): " IPS_LIBERADOS
IPS_LIBERADOS="${IPS_LIBERADOS:-$DEFAULT_IPS}"
for ip in $IPS_LIBERADOS; do
  [[ "$ip" =~ ^[0-9a-fA-F:.]+(/[0-9]{1,3})?$ ]] || err "IP/rede inválido: '$ip'."
done

# Numa atualização, o próprio serviço ocupa a porta: para antes de checar.
if systemctl list-unit-files "$SERVICE_NAME.service" 2>/dev/null | grep -q "$SERVICE_NAME.service"; then
  info "Parando $SERVICE_NAME temporariamente durante a atualização..."
  systemctl stop "$SERVICE_NAME" || true
fi
if ss -ltn "( sport = :$BACKEND_PORT )" 2>/dev/null | grep -q LISTEN; then
  err "A porta $BACKEND_PORT já está em uso por outro processo. Rode de novo escolhendo outra porta."
fi

mkdir -p "$CONF_DIR"
cat > "$STATE_FILE" <<EOF
MODO_SALVO=$MODO
DOMINIO_SALVO=$DOMINIO
BACKEND_PORT_SALVO=$BACKEND_PORT
IPS_LIBERADOS_SALVO="$IPS_LIBERADOS"
EOF

EMAIL=""
if [ "$MODO" = "dominio" ]; then
  read -rp "E-mail para avisos do Let's Encrypt (opcional, Enter para pular): " EMAIL
  if getent hosts "$DOMINIO" >/dev/null 2>&1; then
    ok "$DOMINIO resolve no DNS."
  else
    warn "$DOMINIO não resolveu no DNS deste servidor agora. Se o registro"
    warn "ainda não propagou, a emissão do certificado abaixo vai falhar."
    read -rp "Continuar mesmo assim? [s/N] " resposta
    [[ "${resposta,,}" == "s" ]] || err "Cancelado — ajuste o DNS e rode de novo."
  fi
fi

# Usa o mesmo servidor web que já está de pé (do app técnico / portal).
apache_rodando() { command -v apache2ctl >/dev/null 2>&1 && systemctl is-active --quiet apache2; }
nginx_rodando()  { command -v nginx      >/dev/null 2>&1 && systemctl is-active --quiet nginx; }
WEBSERVER="${WEBSERVER:-}"
if [ -z "$WEBSERVER" ]; then
  if apache_rodando && nginx_rodando; then
    err "Apache e Nginx estão os dois ativos — rode com WEBSERVER=apache ou WEBSERVER=nginx no ambiente."
  elif apache_rodando; then
    WEBSERVER="apache"
  elif nginx_rodando; then
    WEBSERVER="nginx"
  elif [ "$MODO" = "tecnico" ]; then
    err "Nenhum Apache/Nginx ativo — o app técnico deveria estar servindo $DOMINIO. Confira o servidor web."
  else
    while [ -z "$WEBSERVER" ]; do
      read -rp "Nenhum servidor web ativo ainda. Usar Apache ou Nginx? [apache/nginx] " resposta
      case "${resposta,,}" in
        apache) WEBSERVER="apache" ;;
        nginx)  WEBSERVER="nginx" ;;
        *) warn "Digite 'apache' ou 'nginx'." ;;
      esac
    done
  fi
fi
VHOST="coletor-olt-$DOMINIO"

echo
if [ "$MODO" = "tecnico" ]; then
  info "Publicação:         https://$DOMINIO/olt/ (dentro do app técnico)"
  info "Login:              o mesmo do app técnico"
else
  info "Publicação:         https://$DOMINIO (domínio próprio)"
  info "Login:              usuário e senha do servidor web"
fi
info "Coletor local:      127.0.0.1:$BACKEND_PORT (serviço systemd $SERVICE_NAME)"
info "Dados (SQLite):     $DATA_DIR"
info "IPs liberados:      ${IPS_LIBERADOS:-qualquer}"
info "Servidor web:       $WEBSERVER"
echo

# --------------------------------------------------------------------------
# 4. Dependências base
# --------------------------------------------------------------------------
info "Atualizando lista de pacotes..."
apt-get update -y
info "Instalando dependências base..."
# apache2-utils só traz o comando htpasswd (não instala o servidor Apache).
apt-get install -y curl git rsync sudo ca-certificates gnupg certbot apache2-utils \
  python3 python3-venv python3-pip

# tomllib e a sintaxe usada no coletor pedem Python 3.11+ (Debian 12+/Ubuntu 22.04+).
if ! "$PYTHON_BIN" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
  err "Python $("$PYTHON_BIN" -V 2>&1) é antigo demais — o coletor precisa de 3.11+ (Debian 12 ou mais novo)."
fi

# --------------------------------------------------------------------------
# 5. Clonar/atualizar o projeto
# --------------------------------------------------------------------------
# A pasta pertence ao usuário do serviço; o git (rodando como root) recusa
# repositório de outro dono sem o safe.directory.
git_app() { git -c safe.directory="$INSTALL_DIR" -C "$INSTALL_DIR" "$@"; }
if [ -d "$INSTALL_DIR/.git" ]; then
  info "Projeto já clonado em $INSTALL_DIR, atualizando..."
  if [ -n "$(git_app status --porcelain --untracked-files=no)" ]; then
    warn "Descartando alterações locais em $INSTALL_DIR (artefato de deploy, não deve ser editado à mão)..."
    git_app checkout -- .
  fi
  git_app pull --ff-only
else
  info "Clonando $REPO_URL em $INSTALL_DIR..."
  git clone "$REPO_URL" "$INSTALL_DIR"
fi
VERSAO="$(sed -nE 's/^__version__ = "(.*)"/\1/p' "$INSTALL_DIR/coletor/__init__.py")"
ok "Versão do coletor: ${VERSAO:-desconhecida}"

# --------------------------------------------------------------------------
# 6. Node.js (só para buildar o frontend — nada de Node roda em produção)
# --------------------------------------------------------------------------
instalar_node() {
  if command -v node >/dev/null 2>&1; then
    local major
    major="$(node -v | sed -E 's/^v([0-9]+).*/\1/')"
    if [ "$major" -ge 20 ] 2>/dev/null; then
      ok "Node.js $(node -v) já instalado."
      return
    fi
  fi
  info "Instalando Node.js ${NODE_MAJOR}.x (NodeSource)..."
  curl -fsSL "https://deb.nodesource.com/setup_${NODE_MAJOR}.x" | bash -
  apt-get install -y nodejs
}
instalar_node

# --------------------------------------------------------------------------
# 7. Usuário de sistema dedicado (sem login). O HOME aponta para a pasta de
#    dados, para o pip/npm terem onde escrever cache.
# --------------------------------------------------------------------------
mkdir -p "$DATA_DIR"
if ! id -u "$SERVICE_USER" >/dev/null 2>&1; then
  info "Criando usuário de sistema '$SERVICE_USER'..."
  useradd --system --no-create-home --home-dir "$DATA_DIR" --shell /usr/sbin/nologin "$SERVICE_USER"
else
  ok "Usuário '$SERVICE_USER' já existe."
fi
chown -R "$SERVICE_USER:$SERVICE_USER" "$INSTALL_DIR" "$DATA_DIR"
chmod 700 "$DATA_DIR"

# --------------------------------------------------------------------------
# 8. venv + dependências Python
# --------------------------------------------------------------------------
info "Preparando o ambiente Python..."
if [ ! -d "$INSTALL_DIR/.venv" ]; then
  sudo -H -u "$SERVICE_USER" "$PYTHON_BIN" -m venv "$INSTALL_DIR/.venv"
fi
sudo -H -u "$SERVICE_USER" "$INSTALL_DIR/.venv/bin/pip" install --quiet --upgrade pip
sudo -H -u "$SERVICE_USER" "$INSTALL_DIR/.venv/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"
ok "Dependências Python instaladas."

# --------------------------------------------------------------------------
# 9. Arquivo de ambiente — em /etc, para o "git pull" não apagar ajustes.
#    As linhas ligadas ao modo de publicação são sempre atualizadas.
# --------------------------------------------------------------------------
if [ ! -f "$ENV_FILE" ]; then
  info "Criando $ENV_FILE..."
  cat > "$ENV_FILE" <<EOF
COLETOR_HOST=127.0.0.1
COLETOR_PORTA=$BACKEND_PORT
COLETOR_DADOS=$DATA_DIR
# Inventário opcional: OLTs neste arquivo são importadas na subida (o normal
# é cadastrar pela tela). Se usar, deixe com chmod 600 — tem senha em texto.
COLETOR_OLTS=$CONF_DIR/olts.toml
# Token para integração servidor-a-servidor (deixe vazio se não usar).
COLETOR_API_TOKEN=
COLETOR_LOG=INFO
PYTHONDONTWRITEBYTECODE=1
EOF
else
  ok "$ENV_FILE já existe, mantendo os ajustes manuais."
fi
definir_env() {  # definir_env CHAVE VALOR — troca a linha ou acrescenta
  if grep -q "^$1=" "$ENV_FILE"; then
    sed -i -E "s#^$1=.*#$1=$2#" "$ENV_FILE"
  else
    echo "$1=$2" >> "$ENV_FILE"
  fi
}
definir_env COLETOR_PORTA "$BACKEND_PORT"
definir_env COLETOR_CORS "https://$DOMINIO"
if [ "$MODO" = "tecnico" ]; then
  # Login pelo app técnico: valida o cookie TECSESSION no /auth/me dele.
  definir_env COLETOR_AUTH "tecnico"
  definir_env COLETOR_TECNICO_URL "http://127.0.0.1:$TEC_PORTA"
  definir_env COLETOR_TECNICO_COOKIE "TECSESSION"
  # Token do backend do app técnico para /api/integracao/* (histórico da ONU
  # na tela do cliente). Gerado uma vez; o app técnico usa o mesmo valor.
  if ! grep -q "^COLETOR_SERVICO_TOKEN=." "$ENV_FILE"; then
    definir_env COLETOR_SERVICO_TOKEN "$(head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n')"
    ok "Token de integração com o app técnico gerado em $ENV_FILE."
  fi
else
  definir_env COLETOR_AUTH ""
fi
chown root:"$SERVICE_USER" "$ENV_FILE"
chmod 640 "$ENV_FILE"

# --------------------------------------------------------------------------
# 10. Serviço systemd
# --------------------------------------------------------------------------
info "Configurando o serviço systemd $SERVICE_NAME..."
cat > "/etc/systemd/system/$SERVICE_NAME.service" <<EOF
[Unit]
Description=Coletor de OLTs HOTNET (FastAPI + coleta SSH)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
Group=$SERVICE_USER
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=$ENV_FILE
# Um processo só: o agendador de coleta vive dentro da API.
ExecStart=$INSTALL_DIR/.venv/bin/python -m coletor
Restart=always
RestartSec=5

NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=$DATA_DIR

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME" >/dev/null
systemctl restart "$SERVICE_NAME"
sleep 3
systemctl is-active --quiet "$SERVICE_NAME" \
  || err "O serviço $SERVICE_NAME não subiu — veja 'journalctl -u $SERVICE_NAME -n 50'."
ok "Coletor rodando em 127.0.0.1:$BACKEND_PORT."

# Admin do coletor: só ele cadastra/edita/exclui OLTs e muda as Configurações.
# Pergunta só na primeira vez (depois, troca pela tela ou com o comando abaixo).
ADMIN_CMD="cd $INSTALL_DIR && sudo -u $SERVICE_USER env COLETOR_DADOS=$DATA_DIR .venv/bin/python -m coletor.admin"
if ! ( cd "$INSTALL_DIR" && sudo -H -u "$SERVICE_USER" env COLETOR_DADOS="$DATA_DIR" .venv/bin/python -m coletor.admin --se-vazio ); then
  warn "Admin do coletor não definido. Sem ele ninguém cadastra OLTs. Defina com: $ADMIN_CMD"
fi

# --------------------------------------------------------------------------
# 11. Build do frontend (em /olt/ quando vai dentro do app técnico)
# --------------------------------------------------------------------------
BASE_URL="/"; [ "$MODO" = "tecnico" ] && BASE_URL="/olt/"
info "Gerando o build de produção do frontend (base $BASE_URL)..."
( cd "$INSTALL_DIR/frontend" && sudo -H -u "$SERVICE_USER" npm ci --no-audit --no-fund \
  && sudo -H -u "$SERVICE_USER" env COLETOR_BASE="$BASE_URL" npm run build )
ok "Build gerado em $INSTALL_DIR/frontend/dist"

info "Publicando o build em $PUBLISH_DIR..."
mkdir -p "$PUBLISH_DIR"
rsync -a --delete "$INSTALL_DIR/frontend/dist/" "$PUBLISH_DIR/"
chown -R www-data:www-data "$WWW_ROOT"

# --------------------------------------------------------------------------
# 12. Servidor web
# --------------------------------------------------------------------------
if [ "$WEBSERVER" = "nginx" ]; then
  SERVICE_WEB="nginx"
  dpkg -s nginx >/dev/null 2>&1 || { info "Instalando Nginx..."; apt-get install -y nginx; }
  testar_web() { nginx -t; }
else
  SERVICE_WEB="apache2"
  dpkg -s apache2 >/dev/null 2>&1 || { info "Instalando Apache..."; apt-get install -y apache2; }
  a2enmod proxy proxy_http headers rewrite ssl alias auth_basic authn_file authz_host >/dev/null
  testar_web() { apache2ctl configtest; }
fi
systemctl enable --now "$SERVICE_WEB" >/dev/null

# Lista de IPs liberados no formato de cada servidor web.
if [ -n "$IPS_LIBERADOS" ]; then
  REGRAS_NGINX=""; for ip in $IPS_LIBERADOS; do REGRAS_NGINX+="        allow $ip;\n"; done; REGRAS_NGINX+="        deny all;"
  REGRAS_APACHE="Require ip $IPS_LIBERADOS"
else
  REGRAS_NGINX="        # (sem lista de IPs no servidor web)"
  REGRAS_APACHE="Require all granted"
fi

# Desativa vhosts de domínio próprio do coletor que não são o atual (troca de
# domínio, ou passou a rodar dentro do app técnico). Só os com a marca.
for antigo in /etc/nginx/sites-available/coletor-olt-*.conf /etc/apache2/sites-available/coletor-olt-*.conf; do
  [ -f "$antigo" ] || continue
  nome="$(basename "$antigo" .conf)"
  [ "$MODO" = "dominio" ] && [ "$nome" = "$VHOST" ] && continue
  grep -q "@coletor-olt@" "$antigo" || continue
  warn "Desativando vhost antigo do coletor: $nome"
  rm -f "/etc/nginx/sites-enabled/$nome.conf"
  if command -v a2dissite >/dev/null 2>&1; then a2dissite "$nome" >/dev/null 2>&1 || true; fi
done

if [ "$MODO" = "tecnico" ]; then
  # ------------------------------------------------------------------------
  # 13a. Dentro do app técnico: só o trecho que o vhost dele inclui.
  # ------------------------------------------------------------------------
  mkdir -p "$WEB_SNIPPETS"
  rm -f "$WEB_SNIPPETS"/nginx-*.conf "$WEB_SNIPPETS"/apache-*.conf
  if [ "$WEBSERVER" = "nginx" ]; then
    sed \
      -e "s#/var/www/coletor-olt/dist#$PUBLISH_DIR#g" \
      -e "s/127\.0\.0\.1:8090/127.0.0.1:$BACKEND_PORT/g" \
      -e "s|^ *# @IPS_LIBERADOS@$|$REGRAS_NGINX|" \
      "$TEMPLATE_DIR/olt-subcaminho.nginx.conf.example" > "$WEB_SNIPPETS/nginx-olt.conf"
    VHOST_TEC="$(grep -lE "server_name[^;]*[[:space:]]${TEC_DOMINIO//./\\.}([[:space:]]|;)" /etc/nginx/sites-enabled/* 2>/dev/null | head -1 || true)"
  else
    sed \
      -e "s#/var/www/coletor-olt/dist#$PUBLISH_DIR#g" \
      -e "s/127\.0\.0\.1:8090/127.0.0.1:$BACKEND_PORT/g" \
      -e "/# @IPS_LIBERADOS@/{n;s|.*|    $REGRAS_APACHE|}" \
      "$TEMPLATE_DIR/olt-subcaminho.apache.conf.example" > "$WEB_SNIPPETS/apache-olt.conf"
    VHOST_TEC="$(grep -lE "ServerName[[:space:]]+${TEC_DOMINIO//./\\.}([[:space:]]|\$)" /etc/apache2/sites-enabled/*.conf 2>/dev/null | head -1 || true)"
  fi
  chmod 644 "$WEB_SNIPPETS"/*.conf

  INCLUIDO="nao"
  if [ -n "$VHOST_TEC" ] && grep -q "coletor-olt/web" "$VHOST_TEC"; then
    INCLUIDO="sim"
    testar_web && systemctl reload "$SERVICE_WEB"
    ok "Coletor publicado em https://$DOMINIO/olt/ (incluído pelo vhost do técnico: $VHOST_TEC)."
  else
    warn "O vhost do app técnico ainda não inclui o coletor (${VHOST_TEC:-vhost de $TEC_DOMINIO não encontrado})."
    warn "Atualize o PWA técnico para a versão 1.6.0 ou mais nova e rode o instalador dele:"
    warn "  sudo bash /opt/hotnet-tecnico/deploy/install.sh"
    warn "O coletor já está rodando; /olt/ e o menu \"OLTs\" aparecem depois disso."
  fi
else
  # ------------------------------------------------------------------------
  # 13b. Domínio próprio: senha do site, certificado e vhost do coletor.
  # ------------------------------------------------------------------------
  rm -f "$WEB_SNIPPETS"/nginx-*.conf "$WEB_SNIPPETS"/apache-*.conf  # sai de dentro do técnico, se estava

  if [ ! -s "$HTPASSWD_FILE" ]; then
    echo
    info "Crie o primeiro acesso ao coletor (usuário e senha pedidos pelo navegador)."
    read -rp "Usuário: " USUARIO_WEB
    [[ "$USUARIO_WEB" =~ ^[A-Za-z0-9._-]+$ ]] || err "Usuário inválido (use letras, números, ponto, hífen)."
    htpasswd -B -c "$HTPASSWD_FILE" "$USUARIO_WEB"
  else
    ok "Acessos já cadastrados em $HTPASSWD_FILE (para incluir: htpasswd -B $HTPASSWD_FILE nome)."
  fi
  chown root:www-data "$HTPASSWD_FILE"
  chmod 640 "$HTPASSWD_FILE"

  mkdir -p "$ACME_WEBROOT"
  if [ ! -f "/etc/letsencrypt/live/$DOMINIO/fullchain.pem" ]; then
    info "Preparando vhost provisório na porta 80 para validar o domínio..."
    if [ "$WEBSERVER" = "nginx" ]; then
      cat > "/etc/nginx/sites-available/$VHOST.conf" <<EOF
# @coletor-olt@ vhost provisório do Coletor de OLTs (gerado pelo install.sh)
server {
    listen 80;
    listen [::]:80;
    server_name $DOMINIO;
    location /.well-known/acme-challenge/ { root $ACME_WEBROOT; }
    location / { return 404; }
}
EOF
      ln -sf "/etc/nginx/sites-available/$VHOST.conf" "/etc/nginx/sites-enabled/$VHOST.conf"
    else
      cat > "/etc/apache2/sites-available/$VHOST.conf" <<EOF
# @coletor-olt@ vhost provisório do Coletor de OLTs (gerado pelo install.sh)
<VirtualHost *:80>
    ServerName $DOMINIO
    DocumentRoot $ACME_WEBROOT
    <Directory $ACME_WEBROOT>
        Require all granted
    </Directory>
</VirtualHost>
EOF
      a2ensite "$VHOST" >/dev/null
    fi
    testar_web && systemctl reload "$SERVICE_WEB"
  fi

  if [ -f "/etc/letsencrypt/live/$DOMINIO/fullchain.pem" ]; then
    ok "Já existe certificado para $DOMINIO, pulando emissão."
  else
    info "Emitindo certificado Let's Encrypt para $DOMINIO..."
    certbot_args=(certonly --webroot -w "$ACME_WEBROOT" -d "$DOMINIO"
      --non-interactive --agree-tos --deploy-hook "systemctl reload $SERVICE_WEB")
    if [ -n "$EMAIL" ]; then certbot_args+=(-m "$EMAIL" --no-eff-email); else certbot_args+=(--register-unsafely-without-email); fi
    certbot "${certbot_args[@]}"
    ok "Certificado emitido."
  fi
  systemctl enable --now certbot.timer >/dev/null 2>&1 || true

  info "Publicando o vhost definitivo (HTTPS + senha + proxy para o coletor)..."
  if [ "$WEBSERVER" = "nginx" ]; then
    sed \
      -e "s/olt\.hotnet\.net\.br/$DOMINIO/g" \
      -e "s#/var/www/coletor-olt/dist#$PUBLISH_DIR#g" \
      -e "s#/etc/coletor-olt/htpasswd#$HTPASSWD_FILE#g" \
      -e "s/127\.0\.0\.1:8090/127.0.0.1:$BACKEND_PORT/g" \
      -e "s|^ *# @IPS_LIBERADOS@$|$REGRAS_NGINX|" \
      "$TEMPLATE_DIR/nginx.conf.example" > "/etc/nginx/sites-available/$VHOST.conf"
    ln -sf "/etc/nginx/sites-available/$VHOST.conf" "/etc/nginx/sites-enabled/$VHOST.conf"
  else
    sed \
      -e "s/olt\.hotnet\.net\.br/$DOMINIO/g" \
      -e "s#/var/www/coletor-olt/dist#$PUBLISH_DIR#g" \
      -e "s#/etc/coletor-olt/htpasswd#$HTPASSWD_FILE#g" \
      -e "s/127\.0\.0\.1:8090/127.0.0.1:$BACKEND_PORT/g" \
      -e "/# @IPS_LIBERADOS@/{n;s|.*|            $REGRAS_APACHE|}" \
      "$TEMPLATE_DIR/apache-vhost.conf.example" > "/etc/apache2/sites-available/$VHOST.conf"
    a2ensite "$VHOST" >/dev/null
  fi
  testar_web && systemctl reload "$SERVICE_WEB"
fi

# --------------------------------------------------------------------------
# 14. Resumo
# --------------------------------------------------------------------------
IP_SAIDA="$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || echo 'não identificado')"
echo
ok "Instalação concluída (versão ${VERSAO:-?})."
if [ "$MODO" = "tecnico" ]; then
  ENDERECO="https://$DOMINIO/olt/  (login do app técnico; aparece também no menu \"OLTs\" do PWA)"
  [ "$INCLUIDO" = "sim" ] || ENDERECO="$ENDERECO — ATIVA depois de atualizar o PWA técnico (ver aviso acima)"
else
  ENDERECO="https://$DOMINIO  (pede usuário e senha — htpasswd -B $HTPASSWD_FILE nome)"
fi
cat <<RESUMO

  Coletor:          $ENDERECO
  Serviço:          systemctl status $SERVICE_NAME
  Logs:             journalctl -u $SERVICE_NAME -f
  Dados:            $DATA_DIR  (banco SQLite e chave.key — faça backup dos dois)
  Configuração:     $ENV_FILE
  Admin do coletor: botão "Admin" no alto da tela (cadastro de OLTs e Configurações)
                    trocar usuário/senha pelo servidor: $ADMIN_CMD

  IMPORTANTE: as OLTs precisam aceitar SSH vindo deste servidor.
  IP de saída deste servidor: $IP_SAIDA
  Libere esse IP na ACL/firewall de gerência de cada OLT antes de cadastrar.

  Próximo passo: abra o coletor, entre em "Admin" e cadastre as OLTs em
  "Cadastrar OLT" (use "Testar acesso" antes de salvar).

  Para atualizar depois, rode este mesmo script de novo.

RESUMO

exit 0
}

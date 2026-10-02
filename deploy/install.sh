#!/usr/bin/env bash
#
# Instalador do Coletor de OLTs num servidor Debian/Ubuntu — no mesmo
# servidor do PWA HOTNET Técnico (e do portal do cliente), sem mexer em nada
# deles: outro diretório (/opt/coletor-olt), outro domínio, outro serviço
# systemd, outra porta local. Mesmo jeito do deploy/install.sh do app técnico.
#
# Duas partes:
#   - backend Python (FastAPI + agendador SSH), serviço systemd ouvindo SÓ em
#     127.0.0.1 — ele é quem entra nas OLTs por SSH;
#   - build estático do frontend (Vite), servido pelo Apache/Nginx, que faz
#     reverse proxy de /api/* para o backend local.
#
# A interface do coletor não tem login próprio: o site inteiro fica atrás de
# usuário/senha do servidor web (HTTP Basic) e, opcionalmente, de uma lista
# de IPs liberados. Sem isso, qualquer um na internet veria nomes de clientes
# e poderia cadastrar OLTs/mandar comandos.
#
# Uso:
#   sudo bash install.sh
#
# Rodar de novo atualiza tudo (git pull, dependências, build, reinicia o
# serviço) sem reemitir certificado nem apagar dados, credenciais ou a chave
# que cifra as senhas das OLTs. Respostas da primeira vez ficam salvas em
# /etc/coletor-olt/install.conf (Enter aceita).

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
ENV_FILE="$CONF_DIR/coletor.env"
HTPASSWD_FILE="$CONF_DIR/htpasswd"
STATE_FILE="$CONF_DIR/install.conf"
ACME_WEBROOT="/var/www/certbot-acme"
SERVICE_USER="coletor-olt"
SERVICE_NAME="coletor-olt"
DEFAULT_DOMAIN="olt.hotnet.net.br"
DEFAULT_PORT="8090"
DEFAULT_IPS=""
NODE_MAJOR="24"
PYTHON_BIN="python3"
if [ -f "$STATE_FILE" ]; then
  # shellcheck source=/dev/null
  source "$STATE_FILE"
  DEFAULT_DOMAIN="${DOMINIO_SALVO:-$DEFAULT_DOMAIN}"
  DEFAULT_PORT="${BACKEND_PORT_SALVO:-$DEFAULT_PORT}"
  DEFAULT_IPS="${IPS_LIBERADOS_SALVO:-$DEFAULT_IPS}"
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
   1. Instalar dependências (Python 3.11+, Node.js, git, rsync, certbot,
      Apache OU Nginx) — sem tocar no que já está instalado/rodando
   2. Clonar/atualizar o projeto, criar o venv Python e gerar o build do
      frontend
   3. Criar um usuário de sistema e um serviço systemd para o coletor,
      ouvindo só em 127.0.0.1
   4. Proteger o site com usuário e senha (e, se quiser, por IP)
   5. Publicar o frontend com reverse proxy para o coletor e emitir o
      certificado Let's Encrypt do domínio informado

 Roda em PARALELO com o PWA técnico e o portal do cliente: só adiciona os
 arquivos deste app, não mexe em site/vhost/serviço existente.
==========================================================================
BANNER

# --------------------------------------------------------------------------
# 2. Pré-requisitos básicos
# --------------------------------------------------------------------------
[ "$(id -u)" -eq 0 ] || err "Rode este script como root (ex: sudo bash install.sh)."
command -v apt-get >/dev/null 2>&1 || err "Este instalador é só para Debian/Ubuntu (precisa de apt-get)."

# --------------------------------------------------------------------------
# 3. Perguntas
# --------------------------------------------------------------------------
DOMAIN_REGEX='^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+$'

if [ -f "$STATE_FILE" ]; then
  ok "Instalação existente detectada (domínio '$DEFAULT_DOMAIN', porta '$DEFAULT_PORT') — Enter mantém, ou digite um novo valor."
fi

read -rp "Domínio do coletor (Enter para usar '$DEFAULT_DOMAIN'): " DOMINIO
DOMINIO="${DOMINIO:-$DEFAULT_DOMAIN}"
[[ "$DOMINIO" =~ $DOMAIN_REGEX ]] || err "Domínio inválido: '$DOMINIO' (sem http://, sem barra no fim)."

# O coletor precisa de um domínio só dele. Se algum site do servidor (PWA
# técnico, portal do cliente...) já responde por esse nome, para aqui — antes
# de mexer em qualquer coisa. Os vhosts do coletor levam a marca @coletor-olt@.
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
  err "O domínio '$DOMINIO' já é de outro site deste servidor ($ARQ_ALHEIO). Use um domínio só do coletor (ex: olt.hotnet.net.br) — usar o mesmo sobrescreveria aquele site."
fi

read -rp "Porta local do coletor (Enter para usar '$DEFAULT_PORT'): " BACKEND_PORT
BACKEND_PORT="${BACKEND_PORT:-$DEFAULT_PORT}"
[[ "$BACKEND_PORT" =~ ^[0-9]+$ ]] || err "Porta inválida: '$BACKEND_PORT'."

echo "IPs/redes (IPv4 ou IPv6) que podem abrir o coletor, separados por espaço (ex: 177.85.130.0/24 2804:abc::/32)."
echo "Vazio = qualquer IP, mas sempre com usuário e senha."
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
  err "A porta $BACKEND_PORT já está em uso por outro processo (o backend do app técnico usa a 8000 por padrão). Rode de novo escolhendo outra porta."
fi

mkdir -p "$CONF_DIR"
cat > "$STATE_FILE" <<EOF
DOMINIO_SALVO=$DOMINIO
BACKEND_PORT_SALVO=$BACKEND_PORT
IPS_LIBERADOS_SALVO="$IPS_LIBERADOS"
EOF

read -rp "E-mail para avisos do Let's Encrypt (opcional, Enter para pular): " EMAIL

if getent hosts "$DOMINIO" >/dev/null 2>&1; then
  ok "$DOMINIO resolve no DNS."
else
  warn "$DOMINIO não resolveu no DNS deste servidor agora. Se o registro"
  warn "ainda não propagou, a emissão do certificado abaixo vai falhar."
  read -rp "Continuar mesmo assim? [s/N] " resposta
  [[ "${resposta,,}" == "s" ]] || err "Cancelado — ajuste o DNS e rode de novo."
fi

# Usa o mesmo servidor web que já está de pé (do app técnico / portal).
apache_rodando() { command -v apache2ctl >/dev/null 2>&1 && systemctl is-active --quiet apache2; }
nginx_rodando()  { command -v nginx      >/dev/null 2>&1 && systemctl is-active --quiet nginx; }
WEBSERVER="${WEBSERVER:-}"
if [ -z "$WEBSERVER" ]; then
  if apache_rodando && nginx_rodando; then
    err "Apache e Nginx estão os dois ativos — rode com WEBSERVER=apache ou WEBSERVER=nginx no ambiente."
  elif apache_rodando; then
    WEBSERVER="apache"; ok "Apache já está rodando — vou só adicionar o vhost de $DOMINIO."
  elif nginx_rodando; then
    WEBSERVER="nginx"; ok "Nginx já está rodando — vou só adicionar o vhost de $DOMINIO."
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

# Pasta e vhost próprios, com nome que nunca coincide com os de outros apps
# (o PWA técnico usa /var/www/<domínio> e sites-available/<domínio>.conf).
WWW_ROOT="/var/www/coletor-olt"
VHOST="coletor-olt-$DOMINIO"
PUBLISH_DIR="$WWW_ROOT/dist"
TEMPLATE_DIR="$INSTALL_DIR/deploy"

echo
info "Domínio:            $DOMINIO"
info "Coletor local:      127.0.0.1:$BACKEND_PORT (serviço systemd $SERVICE_NAME)"
info "Dados (SQLite):     $DATA_DIR"
info "IPs liberados:      ${IPS_LIBERADOS:-qualquer (com usuário e senha)}"
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
#    dados, para o pip/paramiko terem onde escrever cache.
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
# Token para o backend do app técnico consultar a API direto em
# 127.0.0.1:$BACKEND_PORT na integração. Deixe vazio enquanto a interface do
# coletor for usada pelo navegador (ela não envia token; quem protege o site
# é o usuário/senha do servidor web).
COLETOR_API_TOKEN=
COLETOR_CORS=https://$DOMINIO
COLETOR_LOG=INFO
PYTHONDONTWRITEBYTECODE=1
EOF
else
  ok "$ENV_FILE já existe, mantendo (edite à mão se precisar)."
  sed -i -E "s/^COLETOR_PORTA=.*/COLETOR_PORTA=$BACKEND_PORT/" "$ENV_FILE"
  sed -i -E "s#^COLETOR_CORS=.*#COLETOR_CORS=https://$DOMINIO#" "$ENV_FILE"
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

# --------------------------------------------------------------------------
# 11. Build do frontend
# --------------------------------------------------------------------------
info "Gerando o build de produção do frontend..."
( cd "$INSTALL_DIR/frontend" && sudo -H -u "$SERVICE_USER" npm ci --no-audit --no-fund \
  && sudo -H -u "$SERVICE_USER" npm run build )
ok "Build gerado em $INSTALL_DIR/frontend/dist"

# --------------------------------------------------------------------------
# 12. Usuário e senha do site (HTTP Basic). Só pergunta na primeira vez;
#     para incluir mais pessoas depois: htpasswd -B $HTPASSWD_FILE nome
# --------------------------------------------------------------------------
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

# --------------------------------------------------------------------------
# 13. Servidor web
# --------------------------------------------------------------------------
if [ "$WEBSERVER" = "nginx" ]; then
  SERVICE_WEB="nginx"
  dpkg -s nginx >/dev/null 2>&1 || { info "Instalando Nginx..."; apt-get install -y nginx; }
else
  SERVICE_WEB="apache2"
  dpkg -s apache2 >/dev/null 2>&1 || { info "Instalando Apache..."; apt-get install -y apache2; }
  a2enmod proxy proxy_http headers rewrite ssl auth_basic authn_file authz_host >/dev/null
fi
systemctl enable --now "$SERVICE_WEB" >/dev/null

# --------------------------------------------------------------------------
# 14. Publica o build
# --------------------------------------------------------------------------
info "Publicando o build em $PUBLISH_DIR..."
mkdir -p "$PUBLISH_DIR"
rsync -a --delete "$INSTALL_DIR/frontend/dist/" "$PUBLISH_DIR/"
chown -R www-data:www-data "$WWW_ROOT"

# --------------------------------------------------------------------------
# 15. Vhost provisório (porta 80, só para o desafio do Let's Encrypt)
# --------------------------------------------------------------------------
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
    nginx -t && systemctl reload nginx
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
    apache2ctl configtest && systemctl reload apache2
  fi
fi

# --------------------------------------------------------------------------
# 16. Certificado Let's Encrypt
# --------------------------------------------------------------------------
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

# --------------------------------------------------------------------------
# 17. Vhost final — a partir do exemplo em deploy/
# --------------------------------------------------------------------------
# Lista de IPs liberados no formato de cada servidor web.
if [ -n "$IPS_LIBERADOS" ]; then
  REGRAS_NGINX=""; for ip in $IPS_LIBERADOS; do REGRAS_NGINX+="        allow $ip;\n"; done; REGRAS_NGINX+="        deny all;"
  REGRAS_APACHE="Require ip $IPS_LIBERADOS"
else
  REGRAS_NGINX="        # (sem lista de IPs: só usuário e senha)"
  REGRAS_APACHE="Require all granted"
fi

# Se o domínio do coletor mudou, desativa o vhost antigo DO COLETOR (só os
# que têm a marca @coletor-olt@ — nunca toca em vhost de outro app).
for antigo in /etc/nginx/sites-available/coletor-olt-*.conf /etc/apache2/sites-available/coletor-olt-*.conf; do
  [ -f "$antigo" ] || continue
  nome="$(basename "$antigo" .conf)"
  [ "$nome" = "$VHOST" ] && continue
  grep -q "@coletor-olt@" "$antigo" || continue
  warn "Desativando vhost antigo do coletor: $nome"
  rm -f "/etc/nginx/sites-enabled/$nome.conf"
  if command -v a2dissite >/dev/null 2>&1; then a2dissite "$nome" >/dev/null 2>&1 || true; fi
done

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
  nginx -t && systemctl reload nginx
else
  sed \
    -e "s/olt\.hotnet\.net\.br/$DOMINIO/g" \
    -e "s#/var/www/coletor-olt/dist#$PUBLISH_DIR#g" \
    -e "s#/etc/coletor-olt/htpasswd#$HTPASSWD_FILE#g" \
    -e "s/127\.0\.0\.1:8090/127.0.0.1:$BACKEND_PORT/g" \
    -e "/# @IPS_LIBERADOS@/{n;s|.*|            $REGRAS_APACHE|}" \
    "$TEMPLATE_DIR/apache-vhost.conf.example" > "/etc/apache2/sites-available/$VHOST.conf"
  a2ensite "$VHOST" >/dev/null
  apache2ctl configtest && systemctl reload apache2
fi

# --------------------------------------------------------------------------
# 18. Resumo
# --------------------------------------------------------------------------
IP_SAIDA="$(curl -fsS --max-time 5 https://api.ipify.org 2>/dev/null || echo 'não identificado')"
echo
ok "Instalação concluída (versão ${VERSAO:-?})."
cat <<RESUMO

  Coletor:          https://$DOMINIO  (pede usuário e senha)
  Serviço:          systemctl status $SERVICE_NAME
  Logs:             journalctl -u $SERVICE_NAME -f
  Dados:            $DATA_DIR  (banco SQLite e chave.key — faça backup dos dois)
  Configuração:     $ENV_FILE
  Acessos ao site:  htpasswd -B $HTPASSWD_FILE nome   (incluir/trocar senha)

  IMPORTANTE: as OLTs precisam aceitar SSH vindo deste servidor.
  IP de saída deste servidor: $IP_SAIDA
  Libere esse IP na ACL/firewall de gerência de cada OLT antes de cadastrar.

  Próximo passo: abra o coletor e cadastre as OLTs em "Cadastrar OLT"
  (use "Testar acesso" antes de salvar).

  Para atualizar depois, rode este mesmo script de novo.

RESUMO

exit 0
}

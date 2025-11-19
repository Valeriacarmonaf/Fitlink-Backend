#!/usr/bin/env zsh
# Crea 3 reporters, obtiene sus tokens y envía 3 reportes contra la VICTIM_ID
API="http://127.0.0.1:8000"
VICTIM_ID="e689565b-b607-4900-b890-b30903a61e3b"
PASSWORD="123456"

# Emails de prueba (cámbialos si ya existen)
REPORTER1="reporter1+dev@example.com"
REPORTER2="reporter2+dev@example.com"
REPORTER3="reporter3+dev@example.com"

for EMAIL in $REPORTER1 $REPORTER2 $REPORTER3; do
  echo "=== Registrar $EMAIL ==="
  curl -sS -X POST "$API/auth/register" \
    -H 'Content-Type: application/json' \
    -d "{\
      \"carnet\": \"0\",\
      \"nombre\": \"${EMAIL%%@*}\",\
      \"biografia\": \"reporter\",\
      \"fechaNacimiento\": \"1990-01-01\",\
      \"ciudad\": \"Ciudad\",\
      \"foto\": \"\",\
      \"email\": \"${EMAIL}\",\
      \"password\": \"${PASSWORD}\"\
    }" | jq
  echo
done

# Esperar 1s para que Supabase procese
sleep 1

TOKENS=()
i=1
for EMAIL in $REPORTER1 $REPORTER2 $REPORTER3; do
  echo "=== Login $EMAIL ==="
  LOGIN_RES=$(curl -sS -X POST "$API/auth/login" \
    -H 'Content-Type: application/json' \
    -d "{\
      \"email\": \"${EMAIL}\",\
      \"password\": \"${PASSWORD}\"\
    }")
  echo "$LOGIN_RES" | jq
  ACCESS_TOKEN=$(echo "$LOGIN_RES" | jq -r '.session.access_token // empty')
  if [[ -z "$ACCESS_TOKEN" ]]; then
    echo "ERROR: no obtuve access_token para $EMAIL"
    exit 1
  fi
  TOKENS+=("$ACCESS_TOKEN")
  i=$((i+1))
  echo
done

# Enviar reportes usando cada token (uno por cada reporter)
idx=1
for TOKEN in "${TOKENS[@]}"; do
  echo "=== Report ${idx} from reporter ${idx} ==="
  curl -sS -X POST "$API/users/$VICTIM_ID/report" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d '{}' | jq
  echo
  idx=$((idx+1))
done

echo "Hecho. Ahora verifica en la BD si el usuario fue bloqueado (is_blocked)."

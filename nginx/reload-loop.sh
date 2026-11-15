#!/bin/sh
# Recarrega o Nginx a cada 6 horas para aplicar certificados renovados pelo certbot.
(while :; do sleep 21600; nginx -s reload 2>/dev/null; done) &

FROM nginx:alpine
COPY frontend/ /usr/share/nginx/html/
# Templated config: the official entrypoint runs envsubst on /etc/nginx/templates/*.template
# at container start and writes the processed file to /etc/nginx/conf.d/default.conf.
# NGINX_ENVSUBST_FILTER (set in compose) limits substitution to our API-key env vars only.
COPY nginx.conf /etc/nginx/templates/default.conf.template

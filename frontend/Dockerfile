# Corpo Sano — build do frontend + Nginx (proxy reverso, HTTPS e arquivos estáticos)
FROM node:22-alpine AS build
WORKDIR /src
COPY package.json package-lock.json* ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
RUN rm -f /etc/nginx/conf.d/default.conf
COPY --from=build /src/dist /usr/share/nginx/html
# A configuração (HTTPS de produção ou HTTP local) é montada pelo docker-compose em /etc/nginx/templates.
EXPOSE 80 443

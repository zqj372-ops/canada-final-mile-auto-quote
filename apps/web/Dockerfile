FROM node:22-alpine AS build

WORKDIR /app/apps/web

COPY apps/web/package*.json ./
RUN npm ci

COPY apps/web ./

ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=${VITE_API_BASE_URL}

RUN npm run build

FROM nginx:1.27-alpine

COPY apps/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/apps/web/dist /usr/share/nginx/html

FROM docker.m.daocloud.io/library/node:22-alpine AS build
ARG AUTOLAVA_GIT_SHA=unknown

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm config set registry https://registry.npmmirror.com && npm ci
COPY . .
RUN npm run build
RUN printf '{"git_sha":"%s"}\n' "$AUTOLAVA_GIT_SHA" > /app/dist/version.json

FROM docker.m.daocloud.io/library/nginx:1.27-alpine
ARG AUTOLAVA_GIT_SHA=unknown
LABEL org.opencontainers.image.revision=$AUTOLAVA_GIT_SHA
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80

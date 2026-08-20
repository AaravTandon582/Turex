FROM node:22-slim AS builder

WORKDIR /build
# Lockfile first, so a source edit does not reinstall every package.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
# Next inlines NEXT_PUBLIC_* at build time, so the API address has to be known here rather
# than at start-up.
ARG NEXT_PUBLIC_API_URL=http://localhost:8000/api/v1
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build


FROM node:22-slim AS runtime

RUN useradd --create-home --uid 10001 atlas
WORKDIR /app

# Next's standalone output carries only the files the server actually needs.
COPY --from=builder --chown=atlas:atlas /build/.next/standalone ./
COPY --from=builder --chown=atlas:atlas /build/.next/static ./.next/static
COPY --from=builder --chown=atlas:atlas /build/public ./public

USER atlas
EXPOSE 3000
ENV PORT=3000 HOSTNAME=0.0.0.0

CMD ["node", "server.js"]

FROM node:25-alpine AS builder

WORKDIR /app

# Copy the lockfile too — `npm ci` installs the exact tree in package-lock.json
# and fails if the lock and package.json disagree. `npm install` (the previous
# command here) ignored the lock entirely because it was never copied in, so
# every image build silently re-resolved to the newest matching versions.
COPY package.json package-lock.json ./
RUN npm ci

COPY . .
RUN npm run build

# Serve with nginx
FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80 443
CMD ["nginx", "-g", "daemon off;"]

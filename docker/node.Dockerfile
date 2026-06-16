# Sandbox image for the node-20-web environment. `npm test` / `npm` are built into the base; SAST is
# the generic Semgrep image. Writable HOME/npm cache for the non-root --user run.
FROM node:20-alpine
ENV HOME=/tmp \
    npm_config_cache=/tmp/.npm

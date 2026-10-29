# Feina — prepend Hermes-bundled Node to PATH (source from bootstrap / feina-onboard).
feina_prepend_hermes_node_path() {
  local d
  if [ -n "${HERMES_HOME:-}" ] && [ -d "$HERMES_HOME/tools" ]; then
    for d in "$HERMES_HOME"/tools/node-*/bin; do
      if [ -d "$d" ]; then
        export PATH="$d:$PATH"
        return 0
      fi
    done
  fi
  if [ -n "${HERMES_HOME:-}" ] && [ -d "$HERMES_HOME/node/bin" ]; then
    export PATH="$HERMES_HOME/node/bin:$PATH"
  fi
}

# Used as $ZDOTDIR/.zshrc for the browser terminal.
# Keep the user's PATH/aliases, but force a glyph-free prompt: Powerline /
# Nerd Font separators otherwise render as hollow tofu boxes in xterm.js.

[[ -r ${HOME}/.zshenv ]] && source ${HOME}/.zshenv
[[ -r ${HOME}/.zprofile ]] && source ${HOME}/.zprofile
[[ -r ${HOME}/.zshrc ]] && source ${HOME}/.zshrc

_v2raypi_web_terminal_prompt() {
  PROMPT='%F{75}%1~%f %# '
  RPROMPT=
}

if typeset -f prompt_powerlevel9k_teardown >/dev/null 2>&1; then
  prompt_powerlevel9k_teardown
fi

autoload -Uz add-zsh-hook 2>/dev/null || true
if typeset -f add-zsh-hook >/dev/null 2>&1; then
  add-zsh-hook -D precmd '_p9k_*' 2>/dev/null || true
  add-zsh-hook -D precmd 'prompt_powerlevel9k_*' 2>/dev/null || true
  add-zsh-hook -D preexec '_p9k_*' 2>/dev/null || true
  add-zsh-hook -D preexec 'prompt_powerlevel9k_*' 2>/dev/null || true
  add-zsh-hook precmd _v2raypi_web_terminal_prompt
fi

_v2raypi_web_terminal_prompt

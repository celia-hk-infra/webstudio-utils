# Loaded by login Bash shells after init.sh links this file at ~/.bash_profile.
_webstudio_profile_dir=$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")
source "$_webstudio_profile_dir/init.sh"
unset _webstudio_profile_dir

# Login Bash shells do not otherwise read ~/.bashrc.
if [[ -f ${HOME%/}/.bashrc ]]; then
    source "${HOME%/}/.bashrc"
fi
